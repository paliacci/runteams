"""Open a regular source file without following its final symbolic link."""
import errno
from contextlib import ExitStack
import os
from pathlib import Path
import stat


def storage_path(path):
    """Use an absolute extended path for application-owned Windows file trees."""
    if os.name != 'nt':
        return Path(path)
    absolute = os.path.abspath(path)
    if absolute.startswith(('\\\\?\\', '\\\\.\\')):
        return Path(absolute)
    if absolute.startswith('\\\\'):
        return Path('\\\\?\\UNC\\' + absolute[2:])
    return Path('\\\\?\\' + absolute)


def sqlite_file_uri(path):
    """Encode a local SQLite filename with an empty URI authority."""
    absolute = storage_path(path).resolve()
    uri = absolute.as_uri()
    if os.name == 'nt' and absolute.drive.startswith('\\\\'):
        # pathlib treats the extended path prefix as a hostname. SQLite needs
        # its leading double slash in the filename, after the empty authority.
        return 'file://' + uri.removeprefix('file:')
    return uri


def is_link(info):
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def open_beneath(directory, parts):
    """Open a file inside a bound directory, without following child links."""
    from runteams_core.foundation.archive_paths import valid_relative
    if not parts or any('/' in part for part in parts) or not valid_relative('/'.join(parts)):
        raise OSError(errno.EINVAL, 'Expected a relative file path')
    with ExitStack() as opened:
        if os.name == 'nt':
            import _winapi
            import msvcrt
            parent = storage_path(directory)
            for part in ('', *parts[:-1]):
                parent = parent / part
                # Open each directory itself (including reparse points). Sharing
                # only reads prevents replacement or retargeting until file open.
                handle = _winapi.CreateFile(str(parent), 0x80, 1, 0, 3, 0x02200000, 0)
                try:
                    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
                except BaseException:
                    _winapi.CloseHandle(handle)
                    raise
                opened.callback(os.close, fd)
                info = os.fstat(fd)
                if is_link(info) or not stat.S_ISDIR(info.st_mode):
                    raise OSError(errno.ENOTDIR, 'Expected a regular directory', parent)
            return open_readonly(parent / parts[-1])
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        opened.callback(os.close, parent)
        for part in parts[:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            opened.callback(os.close, parent)
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)


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
