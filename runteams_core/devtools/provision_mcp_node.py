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
from urllib.request import urlopen

ROOT = source_root()
LOCK = ROOT / 'sdk/mcp-host/node-runtime.json'


def provision(cache):
    lock = json.loads(LOCK.read_text())
    machine = {'aarch64': 'arm64', 'x86_64': 'x64'}.get(platform.machine(), platform.machine())
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
    prefix = spec['file'].removesuffix('.tar.gz')
    output = cache / prefix
    # Extract only two fixed regular members, never archive-controlled paths.
    with tarfile.open(archive, 'r:gz') as source:
        for name in ('bin/node', 'LICENSE'):
            item = source.getmember(prefix + '/' + name)
            if not item.isfile() or item.size > 128 * 1024 * 1024:
                raise ValueError('mcp_node_download_integrity')
            target_file = output / name
            if any(p.is_symlink() for p in (target_file, *target_file.parents)):
                raise ValueError('mcp_node_cache_invalid')
            body = source.extractfile(item).read()
            target_file.parent.mkdir(parents=True, exist_ok=True)
            if target_file.exists() and target_file.read_bytes() != body:
                raise ValueError('mcp_node_cache_changed')
            if not target_file.exists():
                target_file.write_bytes(body)
            if name == 'bin/node':
                target_file.chmod(0o755)
    return output / 'bin/node'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', required=True)
    args = parser.parse_args()
    print(provision(args.cache))
