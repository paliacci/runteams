"""Expose a deep checkout as a Windows child process's current directory."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import struct
import tempfile
import _winapi

from runteams_core.foundation.regular_files import storage_path

DELETE = 0x10000
SHARE_READ_WRITE_DELETE = 7
DELETE_ON_CLOSE = 0x04000000
OPEN_REPARSE_POINT = 0x00200000
BACKUP_SEMANTICS = 0x02000000
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
FSCTL_SET_REPARSE_POINT = 0x900A4


def _fits(path):
    # CreateProcessW reserves room for a trailing separator and a terminating NUL.
    return len(os.fspath(path).encode('utf-16-le')) <= 258 * 2


@contextmanager
def working_directory(path):
    if _fits(path):
        yield path
        return
    extended = str(storage_path(path))
    try:
        short = _winapi.GetShortPathName(extended)
    except OSError:
        short = None
    if short and _fits(short):
        yield Path(short)
        return

    # Volumes may have 8.3 names disabled. A junction gives the runtime access
    # to the same checkout. Closing the handle removes only the junction,
    # including when the service is terminated before the turn finishes.
    alias = Path(tempfile.mkdtemp(prefix='runteams-src-'))
    try:
        handle = _winapi.CreateFile(str(alias), _winapi.GENERIC_WRITE | DELETE, SHARE_READ_WRITE_DELETE, 0,
                                    _winapi.OPEN_EXISTING, DELETE_ON_CLOSE | OPEN_REPARSE_POINT | BACKUP_SEMANTICS, 0)
    except BaseException:
        alias.rmdir()
        raise
    try:
        # MountPointReparseBuffer holds the NT substitute name and an empty print name.
        name = ('\\??\\' + extended.removeprefix('\\\\?\\')).encode('utf-16-le')
        mount = struct.pack('<HHHH', 0, len(name), len(name) + 2, 0) + name + b'\0\0\0\0'
        data = struct.pack('<IHH', IO_REPARSE_TAG_MOUNT_POINT, len(mount), 0) + mount
        set_point = ctypes.WinDLL('kernel32', use_last_error=True).DeviceIoControl
        set_point.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                              wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        if not set_point(handle, FSCTL_SET_REPARSE_POINT, data, len(data), None, 0, ctypes.byref(wintypes.DWORD()), None):
            raise ctypes.WinError(ctypes.get_last_error())
        yield alias
    finally:
        _winapi.CloseHandle(handle)
