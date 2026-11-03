"""Isolated packaging probe using the same entry as the product executable."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sys
from runteams_core.creator_worker_entry import dispatch

if not dispatch(sys.argv[1:]):raise SystemExit(2)
