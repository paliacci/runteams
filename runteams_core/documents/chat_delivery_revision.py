"""Restore an owned editable delivery's saved revision through its asset chat."""
import json
import sqlite3

from runteams_core.configuration import chat_setup
from runteams_core.foundation.contracts import ContractError, digest
from runteams_core.foundation.identity.work_identity import principal

TOOL = 'runteams_restore_delivery_revision'
DESCRIPTION = (
    'In the current employee or team chat, inspect its saved deliverable documents and their revision history. '
    'Use inspect with document_id to identify a particular historical revision. Restore requires the document '
    'root ID, historical revision number, the exact expected_current_revision and expected_current_token '
    'from inspect, and the current user’s explicit '
    'instruction as intent. Restoring copies the retained version into a new current revision. Formal submitted '
    'team reports and read-only evidence cannot be restored.'
)
GUIDANCE = (
    '\n\n用户询问交付文档版本或明确要求恢复历史内容时，先用 runteams_restore_delivery_revision 的 inspect。'
    '按名称查找可传 query，读取一份文档的修订时传 document_id。若同名或版本指代不明确，先让用户明确文档和修订。'
    '只有用户本轮明确要求恢复时才 restore，复制原话为 intent，传明确的文档、历史修订号及回执里的当前修订号和 current_revision_token。'
    '系统和正式提交的团队汇报及只读附件只能按原链接查看。恢复成功后只按回执给出新版本及历史链接。'
    '如果当前版本已经改变，重新检查并告知用户，不能用新的当前版本自动覆盖。'
)
_ID = {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991}
INPUT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['operation'], 'properties': {
    'operation': {'type': 'string', 'enum': ['inspect', 'restore']},
    'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
    'document_id': _ID,
    'revision': _ID,
    'expected_current_revision': _ID,
    'expected_current_token': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
    'intent': {'type': 'string', 'minLength': 2, 'maxLength': 4000},
}}


def _workflow(connection, row, meta):
    report = meta.get('work_report') or {}
    system_report = meta.get('pipeline_task_report') or {}
    identifiers = {value for value in (meta.get('workflow_id'), meta.get('workflow_run_id'),
                                        report.get('workflow_id'), system_report.get('workflow_id')) if value is not None}
    if row['employee_run_id']:
        attempt = connection.execute('SELECT workflow_run_id FROM employee_runs WHERE id=?',
                                     (row['employee_run_id'],)).fetchone()
        if attempt is None:
            raise PermissionError('原交付的岗位归属无法核对。')
        identifiers.add(attempt[0])
    if not identifiers:
        return None, {}
    if len(identifiers) != 1 or any(type(identifier) is not int or identifier < 1 for identifier in identifiers):
        raise PermissionError('原交付的工作归属无法核对。')
    owner = connection.execute(
        'SELECT w.id,w.snapshot_json,t.pipeline_id,t.employee_id FROM workflow_runs w '
        'JOIN tasks t ON t.id=w.task_id WHERE w.id=? AND t.trashed_at IS NULL',
        (identifiers.pop(),)).fetchone()
    if owner is None:
        raise PermissionError('原交付的工作已不可用。')
    return owner, json.loads(owner['snapshot_json'])


def _owner(connection, turn, row, meta):
    owner, frozen = _workflow(connection, row, meta)
    if turn.kind == 'pipeline':
        reference = meta.get('pipeline_reference')
        if owner:
            pipeline = frozen.get('pipeline_work') or {}
            if pipeline.get('reference') == turn.reference and reference in (None, turn.reference):
                return owner['id'], frozen
        elif reference == turn.reference:
            return None, {}
    elif not meta.get('pipeline_reference'):
        from runteams_core.employees.employee_references import same
        from runteams_core.employees.employee_work_contracts import owns_direct_work
        report = meta.get('work_report') or {}
        if owner and owns_direct_work(connection, owner, frozen, turn.reference):
            return owner['id'], frozen
        if not owner:
            references = [item for item in (meta.get('employee_reference'), report.get('employee_reference')) if item]
            if references and all(same(item, turn.reference) for item in references):
                return None, {}
            from runteams_core.employees import employee_documents
            if (not references and meta.get('source') == employee_documents.SOURCE
                    and turn.reference.get('schema') == 'runteams.business-reference/v1'
                    and turn.reference.get('resource') == 'employees'
                    and meta.get('employee_id') == turn.reference.get('id')):
                return None, {}
    raise PermissionError('无法核对这份交付文档属于当前员工或智能体团队。')


def _formal(connection, workflow_id, frozen, root_id):
    if workflow_id is None or not frozen.get('pipeline_work'):
        return False
    owners = [frozen, *(visit['snapshot'] for visit in frozen.get('pipeline_history', []))]
    if any(item.get('id') == root_id for owner in owners
           for item in (owner.get('pipeline_submission') or {}).get('reports', [])):
        return True
    return connection.execute(
        "SELECT 1 FROM employee_runs er,json_each(er.output_json,'$.report_references') r "
        "WHERE er.workflow_run_id=? AND json_extract(r.value,'$.id')=? LIMIT 1",
        (workflow_id, root_id)).fetchone() is not None


def _is_editable(core, row, meta):
    source = meta.get('source')
    return (core.is_document_artifact(meta, row['name'])
            and source != 'pipeline_task_report' and not meta.get('pipeline_task_report')
            and not meta.get('read_only') and not meta.get('data_view') and (meta.get('content_model') == 'rich-document'
                                               or core.document_can_edit(meta.get('path') or row['name'])))


def _document(core, connection, turn, chain, *, with_revisions=False):
    root = int(chain[0]['id'])
    rows = [(row, core._decode_meta(row['meta_json'])) for row in chain]
    latest, current = rows[-1]
    work_id, frozen = _owner(connection, turn, latest, current)
    if chain[0]['id'] != latest['id']:
        root_work_id, _ = _owner(connection, turn, *rows[0])
        if root_work_id != work_id:
            raise PermissionError('原交付的版本链归属无法核对。')
    if not core.is_document_artifact(current, latest['name']):
        raise ContractError('这项交付是附件，不是可恢复的文档。')
    revisions = [
        {'revision': int(meta.get('revision') or index), 'artifact_id': int(row['id']),
         'created_at': row['created_at'], 'note': meta.get('note', ''),
         'internal_link': f'runteams://document/{root}?revision={row["id"]}'}
        for index, (row, meta) in enumerate(rows, start=1)
    ]
    is_formal = _formal(connection, work_id, frozen, root) or any(
        meta.get('source') == 'pipeline_task_report' or meta.get('pipeline_task_report') for _, meta in rows)
    editable = _is_editable(core, latest, current) and not is_formal
    return {'document_id': root, 'name': latest['name'], 'current_revision': revisions[-1]['revision'],
            'current_artifact_id': int(latest['id']),
            'current_revision_token': digest([latest['id'], latest['name'], latest['ref'], current]),
            'internal_link': f'runteams://document/{root}',
            'revision_count': len(revisions), 'can_restore': editable and len(revisions) > 1,
            'reason': 'formal_report' if is_formal else 'read_only' if not editable else
                       'no_historical_revision' if len(revisions) < 2 else '',
            **({'revisions': revisions} if with_revisions else {})}


def _find(core, connection, turn, identifier):
    chain = core._document_chain(connection, identifier)
    if not chain or chain[0]['id'] != identifier:
        raise ContractError('请使用当前资产的文档根编号查看修订。')
    return chain, _document(core, connection, turn, chain, with_revisions=True)


def _list(core, connection, turn, query):
    groups = {}
    for row in core._document_rows(connection):
        groups.setdefault(core._document_root_id(row), []).append(row)
    documents = []
    for root, chain in reversed(tuple(groups.items())):
        if root != chain[0]['id'] or query and query not in (chain[-1]['name'] or '').casefold():
            continue
        try:
            documents.append(_document(core, connection, turn, chain))
        except (PermissionError, ContractError):
            continue
        if len(documents) >= 30:
            break
    return {'status': 'checked', 'documents': documents,
            'scope_note': '仅显示属于当前资产或其工单的交付文档。'}


def _restore(core, turn, args):
    identifier = args['document_id']
    stream = f'chat-delivery-restore:{turn.epoch}:{turn.message_id}:{identifier}'
    requested = {key: args[key] for key in ('document_id', 'revision', 'expected_current_revision', 'expected_current_token')}
    fingerprint = digest(requested)
    with core.repository.definition_lock(), core.repository.connect() as connection:
        chain, current = _find(core, connection, turn, identifier)
        received = connection.execute('SELECT data_json FROM events WHERE stream=? AND type=? ORDER BY id DESC LIMIT 1',
                                      (stream, 'delivery.revision_restored')).fetchone()
        if received is not None:
            receipt = json.loads(received[0])
            if receipt['request_sha256'] != fingerprint:
                raise ContractError('这条消息已恢复了该文档的另一修订。')
            result = receipt['result']
            return {**result, 'current_revision': current['current_revision'],
                    'is_current': result['artifact_id'] == current['current_artifact_id']}
        if not current['can_restore']:
            raise ContractError('正式汇报、只读交付或没有历史修订的文档无法恢复。')
        if (current['current_revision'] != args['expected_current_revision']
                or current['current_revision_token'] != args['expected_current_token']):
            raise ContractError('文档已被更新，请重新读取版本后再恢复。')
        matches = [item for item in current['revisions'] if item['revision'] == args['revision']]
        if len(matches) != 1 or matches[0]['artifact_id'] == current['current_artifact_id']:
            raise ContractError('请明确选择当前文档的一份历史修订。')
        chosen = matches[0]
        artifact = next(row for row in chain if row['id'] == chosen['artifact_id'])
        selected_meta = core._decode_meta(artifact['meta_json'])
        _owner(connection, turn, artifact, selected_meta)
        if not _is_editable(core, artifact, selected_meta):
            raise ContractError('该历史修订属于只读交付，无法恢复。')
        chat_setup._current_message(turn)
        new_artifact = core.revert_document(chosen['artifact_id'],
                                            expected_current_revision=current['current_revision'])
        if new_artifact == current['current_artifact_id']:
            raise ContractError('未能创建新的当前修订，请核对版本历史。')
        result = {'status': 'restored', 'document_id': identifier, 'name': current['name'],
                  'artifact_id': new_artifact, 'revision': current['current_revision'] + 1,
                  'restored_from_revision': chosen['revision'], 'source_revision_link': chosen['internal_link'],
                  'internal_link': f'runteams://document/{identifier}?revision={new_artifact}'}
        core.repository.event(stream, 'delivery.revision_restored',
                              {'request_sha256': fingerprint, 'result': result}, connection=connection)
    return {**result, 'current_revision': result['revision'], 'is_current': True}


def _execute(core, turn, arguments, message):
    from jsonschema import Draft202012Validator

    if not Draft202012Validator(INPUT_SCHEMA).is_valid(arguments):
        raise ContractError('交付文档修订请求无效。')
    if arguments['operation'] == 'restore':
        if (set(arguments) != {'operation', 'document_id', 'revision', 'expected_current_revision', 'expected_current_token', 'intent'}
                or not arguments['intent'].strip() or arguments['intent'].strip() not in message):
            raise ContractError('请从本轮用户明确指令中提交原话、文档和历史修订编号。')
        return _restore(core, turn, arguments)
    if set(arguments) not in ({'operation'}, {'operation', 'query'}, {'operation', 'document_id'}):
        raise ContractError('请按名称查找交付文档，或指定文档检查修订。')
    with core.repository.read_snapshot() as connection:
        if 'document_id' in arguments:
            _, current = _find(core, connection, turn, arguments['document_id'])
            return {'status': 'checked', 'document': current}
        return _list(core, connection, turn, arguments.get('query', '').strip().casefold())


def call(arguments, context):
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError, AgentToolResult
    from runteams_core.work.device_work_services import current

    turn = context.get(chat_setup.TURN_CONTEXT)
    if (not isinstance(turn, chat_setup.SetupTurn) or context.get('chat_id') != turn.chat_id
            or context.get('actor_id') != principal(turn.scope)):
        raise AgentToolError('请从员工或智能体团队的直属对话操作交付文档。')
    try:
        result = _execute(current(), turn, arguments, chat_setup._current_message(turn))
    except (ValueError, PermissionError) as exc:
        raise AgentToolError(str(exc)) from exc
    except (OSError, sqlite3.Error) as exc:
        raise AgentToolError('暂时无法读取或恢复修订，请核对原文档。') from exc
    return AgentToolResult('delivery_revision', '已返回交付文档修订结果。', result)
