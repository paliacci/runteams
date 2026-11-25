"""Build the per-user Windows x64 installer for RunTeams Local."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from runteams_core.devtools.community_source import load_contract
from runteams_core.devtools.prepare_agent_python import prepare, seal_runtime, stage
from desktop.community.sdk_resources import snapshot as sdk_snapshot, stage as stage_sdk

WEBVIEW_VERSION = '1.0.4370.26'
WEBVIEW_SHA256 = '1c0dacac84b70109b3fd42f90c53a0ba942abc3a87590d7a4e0ccd86e4a06cf4'


def compile_host(payload, package):
    if hashlib.sha256(package.read_bytes()).hexdigest() != WEBVIEW_SHA256:
        raise ValueError('Unexpected WebView2 SDK checksum')
    with ZipFile(package) as sdk:
        assemblies = ['Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll']
        for assembly in assemblies:
            (payload / assembly).write_bytes(sdk.read('lib/net462/' + assembly))
        loader = 'WebView2Loader.dll'
        (payload / loader).write_bytes(sdk.read('runtimes/win-x64/native/' + loader))
        (payload / 'WebView2-LICENSE.txt').write_bytes(sdk.read('LICENSE.txt'))
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([compiler, '/nologo', '/codepage:65001', '/target:winexe', '/platform:x64', '/optimize+',
                    '/out:RunTeamsLocal.exe', '/reference:System.Windows.Forms.dll',
                    '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll',
                    *['/reference:' + name for name in assemblies], HERE / 'RunTeamsLocal.cs',
                    HERE / 'AttachmentPicker.cs'],
                   cwd=payload, check=True)


def build(args):
    if sys.platform != 'win32' or struct.calcsize('P') != 8 or sys.version_info[:2] != (3, 12):
        raise ValueError('Use a Windows x64 Python 3.12 build environment')
    contract = load_contract(ROOT)
    sdk = sdk_snapshot(args.creator_builder, args.mcp_runtime)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rt-build-') as temp:
        scratch = Path(temp)
        payload = scratch / 'app'
        core = payload / 'core'
        for dest, names in [(core, contract['runtime_sources'] + contract['runtime_assets']),
                            (payload, contract['notices'])]:
            for name in names:
                target = dest / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
        runtime = core / 'runtime-dependencies/agent-python'
        runtime.parent.mkdir()
        if args.runtime:
            stage(args.runtime, runtime)
        else:
            prepare(runtime)
        stage_sdk(core, sdk, signer=None)
        packages = payload / 'python-packages'
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                        '--no-compile', '--target', packages, '-r', ROOT / 'requirements/runtime.txt'],
                       check=True)
        site = runtime / 'Lib/site-packages'
        (site / 'runteams-application.pth').write_text(
            '\n'.join(os.path.relpath(path, site) for path in (core, packages)) + '\n',
            encoding='ascii')
        seal_runtime(runtime)
        python = runtime / 'python.exe'
        subprocess.run([python, '-I', '-B', '-X', 'utf8', '-c',
                        'import pyvips, pypdfium2, yaml, jsonschema; '
                        'from runteams_core.application import community; '
                        'from runteams_core.agents.environment.agent_environment import managed_python; '
                        'assert managed_python()["status"] == "ready"'], cwd=scratch, check=True)
        package = args.webview_sdk
        if package is None:
            package = scratch / 'webview2.nupkg'
            url = ('https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/'
                   f'{WEBVIEW_VERSION}/microsoft.web.webview2.{WEBVIEW_VERSION}.nupkg')
            with urlopen(url, timeout=60) as source, package.open('xb') as target:
                shutil.copyfileobj(source, target)
        compile_host(payload, package)
        doctor = subprocess.run([payload / 'RunTeamsLocal.exe', '--sdk', 'doctor'], cwd=scratch,
                                check=True, capture_output=True, timeout=60)
        if json.loads(doctor.stdout).get('ok') is not True:
            raise ValueError('Packaged SDK doctor failed')
        version = (ROOT / 'VERSION').read_text(encoding='ascii').strip()
        subprocess.run([args.iscc, '/Qp', '/DAppVersion=' + version, '/DPayload=' + str(payload),
                        '/DDestination=' + str(scratch), HERE / 'installer.iss'], check=True)
        installer = scratch / f'RunTeams-Local-{version}-windows-x64-setup.exe'
        # Publish only the completed installer, also across volumes.
        with tempfile.NamedTemporaryFile(dir=output, delete=False) as target:
            pending = Path(target.name)
        try:
            shutil.copyfile(installer, pending)
            pending.replace(output / installer.name)
        finally:
            pending.unlink(missing_ok=True)
        return output / installer.name


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, help='Verified prepare_agent_python output')
    parser.add_argument('--webview-sdk', type=Path, help='Cached pinned WebView2 NuGet package')
    parser.add_argument('--creator-builder', type=Path, help='Verified Windows creator-builder directory')
    parser.add_argument('--mcp-runtime', type=Path, help='Verified Windows managed MCP runtime directory')
    parser.add_argument('--iscc', default='ISCC.exe', help='Inno Setup 6 compiler')
    print(build(parser.parse_args()))
