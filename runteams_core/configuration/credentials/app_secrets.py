# -*- coding: utf-8 -*-
"""本机凭据保险箱。

凭据值只保存在限制为文件所有者访问的本机文件中，不进入数据库、移动同步、Prompt 或运行记录。
当前产品只提供一个扁平凭据集合；能力包用同名 Key 显式声明依赖，运行时只解析并注入
当前工具声明的那几项值。
"""
import json
import os
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from runteams_core.storage import product_store as store


_lock = threading.Lock()
MAX_SECRET_BYTES = 512 * 1024
_vault_scope = ContextVar('runteams_host_vault', default=None)
# Empty names cannot be credential keys. Older readers ignore this metadata.
_FILENAME_METADATA = ""


@contextmanager
def vault_scope(path):
    """Pin a host execution's explicit vault without changing process env."""
    token = _vault_scope.set(os.path.abspath(path))
    try:
        yield
    finally:
        _vault_scope.reset(token)


def _path():
    if _vault_scope.get() is not None:
        return _vault_scope.get()
    configured = str(os.environ.get("RUNTEAMS_SECRET_VAULT") or "").strip()
    return os.path.abspath(configured) if configured else os.path.join(store.data_dir(), "secrets.json")


def vault_path():
    """Return the local vault location, never its contents."""
    return _path()


def _load_vault():
    try:
        with open(_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}, {}
    if not isinstance(data, dict):
        data = {}
    metadata = data.get(_FILENAME_METADATA)
    filenames = {name: filename for name, filename in metadata.items() if isinstance(filename, str)} if isinstance(metadata, dict) else {}
    values = {name: str(value) for name, value in data.items()
              if name.strip() and isinstance(value, (str, int, float, bool))}
    return values, filenames


def _load():
    return _load_vault()[0]


def _create_vault_file(path):
    if os.name != 'nt':
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    import _winapi
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('descriptor', wintypes.LPVOID),
                    ('inherit', wintypes.BOOL)]

    # Set a protected owner-only DACL at creation, before writing credentials.
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    descriptor = wintypes.LPVOID()
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            'D:P(A;;FA;;;OW)', 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        handle = _winapi.CreateFile(path, _winapi.GENERIC_WRITE, 0, ctypes.addressof(attributes),
                                    1, 0x80, 0)  # CREATE_NEW, FILE_ATTRIBUTE_NORMAL
    finally:
        kernel.LocalFree(descriptor)
    try:
        flags = wintypes.DWORD()
        if not kernel.GetVolumeInformationByHandleW(wintypes.HANDLE(handle), None, 0, None,
                                                   None, ctypes.byref(flags), None, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if not flags.value & 0x8:  # FILE_PERSISTENT_ACLS
            raise PermissionError('凭据保险箱所在卷必须支持 Windows 文件访问控制。')
        return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except BaseException:
        _winapi.CloseHandle(handle)
        os.unlink(path)
        raise


def _save(values, filenames):
    path = _path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + '.' + uuid.uuid4().hex + '.tmp'
    fd = _create_vault_file(tmp)
    try:
        data = {**values, _FILENAME_METADATA: filenames} if filenames else values
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _clean_name(name):
    return str(name or "").strip()[:120]


def _mask(value):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return value[:2] + "•" * max(2, min(8, len(value) - 6)) + value[-4:]


def set_secret(name, value, *, filename=None):
    name = _clean_name(name)
    if not name:
        raise ValueError("密钥名不能为空")
    value = str(value if value is not None else "")
    if len(value.encode("utf-8")) > MAX_SECRET_BYTES:
        raise ValueError("凭据文件不能超过 512 KB")
    with _lock:
        values, filenames = _load_vault()
        if filename or name in values or name in filenames:
            # An explicit empty name supersedes any legacy configuration label.
            filenames[name] = filename or ""
        if value == "":
            values.pop(name, None)
        else:
            values[name] = value
        _save(values, filenames)
    return {"name": name, "set": value != ""}


def set_secrets(values):
    """一次性保存多项凭据，验证全部输入后再落盘。"""
    if not isinstance(values, dict) or not values:
        raise ValueError("没有需要保存的凭据")
    cleaned = {}
    for raw_name, raw_value in values.items():
        name = _clean_name(raw_name)
        if not name:
            raise ValueError("密钥名不能为空")
        value = str(raw_value if raw_value is not None else "")
        if not value.strip():
            raise ValueError("凭据值不能为空")
        if len(value.encode("utf-8")) > MAX_SECRET_BYTES:
            raise ValueError("凭据文件不能超过 512 KB")
        cleaned[name] = value
    with _lock:
        current, filenames = _load_vault()
        for name in cleaned:
            if name in current or name in filenames:
                filenames[name] = ""
        current.update(cleaned)
        _save(current, filenames)
    return [{"name": name, "set": True} for name in cleaned]


def list_masked():
    """返回 Key、掩码和是否已填写，绝不返回明文。"""
    return {name: {"set": True, "masked": _mask(value)}
            for name, value in _load().items()}


def names():
    """返回当前已填写的 Key；用于发布和启动前的可运行性检查。"""
    return set(_load())


def file_name(name):
    """Return filename metadata only. None denotes a legacy entry."""
    return _load_vault()[1].get(name)


def resolve(requested):
    """只解析调用方明确请求的 Key，绝不提供整库读取接口。"""
    requested = [str(name or "").strip() for name in (requested or [])]
    if not requested:
        return {}
    values = _load()
    return {name: values[name] for name in requested if name in values and values[name] != ""}
