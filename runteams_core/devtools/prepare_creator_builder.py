"""Stage signed SDK build resources and the matching portable development kit."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = source_root()
sys.path.insert(0, str(ROOT))
from runteams_core.creator_build_tools import load
from runteams_core.creator_contracts import canonical, strict_json
from runteams_creator_dev.file_copy import copy_new


def prepare(source, output, *, sign_identity=None, profile='mcp'):
    source, output = Path(source).resolve(), Path(output).absolute()
    load(source,profile=profile)
    if output.is_symlink() or output.exists():raise ValueError('output_exists')
    output.mkdir(mode=0o755,parents=True)
    target=output/'esbuild';copy_new(source/'esbuild',target)
    if sign_identity is not None:
        subprocess.run(['/usr/bin/codesign','--force','-s',sign_identity,str(target)],check=True,capture_output=True)
    target.chmod(0o755)
    manifest={'schema':'runteams.platform-builder/2','platform':'darwin-arm64',
        'esbuild':{'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}}
    (output/'toolchain.json').write_bytes(canonical(manifest));load(output,profile=profile)
    return manifest


def sdk_archive(tools, output, *, profile='mcp', runtime_root=None, libraries=None):
    from runteams_core.devtools.export_creator_devkit import export_mcp
    import tempfile
    output = Path(output).absolute()
    with tempfile.TemporaryDirectory(prefix='runteams-sdk-stage-', dir=output.parent) as temporary:
        kit = Path(temporary)/'sdk'
        if profile!='mcp':raise ValueError('unsupported_sdk_profile')
        export_mcp(kit,runtime_root,libraries,Path(tools)/'esbuild')
        inventory = strict_json((kit/'devkit-inventory.json').read_bytes())
        with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(kit.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(kit).as_posix())
        with zipfile.ZipFile(output) as archive:
            expected = {item['path']:item['sha256'] for item in inventory['files']}
            expected['devkit-inventory.json'] = hashlib.sha256((kit/'devkit-inventory.json').read_bytes()).hexdigest()
            if set(archive.namelist()) != set(expected):
                raise ValueError('sdk_archive_integrity')
            for name, sha in expected.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != sha:
                    raise ValueError('sdk_archive_integrity')
    return {'sha256':hashlib.sha256(output.read_bytes()).hexdigest(), 'files':len(expected)}


def compiler_source_hashes():
    # Frozen Python modules live in PYZ. The compiler's existing provenance
    # contract hashes exact source bytes, so retain that explicit source set
    # as signed data too; never infer provenance from a missing source file.
    from runteams_core.creator_definitions import compiler_identity
    expected = compiler_identity()['implementation']
    for name in ('creator_build.py','creator_dependencies.py','creator_mcp_build.py','creator_conversation_assets.py','creator_source_import.py','creator_local_build_worker.py'):
        expected[name] = hashlib.sha256((ROOT/'runteams_core'/name).read_bytes()).hexdigest()
    return expected


def compiler_sources(output, *, verify=False):
    expected = compiler_source_hashes()
    output = Path(output).absolute()
    if verify:
        if output.is_symlink():raise ValueError('compiler_source_integrity')
        for name, sha256 in expected.items():
            target = output/name
            if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
                raise ValueError('compiler_source_integrity')
        return expected
    if output.exists() or output.is_symlink():
        raise ValueError('output_exists')
    output = output.resolve();output.mkdir(parents=True)
    for name, sha256 in expected.items():
        target = output/name
        copy_new(ROOT/'runteams_core'/name, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
            raise ValueError('compiler_source_integrity')
    return expected


def seal_packaged(source, target, *, profile='mcp'):
    # PyInstaller may rewrite/re-sign Mach-O DATA entries. Restore the exact
    # already-signed staging closure after collection, before sealing the app.
    source = Path(source).resolve();load(source,profile=profile)
    target = Path(target).absolute()
    if any(p.is_symlink() for p in (target,*target.parents)):
        raise ValueError('linked_builder_output')
    target = target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('builder_output_overlaps_source')
    names = {'esbuild','toolchain.json'}
    if {p.name for p in target.iterdir()} != names or not all((target/n).is_file() and not (target/n).is_symlink() for n in names):
        raise ValueError('unexpected_builder_output')
    for name in names:
        (target/name).unlink()
        copy_new(source/name,target/name)
    return load(target,profile=profile)[1]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', required=True)
    parser.add_argument('--output')
    parser.add_argument('--sign-identity')
    parser.add_argument('--sdk-archive')
    parser.add_argument('--sdk-profile',choices=['mcp'],default='mcp')
    parser.add_argument('--mcp-runtime')
    parser.add_argument('--mcp-libraries')
    parser.add_argument('--compiler-output')
    parser.add_argument('--restore-to')
    parser.add_argument('--verify-compiler',action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        tools = Path(args.tools).resolve()
        _, identity = load(tools,profile=args.sdk_profile)
        result = {'verified':True, 'toolchain_sha256':identity}
        if args.sdk_archive:result['sdk']=sdk_archive(tools,args.sdk_archive,profile=args.sdk_profile,runtime_root=args.mcp_runtime,libraries=args.mcp_libraries)
    else:
        if not args.output:parser.error('--output is required')
        manifest = prepare(args.tools, args.output, sign_identity=args.sign_identity, profile=args.sdk_profile)
        tools = Path(args.output).resolve()
        result = {'toolchain':manifest}
        if args.sdk_archive:result['sdk']=sdk_archive(args.output,args.sdk_archive,profile=args.sdk_profile,runtime_root=args.mcp_runtime,libraries=args.mcp_libraries)
    if args.compiler_output:result['compiler_sources']=compiler_sources(args.compiler_output,verify=args.verify_compiler)
    if args.restore_to:result['sealed_toolchain_sha256']=seal_packaged(tools,args.restore_to,profile=args.sdk_profile)
    print(canonical(result).decode())
