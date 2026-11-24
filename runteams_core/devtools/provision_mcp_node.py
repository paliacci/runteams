"""Build-time Node provisioner, not an installation/first-launch hook.

The supported target list is deliberately limited to the verified native
candidate. No global environment, provider CLI or system Node is changed.
"""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import tarfile
import zipfile
import stat
from urllib.request import urlopen

ROOT = source_root()
LOCK = ROOT / 'sdk/mcp-host/node-runtime.json'


def provision(cache):
    lock = json.loads(LOCK.read_text())
    machine = platform.machine().lower()
    machine = {'aarch64': 'arm64', 'x86_64': 'x64', 'amd64': 'x64'}.get(machine, machine)
    target = sys.platform + '-' + machine
    spec = lock['targets'].get(target)
    if spec is None:
        raise ValueError('mcp_node_target_not_verified')
    cache = Path(cache).absolute()
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / spec['file']
    if not archive.exists():
        # Exact official HTTPS resource, with a separately pinned source hash.
        request = 'https://nodejs.org/dist/v' + lock['version'] + '/' + spec['file']
        with urlopen(request, timeout=30) as response:
            raw = response.read(128 * 1024 * 1024 + 1)
        if len(raw) > 128 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != spec['sha256']:
            raise ValueError('mcp_node_download_integrity')
        archive.write_bytes(raw)
    if archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
        raise ValueError('mcp_node_download_integrity')
    if archive.suffix == '.zip':
        output = cache / archive.stem
        executable = 'bin/node.exe'
        with zipfile.ZipFile(archive) as source:
            for member, dest in [('node.exe', executable), ('LICENSE', 'LICENSE')]:
                info = source.getinfo(archive.stem + '/' + member)
                if (info.is_dir() or stat.S_ISLNK(info.external_attr >> 16)
                        or info.file_size > 128 * 1024 * 1024):
                    raise ValueError('mcp_node_download_integrity')
                _store(output / dest, source.read(info))
    else:
        output = cache / archive.name.removesuffix('.tar.gz')
        executable = 'bin/node'
        with tarfile.open(archive, 'r:gz') as source:
            for member in (executable, 'LICENSE'):
                item = source.getmember(output.name + '/' + member)
                if not item.isfile() or item.size > 128 * 1024 * 1024:
                    raise ValueError('mcp_node_download_integrity')
                _store(output / member, source.extractfile(item).read())
    node = output / executable
    node.chmod(0o755)
    return node


def _store(path, body):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('mcp_node_cache_invalid')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise ValueError('mcp_node_cache_changed')
    else:
        path.write_bytes(body)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', required=True)
    args = parser.parse_args()
    print(provision(args.cache))
