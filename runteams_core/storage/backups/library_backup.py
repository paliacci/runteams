"""Verified snapshots of the connected local-library stores, without cloud identity."""
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import shutil
from pathlib import Path
import uuid

from runteams_core.storage.backups import backup_files as disk
from runteams_core.foundation.local_json import strict_json
from runteams_core.storage.local_library import scope_for

SCHEMA='runteams.library-backup/1'
DATABASES=('personal.sqlite3','library-assets.sqlite3','interaction-settings.sqlite3')
SCHEDULES=('employee-schedules','pipeline-schedules')
TREES=('attachments','conversation-folders','workspaces','employee-workspaces','pipeline-workspaces')
IGNORED={'employee-mcp-packages','conversation-runtime.sqlite3','conversation-runtime.sqlite3-wal','conversation-runtime.sqlite3-shm'}
PORTABLE_WORKSPACE='library://workspaces/assistant'


def load(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>64*1024*1024:raise ValueError('备份记录路径或大小无效。')
    return strict_json(path.read_bytes())


def verify_work(directory, scope):
    from runteams_core.work import device_work as work
    from runteams_core.storage.repository import Repository
    from runteams_core.documents import rich_documents as rich, rich_document_assets as assets
    path=directory/'work'/work.DATABASE
    if not path.exists():return
    with closing(disk.readonly_database(path)) as connection:
        if connection.execute('PRAGMA user_version').fetchone()[0]!=work.VERSION:raise ValueError('本机文档版本不受支持。')
        work.verify_structure(connection)
        row=connection.execute('SELECT binding_json,data_epoch FROM device_work_scope WHERE singleton=1').fetchone()
        if not row or json.loads(row[0])!={k:scope[k] for k in ('storage_kind','library_id','storage_namespace')} or str(uuid.UUID(row[1]))!=row[1]:
            raise ValueError('文档与资料库身份不一致。')
        # Only canonical own-source work is admitted. Original pipeline and
        # report links are verified below; a fabricated acquired grant is rejected.
        if connection.execute('SELECT 1 FROM employee_releases LIMIT 1').fetchone():raise ValueError('本机资料不包含官方资产。')
        for raw,reference,pipeline in connection.execute('SELECT wr.snapshot_json,t.employee_reference,t.pipeline_id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id'):
            from runteams_core.employees.employee_work_contracts import verify_frozen
            value=verify_frozen(json.loads(raw),scope)
            if pipeline is not None or json.loads(reference or '{}')!=value['employee_reference']:
                raise ValueError('免费员工工作归属无效。')
        if connection.execute('SELECT 1 FROM tasks t LEFT JOIN workflow_runs wr ON wr.task_id=t.id WHERE wr.id IS NULL LIMIT 1').fetchone():raise ValueError('工作缺少原执行记录。')
        connection.row_factory=sqlite3.Row
        rows=connection.execute('SELECT * FROM artifacts ORDER BY id').fetchall();chains={}
        for row in rows:
            meta=json.loads(row['meta_json']);ref=row['ref']
            if meta.get('content_model')!=rich.MODEL or meta.get('source')!='agent_chat' or meta.get('data_view'):
                raise ValueError('文档归属或格式无效。')
            if not isinstance(ref,str) or not ref.startswith(work.FILE_PREFIX+'artifacts/agent-documents/'):raise ValueError('文档文件引用无效。')
            body_path=directory/'work'/disk.safe_name(ref[len(work.FILE_PREFIX):])
            if body_path.stat().st_size>2*1024*1024:raise ValueError('文档内容超过存储上限。')
            body=body_path.read_bytes()
            value=rich.validate(body.decode())
            if hashlib.sha256(body).hexdigest()!=meta.get('sha256') or len(body)!=meta.get('size'):raise ValueError('文档正文与修订不一致。')
            root=meta.get('revision_of');chains.setdefault(root,[]).append((row['id'],meta.get('revision')))
            def visit(blocks):
                for block in blocks:
                    identifier=block.get('props',{}).get('assetId') if block['type'] in {'image','video','file'} else None
                    if identifier:
                        if not isinstance(identifier,str) or not assets.IDENTIFIER.fullmatch(identifier):raise ValueError('文档附件引用无效。')
                        saved=load(directory/'work/artifacts/rich-assets'/(identifier+'.json'))
                        if hashlib.sha256(assets._encoded(saved)).hexdigest()!=identifier or saved.get('document_root')!=root:raise ValueError('文档附件归属无效。')
                        assets._file({k:saved[k] for k in ('name','type','data')})
                    visit(block.get('children',[]))
            visit(value['blocks'])
        for root,chain in chains.items():
            if chain[0][0]!=root or [r[1] for r in chain]!=list(range(1,len(chain)+1)):raise ValueError('文档版本链不完整。')
        previous=None
        for event in connection.execute('SELECT * FROM events ORDER BY id'):
            calculated=Repository._event_hash(**{k:event[k] for k in ('stream','data_json','created_at','actor_id','correlation_id','source','schema_version')},event_id=event['id'],event_type=event['type'],prev_hash=previous)
            if event['prev_hash']!=previous or event['event_hash']!=calculated:raise ValueError('文档执行回执校验失败。')
            previous=event['event_hash']
    work.verify(directory,scope)
    template_root=directory/'work/artifacts/rich-templates'
    if (template_root/'index.json').exists():
        index=load(template_root/'index.json');seen=set()
        if not isinstance(index,list) or len(index)>100:raise ValueError('文档模板索引无效。')
        for item in index:
            identifier=item['id'];name=item['name']
            if identifier in seen or not assets.IDENTIFIER.fullmatch(identifier):raise ValueError('文档模板索引无效。')
            seen.add(identifier);fragment=load(template_root/(identifier+'.json'))
            if hashlib.sha256(assets._encoded(fragment)+name.encode()).hexdigest()!=identifier or fragment.get('schema')!='runteams.block-fragment/1':raise ValueError('文档模板不完整。')
            rich.validate({'schema':rich.SCHEMA,'blocks':fragment.get('blocks'),'sources':fragment.get('sources')})
            for file in fragment.get('assets',{}).values():assets._file(file)


def folders(directory, *, source_root=None, final_root=None):
    """Preserve the kind and conversation owner of each managed directory."""
    if source_root is not None and final_root is not None:raise ValueError('工作目录转换范围无效。')
    path=directory/'conversation-folders/folders.json'
    if not path.exists():return
    value=load(path)
    if not isinstance(value,dict) or set(value)!={'defaults','chats'} or any(not isinstance(v,dict) for v in value.values()):raise ValueError('工作目录记录无效。')
    identities=None
    for group_name,group in value.items():
        for key,item in group.items():
            if not isinstance(item,dict) or type(item.get('custom')) is not bool or not isinstance(item.get('path'),str) or '\0' in item['path']:raise ValueError('工作目录记录无效。')
            if item['custom']:
                if not Path(item['path']).is_absolute():raise ValueError('外部工作目录引用无效。')
                continue
            employee='library://employee-workspaces/'+key
            if source_root is not None:
                selected=Path(item['path']);root=Path(source_root)
                if selected==root/'workspaces/assistant':portable=PORTABLE_WORKSPACE
                elif group_name=='chats' and selected==root/'employee-workspaces'/key:portable=employee
                else:raise ValueError('托管工作目录不属于当前资料库，未自动改选目录。')
            else:portable=item['path']
            if portable==PORTABLE_WORKSPACE:relative=Path('workspaces/assistant')
            elif group_name=='chats' and portable==employee:
                try:
                    if str(uuid.UUID(key))!=key:raise ValueError()
                except (ValueError,TypeError,AttributeError):raise ValueError('员工工作目录身份无效。') from None
                if identities is None:
                    with closing(disk.readonly_database(directory/'personal.sqlite3')) as c:
                        identities={row[0] for row in c.execute('SELECT identity FROM device_chat_index')}
                if key not in identities:raise ValueError('员工工作目录不属于备份对话。')
                relative=Path('employee-workspaces')/key
            else:raise ValueError('托管工作目录引用无效。')
            item['path']=str(Path(final_root)/relative) if final_root is not None else portable
    if source_root is not None or final_root is not None:disk.replace_json(path,value)


def verify_payload(directory, manifest, *, portable=True):
    from runteams_core.storage.backups.device_runtime_backup import verify as runtime_verify
    scope=scope_for(manifest['library_id'])
    if manifest['storage_namespace']!=scope['storage_namespace']:raise ValueError('备份资料库身份无效。')
    from runteams_core.storage.library_stores import verify as verify_stores
    verify_stores(directory,manifest['library_id'])
    for name in ('personal.sqlite3',):
        with closing(disk.readonly_database(directory/name)) as connection:
            if name=='personal.sqlite3':
                runtime_verify(connection)
                from runteams_core.work.work_ui_state import verify as verify_ui_state
                verify_ui_state(connection,scope)
                if connection.execute('SELECT 1 FROM chat_messages WHERE length(CAST(attachments AS BLOB))>4194304 LIMIT 1').fetchone():raise ValueError('对话附件记录过大。')
                for chat_id,raw in connection.execute('SELECT chat_id,attachments FROM chat_messages'):
                    values=strict_json(raw.encode())
                    if not isinstance(values,list):raise ValueError('对话附件记录无效。')
                    for item in values:
                        for entry in [item,*item.get('normalized',[])]:
                            path=directory/'attachments'/str(chat_id)/disk.safe_name(entry.get('stored_name'))
                            if not path.exists() or path.is_symlink():raise ValueError('对话附件或派生资料缺失。')

    if portable:folders(directory)
    from runteams_core.storage.backups.local_creator_backup import verify as verify_sources
    verify_sources(directory,scope)
    verify_work(directory,scope)
    path=directory/'work/runteams.db'
    if path.exists():
        from runteams_core.work.work_connection_calls import verify as verify_connection_calls
        with closing(disk.readonly_database(path)) as connection:verify_connection_calls(connection,scope,directory)
    from runteams_core.automation.device_employee_schedules import verify as verify_schedules
    from runteams_core.automation.source_pipeline_schedules import verify as verify_pipeline_schedules
    verify_schedules(directory,scope);verify_pipeline_schedules(directory,scope)
    return manifest


def verify(directory):
    directory=Path(directory);manifest=load(directory/'manifest.json')
    if not isinstance(manifest,dict) or set(manifest)!={'schema','library_id','storage_namespace','created_at','files','directories'} or manifest['schema']!=SCHEMA:
        raise ValueError('不是当前版本的本机资料库备份。')
    datetime.fromisoformat(manifest['created_at']);scope_for(manifest['library_id'])
    disk.verify_files(directory,manifest['files'])
    directories=manifest['directories']
    actual=sorted(p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_dir())
    if not isinstance(directories,list) or directories!=actual:raise ValueError('备份目录不完整。')
    for name in directories:disk.safe_name(name)
    allowed=set(DATABASES)|{'manifest.json'}
    if any(name.split('/')[0] not in allowed|set(TREES)|set(SCHEDULES)|{'work','creator-sources'} for name in [*manifest['files'],*directories]):raise ValueError('备份包含不支持的资料。')
    return verify_payload(directory,manifest)


def snapshot(app, destination):
    from runteams_core.storage import device_data
    app.runtime
    app.settings.read();app.assets.list(limit=1)
    with app.runtime.scope(), ExitStack() as stack:
        stack.enter_context(device_data.connect())
        stack.enter_context(app.assets._connect(write=True))
        stack.enter_context(app.settings.connect())
        return _snapshot_payload(app.binding,Path(destination),app.check)


def _snapshot_payload(binding,destination,check):
    from runteams_core.storage.storage_context import StorageBinding
    from runteams_core.assets.library_assets import LocalAssets
    from runteams_core.configuration.library_settings import LibrarySettings
    from runteams_core.conversations import conversation_folders
    from runteams_core.work import device_work
    check()
    source=binding.root;scope=binding.scope
    allowed=set(DATABASES)|set(TREES)|set(SCHEDULES)|{'work','creator-sources'}|IGNORED|{n+s for n in DATABASES for s in ('-wal','-shm')}
    if any(p.name not in allowed for p in source.iterdir()):raise ValueError('免费版含有尚未接通的资料，未省略任何内容。')
    destination.mkdir(mode=0o700)
    if not (source/'personal.sqlite3').is_file():raise ValueError('免费版尚无已保存资料。')
    for name in DATABASES:
        if (source/name).exists():disk.snapshot_database(source/name,destination/name)
    copied=StorageBinding(destination,binding.library_id,scope)
    LocalAssets(destination,binding.library_id,check).list(limit=1)
    LibrarySettings(copied,check).read()
    for name in TREES:
        if not (source/name).exists():continue
        if name=='conversation-folders':
            conversation_folders.snapshot(source,destination,scope,check)
        else:
            (destination/name).mkdir(mode=0o700);disk.copy_tree(source/name,destination/name,check)
    from runteams_core.authoring.source.creator_local_source import snapshot as source_snapshot
    from runteams_core.authoring.compilation.creator_build_backup import snapshot as build_snapshot
    from runteams_core.automation.device_employee_schedules import snapshot as schedule_snapshot
    from runteams_core.automation.source_pipeline_schedules import snapshot as pipeline_schedule_snapshot
    schedule_snapshot(source,destination,scope,check);pipeline_schedule_snapshot(source,destination,scope,check)
    source_snapshot(source,destination,scope,check)
    build_snapshot(source,destination,scope,check)
    work=source/'work'
    if work.exists():
        target=destination/'work';target.mkdir(mode=0o700)
        disk.snapshot_database(work/device_work.DATABASE,target/device_work.DATABASE)
        excluded={device_work.DATABASE,device_work.DATABASE+'-wal',device_work.DATABASE+'-shm','.writer.lock'}
        before={n:v for n,v in disk.files(work).items() if n.split('/')[0] not in excluded}
        for name in before:
            path=target/disk.safe_name(name);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);shutil.copyfile(work/name,path);path.chmod(0o600)
        if before!={n:v for n,v in disk.files(work).items() if n.split('/')[0] not in excluded} or any(disk.file_digest(target/n)!=v for n,v in before.items()):raise ValueError('免费版文档文件正在变化，请稍后重试。')
    check()
    manifest={'schema':SCHEMA,'library_id':binding.library_id,'storage_namespace':scope['storage_namespace'],'created_at':datetime.now(timezone.utc).isoformat(),'files':disk.files(destination),'directories':sorted(p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_dir())}
    disk.write_json(destination/'manifest.json',manifest);verify(destination)
    return manifest


def offline_snapshot(profile,destination):
    """Same snapshot engine, held by the closed free host's exclusive lease."""
    from runteams_core.application.local_host_lock import acquire
    from runteams_core.storage.local_library import LocalLibrary, _read
    from runteams_core.storage.storage_context import StorageBinding
    profile=Path(profile);destination=Path(destination)
    if profile.is_symlink():raise ValueError('免费版资料目录无效。')
    lease=acquire(profile)
    try:
        provider=LocalLibrary();base=profile/'device-data'
        library_id=_read(base/'.local-library.json');scope=scope_for(library_id)
        source=base/'libraries'/scope['storage_namespace']
        if not source.is_dir() or source.is_symlink():raise ValueError('免费版资料目录无效。')
        binding=StorageBinding(source,library_id,scope)
        return _snapshot_payload(binding,destination,lambda:provider.check(base,binding))
    finally:lease.rollback();lease.close()
