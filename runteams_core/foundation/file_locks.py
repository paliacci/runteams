"""File locks held until the returned descriptor closes."""
from contextlib import contextmanager
import errno
import os
import stat
import time


def _open_windows_lock(path, blocking, readonly):
    import _winapi
    import msvcrt

    # A synchronous handle with no sharing excludes other owners even when
    # the file is empty. Crashes release it without a separate cleanup step.
    access = _winapi.GENERIC_READ if readonly else _winapi.GENERIC_READ | _winapi.GENERIC_WRITE
    share = 1 if readonly else 0  # FILE_SHARE_READ
    disposition = 3 if readonly else 4  # OPEN_EXISTING / OPEN_ALWAYS
    open_reparse_point = 0x00200000
    while True:
        try:
            handle = _winapi.CreateFile(
                os.fsdecode(path), access, share, 0, disposition, open_reparse_point, 0,
            )
            break
        except OSError as exc:
            if exc.winerror != 32:  # ERROR_SHARING_VIOLATION
                raise
            if not blocking:
                raise BlockingIOError(errno.EWOULDBLOCK, 'lock is held', path) from exc
            time.sleep(.05)
    try:
        return msvcrt.open_osfhandle(handle, 0)
    except BaseException:
        _winapi.CloseHandle(handle)
        raise


def acquire(path, *, blocking=True, readonly=False):
    """Writers create the lock file. Readers share an existing regular file."""
    if os.name == 'nt':
        fd = _open_windows_lock(path, blocking, readonly)
    else:
        flags = (os.O_RDONLY if readonly else os.O_RDWR | os.O_CREAT) | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('锁文件无效。')
        if os.name != 'nt':
            import fcntl
            mode = fcntl.LOCK_SH if readonly else fcntl.LOCK_EX
            fcntl.flock(fd, mode if blocking else mode | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def held(path, *, readonly=False):
    descriptor = acquire(path, readonly=readonly)
    try:
        yield
    finally:
        os.close(descriptor)
