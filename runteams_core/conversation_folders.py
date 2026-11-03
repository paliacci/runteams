"""Account-local working folders. Asset materialization stays in managed storage."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid

from . import device_data

_lock = threading.RLock()


def session(chat_id=None):
    import product_store as store
    if not device_data.personal():
        raise PermissionError('请在个人工作区选择工作文件夹。')
    if chat_id in (None, '', 'new'):
        return None
    if not str(chat_id).isdigit() or not device_data.contains(int(chat_id)):
        raise PermissionError('本机对话不存在。')
    item = store.get_chat(int(chat_id))
    if not item or item['kind'] != 'general' or item.get('scope_pipeline_id') or item.get('scope_run_id'):
        raise PermissionError('此对话不支持更换工作文件夹。')
    return item


def context_key(item):
    context = (item or {}).get('context') or {}
    if (item or {}).get('subject_type') == 'employee':
        reference = context.get('employee_binding') or context.get('employee_reference') or (context.get('local_employee_package') or {}).get('reference')
        if not reference:
            raise ValueError('\u5458\u5de5\u5b8c\u6574\u8eab\u4efd\u672a\u80fd\u786e\u8ba4\uff0c\u8bf7\u4ece\u5458\u5de5\u76ee\u5f55\u91cd\u65b0\u6253\u5f00\u3002')
        value = {'employee': reference}
    else:
        value = {'general': True}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@contextmanager
def _lease(root):
    import fcntl
    descriptor = os.open(root / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def records(expected=None):
    scope = device_data.identity()
    if expected is not None:
        device_data.check(expected)
    root = device_data.root() / 'conversation-folders'
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink():
        raise ValueError('工作文件夹记录目录无效。')
    with _lock, _lease(root):
        path = root / 'folders.json'
        if path.is_symlink():
            raise ValueError('工作文件夹记录无效。')
        value = json.loads(path.read_text()) if path.exists() else {'defaults': {}, 'chats': {}}
        if not isinstance(value, dict) or set(value) != {'defaults', 'chats'} or any(not isinstance(value[k], dict) for k in value):
            raise ValueError('工作文件夹记录无效，请核对本机数据。')
        before = json.dumps(value, sort_keys=True)
        yield value
        device_data.check(scope)
        if json.dumps(value, sort_keys=True) != before:
            temp = root / (uuid.uuid4().hex + '.tmp')
            try:
                with temp.open('x') as stream:
                    os.chmod(temp, 0o600)
                    json.dump(value, stream, ensure_ascii=False)
                    stream.flush();os.fsync(stream.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)


def original(item):
    import product_store as store
    if item and item.get('subject_type') == 'employee':
        from .employee_context import current as employee_context
        return str(employee_context().workspace(item['id']))
    return store.assistant_workspace()


def _chat_key(item):
    return device_data.epoch(item['id']) if item else None


def _chosen(data, item):
    key = _chat_key(item)
    if key and key in data['chats']:
        return data['chats'][key]
    # A previously started chat has its original directory, irrespective of later defaults.
    if not item or not item.get('messages'):
        selected = data['defaults'].get(context_key(item))
        if selected:
            return selected
    return {'id': 'managed', 'path': original(item), 'custom': False}


def present(choice, item):
    path = Path(choice['path'])
    exists = path.is_dir() and os.access(path, os.R_OK | os.W_OK | os.X_OK)
    home = str(Path.home())
    display = '~' + str(path)[len(home):] if str(path) == home or str(path).startswith(home + os.sep) else str(path)
    return {**choice, 'display_path': display, 'name': path.name or str(path),
            'available': exists, 'started': bool((item or {}).get('messages') or choice.get('sealed'))}


def read(chat_id=None, *, expected=None):
    scope = expected or device_data.identity()
    item = session(chat_id)
    with records(scope) as data:
        return present(_chosen(data, item), item)


def bind(chat_id, selection_id, *, expected=None):
    scope = expected or device_data.identity()
    import product_store as store
    if not str(chat_id).isdigit():
        raise ValueError('对话编号无效。')
    with store.chat_lock(int(chat_id)):
        item = session(chat_id)
        if not item:
            raise ValueError('请先创建对话。')
        with records(scope) as data:
            choice = _chosen(data, item)
            if choice['id'] != selection_id:
                raise ValueError('工作文件夹已变化，请重新选择后发送。')
            state = present(choice, item)
            if not state['available']:
                raise ValueError('工作文件夹不可用，请重新选择。')
            data['chats'][_chat_key(item)] = {**choice, 'sealed': True}
            return state


def pick(chat_id=None, *, expected=None, cancel_event=None):
    import chat_attachments
    import product_store as store
    scope = expected or device_data.identity()
    device_data.check(scope)
    item = session(chat_id)
    paths = chat_attachments.pick_native_paths('folder', **({'cancel_event': cancel_event} if cancel_event is not None else {}))
    device_data.check(scope)
    if not paths:
        return {'cancelled': True}
    if len(paths) != 1:
        raise ValueError('请选择一个工作文件夹。')
    path = Path(paths[0]).resolve(strict=True)
    if not path.is_dir() or not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        raise ValueError('工作文件夹不可用，请重新选择。')
    choice = {'id': uuid.uuid4().hex, 'path': str(path), 'custom': True}
    # Recheck after the native picker; a new message may have started meanwhile.
    with store.chat_lock(int(chat_id)) if item else _lock:
        item = session(chat_id)
        with records(scope) as data:
            started = bool(item and (item.get('messages') or data['chats'].get(_chat_key(item), {}).get('sealed')))
            data['defaults'][context_key(item)] = choice
            if item and not started:
                data['chats'][_chat_key(item)] = choice
    return {'folder': present(choice, item), 'new_conversation': started}


def clear(chat_id=None, selection_id=None, *, expected=None):
    """Forget the selection without touching files or an already frozen chat."""
    import product_store as store
    scope = expected or device_data.identity()
    item = session(chat_id)
    with store.chat_lock(int(chat_id)) if item else _lock:
        item = session(chat_id)
        with records(scope) as data:
            choice = _chosen(data, item)
            if choice['id'] != selection_id:
                raise ValueError('工作文件夹已变化，请重新读取。')
            started = bool(item and (item.get('messages') or data['chats'].get(_chat_key(item), {}).get('sealed')))
            data['defaults'].pop(context_key(item), None)
            if item and not started:
                data['chats'].pop(_chat_key(item), None)
            managed = {'id': 'managed', 'path': original(item if not started else None), 'custom': False}
            return {'folder': present(managed, None), 'new_conversation': started}


def open_folder(chat_id, selection_id, *, expected=None):
    scope = expected or device_data.identity()
    item = session(chat_id)
    with records(scope) as data:
        choice = _chosen(data, item)
        if choice['id'] != selection_id or not present(choice, item)['available']:
            raise ValueError('工作文件夹已变化或不可用，请重新读取。')
        path = choice['path']
    device_data.check(scope)
    import sys
    if sys.platform == 'darwin':
        result = subprocess.run(['open', path], capture_output=True, timeout=10)
    elif sys.platform == 'win32':
        os.startfile(path)
        return {'opened': True}
    else:
        result = subprocess.run(['xdg-open', path], capture_output=True, timeout=10)
    if result.returncode:
        raise ValueError('工作文件夹未能打开，请重试。')
    return {'opened': True}


def runtime(chat_id, fallback):
    """Freeze only this chat's CWD; never rematerialize assets into a selected folder."""
    scope = device_data.identity()
    item = session(chat_id)
    with records(scope) as data:
        choice = data['chats'].get(_chat_key(item))
        if choice is None:
            # Existing/other callers retain the actual runtime's original directory.
            choice = {'id': 'managed', 'path': str(fallback), 'custom': False, 'sealed': True}
            data['chats'][_chat_key(item)] = choice
        if not present(choice, item)['available']:
            raise ValueError('工作文件夹不可用，请重新选择后开始新对话。')
        return choice['path']


def snapshot(source, destination, scope, check):
    # Only directory references are backed up; external files are never traversed.
    import shutil
    root = Path(source) / 'conversation-folders'
    with _lock:
        if root.exists():
            if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')):
                raise ValueError('工作文件夹记录不能包含符号链接。')
            check()
            with _lease(root):
                shutil.copytree(root, Path(destination) / 'conversation-folders')
            from .library_backup import folders
            folders(Path(destination),source_root=Path(source))
            check()


def frozen_reference(chat_id):
    scope = device_data.identity()
    import product_store as store
    item = store.get_chat(chat_id, include_messages=False)
    if item and item.get('kind') == 'employee_design':
        from .employee_context import current as employee_context
        if not device_data.personal() or not device_data.contains(chat_id):
            raise PermissionError('本机对话不存在。')
        employee_context().verify_authoring(item)
        # Creation may have changed the original general conversation's kind.
        # Read its already frozen folder by epoch; do not select or move it.
    else:
        item = session(chat_id)
    with records(scope) as data:
        origin = _chat_key(item)
        choice = data['chats'].get(origin)
        return {'origin': origin, 'choice': dict(choice)} if choice and choice.get('custom') else None


def inherit(chat_id, reference):
    """A trusted assignment carries the source chat's exact selected directory."""
    scope = device_data.identity()
    item = session(chat_id)
    with records(scope) as data:
        origin = data['chats'].get(reference.get('origin'))
        if not origin or origin != reference.get('choice'):
            raise ValueError('原工作文件夹记录未能确认。')
        key = _chat_key(item)
        if key in data['chats'] and data['chats'][key] != origin:
            raise ValueError('工作已绑定其他文件夹。')
        if not present(origin, item)['available']:
            raise ValueError('工作文件夹不可用，请恢复原目录。')
        data['chats'][key] = dict(origin)
        return origin['path']
