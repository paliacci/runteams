"""Read only the owned worker's RSS; failure never disables resource limits."""
import ctypes
import errno
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
        try:
            lines = Path('/proc', str(pid), 'status').read_text().splitlines()
        except FileNotFoundError:
            return 0
        return int(next(line.split()[1] for line in lines if line.startswith('VmRSS:'))) * 1024
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
