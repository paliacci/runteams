"""Work reports are versioned documents, never a second store of report bodies.

The host owns employee/chat/work identity. Model input supplies report content
and the expected revision; a report cannot mutate workflow state.
"""
import base64
import copy
import hashlib
from io import BytesIO
import json
import os
import stat
from pathlib import Path, PurePosixPath
import re
from contextlib import ExitStack, nullcontext

from runteams_core.foundation.contracts import ContractError
from runteams_core.documents import reply_visualizations

SCHEMA = 'runteams.work-report/v1'
TOOL = 'runteams_work_report'
ATTACHMENTS = {'attach_image': ('image', 'image'), 'attach_audio': ('file', 'audio'), 'attach_video': ('video', 'video')}
INPUT_SCHEMA = {'type':'object','properties':{
    'operation':{'type':'string','enum':['read','write',*ATTACHMENTS,'followup_list','followup_read','followup_append']},
    'report_id':{'type':'integer','minimum':1},
    'title':{'type':'string','minLength':1,'maxLength':200},
    'content':{'type':'string','minLength':1},
    'document':{'type':'object','description':'可选的 runteams.rich-document/1 内容，包含 blocks 与随文档保存的 sources 快照；不是实时查询。'},
    'workflow_id':{'type':'integer','minimum':1}, 'revision':{'type':'integer','minimum':1},
    'cursor':{'type':'integer','minimum':0}, 'observed_at':{'type':'string'}, 'source_url':{'type':'string'},
    'metrics':{'type':'object'}, 'visualization':reply_visualizations.INPUT,
    'path':{'type':'string','description':'Relative output/ path for a prepared Markdown deliverable (write instead of content), or a media attachment.'},
    'base_revision':{'type':'integer','minimum':0}},
    'required':['operation'],'additionalProperties':False}


def _arguments(value):
    if not isinstance(value,dict) or set(value)-{'operation','report_id','title','content','document','visualization','path','base_revision'}:
        raise ContractError('汇报参数无效。')
    if value.get('operation') not in ('read','write',*ATTACHMENTS):
        raise ContractError('请选择读取或保存汇报。')
    for key,minimum in [('report_id',1),('base_revision',0)]:
        if key in value and (type(value[key]) is not int or value[key]<minimum):
            raise ContractError('汇报标识或版本无效。')
    if value['operation'] in ATTACHMENTS:
        if set(value)!={'operation','report_id','base_revision','path'} or not isinstance(value['path'],str):
            raise ContractError('添加附件需要汇报编号、当前修订号和 output 下的文件路径。')
    elif 'path' in value:
        raise ContractError('请使用对应的添加附件操作。')
    if value['operation']=='write':
        if 'base_revision' not in value:raise ContractError('保存汇报需要刚读取的版本；首次创建使用0。')
        if not isinstance(value.get('content'),str) or not value['content'].strip():
            raise ContractError('汇报正文不能为空。')
        if len(value['content'].encode())>2*1024*1024:raise ContractError('汇报正文超过2 MB。')
    elif 'visualization' in value:
        raise ContractError('请通过保存汇报提交可视化。')
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
        rows=c.execute('SELECT id,name,created_at,meta_json FROM artifacts WHERE trashed_at IS NULL ORDER BY id DESC').fetchall()
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


def _output_bytes(directory, relative, limit):
    if not isinstance(relative, str):
        raise ContractError('请提供工作文件的相对路径。')
    path = PurePosixPath(relative)
    if (len(relative) > 240 or '\\' in relative or '\x00' in relative
            or len(path.parts) < 2 or path.parts[0] != 'output' or '..' in path.parts):
        raise ContractError('请选择当前工作 output 文件夹中的文件。')
    try:
        with ExitStack() as opened:
            parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            opened.callback(os.close, parent)
            for part in path.parts[:-1]:
                parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                opened.callback(os.close, parent)
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ContractError('请选择普通文件。')
                raw = stream.read(limit + 1)
    except OSError as error:
        raise ContractError('工作文件不存在、打不开或为链接。') from error
    if not raw or len(raw) > limit:
        raise ContractError(f'请选择不超过 {limit // 1024**2} MB 的非空文件。')
    return path, raw


def _work_attachment(directory, relative, kind):
    from runteams_core.documents.rich_document_assets import MAX_FILE

    path, raw = _output_bytes(directory, relative, MAX_FILE)
    evidence = {'sha256':hashlib.sha256(raw).hexdigest(), 'size':len(raw)}
    if kind == 'audio':
        # The producer checks full decoding and timing before it attaches the MP3.
        if path.suffix.lower() != '.mp3' or len(raw)<128 or not (
                raw.startswith(b'ID3') or raw[0]==0xff and raw[1]&0xe0==0xe0):
            raise ContractError('配音附件必须是 MP3。')
        mime = 'audio/mpeg'
    elif kind == 'video':
        if path.suffix.lower() != '.mp4' or len(raw)<128 or raw[4:8]!=b'ftyp':
            raise ContractError('视频附件必须是 MP4。')
        mime = 'video/mp4'
    else:
        from PIL import Image
        try:
            with Image.open(BytesIO(raw)) as image:
                mime = {'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}.get(image.format)
                if not mime:
                    raise ContractError('成品图片须为 PNG、JPEG 或 WebP。')
                width, height = image.size
                image.verify()
        except (OSError, Image.DecompressionBombError) as error:
            raise ContractError('成品图片打不开。') from error
        evidence = {'width':width,'height':height,'sha256':evidence['sha256']}
    file = {'name':path.name,'type':mime,'data':'data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii')}
    return file, evidence


def _operate(core, arguments, binding, *, owner=nullcontext(), output_directory=None):
    if arguments.get('operation') == 'write' and 'path' in arguments:
        if output_directory is None:
            raise ContractError('当前工作没有文件入口，请直接提交 Markdown 正文。')
        if 'content' in arguments or 'document' in arguments:
            raise ContractError('请在文件路径与正文之间选择一项。')
        arguments = dict(arguments)
        path, raw = _output_bytes(output_directory, arguments.pop('path'), 2 * 1024**2)
        if path.suffix.lower() != '.md':
            raise ContractError('工作成果正文需要 Markdown (.md) 文件。')
        try:
            arguments['content'] = raw.decode('utf-8-sig')
        except UnicodeDecodeError as error:
            raise ContractError('工作成果需要 UTF-8 编码的 Markdown。') from error
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
        attachment_result = {}
        if args['operation'] in ATTACHMENTS:
            block_type, kind = ATTACHMENTS[args['operation']]
            if output_directory is None or current is None:
                raise ContractError('请在当前智能体团队工作中先保存工作汇报，再添加附件。')
            if args['base_revision'] not in (revision, revision-1):
                return {'ok':False,'conflict':True,'current_revision':revision,
                    'message':'汇报已变化，请重新读取后再添加附件。'}
            from runteams_core.documents import rich_document_assets
            file,evidence=_work_attachment(output_directory,args['path'],kind)
            value=rich_documents.validate(current['content'])
            # Calculate the same content identifier for a retry, before uploading new bytes.
            attachment=rich_document_assets.attachment_id(selected['id'], file)
            attachment_result={kind:{'asset_id':attachment,**evidence}}
            if any(b['type']==block_type and b['props'].get('assetId')==attachment for b in value['blocks']):
                return {'ok':True,'report_id':selected['id'],'document':_agent_document(current),
                        'internal_link':'runteams://document/'+str(selected['id']),
                        **attachment_result}
            if args['base_revision']!=revision:
                return {'ok':False,'conflict':True,'current_revision':revision,
                        'message':'汇报已变化，请重新读取后再添加附件。'}
            rich_document_assets.upload(core,selected['id'],file)
            value['blocks'].append({'id':'work-'+kind+'-'+attachment, 'type':block_type,
                                    'props':{'assetId':attachment,'name':file['name'],'mime':file['type']}})
        else:
            value = args.get('document') or rich_documents.from_markdown(args['content'])
            # Stable block identity makes a retried Markdown save byte-identical.
            if 'document' not in args:value['blocks'][0]['id']='report-body'
            if current and 'document' not in args:
                old=rich_documents.validate(current['content'])
                value['sources']=old['sources']
                value['blocks'] += [block for block in old['blocks']
                                    if block['type'] in {'dataTable','barChart','jsonData','metric','image','video','file'}
                                    or reply_visualizations.is_generated(block)]
        if 'visualization' in args:
            value=reply_visualizations.apply(value,args['visualization'])
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

        row=c.execute('SELECT * FROM artifacts WHERE id=?',(doc['id'],)).fetchone()
        if core._read_document_body(row) != body:
            raise ContractError('保存的工作成果未能完整读回，请核对原文档。')
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
                'internal_link':'runteams://document/'+str(root),
                **attachment_result}


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
    from runteams_core.pipelines import scheduled_followup
    if arguments.get('operation') in scheduled_followup.OPERATIONS:
        with work.repository.audit_context(actor_id=principal(expected), source='agent_tool'):
            work._actor()
            scope = scheduled_followup.scope_for_chat(session['id'], employee['reference'])
            result = scheduled_followup.operate(work, employee['reference'], scope, arguments)
            device_data.check(expected)
            return result
    output_directory=None
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
            if arguments.get('operation') in ('write',*ATTACHMENTS) and frozen.get('pipeline_submission'):
                raise ContractError('岗位结果已经提交，汇报版本已固定；请先完成本次交接。')
            binding['employee_run_id']=frozen['employee_run_id']
            binding['kind']='pipeline_stage'
    if ((arguments.get('operation') == 'write' and 'path' in arguments)
            or (binding.get('kind') == 'pipeline_stage' and arguments.get('operation') in ATTACHMENTS)):
        from runteams_core.conversations.conversation_folders import runtime
        from runteams_core.employees.employee_workspaces import workspace
        output_directory = Path(runtime(session['id'], workspace(session['id'])))
    with work.repository.audit_context(actor_id=principal(expected),source='agent_tool'):
        work._actor()
        result=_operate(work,arguments,binding,owner=employee_host.document_owner(session),
                        output_directory=output_directory)
        if binding.get('kind') == 'pipeline_stage':
            from runteams_core.pipelines.pipeline_task_report import _root
            with work.repository.connect() as connection:
                task = connection.execute('SELECT task_id FROM workflow_runs WHERE id=?', (workflow_id,)).fetchone()
                document = _root(connection, task['task_id']) if task else None
            if document and not document['trashed_at']:
                result['task_document_link'] = 'runteams://document/' + str(document['id'])
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
