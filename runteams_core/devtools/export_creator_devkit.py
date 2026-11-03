"""Export a self-contained macOS development workspace, without account data."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = source_root()
sys.path.insert(0, str(ROOT))
from runteams_core.authoring.creator_contracts import canonical
from runteams_core.authoring.creator_definitions import author_schema
from runteams_creator_dev.scaffold import inventory

from runteams_core.devtools.python_sources import developer_sources


def export_mcp(output,runtime_root,libraries,esbuild):
    from runteams_core.employees.mcp.employee_mcp import ManagedMCPRuntime
    from runteams_core.authoring.creator_contracts import strict_json
    from runteams_creator_dev.mcp_template import make,scenarios as mcp_cases
    from runteams_creator_dev.file_copy import copy_new
    output=Path(output).absolute();runtime_root=Path(runtime_root).absolute();libraries=Path(libraries).absolute()
    if output.exists() or output.is_symlink():raise ValueError('output_exists')
    runtime=ManagedMCPRuntime(runtime_root,(runtime_root/'runtime.sha256').read_text().strip());runtime.verify()
    if not (runtime_root/'NODE-LICENSE').is_file() or (runtime_root/'NODE-LICENSE').is_symlink():raise ValueError('mcp_node_license_required')
    provenance=strict_json((libraries/'provenance.json').read_bytes())
    if provenance['lock_sha256']!=hashlib.sha256((ROOT/'sdk/mcp-host/package-lock.json').read_bytes()).hexdigest():raise ValueError('mcp_library_lock_integrity')
    for name in ('creator-server.cjs','creator-app.js'):
        if provenance['files'].get(name)!=hashlib.sha256((libraries/name).read_bytes()).hexdigest():raise ValueError('mcp_library_integrity')
    output.mkdir(parents=True);kit=output/'_runteams';kit.mkdir()
    def copy(source,target):target.parent.mkdir(parents=True,exist_ok=True);copy_new(source,target)
    for name in ('LICENSE','docs/legal/LICENSING.md','docs/legal/THIRD_PARTY_DOCUMENTS.md','docs/legal/THIRD_PARTY_INVENTORY.json'):
        copy(ROOT/name,kit/name)
    copy(ROOT/'runteams_creator_dev/TEMPLATE_LICENSE.txt',output/'TEMPLATE_LICENSE.txt')
    for name in developer_sources(ROOT):copy(ROOT/name,kit/name)
    for path in (ROOT/'runteams_creator_dev').iterdir():
        if path.suffix in ('.md','.ts','.html','.css','.txt'):copy(path,kit/'runteams_creator_dev'/path.name)
    for path in (ROOT/'contracts/creator-system').rglob('*'):
        if path.is_file():copy(path,kit/'runteams_core/_resources'/path.relative_to(ROOT))
    for name in ('product-model-v2.json','marketplace-pipeline-v2.json'):copy(ROOT/'contracts'/name,kit/'runteams_core/_resources/contracts'/name)
    for path in (ROOT/'sdk/ui').rglob('*'):
        if path.is_file() and 'node_modules' not in path.parts and 'tests' not in path.parts:copy(path,kit/'runteams_core/_resources'/path.relative_to(ROOT))
    for folder in ('sdk/runtime','sdk/shared','web/worker-avatars/bottts'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and 'node_modules' not in path.parts:
                copy(path,kit/'runteams_core/_resources'/path.relative_to(ROOT))
    for path in runtime_root.iterdir():
        if path.is_file():copy(path,kit/'mcp-runtime'/path.name)
    (kit/'mcp-runtime/node').chmod(0o755)
    copy(Path(esbuild),kit/'tools/esbuild');(kit/'tools/esbuild').chmod(0o755)
    copy(ROOT/'sdk/mcp-host/esbuild-LICENSE.txt',kit/'tools/esbuild.LICENSE.txt')
    (kit/'toolchain.json').write_bytes(canonical({'schema':'runteams.dev-toolchain/2','runtime':{'path':'mcp-runtime','manifest_sha256':runtime.manifest_sha256},'esbuild':{'path':'tools/esbuild','sha256':hashlib.sha256((kit/'tools/esbuild').read_bytes()).hexdigest()}}))
    vendor=kit/'mcp-libraries';vendor.mkdir()
    for src,dest in [('creator-server.cjs','server.cjs'),('creator-app.js','app.js'),('creator-server.cjs.LEGAL.txt','creator-server.cjs.LEGAL.txt'),
                     ('creator-app.js.LEGAL.txt','creator-app.js.LEGAL.txt'),('THIRD_PARTY_NOTICES.txt','THIRD_PARTY_NOTICES.txt')]:copy(libraries/src,vendor/dest)
    copy(ROOT/'sdk/ui/dist/foundation/theme.css',vendor/'theme.css');copy(ROOT/'sdk/ui/dist/components/styles.css',vendor/'components.css')
    files=make('local-employee','本机员工开发示例',vendor)
    for name,body in files.items():
        for base in (output/'source',kit/'templates/mcp/source'):
            target=base/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
    for path in (output/'dev/tests.json',kit/'templates/mcp/tests.json'):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(canonical(mcp_cases()))
    guide=(ROOT/'runteams_creator_dev/MCP_AUTHORING.md').read_text()
    (output/'README.md').write_text(guide);copy(ROOT/'runteams_creator_dev/UIKIT.md',output/'UIKIT.md')
    for name in ('AGENTS.md','CLAUDE.md'):copy(ROOT/'runteams_creator_dev'/('PROJECT_'+name),output/name)
    skill=output/'.agents/skills/runteams-creator/SKILL.md';skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: runteams-creator\ndescription: Develop and verify local RunTeams MCP employee sources with the bundled tools.\n---\n\n'+guide)
    copy(ROOT/'requirements/runtime.txt',output/'requirements.txt')
    (output/'.gitignore').write_text('.venv/\n__pycache__/\ndist/\ndev/mcp-preview/\n')
    (output/'runteams.py').write_text('from pathlib import Path\nimport sys\nsys.path.insert(0,str(Path(__file__).resolve().parent/"_runteams"))\nfrom runteams_creator_dev.cli import main\nraise SystemExit(main())\n')
    (output/'devkit-inventory.json').write_bytes(canonical(inventory(output)))
    return {'workspace':str(output),'source':'editable-mcp-development-template','cloud_verified':False,'published':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--profile',choices=['mcp'],default='mcp')
    parser.add_argument('--runtime-root');parser.add_argument('--libraries')
    for tool in ('esbuild',):
        parser.add_argument('--' + tool)
    args = parser.parse_args()
    print(json.dumps(export_mcp(args.output,args.runtime_root,args.libraries,args.esbuild),ensure_ascii=False,indent=2))
