"""Fixed trusted validator entry points for source and packaged execution."""
from pathlib import Path
import sys


WORKERS = {'inspect': 'authoring/workers/creator_import_worker.py', 'schema': 'authoring/workers/creator_validator_worker.py', 'build': 'authoring/workers/creator_local_build_worker.py'}


def command(kind):
    if kind not in WORKERS:raise ValueError('Unknown creator worker')
    if not getattr(sys,'frozen',False):
        return [sys.executable,'-I','-B',str(Path(__file__).resolve().parents[2] / WORKERS[kind])]
    # Reuse the signed product executable in its early private worker mode.
    # The process stays separate; no second CPython/library payload, PATH search,
    # environment override, author interpreter, or application startup occurs.
    return [sys.executable,'--runteams-creator-'+kind]
