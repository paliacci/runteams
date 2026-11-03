"""Seal the already verified M06 runtime for desktop packaging; never fetch tools."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = source_root()
sys.path.insert(0, str(ROOT))
from runteams_core.authoring.creator_contracts import canonical, strict_json
from runteams_core.employees.mcp.employee_mcp import ManagedMCPRuntime

FILES = {'node', 'worker.cjs', 'app-host.js', 'runtime.json', 'runtime.sha256',
         'provenance.json', 'NODE-LICENSE', 'THIRD_PARTY_NOTICES.txt',
         'worker.cjs.LEGAL.txt', 'app-host.js.LEGAL.txt'}


def verify(root):
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('linked_mcp_runtime')
    if {p.name for p in root.iterdir()} != FILES:
        raise ValueError('unexpected_mcp_resources')
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('linked_mcp_resource')
    pin = (root / 'runtime.sha256').read_text().strip()
    ManagedMCPRuntime(root, pin).verify()
    manifest = strict_json((root / 'runtime.json').read_bytes())
    if not manifest['node_version'].startswith('v24.'):
        raise ValueError('mcp_node24_required')
    provenance = strict_json((root / 'provenance.json').read_bytes())
    if provenance['lock_sha256'] != hashlib.sha256((ROOT / 'sdk/mcp-host/package-lock.json').read_bytes()).hexdigest():
        raise ValueError('mcp_host_lock_integrity')
    for name in ('worker.cjs', 'app-host.js'):
        if provenance['files'][name] != manifest['files'][name]:
            raise ValueError('mcp_host_integrity')
    # File pins and a dependency lock can also describe an obsolete host.
    # Both editions use this build-time probe; no author program is loaded.
    try:
        presentation = subprocess.run([str(root/'node'),
            str(ROOT/'runteams_core/devtools/check_mcp_host_presentation.cjs'),str(root/'app-host.js')],
            capture_output=True,text=True,timeout=15)
    except (OSError,subprocess.TimeoutExpired) as error:
        raise ValueError('MCP 宿主展开能力无法核对，请重新准备当前 SDK 运行资源。') from error
    if presentation.returncode:
        raise ValueError('MCP 宿主不支持工作台展开与返回，请重新构建当前 SDK 运行资源。')
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir())}


def prepare(source, output, identity):
    source, output = Path(source).absolute(), Path(output).absolute()
    before = verify(source)
    if output.exists() or output.is_symlink():
        raise ValueError('output_exists')
    if not identity:
        raise ValueError('signing_identity_required')
    shutil.copytree(source, output)
    # Sign before pinning. PyInstaller and the final generic signing pass must
    # preserve these exact bytes, including the copy inside the downloadable kit.
    subprocess.run(['/usr/bin/codesign', '--force', '-s', identity, str(output / 'node')], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(output / 'node')], check=True)
    manifest = strict_json((output / 'runtime.json').read_bytes())
    manifest['files']['node'] = hashlib.sha256((output / 'node').read_bytes()).hexdigest()
    raw = canonical(manifest)
    (output / 'runtime.json').write_bytes(raw)
    (output / 'runtime.sha256').write_text(hashlib.sha256(raw).hexdigest() + '\n')
    result = verify(output)
    if verify(source) != before:
        raise ValueError('source_changed_during_packaging')
    return result


def seal(source, target):
    source, target = Path(source).absolute(), Path(target).absolute()
    expected = verify(source)
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('overlapping_mcp_output')
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError('linked_mcp_output')
    if {p.name for p in target.iterdir()} != FILES or any(p.is_symlink() or not p.is_file() for p in target.iterdir()):
        raise ValueError('unexpected_mcp_output')
    for name in FILES:
        (target / name).unlink()
        shutil.copy2(source / name, target / name)
    if verify(target) != expected:
        raise ValueError('mcp_seal_integrity')
    return expected


def verify_sdk(runtime, tools, resources):
    runtime, tools, resources = Path(runtime), Path(tools), Path(resources)
    expected = verify(runtime)
    metadata = strict_json((resources / 'resource.json').read_bytes())
    path = resources / 'RunTeams-Creator-SDK.zip'
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sdk']['sha256']:
        raise ValueError('sdk_archive_integrity')
    with zipfile.ZipFile(path) as z:
        inventory = strict_json(z.read('devkit-inventory.json'))
        rows = {item['path']: item['sha256'] for item in inventory['files']}
        if set(z.namelist()) != set(rows) | {'devkit-inventory.json'} or len(z.namelist()) != len(rows) + 1:
            raise ValueError('sdk_inventory_integrity')
        for name, digest in rows.items():
            if hashlib.sha256(z.read(name)).hexdigest() != digest:
                raise ValueError('sdk_inventory_integrity')
        for name, digest in expected.items():
            if hashlib.sha256(z.read('_runteams/mcp-runtime/' + name)).hexdigest() != digest:
                raise ValueError('sdk_mcp_runtime_binding')
        parser = (tools / 'esbuild').read_bytes()
        if z.read('_runteams/tools/esbuild') != parser:
            raise ValueError('sdk_parser_binding')
        config = strict_json(z.read('_runteams/toolchain.json'))
        if config['runtime']['manifest_sha256'] != (runtime / 'runtime.sha256').read_text().strip():
            raise ValueError('sdk_runtime_pin')
        if config['esbuild']['sha256'] != hashlib.sha256(parser).hexdigest():
            raise ValueError('sdk_parser_pin')
    return {'runtime_files': expected, 'sdk_sha256': metadata['sdk']['sha256']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--output')
    p.add_argument('--sign-identity')
    p.add_argument('--restore-to')
    p.add_argument('--sdk-resources')
    p.add_argument('--tools')
    args = p.parse_args()
    if args.output:
        result = prepare(args.source, args.output, args.sign_identity)
    elif args.restore_to:
        result = seal(args.source, args.restore_to)
    elif args.sdk_resources:
        result = verify_sdk(args.source, args.tools, args.sdk_resources)
    else:
        result = verify(args.source)
    print(canonical(result).decode())
