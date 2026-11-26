"""Allocate stable eight-character browser IDs in the active library."""
from contextlib import closing
import hashlib
import json
import sqlite3
import string

from runteams_core.foundation.regular_files import sqlite_file_uri

DATABASE = 'page-ids.sqlite3'
SCHEMA = """CREATE TABLE IF NOT EXISTS page_ids (
    identity TEXT PRIMARY KEY NOT NULL,
    public_id TEXT UNIQUE NOT NULL CHECK (
        length(public_id) = 8 AND public_id GLOB '[0-9][a-z]*'
        AND public_id NOT GLOB '*[^a-z0-9]*')
);"""


def _candidate(identity, attempt):
    # A digit then a letter distinguishes local pages from cloud and numeric IDs.
    number = int.from_bytes(hashlib.sha256(f'{identity}/{attempt}'.encode()).digest(), 'big')
    alphabets = (string.digits, string.ascii_lowercase) + (string.digits + string.ascii_lowercase,) * 6
    characters = []
    for alphabet in alphabets:
        number, index = divmod(number, len(alphabet))
        characters.append(alphabet[index])
    return ''.join(characters)


def lookup(directory, public_id):
    """Look up an existing public ID without allocating or modifying an identity."""
    path = directory / DATABASE
    if path.is_symlink():
        raise ValueError('资料库页面索引路径无效。')
    if not path.exists():
        return None
    with closing(sqlite3.connect(sqlite_file_uri(path) + '?mode=ro', uri=True, timeout=30)) as database:
        if not database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='page_ids'").fetchone():
            return None
        row = database.execute('SELECT identity FROM page_ids WHERE public_id=?', (public_id,)).fetchone()
    return row[0] if row else None


def resolve(directory, identities):
    keys = sorted(set(identities))
    if not keys:
        return {}
    path = directory / DATABASE
    if path.is_symlink():
        raise ValueError('资料库页面索引路径无效。')
    if not path.exists():
        path.touch(mode=0o600, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30)) as database, database:
        database.execute(SCHEMA)
        def read():
            return dict(database.execute(
                'SELECT identity,public_id FROM page_ids WHERE identity IN (SELECT value FROM json_each(?))',
                (json.dumps(keys),)))
        found = read()
        if len(found) == len(keys):
            return found
        database.execute('BEGIN IMMEDIATE')
        found = read()
        for identity in keys:
            if identity in found:
                continue
            attempt = 0
            while True:
                public_id = _candidate(identity, attempt)
                inserted = database.execute('INSERT INTO page_ids VALUES(?,?) ON CONFLICT(public_id) DO NOTHING',
                                            (identity, public_id)).rowcount
                if inserted:
                    found[identity] = public_id
                    break
                attempt += 1
        return found
