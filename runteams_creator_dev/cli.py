"""Machine-readable commands shared by Codex and humans. No cloud login."""
import argparse
import json
from pathlib import Path
import stat
import sys

from runteams_core.content_hashes import sha256 as sha
from runteams_core.creator_contracts import (MAX_BYTES, MAX_FILES, CreatorContractError,
    canonical, compile_source, relative, source_files, strict_json, tree)
from runteams_core.creator_definitions import definition_artifacts
from . import VERSION
from .archive import inspect_file, pack

ROOT = Path(__file__).resolve().parents[1]


def read_source(folder):
    root = Path(folder)
    if root.is_symlink() or not root.is_dir():
        raise CreatorContractError('invalid_root')
    files, total = {}, 0
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise CreatorContractError('invalid_path')
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CreatorContractError('invalid_path')
        total += info.st_size
        if total > MAX_BYTES or len(files) >= MAX_FILES:
            raise CreatorContractError('asset_limit')
        name = relative(path.relative_to(root).as_posix())
        with path.open('rb') as stream:
            body = stream.read(info.st_size + 1)
        if len(body) != info.st_size:
            raise CreatorContractError('source_changed_during_read')
        files[name] = body
    return source_files(files)


def check(files):
    from runteams_core.creator_source_import import validate_source
    return validate_source(files)


def toolchain(path):
    path = Path(path).resolve()
    config = strict_json(path.read_bytes())
    if config.get('schema')=='runteams.dev-toolchain/2':
        from runteams_core.employee_mcp import ManagedMCPRuntime
        value=config['runtime'];root=path.parent/relative(value['path'])
        runtime=ManagedMCPRuntime(root,value['manifest_sha256']);runtime.verify()
        entry=config['esbuild'];parser=path.parent/relative(entry['path'])
        if parser.is_symlink() or sha(parser.read_bytes())!=entry['sha256']:raise ValueError('toolchain_integrity')
        return config,{'runtime':runtime,'esbuild':parser}
    raise ValueError('unsupported_toolchain')


def build(files, configuration):
    check(files)
    from runteams_core.creator_mcp_source import mcp_project
    if mcp_project(files):
        from runteams_core.creator_mcp_build import MCPSourceBuilder
        from runteams_core.creator_mcp_preview import MCPPreview
        config,paths=toolchain(configuration)
        if config['schema']!='runteams.dev-toolchain/2':raise ValueError('mcp_toolchain_required')
        built=MCPSourceBuilder(paths['runtime'],esbuild=paths['esbuild'],esbuild_sha256=config['esbuild']['sha256']).build(files);built['files']=files
        return built,MCPPreview(built,paths['runtime'],Path(configuration).absolute().parent.parent/'dev/mcp-preview'/built['manifest']['source_sha256'])
    raise ValueError('unsupported_source_contract')


def write_new(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description='RunTeams local creator development; preview and self-test require trusted author code')
    parser.add_argument('--project', default='source')
    parser.add_argument('--toolchain', default=str(ROOT / 'toolchain.json'))
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Create a standalone employee workspace from the bundled example')
    init.add_argument('directory')
    init.add_argument('--key', required=True)
    init.add_argument('--name', required=True)
    reopen = commands.add_parser('open', help='Continue a platform source ZIP in a new standalone workspace')
    reopen.add_argument('archive'); reopen.add_argument('directory')
    commands.add_parser('doctor')
    commands.add_parser('check')
    commands.add_parser('build')
    test = commands.add_parser('test'); test.add_argument('--cases', default='dev/tests.json');test.add_argument('--trust-local-code',action='store_true')
    archive = commands.add_parser('pack'); archive.add_argument('--output', required=True)
    inspect = commands.add_parser('inspect'); inspect.add_argument('archive')
    preview = commands.add_parser('preview'); preview.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    result = {'sdk_dev': VERSION, 'scope': 'local-code-development', 'cloud_verified': False, 'published': False}
    try:
        if args.command == 'init':
            from .scaffold import initialize
            result.update(initialize(ROOT, args.directory, args.key, args.name), ok=True)
        elif args.command == 'open':
            from .scaffold import open_archive
            result.update(open_archive(ROOT,args.archive,args.directory),ok=True)
        elif args.command == 'doctor':
            config, paths = toolchain(args.toolchain)
            result.update(ok=True, platform=sys.platform, tools={k: config[k]['sha256'] if k!='runtime' else paths[k].manifest_sha256 for k in paths})
        else:
            files = inspect_file(args.archive) if args.command == 'inspect' else read_source(args.project)
            compiled = check(files)
            result.update(ok=True, source_sha256=compiled['source']['sha256'], files=len(files))
            if args.command == 'pack':
                target = Path(args.output).resolve()
                if target.is_relative_to(Path(args.project).resolve()):
                    raise ValueError('output_must_be_outside_source')
                raw = pack(files); write_new(target, raw)
                result.update(archive=str(target), archive_sha256=sha(raw), format='runteams.source-archive/1-dev')
            if args.command in ('build', 'test', 'preview'):
                built, sandbox = build(files, args.toolchain)
                source_root=Path(args.project).absolute();expected=built['manifest']['source_sha256']
                def current_source():
                    if tree(read_source(source_root))['sha256']!=expected:
                        raise PermissionError('源码已变化，请重新构建并明确启用新的预览。')
                sandbox.check_callback=current_source
                result.update(artifacts=[{'path': p, 'sha256': sha(b)} for p, b in sorted(built['artifacts'].items())])
                if args.command == 'test':
                    if not args.trust_local_code:raise ValueError('local_code_trust_required: self-test executes the current local author program')
                    try:result['cases']=sandbox.run_tests(strict_json(Path(args.cases).read_bytes()))
                    finally:sandbox.close()
                if args.command == 'preview':
                    from .mcp_preview import serve
                    serve(sandbox,args.port)
                    return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        result.update(ok=False, code=getattr(error, 'code', type(error).__name__), message=str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
