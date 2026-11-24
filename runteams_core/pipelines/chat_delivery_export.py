"""Export only the immutable delivery pins of authorized original work orders."""
import base64
from hashlib import sha256
from io import BytesIO
import json
import re
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from runteams_core.configuration import chat_setup
from runteams_core.documents import rich_document_assets, rich_documents
from runteams_core.documents.document_export import MAX_EXPORT_BYTES
from runteams_core.employees.employee_work_contracts import owns_direct_work
from runteams_core.foundation.contracts import ContractError, digest
from runteams_core.foundation.identity.work_identity import principal
from runteams_core.storage import device_data

TOOL = 'runteams_export_submitted_deliveries'
DESCRIPTION = (
    'Find original work orders for this employee or team, then create a downloadable ZIP of the '
    'formal deliveries and attachments pinned at submission for explicitly selected work orders. '
    'List takes an optional query and export requires the selected workflow_ids.'
)
GUIDANCE = (
    '\n\n用户要求打包原工单的正式交付和附件时，用 runteams_export_submitted_deliveries。'
    '不确定工单编号时先用 list 按名称查找；范围明确才用 export 传 workflow_ids。'
    '只给出工具返回的下载链接、工单和缺失情况，不自行读取当前文档或工作目录补齐。'
)
INPUT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['operation'], 'properties': {
    'operation': {'type': 'string', 'enum': ['list', 'export']},
    'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
    'workflow_ids': {'type': 'array', 'minItems': 1, 'maxItems': 25, 'uniqueItems': True,
                     'items': {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991}},
}}
PATH = re.compile(r'/api/device/work/chats/([1-9][0-9]{0,15})/submitted-deliveries/([0-9a-f]{64})\.zip')
FILENAME = 'RunTeams 工单正式交付.zip'
_EVENT = 'delivery.export_prepared'


def _owned(connection, kind, reference, *, identifiers=None, query=''):
    sql = ('SELECT w.id,w.task_id,w.state,w.snapshot_json,t.title,t.pipeline_id,t.employee_id '
           'FROM workflow_runs w JOIN tasks t ON t.id=w.task_id WHERE t.trashed_at IS NULL')
    args = ()
    if identifiers is not None:
        sql += ' AND w.id IN (SELECT value FROM json_each(?))'
        args = (json.dumps(identifiers),)
    for row in connection.execute(sql + ' ORDER BY w.id DESC', args):
        if query and query not in row['title'].casefold() and query != str(row['id']):
            continue
        frozen = json.loads(row['snapshot_json'])
        if kind == 'pipeline':
            owned = (frozen.get('pipeline_work') or {}).get('reference') == reference
        else:
            owned = owns_direct_work(connection, row, frozen, reference)
        if owned:
            yield row, frozen


def _task(row):
    return {'workflow_id': row['id'], 'task_id': row['task_id'], 'title': row['title'], 'state': row['state']}


def _plan(connection, row, frozen):
    task = _task(row)
    if frozen.get('pipeline_work'):
        from runteams_core.pipelines.pipeline_task_report import FINAL_DELIVERY_EVENT

        receipt = connection.execute('SELECT data_json FROM events WHERE stream=? AND type=? ORDER BY id DESC LIMIT 1',
                                     ('workflow_run:' + str(row['id']), FINAL_DELIVERY_EVENT)).fetchone()
        reports = [{'pin': json.loads(receipt['data_json'])}] if receipt else []
        return {**task, 'kind': 'team', 'reports': reports}

    runs = connection.execute(
        "SELECT output_json FROM employee_runs WHERE workflow_run_id=? AND state='completed' ORDER BY id",
        (row['id'],))
    reports = []
    seen = set()
    for run in runs:
        result = json.loads(run['output_json'])
        chat_id = result.get('report_work_chat_id')
        if type(chat_id) is not int or chat_id < 1:
            continue
        for pin in result.get('report_references', []):
            artifact_id = pin.get('artifact_id') if isinstance(pin, dict) else None
            if type(artifact_id) is int:
                if artifact_id in seen:
                    continue
                seen.add(artifact_id)
            reports.append({'pin': pin, 'work_chat_id': chat_id})
    return {**task, 'kind': 'employee', 'reports': reports}


def _safe_name(value, default):
    value = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', '_', str(value or '')).strip(' .')
    # Keep both the human-readable name and its extension within ZIP readers'
    # and filesystems' byte limits.
    return value.encode()[:160].decode('utf-8', 'ignore').rstrip(' .') or default


def _assets(blocks):
    for block in blocks:
        props = block.get('props', {})
        if block['type'] in {'image', 'video', 'file'} and props.get('assetId'):
            yield props['assetId'], props.get('name')
        yield from _assets(block.get('children', []))


def _report(core, connection, plan, entry):
    from runteams_core.work.work_reports import SCHEMA as work_report_schema

    pin = entry['pin']
    if (not isinstance(pin, dict)
            or any(type(pin.get(k)) is not int or pin[k] < 1 for k in ('id', 'artifact_id', 'revision'))
            or not isinstance(pin.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', pin['sha256'])):
        raise ContractError('缺少提交时的版本记录。')
    row = connection.execute('SELECT * FROM artifacts WHERE id=? AND trashed_at IS NULL',
                             (pin['artifact_id'],)).fetchone()
    meta = core._decode_meta(row['meta_json']) if row else {}
    if plan['kind'] == 'team':
        marker = meta.get('pipeline_task_report') or {}
        owned = (meta.get('source') == rich_documents.TASK_REPORT_SOURCE and marker.get('state') == 'completed'
                 and marker.get('task_id') == plan['task_id'] and marker.get('workflow_id') == plan['workflow_id'])
    else:
        marker = meta.get('work_report') or {}
        owned = (marker.get('schema') == work_report_schema and marker.get('workflow_id') == plan['workflow_id']
                 and marker.get('chat_id') == entry['work_chat_id'] and marker.get('employee_run_id') is None)
    if (not owned or meta.get('content_model') != rich_documents.MODEL
            or meta.get('revision_of') != pin['id'] or meta.get('revision') != pin['revision']
            or meta.get('sha256') != pin['sha256']):
        raise ContractError('交付文件与提交时的版本不一致。')
    body = core._read_document_body(row)
    if sha256(body.encode()).hexdigest() != pin['sha256']:
        raise ContractError('交付文件内容与提交时的版本不一致。')
    return rich_documents.validate(body)


def _archive(core, connection, plans):
    buffer = BytesIO()
    total = 0
    summary = []
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        def write(path, raw):
            nonlocal total
            total += len(raw)
            if total > MAX_EXPORT_BYTES:
                raise ContractError('工单交付超过 128 MB，请减少本次选择的工单。')
            archive.writestr(ZipInfo(path), raw, compress_type=ZIP_DEFLATED)

        for plan in plans:
            task = {key: value for key, value in plan.items() if key not in {'kind', 'reports'}}
            task.update(files=[], missing=[])
            summary.append(task)
            folder = f"工单-{task['task_id']}-{task['workflow_id']}"
            if not plan['reports']:
                task['missing'].append({'reason': '原工单没有可核对的正式提交版本。'})
            for index, entry in enumerate(plan['reports'], start=1):
                pin = entry['pin']
                name = pin.get('name') if isinstance(pin, dict) else None
                label = _safe_name(name, '正式汇报')
                path = f'{folder}/{index:02d}-{label}'
                try:
                    document = _report(core, connection, plan, entry)
                except (ContractError, OSError, TypeError, KeyError):
                    task['missing'].append({'name': label, 'reason': '提交时的汇报版本缺失或无法核对。'})
                    continue
                write(path + '/汇报.json', json.dumps(document, ensure_ascii=False, indent=2).encode())
                write(path + '/汇报.md', rich_documents.narrative(document).encode())
                task['files'].append({'name': label, 'revision': pin['revision'], 'path': path + '/汇报.json'})
                for identifier, asset_name in dict(_assets(document['blocks'])).items():
                    try:
                        file = rich_document_assets.read(core, pin['id'], identifier)
                    except (ContractError, OSError):
                        task['missing'].append({'name': asset_name or identifier, 'report': label,
                                                'reason': '提交时的附件缺失或无法核对。'})
                        continue
                    raw = base64.b64decode(file['data'].split(',', 1)[1])
                    filename = _safe_name(file['name'], '附件')
                    attachment_path = f'{path}/附件/{identifier}-{filename}'
                    write(attachment_path, raw)
                    task['files'].append({'name': file['name'], 'path': attachment_path, 'asset_id': identifier})
        write('交付清单.json', json.dumps({'workflows': summary}, ensure_ascii=False, indent=2, sort_keys=True).encode())
    return buffer.getvalue(), summary


def _execute(core, turn, args):
    from itertools import islice
    from jsonschema import Draft202012Validator

    if not Draft202012Validator(INPUT_SCHEMA).is_valid(args):
        raise ContractError('请查找原工单，或选择 1 至 25 份原工单导出。')
    chat_setup._current_message(turn)
    core._actor()
    if args['operation'] == 'list':
        if 'workflow_ids' in args:
            raise ContractError('查找工单只接受名称或编号。')
        with core.repository.read_snapshot() as connection:
            found = _owned(connection, turn.kind, turn.reference, query=args.get('query', '').strip().casefold())
            matches = [_task(row) for row, _ in islice(found, 31)]
        return {'status': 'listed', 'workflows': matches[:30], 'has_more': len(matches) > 30}
    if set(args) != {'operation', 'workflow_ids'}:
        raise ContractError('请先明确要导出的原工单编号。')
    identifiers = sorted(args['workflow_ids'])
    with core.repository.definition_lock(), core.repository.connect() as connection:
        owned = list(_owned(connection, turn.kind, turn.reference, identifiers=identifiers))
        if len(owned) != len(identifiers):
            raise PermissionError('部分工单不属于当前资产，或已不可用。')
        plans = [_plan(connection, row, frozen) for row, frozen in owned]
        receipt = core.repository.storage.canonical_data({
            'chat_id': turn.chat_id, 'epoch': turn.epoch, 'kind': turn.kind,
            'reference': turn.reference, 'plans': plans,
        })
        raw, summary = _archive(core, connection, receipt['plans'])
        receipt['archive_sha256'] = sha256(raw).hexdigest()
        token = digest(receipt)
        stream = 'submitted-delivery-export:' + token
        chat_setup._current_message(turn)
        if not connection.execute('SELECT 1 FROM events WHERE stream=? AND type=?', (stream, _EVENT)).fetchone():
            core.repository.event(stream, _EVENT, receipt, connection=connection)
    return {'status': 'prepared', 'filename': FILENAME,
            'download_link': f'/api/device/work/chats/{turn.chat_id}/submitted-deliveries/{token}.zip',
            'workflows': summary}


def download(core, chat_id, token):
    core._actor()
    scope = device_data.identity()
    binding = chat_setup._binding(chat_id)
    if binding is None:
        raise PermissionError('请从原员工或团队对话下载。')
    kind, reference = binding
    epoch = device_data.epoch(chat_id)
    with core.repository.definition_lock(), core.repository.read_snapshot() as connection:
        row = connection.execute('SELECT data_json FROM events WHERE stream=? AND type=?',
                                 ('submitted-delivery-export:' + token, _EVENT)).fetchone()
        receipt = json.loads(row[0]) if row else None
        if (receipt is None or receipt['chat_id'] != chat_id or receipt['epoch'] != epoch
                or receipt['kind'] != kind or receipt['reference'] != reference or digest(receipt) != token):
            raise PermissionError('该下载不属于当前对话。')
        plans = receipt['plans']
        identifiers = [plan['workflow_id'] for plan in plans]
        current = {(work['id'], work['task_id'])
                   for work, _ in _owned(connection, kind, reference, identifiers=identifiers)}
        if current != {(plan['workflow_id'], plan['task_id']) for plan in plans}:
            raise PermissionError('原工单已不可用。')
        raw, _ = _archive(core, connection, plans)
        if sha256(raw).hexdigest() != receipt['archive_sha256']:
            raise ContractError('交付资料已变化，请在原对话中重新打包。')
        device_data.check(scope)
        if chat_setup._binding(chat_id) != binding or device_data.epoch(chat_id) != epoch:
            raise PermissionError('原对话已变化，请重新导出。')
    return raw


def call(arguments, context):
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError, AgentToolResult
    from runteams_core.work.device_work_services import current

    turn = context.get(chat_setup.TURN_CONTEXT)
    if (not isinstance(turn, chat_setup.SetupTurn) or context.get('chat_id') != turn.chat_id
            or context.get('actor_id') != principal(turn.scope)):
        raise AgentToolError('请从员工或智能体团队的直属对话导出原工单。')
    try:
        result = _execute(current(), turn, arguments)
    except (ValueError, PermissionError) as error:
        raise AgentToolError(str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise AgentToolError('暂时无法导出正式交付，请稍后重试。') from error
    return AgentToolResult('submitted_delivery_export', '已返回原工单正式交付结果。', result)
