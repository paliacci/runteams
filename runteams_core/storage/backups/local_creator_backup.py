"""Validate genuine library-bound source chats and the original portable SDK ledger."""
from contextlib import closing
from pathlib import Path
from runteams_core.storage.backups import backup_files as disk
from runteams_core.authoring.source.creator_local_source import HASH, LocalSources
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.authoring.creator_contracts import read_folder, tree
from runteams_core.authoring.creator_local_authoring import valid_context, _pending
from runteams_core.authoring.compilation.creator_build_backup import verify as verify_builds
from runteams_core.foundation.local_json import strict_json


def verify(directory, scope):
    directory=Path(directory)
    root=directory/'creator-sources'
    store=LocalSources(root) if root.exists() else None
    if store:
        for entry in root.iterdir():
            if not HASH.fullmatch(entry.name) or entry.is_symlink():
                raise ValueError('备份本机源码身份无效。')
            if any(p.name not in {'draft.json','source.zip','head.json','revisions','authoring','builds','.edit-lock'} for p in entry.iterdir()):
                raise ValueError('备份包含未接通的源码资料。')
            revisions=Revisions(store,entry.name)
            if tree(store.files(entry.name))!=revisions.original['source']:
                raise ValueError('备份原始源码身份不匹配。')
            revisions._files(revisions._head());revisions._history()
            parent=entry/'authoring'
            if parent.exists():
                for work in parent.iterdir():
                    if not work.name.isdigit():raise ValueError('备份源码创作会话无效。')
                    pending=_pending(work);revisions._files(pending['base_revision']);read_folder(work/'source')
        verify_builds(directory,None)
    with closing(disk.readonly_database(directory/'personal.sqlite3')) as connection:
        for kind,raw in connection.execute('SELECT kind,context_json FROM chats'):
            context=strict_json(raw.encode())
            if context.get('creator_local_source_id'):
                if not store or kind!='employee_design' or not valid_context(context) or context['creator_local_scope']!=scope['cache_scope']:
                    raise ValueError('备份源码会话与资料库不匹配。')
                store.describe(context['creator_local_source_id'])
