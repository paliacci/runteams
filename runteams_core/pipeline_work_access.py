"""Trusted pipeline workspace projections and original work admission adapter.

Never exposes employee snapshots/directories or a writable workflow cursor.
Conversation and Apps share this adapter; professional handoffs stay in R05.
"""
import local_references
import copy
import hashlib
import json
import uuid

from . import device_data, source_pipeline_work as work, source_pipeline_control as control
from .creator_contracts import canonical, digest
from .contracts import ContractError

READ_TOOL = 'runteams_pipeline_workspace'
PROPOSE_TOOL = 'runteams_propose_pipeline_work'
READ_SCHEMA = {'type':'object','properties':{
    'operation':{'type':'string','enum':['list','read','read_report','contract','receipt']},
    'workflow_id':{'type':'integer','minimum':1}, 'report_id':{'type':'integer','minimum':1},
    'revision':{'type':'integer','minimum':1}, 'limit':{'type':'integer','minimum':1,'maximum':100},
    'cursor':{'type':'string'},'operation_id':{'type':'string'},'start_column_key':{'type':'string'}},
    'required':['operation'],'additionalProperties':False}
PROPOSE_SCHEMA = {'type':'object','properties':{
    'operation_id':{'type':'string','pattern':'^[0-9a-f-]{36}$'},
    'title':{'type':'string','minLength':1,'maxLength':200},
    'payload':{'type':'object'},'start_column_key':{'type':'string'}},
    'required':['operation_id','title','payload'],'additionalProperties':False}


def bound(chat_id, actor_id=None):
    from .pipeline_context import current as pipeline_context
    scope=device_data.identity()
    from .work_identity import principal
    if actor_id is not None and actor_id!=principal(scope):
        raise PermissionError('账户已变化，请重新打开流水线。')
    return pipeline_context().binding(chat_id)


def _validate(schema, arguments):
    from jsonschema import Draft202012Validator
    if (not isinstance(arguments,dict) or len(canonical(arguments))>96*1024 or
            next(Draft202012Validator(schema).iter_errors(arguments),None)):
        raise ContractError('流水线工作请求无效。')


def _asset(core, ref):
    saved=control.read(core,ref)
    if saved['bundle']:return saved,saved['bundle']['asset'],saved['bundle']['revision']
    from .pipeline_context import current as pipeline_context
    revision,asset=pipeline_context().definition(ref)
    return saved,asset,revision


def _row(connection, ref, identifier):
    if type(identifier) is not int or not 0<identifier<2**53:raise ContractError('工作引用无效。')
    row=connection.execute('SELECT w.*,t.title,t.trashed_at FROM workflow_runs w JOIN tasks t ON t.id=w.task_id WHERE w.id=?',
        (identifier,)).fetchone()
    if not row or row['trashed_at']:raise PermissionError('这项工作不存在或已移入垃圾箱。')
    frozen=json.loads(row['snapshot_json'])
    if (frozen.get('pipeline_work') or {}).get('reference')!=ref:
        raise PermissionError('这项工作不属于当前流水线。')
    work.verify_context(frozen['pipeline_work'],frozen['package'])
    return row,frozen


def _report_references(connection, identifier, frozen):
    references=[]
    for run in connection.execute('SELECT id,output_json FROM employee_runs WHERE workflow_run_id=? ORDER BY id', (identifier,)):
        references.extend((run['id'],ref) for ref in json.loads(run['output_json']).get('report_references',[]))
    references.extend((frozen.get('employee_run_id'),ref) for ref in (frozen.get('pipeline_submission') or {}).get('reports',[]))
    result={}
    for run_id,ref in references:
        artifact=connection.execute('SELECT meta_json,trashed_at FROM artifacts WHERE id=?',(ref.get('artifact_id'),)).fetchone()
        if not artifact or artifact['trashed_at']:
            result[(ref['id'],ref['revision'])]={**copy.deepcopy(ref),'employee_run_id':run_id,'available':False}
            continue
        meta=json.loads(artifact['meta_json']);binding=meta.get('work_report') or {}
        if (binding.get('workflow_id')!=identifier or binding.get('employee_run_id')!=run_id or
                meta.get('revision_of')!=ref.get('id') or meta.get('revision',1)!=ref.get('revision') or
                meta.get('sha256')!=ref.get('sha256')):
            raise ContractError('正式汇报与原工作或固定版本不一致。')
        result[(ref['id'],ref['revision'])]={**copy.deepcopy(ref),'employee_run_id':run_id,'available':True}
    return list(result.values())


def _summary(row, frozen):
    definition=frozen['pipeline_work']['asset']['pipeline']
    position=next((p for p in definition['positions'] if p['key']==row['cursor_key']),None)
    if position is None:
        state=next(p for p in definition.get('states',[]) if p['key']==row['cursor_key'])
        position={**state,'kind':'state'}
    submission=frozen.get('pipeline_submission') or {}
    return {'workflow_id':row['id'],'task_id':row['task_id'],'title':row['title'],'state':row['state'],
        'position':{key:position[key] for key in ('key','name','kind','prompt') if key in position},
        'visit':frozen['pipeline_visit'],'generation':frozen['pipeline_generation'],
        'updated_at':row['updated_at'],'summary':submission.get('result',{}).get('summary') or (frozen.get('pipeline_feedback') or {}).get('summary',''),
        'summary_position_key':frozen['pipeline_work']['position_key'] if submission else (frozen.get('pipeline_feedback') or {}).get('from'),
        'waiting':copy.deepcopy(frozen.get('pipeline_waiting')),
        'handoff_issue':copy.deepcopy(frozen.get('pipeline_handoff')),
        'needs_reconciliation':bool(frozen.get('pipeline_unresolved') or frozen.get('send_admitted') and row['state'] in ('interrupted','needs_human','failed')),
        'settlement_pending':bool(frozen.get('pipeline_recovery_pending')),
        'error':frozen.get('pipeline_program_error','')}


def read(core, chat_id, arguments, *, actor_id=None):
    scope=device_data.identity();ref=bound(chat_id,actor_id);core._actor();_validate(READ_SCHEMA,arguments)
    operation=arguments['operation']
    fields={'list':{'limit','cursor'},'read':{'workflow_id'},
        'read_report':{'workflow_id','report_id','revision'},'contract':{'start_column_key'},'receipt':{'operation_id'}}[operation]
    required=fields if operation in ('read','read_report','receipt') else set()
    if set(arguments)-{'operation'}-fields or not required<=set(arguments):raise ContractError('工作读取参数不完整或包含多余字段。')
    if operation=='contract':
        saved,asset,revision=_asset(core,ref)
        contract=control.dispatch_contract(core,ref,arguments.get('start_column_key'))
        result={**contract,'generation':(saved['bundle'] or {}).get('generation',0),'source_revision':revision,
            'status':saved['status'],'positions':[{k:p[k] for k in ('key','name','kind')} for p in asset['pipeline']['positions']]}
    elif operation=='receipt':
        operation_id=_admission_id(chat_id,arguments['operation_id'])
        with core.repository.connect() as connection:
            row=connection.execute("SELECT data_json FROM events WHERE stream=? AND type='pipeline.work_admitted' ORDER BY id DESC LIMIT 1",
                ('source-pipeline-operation:'+operation_id,)).fetchone()
            if row:
                identifier=json.loads(row[0])['workflow_id'];current,frozen=_row(connection,ref,identifier)
                result={'status':'committed','operation_id':arguments['operation_id'],'work':_summary(current,frozen)}
            else:result={'status':'unknown','operation_id':arguments['operation_id']}
    else:
        with core.repository.connect() as connection:
            if operation=='list':
                saved,asset,revision=_asset(core,ref)
                cursor=arguments.get('cursor','')
                if cursor and (not cursor.isdecimal() or len(cursor)>16):raise ContractError('工作分页位置无效。')
                limit=arguments.get('limit',50)
                rows=connection.execute("SELECT w.id FROM workflow_runs w JOIN tasks t ON t.id=w.task_id "
                    "WHERE t.trashed_at IS NULL AND json_extract(w.snapshot_json,'$.pipeline_work.reference.source_id')=? "
                    "AND json_extract(w.snapshot_json,'$.pipeline_work.reference.pipeline_source')=? AND json_extract(w.snapshot_json,'$.pipeline_work.reference.schema')=? AND w.id<? ORDER BY w.id DESC LIMIT ?",
                    (ref['source_id'],ref['pipeline_source'],ref['schema'],int(cursor) if cursor else 2**53,limit+1)).fetchall()
                items=[];size=0
                for entry in rows[:limit]:
                    item=_summary(*_row(connection,ref,entry['id']));count=len(canonical(item))
                    if items and size+count>256*1024:break
                    items.append(item);size+=count
                counts={r['state']:r['n'] for r in connection.execute(
                    "SELECT w.state,count(*) AS n FROM workflow_runs w JOIN tasks t ON t.id=w.task_id "
                    "WHERE t.trashed_at IS NULL AND json_extract(w.snapshot_json,'$.pipeline_work.reference.source_id')=? "
                    "AND json_extract(w.snapshot_json,'$.pipeline_work.reference.pipeline_source')=? "
                    "AND json_extract(w.snapshot_json,'$.pipeline_work.reference.schema')=? GROUP BY w.state",
                    (ref['source_id'],ref['pipeline_source'],ref['schema']))}
                operations=[json.loads(r[0]) for r in connection.execute(
                    "SELECT data_json FROM events WHERE type='pipeline.workspace_admitted' "
                    "AND json_extract(data_json,'$.chat_identity')=? ORDER BY id DESC LIMIT 50",(device_data.epoch(chat_id),))]
                runtime=control.state(core,ref)
                result={'name':asset['pipeline']['name'],'pipeline':copy.deepcopy(asset['pipeline']),'counts':counts,'total':sum(counts.values()),
                    'runtime':{'status':runtime['status'],'revision':saved['revision'],
                    'source_revision':revision,'generation':(saved['bundle'] or {}).get('generation',0),'pause_error':saved.get('pause_error','')},
                    'items':items,'recent_operations':[{'operation_id':r['operation_id'],'workflow_id':r['workflow_id']} for r in operations],'next_cursor':str(rows[len(items)-1]['id']) if len(rows)>len(items) else None}
            else:
                row,frozen=_row(connection,ref,arguments['workflow_id'])
                reports=_report_references(connection,row['id'],frozen)
                if operation=='read':
                    attempts=[];seen=set()
                    for visit in [*(item['snapshot'] for item in frozen.get('pipeline_history',[])),frozen]:
                        run_id=visit.get('employee_run_id')
                        if not run_id or run_id in seen:continue
                        seen.add(run_id)
                        attempt=connection.execute('SELECT state FROM employee_runs WHERE id=? AND workflow_run_id=?',(run_id,row['id'])).fetchone()
                        if not attempt:raise ContractError('岗位访问记录无法核对。')
                        attempts.append({'visit':visit['pipeline_visit'],'position_key':visit['pipeline_work']['position_key'],
                            'state':attempt['state'],'employee_run_id':run_id})
                    result={**_summary(row,frozen),'attempts':attempts,'reports':reports,
                        'result':copy.deepcopy((frozen.get('pipeline_submission') or {}).get('result'))}
                else:
                    selected=next((r for r in reports if r['id']==arguments['report_id'] and r['revision']==arguments['revision']),None)
                    if selected is None:raise PermissionError('这份汇报版本不属于当前流水线工作的正式交付。')
                    if not selected['available']:raise ContractError('原正式汇报已删除或暂不可用，请核对原工作记录。')
                    from .work_reports import _agent_document
                    document=core.historical_document_detail(selected['artifact_id'])
                    if not document or document['revision']!=selected['revision'] or hashlib.sha256(document['content'].encode()).hexdigest()!=selected['sha256']:
                        raise ContractError('原正式汇报的固定内容无法核对。')
                    result={'reference':selected,'document':_agent_document(document)}
    device_data.check(scope)
    return {**result,'read_only':True,'storage_scope':'device'}


def _admission_id(chat_id, operation_id):
    try:
        if str(uuid.UUID(operation_id))!=operation_id:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ContractError('请保留原工作操作编号。') from None
    return str(uuid.uuid5(uuid.UUID(operation_id),'pipeline-work:'+device_data.epoch(chat_id)))


def proposal(core, chat_id, arguments, *, actor_id=None, composer=True):
    ref=bound(chat_id,actor_id);_validate(PROPOSE_SCHEMA,arguments)
    _admission_id(chat_id,arguments['operation_id'])
    saved,asset,revision=_asset(core,ref)
    if saved['status']!='running':raise ContractError('流水线已暂停，不能交办新工作。')
    payload=copy.deepcopy(arguments['payload'])
    work._request({'operation_id':arguments['operation_id'],'reference':ref,'title':arguments['title'],'payload':payload})
    if payload.get('module_bindings'):
        raise PermissionError('共享业务授权必须沿原资料入口核对。')
    contract=control.dispatch_contract(core,ref,arguments.get('start_column_key'))
    if composer:
        import product_store,local_references
        messages=product_store.get_chat(chat_id).get('messages') or []
        index=next((i for i in range(len(messages)-1,-1,-1) if messages[i]['role']=='user'),None)
        source=local_references.conversation_source(messages[index].get('attachments') or [],messages[:index]) if index is not None else {}
        available={r['grant_id'] for r in source.get('available_local_references',[])}
        mapping={}
        for key,value in payload.get('asset_bindings',{}).items():
            if not isinstance(value,str) or not value.isdecimal() or int(value) not in available:
                raise PermissionError('只能交办本次对话中用户实际提供的资料。')
            mapping[key]=int(value)
        for item in payload.get('inputs',[]):
            grant=item.get('asset_grant_id')
            if grant is not None:
                if not isinstance(grant,str) or not grant.isdecimal() or int(grant) not in available:
                    raise PermissionError('任务资料不能携带未经核对的本机授权。')
                local_references.reference(int(grant))
        if mapping or source.get('local_references'):
            bindings,extra=local_references.bind_task({'asset_bindings':mapping},contract['assets'],source)
            payload['asset_bindings']={key:str(value) for key,value in bindings.items()}
            existing={item.get('asset_grant_id') for item in payload.get('inputs',[])}
            payload.setdefault('inputs',[]).extend({'name':item['name'],'asset_grant_id':str(item['grant_id'])}
                for item in extra if str(item['grant_id']) not in existing)
    elif payload.get('asset_bindings') or any(item.get('asset_grant_id') for item in payload.get('inputs',[])):
        raise PermissionError('作者页面不能借用用户会话的本机资料授权。')
    if set(payload.get('context',{})) & {'pipeline_stage','employee_work','pipeline_work','dispatch_authorization_event_id'}:
        raise PermissionError('任务内容不能声明岗位身份或交接授权。')
    data={'operation_id':arguments['operation_id'],'reference':ref,'title':arguments['title'],'payload':payload,
        **({'start_column_key':arguments['start_column_key']} if 'start_column_key' in arguments else {})}
    work._request(data)
    parameters=asset['pipeline'].get('parameters',[])
    if parameters and set(payload.get('parameters',{}))-{p['key'] for p in parameters if p.get('source')=='user' and p['type']!='secret'}:
        raise ContractError('不能由任务创建者代填员工产出。')
    if contract['kind']=='employee':
        from .creator_validation import validate_data
        validate_data(contract['input_schema'],payload.get('parameters',{}))
    data['payload']=payload
    action={'op':'create_pipeline_work',**data,'source_revision':revision,'generation':(saved['bundle'] or {}).get('generation',0)}
    return {'summary':'交给「'+asset['pipeline']['name']+'」处理「'+arguments['title']+'」','actions':[action],'count':1}


def committed(core, chat_id, arguments):
    """Recover the original admission even while paused; never starts work."""
    ref=bound(chat_id);_validate(PROPOSE_SCHEMA,arguments)
    request={**copy.deepcopy(arguments),'reference':ref,'operation_id':_admission_id(chat_id,arguments['operation_id'])}
    key,normalized=work._request(request)
    identifier=work._receipt(core,key,normalized)
    if identifier is None:return None
    return read(core,chat_id,{'operation':'receipt','operation_id':arguments['operation_id']})


def dispatch_app(core, chat_id, action, guard, notify=None):
    """Only the host's completed native approval may enter this transaction."""
    core._actor();bound(chat_id)
    with core.repository.connect() as connection:
        guard()
        authorization=core.repository.event('chat:'+str(chat_id),'task.dispatch_authorized',
            {'chat_id':chat_id,'device_chat_identity':device_data.epoch(chat_id),'surface':'pipeline-app'},
            source='native_app',connection=connection)
        apply_action(core,action,{'chat_id':chat_id,'dispatch_authorization_event_id':authorization})
    if notify is not None:
        try:notify()
        except Exception:__import__('logging').getLogger(__name__).exception('Pipeline work admitted; worker wake needs recovery')
    return read(core,chat_id,{'operation':'receipt','operation_id':action['operation_id']})


def apply_action(core, action, source):
    """Called only by the original authorized action transaction, never Apps."""
    chat_id=(source or {}).get('chat_id');ref=bound(chat_id)
    allowed={'op','operation_id','reference','title','payload','source_revision','generation','start_column_key'}
    if (not isinstance(action,dict) or set(action)-allowed or not (allowed-{'start_column_key'})<=set(action)
            or action.get('reference')!=ref):
        raise PermissionError('交办事项不属于当前流水线。')
    request={key:copy.deepcopy(action[key]) for key in ('operation_id','reference','title','payload','start_column_key') if key in action}
    request['operation_id']=_admission_id(chat_id,action['operation_id'])
    key,normalized=work._request(request)
    with core.repository.connect() as connection:
        authorization=connection.execute('SELECT type,data_json FROM events WHERE id=?',((source or {}).get('dispatch_authorization_event_id'),)).fetchone()
        grant=json.loads(authorization['data_json']) if authorization else {}
        if (not authorization or authorization['type']!='task.dispatch_authorized' or grant.get('chat_id')!=chat_id
                or grant.get('device_chat_identity')!=device_data.epoch(chat_id)):
            raise PermissionError('请通过原用户交办或确认入口受理。')
        previous=work._receipt(core,key,normalized,connection)
        if previous is None:
            saved,_,revision=_asset(core,ref)
            if action.get('source_revision')!=revision or action.get('generation')!=(saved['bundle'] or {}).get('generation',0):
                raise ContractError('流水线已更新，请按当前岗位和输入重新核对交办事项。')
            # Revalidate the same submitted fields; this does not supply a
            # professional conclusion, bypass pause, or approve an edge.
            proposal(core,chat_id,{k:action[k] for k in ('operation_id','title','payload','start_column_key') if k in action},
                composer=grant.get('surface')!='pipeline-app')
        result=work.create(core,request)
        stream='source-pipeline-workspace-operation:'+key
        if not connection.execute("SELECT 1 FROM events WHERE stream=? AND type='pipeline.workspace_admitted'",(stream,)).fetchone():
            core.repository.event(stream,'pipeline.workspace_admitted',{'chat_identity':device_data.epoch(chat_id),
                'operation_id':action['operation_id'],'workflow_id':result['workflow']['id']},connection=connection)
    workflow=result['workflow']
    return '已受理「'+action['title']+'」',{'run_card':{'workflow_id':workflow['id'],'task_id':workflow['task_id'],
        'title':action['title'],'state':workflow['state'],'pipeline_reference':ref,'storage_scope':'device'}}
