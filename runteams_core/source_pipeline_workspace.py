"""Source pipeline workspace projections and local UI preferences.

Reading/opening this workspace never builds an employee, admits work, resumes a
pipeline or mutates its source. The work ledger remains the board's only truth.
"""
from . import pipeline_references
import copy
import json
import uuid

from . import device_data, source_pipeline_work as work, source_pipeline_control as control
from .contracts import ContractError
from .creator_contracts import canonical, digest, strict_json
from .creator_local_source import current_store
from .creator_source_revisions import Revisions

CONTEXT = 'source_pipeline_workspace'

def allowed_modes(ref):
    from .rented_references import is_rented
    return ['renter'] if is_rented(ref) else ['creator','renter']


def _definition(ref):
    revisions = work.source(ref)
    with revisions.locked():
        revision = revisions._head()
        files = revisions._files(revision)
    project = strict_json(files['project.json'])
    if ref['pipeline_source'] not in project['entrypoints'].get('pipelines', []):
        raise ContractError('流水线源码入口已不存在。')
    asset = strict_json(files[ref['pipeline_source']])
    from .creator_definitions import validate_author
    validate_author('pipeline', asset)
    return revision, asset


def catalog(core):
    core._actor()
    store = current_store(device_data.identity()['cache_scope'])
    rows, errors, after = [], [], None
    while True:
        page = store.list(after)
        for item in page['items']:
            try:
                files = Revisions(store, item['id']).files()
                project = strict_json(files['project.json'])
                for path in project['entrypoints'].get('pipelines', []):
                    ref = pipeline_references.reference(item['id'], path)
                    revision, asset = _definition(ref)
                    rows.append({'reference': ref, 'name': asset['pipeline']['name'], 'revision': revision,
                                 'allowed_modes': ['creator', 'renter']})
            except (ValueError, OSError, ContractError) as exc:
                errors.append({'source_id': item['id'], 'error': str(exc)})
        after = page['next_cursor']
        if after is None:
            break
    from .pipeline_context import current
    rows.extend(current().rented_catalog())
    store.check_scope()
    return {'items': rows, 'errors': errors, 'storage_scope': 'device'}


def _key(ref):
    return 'pipeline-workspace:' + digest(pipeline_references.checked_reference(ref))


def _ui(connection, ref):
    row = connection.execute('SELECT value FROM device_settings WHERE key=?', (_key(ref),)).fetchone()
    value=json.loads(row[0]) if row else {'mode':allowed_modes(ref)[0], 'view':'board', 'revision':0}
    if value['mode'] not in allowed_modes(ref):raise PermissionError('租用资产不能进入创作模式。')
    return value


def preferences(ref, data=None):
    ref = pipeline_references.checked_reference(ref)
    _definition(ref)
    with device_data.connect(readonly=data is None) as connection:
        value = _ui(connection, ref)
        if data is not None:
            fields = set(data) - {'reference', 'expected_revision'}
            if (not fields or fields - {'mode', 'view'} or type(data.get('expected_revision')) is not int or
                    'mode' in fields and data['mode'] not in allowed_modes(ref) or
                    'view' in fields and data['view'] not in ('board', 'conversation')):
                raise ContractError('流水线显示设置无效。')
            patch = {field: data[field] for field in fields}
            if data['expected_revision'] != value['revision']:
                if data['expected_revision'] + 1 == value['revision'] and all(value[k] == v for k, v in patch.items()):
                    return value
                raise ContractError('另一窗口已修改流水线显示设置，请重新读取。')
            value = {**value, **patch, 'revision': value['revision'] + 1}
            connection.execute('INSERT INTO device_settings(key,value) VALUES(?,?) '
                               'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               (_key(ref), canonical(value).decode()))
        return value


def workspace(core, ref, active_ids=()):
    core._actor()
    ref = pipeline_references.checked_reference(ref)
    revision, asset = _definition(ref)
    # Read the applied graph and card facts together. A concurrent control
    # commit invalidates this projection; it cannot mix new columns with old
    # work or omit a card while pause/update is committing.
    for _ in range(2):
        runtime = control.state(core, ref, active_ids)
        with core.repository.connect() as connection:
            saved = control.read(core, ref, connection)
            rows = connection.execute(
                "SELECT w.id,w.state,w.cursor_key,w.snapshot_json,t.title,t.payload_json "
                "FROM workflow_runs w JOIN tasks t ON t.id=w.task_id "
                "WHERE t.trashed_at IS NULL AND json_extract(w.snapshot_json,'$.pipeline_work.reference.source_id')=? "
                "AND json_extract(w.snapshot_json,'$.pipeline_work.reference.pipeline_source')=? ORDER BY w.id",
                (ref['source_id'], ref['pipeline_source'])).fetchall()
        if saved['revision'] == runtime['revision']:
            break
    else:
        raise ContractError('流水线运行状态正在更新，请重新读取。')
    applied = saved['bundle']['asset'] if saved['bundle'] else asset
    workflows = []
    for row in rows:
        snapshot = json.loads(row['snapshot_json'])
        if (snapshot.get('pipeline_work') or {}).get('reference') != ref:
            raise PermissionError('工作不属于这条流水线。')
        workflows.append({'id': row['id'], 'state': row['state'], 'cursor_key': row['cursor_key'],
                          'title': row['title'], 'objective': json.loads(row['payload_json']).get('objective', ''),
                          'summary': (snapshot.get('pipeline_submission') or {}).get('result', {}).get('summary', ''),
                          'pipeline_reference': ref})
    return {'reference': ref, 'name': asset['pipeline']['name'], 'source_revision': revision,
            'pipeline': copy.deepcopy(applied['pipeline']), 'programs_available': bool(applied.get('programs')),
            'runtime': runtime, 'workflows': workflows,
            'ui': preferences(ref), 'allowed_modes': allowed_modes(ref), 'storage_scope': 'device'}


def conversation(core, ref, runtime):
    """One pipeline's own conversation, independent of every position chat."""
    import product_store
    core._actor()
    ref = pipeline_references.checked_reference(ref)
    _, asset = _definition(ref)
    if not isinstance(runtime, dict) or set(runtime) - {'channel_id', 'model', 'reasoning_effort'}:
        raise ContractError('会话运行设置无效。')
    # The source lock serializes competing windows, not worker execution.
    # Recover a chat committed before a lost preference/open response by its
    # immutable binding; there is no second authoritative chat-id index.
    with work.source(ref).locked():
        with device_data.connect(readonly=True) as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM chats WHERE kind='general' AND subject_type='workspace' "
                "AND json_extract(context_json,'$.source_pipeline_workspace.source_id')=? "
                "AND json_extract(context_json,'$.source_pipeline_workspace.pipeline_source')=? ORDER BY id",
                (ref['source_id'], ref['pipeline_source']))]
        for identifier in ids:
            session = product_store.get_chat(identifier)
            if session['context'].get(CONTEXT) == ref:
                return {'session': session, 'storage_scope': 'device'}
        identifier = product_store.create_chat(**runtime, context={'context_type': 'general', CONTEXT: ref})
        with device_data.connect() as connection:
            connection.execute("UPDATE chats SET title=?,title_source='system' WHERE id=?",
                               (asset['pipeline']['name'], identifier))
        return {'session': product_store.get_chat(identifier), 'storage_scope': 'device'}


def creation_choices(core):
    """Actual source and complete signed employee versions, without dispatch."""
    core._actor()
    from .employee_directory import local_entries
    from .source_employee_runtime import describe, units
    from .creator_conversation_assets import extension
    choices, errors, employees = [], [], []
    source_errors = {}
    for entry in local_entries(errors=source_errors):
        try:
            employee = describe(entry['source']['reference'])
            employee.update(origin='创作', version='修订 ' + employee['revision'].removeprefix('r-')[:8],
                dependency={'kind': 'source', 'source_id': employee['reference']['source_id'],
                            'employee_source': employee['reference']['employee_source'], 'revision': employee['revision'],
                            'skills': [unit['key'] for unit in units(employee['asset'])]})
            employees.append(employee)
        except (ValueError, OSError, PermissionError) as exc:
            errors.append({'employee': entry['record']['name'], 'error': str(exc)})
    errors.extend({'employee': key, 'error': str(value)} for key, value in source_errors.items())
    from .pipeline_context import current
    downloaded, failures = current().acquired_employee_catalog(); employees.extend(downloaded); errors.extend(failures)
    for employee in employees:
        for bundle in employee['asset']['skill_bundles']:
            skill = extension(bundle)
            if not skill.get('work'): continue
            choices.append({'reference': employee['reference'], 'revision': employee['revision'],
                'dependency': employee['dependency'], 'version': employee['version'], 'origin': employee['origin'],
                'project_name': employee.get('project_name', ''),
                'employee_name': employee['asset']['employee']['name'], 'skill_key': bundle['package_key'],
                'skill_name': skill.get('display_name') or bundle['package_key']})
    return {'items': choices, 'errors': errors, 'storage_scope': 'device'}


def create(core, data):
    core._actor()
    fields = {'operation_id', 'employee_reference', 'source_revision', 'skill_key', 'name'}
    if set(data) not in (fields, fields | {'dependency'}):
        raise ContractError('请填写流水线名称并选择第一个岗位。')
    try:
        operation = str(uuid.UUID(data['operation_id']))
        if operation != data['operation_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError('请沿原创建操作核对结果。') from None
    if not isinstance(data['name'], str) or not data['name'].strip() or len(data['name']) > 80:
        raise ContractError('请填写不超过 80 字的流水线名称。')
    if 'dependency' in data:
        from .pipeline_context import current
        return current().create_downloaded(core,data)
    from .source_employee_runtime import source
    from .creator_source_import import validate_source
    from .creator_conversation_assets import compile_catalog
    store, revisions = source(data['employee_reference'])
    files = revisions.files_at(data['source_revision'])
    before = validate_source(files)
    employee_source = data['employee_reference']['employee_source']
    catalog = compile_catalog(files, before)
    employee = catalog['employees'].get(employee_source)
    if not employee or data['skill_key'] not in [b['package_key'] for b in employee['skill_bundles']]:
        raise ContractError('第一个岗位必须选择这份工程实际拥有的员工和技能。')
    pipeline_key = 'p-' + uuid.UUID(operation).hex
    path = 'pipelines/' + pipeline_key + '.json'
    if path in files:
        raise ContractError('流水线源码入口已存在，请核对原创建结果。')
    files[path] = canonical({'schema': 'runteams.pipeline-source/3', 'key': pipeline_key,
        'employees': [{'ref': 'employee', 'source': employee_source}],
        'pipeline': {'name': data['name'].strip(), 'positions': [{'key': 'work', 'kind': 'employee',
            'name': employee['employee']['name'], 'employee_ref': 'employee', 'skill_key': data['skill_key']}],
            'edges': [{'from': 'work', 'to': 'done', 'when': 'completed'}],
            'states': [{'key': 'done', 'name': '已完成', 'kind': 'done'}]}})
    project = strict_json(files['project.json'])
    project['entrypoints'].setdefault('pipelines', []).append(path)
    files['project.json'] = canonical(project)
    after = compile_catalog(files, validate_source(files))
    if after['employees'] != catalog['employees']:
        raise ContractError('流水线创建不能修改员工资产。')
    result = revisions.commit(files, data['source_revision'], 'pipeline-create-' + operation)
    return {'reference': pipeline_references.reference(data['employee_reference']['source_id'], path),
            'revision': result['revision'], 'storage_scope': 'device'}


