"""Build runnable JS MCPB and complete skill releases, without executing authors."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from .creator_contracts import ROOT, CreatorContractError, compile_source, canonical, contract, digest
from .creator_definitions import compiler_identity, definition_artifacts, definition_target
from .creator_mcp_source import packages, execution, PROJECT


def identity():
    root=Path(__file__).parent
    return digest({'schema':'runteams.mcp-source-builder/1','compiler':compiler_identity(),
        'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
                 ('creator_mcp_build.py','creator_mcp_source.py','employee_mcp_package.py','creator_conversation_assets.py','creator_source_import.py','creator_local_build_worker.py')},
        'contracts':{name:hashlib.sha256((ROOT/'mcp-v1'/name).read_bytes()).hexdigest() for name in ('project.schema.json','release.schema.json','dependencies.schema.json')}})


class MCPSourceBuilder:
    def __init__(self, runtime=None, *, esbuild=None, esbuild_sha256=None, cancelled=lambda:False):
        self.runtime,self.cancelled=runtime,cancelled
        self.esbuild,self.esbuild_sha256=esbuild,esbuild_sha256

    def parser(self):
        if self.esbuild is None:
            from .creator_build_tools import directory
            from .creator_contracts import strict_json
            config=strict_json((directory()/'toolchain.json').read_bytes())
            self.esbuild=directory()/'esbuild';self.esbuild_sha256=config['esbuild']['sha256']
        path=Path(self.esbuild).absolute()
        if any(p.is_symlink() for p in (path,*path.parents)) or hashlib.sha256(path.read_bytes()).hexdigest()!=self.esbuild_sha256:
            raise CreatorContractError('builder_integrity')
        return path

    def build(self,files, *, require_work=False):
        compiled=compile_source(files)
        if compiled['project']['schema']!=PROJECT:raise CreatorContractError('mcp_project_required')
        from .creator_dependencies import validate_dependency_sources
        validate_dependency_sources(files,compiled)
        values=packages(files,compiled)
        if values:
            if self.runtime is None:
                from .employee_mcp import platform_runtime
                self.runtime=platform_runtime()
            node,_=self.runtime.verify()
            from .creator_contracts import strict_json
            if not strict_json((self.runtime.root/'runtime.json').read_bytes())['node_version'].startswith('v24.'):
                raise CreatorContractError('mcp_node24_required')
            parser=self.parser()
            builtins=set(strict_json(subprocess.check_output([str(node),'-e',
                'process.stdout.write(JSON.stringify(require("node:module").builtinModules))'],
                env={'PATH':os.defpath},timeout=8)))
            with tempfile.TemporaryDirectory(prefix='runteams-mcp-parse-') as folder:
                root=Path(folder).resolve()
                for directory,raw in values.items():
                    from .employee_mcp_package import MCPBundle
                    package=MCPBundle.inspect(raw);materialized=package.materialize(root/'packages')
                    for name in package.files:
                        if not name.endswith(('.js','.cjs','.mjs')):continue
                        if self.cancelled():raise CreatorContractError('build_cancelled')
                        # --check parses only: it cannot run imports, entry code,
                        # npm hooks, or the user's NODE_OPTIONS/preload scripts.
                        try:result=subprocess.run([str(node),'--check',str(materialized/name)],cwd=root,
                            env={'PATH':os.defpath,'HOME':str(root),'TMPDIR':str(root)},capture_output=True,timeout=8)
                        except subprocess.TimeoutExpired:raise CreatorContractError('mcp_parse_budget') from None
                        if result.returncode:raise CreatorContractError('mcp_javascript_syntax',name)
                        try:
                            checked=subprocess.run([str(parser),str(materialized/name),'--bundle','--platform=node','--format=cjs',
                                '--outfile='+str(root/'checked.cjs'),'--metafile='+str(root/'imports.json'),'--log-level=error','--log-limit=3'],cwd=materialized,
                                env={'PATH':os.defpath,'HOME':str(root),'TMPDIR':str(root)},capture_output=True,timeout=8)
                        except subprocess.TimeoutExpired:raise CreatorContractError('mcp_parse_budget') from None
                        if checked.returncode:raise CreatorContractError('mcp_dependency_missing',name)
                        meta=strict_json((root/'imports.json').read_bytes())
                        for imported in meta['inputs']:
                            resolved=(materialized/imported).resolve()
                            if not resolved.is_relative_to(materialized) or resolved.relative_to(materialized).as_posix() not in package.files:
                                raise CreatorContractError('mcp_dependency_escape')
                        for output in meta['outputs'].values():
                            if any(i.get('external') and i['path'].removeprefix('node:') not in builtins for i in output['imports']):
                                raise CreatorContractError('mcp_dependency_missing',name)
        if require_work:
            artifacts=definition_artifacts(files,compiled,require=True)
        else:
            from .creator_conversation_assets import artifacts as conversation_artifacts
            artifacts=conversation_artifacts(files,compiled)
        mode=execution(files,compiled)
        by_source=values
        for row in mode['packages']:artifacts[row['artifact']]=by_source[row['source']]
        if len(artifacts)>500 or sum(map(len,artifacts.values()))>32*1024*1024:raise CreatorContractError('artifact_limit')
        sha=lambda b:hashlib.sha256(b).hexdigest()
        project=compiled['project']
        definition_kind=(definition_target(compiled) if require_work else
                         'pipeline-conversation/v1' if compiled['pipelines'] else 'employee-conversation/v1')
        manifest={'schema':'runteams.release/2','project_key':project['key'],'version':project['version'],
            'source_sha256':compiled['source']['sha256'],'lock_sha256':sha(files[project['dependency_lock']]),
            'artifacts':[{'path':p,'size':len(b),'sha256':sha(b),'target':definition_kind if p.startswith('definitions/') else 'mcpb/0.3-node'} for p,b in sorted(artifacts.items())],
            'builder_sha256':identity(),'dependency_blobs':[{k:d[k] for k in ('key','version','sha256')} for d in compiled['dependencies']['dependencies']],
            'execution':mode}
        if values:manifest['build_resources']={'node_manifest_sha256':self.runtime.manifest_sha256,'parser_sha256':self.esbuild_sha256}
        contract('release.schema.json',manifest)
        return {'manifest':manifest,'artifacts':artifacts,'compiled':compiled,'operations':{}}
