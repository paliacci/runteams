"""The core CI entry: source boundary, deterministic wheel and installed mainline."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from .build_wheel import ROOT, build
from .check_source import check
from .check_repository import check as check_repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sdk-tsc', type=Path, help='Run packed SDK client checks using this installed tsc JS entry.')
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)
    from .command_inventory import inventory
    if json.loads((ROOT / 'tooling/commands.json').read_text()) != inventory(ROOT, 'runteams_core'):
        raise ValueError('Canonical command inventory changed')
    report = {'repository': check_repository(ROOT, 'runteams_core'),
              'source': check(), 'core_build': build(output / 'wheels')}
    interpreter = output / 'environment' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    subprocess.run([sys.executable, '-m', 'venv', str(output / 'environment')], check=True)
    wheel = next((output / 'wheels').glob('runteams_core-*.whl'))
    subprocess.run([str(interpreter), '-I', '-m', 'pip', 'install', str(wheel)], check=True)
    subprocess.run([str(interpreter), '-I', '-B', '-m', 'runteams_core.devtools.verify_install'], cwd=output, check=True)
    subprocess.run([str(interpreter), '-I', '-B', '-m', 'unittest', 'discover', '-s',
                    str(ROOT / 'tests'), '-p', 'test_pdf_attachments.py'], cwd=output, check=True)
    report['pdf_attachment_tests'] = True
    subprocess.run([str(interpreter), '-I', '-B', '-m', 'unittest', 'discover', '-s',
                    str(ROOT / 'tests'), '-p', 'test_repository_hygiene.py'], cwd=output, check=True)
    report['repository_hygiene_tests'] = True
    subprocess.run([str(interpreter), '-I', '-B', '-m', 'unittest', 'discover', '-s',
                    str(ROOT / 'tests'), '-p', 'test_tool_transport.py'], cwd=output, check=True)
    report['canonical_tool_transport'] = True
    subprocess.run([sys.executable, '-B', '-m', 'runteams_core.devtools.build_creator_sdk', '--check'], cwd=ROOT, check=True)
    if args.sdk_tsc:
        subprocess.run([sys.executable, '-B', '-m', 'runteams_core.devtools.check_creator_sdk', '--output',
                        str(output / 'sdk-clients'), '--tsc', str(args.sdk_tsc.absolute())], cwd=ROOT, check=True)
        report['packed_sdk_clients'] = True
    report['installed_mainline'] = True
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
