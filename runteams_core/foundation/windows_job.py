"""Windows Job Object for an owned process tree (loaded only on Windows)."""
import ctypes
from ctypes import wintypes
import subprocess
import weakref

_kernel = ctypes.WinDLL('kernel32', use_last_error=True)
HANDLE, DWORD, BOOL = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
SIZE_T = ctypes.c_size_t
LIMIT_KILL_ON_JOB_CLOSE = 0x2000
CREATE_SUSPENDED = 0x4
TH32CS_SNAPTHREAD = 0x4
THREAD_SUSPEND_RESUME = 0x2
INVALID_HANDLE = HANDLE(-1).value
JOB_EXTENDED_LIMIT_INFORMATION = 9


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
        ('LimitFlags', DWORD), ('MinimumWorkingSetSize', SIZE_T), ('MaximumWorkingSetSize', SIZE_T),
        ('ActiveProcessLimit', DWORD), ('Affinity', SIZE_T), ('PriorityClass', DWORD),
        ('SchedulingClass', DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', _BasicLimits), ('IoInfo', ctypes.c_uint64 * 6),
        ('ProcessMemoryLimit', SIZE_T), ('JobMemoryLimit', SIZE_T),
        ('PeakProcessMemoryUsed', SIZE_T), ('PeakJobMemoryUsed', SIZE_T),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ('dwSize', DWORD), ('cntUsage', DWORD), ('th32ThreadID', DWORD),
        ('th32OwnerProcessID', DWORD), ('tpBasePri', wintypes.LONG),
        ('tpDeltaPri', wintypes.LONG), ('dwFlags', DWORD),
    ]


def _api(name, result, *arguments):
    function = getattr(_kernel, name)
    function.restype = result
    function.argtypes = arguments
    return function


_create_job = _api('CreateJobObjectW', HANDLE, wintypes.LPVOID, wintypes.LPCWSTR)
_set_limits = _api('SetInformationJobObject', BOOL, HANDLE, ctypes.c_int, wintypes.LPVOID, DWORD)
_assign = _api('AssignProcessToJobObject', BOOL, HANDLE, HANDLE)
_terminate = _api('TerminateJobObject', BOOL, HANDLE, wintypes.UINT)
_close = _api('CloseHandle', BOOL, HANDLE)
_snapshot = _api('CreateToolhelp32Snapshot', HANDLE, DWORD, DWORD)
_thread_first = _api('Thread32First', BOOL, HANDLE, ctypes.POINTER(_ThreadEntry))
_thread_next = _api('Thread32Next', BOOL, HANDLE, ctypes.POINTER(_ThreadEntry))
_open_thread = _api('OpenThread', HANDLE, DWORD, BOOL, DWORD)
_resume = _api('ResumeThread', DWORD, HANDLE)


def _checked(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


def _resume_primary_thread(pid):
    # Popen closes the primary thread handle. While CREATE_SUSPENDED is in
    # effect the new process has not run user code or started any children.
    snapshot = _snapshot(TH32CS_SNAPTHREAD, 0)
    if snapshot == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        _checked(_thread_first(snapshot, ctypes.byref(entry)))
        while entry.th32OwnerProcessID != pid:
            entry.dwSize = ctypes.sizeof(entry)
            _checked(_thread_next(snapshot, ctypes.byref(entry)))
        thread = _checked(_open_thread(THREAD_SUSPEND_RESUME, False, entry.th32ThreadID))
        try:
            if _resume(thread) == 0xffffffff:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _close(thread)
    finally:
        _close(snapshot)


class _Job:
    def __init__(self):
        self.handle = _checked(_create_job(None, None))
        self.close = weakref.finalize(self, _close, self.handle)
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = LIMIT_KILL_ON_JOB_CLOSE
        _checked(_set_limits(self.handle, JOB_EXTENDED_LIMIT_INFORMATION,
                             ctypes.byref(limits), ctypes.sizeof(limits)))

    def stop(self):
        if self.close.alive:
            _checked(_terminate(self.handle, 1))
            self.close()


def start(argv, options):
    job = _Job()
    process = None
    try:
        process = subprocess.Popen(argv, creationflags=CREATE_SUSPENDED, **options)
        # CPython 3.12 retains the CreateProcess handle for wait/poll.
        _checked(_assign(job.handle, int(process._handle)))
        _resume_primary_thread(process.pid)
        return process, job
    except BaseException:
        try:
            if process is not None:
                process.kill()
                process.wait(timeout=3)
        finally:
            job.close()
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
        raise
