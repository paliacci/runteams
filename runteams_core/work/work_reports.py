"""Work reports are versioned documents, never a second store of report bodies.

The host owns employee/chat/work identity. Model input supplies only the title,
Markdown and expected revision; a report cannot mutate workflow state.
"""
import copy
import hashlib
import json
import re
from contextlib import nullcontext

from runteams_core.foundation.contracts import ContractError

SCHEMA = 'runteams.work-report/v1'
TOOL = 'runteams_work_report'
INPUT_SCHEMA = {'type':'object','properties':{
    'operation':{'type':'string','enum':['read','write']},
    'report_id':{'type':'integer','minimum':1},
    'title':{'type':'string','minLength':1,'maxLength':200},
    'content':{'type':'string','minLength':1},
    'document':{'type':'object','description':'可选的 runteams.rich-document/1 内容，包含 blocks 与随文档保存的 sources 快照；不是实时查询。'},
    'base_revision':{'type':'integer','minimum':0}},
    'required':['operation'],'additionalProperties':False}


def _arguments(value):
    if not isinstance(value,dict) or set(value)-set(INPUT_SCHEMA['properties']):
        raise ContractError('汇报参数无效。')
    if value.get('operation') not in ('read','write'):
        raise ContractError('请选择读取或保存汇报。')
    for key,minimum in [('report_id',1),('base_revision',0)]:
        if key in value and (type(value[key]) is not int or value[key]<minimum):
            raise ContractError('汇报标识或版本无效。')
    if value['operation']=='write':
        if 'base_revision' not in value:raise ContractError('保存汇报需要刚读取的版本；首次创建使用0。')
        if not isinstance(value.get('content'),str) or not value['content'].strip():
            raise ContractError('汇报正文不能为空。')
        if len(value['content'].encode())>2*1024*1024:raise ContractError('汇报正文超过2 MB。')
    if 'title' in value and (not isinstance(value['title'],str) or not value['title'].strip() or len(value['title'])>200):
        raise ContractError('汇报名称无效。')
    if 'document' in value:
        from runteams_core.documents.rich_documents import validate
        validate(value['document'])
    return value


def catalog(core, *, reference=None, workflow_id=None, chat_id=None):
    """Return references only; listing records must not boot the document editor."""
    from runteams_core.employees.employee_references import same
    with core.repository.connect() as c:
        rows=c.execute('SELECT * FROM artifacts WHERE trashed_at IS NULL ORDER BY id DESC').fetchall()
    seen=set();items=[]
    for row in rows:
        meta=json.loads(row['meta_json']);root=int(meta.get('revision_of') or row['id'])
        if root in seen:continue
        seen.add(root);report=meta.get('work_report') or {}
        if report.get('schema')!=SCHEMA:continue
        if reference is not None and not same(report.get('employee_reference'),reference):continue
        if workflow_id is not None and report.get('workflow_id')!=workflow_id:continue
        if chat_id is not None and report.get('chat_id')!=chat_id:continue
        items.append({'id':root,'revision':int(meta.get('revision') or 1),
            'name':row['name'],'updated_at':row['created_at'],
            'document_key':meta.get('document_key',''),
            'summary':report.get('summary',''),'binding':copy.deepcopy(report)})
    return items


def reference(item):
    return {key:item[key] for key in ('id','revision','name','updated_at','document_key')}


def _agent_document(document):
    # Native editor capabilities/URLs belong to the UI, not model context.
    result={key:copy.deepcopy(document[key]) for key in
            ('id','name','document_key','revision','content_model','content','created_at') if key in document}
    if document.get('content_model')=='rich-document' and 'content' in document:
        from runteams_core.documents import rich_documents
        result['rich_document']=rich_documents.validate(document['content'])
        result['content']=rich_documents.narrative(result['rich_document'])
    return result


def _summary(content):
    lines=[line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    text=next(iter(lines),'')
    # Code and escaped punctuation are literal evidence, including underscores
    # in tool names. Never strip individual punctuation characters from prose.
    literals={}
    prefix='\x00'+hashlib.sha256(text.encode()).hexdigest()+':'
    def literal(match):
        key=prefix+str(len(literals))+'\x00'
        literals[key]=match.group(2) if match.group(1) else match.group(3)
        return key
    text=re.sub(r'(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)|\\([\\`*_\[\]])',literal,text)
    text=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',text)
    text=re.sub(r'\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)\*(?=\S)([^*]+?)(?<=\S)\*(?!\w)',
                lambda match:match.group(1) or match.group(2),text)
    # In-word underscores and double-underscore identifiers remain literal.
    text=re.sub(r'(?<![\w_])_(?=\S)([^_]+?)(?<=\S)_(?![\w_])',r'\1',text)
    for key,value in literals.items():text=text.replace(key,value)
    return text[:240]


def _key(binding,title):
    if binding.get('employee_run_id'):return 'work-report-workflow-'+str(binding['workflow_id'])+'-attempt-'+str(binding['employee_run_id'])
    if binding.get('workflow_id'):return 'work-report-workflow-'+str(binding['workflow_id'])
    # One accepted request may contain several independent jobs. Their initial
    # titles distinguish first saves; all later edits use the returned root ID.
    token=hashlib.sha256(title.strip().encode()).hexdigest()[:20]
    return 'work-report-chat-'+str(binding['chat_id'])+'-'+str(binding['message_id'])+'-'+token


def _operate(core, arguments, binding, *, owner=nullcontext()):
    args=_arguments(arguments)
    # This lock/transaction is the same serialization boundary as document edits.
    # It also makes a first-save retry resolve the same document key.
    with owner, core.repository.definition_lock(),core.repository.connect() as c:
        items=catalog(core,workflow_id=binding.get('workflow_id')) if binding.get('workflow_id') else catalog(core,reference=binding['employee_reference'],chat_id=binding['chat_id'])
        if binding.get('employee_run_id'):items=[i for i in items if i['binding'].get('employee_run_id')==binding['employee_run_id']]
        selected=next((item for item in items if item['id']==args.get('report_id')),None)
        if args.get('report_id') and selected is None:raise PermissionError('这份汇报不属于当前工作。')
        if selected is None:
            candidates=[item for item in items if binding.get('workflow_id') or item['binding'].get('message_id')==binding.get('message_id')]
            if binding.get('workflow_id') or args.get('operation')=='read' or not args.get('title'):
                selected=candidates[0] if len(candidates)==1 else None
            else:
                selected=next((item for item in candidates if item['binding'].get('creation_title')==args['title'].strip()),None)
        if args['operation']=='read':
            if selected is None:return {'exists':False,'reports':[{**reference(i),'summary':i['summary']} for i in items[:20]]}
            doc=core.document_detail(selected['id'])
            return {'exists':True,'report_id':selected['id'],'document':_agent_document(doc),
                    'internal_link':'runteams://document/'+str(selected['id'])}
        current=core.document_detail(selected['id']) if selected else None
        revision=int(current['revision']) if current else 0
        title=(args.get('title') or (current or {}).get('name') or '').strip()
        if not title:raise ContractError('首次保存汇报需要工作名称。')
        from runteams_core.documents import rich_documents
        if current and current.get('content_model')!=rich_documents.MODEL:
            raise ContractError('请为本次工作新建汇报，原测试格式不再支持更新。')
        value = args.get('document') or rich_documents.from_markdown(args['content'])
        # Stable block identity makes a retried Markdown save byte-identical.
        if 'document' not in args:value['blocks'][0]['id']='report-body'
        if current and 'document' not in args:
            old=rich_documents.validate(current['content'])
            value['sources']=old['sources']
            value['blocks'] += [block for block in old['blocks'] if block['type'] in {'dataTable','barChart','jsonData','metric'}]
        body=rich_documents.encode(value)
        identical=current and current.get('content')==body and current['name']==title
        if args['base_revision']!=revision and not identical:
            return {'ok':False,'conflict':True,'current_revision':revision,
                    'message':'汇报已变化，请重新读取并合并最新内容后保存。'}
        key=selected['document_key'] if selected else _key(binding,title)
        if not selected and c.execute("SELECT 1 FROM artifacts WHERE json_extract(meta_json,'$.document_key')=? LIMIT 1",(key,)).fetchone():
            raise ContractError('原汇报或同标识文档已存在；请读取原文档，已删除时先恢复。')
        doc=rich_documents.write(core,name=title,document=value,document_id=selected['id'] if selected else None,
            document_key=key,base_revision=args['base_revision'],author='agent')
        if doc.get('conflict'):return doc

        row=c.execute('SELECT meta_json FROM artifacts WHERE id=?',(doc['id'],)).fetchone()
        meta=json.loads(row[0]);root=int(meta.get('revision_of') or doc['id'])
        marker=copy.deepcopy(selected['binding'] if selected else binding)
        marker.setdefault('creation_title',title)
        if 'created_at' not in marker:
            from runteams_core.storage.repository import utc_now
            marker['created_at']=utc_now()
        marker['summary']=_summary(rich_documents.narrative(value))
        meta['work_report']=marker
        if binding.get('workflow_id'):meta['workflow_id']=binding['workflow_id']
        c.execute('UPDATE artifacts SET meta_json=? WHERE id=?',(json.dumps(meta),doc['id']))
        return {'ok':True,'report_id':root,'document':_agent_document(doc),
                'internal_link':'runteams://document/'+str(root)}


def employee_call(arguments, context):
    from runteams_core.storage import product_store
    from runteams_core.storage import device_data
    from runteams_core.employees.employee_context import current as employee_context
    employee_host = employee_context()
    from runteams_core.employees.employee_references import same
    from runteams_core.work.device_work_services import current as device_work_service
    from runteams_core.foundation.identity.work_identity import principal
    expected=device_data.identity()
    if context.get('actor_id')!=principal(expected) or not device_data.personal():raise PermissionError('当前账户不能保存这份汇报。')
    employee=employee_host.resolve(context)
    if employee is None:raise PermissionError('请在已绑定员工的工作对话中维护汇报。')
    session=product_store.get_chat(context['chat_id'])
    if session.get('kind')!='general':raise ContractError('员工创作对话不生成工作汇报，请进入工作对话。')
    message=next((m for m in reversed(session.get('messages') or []) if m.get('role')=='user'),None)
    if not message:raise ContractError('原工作请求不存在。')
    binding={'schema':SCHEMA,'employee_reference':employee['reference'],'chat_id':session['id'],'message_id':message['id']}
    work=device_work_service(channel_resolver=product_store.get_channel)
    workflow_id=(session.get('context') or {}).get('employee_work',{}).get('workflow_id')
    if workflow_id:
        with work.repository.connect() as c:
            row=c.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?',(workflow_id,)).fetchone()
        frozen=json.loads(row[0]) if row else {}
        if frozen.get('work_chat_id')!=session['id'] or not same(frozen.get('employee_reference'),employee['reference']):
            raise PermissionError('原工作归属未能确认。')
        binding['workflow_id']=workflow_id
        if frozen.get('pipeline_work'):
            from runteams_core.pipelines.source_pipeline_control import check_chat_operation
            check_chat_operation(session['id'])
            if arguments.get('operation')=='write' and frozen.get('pipeline_submission'):
                raise ContractError('岗位结果已经提交，汇报版本已固定；请先完成本次交接。')
            binding['employee_run_id']=frozen['employee_run_id']
    with work.repository.audit_context(actor_id=principal(expected),source='agent_tool'):
        work._actor()
        result=_operate(work,arguments,binding,owner=employee_host.document_owner(session))
        device_data.check(expected)
        return result


def protocol_call(protocol, run, arguments):
    from runteams_core.documents.document_service import Documents
    # Use the already-authorized repository. Constructing another business core
    # could bootstrap a different storage adapter or account while running.
    class DocumentView(Documents):
        def __init__(self):
            self.root=protocol.repository_root
            self.repository=protocol.repository
    core=DocumentView()
    binding={'schema':SCHEMA,'workflow_id':int(run['workflow_run_id'])}
    return _operate(core,arguments,binding)


def apply_to_delivery(core, delivery, reports=None):
    reports=catalog(core,workflow_id=delivery['workflow_id']) if reports is None else reports
    if reports:
        report=reports[0];delivery['report_document']=reference(report)
        delivery['summary']=report['summary'] or delivery['summary']
        delivery['updated_at']=max(delivery['updated_at'],report['updated_at'])
    return delivery


def standalone_results(core, employee_reference):
    results=[]
    for report in catalog(core,reference=employee_reference):
        if report['binding'].get('workflow_id'):continue
        results.append({'key':'report-'+str(report['id']),'workflow_id':None,
            'title':report['name'],'state':'recorded','summary':report['summary'],
            'created_at':report['binding'].get('created_at',report['updated_at']),'updated_at':report['updated_at'],
            'origin':{'kind':'employee_chat','chat_id':report['binding']['chat_id']},
            'report_document':reference(report),'contributions':[],'attempts':[],
            'outputs':[],'references':[]})
    return results


def signature(core,session,workflows):
    """Piggyback on the existing visible-chat poll; no body reads or new timer."""
    from runteams_core.employees.employee_references import same
    saved=session.get('context') or {}
    employee=saved.get('source_employee') or saved.get('employee_reference')
    ids={row['workflow_id'] for row in workflows}
    visible=[(report['id'],report['revision'],report['updated_at']) for report in catalog(core)
        if report['binding'].get('chat_id')==session['id']
        or employee is not None and same(report['binding'].get('employee_reference'),employee)
        or report['binding'].get('workflow_id') in ids]
    return hashlib.sha256(json.dumps(visible,sort_keys=True).encode()).hexdigest() if visible else 'none'
