"""Account-free application composition for one explicitly opened library."""
from contextlib import contextmanager
from pathlib import Path
import json
import threading

from .library_assets import LocalAssets
from .local_library import LocalLibrary, private_directory
from .local_json import strict_json
from .library_settings import LibrarySettings


class LocalFeatureUnavailable(RuntimeError):
    pass


class LocalApplication:
    def __init__(self, data_directory):
        directory = private_directory(Path(data_directory).expanduser()).resolve()
        from .local_backups import LocalBackups
        self.backups = LocalBackups(directory)
        self.backups.recover()
        self._generation=self.backups.generation
        self.base = directory / 'device-data'
        self.provider = LocalLibrary()
        self.provider.work_factory=lambda **options:self.runtime.work_core(**options)
        self.binding = self.provider.resolve(self.base)
        self.assets = LocalAssets(self.binding.root, self.binding.library_id, self.check)
        self.settings = LibrarySettings(self.binding, self.check)
        self.data_directory = directory
        self._lease = None
        self._runtime = None
        self._runtime_lock = threading.Lock()
        self._gate = threading.RLock()
        self._requests = 0
        self._maintenance = False
        from .local_backup_maintenance import AutomaticBackups
        self.automatic_backups = AutomaticBackups(self)

    @property
    def runtime(self):
        with self._gate, self._runtime_lock:
            if self._runtime is None:
                from .local_runtime import LocalRuntime
                self._runtime = LocalRuntime(self)
            return self._runtime

    def own(self):
        with self._gate:
            if self._lease is None:
                from .local_host_lock import acquire
                self._lease=acquire(self.data_directory)
            return self._lease

    def close(self):
        self.automatic_backups.close()
        if self._runtime is not None:self._runtime.close()
        elif self._lease is not None:self._lease.rollback();self._lease.close()
        self._lease=None

    def check(self):
        self.provider.check(self.base, self.binding)

    def library(self):
        self.check()
        return {**self.binding.scope,'generation':self.backups.generation}

    def rebind(self):
        if self._generation!=self.backups.generation:
            from runteams_core import chat_attachments
            chat_attachments.discard_native_selections(self.binding.scope)
        self._generation=self.backups.generation
        self.binding=self.provider.resolve(self.base)
        self.assets=LocalAssets(self.binding.root,self.binding.library_id,self.check)
        self.settings=LibrarySettings(self.binding,self.check)

    def check_request_scope(self, expected):
        if expected is not None and expected!=(self.binding.library_id,self.backups.generation):
            raise PermissionError('资料库已恢复，请重新打开当前窗口。')

    @contextmanager
    def request(self, expected=None):
        from .local_host_lock import RuntimeBusy
        self.own()
        with self._gate:
            if self._maintenance or self.backups.restoring():
                raise RuntimeBusy('资料正在备份或恢复，请稍后重试。')
            self.check_request_scope(expected);self._requests+=1
        try:yield
        finally:
            with self._gate:self._requests-=1

    @contextmanager
    def exclusive(self, expected=None):
        from .local_host_lock import RuntimeBusy
        with self._gate:
            if self._maintenance or self._requests:raise RuntimeBusy('请先完成当前操作，再备份或恢复。')
            self.check_request_scope(expected);runtime=self.runtime
            if runtime.active or runtime._schedules is not None and runtime._schedules.busy() or not runtime.picker_lock.acquire(blocking=False):
                raise RuntimeBusy('请先等待当前对话或文件选择结束，再备份或恢复。')
            runtime.picker_lock.release();self._maintenance=True
        try:yield
        finally:
            with self._gate:self._maintenance=False

    def dispatch(self, method, path, data, *, scope=None):
        if path.startswith('/api/backups'):
            from .local_backup_http import dispatch
            try:return dispatch(self,method,path,data,scope)
            except ValueError as error:
                from .library_assets import AssetConflict
                from .local_runtime import LocalInputError
                if isinstance(error,AssetConflict):raise
                raise LocalInputError(str(error)) from error
        if path=='/api/library' and self.backups.restoring():
            with self.exclusive():
                self.backups.recover(owned=True);self.rebind()
        with self.request(scope):return self._dispatch(method,path,data)

    def _dispatch(self, method, path, data):
        """Native callers and HTTP share this single account-free application."""
        if path == '/api/settings':
            if method == 'GET':
                _fields(data, set())
                return self.settings.read()
            if method == 'POST':
                return self.settings.save(data)
        self.check()
        from .local_schedules import handles as schedule_handles,dispatch as schedule_dispatch
        if schedule_handles(path):
            with self.runtime.scope():return schedule_dispatch(self.runtime,method,path,data)
        from .local_pipeline_http import handles as pipeline_handles,dispatch as pipeline_dispatch
        if pipeline_handles(path):
            with self.runtime.scope():return pipeline_dispatch(self.runtime,method,path,data)
        from .local_employee_http import handles as employee_handles,dispatch as employee_dispatch
        if employee_handles(path):
            with self.runtime.scope():return employee_dispatch(self.runtime,method,path,data)
        from .local_document_http import handles as document_handles, dispatch as document_dispatch
        if document_handles(path):
            if not isinstance(data, dict):raise ValueError("请求字段无效。")
            with self.runtime.scope():
                core = self.runtime.work_core()
                with core.repository.audit_context(actor_id=self.binding.library_id, source='http'):
                    return document_dispatch(core, method, path, data)
        if method == 'GET' and path == '/api/employee-avatars':
            _fields(data, set())
            from .employee_avatars import preset_items
            return {'presets': preset_items()}
        if path.startswith('/api/creator-source/drafts'):
            from .local_creator_sources import dispatch
            with self.runtime.lock, self.runtime.scope():
                return dispatch(self.runtime, method, path, data)
        from .local_runtime import handles
        if handles(path):
            if not isinstance(data, dict):
                raise ValueError('请求字段无效。')
            try:
                return self.runtime.dispatch(method, path, data)
            except ValueError as error:
                from .local_runtime import LocalInputError
                raise LocalInputError(str(error)) from None
        if method == 'GET' and path == '/api/library':
            _fields(data, set())
            return self.library()
        if method == 'GET' and path == '/api/assets':
            _fields(data, set(), {'kind', 'limit', 'after'})
            return self.assets.list(**data)
        if method == 'POST' and path == '/api/assets':
            _fields(data, {'kind', 'name', 'source', 'operation_id'})
            return self.assets.create(**data)
        if method == 'POST' and path == '/api/assets/import':
            _fields(data, {'kind', 'name', 'source_text', 'operation_id'})
            if not isinstance(data['source_text'], str):
                raise ValueError('源码文件无效。')
            source = strict_json(data['source_text'].encode('utf-8'))
            return self.assets.create(data['kind'], data['name'], source, operation_id=data['operation_id'])
        if method == 'POST' and path == '/api/assets/read':
            _fields(data, {'reference'}, {'revision'})
            return self.assets.get(**data)
        if method == 'POST' and path == '/api/assets/save':
            _fields(data, {'reference', 'name', 'source', 'expected_revision', 'operation_id'})
            return self.assets.save(**data)
        if method == 'POST' and path == '/api/assets/rename':
            _fields(data, {'reference', 'name', 'expected_revision', 'operation_id'})
            if type(data['expected_revision']) is not int or data['expected_revision'] < 1:
                raise ValueError('当前修订无效。')
            record = self.assets.get(data['reference'], revision=data['expected_revision'])
            return self.assets.save(data['reference'], data['name'], record['source'],
                expected_revision=data['expected_revision'], operation_id=data['operation_id'])
        if method == 'POST' and path == '/api/assets/export':
            _fields(data, {'reference'}, {'revision'})
            record = self.assets.get(**data)
            return {'name': record['name'], 'source_text': json.dumps(record['source'],
                ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)}
        if path.startswith(('/api/account/', '/api/billing', '/api/core/marketplace', '/api/organizations', '/api/market')):
            raise KeyError('官方接口不在本机版提供。')
        if path.startswith(('/api/employee-', '/api/core/', '/api/device/', '/api/channels',
                            '/api/environment', '/api/model-', '/api/chats', '/api/chat/',
                            '/api/conversations', '/api/pipeline-work/', '/api/app/')):
            raise LocalFeatureUnavailable('这项业务的本机接口尚未接通。')
        raise KeyError('本机接口不存在。')


def _fields(data, required, optional=frozenset()):
    if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - optional:
        raise ValueError('请求字段无效。')
