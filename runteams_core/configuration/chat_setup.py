"""Recipient-side readiness and configuration in an asset's interactive chat."""
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
import uuid

from runteams_core.configuration import asset_onboarding, configuration_schema
from runteams_core.configuration import employee_configuration as configuration
from runteams_core.foundation.identity.work_identity import principal
from runteams_core.storage import device_data, product_store

TOOL = 'runteams_configure_work'
DESCRIPTION = (
    'Inspect device work configuration in the current employee or team chat, then check each team role. '
    'Save only ordinary values explicitly requested and supplied by the user in the current message. '
    'Use the exact scope, revision and definition hash from inspect. Recheck after saving or after the user '
    'returns from the supplied settings link. Send credentials, locations and other authorizations through '
    'the supplied settings link. Never request credentials or absolute paths in chat.'
)
GUIDANCE = (
    '\n\n用户问当前员工、团队或岗位在这台设备能否开工、还缺哪些配置或要求补齐时，用 runteams_configure_work。'
    '先 inspect，团队按团队自身和各员工岗位汇报。用户本轮明确要求保存且已给出普通配置值时才 save，'
    '复制要求保存的原话为 intent，使用查得的配置范围和版本。问进度或询问建议时只读。'
    '凭据、目录、文件、应用连接和资料授权须通过返回的 settings_link 打开原设置，由用户在该入口完成。'
    '不要要求用户在聊天中粘贴凭据、文件路径或连接令牌。用户回到对话后再 inspect，'
    '只按实际状态说明配置结果。配置就绪不代表已派发或运行工作。'
)
INPUT_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['operation'],
    'properties': {
        'operation': {'type': 'string', 'enum': ['inspect', 'save']},
        'target': {'type': 'string', 'enum': ['employee', 'pipeline', 'position']},
        'position': {'type': 'string', 'pattern': '^[a-z][a-z0-9-]{0,79}$'},
        'revision': {'type': 'integer', 'minimum': 0},
        'definition_sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
        'values': {'type': 'object', 'minProperties': 1, 'maxProperties': 128},
        'intent': {'type': 'string', 'minLength': 2, 'maxLength': 4000},
    },
}
_NATIVE_FIELDS = configuration_schema.PRIVATE | {'file_path', 'directory_path'}
TURN_CONTEXT = 'asset_setup_turn'


@dataclass(frozen=True)
class SetupTurn:
    chat_id: int
    message_id: int
    epoch: str
    scope: dict
    kind: str
    reference: dict
    cancel: object


def _eligible(session):
    context = (session or {}).get('context') or {}
    return bool(session and session.get('kind') == 'general'
                and not any(context.get(key) for key in ('employee_work', 'pipeline_work',
                                                        'employee_schedule_operation', 'employee_configuration_snapshot')))


def admission_pending(session, error, *, background=False):
    """An unpinned interactive chat can guide setup when work admission fails."""
    return (not background and isinstance(error, configuration.ConfigurationInvalid)
            and _eligible(session) and session.get('subject_type') == 'employee')


def _binding(chat_id):
    if not chat_id or not device_data.personal() or not product_store.device_chat(chat_id):
        return None
    session = product_store.get_chat(chat_id, include_messages=False)
    if not session or (session.get('context') or {}).get('employee_configuration_snapshot'):
        return None
    from runteams_core.automation.chat_automation_tool import _binding as asset_chat
    return asset_chat(chat_id)


def bind_turn(context, message_id, cancel):
    if (type(message_id) is not int or message_id < 1 or
            getattr(cancel, 'background_employee_work', False) or getattr(cancel, 'background_chat_turn', False)):
        return False
    chat_id = context.get('chat_id')
    try:
        scope = device_data.identity()
        binding = _binding(chat_id) if context.get('actor_id') == principal(scope) else None
        if binding is None:
            return False
        kind, reference = binding
        epoch = device_data.epoch(chat_id)
    except (ValueError, OSError, PermissionError, sqlite3.Error):
        return False
    context[TURN_CONTEXT] = SetupTurn(chat_id, message_id, epoch, scope, kind, reference, cancel)
    return True


def _current_message(turn):
    if turn.cancel is not None and turn.cancel.is_set():
        raise PermissionError('本轮对话已结束。')
    device_data.check(turn.scope)
    if _binding(turn.chat_id) != (turn.kind, turn.reference) or device_data.epoch(turn.chat_id) != turn.epoch:
        raise PermissionError('对话的配置范围已变化，请重新打开。')
    message = product_store.get_chat_message(turn.chat_id, turn.message_id)
    if not message or message['role'] != 'user':
        raise PermissionError('本轮用户消息已变化，请重新发送。')
    return message['text']


def _targets(turn):
    if turn.kind == 'employee':
        return [{'target': 'employee'}]
    from runteams_core.pipelines.pipeline_context import current
    from runteams_core.pipelines.pipeline_dependency_contracts import selector
    _, asset = current().definition(turn.reference)
    members = {member['ref']: selector(member) for member in asset['employees']}
    return [{'target': 'pipeline'}, *(
        {'target': 'position', 'position': row['key'], 'label': row['name'],
         'employee_source': members[row['employee_ref']]}
        for row in asset['pipeline']['positions'] if row['kind'] == 'employee'
    )]


def _store(turn, target):
    if target['target'] == 'employee':
        session = product_store.get_chat(turn.chat_id, include_messages=False)
        if session.get('kind') == 'employee_design':
            return configuration.for_source(turn.reference)
        return nullcontext(configuration.for_chat(turn.chat_id))
    from runteams_core.pipelines.pipeline_context import current
    context = current()
    if target['target'] == 'pipeline':
        return context.own_configuration_store(turn.reference)
    return context.configuration_store(turn.reference, target['employee_source'])


def _view(chat_id, target, stored):
    definition, states = stored['definition'], stored['states']
    settings_link = f'runteams://configuration/{chat_id}'
    if target.get('position'):
        settings_link += '?' + urlencode({'position': target['position']})
    fields = []
    ready = stored['ready']
    for field in configuration_schema.fields(definition):
        key, kind = field['key'], field['type']
        row = {name: field[name] for name in ('key', 'label', 'type', 'required', 'description', 'options', 'constraints')
               if name in field}
        state = states[key]
        if state == 'configured' and kind in ('file_path', 'directory_path'):
            path = Path(stored['values'][key])
            try:
                available = path.is_file() if kind == 'file_path' else path.is_dir()
            except OSError:
                available = False
            if not available:
                state = 'unavailable'
                ready = ready and not field.get('required')
        row.update(state=state, input='settings' if kind in _NATIVE_FIELDS else 'chat')
        if kind not in _NATIVE_FIELDS and key in stored['values']:
            row['value'] = stored['values'][key]
        fields.append(row)
    target_info = {key: target[key] for key in ('target', 'position', 'label') if key in target}
    if stored.get('employee', {}).get('name'):
        target_info['employee_name'] = stored['employee']['name']
    return {**target_info, 'ready': ready, 'revision': stored['revision'],
            'definition_sha256': stored['definition_sha256'], 'settings_link': settings_link,
            'fields': fields, 'guide': asset_onboarding.remaining_steps(definition, states)}


def _execute(turn, arguments, message):
    from jsonschema import Draft202012Validator
    from runteams_core.authoring.creator_contracts import canonical
    if (not isinstance(arguments, dict) or len(canonical(arguments)) > 96 * 1024
            or not Draft202012Validator(INPUT_SCHEMA).is_valid(arguments)):
        raise ValueError('开工配置操作无效。')
    action = arguments['operation']
    target, position = arguments.get('target'), arguments.get('position')
    fields = {'operation'} | ({'target'} if target is not None else set()) | ({'position'} if position is not None else set())
    if (target == 'position') != (position is not None):
        raise ValueError('请选择要配置的岗位。')
    if action == 'save':
        expected = fields | {'revision', 'definition_sha256', 'values', 'intent'}
        intent = (arguments.get('intent') or '').strip()
        if set(arguments) != expected or target is None or len(intent) < 2 or intent not in message:
            raise ValueError('请根据本轮用户的明确要求提交原话和要保存的配置。')
    elif set(arguments) != fields:
        raise ValueError('检查配置只接受配置范围。')
    targets = [row for row in _targets(turn)
               if target is None or (row['target'] == target and row.get('position') == position)]
    if not targets:
        raise PermissionError('配置范围不属于当前员工或智能体团队。')

    results = []
    for row in targets:
        with _store(turn, row) as store:
            if action == 'save':
                key = row.get('employee_source') or row['target']
                operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                              f'runteams-chat-setup:{turn.epoch}:{turn.message_id}:{key}'))
                saved = store.save(operation_id=operation_id, expected_revision=arguments['revision'],
                                   definition_sha256=arguments['definition_sha256'],
                                   values=arguments['values'], patch_values=True)
            else:
                saved = store.read()
            results.append(_view(turn.chat_id, row, saved))
    return {'status': 'saved' if action == 'save' else 'checked',
            'ready': all(row['ready'] for row in results), 'targets': results}


def call(arguments, context):
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError, AgentToolResult
    turn = context.get(TURN_CONTEXT)
    if (not isinstance(turn, SetupTurn) or context.get('chat_id') != turn.chat_id
            or context.get('actor_id') != principal(turn.scope)):
        raise AgentToolError('请在当前员工或团队的直属对话中检查配置。')
    try:
        result = _execute(turn, arguments, _current_message(turn))
    except configuration.ConfigurationInvalid as exc:
        return AgentToolResult('work_configuration', str(exc), {'status': 'invalid', 'errors': exc.errors})
    except (ValueError, PermissionError) as exc:
        raise AgentToolError(str(exc)) from exc
    except (OSError, sqlite3.Error) as exc:
        raise AgentToolError('暂时无法读取或保存配置，请检查原配置后重试。') from exc
    return AgentToolResult('work_configuration', '已返回工作配置状态。', result)
