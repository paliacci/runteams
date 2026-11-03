"""Library ingress to canonical employee services, with no account RPCs."""
import json,re

def handles(path):
    return path in {'/api/employee-directory','/api/employee-directory/open','/api/employee-configuration/resources','/api/employee-configuration/resources/import','/api/local-references/pick','/api/local-references/confirm','/api/device/work/results','/api/device/work/files'} or bool(re.fullmatch(r'/api/chat/[1-9][0-9]*/(?:employee-configuration|employee-mcp|pipeline-mcp|pipeline-work|work)',path) or re.fullmatch(r'/api/device/work/chats/[1-9][0-9]*',path) or re.fullmatch(r'/api/(?:core|device/work)/workflows/[1-9][0-9]*(?:/(?:cancel|retry))?',path))

def dispatch(runtime,method,path,data):
    from .employee_directory import read,open_entry
    if path=='/api/employee-directory' and method=='GET' and not data:return read()
    if path=='/api/employee-directory/open' and method=='POST':return open_entry(data)
    work=re.fullmatch(r'/api/(?:chat/([1-9][0-9]*)/work|device/work/chats/([1-9][0-9]*))',path)
    if work and method=='GET' and not data:
        cid=int(work[1] or work[2]);session=runtime.chat(cid,include_live=False)
        from .conversation_work import conversation_work
        from .work_reports import signature
        core=runtime.work_core();result=conversation_work(core.repository,cid)
        return {**result,'work_report_signature':signature(core,session,result['work']),'storage_scope':'device','device_page_ids':core.page_ids()}
    match=re.fullmatch(r'/api/chat/([1-9][0-9]*)/(employee-configuration|employee-mcp|pipeline-mcp|pipeline-work)',path)
    if match:
        cid=int(match[1]);session=runtime.chat(cid,include_live=False)
        if match[2]=='employee-configuration':
            from .employee_configuration import for_work_settings
            config=for_work_settings(cid)
            if method=='GET':
                if not data:return config.read()
                if set(data)=={'operation_id'}:return config.receipt(data['operation_id'])
            if method=='POST' and set(data) in ({'operation_id','expected_revision','definition_sha256','values'},{'operation_id','expected_revision','definition_sha256','values','bindings'}):return config.save(**data)
        elif match[2]=='pipeline-work':
            from .pipeline_work_access import read
            if method=='GET' and not data:return read(runtime.work_core(),cid,{'operation':'list'},actor_id=runtime.app.binding.library_id)
            if method=='POST':return read(runtime.work_core(),cid,data,actor_id=runtime.app.binding.library_id)
        elif match[2] in ('pipeline-mcp','employee-mcp'):
            observing=method=='GET' and data=={'observe':'1'}
            if observing:
                # runtime.chat already checked this saved session's library,
                # type and frozen reference. Only select its hint owner here;
                # full reads and commands keep their complete verification.
                owned=(bool(session.get('context',{}).get('source_pipeline_workspace'))
                       if match[2]=='pipeline-mcp' else
                       session['kind']=='general' and session['subject_type']=='employee')
            elif match[2]=='pipeline-mcp':owned=runtime.pipeline_chat(session)
            else:owned=runtime.employee_chat(session)
            if not owned:raise PermissionError('员工工作请求无效。')
            from .mcp_work_operations import dispatch
            host=runtime.pipeline_mcp_work() if match[2]=='pipeline-mcp' else runtime.employee_mcp_work()
            if method=='GET' and (not data or observing):return dispatch(host,cid,method,observing=observing)
            if method=='POST':return dispatch(host,cid,method,data)
        raise ValueError('员工工作请求无效。')
    if path.startswith('/api/employee-configuration/resources'):
        if 'employee_id' in data:raise PermissionError('请选择本机源码资产。')
        from .employee_collection_operations import dispatch
        return dispatch(method,data,importing=path.endswith('/import'))
    if path.startswith('/api/local-references/') and method=='POST':
        from runteams_core import local_references
        from runteams_core import chat_attachments; import os
        if path.endswith('/confirm') and set(data)=={'tokens'}:return {'references':local_references.confirm(data['tokens'])}
        if path.endswith('/pick') and set(data)=={'kind'}:
            if data['kind'] not in ('file','folder'):raise ValueError('资料类型无效。')
            if not os.environ.get('RUNTEAMS_ATTACHMENT_PICKER'):raise ValueError('请在本机桌面版选择资料。')
            if not runtime.picker_lock.acquire(blocking=False):raise BlockingIOError('资料选择正在进行。')
            try:
                paths=chat_attachments.pick_native_paths(data['kind'],cancel_event=runtime.picker_cancel)
                return local_references.prepare(paths) if paths else {'references':[],'pending':[]}
            finally:runtime.picker_lock.release()
        raise ValueError('资料选择请求无效。')
    core=runtime.work_core()
    if path in {'/api/device/work/results','/api/device/work/files'} and method=='GET':
        if set(data)!={'employee_reference'}:raise ValueError('请选择原员工。')
        from .employee_references import checked_reference
        from .employee_chat_work import results,documents
        ref=checked_reference(json.loads(data['employee_reference']))
        result=results(core,ref) if path.endswith('results') else {'files':documents(core,ref)}
        return {**result,'storage_scope':'device','device_page_ids':core.page_ids()}
    match=re.fullmatch(r'/api/(?:core|device/work)/workflows/([1-9][0-9]*)(?:/(cancel|retry))?',path)
    if match:
        from .employee_chat_work import snapshot
        identifier=int(match[1]);frozen=snapshot(core,identifier)
        if not frozen:raise KeyError('工作不存在。')
        if method=='GET' and not match[2] and not data:return core.workflow(identifier)
        if method=='POST' and not data:
            if match[2]=='cancel':return core.cancel_workflow(identifier)
            if match[2]=='retry':return core.retry_workflow(identifier)
    raise KeyError('员工工作接口不存在。')
