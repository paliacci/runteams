"""Account-free interaction preferences with atomic operation receipts."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from runteams_core.configuration.interaction_settings import validate
from runteams_core.assets.library_assets import AssetConflict
from runteams_core.storage.local_library import private_directory


SCHEMA = """
CREATE TABLE settings(library_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,value TEXT NOT NULL);
CREATE TABLE operations(id TEXT PRIMARY KEY,digest TEXT NOT NULL,receipt TEXT NOT NULL);
"""

class LibrarySettings:
    def __init__(self, binding, check):
        self.binding, self.check = binding, check
        self.path = binding.root / 'interaction-settings.sqlite3'

    @contextmanager
    def connect(self):
        self.check(); private_directory(self.binding.root)
        for path in (self.path,Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm')):
            if path.is_symlink(): raise ValueError('Invalid settings path')
        try: descriptor=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        except FileExistsError: pass
        else: os.close(descriptor)
        connection=sqlite3.connect(self.path,timeout=30)
        try:
            connection.execute('BEGIN IMMEDIATE')
            version=connection.execute('PRAGMA user_version').fetchone()[0]
            if version==0:
                if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():raise ValueError('Unknown settings schema')
                from runteams_core.storage.device_schema import execute
                execute(connection,SCHEMA)
                connection.execute('INSERT INTO settings VALUES(?,0,?)',(self.binding.library_id,'{}'))
                connection.execute('PRAGMA user_version=1')
            elif version!=1:raise ValueError('Unknown settings schema')
            if connection.execute('SELECT library_id FROM settings').fetchall()!=[(self.binding.library_id,)]:raise PermissionError('Settings belong to another library')
            yield connection
            self.check();connection.commit()
        except BaseException:connection.rollback();raise
        finally:connection.close()

    def read(self):
        with self.connect() as connection:
            revision,raw=connection.execute('SELECT revision,value FROM settings').fetchone()
            value=json.loads(raw);validate(value)
            return {'library_id':self.binding.library_id,'revision':revision,'settings':value}

    def save(self, data):
        if set(data)!={'patch','expected_revision','operation_id'}:raise ValueError('Invalid settings fields')
        op=data['operation_id']
        if not isinstance(op,str) or str(uuid.UUID(op))!=op or type(data['expected_revision']) is not int or data['expected_revision']<0:raise ValueError('Invalid settings operation')
        validate(data['patch'])
        digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        with self.connect() as connection:
            previous=connection.execute('SELECT digest,receipt FROM operations WHERE id=?',(op,)).fetchone()
            if previous:
                if previous[0]!=digest:raise AssetConflict('Operation changed')
                return json.loads(previous[1])
            revision,raw=connection.execute('SELECT revision,value FROM settings').fetchone()
            if revision!=data['expected_revision']:raise AssetConflict('Settings changed')
            value={**json.loads(raw),**data['patch']};validate(value)
            receipt={'ok':True,'library_id':self.binding.library_id,'operation_id':op,'revision':revision+1,'settings':value}
            connection.execute('UPDATE settings SET revision=?,value=?',(revision+1,json.dumps(value,ensure_ascii=False)))
            connection.execute('INSERT INTO operations VALUES(?,?,?)',(op,digest,json.dumps(receipt,ensure_ascii=False)))
            return receipt
