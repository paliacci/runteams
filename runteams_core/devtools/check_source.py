"""Check the maintained standalone source/module boundary without starting work."""
from runteams_core.devtools.source_root import root as source_root
import ast
import json
from pathlib import Path
import tomllib

ROOT = source_root()
PRIVATE = {'account_auth', 'account_preferences', 'app', 'app_update', 'edition', 'core_api',
           'core_protocol_mcp', 'employee_sessions', 'execution_backend', 'chat', 'scheduler', 'sparkle_bridge'}
EXCLUDED = {'.git', '.venv', 'build', 'dist', 'node_modules', '__pycache__', '.dependencies', '.build'}


def check(root=ROOT):
    root = Path(root)
    findings = []
    files = []
    for path in root.rglob('*.py'):
        if any(part in EXCLUDED or part.endswith('.egg-info') for part in path.relative_to(root).parts):
            continue
        files.append(path)
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or '']
            for name in names:
                if name.split('.')[0] in PRIVATE | {'runteams_official'} or (name.split('.')[0] == 'scripts' and path.relative_to(root).parts[0] in {'runteams_core','runteams_creator_dev'}):
                    findings.append({'source': path.relative_to(root).as_posix(), 'line': node.lineno, 'import': name})
    if (root / 'scripts').exists():
        findings.append({'old_entry_directory': 'scripts'})
    config = tomllib.loads((root / 'pyproject.toml').read_text())
    if set(config['project']['scripts']) != {'runteams-community'}:
        findings.append({'product_entries': config['project']['scripts']})
    if findings:
        raise ValueError(json.dumps(findings, ensure_ascii=False))
    return {'python_sources': len(files), 'private_imports': 0, 'old_script_entries': 0}


if __name__ == '__main__':
    print(json.dumps(check()))
