"""Prepare fixed application resources. Never download/install on an end user's launch."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import platform
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = source_root()
sys.path.insert(0, str(ROOT))
from runteams_core.authoring.creator_contracts import canonical
from runteams_core.employees.mcp.employee_mcp_package import sha256
from runteams_core.employees.mcp.employee_mcp import ManagedMCPRuntime


def prepare(node, host, output, *, node_license=None):
    node, host, output = Path(node).resolve(), Path(host).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('output_exists')
    version = subprocess.run([str(node), '--version'], check=True, capture_output=True, text=True).stdout.strip()
    if not version.startswith(('v22.', 'v24.')):
        raise ValueError('unsupported_managed_node')
    output.mkdir(parents=True, mode=0o755)
    name = 'node.exe' if sys.platform == 'win32' else 'node'
    shutil.copyfile(node, output / name)
    (output / name).chmod(0o755)
    for file in ('worker.cjs', 'app-host.js'):
        shutil.copyfile(host / file, output / file)
    shutil.copyfile(host / 'provenance.json', output / 'provenance.json')
    shutil.copyfile(host / 'THIRD_PARTY_NOTICES.txt', output / 'THIRD_PARTY_NOTICES.txt')
    candidates=[Path(node_license)] if node_license is not None else [node.parent/'NODE-LICENSE',node.parent.parent/'LICENSE']
    for license_path in candidates:
        if license_path.is_file() and not license_path.is_symlink():
            shutil.copyfile(license_path,output/'NODE-LICENSE');break
    for license_name in ('worker.cjs.LEGAL.txt', 'app-host.js.LEGAL.txt'):
        if (host / license_name).is_file():
            shutil.copyfile(host / license_name, output / license_name)
    manifest = {'schema': 'runteams.managed-mcp/1', 'platform': sys.platform, 'machine': platform.machine(),
        'node_version': version, 'files': {n: sha256((output / n).read_bytes()) for n in (name, 'worker.cjs', 'app-host.js')}}
    raw = canonical(manifest)
    (output / 'runtime.json').write_bytes(raw)
    pin = sha256(raw)
    # The release signs this pin together with the platform resource directory.
    # It is not accepted from employee metadata or a browser request.
    (output / 'runtime.sha256').write_text(pin+'\n')
    ManagedMCPRuntime(output, pin).verify()
    return pin


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--node', required=True, help='Already provisioned and verified release Node executable')
    parser.add_argument('--host', required=True, help='Offline bundled official SDK helper')
    parser.add_argument('--output', required=True, help='New candidate resources directory')
    parser.add_argument('--node-license',help='Original license from the verified Node distribution')
    args = parser.parse_args()
    print(prepare(args.node, args.host, args.output,node_license=args.node_license))
