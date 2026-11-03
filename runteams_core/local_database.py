# -*- coding: utf-8 -*-
"""Host-only SQLite location; saved business transactions route to Supabase."""

import datetime
from contextlib import contextmanager
import os
import sqlite3
import sys
import threading
import time


def data_dir():
    """Return the writable RunTeams application data directory."""
    configured = os.environ.get("RUNTEAMS_DATA")
    if configured:
        directory = configured
    elif os.name == "nt":
        base = (os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
                or os.path.expanduser("~/AppData/Roaming"))
        directory = os.path.join(base, "RunTeams.ai")
    elif sys.platform == "darwin":
        directory = os.path.expanduser("~/Library/Application Support/RunTeams.ai")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        directory = os.path.join(base, "runteams")
    os.makedirs(directory, exist_ok=True)
    return directory


_DATA_DIR = data_dir()
DB_PATH = os.path.join(_DATA_DIR, "runteams.db")
lock = threading.Lock()


def timestamp(value):
    """Parse an explicit instant; wall-clock strings have no persisted meaning."""
    if not isinstance(value, str) or not value:
        raise ValueError("时间必须包含时区")
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return parsed.astimezone(datetime.timezone.utc)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def after(seconds):
    return (datetime.datetime.now(datetime.timezone.utc) +
            datetime.timedelta(seconds=max(0, int(seconds or 0)))).isoformat(timespec="seconds")


@contextmanager
def host_conn():
    """Open the host execution/security store, never a business database."""
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        for attempt in range(600):
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 599:
                    raise
                time.sleep(0.05)
        connection.execute("PRAGMA foreign_keys=ON")
        with connection:
            yield connection
    finally:
        connection.close()


@contextmanager
def conn():
    """Business rows always reach cloud; host tables use the host transaction."""
    from runteams_core.business_storage import storage_for
    with storage_for(DB_PATH).connect() as connection:
        yield connection
