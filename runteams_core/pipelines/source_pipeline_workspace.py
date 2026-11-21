"""Source pipeline workspace projections and local UI preferences.

Reading/opening this workspace never builds an employee, admits work, resumes a
pipeline or mutates its source. The work ledger remains the board's only truth.
"""
from runteams_core.conversations.page_paths import asset_key, short_ids
from runteams_core.pipelines import pipeline_references
import copy
import json
import uuid

from runteams_core.storage import device_data
from runteams_core.pipelines import source_pipeline_work as work, source_pipeline_control as control
from runteams_core.foundation.contracts import ContractError, PIPELINE_STATUS_FIRST
from runteams_core.authoring.creator_contracts import canonical, digest, strict_json
from runteams_core.authoring.source.creator_local_source import current_store
from runteams_core.authoring.source.creator_source_revisions import Revisions

CONTEXT = 'source_pipeline_workspace'

def allowed_modes(ref):
    from runteams_core.assets.rented_references import is_rented
    return ['renter'] if is_rented(ref) else ['creator']


def _definition(ref):
    revisions = work.source(ref)
    with revisions.locked():
        revision = revisions._head()
        files = revisions._files(revision)
    project = strict_json(files['project.json'])
    if ref['pipeline_source'] not in project['entrypoints'].get('pipelines', []):
        raise ContractError('智能体团队源码入口已不存在。')
    return revision, _pipeline_definition(files, ref['pipeline_source']), files


def _pipeline_definition(files, path):
    asset = strict_json(files[path])
    from runteams_core.authoring.creator_definitions import validate_author
    validate_author('pipeline', asset)
    return asset


def catalog(core):
    from runteams_core.pipelines.pipeline_avatars import image_src, source_fields

    core._actor()
    store = current_store(device_data.identity()['cache_scope'])
    from runteams_core.pipelines import source_pipeline_trash
    removed = {(item['reference']['source_id'], item['reference']['pipeline_source']) for item in source_pipeline_trash.catalog(core)}
    rows, errors, after = [], [], None
    while True:
        page = store.list(after)
        for item in page['items']:
            try:
                revisions = Revisions(store, item['id'])
                with revisions.locked():
                    revision = revisions._head()
                    files = revisions._files(revision)
                project = strict_json(files['project.json'])
                for path in project['entrypoints'].get('pipelines', []):
                    if (item['id'], path) in removed:
                        continue
                    ref = pipeline_references.reference(item['id'], path)
                    asset = _pipeline_definition(files, path)
                    avatar_src = image_src(source_fields(asset, files))
                    rows.append({'reference': ref, 'name': asset['pipeline']['name'], 'revision': revision,
                                 'allowed_modes': allowed_modes(ref), **({'avatar_src': avatar_src} if avatar_src else {})})
            except (ValueError, OSError, ContractError) as exc:
                errors.append({'source_id': item['id'], 'error': str(exc)})
        after = page['next_cursor']
        if after is None:
            break
    from runteams_core.pipelines.pipeline_context import current
    rows.extend(current().rented_catalog())
    ids = short_ids(asset_key(row['reference']) for row in rows)
    for row in rows:
        row['page_id'] = ids[asset_key(row['reference'])]
    store.check_scope()
    return {'items': rows, 'errors': errors, 'storage_scope': 'device'}


def _key(ref):
    return 'pipeline-workspace:' + digest(pipeline_references.checked_reference(ref))


def _ui(connection, ref):
    row = connection.execute('SELECT value FROM device_settings WHERE key=?', (_key(ref),)).fetchone()
    value = json.loads(row[0]) if row else {'view': 'board', 'revision': 0}
    # Older workspaces may have stored a manual mode. Ownership now determines it.
    return {**value, 'mode': allowed_modes(ref)[0]}


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
                raise ContractError('智能体团队显示设置无效。')
            patch = {field: data[field] for field in fields}
            if data['expected_revision'] != value['revision']:
                if data['expected_revision'] + 1 == value['revision'] and all(value[k] == v for k, v in patch.items()):
                    return value
                raise ContractError('另一窗口已修改智能体团队显示设置，请重新读取。')
            value = {**value, **patch, 'revision': value['revision'] + 1}
            connection.execute('INSERT INTO device_settings(key,value) VALUES(?,?) '
                               'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               (_key(ref), canonical(value).decode()))
        return value


def workspace(core, ref, active_ids=(), *, background_revision=None):
    from runteams_core.assets.workspace_background import display_fields
    from runteams_core.pipelines.pipeline_card_actions import capabilities
    from runteams_core.pipelines.source_pipeline_flow import launch_failure, retry_mode
    core._actor()
    ref = pipeline_references.checked_reference(ref)
    revision, asset, files = _definition(ref)
    from runteams_core.pipelines.pipeline_avatars import image_src, source_fields
    icon = source_fields(asset, files)
    # The runtime and its cards share one snapshot without waiting for a work writer.
    with core.repository.storage.connect(readonly=True) as connection:
        runtime = control.state(core, ref, active_ids, connection=connection)
        rows = connection.execute(
            "SELECT w.id,w.state,w.cursor_key,w.snapshot_json,t.title,t.payload_json,t.trashed_at "
            "FROM workflow_runs w JOIN tasks t ON t.id=w.task_id "
            "WHERE t.trashed_at IS NULL AND json_extract(w.snapshot_json,'$.pipeline_work.reference.source_id')=? "
            "AND json_extract(w.snapshot_json,'$.pipeline_work.reference.pipeline_source')=? ORDER BY w.id",
            (ref['source_id'], ref['pipeline_source'])).fetchall()
        positions = {item['key'] for item in runtime['positions'] if item['kind']=='employee'}
        active = set(runtime['active_workflow_ids'])
        workflows = []
        for row in rows:
            snapshot = json.loads(row['snapshot_json'])
            if (snapshot.get('pipeline_work') or {}).get('reference') != ref:
                raise PermissionError('工作不属于这个智能体团队。')
            error = launch_failure(connection, row, snapshot)
            workflows.append({'id': row['id'], 'state': 'blocked' if error else row['state'], 'cursor_key': row['cursor_key'],
                              'title': row['title'], 'objective': json.loads(row['payload_json']).get('objective', ''),
                              'summary': error or (snapshot.get('pipeline_submission') or {}).get('result', {}).get('summary', ''),
                              'pipeline_reference': ref, 'work_chat_id': snapshot.get('work_chat_id'),
                              'card_actions': capabilities(row, snapshot, active_ids),
                              'retry_mode': retry_mode(row['state'],row['cursor_key'],snapshot,positions,
                                                       active=row['id'] in active, launch_error=error)})
    return {'reference': ref, 'name': asset['pipeline']['name'], 'description': asset.get('description', ''), 'source_revision': revision,
            **({'avatar': icon['avatar'], 'avatar_src': image_src(icon)} if icon else {}),
            **(display_fields(asset, files=files) if revision != background_revision else {}),
            'pipeline': copy.deepcopy(asset['pipeline']), 'programs_available': bool(asset.get('programs')),
            'runtime': runtime, 'workflows': workflows,
            'ui': preferences(ref), 'allowed_modes': allowed_modes(ref), 'storage_scope': 'device'}


def conversation(core, ref, runtime, *, discussion_id=None):
    """Open the board conversation or one separately requested team discussion."""
    from runteams_core.storage import product_store
    core._actor()
    ref = pipeline_references.checked_reference(ref)
    _, asset, _ = _definition(ref)
    if not isinstance(runtime, dict) or set(runtime) - {'channel_id', 'model', 'reasoning_effort'}:
        raise ContractError('会话运行设置无效。')
    if discussion_id is not None:
        try:
            discussion_id = str(uuid.UUID(discussion_id))
        except (ValueError, AttributeError, TypeError):
            raise ContractError('新对话编号无效。') from None
    # The source lock serializes competing windows, not worker execution.
    # Recover a chat committed before a lost preference/open response by its
    # immutable binding; there is no second authoritative chat-id index.
    with work.source(ref).locked():
        with device_data.connect(readonly=True) as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM chats WHERE kind='general' AND subject_type='workspace' "
                "AND json_extract(context_json,'$.source_pipeline_workspace.source_id')=? "
                "AND json_extract(context_json,'$.source_pipeline_workspace.pipeline_source')=? "
                "AND json_extract(context_json,'$.source_pipeline_discussion') IS ? ORDER BY created_at,id",
                (ref['source_id'], ref['pipeline_source'], discussion_id))]
        for identifier in ids:
            session = product_store.get_chat(identifier)
            if session['context'].get(CONTEXT) == ref:
                return {'session': session, 'storage_scope': 'device'}
        context = {'context_type': 'general', CONTEXT: ref}
        if discussion_id:
            context['source_pipeline_discussion'] = discussion_id
        identifier = product_store.create_chat(**runtime, context=context)
        if discussion_id:
            return {'session': product_store.get_chat(identifier), 'storage_scope': 'device'}
        with device_data.connect() as connection:
            connection.execute("UPDATE chats SET title=?,title_source='system' WHERE id=?",
                               (asset['pipeline']['name'], identifier))
        return {'session': product_store.get_chat(identifier), 'storage_scope': 'device'}


def _skill_fields(schema):
    required = set(schema.get('required', []))
    fields = []
    for key, definition in schema.get('properties', {}).items():
        definition = definition if isinstance(definition, dict) else {}
        field_type = definition.get('type')
        fields.append({'key': key, 'title': definition.get('title', ''),
            'description': definition.get('description', ''), 'required': key in required,
            'types': [field_type] if isinstance(field_type, str) else field_type or []})
    return fields


def skill_description(bundle):
    from runteams_core.authoring.creator_conversation_assets import extension

    skill = extension(bundle)
    contract = skill.get('work')
    if not contract:
        return None
    route = contract.get('output_schema', {}).get('properties', {}).get('route', {})
    routes = route.get('enum', [route.get('const')]) if isinstance(route, dict) else []
    from runteams_core.assets.skills.skill_metadata import bundle_environment
    tools = bundle_environment(bundle)
    return {**({'environment_tools': tools} if tools else {}), 'key': bundle['package_key'], 'name': skill.get('display_name') or contract['name'],
            'inputs': _skill_fields(contract.get('input_schema', {})),
            'outputs': _skill_fields(contract.get('output_schema', {})),
            'routes': list(dict.fromkeys(value for value in routes if isinstance(value, str) and value.strip()))}


def creation_choices(core):
    """Actual source and complete signed employee versions, without dispatch."""
    core._actor()
    from runteams_core.employees.employee_directory import local_entries
    from runteams_core.employees.source_employee_runtime import describe, units
    choices, errors, employees = [], [], []
    source_errors = {}
    catalog_cache = {}
    for entry in local_entries(errors=source_errors):
        try:
            employee = describe(entry['source']['reference'], catalog_cache=catalog_cache)
            employee.update(origin='创作', version='修订 ' + employee['revision'].removeprefix('r-')[:8],
                dependency={'kind': 'source', 'source_id': employee['reference']['source_id'],
                            'employee_source': employee['reference']['employee_source'], 'revision': employee['revision'],
                            'skills': [unit['key'] for unit in units(employee['asset'])]})
            employees.append(employee)
        except (ValueError, OSError, PermissionError) as exc:
            errors.append({'employee': entry['record']['name'], 'error': str(exc)})
    errors.extend({'employee': key, 'error': str(value)} for key, value in source_errors.items())
    from runteams_core.pipelines.pipeline_context import current
    downloaded, failures = current().acquired_employee_catalog(); employees.extend(downloaded); errors.extend(failures)
    for employee in employees:
        for bundle in employee['asset']['skill_bundles']:
            skill = skill_description(bundle)
            if not skill: continue
            choices.append({'reference': employee['reference'], 'revision': employee['revision'],
                'dependency': employee['dependency'], 'version': employee['version'], 'origin': employee['origin'],
                'project_name': employee.get('project_name', ''),
                'employee_name': employee['asset']['employee']['name'], 'skill_key': bundle['package_key'],
                'skill_name': skill['name'], 'skill': skill})
    return {'items': choices, 'errors': errors, 'storage_scope': 'device'}


def new_pipeline_graph(name, employee_name, skill_key, end_name=None):
    return {'name': name.strip(), 'routing_policy': PIPELINE_STATUS_FIRST,
        'positions': [{'key': 'work', 'kind': 'employee', 'name': employee_name,
            'employee_ref': 'employee', 'skill_key': skill_key}],
        'edges': [{'from': 'work', 'to': 'done', 'when': 'completed'}],
        'states': [{'key': 'done', 'name': '已完成' if end_name is None else end_name.strip(), 'kind': 'done'}]}


def create(core, data):
    core._actor()
    fields = {'operation_id', 'employee_reference', 'source_revision', 'skill_key', 'name'}
    if not fields <= data.keys() <= fields | {'dependency', 'end_name'}:
        raise ContractError('请填写智能体团队名称并选择第一个岗位。')
    try:
        operation = str(uuid.UUID(data['operation_id']))
        if operation != data['operation_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError('请沿原创建操作核对结果。') from None
    if not isinstance(data['name'], str) or not data['name'].strip() or len(data['name']) > 80:
        raise ContractError('请填写不超过 80 字的智能体团队名称。')
    if 'end_name' in data:
        end_name = data['end_name']
        if not isinstance(end_name, str) or not end_name.strip() or len(end_name.strip()) > 160:
            raise ContractError('请填写不超过 160 字的结束位置名称。')
    if 'dependency' in data:
        from runteams_core.pipelines.pipeline_context import current
        return current().create_downloaded(core,data)
    from runteams_core.employees.source_employee_runtime import source
    from runteams_core.authoring.source.creator_source_import import validate_source
    from runteams_core.authoring.creator_conversation_assets import compile_catalog
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
        raise ContractError('智能体团队源码入口已存在，请核对原创建结果。')
    operation_key = 'pipeline-create-' + operation
    graph = new_pipeline_graph(data['name'], employee['employee']['name'], data['skill_key'], data.get('end_name'))
    reserved = revisions.operation_files(operation_key)
    if reserved and path in reserved and 'routing_policy' not in strict_json(reserved[path])['pipeline']:
        # Replaying a pre-upgrade operation must produce the same source hash.
        graph.pop('routing_policy')
    files[path] = canonical({'schema': 'runteams.pipeline-source/3', 'key': pipeline_key,
        'employees': [{'ref': 'employee', 'source': employee_source}],
        'pipeline': graph})
    project = strict_json(files['project.json'])
    project['entrypoints'].setdefault('pipelines', []).append(path)
    files['project.json'] = canonical(project)
    after = compile_catalog(files, validate_source(files))
    if after['employees'] != catalog['employees']:
        raise ContractError('智能体团队创建不能修改员工资产。')
    result = revisions.commit(files, data['source_revision'], operation_key)
    return {'reference': pipeline_references.reference(data['employee_reference']['source_id'], path),
            'revision': result['revision'], 'storage_scope': 'device'}


