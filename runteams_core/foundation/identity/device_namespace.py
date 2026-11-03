"""Durable device identity, independent of the business API's transport origin.

Auth issuer + authenticated account identifies every device deployment.
No cloud history import, database schema change, directory move, or data deletion.
"""
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

SCHEMA='runteams.device-deployment/v1'


def issuer(value):
    parsed=urlsplit(str(value))
    if (parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip('/')!='/auth/v1'
            or (parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1'))):
        raise ValueError('无效的登录服务身份。')
    parsed.port  # Validate malformed ports before touching any device path.
    return str(value).rstrip('/')


def _identity(scope):
    account=str(scope.get('account_id') or '')
    if not account:raise PermissionError('请先登录。')
    return issuer(scope['deployment_id']),account


def _directory(base):
    base=Path(base)
    for path in (base,base/'.identities'):
        if path.is_symlink():raise ValueError('本机数据身份目录无效。')
        path.mkdir(mode=0o700,parents=True,exist_ok=True);path.chmod(0o700)
    return base/'.identities'


def _read(path):
    if path.is_symlink():raise ValueError('本机数据身份文件无效。')
    if not path.exists():return None
    if path.stat().st_size>8192:raise ValueError('本机数据身份文件无效。')
    value=json.loads(path.read_text())
    if (set(value)!={'schema','deployment_id','account_id','storage_namespace','storage_service_url'}
            or value['schema']!=SCHEMA or not isinstance(value['account_id'],str) or not value['account_id']
            or not isinstance(value['storage_service_url'],str) or not value['storage_service_url']
            or not re.fullmatch('[a-f0-9]{64}',value['storage_namespace'])):
        raise ValueError('本机数据身份记录无效。')
    issuer(value['deployment_id'])
    return value


def _publish(path,record):
    """Publish a complete immutable record; concurrent losers read the winner."""
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex)
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(descriptor,'w') as handle:
            json.dump(record,handle,ensure_ascii=False,sort_keys=True)
            handle.flush();os.fsync(handle.fileno())
        try:os.link(temporary,path)
        except FileExistsError:pass
    finally:temporary.unlink(missing_ok=True)
    if _read(path)!=record:raise PermissionError('本机数据已绑定其他服务或账户。')


def _paths(base,scope):
    deployment,account=_identity(scope)
    key=hashlib.sha256((deployment+'\n'+account).encode()).hexdigest()
    directory=_directory(base)
    return directory,directory/(key+'.deployment.json'),deployment,account


def _claim(base,scope,namespace,storage_service):
    directory,index,deployment,account=_paths(base,scope)
    record={'schema':SCHEMA,'deployment_id':deployment,'account_id':account,
            'storage_namespace':namespace,'storage_service_url':storage_service}
    # Owner first: two projects cannot claim one old directory concurrently.
    _publish(directory/(namespace+'.owner.json'),record)
    _publish(index,record)
    return record


def resolve(base,scope):
    directory,index,deployment,account=_paths(base,scope)
    current=_read(index)
    if current:
        owner=_read(directory/(current['storage_namespace']+'.owner.json'))
        if (current['deployment_id'],current['account_id'])!=(deployment,account) or owner!=current:
            raise PermissionError('本机数据服务身份不匹配。')
        return current
    recovered=[]
    for path in directory.glob('*.owner.json'):
        candidate=_read(path)
        if candidate and (candidate['deployment_id'],candidate['account_id'])==(deployment,account):
            recovered.append(candidate)
    if len(recovered)>1:raise ValueError('本机数据存在多个身份目录，请先核对。')
    if recovered:
        _publish(index,recovered[0]);return recovered[0]
    namespace=hashlib.sha256(('device-deployment/v1\n'+deployment+'\n'+account).encode()).hexdigest()
    return _claim(base,scope,namespace,deployment)


def matches_backup(manifest,scope):
    return (manifest.get('schema')=='runteams.device-backup/v2'
        and (manifest.get('account_id'),manifest.get('deployment_id'),manifest.get('storage_namespace'))
            ==(scope['account_id'],scope['deployment_id'],scope['storage_namespace']))


def restore_binding(base,scope,manifest):
    """Explicit backup restore may reestablish its identity on a fresh device."""
    directory,index,deployment,account=_paths(base,scope)
    if (manifest.get('deployment_id'),manifest.get('account_id'))!=(deployment,account):
        raise PermissionError('这份备份属于另一个账户或服务。')
    expected={'schema':SCHEMA,'deployment_id':deployment,'account_id':account,
              'storage_namespace':manifest['storage_namespace'],'storage_service_url':manifest['storage_service_url']}
    current=_read(index)
    if current and current!=expected:
        raise ValueError('当前设备已有另一份本机身份，请先另行备份，不能覆盖。')
    destination=Path(base)/manifest['storage_namespace']
    if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
        raise ValueError('当前设备已有本机数据，请先另行备份，不能覆盖。')
    return _claim(base,scope,manifest['storage_namespace'],manifest['storage_service_url'])
