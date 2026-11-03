"""Library transport composition for the canonical SDK source operations."""
import re
from . import creator_source_operations as operations
from .creator_local_source import current_store

PATH = '/api/creator-source/drafts'


def dispatch(runtime, method, path, data):
    match = re.fullmatch(re.escape(PATH) + r'/([a-f0-9]{64})(/(?:file|workspace|history|receipt|edit|restore|session|recovery|build|export|configuration|identity))?', path)
    if not match:
        raise KeyError('本机源码接口不存在。')
    if not isinstance(data, dict):
        raise ValueError('源码请求参数无效。')
    identity, action = match[1], match[2] or ''
    store = current_store(runtime.app.binding.scope['cache_scope'])
    if method == 'GET':
        return operations.read(store, identity, action, {key:[value] for key,value in data.items()})
    if method == 'POST':
        if action == '/session':
            if set(data) != {'runtime'} or not isinstance(data['runtime'],dict) or set(data['runtime'])-{'channel_id','model','reasoning_effort'}:
                raise ValueError('创作会话参数无效。')
        if action == '/recovery':
            session = runtime.chat(data.get('session_id'), include_live=False)
            if session['id'] in runtime.active:
                raise BlockingIOError('请先完成当前创作。')
        if runtime.closing:
            raise BlockingIOError('应用正在退出，请重新打开。')
        value=operations.write(store, identity, action, data, runtime.app.binding.scope['cache_scope'], runtime.public_chat)
        if action=='/build' and isinstance(value,dict) and value.get('state')=='running':
            retain_build(runtime,store,identity,value['operation_key'])
        return value
    raise KeyError('本机源码接口不存在。')


def retain_build(runtime, store, identity, operation):
    """A compiler outlives HTTP, so keep the library lease until its OS lock ends."""
    import os
    import threading
    import time
    from .creator_local_build import LocalBuilds
    builds=LocalBuilds(store,identity)
    owner=(identity,operation)
    if owner in runtime.source_builds:
        return
    lease=runtime.app.request((runtime.app.binding.library_id,runtime.app.backups.generation))
    lease.__enter__()
    def wait():
        try:
            while True:
                try:fd=builds.lock()
                except BlockingIOError:time.sleep(.05)
                else:os.close(fd);break
        finally:
            lease.__exit__(None,None,None)
            with runtime.lock:runtime.source_builds.pop(owner,None)
    thread=threading.Thread(target=wait,name='local-source-build-lease',daemon=False)
    runtime.source_builds[owner]={'thread':thread,'builds':builds,'operation':operation}
    try:thread.start()
    except BaseException:
        runtime.source_builds.pop(owner,None);lease.__exit__(None,None,None);raise
