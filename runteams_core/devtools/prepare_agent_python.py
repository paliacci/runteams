"""Build-time provisioner for checksum-pinned, relocatable Agent Python.

Never invoked by application startup. Release packages carry the completed
payload; users need no Python install, download or dependency repair on launch.
"""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import Request, urlopen

ROOT = source_root()
sys.path.insert(0, str(ROOT))
from runteams_core import agent_environment

LOCK = ROOT / 'contracts/agent-python.lock.json'
MODULES = ('tomllib', 'json', 'pathlib', 'sqlite3', 'ssl', 'venv', 'ensurepip', 'pip')


def download(asset, target):
    request = Request(asset['url'], headers={'User-Agent': 'RunTeams-runtime-build'})
    with urlopen(request, timeout=60) as response, target.open('wb') as output:
        shutil.copyfileobj(response, output)
    if target.stat().st_size != asset['bytes'] or hashlib.sha256(target.read_bytes()).hexdigest() != asset['sha256']:
        raise ValueError('Official Python resource checksum mismatch')


def notices(archive, staging, payload):
    # Install-only archives omit dependency license texts. Keep the matching
    # full distribution's notices and metadata without its build artifacts.
    tar = shutil.which('tar')
    if not tar:
        raise ValueError('Release tooling requires tar with Zstandard support')
    paths = subprocess.check_output([tar, '-tf', str(archive)], text=True).splitlines()
    selected = [name for name in paths if name == 'python/PYTHON.json' or
                (name.startswith('python/licenses/') and not name.endswith('/'))]
    if len(selected) < 2 or any('..' in Path(name).parts for name in selected):
        raise ValueError('Missing or invalid upstream Python notices')
    target = staging / 'notices'
    target.mkdir()
    subprocess.run([tar, '-xf', str(archive), '-C', str(target), *selected], check=True,
                   capture_output=True)
    shutil.copytree(target / 'python/licenses', payload / 'licenses')
    shutil.copyfile(target / 'python/PYTHON.json', payload / 'UPSTREAM-PYTHON.json')


def extract(archive, destination):
    with tarfile.open(archive, 'r:gz') as package:
        members = package.getmembers()
        if len(members) > 30000 or sum(m.size for m in members) > 600 * 1024 * 1024:
            raise ValueError('Python archive exceeds the build resource limit')
        for member in members:
            path = Path(member.name)
            if not path.parts or path.parts[0] != 'python' or path.is_absolute() or '..' in path.parts:
                raise ValueError('Invalid Python archive path')
        package.extractall(destination, filter='data')


def prepare(output, *, archive=None, signing_identity='-'):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Output exists; build into a new directory')
    lock = json.loads(LOCK.read_text())
    asset = lock['assets'][agent_environment.platform_key()]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.agent-python-', dir=output.parent) as tmp:
        staging = Path(tmp)
        if archive is None:
            archive = staging / 'python.tar.gz'
            download(asset, archive)
        archive = Path(archive)
        if archive.stat().st_size != asset['bytes'] or hashlib.sha256(archive.read_bytes()).hexdigest() != asset['sha256']:
            raise ValueError('Official Python archive checksum mismatch')
        extract(archive, staging)
        payload = staging / 'python'
        full = staging / 'python-full.tar.zst'
        download(asset['notices_archive'], full)
        notices(full, staging, payload)
        if sys.platform == 'darwin':
            # Sign before sealing; later desktop signing must preserve these bytes.
            for path in sorted(payload.rglob('*')):
                if path.is_symlink() or not path.is_file():
                    continue
                with path.open('rb') as source:
                    magic = source.read(4)
                if magic in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
                    subprocess.run(['/usr/bin/codesign', '--force', '-s', signing_identity, str(path)],
                                   check=True, capture_output=True)
                    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(path)],
                                   check=True, capture_output=True)
        executable = 'python.exe' if os.name == 'nt' else 'bin/python3'
        # Do not inherit a builder venv's module search paths or frozen-app loader.
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONHOME', 'PYTHONPATH', 'DYLD_LIBRARY_PATH')}
        script = ('import importlib,json,sys; print(json.dumps({"version":sys.version.split()[0],'
                  '"modules":{name:bool(importlib.import_module(name)) for name in ' + repr(MODULES) + '}}))')
        result = subprocess.run([str(payload / executable), '-I', '-B', '-c', script],
                                check=True, capture_output=True, text=True, env=env, timeout=15)
        info = json.loads(result.stdout)
        if info['version'] != lock['version'] or not all(info['modules'].values()):
            raise ValueError('Bundled Python does not satisfy its declared capabilities')
        manifest = {'schema': 'runteams.agent-python/1', 'platform': agent_environment.platform_key(),
                    'version': info['version'], 'executable': executable, 'modules': info['modules'],
                    'archive_sha256': asset['sha256'], 'lock_sha256': hashlib.sha256(LOCK.read_bytes()).hexdigest(),
                    'files': agent_environment.payload_files(payload)}
        raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
        (payload / 'runtime.json').write_bytes(raw)
        (payload / 'runtime.sha256').write_text(hashlib.sha256(raw).hexdigest() + '\n')
        agent_environment.verify_runtime(payload)
        payload.rename(output)
    return {key: manifest[key] for key in ('schema', 'platform', 'version', 'archive_sha256', 'modules')}


def stage(source, output):
    source, output = Path(source).absolute(), Path(output).absolute()
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError('Runtime output must be outside its source')
    agent_environment.verify_runtime(source)
    if output.exists():
        raise ValueError('Runtime output already exists')
    shutil.copytree(source, output, symlinks=True)
    return agent_environment.verify_runtime(output)['version']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    parser.add_argument('--archive')
    parser.add_argument('--sign-identity', default='-')
    parser.add_argument('--stage-from')
    parser.add_argument('--verify')
    args = parser.parse_args()
    if args.verify:
        value = agent_environment.verify_runtime(args.verify)
        print(json.dumps({'version': value['version'], 'platform': value['platform']}))
    elif args.stage_from:
        print(stage(args.stage_from, args.output))
    else:
        print(json.dumps(prepare(args.output, archive=args.archive, signing_identity=args.sign_identity)))
