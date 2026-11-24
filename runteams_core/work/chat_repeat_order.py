"""Create a separate manual order from one completed order in the owning chat."""
import copy
from hashlib import sha256
import json
import logging
import sqlite3
import uuid

from runteams_core.assets import local_references
from runteams_core.authoring.creator_contracts import canonical, digest
from runteams_core.configuration import chat_setup
from runteams_core.employees.employee_work_contracts import owns_direct_work
from runteams_core.foundation.contracts import ContractError
from runteams_core.foundation.identity.work_identity import principal
from runteams_core.storage import device_data, product_store
from runteams_core.work import task_inputs

TOOL = 'runteams_repeat_manual_order'
DESCRIPTION = (
    'Find completed manual orders owned by this employee or team. Use list by title, or inspect an exact '
    'workflow ID to see the original inputs, attachments, and version. Use create only when the current user '
    'requests a separate new order. Pass only explicitly requested title, objective, and parameter changes. '
    'Select keep, replace, or omit for attachments. For keep or replace, original_attachment_ids selects the exact '
    'original files to retain. For replace, use only attachment IDs actually uploaded '
    'in this message. Create presents its own native confirmation before committing and returns the order receipt. '
    'Use receipt to recover a previously confirmed order in this user turn. Automation executions and continuation '
    'of an existing order use their own tools.'
)
GUIDANCE = (
    '\n\n用户要求照已完成的手动工单另开新单时，用 runteams_repeat_manual_order。'
    '按名称或时间范围查找，查看原目标、参数和附件；有多个符合条件的工单时，请用户选择。'
    '本轮明确要求开新单才调用 create，填写本轮要求的变更和附件选择，沿用其余有效任务输入。'
    '工具会显示原工单、拟派发的内容和附件并等待用户点击确认。已有回执直接核对编号和关联。'
    '只询问、原工单继续办理、计划运行重跑分别走已有入口。'
)
INPUT_SCHEMA = {'type': 'object', 'required': ['operation'], 'additionalProperties': False, 'properties': {
    'operation': {'enum': ['list', 'inspect', 'create', 'receipt']},
    'workflow_id': {'type': 'integer', 'minimum': 1, 'maximum': 2**53 - 1},
    'query': {'type': 'string', 'maxLength': 200},
    'completed_from': {'type': 'string', 'format': 'date'},
    'completed_through': {'type': 'string', 'format': 'date'},
    'intent': {'type': 'string', 'minLength': 2, 'maxLength': 4000},
    'changes': {'type': 'object', 'additionalProperties': False, 'properties': {
        'title': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'objective': {'type': 'string', 'minLength': 1, 'maxLength': 8000},
        'parameters': {'type': 'object'},
    }},
    'attachment_mode': {'enum': ['keep', 'replace', 'omit']},
    'original_attachment_ids': {'type': 'array', 'maxItems': 50, 'uniqueItems': True,
                                'items': {'type': 'string', 'minLength': 1, 'maxLength': 70}},
    'attachment_ids': {'type': 'array', 'minItems': 1, 'maxItems': 10, 'uniqueItems': True,
                       'items': {'type': 'string', 'minLength': 1, 'maxLength': 40}},
    'asset_bindings': {'type': 'object', 'propertyNames': {'pattern': '^[a-z][a-z0-9-]{0,79}$'},
                       'additionalProperties': {'type': 'string'}},
}}
_SELECT = (
    'SELECT w.id,w.task_id,w.state,w.snapshot_json,w.created_at,w.updated_at,t.title,t.pipeline_id,'
    't.employee_id,t.start_column_key,t.payload_json FROM workflow_runs w JOIN tasks t ON t.id=w.task_id '
    "WHERE t.trashed_at IS NULL AND w.state='completed'"
)
_RECEIPT = 'work.repeat_order_admitted'
_PROMPTED = 'work.repeat_order_confirmation_requested'
_DECLINED = 'work.repeat_order_cancelled'


def _ordinary(connection, turn, row, frozen):
    source = frozen.get('source') or {}
    if (frozen.get('rerun') or frozen.get('schedule_origin')
            or any(source.get(field) for field in ('schedule_id', 'automation_id', 'automation_run_id'))
            or 'schedule' in str(source.get('kind') or '')):
        return False
    if turn.kind == 'pipeline':
        if (frozen.get('pipeline_work') or {}).get('reference') != turn.reference:
            return False
        if frozen.get('manual_order'):
            return True
        # Only positively classified legacy orders are eligible. Older
        # pipeline scheduler receipts used the same admission operation.
        return connection.execute(
            "SELECT 1 FROM events WHERE type='pipeline.workspace_admitted' "
            "AND json_extract(data_json,'$.workflow_id')=? LIMIT 1", (row['id'],)).fetchone() is not None
    return owns_direct_work(connection, row, frozen, turn.reference)


def _original(connection, turn, identifier):
    row = connection.execute(_SELECT + ' AND w.id=?', (identifier,)).fetchone()
    frozen = json.loads(row['snapshot_json']) if row else {}
    if not row or not _ordinary(connection, turn, row, frozen):
        raise PermissionError('请选择当前员工或团队已完成的手动工单。')
    return row, frozen


def _base_payload(turn, row, frozen):
    if turn.kind == 'pipeline':
        raw = frozen.get('queued_pipeline_input', frozen.get('initial_pipeline_input'))
        if raw is None:
            raise ContractError('原工单缺少可核对的初始任务输入。')
    else:
        raw = json.loads(row['payload_json'])
    raw_context = raw.get('context') or {}
    if raw.get('module_bindings') or any(raw_context.get(field) for field in ('business_event', 'work_item')):
        raise ContractError('共享业务工单须从原业务入口重新交办。')
    payload = {
        'schema': 'runteams.task-input/v2', 'objective': raw.get('objective'),
        'parameters': raw.get('parameters') or {},
        'context': {key: raw_context[key] for key in ('brief', 'acceptance') if key in raw_context},
        'inputs': raw.get('inputs') or [], 'asset_bindings': raw.get('asset_bindings') or {},
        'module_bindings': {},
    }
    if raw.get('skill_key'):
        payload['skill_key'] = raw['skill_key']
    return copy.deepcopy(payload)


def _source_info(row):
    return {'workflow_id': row['id'], 'task_id': row['task_id'], 'title': row['title'],
            'created_at': row['created_at'], 'completed_at': row['updated_at']}


def _source_version(frozen):
    package = frozen.get('package') or {}
    pipeline = frozen.get('pipeline_work') or {}
    if pipeline:
        return {'revision': pipeline.get('source_revision') or package.get('revision'),
                'generation': frozen.get('pipeline_generation')}
    positions = (frozen.get('definition') or {}).get('positions') or [{}]
    return {'revision': package.get('revision'), 'release_id': positions[0].get('employee_release_id')}


def _original_attachments(payload):
    entries = {}
    for index, item in enumerate(payload['inputs']):
        grant = item.get('asset_grant_id')
        identifier = 'grant-' + str(grant) if grant else item.get('id') or f'file-{index}'
        entries[identifier] = {'id': identifier, 'name': item.get('name') or '附件', 'slots': [], 'item': item}
    for slot, grant in payload['asset_bindings'].items():
        identifier = 'grant-' + str(grant)
        if identifier not in entries:
            try:
                name = _check_grant(grant)['name']
            except (ValueError, PermissionError, OSError, TypeError):
                name = '原资料不可用'
            entries[identifier] = {'id': identifier, 'name': name, 'slots': [], 'grant': grant}
        entries[identifier]['slots'].append(slot)
    return entries


def _selected_attachments(turn, arguments):
    message = product_store.get_chat_message(turn.chat_id, turn.message_id)
    available = {item['id']: item for item in message.get('attachments') or []}
    selected = arguments.get('attachment_ids', [])
    if set(selected) - available.keys():
        raise PermissionError('替换附件只能选本轮实际上传的文件。')
    return [available[key] for key in selected]


def _file_digest(turn, item):
    from runteams_core.conversations.chat_attachments import snapshot_tree
    return sha256(snapshot_tree(turn.chat_id, item)).hexdigest()


def _managed_sha(core, task_id, item):
    reference = task_inputs.LOCAL_INPUT_REF.fullmatch(item.get('ref', ''))
    if reference is None:
        raise ContractError('原附件缺少可核对的文件快照，请重新提供。')
    task_inputs.source_for_item(core.root, task_id, item)
    return reference[3]


def _check_grant(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ContractError('原资料缺少可核对的本机授权。')
    return local_references.reference(int(value))


def _plan_attachments(core, turn, arguments, row, payload):
    mode = arguments['attachment_mode']
    selected = _selected_attachments(turn, arguments)
    bindings = arguments.get('asset_bindings', {})
    retained = arguments.get('original_attachment_ids')
    available = _original_attachments(payload)
    if mode != 'replace' and (selected or bindings):
        raise ContractError('请在替换附件时选择本轮文件和资料。')
    if mode == 'replace' and not selected:
        raise ContractError('请选择本轮实际上传的替换附件。')
    if mode == 'omit' and retained is not None:
        raise ContractError('不带附件时无需选择原资料。')
    if retained is None:
        retained = list(available) if mode == 'keep' else []
    if set(retained) - available.keys():
        raise PermissionError('只能沿用该原工单提供的附件。')

    copies, names = [], []
    payload['inputs'], payload['asset_bindings'] = [], {}
    for identifier in retained:
        entry = available[identifier]
        names.append(entry['name'])
        item = entry.get('item')
        grant = item.get('asset_grant_id') if item else entry.get('grant')
        if grant:
            _check_grant(grant)
            for slot in entry['slots']:
                payload['asset_bindings'][slot] = grant
            if item:
                payload['inputs'].append(item)
        else:
            copies.append({'original': True, 'item': item, 'sha256': _managed_sha(core, row['task_id'], item)})

    grants = {}
    for item in selected:
        names.append(item['name'])
        if item['kind'] == 'local_asset':
            grant = str(item['grant_id'])
            _check_grant(grant)
            if 'grant-' + grant in retained:
                raise ContractError('同一份资料只能选择一次。')
            grants[item['id']] = grant
            payload['inputs'].append({'name': item['name'], 'asset_grant_id': grant})
        elif item['kind'] in ('file', 'image', 'folder'):
            copies.append({'original': False, 'item': item, 'sha256': _file_digest(turn, item)})
        else:
            raise ContractError('请选择工作支持的文件、文件夹或本机资料。')
    if set(bindings.values()) - grants.keys():
        raise PermissionError('岗位资料栏只能绑定本轮选中的本机资料。')
    if set(bindings) & payload['asset_bindings'].keys():
        raise ContractError('同一个岗位资料栏只能选择一份资料。')
    payload['asset_bindings'].update({slot: grants[value] for slot, value in bindings.items()})
    return copies, names


def _runtime(core, turn, row, payload):
    from runteams_core.authoring.definition_contracts import validate_definition
    validate_definition('task_payload', payload)
    if turn.kind == 'pipeline':
        from runteams_core.authoring.compilation.creator_validation import validate_data
        from runteams_core.pipelines import source_pipeline_control as control
        from runteams_core.pipelines.pipeline_context import current
        revision, asset = current().definition(turn.reference)
        active = control.read(core, turn.reference)
        if active['status'] != 'running':
            raise ContractError('请先恢复智能体团队，再交办新工单。')
        slot = row['start_column_key']
        contract = control.dispatch_contract(core, turn.reference, slot)
        declarations = asset['pipeline'].get('parameters', [])
        if declarations and set(payload['parameters']) - {
                field['key'] for field in declarations if field.get('source') == 'user' and field['type'] != 'secret'}:
            raise ContractError('任务只能使用岗位声明的用户参数。')
        if contract['kind'] == 'employee':
            validate_data(contract['input_schema'], payload['parameters'])
        missing = [field['name'] for field in contract.get('assets', [])
                   if field.get('required') and field['name'] not in payload['asset_bindings']]
        if missing:
            raise ContractError('请选择岗位所需的资料：' + '、'.join(missing))
        return {'revision': revision, 'generation': (active['bundle'] or {}).get('generation', 0),
                'start_column_key': slot, 'start_position': contract.get('position_name') or slot}, None

    from runteams_core.employees.employee_binding import resolve
    from runteams_core.employees.source_employee_runtime import package_asset, validate, validate_parameters
    session = product_store.get_chat(turn.chat_id, include_messages=False)
    binding = resolve(session)
    if binding['reference'] != turn.reference:
        raise PermissionError('当前员工已变化，请重新核对。')
    package = binding['package']
    if package:
        validate(package)
        if payload.get('skill_key'):
            validate_parameters(package_asset(package), payload['skill_key'], payload['parameters'])
        return {'revision': package['revision'], 'package_sha256': package['result_sha256']}, binding
    release = binding['employee']['active_release']
    if payload.get('skill_key'):
        units = release['snapshot_json']['work_units']
        unit = next((unit for unit in units if unit['skill_key'] == payload['skill_key']), None)
        if unit is None:
            raise ContractError('原技能在当前员工版本中不可用。')
        from runteams_core.authoring.compilation.creator_validation import validate_data
        validate_data(unit['work']['input_schema'], payload['parameters'])
    return {'release_id': release['id'], 'version': release.get('version'), 'release_sha256': release.get('digest')}, binding


def _operation(turn):
    origin = [turn.scope['cache_scope'], turn.epoch, turn.chat_id, turn.message_id, turn.kind, turn.reference]
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'runteams:repeat-order:' + digest(origin)))


def _existing(connection, operation):
    row = connection.execute('SELECT data_json FROM events WHERE stream=? AND type=? LIMIT 1',
                             ('manual-repeat-order:' + operation, _RECEIPT)).fetchone()
    return json.loads(row[0]) if row else None


def _question(plan, policy):
    from runteams_core.agents.language_policy import snapshot
    english = snapshot(policy)['communication_language'] == 'en'
    source = plan['source']
    payload = plan['payload']
    runtime = plan['runtime']
    selected_version = runtime.get('version') or runtime.get('revision') or runtime.get('release_id')
    parameters = json.dumps(payload['parameters'], ensure_ascii=False, sort_keys=True) if payload['parameters'] else None
    mode = plan['attachment_mode']
    names = '、'.join(plan['attachment_names'])
    if english:
        confirm = 'Create new order'
        cancel = 'Cancel'
        header = 'Confirm new order'
        details = ['Assign the work shown here', 'End this request']
        attachment = {'keep': 'Keep originals', 'replace': 'Replace', 'omit': 'No attachments'}[mode]
        fields = [
            f"Original order #{source['workflow_id']} · {source['title']}",
            f"New order · {plan['title']}",
            f"Objective · {payload['objective']}",
            f"Parameters · {parameters or 'None'}",
            'Attachments · ' + attachment + (' · ' + names if names else ''),
        ]
        if runtime.get('start_position'):
            fields.append('Starting position · ' + runtime['start_position'])
        if selected_version:
            fields.append('Execution version · ' + str(selected_version))
    else:
        confirm = '确认创建新工单'
        cancel = '取消'
        header = '另开新工单'
        details = ['交办显示的任务、参数和附件', '结束本次交办']
        attachment = {'keep': '沿用', 'replace': '替换', 'omit': '不带附件'}[mode]
        fields = [
            f"原工单 #{source['workflow_id']} · {source['title']}",
            f"新工单 · {plan['title']}",
            f"目标 · {payload['objective']}",
            f"参数 · {parameters or '无'}",
            '附件 · ' + attachment + (' · ' + names if names else ''),
        ]
        if runtime.get('start_position'):
            fields.append('起始岗位 · ' + runtime['start_position'])
        if selected_version:
            fields.append('执行版本 · ' + str(selected_version))
    question = '\n'.join(fields)
    if len(question) > 4000:
        raise ContractError('派单确认内容过长，请缩短本次工单目标或参数。')
    return [{'id': 'manual_repeat_order', 'header': header, 'question': question,
             'options': [{'label': confirm, 'description': details[0]},
                         {'label': cancel, 'description': details[1]}]}], confirm


def _confirmation_status(connection, operation):
    return connection.execute(
        'SELECT type FROM events WHERE stream=? AND type IN (?,?) ORDER BY id DESC LIMIT 1',
        ('manual-repeat-order:' + operation, _PROMPTED, _DECLINED)).fetchone()


def _ask(core, ask, plan, operation, policy):
    question, confirm = _question(plan, policy)
    with core.repository.connect() as connection:
        existing = _confirmation_status(connection, operation)
        if existing:
            return False
        core.repository.event('manual-repeat-order:' + operation, _PROMPTED,
                              {'plan_sha256': digest(plan)}, connection=connection)
    answer = ask(question)
    accepted = (answer or {}).get('answers', {}).get('manual_repeat_order', {}).get('answers') == [confirm]
    if not accepted:
        with core.repository.connect() as connection:
            core.repository.event('manual-repeat-order:' + operation, _DECLINED,
                                  {'source_workflow_id': plan['source']['workflow_id']}, connection=connection)
    return accepted


def _copy_files(core, turn, task_id, plan, operation):
    from runteams_core.assets.file_trees import decode_tree, materialize_tree, tree_bytes
    from runteams_core.conversations.chat_attachments import snapshot_tree
    payload = copy.deepcopy(plan['payload'])
    for copy_ in plan['copies']:
        item = copy_['item']
        if copy_['original']:
            source_id = plan['source']['task_id']
            _managed_sha(core, source_id, item)
            body = tree_bytes(task_inputs.task_root(core.root, source_id) / item['id'])
        else:
            body = snapshot_tree(turn.chat_id, item)
        sha = sha256(body).hexdigest()
        if sha != copy_['sha256']:
            raise ContractError('待交办附件已变化，请重新核对后交办。')
        identifier = uuid.uuid5(uuid.UUID(operation), item['id']).hex[:24]
        target = task_inputs.task_root(core.root, task_id) / identifier
        materialize_tree(decode_tree(body), target)
        entry = {key: item[key] for key in task_inputs.PUBLIC_KEYS if key in item}
        entry.update(id=identifier, ref=f'device-input://{task_id}/{identifier}/{sha}')
        payload['inputs'].append(entry)
    return payload


def _native_employee(core, connection, binding, title, payload, source, prepare, runtime):
    task_id = core.create_employee_task(binding['asset_id'], title, payload, index_identity=False, _connection=connection)
    release = connection.execute(
        "SELECT r.digest,r.source_ref_json FROM tasks t JOIN employee_releases r "
        "ON r.id=json_extract(t.pipeline_snapshot_json,'$.definition.positions[0].employee_release_id') "
        "WHERE t.id=?", (task_id,)).fetchone()
    if (not release or release['digest'] != runtime['release_sha256']
            or json.loads(release['source_ref_json']).get('release_id') != runtime['release_id']):
        raise ContractError('员工执行版本已变化，请重新核对后交办。')
    if prepare:
        payload = prepare(task_id)
        connection.execute('UPDATE tasks SET payload_json=? WHERE id=?', (canonical(payload).decode(), task_id))
    workflow_id = core.start_workflow(task_id, source=source, _connection=connection)
    return {'workflow_id': workflow_id, 'task_id': task_id, 'title': title, 'state': 'ready'}


def _admit(core, turn, plan, revision, operation, arguments_digest):
    task_ids = []
    def prepare(task_id):
        task_ids.append(task_id)
        return _copy_files(core, turn, task_id, plan, operation)

    with core.repository.definition_lock():
        try:
            with core.repository.connect() as connection:
                saved = _existing(connection, operation)
                if saved:
                    if saved['arguments_sha256'] != arguments_digest:
                        raise ContractError('本轮已经提交另一个方案，请核对原回执。')
                    return saved['result'], False
                chat_setup._current_message(turn)
                row, frozen = _original(connection, turn, plan['source']['workflow_id'])
                if _revision(row, frozen) != revision:
                    raise ContractError('原工单已变化，请重新核对后交办。')
                runtime, binding = _runtime(core, turn, row, plan['payload'])
                if runtime != plan['runtime']:
                    raise ContractError('执行版本已变化，请按新版本核对后交办。')
                authorization = core.repository.event('chat:' + str(turn.chat_id), 'task.dispatch_authorized',
                    {'chat_id': turn.chat_id, 'message_id': turn.message_id, 'device_chat_identity': turn.epoch,
                     'surface': 'manual-repeat-order', 'plan_sha256': digest(plan)}, connection=connection)
                link = {'source_task_id': row['task_id'], 'source_workflow_id': row['id'],
                        'source_version': plan['source_version'], 'operation_id': operation}
                message = product_store.get_chat_message(turn.chat_id, turn.message_id)
                source = {'chat_id': turn.chat_id, 'dispatch_authorization_event_id': authorization,
                          'language_policy': message.get('metadata', {}).get('language_policy'), 'repeat_order': link}
                payload = plan['payload']
                prepare_inputs = prepare if plan['copies'] else None
                if turn.kind == 'pipeline':
                    from runteams_core.pipelines.source_pipeline_work import create
                    request = {'operation_id': operation, 'reference': turn.reference,
                               'title': plan['title'], 'payload': payload}
                    if row['start_column_key']:
                        request['start_column_key'] = row['start_column_key']
                    work = create(core, request, repeat_order=link, prepare_inputs=prepare_inputs,
                                  expected_revision=runtime['revision'])['workflow']
                    runtime = {**runtime, 'generation': work['snapshot_json']['pipeline_generation']}
                    card = {'workflow_id': work['id'], 'task_id': work['task_id'], 'title': plan['title'],
                            'state': work['state'], 'pipeline_reference': turn.reference}
                elif binding['package']:
                    from runteams_core.employees.employee_chat_work import _admit as admit_employee
                    _, effect = admit_employee(core, binding, binding['package'], plan['title'], payload,
                                               source, '', repeat_order=link, prepare_inputs=prepare_inputs)
                    card = effect['run_card']
                else:
                    card = _native_employee(core, connection, binding, plan['title'], payload, source,
                                            prepare_inputs, runtime)
                card['storage_scope'] = 'device'
                card['source_workflow_id'] = row['id']
                result = {'status': 'created', 'operation_id': operation, 'source': plan['source'],
                          'source_version': plan['source_version'], 'runtime': runtime,
                          'attachments': plan['attachment_names'], 'run_card': card}
                core.repository.event('workflow_run:' + str(card['workflow_id']), 'workflow.repeated_manual_order',
                                      link, connection=connection)
                core.repository.event('manual-repeat-order:' + operation, _RECEIPT,
                                      {'arguments_sha256': arguments_digest, 'result': result}, connection=connection)
                chat_setup._current_message(turn)
        except BaseException:
            if task_ids:
                try:
                    with core.repository.read_snapshot() as connection:
                        for task_id in task_ids:
                            if connection.execute('SELECT 1 FROM tasks WHERE id=?', (task_id,)).fetchone() is None:
                                task_inputs.discard_task(core.root, task_id)
                except (ValueError, OSError, sqlite3.Error):
                    logging.getLogger(__name__).exception('Could not verify failed manual order attachment cleanup')
            raise
    return result, True


def _revision(row, frozen):
    return digest([row['title'], row['updated_at'], row['payload_json'], frozen])


def _validate(arguments):
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(INPUT_SCHEMA, format_checker=FormatChecker())
    if len(canonical(arguments)) > 96 * 1024 or not validator.is_valid(arguments):
        raise ContractError('手动工单请求无效。')
    operation = arguments['operation']
    required, optional = {
        'list': (set(), {'query', 'completed_from', 'completed_through'}),
        'inspect': ({'workflow_id'}, set()),
        'create': ({'workflow_id', 'intent', 'attachment_mode'}, {'changes', 'attachment_ids', 'original_attachment_ids', 'asset_bindings'}),
        'receipt': (set(), set()),
    }[operation]
    fields = arguments.keys() - {'operation'}
    if not required <= fields or fields - required - optional:
        raise ContractError('请提供本次操作需要的工单、变更和附件。')


def _execute(core, turn, arguments, ask, wake, policy=None):
    _validate(arguments)
    core._actor()
    message = chat_setup._current_message(turn)
    operation = _operation(turn)
    mode = arguments['operation']
    if mode == 'receipt':
        with core.repository.read_snapshot() as connection:
            previous = _existing(connection, operation)
        return previous['result'] if previous else {'status': 'unknown'}
    if mode == 'create' and (not arguments['intent'].strip() or arguments['intent'] not in message):
        raise PermissionError('请引用本轮用户明确要求另开工单的原话。')
    with core.repository.read_snapshot() as connection:
        previous = _existing(connection, operation)
    arguments_digest = digest(arguments)
    if mode == 'create' and previous:
        if previous['arguments_sha256'] != arguments_digest:
            raise ContractError('本轮已经提交另一个方案，请核对原回执。')
        return previous['result']
    with core.repository.read_snapshot() as connection:
        if mode == 'list':
            query = arguments.get('query', '').strip().casefold()
            items = []
            date_from = arguments.get('completed_from', '')
            date_through = arguments.get('completed_through', '9999-12-31')
            if date_from > date_through:
                raise ContractError('完成日期范围无效。')
            selected = connection.execute(_SELECT + ' AND substr(w.updated_at,1,10) BETWEEN ? AND ? '
                                          'ORDER BY w.updated_at DESC,w.id DESC', (date_from, date_through))
            for row in selected:
                if query and query not in row['title'].casefold() and query not in (str(row['id']), str(row['task_id'])):
                    continue
                if _ordinary(connection, turn, row, json.loads(row['snapshot_json'])):
                    items.append(_source_info(row))
                    if len(items) == 31:
                        break
            return {'status': 'listed', 'workflows': items[:30], 'has_more': len(items) > 30}
        row, frozen = _original(connection, turn, arguments['workflow_id'])
        payload = _base_payload(turn, row, frozen)
    if mode == 'inspect':
        return {'status': 'inspected', 'source': _source_info(row), 'source_version': _source_version(frozen),
                'objective': payload['objective'], 'parameters': payload['parameters'], 'skill_key': payload.get('skill_key'),
                'attachments': [{key: entry[key] for key in ('id', 'name', 'slots')}
                                for entry in _original_attachments(payload).values()],
                'start_column_key': row['start_column_key']}
    if not callable(ask):
        raise PermissionError('请在支持确认卡的原对话中交办。')
    changes = arguments.get('changes', {})
    title = changes.get('title', '另开 · ' + row['title'])[:200].strip()
    if not title:
        raise ContractError('请给新工单填写名称。')
    if 'objective' in changes:
        payload['objective'] = changes['objective']
    payload['parameters'].update(changes.get('parameters', {}))
    copies, names = _plan_attachments(core, turn, arguments, row, payload)
    runtime, _ = _runtime(core, turn, row, payload)
    plan = {'source': _source_info(row), 'source_version': _source_version(frozen), 'runtime': runtime,
            'payload': payload, 'title': title, 'attachment_mode': arguments['attachment_mode'],
            'attachment_names': names, 'copies': copies}
    if not _ask(core, ask, plan, operation, policy):
        return {'status': 'cancelled', 'source': plan['source']}
    chat_setup._current_message(turn)
    result, fresh = _admit(core, turn, plan, _revision(row, frozen), operation, arguments_digest)
    if fresh and callable(wake):
        try:
            wake(result['run_card']['workflow_id'])
        except Exception:
            logging.getLogger(__name__).exception('Manual order admitted but worker wake failed')
    return result


def call(arguments, context):
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError, AgentToolResult
    from runteams_core.work.device_work_services import current

    turn = context.get(chat_setup.TURN_CONTEXT)
    if (not isinstance(turn, chat_setup.SetupTurn) or context.get('chat_id') != turn.chat_id
            or context.get('actor_id') != principal(turn.scope)):
        raise AgentToolError('请从原员工或团队的主对话另开工单。')
    try:
        data = _execute(current(), turn, arguments, context.get('repeat_order_confirm'),
                        context.get('repeat_order_wake'), context.get('language_policy'))
    except (ValueError, PermissionError) as error:
        raise AgentToolError(str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise AgentToolError('暂时无法核对工单或附件，请稍后重试。') from error
    return AgentToolResult('manual_repeat_order', '已返回原工单或本轮交办回执。', data)
