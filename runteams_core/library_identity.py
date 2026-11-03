"""Durable library UUID and extra local stores, shared by official backup/restore."""
from pathlib import Path
import shutil
import uuid
from . import backup_files as disk
from .local_library import _read, SCHEMA

MARKER='.library.json'
ORIGIN='.library-origin.json'
STORES=('library-assets.sqlite3','interaction-settings.sqlite3')


def identity(root, initial):
    root=Path(root)
    if root.is_symlink():raise ValueError('资料库目录无效。')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=root/MARKER
    if not path.exists() and not path.is_symlink():
        if (root/ORIGIN).exists() or (root/ORIGIN).is_symlink():raise ValueError('接续资料库身份缺失，原文件已保留。')
        try:disk.write_json(path,{'schema':SCHEMA,'library_id':str(uuid.UUID(initial))});disk.sync_directory(root)
        except FileExistsError:pass
    return _read(path)


def snapshot(source,destination,scope,check):
    if not (source/MARKER).exists():return
    library_id=_read(source/MARKER)
    shutil.copyfile(source/MARKER,destination/MARKER)
    if (source/ORIGIN).exists():shutil.copyfile(source/ORIGIN,destination/ORIGIN)
    for name in STORES:
        if (source/name).exists():disk.snapshot_database(source/name,destination/name)
    if (source/'workspaces').exists():
        (destination/'workspaces').mkdir(mode=0o700)
        disk.copy_tree(source/'workspaces',destination/'workspaces',check)
    verify(destination)


def verify(directory):
    path=directory/MARKER
    if not path.exists():
        if any((directory/name).exists() for name in STORES+(ORIGIN,'workspaces')):raise ValueError('资料库身份缺失。')
        return
    library_id=_read(path)
    from .library_stores import verify as verify_stores
    verify_stores(directory,library_id,tuple(n for n in STORES if (directory/n).exists()))
    if (directory/ORIGIN).exists():
        from .library_backup import load
        value=load(directory/ORIGIN)
        if set(value)!={'schema','source_library_id','source_sha256'} or value['schema']!='runteams.library-origin/1' or value['source_library_id']!=library_id or len(value['source_sha256'])!=64:raise ValueError('资料库接续记录无效。')
