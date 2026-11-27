"""Only explicit backup operations; client paths never select server files."""
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class BackupDownload:
    path:Path
    name:str


def receive(handler, target, scope):
    from runteams_core.application.local_runtime import LocalInputError
    from runteams_core.assets.library_assets import AssetConflict
    from runteams_core.storage.backups.backup_files import MAX_ARCHIVE
    from runteams_core.storage.backups.local_backups import operation_id

    headers = handler.headers
    lengths = headers.get_all('Content-Length', [])
    operations = headers.get_all('X-RunTeams-Operation', [])
    if (target.query or headers.get_all('Transfer-Encoding') or len(operations) != 1 or
            len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()):
        raise ValueError('备份上传请求无效。')
    if headers.get_all('Content-Type') != ['application/zip']:
        return handler._json(415, {'error': '请选择ZIP备份文件。'})
    length = int(lengths[0])
    if length > MAX_ARCHIVE:
        return handler._json(413, {'error': '请选择不超过512MB的备份。'})
    identifier = operation_id(operations[0])
    handler.connection.settimeout(30)
    app = handler.server.application
    try:
        if target.path == '/api/backups/import':
            with app.request(scope):
                result = app.backups.upload(handler.rfile, length, identifier)
        elif target.path == '/api/backups/preview':
            with app.request(scope), app.backups.receive_archive(handler.rfile, length) as (source, digest):
                manifest = app.backups.inspect_archive(source)
                result = {'created_at': manifest['created_at'], 'sha256': digest}
        else:
            expected = headers.get_all('X-RunTeams-Backup-SHA256', [])
            if len(expected) != 1 or not re.fullmatch('[0-9a-f]{64}', expected[0]):
                raise ValueError('备份校验信息无效。')
            with app.exclusive(scope, wait_for_discovery=True), app.backups.receive_archive(handler.rfile, length) as uploaded:
                if uploaded[1] != expected[0]:
                    raise ValueError('备份文件已更改，请重新选择。')
                result = app.backups.restore(app, identifier, uploaded=uploaded)
    except AssetConflict:
        raise
    except ValueError as error:
        raise LocalInputError(str(error)) from error
    return handler._json(200, result)


def dispatch(app,method,path,data,scope):
    if not isinstance(data,dict):raise ValueError('请求字段无效。')
    from runteams_core.application.local_application import _fields
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
        with app.exclusive(scope,wait_for_discovery=True):return app.backups.create(app,data['operation_id'])
    if path=='/api/backups/restore' and method=='POST':
        _fields(data,{'operation_id','import_id'})
        with app.exclusive(scope,wait_for_discovery=True):
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
