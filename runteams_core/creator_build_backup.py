"""Device backup closure for source trials; no work content enters asset export."""
import fcntl
import os
from pathlib import Path

from .creator_contracts import canonical,digest,strict_json,tree
from .creator_local_build import LocalBuilds
from .source_artifacts import KEY
from .creator_local_source import HASH,LocalSources,_read
from .creator_source_archive import inspect


def write(path,raw):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())


def pointers(root):
    values={}
    for name in ('latest.json','valid.json'):
        try:values[name]=_read(root/name,1024)
        except FileNotFoundError:pass
    return values


def snapshot(source,destination,_scope,check):
    source=Path(source);destination=Path(destination)
    sources=source/'creator-sources'
    if sources.exists():
        store=LocalSources(sources,check)
        for path in sorted(sources.iterdir()):
            if not HASH.fullmatch(path.name):continue
            builds_root=path/'builds'
            if not builds_root.exists():continue
            if builds_root.is_symlink():raise ValueError('构建备份路径无效。')
            target=destination/'creator-sources'/path.name/'builds'
            if not target.parent.exists():raise ValueError('备份期间源码已变化，请重新备份。')
            builds=LocalBuilds(store,path.name);before=pointers(builds_root)
            for job in sorted(builds_root.iterdir()):
                if not KEY.fullmatch(job.name):continue
                if job.is_symlink():raise ValueError('构建备份路径无效。')
                raw=_read(job/'status.json',128*1024);status=strict_json(raw)
                if status['operation_key']!=job.name:raise ValueError('构建备份记录无效。')
                captured=dict(status)
                if status['state']=='running':
                    # A backup cannot resume an OS compiler process. Preserve
                    # its fixed input and report interruption after restore.
                    captured.update(state='interrupted',code='build_interrupted',diagnostic='')
                if status['state']=='succeeded':
                    metadata,artifacts=builds.artifacts(job.name)
                    write(target/job.name/'result/build.json',canonical(metadata))
                    for name,body in artifacts.items():write(target/job.name/'result'/name,body)
                write(target/job.name/'source.zip',_read(job/'source.zip',33*1024*1024))
                write(target/job.name/'status.json',canonical(captured))
                if raw!=_read(job/'status.json',128*1024):raise ValueError('备份期间构建已变化，请重新备份。')
                check()
            if before!=pointers(builds_root):raise ValueError('备份期间构建已变化，请重新备份。')
            for name,body in before.items():write(target/name,body)
    verify(destination,None)


def verify(directory,_manifest):
    directory=Path(directory);sources=directory/'creator-sources';index={}
    if sources.exists():
        store=LocalSources(sources)
        for path in sources.iterdir():
            if not HASH.fullmatch(path.name):continue
            root=path/'builds'
            if not root.exists():continue
            builds=LocalBuilds(store,path.name)
            for job in root.iterdir():
                if not KEY.fullmatch(job.name):continue
                state=strict_json(_read(job/'status.json',128*1024))
                if state.get('schema')!='runteams.local-build-state/1' or state.get('builder_profile')!='mcp' or state.get('operation_key')!=job.name or state.get('state') not in ('succeeded','failed','cancelled','interrupted'):
                    raise ValueError('备份构建状态无效。')
                files=inspect(_read(job/'source.zip',33*1024*1024))
                if tree(files)['sha256']!=state['source_sha256'] or builds.revisions._files(state['revision'])!=files:
                    raise ValueError('备份构建与源码修订不一致。')
                if state['state']=='succeeded':
                    metadata,_=builds.artifacts(job.name)
                    index[(path.name,state['revision'],state['result_sha256'])]=metadata
            for name,raw in pointers(root).items():
                key=strict_json(raw)['operation_key']
                if not KEY.fullmatch(key) or not (root/key/'status.json').is_file():raise ValueError('备份构建入口不完整。')
                if name=='valid.json' and strict_json(_read(root/key/'status.json',128*1024))['state']!='succeeded':
                    raise ValueError('备份有效构建入口无效。')
    if (directory/'creator-trials').exists():
        raise ValueError('备份包含不受支持的旧试运行状态。')
