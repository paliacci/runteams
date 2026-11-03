"""Source-owned immutable artifact verification; no build process or toolchain launch."""
import re
from runteams_core.authoring.creator_contracts import contract, digest, relative, strict_json
from runteams_core.authoring.source.creator_local_source import _read
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.foundation.content_hashes import sha256 as sha

KEY=re.compile(r"[a-zA-Z0-9_-]{16,100}")


class BuildArtifacts:
    def __init__(self, store, source_id):
        self.revisions = Revisions(store, source_id)
        self.root = self.revisions.root / 'builds'
        if self.root.is_symlink():raise ValueError('构建目录无效，请保留源码后重新打开。')
        self.root.mkdir(mode=0o700, exist_ok=True)


    def job(self, key):
        if not isinstance(key,str) or not KEY.fullmatch(key):raise ValueError('构建操作无效。')
        path=self.root / key
        if path.is_symlink():raise ValueError('构建操作无效。')
        return path


    def artifacts(self, key):
        job=self.job(key);result=job / 'result'
        if result.is_symlink():raise ValueError('构建产物无效，请重新构建。')
        metadata=strict_json(_read(result / 'build.json',1024*1024))
        manifest=contract('release.schema.json',metadata['manifest'])
        state=strict_json(_read(job / 'status.json',128*1024))
        if state.get('result_sha256') and digest(metadata)!=state['result_sha256']:raise ValueError('构建产物校验失败，请重新构建。')
        if manifest['source_sha256']!=state['source_sha256']:raise ValueError('产物与保存的源码不匹配，请重新构建。')
        bodies={}
        for row in manifest['artifacts']:
            path=relative(row['path']);target=result / path
            if any(p.is_symlink() for p in (target,*target.parents)):raise ValueError('构建产物无效，请重新构建。')
            body=_read(target,32*1024*1024)
            if len(body)!=row['size'] or sha(body)!=row['sha256']:raise ValueError('构建产物校验失败，请重新构建。')
            bodies[path]=body
        if len(bodies)!=len(manifest['artifacts']) or sum(map(len,bodies.values()))>32*1024*1024:
            raise ValueError('构建产物校验失败，请重新构建。')
        return metadata,bodies


