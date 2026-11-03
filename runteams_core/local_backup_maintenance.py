"""Idle automatic backups through the existing portable engine; host-owned policy."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from . import backup_files as disk
from .local_backups import operation_id, failure
from .library_assets import AssetConflict
from .local_host_lock import RuntimeBusy

DAY = 86400
KEEPS = (7, 14, 30)


class AutomaticBackups:
    def __init__(self, app, *, clock=time.time, interval=60, initial_delay=30):
        self.app, self.clock = app, clock
        self.interval, self.initial_delay = interval, initial_delay
        self.path = app.backups.root/'policy.sqlite3'
        self.error_path = app.backups.root/'automatic-error.json'
        self.stop_event = threading.Event()
        self.thread = None

    @contextmanager
    def connect(self):
        for path in (self.path, Path(str(self.path)+'-wal'), Path(str(self.path)+'-shm')):
            if path.is_symlink():raise ValueError('自动备份设置路径无效。')
        try:fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError:pass
        else:os.close(fd)
        c=sqlite3.connect(self.path,timeout=10)
        try:
            c.execute('BEGIN IMMEDIATE')
            version=c.execute('PRAGMA user_version').fetchone()[0]
            if version==0:
                if c.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():raise ValueError('自动备份设置格式无效。')
                c.execute('CREATE TABLE policy(singleton INTEGER PRIMARY KEY CHECK(singleton=1),revision INTEGER NOT NULL,enabled INTEGER NOT NULL,keep INTEGER NOT NULL)')
                c.execute('CREATE TABLE operations(id TEXT PRIMARY KEY,digest TEXT NOT NULL,receipt TEXT NOT NULL)')
                c.execute('INSERT INTO policy VALUES(1,0,1,7)');c.execute('PRAGMA user_version=1')
            elif version!=1:raise ValueError('自动备份设置格式无效。')
            yield c
            c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()

    def policy(self):
        with self.connect() as c:
            revision,enabled,keep=c.execute('SELECT revision,enabled,keep FROM policy WHERE singleton=1').fetchone()
        if type(revision) is not int or revision<0 or enabled not in (0,1) or keep not in KEEPS:raise ValueError('自动备份设置无效。')
        return {'revision':revision,'enabled':bool(enabled),'keep':keep}

    def save(self, data):
        if set(data)!={'operation_id','expected_revision','patch'}:raise ValueError('备份设置字段无效。')
        identifier=operation_id(data['operation_id']);patch=data['patch'];revision=data['expected_revision']
        if (type(revision) is not int or revision<0 or not isinstance(patch,dict) or not patch or set(patch)-{'enabled','keep'}
            or ('enabled' in patch and type(patch['enabled']) is not bool) or ('keep' in patch and (type(patch['keep']) is not int or patch['keep'] not in KEEPS))):raise ValueError('备份设置选项无效。')
        digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        with self.connect() as c:
            old=c.execute('SELECT digest,receipt FROM operations WHERE id=?',(identifier,)).fetchone()
            if old:
                if old[0]!=digest:raise AssetConflict('原操作不能改用其他备份设置。')
                return json.loads(old[1])
            current,enabled,keep=c.execute('SELECT revision,enabled,keep FROM policy WHERE singleton=1').fetchone()
            if revision!=current:raise AssetConflict('备份设置已变化，请重新读取。')
            policy={'revision':revision+1,'enabled':patch.get('enabled',bool(enabled)),'keep':patch.get('keep',keep)}
            value={'operation_id':identifier,'kind':'policy','state':'completed','policy':policy}
            c.execute('UPDATE policy SET revision=?,enabled=?,keep=? WHERE singleton=1',(policy['revision'],int(policy['enabled']),policy['keep']))
            c.execute('INSERT INTO operations VALUES(?,?,?)',(identifier,digest,json.dumps(value)))
        return value

    def receipt(self, identifier):
        with self.connect() as c:row=c.execute('SELECT receipt FROM operations WHERE id=?',(operation_id(identifier),)).fetchone()
        if row is None:raise KeyError('原设置操作尚未受理。')
        return json.loads(row[0])

    def entries(self):
        values=[]
        for path in (self.app.backups.root/'operations').glob('*.json'):
            from .library_backup import load
            value=load(path)
            if (value.get('kind')=='backup' and value.get('source')=='automatic' and value.get('state')=='completed'
                and value.get('library_id')==self.app.binding.library_id and value.get('retained') is not False
                and self.app.backups.path('archives',value['operation_id'],'.zip').is_file()):values.append(value)
        return sorted(values,key=lambda v:(v['created_at'],v['operation_id']),reverse=True)

    def summary(self):
        error=None
        if self.error_path.exists():
            from .library_backup import load
            saved=load(self.error_path)
            if (saved['library_id'],saved['generation'])==(self.app.binding.library_id,self.app.backups.generation):error=saved
        return {'policy':self.policy(),'automatic_backups':[self.app.backups.status(v['operation_id']) for v in self.entries()], 'automatic_error':error}

    def verified(self, value):
        path=self.app.backups.path('archives',value['operation_id'],'.zip')
        if disk.file_digest(path)!=value['archive_sha256']:raise ValueError('自动备份校验未通过，原文件已保留。')
        if self.app.backups.inspect_archive(path)['library_id']!=self.app.binding.library_id:raise ValueError('自动备份资料身份不一致，原文件已保留。')
        return path

    def run_once(self):
        # Never open a runtime just to maintain an unused library.
        if self.app._runtime is None and not any(self.app.binding.root.iterdir()):return {'deferred':True}
        stage='backup'
        try:
            with self.app.exclusive():
                policy=self.policy()
                if not policy['enabled']:return {'disabled':True}
                now=self.clock();entries=self.entries()
                recent=next((v for v in entries if v.get('generation')==self.app.backups.generation
                    and 0<=now-datetime.fromisoformat(v['created_at']).timestamp()<DAY),None)
                created=None
                if recent is None:
                    timestamp=datetime.fromtimestamp(now,timezone.utc).isoformat()
                    created=str(uuid.uuid4())
                    self.app.backups.create(self.app,created,automatic=True,created_at=timestamp)
                    entries=self.entries()
                if created:entries.sort(key=lambda v:v['operation_id']!=created)
                stage='retention'
                # A verified retained copy is required even when only policy changed.
                if len(entries)>policy['keep']:self.verified(entries[0])
                removed=[]
                for value in entries[policy['keep']:]:
                    path=self.verified(value)
                    self.app.check();path.unlink();disk.sync_directory(path.parent)
                    self.app.backups.record(value['operation_id'],{**value,'retained':False})
                    removed.append(value['operation_id'])
                self.error_path.unlink(missing_ok=True)
                return {'created':recent is None,'removed':removed}
        except RuntimeBusy:return {'deferred':True}
        except Exception as error:
            value={'library_id':self.app.binding.library_id,'generation':self.app.backups.generation,'time':self.clock(),'stage':stage,'error':failure(error)}
            try:disk.replace_json(self.error_path,value)
            except OSError:pass
            return {'error':value['error']}

    def start(self):
        if self.thread is not None:return
        self.app.own();self.stop_event.clear()
        def worker():
            if self.stop_event.wait(self.initial_delay):return
            while not self.stop_event.is_set():
                result=self.run_once()
                if self.stop_event.wait(300 if 'error' in result else self.interval):return
        self.thread=threading.Thread(target=worker,name='runteams-local-backups',daemon=True);self.thread.start()

    def close(self):
        self.stop_event.set()
        thread=self.thread
        if thread is not None:
            thread.join(timeout=30)
            if thread.is_alive():raise RuntimeBusy('自动备份仍在收尾，原运行锁保持。')
            if self.thread is thread:self.thread=None
