"""Local backup operations, durable receipts and crash-safe library publication."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import uuid
import zipfile

from . import backup_files as disk, library_backup as backup
from .local_library import private_directory, scope_for, SCHEMA as LIBRARY_SCHEMA
from .local_host_lock import RuntimeBusy, acquire
from .library_assets import AssetConflict


def operation_id(value):
    if not isinstance(value,str) or str(uuid.UUID(value))!=value:raise ValueError('备份操作标识无效。')
    return value


def failure(error):
    return str(error)[:400] if isinstance(error,ValueError) else '本机文件无法保存或读取，请检查磁盘后重试。'


class LocalBackups:
    def __init__(self, directory):
        self.directory=Path(directory);self.root=private_directory(self.directory/'library-backups')
        self.lock=threading.RLock()
        for name in ('operations','archives','imports'):private_directory(self.root/name)
        path=self.root/'state.json'
        if not path.exists() and not path.is_symlink():
            try:disk.write_json(path,{'schema':'runteams.library-backup-host/1','generation':str(uuid.uuid4())})
            except FileExistsError:pass
        self.state()

    def state(self):
        value=backup.load(self.root/'state.json')
        if set(value)!={'schema','generation'} or value['schema']!='runteams.library-backup-host/1':raise ValueError('本机恢复状态无效。')
        operation_id(value['generation']);return value

    @property
    def generation(self):return self.state()['generation']

    def path(self, group, identifier, suffix):
        path=self.root/group/(operation_id(identifier)+suffix)
        if self.root.is_symlink() or path.parent.is_symlink() or path.is_symlink():raise ValueError('备份文件路径无效。')
        return path

    def receipt(self, identifier):
        path=self.path('operations',identifier,'.json')
        return backup.load(path) if path.exists() else None

    def record(self, identifier, value):disk.replace_json(self.path('operations',identifier,'.json'),value)

    def status(self, identifier):
        result=self.receipt(identifier)
        if not result:raise KeyError('原操作尚未受理。')
        return {k:v for k,v in result.items() if k in {'operation_id','kind','state','created_at','library_id','backup_id','safety_backup_id','error'}}

    def summary(self, library_id):
        values=[backup.load(p) for p in (self.root/'operations').glob('*.json')]
        complete=sorted((v for v in values if v.get('state')=='completed'),key=lambda v:v['created_at'],reverse=True)
        last_backup=next((v for v in complete if v['kind']=='backup' and v.get('source')!='automatic' and v['library_id']==library_id),None)
        last_restore=next((v for v in complete if v['kind']=='restore' and v['library_id']==library_id),None)
        return {'last_backup':self.status(last_backup['operation_id']) if last_backup else None,'last_restore':self.status(last_restore['operation_id']) if last_restore else None}

    def prior(self, identifier, kind, digest):
        value=self.receipt(identifier)
        if value and (value.get('kind')!=kind or value.get('digest')!=digest):raise AssetConflict('原操作不能使用不同的备份内容。')
        return value

    def create(self, app, identifier, *, automatic=False, created_at=None):
        identifier=operation_id(identifier);digest='backup:'+app.binding.library_id
        if automatic:digest+=':automatic:'+self.generation
        previous=self.prior(identifier,'backup',digest)
        if previous:
            if previous['state'] in ('completed','failed'):return self.status(identifier)
            if previous['state']=='pending':raise RuntimeBusy('备份结果尚未确认，请读取原操作。')
        value={'operation_id':identifier,'kind':'backup','digest':digest,'state':'pending','created_at':datetime.now(timezone.utc).isoformat(),'library_id':app.binding.library_id}
        if automatic:value.update(source='automatic',generation=self.generation,created_at=created_at or value['created_at'])
        self.record(identifier,value)
        temporary=self.root/('.snapshot-'+identifier);packed=self.root/('.archive-'+identifier+'.zip')
        try:
            if temporary.exists():shutil.rmtree(temporary)
            packed.unlink(missing_ok=True)
            backup.snapshot(app,temporary);disk.pack(temporary,packed)
            # Verify the actual portable transport before publishing a receipt.
            self.inspect_archive(packed)
            if automatic:
                value['archive_sha256']=disk.file_digest(packed)
                self.record(identifier,value)
            os.replace(packed,self.path('archives',identifier,'.zip'));disk.sync_directory(self.root/'archives')
            self.record(identifier,{**value,'state':'completed','backup_id':identifier})
            return self.status(identifier)
        except BaseException as error:
            if not self.path('archives',identifier,'.zip').exists():
                self.record(identifier,{**value,'state':'failed','error':failure(error)})
            raise
        finally:
            if temporary.exists():shutil.rmtree(temporary)
            packed.unlink(missing_ok=True)

    def inspect_archive(self, path):
        directory=self.root/('.inspect-'+uuid.uuid4().hex)
        try:
            disk.unpack(path,directory);return backup.verify(directory)
        except (zipfile.BadZipFile,zipfile.LargeZipFile,NotImplementedError,sqlite3.Error,OSError,KeyError,TypeError,json.JSONDecodeError,UnicodeError) as error:
            raise ValueError('备份文件损坏、缺失或格式无效。') from error
        finally:
            if directory.exists():shutil.rmtree(directory)

    def upload(self, stream, length, identifier):
        identifier=operation_id(identifier)
        if not 1<=length<=disk.MAX_ARCHIVE:raise ValueError('请选择不超过512MB的备份。')
        temporary=self.root/('.upload-'+uuid.uuid4().hex)
        try:
            sha=hashlib.sha256();remaining=length
            with temporary.open('xb') as output:
                temporary.chmod(0o600)
                while remaining:
                    block=stream.read(min(1024*1024,remaining))
                    if not block:raise ValueError('备份上传未完成。')
                    output.write(block);sha.update(block);remaining-=len(block)
                output.flush();os.fsync(output.fileno())
            meta=self.path('imports',identifier,'.json')
            if meta.exists():
                value=backup.load(meta)
                if value['sha256']!=sha.hexdigest():raise AssetConflict('同一上传操作不能选择另一份文件。')
                return value['preview']
            manifest=self.inspect_archive(temporary)
            os.replace(temporary,self.path('imports',identifier,'.zip'));disk.sync_directory(self.root/'imports')
            preview={'import_id':identifier,'library_id':manifest['library_id'],'created_at':manifest['created_at'],'files':len(manifest['files'])}
            disk.write_json(meta,{'sha256':sha.hexdigest(),'preview':preview});disk.sync_directory(meta.parent)
            return preview
        finally:temporary.unlink(missing_ok=True)

    def download(self, identifier):
        value=self.receipt(identifier)
        if not value or value.get('kind')!='backup' or value.get('state')!='completed':raise KeyError('备份尚未完成。')
        path=self.path('archives',identifier,'.zip')
        self.inspect_archive(path)
        return path

    def _finish(self, pending):
        identifier=pending['operation_id'];stage=self.directory/pending['stage'];previous=self.directory/pending['previous'];base=self.directory/'device-data'
        if stage.exists():
            # Publication has not completed. Restore the exact original tree.
            if previous.exists():
                if base.exists():raise ValueError('恢复目录状态不一致，原资料均已保留。')
                os.replace(previous,base);disk.sync_directory(self.directory)
            if not base.exists():raise ValueError('原资料目录不可用，请保留恢复文件。')
            self.record(identifier,{**pending['receipt'],'state':'failed','error':'恢复未完成，原资料已保留。'})
            shutil.rmtree(stage)
        elif previous.exists() and base.exists():
            # Rename published the whole new tree; finish its receipt, never
            # replay another restore over newly written data.
            marker=backup.load(base/'.local-library.json')
            if marker!={'schema':LIBRARY_SCHEMA,'library_id':pending['library_id']}:raise ValueError('恢复资料库身份不一致。')
            disk.replace_json(self.root/'state.json',{'schema':'runteams.library-backup-host/1','generation':pending['generation']})
            self.record(identifier,{**pending['receipt'],'state':'completed'})
            try:shutil.rmtree(previous)
            except OSError:return
            self.path('imports',pending['import_id'],'.zip').unlink(missing_ok=True)
        else:
            # A completed journal can be left behind only after cleanup.
            receipt=self.receipt(identifier)
            if not receipt or receipt['state'] not in ('completed','failed'):raise ValueError('恢复状态未确认，请保留本机资料。')
        (self.root/'restore-pending.json').unlink(missing_ok=True);disk.sync_directory(self.root)

    def restoring(self):
        path=self.root/'restore-pending.json'
        if not path.exists():return False
        value=backup.load(path);receipt=self.receipt(value['operation_id'])
        return not receipt or receipt.get('state')!='completed'

    def recover(self, *, owned=False):
        path=self.root/'restore-pending.json'
        pending=[backup.load(p) for p in (self.root/'operations').glob('*.json') if backup.load(p).get('state')=='pending']
        if not path.exists() and not pending:return
        lease=None if owned else acquire(self.directory)
        try:
            if path.exists():
                value=backup.load(path)
                operation_id(value['operation_id']);operation_id(value['import_id']);operation_id(value['generation'])
                if value['stage']!='.restore-stage-'+value['operation_id'] or value['previous']!='.restore-previous-'+value['operation_id']:raise ValueError('恢复目录记录无效。')
                self._finish(value)
            for value in pending:
                identifier=operation_id(value['operation_id']);current=self.receipt(identifier)
                if current['state']!='pending':continue
                if value['kind']=='backup':
                    archive=self.path('archives',identifier,'.zip')
                    if archive.exists():
                        if value.get('source')=='automatic':
                            try:
                                manifest=self.inspect_archive(archive)
                                if manifest['library_id']!=value['library_id'] or disk.file_digest(archive)!=value['archive_sha256']:raise ValueError('自动备份校验失败。')
                            except (ValueError,OSError,KeyError):
                                message='上次自动备份未通过校验，原资料和备份文件均已保留。'
                                self.record(identifier,{**value,'state':'failed','error':message})
                                disk.replace_json(self.root/'automatic-error.json',{'library_id':value['library_id'],'generation':value['generation'],'time':datetime.now(timezone.utc).timestamp(),'stage':'backup','error':message})
                            else:self.record(identifier,{**value,'state':'completed','backup_id':identifier})
                        else:
                            self.inspect_archive(archive);self.record(identifier,{**value,'state':'completed','backup_id':identifier})
                    else:self.record(identifier,{**value,'state':'failed','error':'上次备份未完成，原资料保持不变。'})
                    temporary=self.root/('.snapshot-'+identifier)
                    if temporary.exists():shutil.rmtree(temporary)
                    (self.root/('.archive-'+identifier+'.zip')).unlink(missing_ok=True)
                elif value['kind']=='restore':
                    stage=self.directory/('.restore-stage-'+identifier);previous=self.directory/('.restore-previous-'+identifier)
                    if previous.exists():raise ValueError('恢复记录缺失，请保留原资料目录。')
                    self.record(identifier,{**value,'state':'failed','error':'上次恢复未开始，原资料保持不变。'})
                    if stage.exists():shutil.rmtree(stage)
                else:raise ValueError('备份操作记录无效。')
        finally:
            if lease:lease.rollback();lease.close()

    def restore(self, app, identifier, import_id):
        identifier=operation_id(identifier);import_id=operation_id(import_id);digest='restore:'+import_id
        old=self.prior(identifier,'restore',digest)
        if old:
            if old['state'] in ('completed','failed'):return self.status(identifier)
            if old['state']=='pending':self.recover(owned=True);return self.status(identifier)
        if (self.root/'restore-pending.json').exists():
            self.recover(owned=True)
            if (self.root/'restore-pending.json').exists():raise RuntimeBusy('上次恢复的文件尚待清理，请检查磁盘后重试。')
        receipt={'operation_id':identifier,'kind':'restore','digest':digest,'state':'pending','created_at':datetime.now(timezone.utc).isoformat(),'library_id':app.binding.library_id}
        self.record(identifier,receipt)
        try:
            if any(p.name not in {'.local-library.json','libraries'} for p in app.base.iterdir()):
                raise ValueError('此目录含有其他版本的资料，请为免费版使用独立资料目录后再恢复。')
            source=self.path('imports',import_id,'.zip');manifest=self.inspect_archive(source)
            safety=str(uuid.uuid5(uuid.UUID(identifier),'before-restore'))
            self.create(app,safety)
        except BaseException as error:
            self.record(identifier,{**receipt,'state':'failed','error':failure(error)});raise
        stage=self.directory/('.restore-stage-'+identifier);previous=self.directory/('.restore-previous-'+identifier)
        if stage.exists() or previous.exists():raise ValueError('原恢复目录尚待确认，请读取原操作。')
        extracted=self.root/('.restore-input-'+identifier)
        receipt={**receipt,'library_id':manifest['library_id'],'safety_backup_id':safety}
        try:
            disk.unpack(source,extracted);backup.verify(extracted)
            scope=scope_for(manifest['library_id']);target=stage/'libraries'/scope['storage_namespace'];target.mkdir(mode=0o700,parents=True)
            for name in manifest['directories']:(target/disk.safe_name(name)).mkdir(mode=0o700,parents=True,exist_ok=True)
            (target/'workspaces/assistant').mkdir(mode=0o700,parents=True,exist_ok=True)
            for name in manifest['files']:
                path=target/disk.safe_name(name);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);shutil.copyfile(extracted/name,path);path.chmod(0o600)
                with path.open('rb') as f:os.fsync(f.fileno())
            backup.folders(target,final_root=app.base/'libraries'/scope['storage_namespace'])
            backup.verify_payload(target,manifest,portable=False)
            from .device_work import quarantine_restored
            quarantine_restored(target)
            from .device_employee_schedules import quarantine_restored as quarantine_employee_schedules
            from .source_pipeline_schedules import quarantine_restored as quarantine_pipeline_schedules
            quarantine_employee_schedules(target);quarantine_pipeline_schedules(target)
            app.runtime.retire_employee_services()
            disk.write_json(stage/'.local-library.json',{'schema':LIBRARY_SCHEMA,'library_id':manifest['library_id']})
            for folder in sorted((p for p in stage.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):folder.chmod(0o700);disk.sync_directory(folder)
            stage.chmod(0o700);disk.sync_directory(stage)
            pending={'operation_id':identifier,'import_id':import_id,'library_id':manifest['library_id'],'generation':str(uuid.uuid4()),'stage':stage.name,'previous':previous.name,'receipt':receipt}
            self.record(identifier,receipt);disk.replace_json(self.root/'restore-pending.json',pending)
            os.replace(app.base,previous);disk.sync_directory(self.directory)
            os.replace(stage,app.base);disk.sync_directory(self.directory)
            self._finish(pending)
            app.rebind()
            return self.status(identifier)
        except BaseException:
            if (self.root/'restore-pending.json').exists():
                self.recover(owned=True);app.rebind()
                result=self.status(identifier)
                if result['state']=='completed':return result
            else:
                if stage.exists():shutil.rmtree(stage)
                self.record(identifier,{**receipt,'state':'failed','error':'备份恢复未完成，原资料保持不变。'})
            raise
        finally:
            if extracted.exists():shutil.rmtree(extracted)
