"""Machine-readable commands shared by Codex and humans. No cloud login."""
import argparse
import json
from pathlib import Path
import stat
import sys
from tempfile import TemporaryDirectory

from runteams_core.foundation.content_hashes import sha256 as sha
from runteams_core.authoring.creator_contracts import MAX_BYTES, MAX_FILES, CreatorContractError, relative, source_files, strict_json, tree
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
    from runteams_core.authoring.source.creator_source_import import validate_source
    return validate_source(files)


def toolchain(path):
    path = Path(path).resolve()
    config = strict_json(path.read_bytes())
    if config.get('schema')=='runteams.dev-toolchain/2':
        from runteams_core.employees.mcp.employee_mcp import ManagedMCPRuntime
        value=config['runtime'];root=path.parent/relative(value['path'])
        runtime=ManagedMCPRuntime(root,value['manifest_sha256']);runtime.verify()
        entry=config['esbuild'];parser=path.parent/relative(entry['path'])
        if parser.is_symlink() or sha(parser.read_bytes())!=entry['sha256']:raise ValueError('toolchain_integrity')
        return config,{'runtime':runtime,'esbuild':parser}
    raise ValueError('unsupported_toolchain')


def local_builder(configuration):
    if configuration is None:
        from runteams_core.authoring.compilation.creator_build_tools import load
        from runteams_core.employees.mcp.employee_mcp import platform_runtime
        builder, _ = load()
        builder.runtime = platform_runtime()
        return builder

    from runteams_core.authoring.compilation.creator_mcp_build import MCPSourceBuilder
    config, paths = toolchain(configuration)
    return MCPSourceBuilder(paths['runtime'], esbuild=paths['esbuild'],
                            esbuild_sha256=config['esbuild']['sha256'])


def run_local_code(args, built, runtime, root):
    from runteams_core.authoring.creator_mcp_preview import MCPPreview

    source_root = Path(args.project).absolute()
    expected = built['manifest']['source_sha256']

    def current_source():
        if tree(read_source(source_root))['sha256'] != expected:
            raise PermissionError('源码已变化，请重新构建并明确启用新的预览。')

    preview = MCPPreview(built, runtime, root, check=current_source)
    if args.command == 'preview':
        from .mcp_preview import serve
        serve(preview, args.port)
        return None
    try:
        return preview.run_tests(strict_json(Path(args.cases).read_bytes()))
    finally:
        preview.close()


def write_new(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(body)


def main(argv=None, *, packaged=False):
    parser = argparse.ArgumentParser(description='RunTeams local creator development; preview and self-test require trusted author code')
    parser.add_argument('--project', default='source')
    if not packaged:
        parser.add_argument('--toolchain', default=str(ROOT / 'toolchain.json'))
    commands = parser.add_subparsers(dest='command', required=True)
    if not packaged:
        init = commands.add_parser('init', help='Create a standalone employee workspace from the bundled example')
        init.add_argument('directory')
        init.add_argument('--key', required=True)
        init.add_argument('--name', required=True)
        reopen = commands.add_parser('open', help='Continue a platform source ZIP in a new standalone workspace')
        reopen.add_argument('archive')
        reopen.add_argument('directory')
    commands.add_parser('doctor')
    commands.add_parser('check')
    commands.add_parser('build')
    test = commands.add_parser('test'); test.add_argument('--cases', default='dev/tests.json');test.add_argument('--trust-local-code',action='store_true')
    archive = commands.add_parser('pack'); archive.add_argument('--output', required=True)
    archive.add_argument('--knowledge', action='append', default=[], metavar='ENTRY=FOLDER',
                         help='include the selected employee or pipeline materials folder')
    inspect = commands.add_parser('inspect'); inspect.add_argument('archive')
    preview = commands.add_parser('preview'); preview.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    configuration = None if packaged else args.toolchain
    result = {'sdk_dev': VERSION, 'scope': 'local-code-development', 'cloud_verified': False, 'published': False}
    try:
        if args.command == 'init':
            from .scaffold import initialize
            result.update(initialize(ROOT, args.directory, args.key, args.name), ok=True)
        elif args.command == 'open':
            from .scaffold import open_archive
            result.update(open_archive(ROOT,args.archive,args.directory),ok=True)
        elif args.command == 'doctor':
            builder = local_builder(configuration)
            result.update(ok=True, platform=sys.platform, tools={
                'esbuild': builder.esbuild_sha256,
                'runtime': builder.runtime.manifest_sha256,
            })
        else:
            from . import knowledge
            if args.command == 'inspect':
                with TemporaryDirectory() as directory:
                    files = knowledge.inspect_package(args.archive, Path(directory))
            else:
                files = read_source(args.project)
            blobs = {}
            if args.command == 'pack':
                folders = knowledge.folders_for(files, args.project, args.knowledge)
                if folders:
                    files, blobs = knowledge.media.inventory(files, folders)
            if args.command in ('build', 'test', 'preview'):
                if args.command == 'test' and not args.trust_local_code:
                    raise ValueError('local_code_trust_required: self-test executes the current local author program')
                builder = local_builder(configuration)
                built = builder.build(files)
                compiled = built['compiled']
                result['artifacts'] = [{'path': path, 'sha256': sha(body)}
                                       for path, body in sorted(built['artifacts'].items())]
            else:
                compiled = check(files)
            result.update(ok=True, source_sha256=compiled['source']['sha256'], files=len(files))
            if args.command == 'pack':
                target = Path(args.output).resolve()
                if target.is_relative_to(Path(args.project).resolve()):
                    raise ValueError('output_must_be_outside_source')
                checksum = knowledge.save_package(target, files, blobs)
                result.update(archive=str(target), archive_sha256=checksum,
                              format='runteams.knowledge-package/1' if blobs else 'runteams.source-archive/1-dev')
            if args.command in ('test', 'preview'):
                if packaged:
                    with TemporaryDirectory(prefix='runteams-sdk-') as folder:
                        cases = run_local_code(args, built, builder.runtime, Path(folder).resolve())
                else:
                    root = Path(configuration).absolute().parent.parent / 'dev/mcp-preview'
                    cases = run_local_code(args, built, builder.runtime, root / result['source_sha256'])
                if args.command == 'preview':
                    return 0
                result['cases'] = cases
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        result.update(ok=False, code=getattr(error, 'code', type(error).__name__), message=str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
