"""Shared bounded no-follow reads and atomic durable file publication."""
import os,stat,uuid
from runteams_core.authoring.creator_contracts import CreatorContractError, strict_json
MAX_RECORD=96*1024*1024

def _scope(value):
    # Verified deployment namespaces survive an authorized endpoint alias;
    # legacy namespaces remain bound to their exact original service URL.
    if value.get('storage_kind')=='local':return {k:value[k] for k in ('storage_kind','library_id')}
    keys = ('account_id', 'deployment_id', 'storage_namespace', 'storage_service_url') if value.get('deployment_id') else ('account_id', 'service_url')
    return {k: value[k] for k in keys if k in value}


def _raw(path, limit=MAX_RECORD):
    if path.is_symlink(): raise CreatorContractError('asset_path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise CreatorContractError('asset_path')
        raw = stream.read(limit + 1)
    if len(raw) > limit: raise CreatorContractError('asset_limit')
    return raw


def _read(path):
    return strict_json(_raw(path))


def _publish(root, directory, target, raw):
    temporary = root / ('.creator-asset-' + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)
        fd = os.open(directory, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)

