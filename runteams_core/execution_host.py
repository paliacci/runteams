"""Device execution identity. Contains no saved business objects."""
import json
import os
from pathlib import Path
import secrets
import uuid


def identity(directory, *, create=True):
    path=Path(directory)/'.cloud-execution-host.json'
    if path.is_symlink():
        raise ValueError('主机执行身份路径无效')
    if not create and not path.exists():
        return None
    if create:
        path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        value={'host_id':str(uuid.uuid4()),'secret':secrets.token_urlsafe(48)}
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex)
        descriptor=os.open(str(temporary),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(descriptor,'w') as handle:
                json.dump(value,handle);handle.flush();os.fsync(handle.fileno())
            # Linking is atomic and never replaces an identity another process
            # created while this process prepared its own file.
            try:os.link(temporary,path)
            except FileExistsError:pass
        finally:
            temporary.unlink(missing_ok=True)
    value=json.loads(path.read_text())
    if str(uuid.UUID(value['host_id']))!=value['host_id'] or not isinstance(value['secret'],str) or len(value['secret'])<40:
        raise ValueError('主机执行身份无效')
    if create:
        os.chmod(path,0o600)
    return value
