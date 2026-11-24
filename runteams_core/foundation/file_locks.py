"""Exclusive locks on dedicated files, held until the returned descriptor closes."""
import errno
import os
import stat
import time


def _open_windows_lock(path, blocking):
    import _winapi
    import msvcrt

    # A synchronous handle with no sharing excludes other owners even when
    # the file is empty. Crashes release it without a separate cleanup step.
    open_always = 4
    open_reparse_point = 0x00200000
    while True:
        try:
            handle = _winapi.CreateFile(
                os.fsdecode(path), _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                0, _winapi.NULL, open_always, open_reparse_point, _winapi.NULL,
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


def acquire(path, *, blocking=True):
    """Open or create a regular lock file and take exclusive ownership."""
    if os.name == 'nt':
        fd = _open_windows_lock(path, blocking)
    else:
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('锁文件无效。')
        if os.name != 'nt':
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise
