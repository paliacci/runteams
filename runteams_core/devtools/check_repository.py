"""Check tracked project files, documentation links and canonical tool ownership."""
import argparse
import json
from pathlib import Path
import re
import subprocess


REQUIRED = ('README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'LICENSE',
            'CHANGELOG.md', 'docs/architecture.md', 'docs/development.md',
            'docs/releasing.md', '.github/PULL_REQUEST_TEMPLATE.md',
            '.github/ISSUE_TEMPLATE/bug_report.yml', 'tooling/commands.json')
GENERATED = {'node_modules', '__pycache__', '.venv', '.dependencies', '.temp',
             '.pytest_cache', '.ruff_cache', 'playwright-report', 'test-results'}
PRIVATE_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.p12', '.pfx', '.p8',
                    '.key', '.mobileprovision', '.pyc', '.dmg', '.log'}
SOURCE_SUFFIXES = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.sh'}


def check(root, namespace):
    from .command_inventory import inventory
    root = Path(root).resolve()
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')
    names = [name for name in names if name]
    tracked = set(names)
    findings = []
    folded = {}
    for name in names:
        relative = Path(name)
        path = root / relative
        if not path.is_file() or path.is_symlink():
            findings.append({'path': name, 'reason': 'missing tracked file or source symlink'})
            continue
        if (set(relative.parts) & GENERATED or relative.parts[0] in {'build', 'dist', 'design'}
                or any(part.endswith(('.egg-info', '.app')) for part in relative.parts)
                or relative.suffix in PRIVATE_SUFFIXES
                or (relative.name.startswith('.env') and relative.name != '.env.example')
                or relative.name == '.DS_Store'):
            findings.append({'path': name, 'reason': 'generated output or private local file'})
        key = name.casefold()
        if key in folded:
            findings.append({'path': name, 'reason': 'case-insensitive path collision', 'other': folded[key]})
        folded[key] = name
        if relative.suffix in SOURCE_SUFFIXES:
            text = path.read_text(errors='replace')
            if re.search(r'/Users/[^/\s]+/(?:solo|Desktop|Downloads)/', text):
                findings.append({'path': name, 'reason': 'personal-machine path in maintained source'})
    for name in REQUIRED:
        if name not in tracked:
            findings.append({'path': name, 'reason': 'missing project documentation or contributor entry'})
    for name in ['README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md',
                 'docs/architecture.md', 'docs/development.md', 'docs/releasing.md']:
        path = root / name
        if not path.is_file():
            continue
        for target in re.findall(r'\[[^\]\n]+\]\(([^)\s]+)\)', path.read_text()):
            if target.startswith(('#', 'https://', 'http://', 'mailto:')):
                continue
            destination = (path.parent / target.split('#')[0]).resolve()
            if not destination.is_relative_to(root) or not destination.exists():
                findings.append({'path': name, 'reason': 'broken or external local documentation link', 'target': target})
    command_file = root / 'tooling/commands.json'
    if command_file.exists() and json.loads(command_file.read_text()) != inventory(root, namespace):
        findings.append({'path': 'tooling/commands.json', 'reason': 'tool inventory differs from maintained modules'})
    if findings:
        raise ValueError(json.dumps(findings, ensure_ascii=False))
    return {'tracked_files': len(names), 'namespace': namespace, 'repository_hygiene': 'passed',
            'documentation_links': 'passed', 'canonical_tool_inventory': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--namespace', required=True, choices=['runteams_core', 'runteams_official'])
    args = parser.parse_args()
    print(json.dumps(check(args.root, args.namespace)))


if __name__ == '__main__':
    main()
