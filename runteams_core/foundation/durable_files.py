"""Publish complete JSON records atomically on the destination filesystem."""
import json
import os
import uuid

from runteams_core.foundation.regular_files import storage_path


def move(temporary, destination, *, replace=False):
    """Publish a staged file or directory by same-volume rename."""
    if os.name == 'nt':
        import ctypes
        import time
        from ctypes import wintypes

        rename = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileExW
        rename.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        rename.restype = wintypes.BOOL
        # Same-directory rename. Without REPLACE_EXISTING a competing first
        # writer wins, and WRITE_THROUGH requests the on-disk move before return.
        flags = 0x8 | (0x1 if replace else 0)
        # A reader or scanner can briefly hold the existing record without
        # delete sharing. Only retry the same staged rename, never its producer.
        for delay in (0, .025, .05, .1, .2, .4):
            if delay:
                time.sleep(delay)
            if rename(str(temporary), str(destination), flags):
                return
            error = ctypes.get_last_error()
            if not replace or error not in (5, 32, 33):
                break
        raise ctypes.WinError(error)
    else:
        if replace:
            os.replace(temporary, destination)
        else:
            os.rename(temporary, destination)
        sync_directory(destination.parent)


def sync_directory(path):
    """Flush POSIX directory entries. Windows publication uses write-through moves."""
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _publish(temporary, destination, replace):
    if replace or os.name == 'nt':
        move(temporary, destination, replace=replace)
    else:
        # POSIX rename could overwrite a competing writer's immutable record.
        os.link(temporary, destination)
        sync_directory(destination.parent)


def publish_json(path, value, *, replace=False):
    destination = storage_path(path)
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
