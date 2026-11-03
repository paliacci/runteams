"""Library-owned composition of the original schedule stores and unique runner."""
import re,threading
from pathlib import Path
from types import SimpleNamespace

class LocalSchedules:
    def __init__(self,runtime):
        self.runtime=runtime;self.backends={};self.runners={};self.lock=threading.RLock()

    def controller(self):
        return SimpleNamespace(core=self.runtime.work_core(),wake=self.runtime.activate_employee_host)

    def backend(self,kind):
        with self.lock,self.runtime.scope():
            if kind not in ('employee','pipeline'):raise ValueError('计划类型无效。')
            if kind not in self.backends:
                if kind=='pipeline':
                    from runteams_core.automation.source_pipeline_schedules import PipelineSchedules
                    value=PipelineSchedules(self.controller)
                else:
                    from runteams_core.automation.device_employee_schedules import EmployeeSchedules
                    from runteams_core.automation.scheduled_employee_chat import execute
                    value=EmployeeSchedules(self.controller,chat_execute=lambda backend,job,asset,cancel:execute(self.runtime,backend,job,asset,cancel))
                self.backends[kind]=value
            return self.backends[kind]

    def start(self,kind):
        with self.lock,self.runtime.scope():
            if self.runtime.closing:return
            backend=self.backend(kind)
            if not backend.path.is_file():return
            if kind not in self.runners:
                from runteams_core.automation.automation_scheduler import AutomationScheduler
                self.runners[kind]=AutomationScheduler(backend.execute,backends=[backend],on_tick=backend.reconcile,
                    scope=self.runtime.scope,operation_scope=self.runtime.app.request)
            runner=self.runners[kind];runner.start();runner.wake()

    def activate_existing(self):
        for kind in ('employee','pipeline'):
            if (self.runtime.app.binding.root/(kind+'-schedules')/'schedules.sqlite3').is_file():self.start(kind)

    def busy(self):
        for runner in tuple(self.runners.values()):
            with runner._lock:
                if runner._active:return True
        return False

    def stop(self):
        for runner in tuple(self.runners.values()):runner.stop()
        if self.busy() or any(r._thread and r._thread.is_alive() for r in self.runners.values()):
            raise RuntimeError('自动化仍在停止，资料库运行锁保持。')
        self.runners.clear();self.backends.clear()

PREFIX='/api/device/'

def handles(path):
    return bool(re.fullmatch(r'/api/device/(?:employee|pipeline)-schedules(?:/operations/[a-f0-9-]{36}(?:/abandon)?)?',path))

def dispatch(runtime,method,path,data):
    from runteams_core.automation.schedule_operations import dispatch as operation
    kind='pipeline' if path.startswith(PREFIX+'pipeline-') else 'employee'
    host=runtime.schedule_host();backend=host.backend(kind)
    query={key:[value] for key,value in data.items()} if method=='GET' else {}
    try:return operation(backend,method,path,query,data,on_mutation=lambda:host.start(kind))
    except Exception as error:
        from runteams_core.automation.device_employee_schedules import PreparationUnknown
        from runteams_core.application.http.local_document_http import DocumentResponse
        from runteams_core.application.local_runtime import LocalInputError
        import sqlite3
        if isinstance(error,PermissionError):raise
        if isinstance(error,PreparationUnknown):return DocumentResponse({'error':str(error),'state':'unknown'},409)
        if isinstance(error,(OSError,sqlite3.Error)):return DocumentResponse({'error':'本机自动化暂时无法读取或保存，请核对原操作。','state':'unknown'},503)
        if isinstance(error,(ValueError,TypeError)):raise LocalInputError(str(error)) from error
        raise
