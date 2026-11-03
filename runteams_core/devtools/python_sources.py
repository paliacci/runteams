"""Project canonical account-free Python sources into an offline developer kit."""
import ast
from importlib.util import resolve_name
from pathlib import Path


def module_file(root, module):
    for name in (module.replace('.', '/') + '.py', module.replace('.', '/') + '/__init__.py'):
        if (root / name).is_file():
            return name
    return None


def closure(root, seeds):
    root = Path(root)
    pending, selected = list(seeds), set()
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        source = root / name
        if source.is_symlink() or not source.is_file():
            raise ValueError('Missing canonical SDK source: ' + name)
        selected.add(name)
        package = '.'.join(Path(name).parent.parts)
        for node in ast.walk(ast.parse(source.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [entry.name for entry in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if node.level:
                    module = resolve_name('.' * node.level + module, package)
                modules = [module] + [module + '.' + entry.name for entry in node.names]
            for module in modules:
                if module == 'runteams_official' or module.startswith('runteams_official.'):
                    raise ValueError('Private source in SDK closure: ' + module)
                target = module_file(root, module)
                if target:
                    pending.append(target)
                    parts = Path(target).parts[:-1]
                    for i in range(1, len(parts) + 1):
                        init = Path(*parts[:i]) / '__init__.py'
                        if (root / init).is_file():
                            pending.append(init.as_posix())
                elif module.startswith(('runteams_core.', 'runteams_creator_dev.')):
                    # Imported attributes are not separate modules; their parent must exist.
                    if not module_file(root, module.rsplit('.', 1)[0]):
                        raise ValueError('Unresolved SDK module: ' + module)
    return sorted(selected)


def developer_sources(root):
    from runteams_core.authoring.creator_definitions import compiler_identity
    from runteams_core.authoring.workers.creator_worker_process import WORKERS
    seeds = ['runteams_creator_dev/' + p.name for p in (Path(root) / 'runteams_creator_dev').glob('*.py')]
    seeds += ['runteams_core/' + name for name in compiler_identity()['implementation']]
    seeds = [str(Path(name)) if '..' not in Path(name).parts else
             (Path(root) / name).resolve().relative_to(Path(root).resolve()).as_posix() for name in seeds]
    seeds += ['runteams_core/' + name for name in WORKERS.values()]
    return closure(Path(root), seeds)
