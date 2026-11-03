"""Library-owned employee capability, using the canonical SDK execution services."""
from runteams_core.employees.bound_employee_context import BoundEmployeeContext
from runteams_core.agents.tools.tool_services import ToolServiceUnavailable
class LocalEmployeeContext(BoundEmployeeContext):
    def verify_connection_archive(self,*args):
        self._check();raise PermissionError('本机资料库不核验官方MCP资产回执。')

    def work_resource_setup(self,employee,packages):
        self._check();return False

    def connection_provider(self,host,chat):
        self._check();raise PermissionError('本机资料库不提供官方MCP服务授权。')

    def directory(self,**kwargs):
        self._check()
        from runteams_core.employees.employee_directory import local_entries, assemble, SCHEMA
        errors={};rows=local_entries(errors=errors)
        return {'schema':SCHEMA,'items':assemble(rows,[],[]),'errors':({'sources':{'error':'部分员工源码需要修正。','items':errors}} if errors else {}),'profile':None}

    def connection_assets(self,*args):
        self._check();raise PermissionError('本机资料库不提供官方下载或租用授权。')

    def acquired_binding(self,session):
        raise ToolServiceUnavailable('本机资料库只使用自己的 SDK 源码员工。')

    def package_adapter(self,*args):
        raise ToolServiceUnavailable('本机资料库不提供官方下载或租用授权。')

    def prepare_task_references(self,action,source,*,core=None):
        self._check()
        from runteams_core.employees.employee_task_references import source_task_references
        return source_task_references(action,source,core=core)

    def allows_actions(self,core,session,actions):
        self._check()
        if session.get('scope_pipeline_id'):return False
        if session.get('context',{}).get('source_pipeline_workspace'):
            from runteams_core.pipelines.pipeline_work_access import bound
            reference=bound(session['id'])
            return all(a.get('op') in ('create_document','update_document') or
                a.get('op')=='create_pipeline_work' and a.get('reference')==reference for a in actions)
        if session.get('context',{}).get('pipeline_work'):
            return all(a.get('op') in ('create_document','update_document') for a in actions)
        from runteams_core.employees.employee_binding import resolve
        from runteams_core.employees.employee_references import same
        binding=resolve(session)
        return bool(binding.get('package')) and all(a.get('op') in ('create_document','update_document') or
            (a.get('op')=='create_employee_task' and (a.get('employee_reference') is None or same(a['employee_reference'],binding['reference']))) for a in actions)

    def apply_action(self,core,action,context):
        self._check()
        if action['op'] in ('create_document','update_document'):
            from runteams_core.documents.document_actions import apply_document_action
            return apply_document_action(core,action)
        if action['op']=='create_pipeline_work':
            from runteams_core.pipelines.pipeline_work_access import apply_action
            return apply_action(core,action,context)
        if action['op']=='create_employee_task':
            from runteams_core.employees.employee_binding import for_context
            from runteams_core.employees.employee_chat_work import submit
            binding=for_context(context)
            if binding and binding['package']:return submit(core,binding,action,context)
        raise PermissionError('请在绑定的本机员工工作中操作。')

    def scheduled_employee(self,*args):
        self._check();raise PermissionError('本机资料库只使用自己的源码员工计划。')

    def schedule_record_id(self,*args):
        self._check();raise PermissionError('本机资料库只使用自己的源码员工计划。')

    def scheduled_host_ready(self,host):
        self._check()
        return host is not None and host.app.provider is self.provider and not host.closing and host.lease is not None

    def scheduled_downloaded_chat(self,*args):
        self._check();raise PermissionError('本机资料库只使用自己的源码员工计划。')

    def scheduled_turn(self,host,scope,operation,chat_id,prompt,cancel_event=None):
        self._check()
        from runteams_core.storage import device_data
        device_data.check(scope)
        if not self.scheduled_host_ready(host):raise PermissionError('原本机工作宿主已关闭。')
        import threading
        return host.execute_employee_chat(chat_id,prompt,cancel_event or threading.Event(),operation)
