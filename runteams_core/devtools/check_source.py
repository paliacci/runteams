"""Check the maintained standalone source/module boundary without starting work."""
from runteams_core.devtools.source_root import root as source_root
import ast
import json
from pathlib import Path
import tomllib
from importlib.util import resolve_name

ROOT = source_root()
PRIVATE = {'account_auth', 'account_preferences', 'app', 'app_update', 'edition', 'core_api',
           'core_protocol_mcp', 'employee_sessions', 'execution_backend', 'chat', 'scheduler', 'sparkle_bridge'}
EXCLUDED = {'.git', '.venv', 'build', 'dist', 'node_modules', '__pycache__', '.dependencies', '.build'}


def module_path(root, module):
    base = root / module.replace('.', '/')
    return base.with_suffix('.py').is_file() or (base / '__init__.py').is_file()


def package_symbols(root, module):
    path = root / module.replace('.', '/') / '__init__.py'
    if not path.is_file():
        return None
    names = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return names


def check(root=ROOT):
    root = Path(root)
    from .check_ui_boundary import check as check_ui
    ui = check_ui(root)
    findings = []
    files = []
    internal_names = {path.stem for path in (root / 'runteams_core').rglob('*.py') if path.name != '__init__.py'}
    for path in root.rglob('*.py'):
        if any(part in EXCLUDED or part.endswith('.egg-info') for part in path.relative_to(root).parts):
            continue
        files.append(path)
        package = '.'.join(path.relative_to(root).parent.parts)
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if node.level:
                    module = resolve_name('.' * node.level + module, package)
                names = [module]
                if module.startswith('runteams_core'):
                    symbols = package_symbols(root, module)
                    if symbols is not None:
                        for alias in node.names:
                            if alias.name != '*' and alias.name not in symbols and not module_path(root, module + '.' + alias.name):
                                findings.append({'source': path.relative_to(root).as_posix(), 'line': node.lineno,
                                                 'missing_core_member': module + '.' + alias.name})
            for name in names:
                if name.split('.')[0] in internal_names:
                    findings.append({'source': path.relative_to(root).as_posix(), 'line': node.lineno,
                                     'unqualified_core_import': name})
                if (name == 'runteams_core' or name.startswith('runteams_core.')) and not module_path(root, name):
                    findings.append({'source': path.relative_to(root).as_posix(), 'line': node.lineno,
                                     'missing_core_module': name})
                if name.split('.')[0] in PRIVATE | {'runteams_official'} or (name.split('.')[0] == 'scripts' and path.relative_to(root).parts[0] in {'runteams_core','runteams_creator_dev'}):
                    findings.append({'source': path.relative_to(root).as_posix(), 'line': node.lineno, 'import': name})
    if (root / 'scripts').exists():
        findings.append({'old_entry_directory': 'scripts'})
    config = tomllib.loads((root / 'pyproject.toml').read_text())
    if set(config['project']['scripts']) != {'runteams-community'}:
        findings.append({'product_entries': config['project']['scripts']})
    if findings:
        raise ValueError(json.dumps(findings, ensure_ascii=False))
    return {'python_sources': len(files), 'private_imports': 0, 'old_script_entries': 0, 'ui_boundary': ui}


if __name__ == '__main__':
    print(json.dumps(check()))
