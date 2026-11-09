"""One system-owned report per task, projected from accepted work facts."""
from datetime import datetime, timezone
import json
import re

from runteams_core.documents import rich_documents
from runteams_core.pipelines import pipeline_references


STATES = {
    'ready': '等待开始', 'running': '正在工作', 'waiting_retry': '等待重试',
    'needs_approval': '等待审批', 'needs_human': '需要处理', 'blocked': '暂时无法继续',
    'paused': '已暂停', 'interrupted': '执行中断', 'failed': '运行失败',
    'completed': '已完成', 'canceled': '已停止', 'superseded': '历史结果',
}
DECISIONS = {'approved': '通过', 'rejected': '退回', 'revise': '退回补齐'}
MILESTONES = {
    'workflow.human_responded': '收到人工补充',
    'workflow.retry_scheduled': '已安排重试',
    'workflow.paused': '任务暂停',
    'workflow.canceled': '任务停止',
    'workflow.input_invalid': '交接输入需要核对',
    'workflow.approval_requested': '等待人工审批',
}


ENGLISH = {
    '等待开始': 'Ready', '正在工作': 'Working', '等待重试': 'Waiting to retry',
    '等待审批': 'Awaiting approval', '需要处理': 'Needs attention', '暂时无法继续': 'Blocked',
    '已暂停': 'Paused', '执行中断': 'Interrupted', '运行失败': 'Failed',
    '已完成': 'Completed', '已停止': 'Stopped', '历史结果': 'Historical result',
    '通过': 'Approved', '退回': 'Rejected', '退回补齐': 'Revision requested',
    '收到人工补充': 'User response received', '已安排重试': 'Retry scheduled',
    '任务暂停': 'Task paused', '任务停止': 'Task stopped', '交接输入需要核对': 'Handoff input needs review',
    '等待人工审批': 'Awaiting human approval', '当前状态': 'Current status',
    '状态待核对': 'Status needs review', '当前环节': 'Current stage', '任务目标': 'Task objective',
    '历史环节': 'Historical stage', '人工决定': 'Human decision', '已记录': 'Recorded',
    '历史岗位': 'Historical position', '岗位记录': 'Position notes', '任务时间线': 'Task timeline',
    '时间以 UTC 记录。': 'Times are recorded in UTC.', '创建任务': 'Task created',
    '更早的执行可在任务的岗位执行记录中查看。': 'Earlier executions are available in the task’s position records.',
    '阶段交付': 'Stage deliverables', '任务': 'Task', '任务汇报': 'Task report',
}


def _label(frozen, text):
    # Localize only host-owned labels, never user text, asset names or accepted results.
    if (frozen.get('language_policy') or {}).get('communication_language') == 'en':
        return ENGLISH[text]
    return text


def _text(value, limit=500):
    plain = ' '.join(str(value or '').split())[:limit]
    return re.sub(r'([\\`*_{}\[\]<>])', r'\\\1', plain)


def _time(value):
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is not None:
            instant = instant.astimezone(timezone.utc)
        return instant.strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return value


def _workflow(connection, identifier):
    return connection.execute(
        'SELECT w.id,w.task_id,w.state,w.cursor_key,w.snapshot_json,t.title,t.created_at '
        'FROM workflow_runs w JOIN tasks t ON t.id=w.task_id WHERE w.id=?', (identifier,)).fetchone()


def _root(connection, task_id):
    return connection.execute(
        "SELECT id FROM artifacts WHERE json_extract(meta_json,'$.source')='pipeline_task_report' "
        "AND json_extract(meta_json,'$.revision_of')=id "
        "AND json_extract(meta_json,'$.pipeline_task_report.task_id')=?", (task_id,)).fetchone()


def _body(core, connection, row, frozen):
    label_text = lambda text: _label(frozen, text)
    english = (frozen.get('language_policy') or {}).get('communication_language') == 'en'
    identifier = row['id']
    pipeline = frozen['pipeline_work']['asset']['pipeline']
    names = {stage['key']: _text(stage['name'], 100) for stage in pipeline['positions'] + pipeline['states']}
    objective = _text((frozen.get('pipeline_input') or {}).get('objective'), 2000)
    lines = [f"**{label_text('当前状态')}**　{label_text(STATES.get(row['state'], '状态待核对'))}",
             f"**{label_text('当前环节')}**　{names.get(row['cursor_key'], '—')}"]
    if objective:
        lines.extend(('', '## '+label_text('任务目标'), objective))
    milestones = []
    for event in core.repository.events('workflow_run:'+str(identifier)):
        data = event['data_json']
        kind = event['type']
        if kind == 'workflow.routed':
            before, after = (names.get(data.get(key), label_text('历史环节')) for key in ('from', 'to'))
            label = f'{before} → {after}'
        elif kind == 'workflow.approval_decided':
            label = label_text('人工决定')+' · '+label_text(DECISIONS.get(data.get('decision'), '已记录'))
        else:
            label = label_text(MILESTONES[kind]) if kind in MILESTONES else None
        if label:
            milestones.append((event['created_at'], 4 if kind == 'workflow.routed' else 1, label))
    for run in connection.execute(
            'SELECT position_key,attempt,state,input_json,output_json,created_at,updated_at '
            'FROM employee_runs WHERE workflow_run_id=? ORDER BY id', (identifier,)):
        role = names.get(run['position_key'], label_text('历史岗位'))
        title = (f"{role} · Attempt {run['attempt']}" if english else f"{role} · 第 {run['attempt']} 次执行")
        milestones.append((run['created_at'], 2, title+(' started' if english else '开始')))
        if run['state'] == 'running':
            continue
        result = json.loads(run['output_json'])
        detail = result.get('summary')
        if run['state'] in ('failed', 'blocked', 'needs_human', 'interrupted'):
            issues = result.get('issues') or ()
            detail = next((item for item in issues if item and item != '请查看原工作对话。'), detail)
            if not detail and result.get('transport_status') == 'failed':
                from runteams_core.automation.scheduled_employee_chat import recorded_failure_reason
                detail = recorded_failure_reason(json.loads(run['input_json']).get('chat_id'),
                                                 run['created_at'], run['updated_at'])
        label = title+' · '+label_text(STATES.get(run['state'], '状态待核对'))
        if detail:
            label += ' · '+label_text('岗位记录')+' '+_text(detail, 350)
        milestones.append((run['updated_at'], 3, label))
    lines.extend(('', '## '+label_text('任务时间线'), label_text('时间以 UTC 记录。'), '', f"- {_time(row['created_at'])} · {label_text('创建任务')}"))
    if len(milestones) > 1000:
        lines.append(label_text('更早的执行可在任务的岗位执行记录中查看。'))
    for at, _, label in sorted(milestones)[-1000:]:
        lines.append(f'- {_time(at)} · {label}')
    from runteams_core.work.work_reports import catalog
    reports = catalog(core, workflow_id=identifier)
    if reports:
        lines.extend(('', '## '+label_text('阶段交付'), ''))
        lines.extend(f"- [{_text(report['name'], 150)}](runteams://document/{report['id']})" for report in reports[:500])
    document = rich_documents.from_markdown('\n'.join(lines))
    document['blocks'][0]['id'] = 'task-report-body'
    return document


def sync(core, connection, identifier, *, reference=None, expected_root=None):
    row = _workflow(connection, identifier)
    frozen = json.loads(row['snapshot_json']) if row else {}
    stored = (frozen.get('pipeline_work') or {}).get('reference')
    if not stored or reference is not None and stored != pipeline_references.checked_reference(reference):
        raise PermissionError('任务汇报不属于这条流水线。')
    root = _root(connection, row['task_id'])
    root_id = int(root['id']) if root else None
    if expected_root is not None and root_id != expected_root:
        raise PermissionError('任务汇报文档归属未能确认。')
    current = core.document_detail(root_id, include_content=False) if root_id else None
    if root_id and not current:
        raise PermissionError('原任务汇报无法读取。')
    title = str(row['title'] or _label(frozen, '任务'))[:190]+' · '+_label(frozen, '任务汇报')
    return rich_documents.write(core, name=title, document=_body(core, connection, row, frozen),
        document_id=root_id, document_key=f"pipeline-task-report-{row['task_id']}",
        base_revision=current['revision'] if current else 0, author='system',
        task_report={'task_id': row['task_id'], 'workflow_id': identifier}, connection=connection)


def open_report(core, reference, identifier):
    with core.repository.connect() as connection:
        report = sync(core, connection, identifier, reference=reference)
        return {'document_id': report['document_root_id'], 'revision': report['revision']}


def refresh_document(core, marker, root):
    with core.repository.connect() as connection:
        # A retained report is still readable after its task has been removed.
        if not _workflow(connection, marker['workflow_id']):
            return None
        return sync(core, connection, marker['workflow_id'], expected_root=root)
