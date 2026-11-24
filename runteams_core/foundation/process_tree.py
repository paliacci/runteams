"""Own a subprocess and its descendants until the caller stops the tree."""
import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field

if os.name == 'nt':
    from runteams_core.foundation import windows_job


@dataclass
class _Ownership:
    job: object = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    stopped: bool = False


def start(argv, **options):
    """Return a Popen with ordinary pipes, wait and poll, plus owned descendants."""
    owner = _Ownership()
    if os.name == 'nt':
        process, owner.job = windows_job.start(argv, options)
    else:
        process = subprocess.Popen(argv, start_new_session=True, **options)
    process._runteams_tree = owner
    return process


def _signal_group(group, action):
    try:
        os.killpg(group, action)
    except ProcessLookupError:
        return
    except PermissionError:
        # Darwin can deny a signal when the group contains only zombies.
        # Treat denial as success only if the kernel inventory confirms this.
        try:
            result = subprocess.run(['/bin/ps', '-axo', 'pgid=,stat='],
                                    capture_output=True, timeout=3,
                                    env={'PATH': os.defpath, 'LC_ALL': 'C'})
            if result.returncode or len(result.stdout) > 1024 * 1024:
                raise ValueError('unavailable process inventory')
            for line in result.stdout.decode('ascii').splitlines():
                pgid, state = line.split()
                if not state[0].isalpha() or not pgid.isdigit():
                    raise ValueError('invalid process inventory')
                if int(pgid) == group and not state.startswith('Z'):
                    raise ValueError('live group member')
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise PermissionError('process_group_stop_unconfirmed') from None


def stop(process, *, grace=1):
    """Stop descendants even after the leader exits. Failed stops can be retried."""
    owner = process._runteams_tree
    with owner.lock:
        if owner.stopped:
            return
        if owner.job is not None:
            owner.job.stop()
        else:
            if grace:
                try:
                    _signal_group(process.pid, signal.SIGTERM)
                    process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    pass
            _signal_group(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        owner.stopped = True


def run(argv, *, timeout, **options):
    """Run a bounded probe and release its descendants on every exit path."""
    process = start(argv, **options)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    finally:
        try:
            stop(process, grace=0)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
