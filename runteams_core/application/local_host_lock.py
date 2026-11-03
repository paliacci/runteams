"""One local host owner, including atomic library replacement during recovery."""
from pathlib import Path
import sqlite3


class RuntimeBusy(RuntimeError):
    pass


def acquire(directory):
    path=Path(directory)/'.local-runtime.sqlite3'
    if path.is_symlink():raise ValueError('本机运行锁无效。')
    connection=sqlite3.connect(path,timeout=0,check_same_thread=False)
    path.chmod(0o600)
    try:connection.execute('BEGIN EXCLUSIVE')
    except sqlite3.OperationalError:
        connection.close();raise RuntimeBusy('此资料库已在另一进程打开。') from None
    return connection
