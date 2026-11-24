"""Fixed trusted validator entry points for source and packaged execution."""
import os
from pathlib import Path
import sys


WORKERS = {
    'inspect': 'authoring/workers/creator_import_worker.py',
    'schema': 'authoring/workers/creator_validator_worker.py',
    'build': 'authoring/workers/creator_local_build_worker.py',
}


def command(kind):
    if kind not in WORKERS:
        raise ValueError('Unknown creator worker')
    if not getattr(sys, 'frozen', False):
        script = Path(__file__).resolve().parents[2] / WORKERS[kind]
        return [sys.executable, '-I', '-B', '-X', 'utf8', str(script)]
    # Reuse the signed product executable in its early private worker mode.
    # The process stays separate; no second CPython/library payload, PATH search,
    # environment override, author interpreter, or application startup occurs.
    return [sys.executable, '--runteams-creator-' + kind]


# CPU seconds, per-file output bytes, and Windows job commit bytes.
_MIB = 1024 * 1024
_BUDGETS = {
    'inspect': (15, 32 * _MIB, 768 * _MIB),
    'schema': (2, 4096, 128 * _MIB),
    'build': (180, 34 * _MIB, 768 * _MIB),
}


def environment(scratch=None):
    env = {'PATH': os.defpath, 'LANG': 'en_US.UTF-8'}
    if os.name == 'nt':
        for key in ('SystemRoot', 'TEMP', 'TMP'):
            if key in os.environ:
                env[key] = os.environ[key]
        # Windows' os.defpath includes the current directory.
        env['PATH'] = str(Path(env['SystemRoot']) / 'System32')
    if scratch is not None:
        env.update(HOME=str(scratch), TMPDIR=str(scratch))
        if os.name == 'nt':
            env.update(TEMP=str(scratch), TMP=str(scratch))
    return env


def start(kind, **options):
    from runteams_core.foundation import process_tree
    cpu, _, memory = _BUDGETS[kind]
    return process_tree.start(command(kind), env=environment(),
                              windows_limits={'cpu_seconds': cpu, 'memory_bytes': memory},
                              **options)


def apply_limits(kind):
    if os.name != 'nt':
        import resource
        cpu, file_bytes, memory = _BUDGETS[kind]
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
        if sys.platform == 'linux' and kind == 'inspect':
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))


def build(request, *, cancelled=lambda: False):
    """Run the same bounded builder for new builds and retained-artifact checks."""
    import subprocess
    import tempfile
    import time
    from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, strict_json
    from runteams_core.foundation import process_tree

    with tempfile.TemporaryFile() as inp, tempfile.TemporaryFile() as out:
        inp.write(canonical(request))
        inp.seek(0)
        child = start('build', stdin=inp, stdout=out, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 190
            while child.poll() is None:
                if cancelled():
                    return {'state': 'cancelled', 'code': 'build_cancelled', 'diagnostic': ''}
                if time.monotonic() >= deadline:
                    raise CreatorContractError('build_budget')
                try:
                    child.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            process_tree.stop(child, grace=0)
        out.seek(0)
        raw = out.read(128 * 1024 + 1)
        if child.returncode or len(raw) > 128 * 1024:
            raise CreatorContractError('build_worker_failed')
        result = strict_json(raw)
        if not isinstance(result, dict) or result.get('state') not in ('succeeded', 'failed', 'cancelled'):
            raise CreatorContractError('build_worker_failed')
        return result
