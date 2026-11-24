"""Publish complete JSON records atomically on the destination filesystem."""
import json
import os
from pathlib import Path
import uuid


def _publish(temporary, destination, replace):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        move = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        # Same-directory rename. Without REPLACE_EXISTING a competing first
        # writer wins, and WRITE_THROUGH requests the on-disk move before return.
        flags = 0x8 | (0x1 if replace else 0)
        if not move(str(temporary), str(destination), flags):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        if replace:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def publish_json(path, value, *, replace=False):
    destination = Path(path)
    temporary = destination.with_name('.pending-' + uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        _publish(temporary, destination, replace)
    finally:
        temporary.unlink(missing_ok=True)
