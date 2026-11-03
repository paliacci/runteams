"""Check real packed SDKs in an isolated consumer; never publish or run hooks."""
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
import subprocess
import sys
import tempfile

ROOT = source_root()


def check(output, tsc):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    steps = []

    def run(name, args, cwd=ROOT):
        result = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        steps.append({'name': name, 'exit_code': result.returncode})
        if result.returncode: raise RuntimeError(name + ': ' + result.stdout + result.stderr)
        return result.stdout

    node, npm = shutil.which('node'), shutil.which('npm')
    if not node or not npm or not Path(tsc).is_file(): raise ValueError('Node/npm/TypeScript compiler required')
    run('generated', [sys.executable, ROOT / 'runteams_core/devtools/build_creator_sdk.py', '--check'])
    run('clients', [node, '--test', ROOT / 'sdk/tests/clients.test.mjs'])
    packages = []
    for profile in ('runtime', 'view'):
        details = json.loads(run('pack-' + profile, [npm, 'pack', '--ignore-scripts', '--json', '--pack-destination', output], ROOT / 'sdk' / profile))[0]
        tarball = output / details['filename']
        packages.append({'name': details['name'], 'version': details['version'], 'file': tarball.name,
            'sha256': hashlib.sha256(tarball.read_bytes()).hexdigest(), 'files': [f['path'] for f in details['files']]})
    with tempfile.TemporaryDirectory(prefix='runteams-sdk-consumer-') as directory:
        consumer = Path(directory)
        (consumer / 'package.json').write_text(json.dumps({'name': 'sdk-independent-consumer', 'private': True, 'type': 'module',
            'dependencies': {p['name']: 'file:' + str(output / p['file']) for p in packages}}))
        run('install', [npm, 'install', '--ignore-scripts', '--offline', '--no-audit', '--no-fund'], consumer)
        shutil.copy2(ROOT / 'sdk/tests/types.mts', consumer / 'types.mts')
        for mode, module in [('NodeNext', 'NodeNext'), ('Bundler', 'ESNext')]:
            run('types-' + mode.lower(), [node, tsc, '--noEmit', '--strict', '--target', 'ES2022', '--module', module,
                '--moduleResolution', mode, 'types.mts'], consumer)
        (consumer / 'runtime-only.mts').write_text("import {createRuntime, type RuntimeHost} from 'runteams-runtime';\ndeclare const host: RuntimeHost;\ncreateRuntime(host).data.query({collection:'quote',limit:1});\n")
        run('types-no-dom', [node, tsc, '--noEmit', '--strict', '--target', 'ES2022', '--lib', 'ES2022',
            '--module', 'NodeNext', '--moduleResolution', 'NodeNext', 'runtime-only.mts'], consumer)
        run('consumer', [node, '--input-type=module', '-e', """
import assert from 'node:assert/strict';
import * as runtime from 'runteams-runtime';
import * as view from 'runteams-view';
assert.equal(runtime.operationKey('task:save'),'task:save');
assert.match(view.newOperationKey(),/^op-/);
assert.throws(()=>view.createViewClient(undefined),e=>e.code==='sdk_host_unavailable');
await assert.rejects(import('runteams-runtime/internal/guards.js'),e=>e.code==='ERR_PACKAGE_PATH_NOT_EXPORTED');
console.log('Independent packed imports and exports boundary passed; no Skill loaded.');
"""], consumer)
    report = {'schema': 'runteams.sdk-package-verification/1', 'packages': packages, 'steps': steps,
        'typescript': run('typescript-version', [node, tsc, '--version']).strip(), 'registry_published': False,
        'cloud_verified': False, 'skill_required': False}
    (output / 'packages.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--tsc', required=True, help='Path to an existing TypeScript tsc JS entry; no dependency downloads')
    args = parser.parse_args()
    check(args.output, args.tsc)
