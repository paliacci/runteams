"""List canonical development commands and enforce one owning Python package."""
import argparse
import ast
import json
from pathlib import Path


def inventory(root, namespace):
    result = []
    folder = root / namespace / 'devtools'
    for path in sorted(folder.iterdir()):
        if path.suffix not in {'.py', '.cjs', '.mjs'} or path.name == '__init__.py':
            continue
        executable = path.suffix != '.py'
        description = ''
        if path.suffix == '.py':
            tree = ast.parse(path.read_text())
            description = (ast.get_docstring(tree) or '').split('\n')[0]
            executable = any(isinstance(node, ast.If) and '__name__' in ast.unparse(node.test) for node in tree.body)
        result.append({'path': path.relative_to(root).as_posix(),
                       'module': namespace + '.devtools.' + path.stem if path.suffix == '.py' else None,
                       'command': executable, 'description': description})
    return {'schema': 'runteams.development-commands/1', 'namespace': namespace, 'entries': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--namespace', choices=['runteams_core', 'runteams_official'], required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = args.root.absolute()
    if (root / 'scripts').exists():
        raise ValueError('Retired scripts/ command directory is present')
    result = inventory(root, args.namespace)
    target = root / 'tooling/commands.json'
    if args.check:
        if json.loads(target.read_text()) != result:
            raise ValueError('Regenerate the canonical command inventory')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'canonical_commands_and_helpers': len(result['entries']), 'old_command_directory': False}))


if __name__ == '__main__':
    main()
