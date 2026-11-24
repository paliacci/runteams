"""Inspect or change future model selection for a role of the bound pipeline."""
import sqlite3

from runteams_core.configuration import chat_setup
from runteams_core.foundation.contracts import ContractError
from runteams_core.foundation.identity.work_identity import principal

TOOL = 'runteams_pipeline_position_models'
DESCRIPTION = (
    'Inspect model channels, effective models and effort for employee positions in the current pipeline. '
    'Without position_key, inspect all employee positions. Inspect a specific position to get its available '
    'channels and model values. For set or reset target one position only and copy '
    'its source_revision and selection from inspect into source_revision and expected_selection. For set use '
    'an exact channel_id, model value, and supported effort from that position. Reset removes its local '
    'override. Quote a clear instruction from the current user as intent. Changes apply to newly admitted '
    'work and do not alter already admitted work, other positions, or device-wide defaults.'
)
GUIDANCE = (
    '\n\n用户问当前团队各岗位使用哪个模型时，用 runteams_pipeline_position_models 的 inspect，'
    '按实际回执区分有效模型、推理档位和继承来源。设置前按 position_key 单独 inspect 目标岗位，核对可用选项。'
    '恢复默认前也先核对岗位和当前选择，复制用户明确指令原文为 intent。'
    '只根据该岗位可选渠道、模型和档位提交 set，用户未指定且有多个可选项时先问清。明确要求恢复默认时用 reset，'
    '检查回执确认恢复后的实际模型。每次变更只作用于目标岗位的新工作，已受理工作继续使用原模型快照。'
)

_SELECTION = {
    'type': 'object', 'additionalProperties': False,
    'required': ['channel_id', 'model', 'effort'],
    'properties': {
        'channel_id': {'type': 'integer', 'minimum': 1},
        'model': {'type': 'string', 'minLength': 1, 'maxLength': 160},
        'effort': {'type': 'string', 'maxLength': 80},
    },
}
INPUT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['operation'], 'properties': {
    'operation': {'type': 'string', 'enum': ['inspect', 'set', 'reset']},
    'position_key': {'type': 'string', 'pattern': '^[a-z][a-z0-9-]{0,79}$'},
    'source_revision': {'type': 'string', 'pattern': '^(?:r-)?[a-f0-9]{64}$'},
    'expected_selection': {'anyOf': [_SELECTION, {'type': 'null'}]},
    'selection': _SELECTION,
    'intent': {'type': 'string', 'minLength': 2, 'maxLength': 4000},
}}
_CONTEXT_KEY = 'pipeline_position_model_turn'


def bind_turn(context, message_id, cancel):
    from runteams_core.automation.chat_automation_tool import _binding as asset_chat

    if (type(message_id) is not int or message_id < 1
            or getattr(cancel, 'background_employee_work', False)
            or getattr(cancel, 'background_chat_turn', False)):
        return False
    from runteams_core.storage import device_data

    chat_id = context.get('chat_id')
    try:
        scope = device_data.identity()
        binding = asset_chat(chat_id) if context.get('actor_id') == principal(scope) else None
        if not binding or binding[0] != 'pipeline':
            return False
        epoch = device_data.epoch(chat_id)
    except (ValueError, OSError, PermissionError, sqlite3.Error):
        return False
    context[_CONTEXT_KEY] = chat_setup.SetupTurn(chat_id, message_id, epoch, scope, binding[0], binding[1], cancel)
    return True


def _execute(core, pipeline_context, turn, arguments, message):
    from jsonschema import Draft202012Validator

    if not Draft202012Validator(INPUT_SCHEMA).is_valid(arguments):
        raise ContractError('岗位模型请求无效。')
    operation, key = arguments['operation'], arguments.get('position_key')
    change = None
    if operation == 'inspect':
        if arguments.keys() - {'operation', 'position_key'}:
            raise ContractError('检查只接受岗位。')
    else:
        required = {'operation', 'position_key', 'source_revision', 'expected_selection', 'intent'}
        if operation == 'set':
            required.add('selection')
        intent = (arguments.get('intent') or '').strip()
        if set(arguments) != required or len(intent) < 2 or intent not in message:
            raise ContractError('请根据本轮用户的明确要求提交原话和岗位选择。')
        change = {name: arguments[name] for name in ('source_revision', 'expected_selection')}
        change['selection'] = arguments.get('selection')
    _, asset = pipeline_context.definition(turn.reference)
    positions = [position for position in asset['pipeline']['positions']
                 if position['kind'] == 'employee' and (key is None or position['key'] == key)]
    if key is not None and not positions:
        raise ContractError('当前团队没有这个员工岗位。')
    result = []
    for position in positions:
        configuration = pipeline_context.position_runtime(core, turn.reference, position['key'], change)
        if key is None:
            configuration = {name: value for name, value in configuration.items() if name != 'channels'}
        result.append({'position_key': position['key'], 'position_name': position['name'], **configuration})
    return {'status': {'inspect': 'checked', 'set': 'saved', 'reset': 'reset'}[operation],
            'applies_to': 'new_work_only', 'positions': result}


def call(arguments, context):
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError, AgentToolResult
    from runteams_core.pipelines.pipeline_context import current as pipeline_context
    from runteams_core.work.device_work_services import current as work_core

    turn = context.get(_CONTEXT_KEY)
    if (not isinstance(turn, chat_setup.SetupTurn) or turn.kind != 'pipeline' or context.get('chat_id') != turn.chat_id
            or context.get('actor_id') != principal(turn.scope)):
        raise AgentToolError('请在当前团队的直属对话中检查岗位模型。')
    try:
        message = chat_setup._current_message(turn)
        result = _execute(work_core(), pipeline_context(), turn, arguments, message)
    except (ValueError, PermissionError) as exc:
        raise AgentToolError(str(exc)) from exc
    except (OSError, sqlite3.Error) as exc:
        raise AgentToolError('暂时无法读取或保存岗位模型，请重新核对原设置。') from exc
    return AgentToolResult('pipeline_position_models', '已返回岗位模型设置。', result)
