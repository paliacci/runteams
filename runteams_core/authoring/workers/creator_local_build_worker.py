"""Isolated platform builder; no application startup or account credentials."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from runteams_core.authoring.workers.creator_worker_process import apply_limits
apply_limits('build')

from runteams_core.authoring.compilation.creator_build_tools import load_worker
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, strict_json
from runteams_core.authoring.source.creator_source_archive import inspect_file_with_tree
from runteams_core.authoring.source.creator_source_import import validate_source
from runteams_core.foundation.durable_files import sync_directory


def main():
    request = strict_json(sys.stdin.buffer.read(16385))
    if (not isinstance(request,dict) or request.get('schema')!='runteams.local-build-request/1' or request.get('builder_profile')!='mcp'):
        raise CreatorContractError('invalid_build_request')
    job = Path(request['job'])
    cancelled = lambda: os.getppid() != request['parent_pid'] or (job / 'cancel').exists()
    try:
        builder, identity = load_worker(Path(request['tools']), cancelled=cancelled,profile=request['builder_profile'])
        if request.get('mcp_runtime') and request.get('builder_profile')=='mcp':
            from runteams_core.employees.mcp.employee_mcp import ManagedMCPRuntime
            value=request['mcp_runtime']
            if getattr(sys,'frozen',False) and Path(value['root'])!=Path(sys._MEIPASS)/'mcp-runtime':
                raise CreatorContractError('builder_integrity')
            builder.runtime=ManagedMCPRuntime(Path(value['root']),value['manifest_sha256']);builder.runtime.verify()
        if identity != request['toolchain_sha256']:
            raise CreatorContractError('builder_integrity')
        files, _ = inspect_file_with_tree(job / 'source.zip')
        validate_source(files)
        built = builder.build(files, require_work=False)
        if cancelled():raise CreatorContractError('build_cancelled')
        stage = job / '.result-stage';stage.mkdir(mode=0o700)
        for path, body in built['artifacts'].items():
            target = stage / path;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:
                stream.write(body);stream.flush();os.fsync(stream.fileno())
        metadata = canonical({'manifest':built['manifest'], 'operations':built['operations']})
        if len(metadata) > 1024 * 1024:
            raise CreatorContractError('artifact_limit')
        with (stage / 'build.json').open('xb') as stream:
            stream.write(metadata);stream.flush();os.fsync(stream.fileno())
        for folder in sorted((p for p in stage.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):sync_directory(folder)
        sync_directory(stage)
        result = {'state':'succeeded'}
    except CreatorContractError as error:
        result = {'state':'cancelled' if error.code=='build_cancelled' else 'failed',
            'code':error.code, 'diagnostic':(error.details or '')[:65536]}
    except Exception:
        result = {'state':'failed', 'code':'build_worker_failed', 'diagnostic':''}
    sys.stdout.buffer.write(canonical(result))


main()
