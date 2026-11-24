"""Open a regular source file without following its final symbolic link."""
import errno
import os
import stat


def is_link(info):
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def open_readonly(path):
    if os.name == 'nt':
        import _winapi
        import msvcrt
        # OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT. Sharing permits the
        # existing immutable-file and atomic-replacement checks in each reader.
        handle = _winapi.CreateFile(os.fsdecode(path), _winapi.GENERIC_READ, 7, 0, 3, 0x00200000, 0)
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _winapi.CloseHandle(handle)
            raise
    else:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, 'Expected a regular file', path)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
