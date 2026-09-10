# -*- coding: utf-8 -*-
"""Shared local SQLite location and transaction primitives.

Domain stores own their tables and queries.  This module only owns the one
database file, one process lock, and the small connection/time utilities that
all domain stores share.
"""

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
    elif getattr(sys, "frozen", False):
        if os.name == "nt":
            base = (os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
                    or os.path.expanduser("~/AppData/Roaming"))
            directory = os.path.join(base, "RunTeams.ai")
        elif sys.platform == "darwin":
            directory = os.path.expanduser("~/Library/Application Support/RunTeams.ai")
        else:
            base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            directory = os.path.join(base, "runteams")
    else:
        directory = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(directory, exist_ok=True)
    return directory


_DATA_DIR = data_dir()
DB_PATH = os.path.join(_DATA_DIR, "runteams.db")
lock = threading.Lock()


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def after(seconds):
    return (datetime.datetime.now() + datetime.timedelta(seconds=max(0, int(seconds or 0)))).strftime(
        "%Y-%m-%d %H:%M:%S")


@contextmanager
def conn():
    """Open one transactional SQLite connection and always release its handles."""
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
