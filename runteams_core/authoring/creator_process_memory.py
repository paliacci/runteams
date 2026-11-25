"""Read only the owned worker's RSS; failure never disables resource limits."""
import ctypes
import errno
import os
from functools import lru_cache
from pathlib import Path
import subprocess
import sys


class TaskInfo(ctypes.Structure):
    # Darwin sys/proc_info.h proc_taskinfo, PROC_PIDTASKINFO (4).
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'virtual_size', 'resident_size', 'total_user', 'total_system',
        'threads_user', 'threads_system')] + [(name, ctypes.c_int32) for name in (
        'policy', 'faults', 'pageins', 'cow_faults', 'messages_sent',
        'messages_received', 'syscalls_mach', 'syscalls_unix', 'csw',
        'threadnum', 'numrunning', 'priority')]


@lru_cache(maxsize=1)
def _darwin():
    library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                    ctypes.c_void_p, ctypes.c_int]
    library.proc_pidinfo.restype = ctypes.c_int
    return library


def process_rss(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError('invalid_worker_pid')
    if sys.platform == 'linux':
        # statm keeps its resident-page field even after the child's address
        # space is released. status drops VmRSS before the child is waitable.
        try:
            fields = Path('/proc', str(pid), 'statm').read_bytes().split()
        except FileNotFoundError:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return 0
            raise
        except ProcessLookupError:
            return 0
        if len(fields) != 7 or not fields[1].isdigit():
            raise ValueError('worker_memory_unavailable')
        return int(fields[1]) * os.sysconf('SC_PAGE_SIZE')
    if sys.platform == 'darwin':
        info = TaskInfo()
        ctypes.set_errno(0)
        size = _darwin().proc_pidinfo(pid, 4, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size == ctypes.sizeof(info):
            return info.resident_size
        error = ctypes.get_errno()
        if size == 0 and error == errno.ESRCH:
            return 0  # The owned process exited between poll and measurement.
        raise OSError(error or errno.EIO, 'worker_memory_unavailable')
    result = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(pid)],
                            capture_output=True, timeout=.3, check=False)
    if result.returncode or not result.stdout.strip():
        raise OSError(errno.EIO, 'worker_memory_unavailable')
    return int(result.stdout.strip()) * 1024
