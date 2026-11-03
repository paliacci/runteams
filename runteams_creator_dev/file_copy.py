"""Independent dev-tool copies, sharing physical blocks where supported."""
import ctypes
import errno
import os
from pathlib import Path
import shutil
import sys


def copy_new(source, target):
    source, target = Path(source), Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    if sys.platform == 'darwin':
        library = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        clone = library.clonefile
        clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        clone.restype = ctypes.c_int
        if clone(os.fsencode(source), os.fsencode(target), 0) == 0:
            shutil.copystat(source, target)
            return
        error = ctypes.get_errno()
        if error not in (errno.ENOTSUP, errno.EXDEV, errno.ENOSYS):
            raise OSError(error, 'development_copy_failed', str(target))
    shutil.copy2(source, target)
