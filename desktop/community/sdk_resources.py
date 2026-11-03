"""Verified SDK build resources for the existing community desktop package.

Only the packager selects these directories. No author metadata, application
startup or user conversation can provision tools or download dependencies.
"""
import hashlib
import shutil
from pathlib import Path

from runteams_core.creator_build_tools import load
from runteams_core.creator_contracts import canonical, strict_json
from runteams_core.devtools.package_creator_builder import package as package_builder
from runteams_core.devtools.package_mcp_runtime import verify as verify_mcp

ROOT = Path(__file__).resolve().parents[2]
LICENSE = 'sdk/mcp-host/esbuild-LICENSE.txt'


def snapshot(builder=None, runtime=None):
    builder = Path(builder).expanduser().absolute() if builder else ROOT/'runtime-dependencies/creator-builder'
    runtime = Path(runtime).expanduser().absolute() if runtime else ROOT/'runtime-dependencies/mcp-runtime'
    load(builder)
    runtime_files = verify_mcp(runtime)
    license_path = ROOT/LICENSE
    if license_path.is_symlink() or not license_path.is_file():
        raise ValueError('Missing original esbuild license')
    return {'builder':str(builder), 'runtime':str(runtime),
        'builder_files':{n:hashlib.sha256((builder/n).read_bytes()).hexdigest() for n in ('esbuild','toolchain.json')},
        'runtime_files':runtime_files,'esbuild_license_sha256':hashlib.sha256(license_path.read_bytes()).hexdigest()}


def stage(core, expected, signer):
    # Re-read the full original closure before and after copying. No source
    # mutation, symlinks, hard-link resource coalescing or stale-tool fallback.
    if snapshot(expected['builder'],expected['runtime']) != expected:
        raise ValueError('SDK build resources changed after planning')
    root = Path(core)/'runtime-dependencies'
    builder, runtime = root/'creator-builder', root/'mcp-runtime'
    if builder.exists() or builder.is_symlink() or runtime.exists() or runtime.is_symlink():
        raise ValueError('SDK build resource output already exists')
    package_builder(builder, {'esbuild':Path(expected['builder'])/'esbuild'})
    shutil.copyfile(ROOT/LICENSE,builder/'esbuild-LICENSE.txt')
    shutil.copytree(expected['runtime'],runtime)
    signer.sign(builder/'esbuild',executable=True)
    signer.sign(runtime/'node',executable=True)
    toolchain = strict_json((builder/'toolchain.json').read_bytes())
    toolchain['esbuild']['sha256'] = hashlib.sha256((builder/'esbuild').read_bytes()).hexdigest()
    (builder/'toolchain.json').write_bytes(canonical(toolchain))
    manifest = strict_json((runtime/'runtime.json').read_bytes())
    manifest['files']['node'] = hashlib.sha256((runtime/'node').read_bytes()).hexdigest()
    raw = canonical(manifest)
    (runtime/'runtime.json').write_bytes(raw)
    (runtime/'runtime.sha256').write_text(hashlib.sha256(raw).hexdigest()+'\n')
    _, identity = load(builder)
    runtime_files = verify_mcp(runtime)
    if snapshot(expected['builder'],expected['runtime']) != expected:
        raise ValueError('SDK build source resources changed during packaging')
    return {'schema':'runteams.community-sdk-resources/1','builder_identity':identity,
        'esbuild_sha256':toolchain['esbuild']['sha256'],
        'runtime_manifest_sha256':hashlib.sha256(raw).hexdigest(),'runtime_files':runtime_files}
