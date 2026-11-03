"""Only explicit backup operations; client paths never select server files."""
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class BackupDownload:
    path:Path
    name:str


def dispatch(app,method,path,data,scope):
    if not isinstance(data,dict):raise ValueError('请求字段无效。')
    from .local_application import _fields
    if path=='/api/backups' and method=='GET':
        _fields(data,set())
        with app.request(scope):return {**app.backups.summary(app.binding.library_id),**app.automatic_backups.summary()}
    if path=='/api/backups/policy' and method=='POST':
        with app.request(scope):return app.automatic_backups.save(data)
    policy=re.fullmatch(r'/api/backups/policy/([0-9a-f-]{36})/status',path)
    if policy and method=='GET':
        _fields(data,set())
        with app.request(scope):return app.automatic_backups.receipt(policy[1])
    if path=='/api/backups' and method=='POST':
        _fields(data,{'operation_id'})
        with app.exclusive(scope):return app.backups.create(app,data['operation_id'])
    if path=='/api/backups/restore' and method=='POST':
        _fields(data,{'operation_id','import_id'})
        with app.exclusive(scope):
            result=app.backups.restore(app,data['operation_id'],data['import_id'])
            return result
    match=re.fullmatch(r'/api/backups/([0-9a-f-]{36})/(status|download)',path)
    if match and method=='GET':
        _fields(data,set())
        if match[2]=='status' and (app.backups.receipt(match[1]) or {}).get('state')=='pending':
            with app.exclusive(scope):app.backups.recover(owned=True);app.rebind()
        with app.request(scope):
            if match[2]=='status':return app.backups.status(match[1])
            return BackupDownload(app.backups.download(match[1]),'RunTeams-'+match[1][:8]+'.zip')
    raise KeyError('备份接口不存在。')
