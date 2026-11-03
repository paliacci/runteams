"""Revision-bound local build jobs and immutable results; no cloud authority."""
import contextvars
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time

from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, contract, digest, relative, strict_json, tree
from runteams_core.foundation.content_hashes import sha256 as sha
from runteams_core.authoring.compilation.creator_build_tools import directory, load
from runteams_core.authoring.source.creator_local_source import _read, _sync
from runteams_core.authoring.source.creator_source_archive import pack
from runteams_core.authoring.source.creator_source_revisions import Revisions, SourceConflict
from runteams_core.authoring.workers.creator_worker_process import command
from runteams_core.authoring.source.source_artifacts import BuildArtifacts
from runteams_core.authoring.source import source_io

_slot = threading.BoundedSemaphore(1)


class LocalBuilds(BuildArtifacts):

    def lock(self):
        fd=os.open(self.root / '.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('构建记录无效，请保留源码后重新打开。')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return fd
        except BaseException:os.close(fd);raise


    def read(self, key):
        job=self.job(key)
        state=strict_json(_read(job / 'status.json',128*1024))
        if state.get('schema')!='runteams.local-build-state/1' or state.get('operation_key')!=key or state.get('builder_profile')!='mcp':raise ValueError('构建记录无效。')
        if state['state']=='running':
            try:fd=self.lock()
            except BlockingIOError:pass
            else:
                try:
                    state=strict_json(_read(job / 'status.json',128*1024))
                    if state['state']=='running':
                        state.update(state='interrupted',code='build_interrupted',diagnostic='')
                        source_io.atomic_json(job / 'status.json',state)
                finally:os.close(fd)
        state['current']=state['revision']==self.revisions.current()['revision']
        if not state['current']:state['stale_reason']='source_changed'
        if state['state']=='succeeded':
            self.artifacts(key)
            reason=self.toolchain_stale_reason(state)
            if reason:
                state['current']=False
                state['stale_reason']=reason
        return state

    @staticmethod
    def toolchain_stale_reason(state):
        # Retained results remain inspectable. They are runnable only with the
        # exact currently verified platform tools, including the pinned parser bytes.
        try:_,current=load(profile=state['builder_profile'])
        except CreatorContractError:return 'toolchain_unavailable'
        if state.get('mcp_runtime_sha256'):
            from runteams_core.employees.mcp.employee_mcp import platform_runtime, MCPError
            try:runtime=platform_runtime()
            except MCPError:return 'toolchain_unavailable'
            if runtime.manifest_sha256!=state['mcp_runtime_sha256']:return 'toolchain_changed'
        return '' if current==state.get('toolchain_sha256') else 'toolchain_changed'

    def status(self):
        try:latest=strict_json(_read(self.root / 'latest.json',1024))['operation_key']
        except FileNotFoundError:latest=None
        try:valid=strict_json(_read(self.root / 'valid.json',1024))['operation_key']
        except FileNotFoundError:valid=None
        value={'latest':self.read(latest) if latest else None,'valid':self.read(valid) if valid else None}
        if value['latest'] and value['latest']['state']=='succeeded' and (not value['valid'] or value['latest']['created_at']>value['valid']['created_at']):
            value['valid']=value['latest']
            # A crash after the durable success but before the convenience
            # pointer is repaired from the verified immutable result.
            try:fd=self.lock()
            except BlockingIOError:pass
            else:
                try:
                    if strict_json(_read(self.root / 'latest.json',1024))['operation_key']==latest:
                        source_io.atomic_json(self.root / 'valid.json',{'operation_key':latest})
                finally:os.close(fd)
        return value


    def release_candidate(self, revision, key):
        """Capture a saved source/build pair for a later explicit publication.

        This is local preparation, never a release, signature or cloud receipt.
        The publishing service must validate the source/rights and rebuild it.
        No traversal of the surrounding device/work directories is permitted.
        """
        with self.revisions.locked():
            if self.revisions._head() != revision:
                raise SourceConflict('源码已有更新，请核对当前保存的版本。')
            state = strict_json(_read(self.job(key) / 'status.json', 128*1024))
            if (state.get('operation_key') != key or state.get('state') != 'succeeded' or
                    state.get('revision') != revision):
                raise SourceConflict('请先构建当前保存的源码，再发布版本。')
            if self.toolchain_stale_reason(state):
                raise SourceConflict('构建工具已变化或暂不可用，请重新构建后再发布。')
            files = self.revisions._files(revision)
            source = tree(files)
            metadata, artifacts = self.artifacts(key)
            if (state.get('source_sha256') != source['sha256'] or
                    metadata['manifest']['source_sha256'] != source['sha256'] or
                    state.get('result_sha256') != digest(metadata) or
                    not re.fullmatch('[a-f0-9]{64}', str(state.get('toolchain_sha256', '')))):
                raise ValueError('源码与构建结果不匹配，请重新构建。')
            raw = pack(files)
            self.revisions.store.check_scope()
            candidate = {
                'schema': 'runteams.local-release-candidate/1-dev',
                'scope': 'local-publication-preparation',
                'source_id': self.revisions.identity, 'revision': revision,
                'source': source, 'archive_sha256': sha(raw),
                'build': {'operation_key': key, 'result_sha256': digest(metadata),
                    'toolchain_sha256': state['toolchain_sha256'],
                    'manifest': metadata['manifest']},
                'published': False, 'synchronized': False, 'cloud_verified': False,
            }
            return candidate, raw, artifacts

    def start(self, revision, key):
        return self._start(revision, key, current_head=True)

    def start_saved(self, revision, key):
        """Build an exact saved dependency without moving the author's head."""
        self.revisions.files_at(revision)
        return self._start(revision, key, current_head=False)

    def _start(self, revision, key, *, current_head):
        job=self.job(key)
        self.revisions.store.check_scope()
        if job.exists():
            previous=self.read(key)
            if previous['revision']!=revision:raise SourceConflict('原构建请求绑定另一份源码修订，请先核对原结果。')
            return previous
        self.status()
        fd=self.lock()
        transferred=False
        try:
            if job.exists():
                previous=self.read(key)
                if previous['revision']!=revision:raise SourceConflict('原构建请求绑定另一份源码修订，请先核对原结果。')
                return previous
            with self.revisions.locked():
                if current_head and self.revisions._head()!=revision:
                    raise SourceConflict('源码已更新，请构建当前保存的版本。')
                if revision != self.revisions.identity and revision not in [row['revision'] for row in self.revisions._history()]:
                    raise SourceConflict('所选员工修订不在原作品的保存记录中。')
                files=self.revisions._files(revision)
                raw=pack(files)
            from runteams_core.authoring.compilation.creator_mcp_source import mcp_project
            if not mcp_project(files):raise CreatorContractError('unsupported_source_contract')
            profile='mcp'
            tools=directory();_,toolchain=load(tools,profile=profile)
            if not _slot.acquire(blocking=False):raise CreatorContractError('builder_busy')
            stage=None
            try:
                stage=Path(tempfile.mkdtemp(prefix='.build-',dir=self.root))
                with (stage / 'source.zip').open('xb') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                state={'schema':'runteams.local-build-state/1','operation_key':key,'revision':revision,'source_sha256':tree(files)['sha256'],
                    'toolchain_sha256':toolchain,'builder_profile':profile,'state':'running','code':'','diagnostic':'',
                    'created_at':datetime.now(timezone.utc).isoformat()}
                source_io.atomic_json(stage / 'status.json',state);_sync(stage)
                os.rename(stage,job);_sync(self.root)
                source_io.atomic_json(self.root / 'latest.json',{'operation_key':key})
                context=contextvars.copy_context()
                thread=threading.Thread(target=lambda:context.run(self._run,job,state,tools,fd),daemon=True)
                thread.start();transferred=True
                return {**state,'current':True}
            except BaseException:_slot.release();raise
            finally:
                if stage is not None and stage.exists():shutil.rmtree(stage)
        finally:
            if not transferred:os.close(fd)

    def cancel(self, key):
        job=self.job(key)
        value=self.read(key)
        if value['state']=='running':source_io.atomic_json(job / 'cancel',{'requested':True})
        return self.read(key)

    def _run(self, job, state, tools, fd):
        child=None
        try:
            request={'schema':'runteams.local-build-request/1','job':str(job),'tools':str(tools),'toolchain_sha256':state['toolchain_sha256'],'parent_pid':os.getpid(),
                     'builder_profile':state['builder_profile']}
            if request['builder_profile']=='mcp':
                from runteams_core.employees.mcp.employee_mcp import platform_runtime, MCPError
                try:
                    runtime=platform_runtime();request['mcp_runtime']={'root':str(runtime.root),'manifest_sha256':runtime.manifest_sha256}
                except MCPError:pass  # pure skills need no Node; a program fails explicitly in the worker
            with tempfile.TemporaryFile() as output:
                child=subprocess.Popen(command('build'),stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,
                    env={'PATH':os.defpath,'LANG':'en_US.UTF-8'},start_new_session=True)
                child.stdin.write(canonical(request));child.stdin.close()
                deadline=time.monotonic()+190
                while child.poll() is None:
                    if time.monotonic()>deadline:
                        source_io.atomic_json(job / 'cancel',{'requested':True})
                        raise CreatorContractError('build_budget')
                    time.sleep(.05)
                output.seek(0);response=strict_json(output.read(128*1024))
                if child.returncode or response.get('state') not in ('succeeded','failed','cancelled'):
                    raise CreatorContractError('build_worker_failed')
            state.update(response)
            if (job / 'cancel').exists():state.update(state='cancelled',code='build_cancelled')
            if state['state']=='succeeded':
                os.rename(job / '.result-stage',job / 'result');_sync(job)
                metadata,_=self.artifacts(state['operation_key'])
                resources=metadata['manifest'].get('build_resources')
                if resources:state['mcp_runtime_sha256']=resources['node_manifest_sha256']
                state['result_sha256']=digest(metadata)
                # Recheck platform-owned tools after execution as well.
                if load(tools,profile=state['builder_profile'])[1]!=state['toolchain_sha256']:raise CreatorContractError('builder_integrity')
                source_io.atomic_json(job / 'status.json',state)
                source_io.atomic_json(self.root / 'valid.json',{'operation_key':state['operation_key']})
            else:source_io.atomic_json(job / 'status.json',state)
        except Exception as error:
            state.update(state='failed',code=getattr(error,'code','build_worker_failed'),diagnostic=getattr(error,'details','') or '')
            source_io.atomic_json(job / 'status.json',state)
        finally:
            if child is not None and child.poll() is None:
                # Worker observes cancellation and kills its active compiler.
                try:child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL);child.wait()
            os.close(fd);_slot.release()
