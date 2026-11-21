"""One system-owned report per task, projected from accepted work facts."""
import json
import re

from runteams_core.documents import rich_documents
from runteams_core.foundation.contracts import digest
from runteams_core.pipelines import pipeline_references


STATES = {
    'ready': '等待开始', 'running': '正在工作', 'waiting_retry': '等待重试',
    'needs_approval': '等待审批', 'needs_human': '需要处理', 'blocked': '暂时无法继续',
    'paused': '已暂停', 'interrupted': '执行中断', 'failed': '运行失败',
    'completed': '已完成', 'canceled': '已停止', 'superseded': '历史结果',
}
ENGLISH = {
    '等待开始': 'Ready', '正在工作': 'Working', '等待重试': 'Waiting to retry',
    '等待审批': 'Awaiting approval', '需要处理': 'Needs attention', '暂时无法继续': 'Blocked',
    '已暂停': 'Paused', '执行中断': 'Interrupted', '运行失败': 'Failed',
    '已完成': 'Completed', '已停止': 'Stopped', '历史结果': 'Historical result',
    '当前状态': 'Current status', '任务': 'Task', '创建任务': 'Task created',
    '状态待核对': 'Status needs review', '当前环节': 'Current stage', '任务目标': 'Task objective',
}


def _label(frozen, text):
    # Localize only host-owned labels, never user text, asset names or accepted results.
    if (frozen.get('language_policy') or {}).get('communication_language') == 'en':
        return ENGLISH[text]
    return text


def _text(value, limit=500):
    plain = ' '.join(str(value or '').split())[:limit]
    return re.sub(r'([\\`*_{}\[\]<>])', r'\\\1', plain)


def _workflow(connection, identifier):
    return connection.execute(
        'SELECT w.id,w.task_id,w.state,w.cursor_key,w.snapshot_json,t.title,t.created_at,t.trashed_at '
        'FROM workflow_runs w JOIN tasks t ON t.id=w.task_id WHERE w.id=?', (identifier,)).fetchone()


def _root(connection, task_id):
    return connection.execute(
        "SELECT id,trashed_at FROM artifacts WHERE json_extract(meta_json,'$.source')='pipeline_task_report' "
        "AND json_extract(meta_json,'$.revision_of')=id "
        "AND json_extract(meta_json,'$.pipeline_task_report.task_id')=?", (task_id,)).fetchone()


def final_delivery_reference(core, work):
    """Read the canonical document link without composing a document during list rendering."""
    with core.repository.connect() as connection:
        root = _root(connection, work['task_id'])
    if root and not root['trashed_at']:
        return {'id': root['id'], 'name': work['task']['title']}


def _body(row, frozen):
    label_text = lambda text: _label(frozen, text)
    pipeline = frozen['pipeline_work']['asset']['pipeline']
    names = {stage['key']: _text(stage['name'], 100) for stage in pipeline['positions'] + pipeline.get('states', [])}
    objective = _text((frozen.get('pipeline_input') or {}).get('objective'), 2000)
    lines = [f"**{label_text('当前状态')}**　{label_text(STATES.get(row['state'], '状态待核对'))}",
             f"**{label_text('当前环节')}**　{names.get(row['cursor_key'], '—')}"]
    document = rich_documents.from_markdown('\n'.join(lines))
    document['blocks'][0]['id'] = 'task-report-body'
    if objective:
        title = label_text('任务目标')
        if frozen.get('pipeline_lineage'):
            document['blocks'].append({'id': 'task-objective', 'type': 'toggleListItem',
                'content': [{'type': 'text', 'text': title, 'styles': {}}],
                'children': [{'id': 'task-objective-body', 'type': 'markdown', 'props': {'text': objective}, 'children': []}]})
        else:
            document['blocks'][0]['props']['text'] += '\n\n## ' + title + '\n' + objective
    return document


def add_followup(document, update, frozen):
    if update:
        english = (frozen.get('language_policy') or {}).get('communication_language')=='en'
        heading = 'Latest follow-up' if english else '最近跟进'
        text = [f"## {heading}", update['observed_at'], _text(update['content'],4000)]
        text.extend(f"- {_text(k)} · {_text(str(v)) if v is not None else '—'}" for k,v in update['metrics'].items())
        text.append(_text(update['source_url'],2048))
        document['blocks'].append({'id':'task-latest-followup','type':'markdown','props':{'text':'\n\n'.join(text)},'children':[]})
    return document


def sync(core, connection, identifier, *, reference=None, expected_root=None):
    row = _workflow(connection, identifier)
    frozen = json.loads(row['snapshot_json']) if row else {}
    stored = (frozen.get('pipeline_work') or {}).get('reference')
    if not stored or reference is not None and stored != pipeline_references.checked_reference(reference):
        raise PermissionError('任务汇报不属于这个智能体团队。')
    root = _root(connection, row['task_id'])
    root_id = int(root['id']) if root else None
    if expected_root is not None and root_id != expected_root:
        raise PermissionError('任务汇报文档归属未能确认。')
    current = core.document_detail(root_id, include_content=False) if root_id else None
    if root_id and not current:
        raise PermissionError('原任务汇报无法读取。')
    title = str(row['title'] or _label(frozen, '任务'))
    marker = {'task_id': row['task_id'], 'workflow_id': identifier}
    if current and row['trashed_at']:
        return current
    from runteams_core.pipelines.scheduled_followup import latest
    update = latest(connection, identifier)
    from runteams_core.pipelines import pipeline_task_delivery
    accepted = frozen.get('pipeline_lineage')
    policy = pipeline_task_delivery.policy_for(frozen) if row['state'] == 'completed' and accepted else None
    # A returned stage can shorten the accepted lineage. Its old material then leaves this document.
    if accepted is not None:
        marker['delivery_lineage'] = digest({'layout': 2, 'accepted': accepted, 'policy': policy,
            'state': row['state'], 'position': row['cursor_key'], 'followup': (update or {}).get('revision')})
    if current and 'delivery_lineage' in marker:
        meta = connection.execute('SELECT meta_json FROM artifacts WHERE id=?', (current['id'],)).fetchone()
        if json.loads(meta[0])['pipeline_task_report'] == marker and current['name'] == title[:200]:
            return current
    if policy:
        try:
            document, attachments = pipeline_task_delivery.compose(core, connection, identifier, frozen, policy)
            add_followup(document, update, frozen)
        except pipeline_task_delivery.MissingDeliverySection:
            if frozen['pipeline_work']['asset']['pipeline'].get('delivery'):
                raise
            policy = None
    if not policy:
        document = add_followup(_body(row, frozen), update, frozen)
        document, attachments = pipeline_task_delivery.compose_current(core, connection, identifier, frozen, document)
    return rich_documents.write(core, name=title[:200], document=document, attachments=attachments,
        document_id=root_id, document_key=f"pipeline-task-report-{row['task_id']}",
        base_revision=current['revision'] if current else 0, author='system', task_report=marker, connection=connection)


def open_report(core, reference, identifier):
    with core.repository.definition_lock(), core.repository.connect() as connection:
        report = sync(core, connection, identifier, reference=reference)
        return {'document_id': report['document_root_id'], 'revision': report['revision']}


def refresh_document(core, marker, root):
    with core.repository.definition_lock(), core.repository.connect() as connection:
        # A retained report is still readable after its task has been removed.
        if not _workflow(connection, marker['workflow_id']):
            return None
        return sync(core, connection, marker['workflow_id'], expected_root=root)
