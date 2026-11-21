"""Allow a scheduled team member to follow up on existing cards in its configured state."""
import hashlib
import json
from datetime import datetime
from urllib.parse import urlsplit

from runteams_core.automation.device_employee_schedules import EmployeeSchedules
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_references, pipeline_work_access, source_pipeline_control
from runteams_core.pipelines.pipeline_employee_dependencies import member_reference

EVENT = 'workflow.followup_recorded'
OPERATIONS = ('followup_list', 'followup_read', 'followup_append')


def targets(controller_factory, employee, skills):
    fields = {'followup_pipeline', 'followup_state'}
    eligible = [skill for skill in skills if fields <= set((skill.get('input_schema') or {}).get('properties', {}))
                and set((skill.get('input_schema') or {}).get('required', [])) <= fields]
    if not eligible or employee.get('schema') != 'runteams.local-employee-reference/1':
        return []
    core = controller_factory().core
    prefix = 'source-pipeline-runtime:' + employee['source_id'] + ':'
    result = []
    with core.repository.read_snapshot() as conn:
        streams = conn.execute('SELECT DISTINCT stream FROM events WHERE stream GLOB ? AND type=? ORDER BY stream',
                               (prefix + '*', source_pipeline_control.STATE_EVENT)).fetchall()
        for (stream,) in streams:
            path = stream[len(prefix):]
            ref = pipeline_references.reference(employee['source_id'], path)
            saved = source_pipeline_control.read(core, ref, conn)
            asset = (saved.get('bundle') or {}).get('asset', {})
            if saved['status'] != 'running' or not any(member_reference(ref, m) == employee for m in asset.get('employees', [])):
                continue
            pipeline = asset['pipeline']
            for skill in eligible:
                for state in pipeline['states']:
                    result.append({'skill_key': skill['key'], 'pipeline': path, 'state': state['key'],
                                   'name': pipeline['name'] + ' · ' + state['name']})
    return result


def occurrence(chat_id):
    schedules = EmployeeSchedules(None)
    with schedules.connection() as conn:
        return conn.execute('SELECT operation_id,snapshot,status FROM occurrences WHERE chat_id=?',
                            (chat_id,)).fetchone() if conn else None


def scope_for_chat(chat_id, employee):
    job = occurrence(chat_id)
    if not job or job['status'] not in ('running', 'queued'):
        raise PermissionError('此操作仅供正在执行的定时员工使用。')
    target = followup_scope(job, employee)
    if not target:
        raise PermissionError('计划未指定本团队的跟进位置。')
    return target


def followup_scope(job, employee):
    snap = json.loads(job['snapshot'])
    args = json.loads(snap['payload']).get('parameters', {})
    if json.loads(snap['reference']) != employee:
        raise PermissionError('计划不属于当前员工。')
    if (employee.get('schema') != 'runteams.local-employee-reference/1' or
            not args.get('followup_pipeline') or not args.get('followup_state')):
        return None
    ref = pipeline_references.reference(employee['source_id'], args['followup_pipeline'])
    return ref, args['followup_state'], job['operation_id']


def observed(value):
    try:
        instant = datetime.fromisoformat(value)
        if instant.utcoffset() is not None:
            return instant
    except (TypeError, ValueError):
        pass
    raise ContractError('观察时间必须带时区。')


def latest(connection, workflow_id):
    row = connection.execute('SELECT data_json FROM events WHERE stream=? AND type=? ORDER BY id DESC LIMIT 1',
                             ('workflow_run:'+str(workflow_id), EVENT)).fetchone()
    return json.loads(row[0]) if row else None


def operate(core, employee, scope, request):
    ref, state_key, occurrence = scope
    op = request['operation']
    allowed = {'followup_list': {'cursor'}, 'followup_read': {'workflow_id','report_id','revision'},
               'followup_append': {'workflow_id','base_revision','observed_at','source_url','metrics','content'}}
    if op not in allowed or set(request)-{'operation'}-allowed[op]:
        raise ContractError('跟进参数无效。')
    with core.repository.connect() as conn:
        if op == 'followup_append':
            conn.execute('BEGIN IMMEDIATE')
        saved = source_pipeline_control.read(core, ref, conn)
        asset = (saved.get('bundle') or {}).get('asset', {})
        if (saved['status'] != 'running' or not any(member_reference(ref, m)==employee for m in asset.get('employees', []))
                or not any(s['key']==state_key for s in asset.get('pipeline',{}).get('states',[]))):
            raise PermissionError('请核对运行中的团队、复盘员工和目标状态。')
        if op == 'followup_list':
            cursor = request.get('cursor',0)
            if type(cursor) is not int or cursor<0: raise ContractError('分页位置无效。')
            rows = conn.execute("""SELECT w.id,w.snapshot_json,t.title FROM workflow_runs w JOIN tasks t ON t.id=w.task_id
                WHERE t.trashed_at IS NULL AND w.cursor_key=? AND w.id>? AND
                json_extract(w.snapshot_json,'$.pipeline_work.reference.source_id')=? AND
                json_extract(w.snapshot_json,'$.pipeline_work.reference.pipeline_source')=? ORDER BY w.id LIMIT 51""",
                (state_key,cursor,ref['source_id'],ref['pipeline_source'])).fetchall()
            items = [{'workflow_id':r['id'],'title':r['title'],'latest':latest(conn,r['id'])} for r in rows[:50]
                     if json.loads(r['snapshot_json'])['pipeline_work']['reference']==ref]
            return {'items':items,'next_cursor':rows[49]['id'] if len(rows)>50 else None}
        wid = request.get('workflow_id')
        row, frozen = pipeline_work_access._row(conn, ref, wid)
        if row['cursor_key'] != state_key: raise PermissionError('任务已经离开本计划的目标位置。')
        previous = latest(conn,wid)
        if op == 'followup_read':
            reports = pipeline_work_access._report_references(conn,wid,frozen)
            if 'report_id' not in request and 'revision' not in request:
                return {'title':row['title'],'reports':reports,'latest':previous}
            selected = next((r for r in reports if r['available'] and r['id']==request.get('report_id')
                             and r['revision']==request.get('revision')),None)
            if not selected: raise PermissionError('只能读取这张卡已交付的报告版本。')
            document=core.historical_document_detail(selected['artifact_id'])
            if not document or hashlib.sha256(document['content'].encode()).hexdigest()!=selected['sha256']:
                raise ContractError('报告版本发生变化。')
            from runteams_core.work.work_reports import _agent_document
            return {'document':_agent_document(document),'reference':selected}
        if set(request)-{'operation'} != allowed[op]: raise ContractError('请提供完整的观察数据和来源。')
        data={k:request[k] for k in ('observed_at','source_url','metrics','content')}
        if (not isinstance(data['content'],str) or not 0<len(data['content'])<=4000
                or not isinstance(data['metrics'],dict) or len(json.dumps(data['metrics']))>4096
                or not isinstance(data['source_url'],str) or len(data['source_url'])>2048
                or urlsplit(data['source_url']).scheme not in ('https','http') or not urlsplit(data['source_url']).netloc):
            raise ContractError('观察数据或作品来源无效。')
        at=observed(data['observed_at'])
        version=(previous or {}).get('revision',0)
        stream='workflow_run:'+str(wid)
        prior=conn.execute("SELECT data_json FROM events WHERE stream=? AND type=? AND json_extract(data_json,'$.occurrence')=?",
                           (stream,EVENT,occurrence)).fetchone()
        if prior:
            old=json.loads(prior[0])
            if any(old[k]!=v for k,v in data.items()): raise ContractError('本次计划对该卡已有不同的观察。')
            return old
        if type(request['base_revision']) is not int or request['base_revision']!=version or (previous and at<=observed(previous['observed_at'])):
            raise ContractError('已有更新的观察，请重新读取任务。')
        result={**data,'revision':version+1,'occurrence':occurrence,'workflow_id':wid}
        core.repository.event(stream,EVENT,result,connection=conn)
        return result
