"""Build and verify the SDK kit from pinned public inputs on macOS ARM64."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys

from .source_root import root as source_root

ROOT = source_root()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        parser.error('The pinned SDK developer-kit target is macOS ARM64')
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)

    def run(name, command, cwd=ROOT):
        result = subprocess.run([str(x) for x in command], cwd=cwd, capture_output=True, text=True)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ' failed; see ' + str(output / (name + '.log')))

    from .provision_mcp_node import provision
    from .prepare_mcp_runtime import prepare
    from .export_creator_devkit import export_mcp
    from .prepare_creator_builder import sdk_archive

    node = provision(output / 'node-cache')
    host = output / 'host'
    runtime = output / 'runtime'
    run('npm-install', ['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], ROOT / 'sdk/mcp-host')
    run('libraries-build', [node, ROOT / 'sdk/mcp-host/build.mjs', host])
    prepare(node, host, runtime, node_license=node.parent.parent / 'LICENSE')
    esbuild = ROOT / 'sdk/mcp-host/node_modules/@esbuild/darwin-arm64/bin/esbuild'
    kit = output / 'workspace'
    export_mcp(kit, runtime, host, esbuild)
    commands = [('doctor', ['doctor']), ('check', ['check']), ('build', ['build']),
                ('test', ['test', '--trust-local-code']),
                ('pack', ['pack', '--output', str(output / 'employee-source.zip')]),
                ('init', ['init', str(output / 'new-employee'), '--key', 'new-employee', '--name', 'New employee']),
                ('open', ['open', str(output / 'employee-source.zip'), str(output / 'continued-employee')])]
    for name, command in commands:
        run(name, [sys.executable, '-B', kit / 'runteams.py', *command], kit)
    archive = sdk_archive(esbuild.parent, output / 'runteams-devkit.zip',
                          runtime_root=runtime, libraries=host)
    report = {'target': 'darwin-arm64', 'steps': [name for name, _ in commands],
              'archive': archive, 'real_model_or_account': False}
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
