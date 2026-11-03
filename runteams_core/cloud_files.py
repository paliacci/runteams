"""Portable immutable trees; only verified bytes are materialized on a host."""
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from .contracts import ContractError

TREE_PREFIX = 'supabase-tree://sha256/'
SKILL_PREFIX = 'supabase-skill://sha256/'


def safe_relative(value):
    if (not isinstance(value,str) or not value or '\\' in value or '\x00' in value
            or value.startswith('/') or any(x in ('','..','.') for x in value.split('/'))):
        raise ContractError('云端文件路径无效。')
    return value


def tree_bytes(directory, max_bytes=32*1024*1024):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ContractError('文件包不存在或路径无效。')
    files, size = {}, 0
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ContractError('文件包不能包含符号链接。')
        if not path.is_file():
            continue
        name = safe_relative(path.relative_to(directory).as_posix())
        body = path.read_bytes();size += len(body)
        if size > max_bytes or len(files) >= 500:
            raise ContractError('文件包超过大小或数量限制。')
        files[name] = base64.b64encode(body).decode('ascii')
    return json.dumps({'schema':'runteams.cloud-tree/v1','files':files},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def decode_tree(body):
    try:
        value = json.loads(body)
        if value.get('schema') != 'runteams.cloud-tree/v1' or not isinstance(value.get('files'),dict) or len(value['files']) > 500:
            raise ValueError()
        result, size = {}, 0
        for name, encoded in value['files'].items():
            safe_relative(name)
            data = base64.b64decode(encoded,validate=True)
            size += len(data)
            if size > 32*1024*1024:
                raise ValueError()
            result[name] = data
        return result
    except (ValueError, TypeError, KeyError) as exc:
        raise ContractError('云端文件包内容无效。') from exc


def materialize_tree(files, target):
    target = Path(target)
    if target.is_symlink():
        raise ContractError('缓存目录不能是符号链接。')
    if target.is_dir():
        actual = {p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file() and not p.is_symlink()}
        if actual == files and not any(p.is_symlink() for p in target.rglob('*')):
            return target
        raise ContractError('已有缓存内容校验失败，请清除该文件缓存后重新读取。')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cloud-tree-',dir=target.parent) as temporary:
        staged = Path(temporary)/'tree';staged.mkdir()
        for name,body in files.items():
            path=staged/safe_relative(name);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body);path.chmod(0o600)
        try:
            staged.rename(target)
        except FileExistsError:
            return materialize_tree(files,target)
    return target


def put_tree(cloud,directory):
    return cloud.put_bytes(tree_bytes(directory)).replace('supabase-file://', 'supabase-tree://',1)


def restore_tree(cloud,ref,target):
    if not re.fullmatch(re.escape(TREE_PREFIX)+'[a-f0-9]{64}',str(ref)):
        raise ContractError('云端文件包引用无效。')
    body=cloud.read_bytes(str(ref).replace('supabase-tree://','supabase-file://',1))
    return materialize_tree(decode_tree(body),target)
