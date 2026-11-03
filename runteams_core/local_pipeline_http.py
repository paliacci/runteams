"""Library ingress to the canonical source pipeline operations."""
import re
PREFIX='/api/device/work/source-pipelines/'

def handles(path):
    return path.startswith(PREFIX)

def dispatch(runtime,method,path,data):
    if method!='POST' or not isinstance(data,dict):raise ValueError('流水线请求无效。')
    action=path.removeprefix(PREFIX)
    if action=='market':raise PermissionError('本机资料库不提供官方市场接口。')
    from .source_pipeline_operations import dispatch as operation
    core=runtime.work_core()
    with core.repository.audit_context(actor_id=runtime.app.binding.library_id,source='http'):
        value,status=operation(core,action,data,tuple(runtime.employee_jobs),runtime.activate_employee_host)
    if status!=200:
        from .local_document_http import DocumentResponse
        return DocumentResponse(value,status)
    return value
