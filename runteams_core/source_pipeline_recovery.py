"""Read original native receipts before correcting an interrupted result envelope.

This never runs a tool, copies a professional result into a submission, or
resends the original task. Unconfirmed effects remain behind the existing gate.
"""
import json
import uuid

from .creator_contracts import canonical,digest


def inspect_terminal(core,frozen,native):
    from .source_pipeline_flow import _result
    from .contracts import ContractError
    thread=native.get('thread') or {};turns=thread.get('turns') or []
    if not turns or turns[-1].get('status') not in ('completed','interrupted'):return None
    turn=turns[-1];items=turn.get('items') or []
    if turn.get('itemsView')!='full' or not items or len(items)>5000:return None
    rejected=None
    for item in items:
        kind=item.get('type')
        if kind in ('userMessage','agentMessage','reasoning','plan'):continue
        # Native webSearch items carry read results, not an effect receipt or a
        # status field. They cannot authorize a write and are never replayed.
        if kind=='webSearch':continue
        if kind=='commandExecution':
            if item.get('status')!='completed':return None
            if item.get('exitCode') is None:return None
            continue
        if kind!='dynamicToolCall' or type(item.get('success'))is not bool:return None
        tool=item.get('tool');args=item.get('arguments') or {};operation=args.get('operation')
        if not item['success']:
            if tool!='runteams_pipeline_work' or operation!='submit' or item.get('status')!='failed':return None
            key=args.get('operation_id')
            try:
                if str(uuid.UUID(key))!=key:return None
                _result(frozen['package'],frozen['pipeline_work'],args.get('result'))
            except (ValueError,TypeError,AttributeError) as error:
                if not isinstance(error,ContractError):return None
                output=''.join(p.get('text','')for p in item.get('contentItems') or []if p.get('type')=='inputText')
                if not output or not str(error).startswith(output):return None
                rejected={'submission_id':key,'error':str(error)}
            else:return None
        elif item.get('status')!='completed':return None
        elif tool=='runteams_pipeline_work' and operation in ('read','read_report'):continue
        elif tool=='runteams_work_report' and operation=='read':continue
        elif tool=='runteams_get_document':continue
        elif tool=='runteams_work_report' and operation=='write':
            try:
                payload=next(json.loads(p['text'])for p in item['contentItems']if p.get('type')=='inputText')['data']
                document=core.document_detail(payload['report_id']);marker=core.artifact(document['id'])['meta_json']['work_report']
                if (not payload.get('ok') or document['revision']!=payload['document']['revision']
                        or marker['employee_run_id']!=frozen['employee_run_id']):return None
            except (KeyError,ValueError,StopIteration,TypeError):return None
        else:return None
    return {**rejected,'native_thread_id':thread['id'],'native_turn_id':turn['id'],
        'native_status':turn['status'],'trace_sha256':digest(items)} if rejected else None


def attested_proof(core,connection,frozen,session):
    repair=frozen.get('pipeline_result_correction') or {}
    if not repair.get('native_proof'):return None
    proof={k:v for k,v in repair.items()if k!='admitted'}
    row=connection.execute("SELECT data_json FROM events WHERE stream=? AND type='workflow.native_submission_reconciled' ORDER BY id DESC LIMIT 1",
        ('workflow_run:'+str((session.get('context')or{}).get('employee_work',{}).get('workflow_id')),)).fetchone()
    if not row or json.loads(row[0]).get('proof')!=proof:return None
    if (session.get('runtime_thread_id')!=proof.get('native_thread_id') or
            session.get('runtime_generation')!=proof.get('runtime_generation') or
            not session.get('messages') or session['messages'][-1]['id']!=proof.get('message_id')):return None
    return proof


def reconcile(core,identifier):
    import product_store,codex_threads
    from .source_pipeline_flow import _row,_save
    with core.repository.connect()as connection:
        row=_row(connection,identifier);frozen=json.loads(row['snapshot_json'])
    if (row['state'] not in ('paused','interrupted','needs_human') or
            not frozen.get('send_admitted') or frozen.get('pipeline_submission') or
            frozen.get('pipeline_applied_result') or frozen.get('pipeline_result_correction') or
            (frozen.get('pipeline_execution')or{}).get('active')):return False
    session=product_store.get_chat(frozen.get('work_chat_id'))or{}
    if (session.get('runtime_provider')!='codex' or not session.get('runtime_thread_id') or
            (session.get('context')or{}).get('pipeline_work')!=frozen['pipeline_work'] or
            (session.get('context')or{}).get('pipeline_generation')!=frozen['pipeline_generation']):return False
    channel=product_store.get_channel(session['channel_id'])
    if not channel or channel.get('provider')!='codex':return False
    try:
        native=codex_threads._single_thread_request(channel,
            'thread/read',{'threadId':session['runtime_thread_id'],'includeTurns':True},timeout=20)
    except PermissionError:raise
    except (RuntimeError,OSError,ValueError):return False
    if (native.get('thread')or{}).get('id')!=session['runtime_thread_id']:return False
    proof=inspect_terminal(core,frozen,native)
    if not proof or not session.get('messages'):return False
    proof.update(native_proof=True,message_id=session['messages'][-1]['id'],runtime_generation=session['runtime_generation'])
    with core.repository.connect()as connection:
        current=_row(connection,identifier);latest=json.loads(current['snapshot_json'])
        if latest!=frozen or current['state']=='running':return False
        if connection.execute("SELECT 1 FROM events WHERE stream=? AND type='pipeline.result_submitted'",
                ('source-pipeline-result:'+proof['submission_id'],)).fetchone():return False
        core.repository.event('workflow_run:'+str(identifier),'workflow.native_submission_reconciled',
            {'visit':frozen['pipeline_visit'],'proof':proof},connection=connection)
        frozen['pipeline_result_correction']={**proof,'admitted':False};frozen.pop('pipeline_unresolved',None)
        _save(core,connection,current,frozen,'ready')
    return True
