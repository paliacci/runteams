"""Shared durable backup files, SQLite snapshots and bounded ZIP transport."""
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3
import zipfile

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_FILES = 20000


def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def write_json(path, value):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as handle:
        json.dump(value,handle,ensure_ascii=False,sort_keys=True)
        handle.flush();os.fsync(handle.fileno())


def replace_json(path, value):
    import uuid
    temporary=path.with_name('.pending-'+uuid.uuid4().hex)
    try:
        write_json(temporary,value);os.replace(temporary,path);sync_directory(path.parent)
    finally:temporary.unlink(missing_ok=True)


def safe_name(name):
    if (not isinstance(name,str) or not name or '\\' in name or '\0' in name or name.startswith('/')
            or PureWindowsPath(name).drive or any(p in ('','.','..') for p in name.split('/'))):
        raise ValueError('备份文件路径无效。')
    return name


def file_digest(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        while block:=source.read(1024*1024):digest.update(block)
    return digest.hexdigest()


def files(directory):
    directory=Path(directory)
    if not directory.is_dir() or directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')):
        raise ValueError('备份不能包含符号链接。')
    return {p.relative_to(directory).as_posix():file_digest(p)
            for p in directory.rglob('*') if p.is_file()}


def verify_files(directory, expected, *, required='personal.sqlite3'):
    if not isinstance(expected,dict) or required not in expected:
        raise ValueError('备份文件不完整。')
    for name,value in expected.items():
        safe_name(name)
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('备份校验值无效。')
    actual=files(directory);actual.pop('manifest.json',None)
    if actual!=expected:raise ValueError('备份文件不完整或校验失败。')


def snapshot_database(source, destination):
    if source.is_symlink() or not source.is_file():raise ValueError('本机数据库路径无效。')
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as original, sqlite3.connect(destination) as target:
        original.backup(target);target.execute('PRAGMA journal_mode=DELETE')
    destination.chmod(0o600)


def readonly_database(path):
    if path.is_symlink() or not path.is_file():raise ValueError('备份数据库不可用。')
    connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('备份数据库损坏。')
    except BaseException:connection.close();raise
    return connection


def copy_tree(source, destination, check):
    before=files(source)
    directories=sorted(p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_dir())
    for name in directories:(destination/safe_name(name)).mkdir(mode=0o700,parents=True,exist_ok=True)
    for name in before:
        target=destination/safe_name(name);target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        shutil.copyfile(source/name,target);target.chmod(0o600)
    check()
    if (before!=files(source) or before!=files(destination)
            or directories!=sorted(p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_dir())):
        raise ValueError('本机文件正在变化，请稍后重新备份。')


def pack(source, destination):
    names=files(source)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob('*'):
            if path.is_dir():archive.write(path,safe_name(path.relative_to(source).as_posix())+'/')
        for name in names:archive.write(source/name,safe_name(name))
    destination.chmod(0o600)
    if destination.stat().st_size>MAX_ARCHIVE:raise ValueError('备份超过512MB，请先减少本机资料。')
    with destination.open('rb') as stream:os.fsync(stream.fileno())


def unpack(source, destination):
    if source.is_symlink() or source.stat().st_size>MAX_ARCHIVE:raise ValueError('备份文件过大或不可用。')
    destination.mkdir(mode=0o700)
    with zipfile.ZipFile(source) as archive:
        entries=archive.infolist();names=set();size=0
        if len(entries)>MAX_FILES:raise ValueError('备份文件数量过多。')
        for entry in entries:
            is_directory=entry.is_dir();name=safe_name(entry.filename[:-1] if is_directory else entry.filename)
            mode=entry.external_attr>>16
            allowed_modes=(0,0o040000) if is_directory else (0,0o100000)
            if name in names or mode&0o170000 not in allowed_modes or entry.flag_bits&1 or entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
                raise ValueError('备份包含不支持或重复的文件。')
            size+=entry.file_size;names.add(name)
            if size>MAX_EXPANDED:raise ValueError('备份展开后超过2GB。')
            path=destination/name
            if is_directory:
                if entry.file_size:raise ValueError('备份目录内容无效。')
                path.mkdir(mode=0o700,parents=True,exist_ok=True);continue
            path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with archive.open(entry) as original,path.open('xb') as target:
                count=0
                while block:=original.read(1024*1024):
                    count+=len(block)
                    if count>entry.file_size:raise ValueError('备份文件长度无效。')
                    target.write(block)
                target.flush();os.fsync(target.fileno())
            path.chmod(0o600)
        if 'manifest.json' not in names:raise ValueError('不是可用的RunTeams备份。')
    for path in destination.rglob('*'):
        if path.is_dir():path.chmod(0o700)
