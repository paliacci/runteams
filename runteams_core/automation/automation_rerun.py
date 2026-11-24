"""Admit new work from a scoped historical execution and its original inputs."""
import copy
import hmac
import json
import secrets
import uuid

from runteams_core.automation.automation_run_history import selected
from runteams_core.authoring.creator_contracts import digest
from runteams_core.foundation.contracts import ContractError

_NAMESPACE = uuid.UUID('0fe5def0-d396-4d9f-947f-bd62bed0276f')
_CONFIRMATION_KEY = secrets.token_bytes(32)


def receipt(connection, link):
    row = connection.execute(
        "SELECT data_json FROM events WHERE stream=? AND type='work.rerun_admitted' ORDER BY id DESC LIMIT 1",
        ('work-rerun:' + link['operation_id'],)).fetchone()
    if row is None:
        return None
    saved = json.loads(row[0])
    if saved['request_sha256'] != link['request_sha256']:
        raise ContractError('这次操作已用其他重跑内容受理。')
    return saved['result']


def record(core, connection, link, workflow_id, task_id, title):
    core.repository.event('work-rerun:' + link['operation_id'], 'work.rerun_admitted', {
        'request_sha256': link['request_sha256'],
        'result': {'workflow_id': workflow_id, 'task_id': task_id, 'title': title,
                   'run_key': f'work:{workflow_id}', 'source_run_key': link['source_run_key']},
    }, connection=connection)


def _source(core, original):
    payload = original.get('frozen_schedule_input')
    position = original.get('start_column_key')
    workflow_id = original.get('workflow_id')
    baseline = None
    if workflow_id:
        with core.repository.read_snapshot() as connection:
            row = connection.execute(
                'SELECT w.snapshot_json,t.start_column_key,t.payload_json FROM workflow_runs w '
                'JOIN tasks t ON t.id=w.task_id WHERE w.id=? AND t.trashed_at IS NULL',
                (workflow_id,)).fetchone()
        if row is None:
            raise ContractError('原工作已不可读取。')
        frozen = json.loads(row['snapshot_json'])
        position = position or row['start_column_key']
        baseline = (frozen.get('rerun') or {}).get('knowledge')
        if 'queued_pipeline_input' in frozen:
            payload = frozen['queued_pipeline_input']
        elif payload is None:
            payload = frozen.get('initial_pipeline_input') or frozen.get('pipeline_input') or json.loads(row['payload_json'])
    if original['source'] == 'employee_chat':
        from runteams_core.storage import product_store
        _, chat_id, message_id = original['run_key'].split(':')
        accepted = product_store.get_chat_message(int(chat_id), int(message_id))
        if not accepted or accepted.get('attachments'):
            raise ContractError('原对话的任务附件需要重新提供后才能重做。')
        payload = {'objective': accepted['text'], 'parameters': {}}
    if not isinstance(payload, dict) or not payload.get('objective') or original.get('work_record_unavailable'):
        raise ContractError('原运行没有可核对的任务输入。')
    fields = ('objective', 'parameters', 'skill_key', 'context', 'inputs', 'asset_bindings', 'module_bindings')
    work = {key: copy.deepcopy(payload[key]) for key in fields if key in payload and payload[key] is not None}
    work['schema'] = 'runteams.task-input/v2'
    for field, default in (('parameters', {}), ('context', {}), ('inputs', []), ('asset_bindings', {}), ('module_bindings', {})):
        work.setdefault(field, default)
    return work, position, baseline


def _inventory(reference):
    from runteams_core.assets import bundled_knowledge
    from runteams_core.conversations import asset_memory, asset_sources
    bank = asset_memory.bank_for(reference)
    bundled = bundled_knowledge.catalog(reference)
    sources = asset_sources.catalog(bank, bundled=bundled, limit=None)['sources']
    versions = [{'id': source['id'], 'name': source['name'], 'origin': source['origin'],
                 'version': source.get('revision') or bundled[source['id']]['sha256']}
                for source in sources]
    return {'sources': versions, 'preferences': asset_memory.read(bank)['revision']}


def _knowledge_changes(reference, original, inventory, baseline):
    if baseline is not None:
        prior = {item['id']: item for item in baseline['sources']}
        current = {item['id']: item for item in inventory['sources']}
        changes = [{'name': item['name'], 'change': 'removed' if key not in current else 'changed'}
                   for key, item in prior.items() if current.get(key) != item]
        changes.extend({'name': item['name'], 'change': 'added'}
                       for key, item in current.items() if key not in prior)
        if baseline['preferences'] != inventory['preferences']:
            changes.append({'name': '长期偏好', 'change': 'changed'})
        return changes
    from runteams_core.assets import bundled_knowledge
    from runteams_core.conversations import asset_memory, asset_sources

    by_name = {}
    for item in inventory['sources']:
        by_name.setdefault(item['name'], []).append(item)
    known = {}
    for item in original.get('knowledge_evidence', ()):
        if item.get('name'):
            known.setdefault(item['name'], []).append(item)
    changes = [{'name': name, 'change': 'missing_from_current_catalog'}
               for name in sorted(known.keys() - by_name.keys())]
    bundled = None
    for name, sources in sorted(by_name.items()):
        change = 'historical_version_unverified'
        for proof in known.get(name, ()):
            source = next((item for item in sources if item['id'] == proof.get('source')), None)
            version = proof.get('revision')
            if source and version:
                if source['version'] != version:
                    change = 'changed'
                    break
                if len(sources) == 1:
                    change = None
                continue
            if source and source.get('origin') == 'bundled' and len(sources) == 1:
                # Bundled source IDs include the full content SHA.
                change = None
                continue
            if len(sources) == 1 and proof.get('method') == 'excerpt' and proof.get('excerpt_preview'):
                if bundled is None:
                    bank = asset_memory.bank_for(reference)
                    bundled = bundled_knowledge.catalog(reference)
                try:
                    current = asset_sources.excerpt(bank, sources[0]['id'], proof.get('page', 1),
                                                    proof.get('offset', 0), bundled=bundled)
                except (OSError, ValueError):
                    current = {}
                if not current.get('text', '').startswith(proof['excerpt_preview']):
                    change = 'changed'
                    break
        if change:
            changes.append({'name': name, 'change': change})
    if inventory['preferences'] != digest(''):
        changes.append({'name': '长期偏好', 'change': 'historical_version_unverified'})
    return changes


def assert_knowledge(frozen, *, reference=None):
    link = frozen.get('rerun')
    if link is None:
        return
    reference = reference or (frozen.get('pipeline_work') or {}).get('reference') or frozen['employee_reference']
    if _inventory(reference) != link['knowledge']:
        raise ContractError('重跑受理后知识库已变化，请核对后重新发起。')


def _signature(origin, request, inventory):
    body = digest([origin, request, inventory]).encode('ascii')
    return hmac.digest(_CONFIRMATION_KEY, body, 'sha256').hex()


def _confirmed_origin(token, turn_key, request, inventory):
    if not token:
        return None
    origin, separator, signature = token.rpartition('.')
    origin_epoch, _, origin_message = origin.rpartition(':')
    current_epoch, _, current_message = turn_key.rpartition(':')
    if (separator and origin_epoch and origin_epoch == current_epoch and origin_message.isascii()
            and origin_message.isdecimal() and current_message.isascii() and current_message.isdecimal()
            and int(current_message) > int(origin_message)
            and hmac.compare_digest(signature, _signature(origin, request, inventory))):
        return origin
    return None


def _admit_employee(backend, core, reference, title, payload, link):
    from runteams_core.automation.device_employee_schedules import employee, record_id
    from runteams_core.employees import employee_chat_work, source_employee_runtime
    from runteams_core.employees.employee_references import SOURCE_SCHEMA

    if reference['schema'] == SOURCE_SCHEMA:
        package = source_employee_runtime.prepare(reference, link['operation_id'])
        employee_chat_work.admit_rerun(core, reference, package, title, payload, link)
        return

    identifier = record_id(reference)
    asset = employee(identifier, reference)
    backend.validate_skill_parameters(asset, payload.get('skill_key'), payload['parameters'])
    from runteams_core.authoring.definition_contracts import validate_definition
    payload = validate_definition('task_payload', payload)
    with core.repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        if receipt(connection, link) is not None:
            return
        if _inventory(reference) != link['knowledge']:
            raise ContractError('重跑受理前知识库已变化，请重新核对。')
        result = core.dispatch_task(title, payload, employee_id=identifier, source={
            'kind': 'employee_rerun', 'source_run_key': link['source_run_key'],
            'operation_id': link['operation_id'],
        })
        workflow_id = result['workflow_id']
        row = connection.execute('SELECT task_id,snapshot_json FROM workflow_runs WHERE id=?', (workflow_id,)).fetchone()
        frozen = json.loads(row['snapshot_json'])
        frozen['rerun'] = {'reference': reference, **{key: link[key] for key in ('source_run_key', 'knowledge')}}
        connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?', (json.dumps(frozen), workflow_id))
        record(core, connection, link, workflow_id, row['task_id'], title)


def execute(host, *, kind, reference, turn_key, arguments):
    if set(arguments) - {'run_key', 'changes', 'knowledge_confirmation'}:
        raise ContractError('重跑只接受原运行和本次需要替换的目标、参数。')
    run_key = arguments.get('run_key')
    changes = arguments.get('changes', {})
    token = arguments.get('knowledge_confirmation')
    if (not isinstance(run_key, str) or not isinstance(changes, dict)
            or set(changes) - {'objective', 'parameters'}
            or 'objective' in changes and (not isinstance(changes['objective'], str)
                                           or not changes['objective'].strip() or len(changes['objective']) > 20000)
            or 'parameters' in changes and not isinstance(changes['parameters'], dict)
            or token is not None and (not isinstance(token, str) or len(token) > 512)):
        raise ContractError('重跑参数无效。')
    from runteams_core.storage import device_data
    request = [device_data.identity()['cache_scope'], kind, reference, run_key, changes]
    backend = host.backend(kind)
    controller = backend.controller_factory()
    core = controller.core
    # A confirmation is tied to the original request and the disclosed knowledge
    # revision. Returning an already committed receipt never starts another run.
    authentication_origin = token.rpartition('.')[0] if token else None
    operation = str(uuid.uuid5(_NAMESPACE, digest([authentication_origin or turn_key, kind, reference, run_key])))
    link = {'operation_id': operation, 'source_run_key': run_key, 'request_sha256': digest(request)}
    with core.repository.read_snapshot() as connection:
        existing = receipt(connection, link)
    if existing is None:
        original = selected(host, kind, reference, run_key)
        if original['status'] not in ('completed', 'failed', 'canceled', 'cancelled', 'interrupted'):
            raise ContractError('请在原运行结束后从历史记录中重跑。')
        payload, position, baseline = _source(core, original)
        if 'objective' in changes:
            payload['objective'] = changes['objective']
        payload['parameters'].update(changes.get('parameters', {}))
        inventory = _inventory(reference)
        differences = _knowledge_changes(reference, original, inventory, baseline)
        confirmed = _confirmed_origin(token, turn_key, request, inventory)
        if confirmed is None and (differences or token is not None):
            return {'status': 'knowledge_confirmation_required', 'source_run_key': run_key,
                    'knowledge_changes': differences,
                    'knowledge_confirmation': f'{turn_key}.{_signature(turn_key, request, inventory)}'}
        link['knowledge'] = inventory
        title = ('重跑 · ' + (original.get('title') or run_key))[:200]
        if kind == 'pipeline':
            from runteams_core.pipelines import source_pipeline_work
            data = {'operation_id': operation, 'reference': reference, 'title': title, 'payload': payload}
            if position:
                data['start_column_key'] = position
            try:
                source_pipeline_work.create(core, data, rerun=link)
            except source_pipeline_work.WorkAdmissionUnknown:
                # Projection may fail after the atomic admission committed.
                with core.repository.read_snapshot() as connection:
                    if receipt(connection, link) is None:
                        raise
        else:
            _admit_employee(backend, core, reference, title, payload, link)
        with core.repository.read_snapshot() as connection:
            existing = receipt(connection, link)
        if existing is None:
            raise ContractError('工作受理结果尚未确认，请沿原操作核对。')
    controller.wake()
    return {'status': 'queued', **existing}
