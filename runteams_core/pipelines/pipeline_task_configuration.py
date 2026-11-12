"""Task setup and task/project-scoped host credentials.

Saving never sends work or changes its cursor. Past runs retain their input;
subsequent visits consume the task's values through normal visibility rules.
"""
import copy
import json
import uuid
from contextlib import contextmanager, ExitStack

from jsonschema import Draft202012Validator
from runteams_core.authoring.creator_contracts import canonical, digest
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_references
from runteams_core.storage.repository import utc_now


def fields(frozen):
    return [copy.deepcopy(p) for p in frozen['pipeline_work']['asset']['pipeline'].get('parameters', [])
            if p.get('source') == 'user' and p.get('display') == 'setup' and p.get('type') != 'secret']


def configuration_fields(frozen):
    declarations = fields(frozen)
    if not declarations:return declarations
    from runteams_core.pipelines.source_pipeline_workspace import _definition
    _, asset, _ = _definition(frozen['pipeline_work']['reference'])
    current = {p['key']:p for p in asset['pipeline'].get('parameters', [])
               if p.get('source') == 'user' and p.get('display') == 'setup'}
    for field in declarations:
        latest = current.get(field['key'], {})
        if latest.get('type') != field['type']:continue
        for key in ('group', 'note', 'required', 'required_when', 'constraints'):
            if (key == 'note' or key not in field) and key in latest:field[key] = copy.deepcopy(latest[key])
    # Adding a host credential does not change frozen business inputs or runs.
    # Its project identity must already belong to this task's declared setup.
    keys = {p['key'] for p in declarations}
    for field in current.values():
        if field['type'] == 'secret' and field.get('scope_parameter') in keys:
            declarations.append(copy.deepcopy(field))
    return declarations


def credential_field_key(key):
    return 'credential-' + digest(key)[:32]


def credential_store(row, frozen, declarations):
    """Reuse the shared configuration/vault implementation with a unique owner.

    No plaintext or credential record is ever put in pipeline_input, task
    snapshots, browser drafts or exports. Project changes select a distinct
    store and vault slot, so neither another task nor a global key can fall back.
    """
    from runteams_core.configuration.employee_configuration import ConfigurationStore
    from runteams_core.storage import device_data
    from runteams_core.foundation.identity.work_identity import schedule_binding
    reference = frozen['pipeline_work']['reference']
    parameters = frozen.get('pipeline_input', {}).get('parameters', {})
    secret_fields = [p for p in declarations if p['type'] == 'secret' and p.get('scope_parameter')]
    identities = {p['key']: parameters.get(p['scope_parameter'], '') for p in secret_fields}
    owner = {'reference': reference, 'workflow_id': row['id'], 'owner': schedule_binding(device_data.identity()),
             'projects': identities}
    definition = {'schema':'runteams.employee-configuration/1', 'groups':[]}
    if secret_fields:
        definition['groups'] = [{'key':'task-credentials','label':'任务凭据','fields':[
            {'key':credential_field_key(p['key']), 'label':p['label'], 'type':'secret', 'required':False,
             'binding':{'provider':'native_credential','key':'TASK_' + digest({**owner,'field':p['key']})}}
            for p in secret_fields]}]
    store = ConfigurationStore(reference, definition, digest(definition))
    store.key = 'pipeline-task-credentials:' + digest(owner)
    store.receipt_prefix = store.key + ':receipt:'
    return store, identities


def credential_view(row, frozen, declarations):
    if not any(p['type'] == 'secret' for p in declarations):return {}
    store, identities = credential_store(row, frozen, declarations)
    data = store.read()
    view = {}
    for key, identity in identities.items():
        field = credential_field_key(key)
        details = data['credential_fields'][field]
        view[key] = {'state':data['states'][field], 'selected':field in data['bindings'],
                     'available':details['available'], 'scope_value':identity, 'ready':bool(identity),
                     'revision':data['revision']}
        if 'mask_length' in details:
            view[key]['mask_length'] = details['mask_length']
    return view


def chat_credentials(chat):
    from runteams_core.storage import product_store
    from runteams_core.work.device_work_services import current
    context = (product_store.get_chat(chat, include_messages=False) or {}).get('context') or {}
    if not context.get('pipeline_work'):return None
    core = current()
    with core.repository.read_snapshot() as connection:
        row = connection.execute('SELECT * FROM workflow_runs WHERE id=?',
            (context.get('employee_work', {}).get('workflow_id'),)).fetchone()
        if not row:raise PermissionError('任务凭据所属工作不存在。')
        frozen = json.loads(row['snapshot_json'])
    if frozen.get('work_chat_id') != chat or frozen.get('pipeline_work') != context['pipeline_work']:
        raise PermissionError('任务凭据所属工作已变化。')
    declarations = configuration_fields(frozen)
    return row, frozen, declarations


def credential_scopes(chat, required):
    """Host-supplied non-secret project identity for a credential's consumer."""
    bound = chat_credentials(chat)
    if not bound:return {}
    _, frozen, declarations = bound
    position = frozen['pipeline_work']['position_key']
    parameters = frozen.get('pipeline_input', {}).get('parameters', {})
    return {p['key']:parameters.get(p['scope_parameter'], '') for p in declarations
            if p['type']=='secret' and p['key'] in required and p.get('scope_parameter')
            and (not p.get('visible_to') or position in p['visible_to'])}


@contextmanager
def credential_lease(chat, required, check, shared):
    """Resolve task-declared keys first, with no shared-credential fallback."""
    from runteams_core.configuration.credentials.configuration_credentials import lease
    from runteams_core.employees.mcp.employee_mcp import MCPBoundCredentials
    bound = chat_credentials(chat)
    keys = {p['key'] for p in bound[2] if p['type']=='secret'} if bound else set()
    selected = set(required) & keys
    with ExitStack() as stack:
        values = {}; checks = []
        if selected:
            row, frozen, declarations = bound
            position = frozen['pipeline_work']['position_key']
            for field in declarations:
                if field['key'] in selected and field.get('visible_to') and position not in field['visible_to']:
                    raise PermissionError('当前岗位未获准使用此任务凭据。')
            store, identities = credential_store(row, frozen, declarations)
            if any(not identities[k] for k in selected):raise PermissionError('请先填写本任务的项目配置和凭据。')
            snapshot = store.snapshot()
            native = {f['key']:f['binding']['key'] for g in store.definition['groups'] for f in g['fields']}
            mapping = {key:native[credential_field_key(key)] for key in selected}
            def task_check():
                check()
                now = chat_credentials(chat)
                current_store, _ = credential_store(*now)
                if current_store.key != store.key or current_store.snapshot() != snapshot:
                    raise PermissionError('本任务的项目或凭据已变化。')
            bound_values = stack.enter_context(lease(store.definition, snapshot, [mapping[k] for k in selected], task_check))
            values.update({k:bound_values.values[mapping[k]] for k in selected}); checks.append(bound_values.check)
        remaining = set(required) - selected
        if remaining:
            definition, snapshot = shared()
            bound_values = stack.enter_context(lease(definition, snapshot, remaining, check))
            values.update(bound_values.values); checks.append(bound_values.check)
        yield MCPBoundCredentials(values, lambda: all(test() for test in checks))


class ConfigurationInvalid(ContractError):
    def __init__(self, errors):
        self.fields = errors
        super().__init__('请检查标出的配置项。')


def schema(declarations):
    properties = {}
    for field in declarations:
        kind = field['type']
        if kind == 'secret':continue
        value = {'type': 'boolean'} if kind == 'checkbox' else {'type': 'number'} if kind == 'number' else (
            {'type': 'array', 'items': {'type': 'string', 'enum': field.get('options', [])}, 'uniqueItems': True}
            if kind in ('multiselect', 'checklist') else {'type': 'string', 'maxLength': 8192})
        if kind == 'select':value['enum'] = field.get('options', [])
        limits = field.get('constraints', {})
        if kind in ('text', 'textarea'):
            for source, target in (('min_length','minLength'), ('max_length','maxLength'), ('pattern','pattern')):
                if source in limits:value[target] = limits[source]
            if field.get('required'):value['minLength'] = max(1, value.get('minLength', 0))
        if kind == 'number':
            for source, target in (('min','minimum'), ('max','maximum')):
                if source in limits:value[target] = limits[source]
        properties[field['key']] = value
    return {'type': 'object', 'properties': properties, 'additionalProperties': False,
            'required': [field['key'] for field in declarations if field['type'] != 'secret' and field.get('required')]}


def validate_values(declarations, values):
    if not isinstance(values, dict) or len(canonical(values)) > 65536:
        raise ContractError('任务配置格式无效。')
    errors = {}
    for error in Draft202012Validator(schema(declarations)).iter_errors(values):
        key = str(next(iter(error.path), '_form'))
        if error.validator == 'required':
            for field in declarations:
                if field.get('required') and field['key'] not in values:errors[field['key']] = '请填写此项。'
            continue
        errors[key] = {'pattern':'填写格式不符合要求，请查看字段说明。',
                      'maxLength':'内容超过允许长度。', 'minLength':'内容少于要求长度。',
                      'minimum':'数值小于允许的最小值。', 'maximum':'数值超过允许的最大值。',
                      'enum':'请从当前选项中选择。'}.get(error.validator, '填写内容不符合字段要求。')
    for field in declarations:
        if field['type'] == 'secret':continue
        value = values.get(field['key'])
        if field.get('required') and (isinstance(value,str) and not value.strip() or isinstance(value,list) and not value):
            errors[field['key']] = '请填写此项。'
        limits = field.get('constraints', {})
        if field['type'] == 'number' and type(value) in (int,float) and 'step' in limits:
            from decimal import Decimal
            quotient = (Decimal(str(value)) - Decimal(str(limits.get('min',0)))) / Decimal(str(limits['step']))
            if quotient != quotient.to_integral_value():errors[field['key']] = '数值不符合允许步长。'
    if errors:raise ConfigurationInvalid(errors)
    return copy.deepcopy(values)


def readonly_reason(row, frozen, active_ids=()):
    from runteams_core.pipelines.source_pipeline_control import TERMINAL
    if row['state'] in TERMINAL:return 'finished'
    if row['id'] in active_ids or row['state'] == 'running' or (frozen.get('pipeline_execution') or {}).get('active'):
        return 'running'
    if frozen.get('pipeline_unresolved') or frozen.get('pipeline_recovery_pending') or frozen.get('pipeline_result_correction'):
        return 'unresolved'
    return ''


def project(row, frozen, active_ids=(), declarations=None):
    declarations = configuration_fields(frozen) if declarations is None else declarations
    if not declarations:return None
    supplied = frozen.get('pipeline_input', {}).get('parameters', {})
    values = {p['key']: copy.deepcopy(supplied.get(p['key'], p.get('default')))
              for p in declarations if p['type'] != 'secret' and (p['key'] in supplied or 'default' in p)}
    reason = readonly_reason(row, frozen, active_ids)
    credentials = credential_view(row, frozen, declarations)
    revision = {'snapshot': frozen, 'fields': declarations}
    if credentials:
        revision['credentials'] = {key:{k:v for k,v in info.items() if k!='mask_length'} for key,info in credentials.items()}
    return {'fields': declarations, 'values': values, 'credential_fields':credentials, 'revision': digest(revision),
            'editable': not reason, 'readonly_reason': reason}


def request(core, data, active_ids=()):
    from runteams_core.pipelines import source_pipeline_flow as flow
    core._actor()
    base = {'reference', 'workflow_id', 'action'}
    action = data.get('action') if isinstance(data, dict) else None
    extra = {'read': set(), 'save': {'operation_id', 'expected_revision', 'values'},
             'credential': {'expected_revision', 'field', 'value'},
             'reveal-credential': {'expected_revision', 'field'},
             'receipt': {'operation_id', 'expected_revision', 'values'}}
    if action not in extra or set(data) != base | extra[action] or type(data['workflow_id']) is not int:
        raise ContractError('任务配置请求无效。')
    ref = pipeline_references.checked_reference(data['reference'])
    if action in ('save', 'receipt'):
        try:
            if str(uuid.UUID(data['operation_id'])) != data['operation_id']:raise ValueError()
        except (ValueError, TypeError, AttributeError):raise ContractError('任务配置保存编号无效。') from None
        if not isinstance(data['expected_revision'], str) or len(data['expected_revision']) != 64:
            raise ContractError('请重新读取任务配置。')
        if not isinstance(data['values'], dict) or len(canonical(data['values'])) > 65536:
            raise ContractError('任务配置格式无效。')
    with core.repository.connect() as connection:
        if action in ('save', 'credential'):connection.execute('BEGIN IMMEDIATE')
        row = flow._row(connection, data['workflow_id'])
        frozen = json.loads(row['snapshot_json'])
        if (frozen.get('pipeline_work') or {}).get('reference') != ref:
            raise PermissionError('工作不属于这条流水线。')
        declarations = configuration_fields(frozen)
        if action == 'read':return {'configuration': project(row, frozen, active_ids, declarations)}
        if action in ('credential', 'reveal-credential'):
            core.repository.storage.assert_executable(row['id'])
            current = project(row, frozen, active_ids, declarations)
            if not current or not current['editable']:
                raise ContractError('当前任务不能修改凭据。' if action=='credential' else '当前任务不能显示凭据。')
            if data['expected_revision'] != current['revision']:
                return {'error':'任务或配置已更新，请重新读取后核对。','code':'task_configuration_conflict'},409
            field = next((p for p in declarations if p['key']==data['field'] and p['type']=='secret'),None)
            if not field:raise ContractError('本任务未声明此凭据。')
            store, identities = credential_store(row, frozen, declarations)
            if not identities[field['key']]:raise ConfigurationInvalid({field['key']:'请先填写并保存对应的项目 ID。'})
            key=credential_field_key(field['key'])
            if action == 'reveal-credential':
                return store.reveal_credential(field=key, definition_sha256=store.definition_sha256)
            store.credential(field=key, definition_sha256=store.definition_sha256, value=data['value'])
            return {'configuration':project(row, frozen, active_ids, declarations)}
        stream = 'pipeline-task-configuration:' + data['operation_id']
        fingerprint = digest({**data, 'action': 'save', 'reference': ref})
        event = connection.execute("SELECT data_json FROM events WHERE stream=? AND type='workflow.configuration_saved' LIMIT 1", (stream,)).fetchone()
        if event:
            receipt = json.loads(event[0])
            if receipt['request_sha256'] != fingerprint:raise ContractError('原保存编号已用于其他任务配置。')
            return {'status': 'committed', 'configuration': project(row, frozen, active_ids, declarations)}
        if action == 'receipt':return {'status': 'unknown'}
        core.repository.storage.assert_executable(row['id'])
        current = project(row, frozen, active_ids, declarations)
        if not current:raise ContractError('这项任务没有声明任务配置。')
        if not current['editable']:raise ContractError('当前任务正在执行、等待结果核对或已经结束，不能修改配置。')
        if data['expected_revision'] != current['revision']:
            return {'error': '任务或配置已更新，请重新读取后核对。', 'code': 'task_configuration_conflict'}, 409
        values = validate_values(current['fields'], data['values'])
        keys = {p['key'] for p in current['fields']}
        parameters = frozen['pipeline_input'].setdefault('parameters', {})
        for key in keys:parameters.pop(key, None)
        parameters.update(values)
        # An already admitted run keeps its exact task payload and input_json.
        # Only unsent stages may receive a freshly projected payload.
        payload = None
        position = next((p for p in frozen['pipeline_work']['asset']['pipeline']['positions'] if p['key'] == row['cursor_key']), None)
        if not frozen.get('send_admitted') and position and position['kind'] == 'employee':
            role = {'context': frozen['pipeline_work'], 'package': frozen['package']}
            try:payload = flow.payload_for(core, connection, frozen, role)
            except ContractError:
                if row['state'] not in ('blocked', 'needs_human', 'paused'):raise
        encoded = canonical(frozen).decode();now = utc_now()
        connection.execute('UPDATE workflow_runs SET snapshot_json=?,updated_at=? WHERE id=?', (encoded, now, row['id']))
        connection.execute('UPDATE tasks SET pipeline_snapshot_json=?,updated_at=? WHERE id=?', (encoded, now, row['task_id']))
        if payload is not None:
            connection.execute('UPDATE tasks SET payload_json=? WHERE id=?', (canonical(payload).decode(), row['task_id']))
        core.repository.event(stream, 'workflow.configuration_saved',
            {'request_sha256': fingerprint, 'workflow_id': row['id'], 'fields': sorted(keys),
             'previous_revision': current['revision'], 'revision': project(row, frozen, active_ids, declarations)['revision']}, connection=connection)
        return {'status': 'committed', 'configuration': project(row, frozen, active_ids, declarations)}
