"""Stable local library identity. No account, service URL or cloud fallback."""
import hashlib
import json
import os
import stat
from pathlib import Path
import uuid

from .storage_context import StorageBinding

SCHEMA = 'runteams.local-library/1'


def private_directory(path):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise ValueError('本机资料目录无效。')
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('本机资料目录无效。')
    if stat.S_IMODE(info.st_mode) != 0o700:
        path.chmod(0o700)
    return path


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError('本机资料库身份无效。')
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != {'schema', 'library_id'} or value['schema'] != SCHEMA:
        raise ValueError('本机资料库身份无效。')
    if not isinstance(value['library_id'], str) or str(uuid.UUID(value['library_id'])) != value['library_id']:
        raise ValueError('本机资料库身份无效。')
    return value['library_id']


def scope_for(library_id):
    if not isinstance(library_id,str) or str(uuid.UUID(library_id))!=library_id:
        raise ValueError('本机资料库身份无效。')
    namespace=hashlib.sha256((SCHEMA+'\n'+library_id).encode()).hexdigest()
    return {'storage_kind':'local','library_id':library_id,'storage_namespace':namespace,'cache_scope':namespace}


class LocalLibrary:
    def resource_discovery(self):
        from .resource_discovery import LocalResources
        return LocalResources(self)

    def tool_service(self):
        return self.device_work_service()

    def device_work_service(self, **kwargs):
        factory=getattr(self,'work_factory',None)
        if factory is None:raise RuntimeError('本机员工工作宿主尚未组装。')
        return factory(**kwargs)

    def native_employee_tool(self, name, arguments, context):
        from runteams_core.native_employee_tools import dispatch
        return dispatch(name,arguments,context)

    def creator_source_tool(self, arguments, context):
        from .creator_source_tool import tool
        return tool(arguments, context)

    def creator_resource_tool(self, name, arguments, context):
        from .tool_services import ToolServiceUnavailable
        raise ToolServiceUnavailable('本机入口不提供官方作品资源工具。')

    def pipeline_context(self):
        from .local_pipeline_context import LocalPipelineContext
        return LocalPipelineContext(self)

    def employee_context(self):
        from .local_employee_context import LocalEmployeeContext
        return LocalEmployeeContext(self)

    def interaction_scope(self):
        return ('local-library', self.attachment_scope()['library_id'], '')

    def record_reply_feedback_case(self, chat_id, message_id, rating, environment):
        # Free ratings live solely in the transcript; no case or upload outbox.
        return None

    def project_reply_feedback_case(self, value):
        return value

    def attachment_storage(self):
        from .attachment_storage import LocalAttachmentStorage
        return LocalAttachmentStorage()

    def attachment_scope(self):
        from .device_data import identity
        return identity()

    def host_identity(self):
        return ('local-library', self.attachment_scope()['library_id'])

    def core_data_root(self, base):
        return Path(base)

    def reject_host_business(self, module):
        from .contracts import ContractError
        raise ContractError(module + '请通过当前资料库的业务存储入口访问。')

    def check(self, base, expected):
        """A running host must not recreate a missing or replaced identity."""
        base = Path(base)
        try:
            current = _read(base / '.local-library.json')
        except (OSError, ValueError):
            raise PermissionError('本机资料库已变化，请重新打开。') from None
        if base.is_symlink() or current != expected.library_id:
            raise PermissionError('本机资料库已变化，请重新打开。')
        if self.resolve(base) != expected:
            raise PermissionError('本机资料库已变化，请重新打开。')

    def resolve(self, base):
        from .workspace_context import selected
        if selected():
            raise PermissionError('本机资料库没有组织工作区。')
        base = private_directory(base)
        marker = base / '.local-library.json'
        if not marker.exists() and not marker.is_symlink():
            temporary = base / ('.library-' + uuid.uuid4().hex)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, 'w') as stream:
                    json.dump({'schema': SCHEMA, 'library_id': str(uuid.uuid4())}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, marker)
                except FileExistsError:
                    pass
                directory = os.open(base, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                temporary.unlink(missing_ok=True)
        library_id = _read(marker)
        scope=scope_for(library_id)
        directory=private_directory(private_directory(base/'libraries')/scope['storage_namespace'])
        return StorageBinding(directory,library_id,scope)
