"""Own Windows knowledge-reader copies until the service and the reader release them."""
import atexit
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import stat
import tempfile

from runteams_core.foundation.regular_files import is_link, storage_path

_PREFIX = 'runteams-knowledge-'
_RECEIPT = '.runteams-view-v1'
_DELETE = 0x10000
_READ_ATTRIBUTES = 0x80
_WRITE_ATTRIBUTES = 0x100


@contextmanager
def _handle(path, access, share=0, *, directory=False):
    import _winapi
    import msvcrt
    flags = 0x00200000  # OPEN_REPARSE_POINT
    if directory:
        flags |= 0x02000000  # BACKUP_SEMANTICS
    handle = _winapi.CreateFile(str(path), access, share, 0, 3, flags, 0)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _winapi.CloseHandle(handle)
        raise
    try:
        info = os.fstat(fd)
        if is_link(info) or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise OSError('Unexpected viewer file type')
        yield fd, info
    finally:
        os.close(fd)


def _identity(info):
    return [info.st_dev, info.st_ino]


def _file_identity(info):
    return [*_identity(info), info.st_size, info.st_mtime_ns]


class _BasicInfo(ctypes.Structure):
    _fields_ = [('times', ctypes.c_longlong * 4), ('attributes', wintypes.DWORD)]


def _set_info(fd, kind, value):
    import msvcrt
    set_info = ctypes.WinDLL('kernel32', use_last_error=True).SetFileInformationByHandle
    set_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    set_info.restype = wintypes.BOOL
    if not set_info(msvcrt.get_osfhandle(fd), kind, ctypes.byref(value), ctypes.sizeof(value)):
        raise ctypes.WinError(ctypes.get_last_error())


def _delete(fd, attributes=0):
    readonly = attributes & stat.FILE_ATTRIBUTE_READONLY
    if readonly:
        # Zero time fields preserve timestamps. Changing attributes through the
        # exclusive handle also keeps a replacement path out of the operation.
        writable = attributes & ~stat.FILE_ATTRIBUTE_READONLY
        _set_info(fd, 0, _BasicInfo(attributes=writable or stat.FILE_ATTRIBUTE_NORMAL))
    try:
        _set_info(fd, 4, ctypes.c_ubyte(1))  # FileDispositionInfo: delete on close.
    except OSError:
        if readonly:
            _set_info(fd, 0, _BasicInfo(attributes=attributes))
        raise


def _reclaim_file(folder, record):
    name, identity = record
    if not isinstance(name, str) or Path(name).name != name or name in ('', '.', '..', _RECEIPT) or ':' in name:
        raise ValueError('Invalid viewer receipt')
    try:
        with _handle(folder / name, _READ_ATTRIBUTES | _WRITE_ATTRIBUTES | _DELETE) as (fd, info):
            if info.st_nlink == 1 and info.st_ino and _file_identity(info) == identity:
                _delete(fd, info.st_file_attributes)
    except FileNotFoundError:
        pass


def _reclaim(folder):
    try:
        if is_link(folder.lstat()) or not (folder / _RECEIPT).is_file():
            return
        # Denying delete sharing pins the directory while resolving its immediate children.
        with _handle(folder, _READ_ATTRIBUTES | _DELETE, 3, directory=True) as (directory_fd, directory):
            # The owner holds an incompatible handle until exit. Only one reaper can claim it.
            with _handle(folder / _RECEIPT, 0x80000000 | _DELETE) as (receipt, receipt_info):
                if not directory.st_ino or receipt_info.st_nlink != 1:
                    return
                with os.fdopen(os.dup(receipt), 'rb') as records:
                    if json.loads(records.readline()) != _identity(directory):
                        return
                    for line in records:
                        _reclaim_file(folder, json.loads(line))
                _delete(receipt)
            _delete(directory_fd)  # Windows leaves a nonempty directory intact.
    except (OSError, ValueError, TypeError):
        # Sharing violations are normal while a service or an external reader is active.
        return


def reclaim_abandoned():
    try:
        for folder in storage_path(tempfile.gettempdir()).glob(_PREFIX + '*'):
            _reclaim(folder)
    except OSError:
        pass


class ViewerDirectory:
    def __init__(self):
        self.name = tempfile.mkdtemp(prefix=_PREFIX, dir=storage_path(tempfile.gettempdir()))
        self._files = {}
        marker = Path(self.name) / _RECEIPT
        # Python's open on Windows denies delete sharing, keeping _reclaim out.
        self._receipt = marker.open('xb')
        try:
            self._append(_identity(marker.parent.stat()))
        except OSError:
            self._receipt.close()
            marker.unlink(missing_ok=True)
            marker.parent.rmdir()
            raise
        atexit.register(self.cleanup)

    def _append(self, value):
        self._receipt.write(json.dumps(value).encode('ascii') + b'\n')
        self._receipt.flush()
        os.fsync(self._receipt.fileno())

    def record(self, path):
        path = Path(path)
        identity = _file_identity(path.stat())
        if self._files.get(path.name) != identity:
            self._append([path.name, identity])
            self._files[path.name] = identity

    def cleanup(self):
        self._receipt.close()
        _reclaim(Path(self.name))
        atexit.unregister(self.cleanup)
