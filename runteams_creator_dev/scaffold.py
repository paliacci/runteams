"""Create a standalone workspace from the exported, pristine MCP template."""
import hashlib
from pathlib import Path
import re
import shutil

from runteams_core.authoring.creator_contracts import canonical, relative, strict_json
from .file_copy import copy_new


def inventory(folder):
    return {'schema': 'runteams.devkit-inventory/1', 'files': [
        {'path': p.relative_to(folder).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(folder.rglob('*'))
        if p.is_file() and p.name != 'devkit-inventory.json' and '__pycache__' not in p.parts]}


def initialize(kit, target, key, name):
    from .cli import check, read_source
    kit = Path(kit).resolve()
    workspace = kit.parent
    target = Path(target).absolute()
    if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', key):
        raise ValueError('invalid_project_key')
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise ValueError('invalid_project_name')
    if target.exists() or target.is_symlink():
        raise ValueError('output_exists')
    if target.resolve().is_relative_to(workspace):
        raise ValueError('output_must_be_outside_devkit')
    files = read_source(kit / 'templates/mcp/source')
    project = strict_json(files['project.json']); project.update(key=key, name=name)
    files['project.json'] = canonical(project)
    lock = strict_json(files['dependencies.lock.json']); lock['root'] = key
    files['dependencies.lock.json'] = canonical(lock)
    employee = strict_json(files['employees/main.json']); employee['name'] = name
    files['employees/main.json'] = canonical(employee)
    path='skills/worker/mcp/manifest.json';manifest=strict_json(files[path]);manifest.update(name=key,display_name=name);files[path]=canonical(manifest)
    compiled = check(files)

    return _create(kit,target,files,compiled,imported=False)


def open_archive(kit,archive,target):
    """Continue exact platform-exported source in a new independent workspace."""
    from .archive import inspect_file
    from .cli import check
    files=inspect_file(archive)
    return _create(kit,target,files,check(files),imported=True)


def _create(kit,target,files,compiled,*,imported):
    kit=Path(kit).resolve();workspace=kit.parent;target=Path(target).absolute()
    if target.exists() or target.is_symlink():raise ValueError('output_exists')
    if target.resolve().is_relative_to(workspace):raise ValueError('output_must_be_outside_devkit')
    # Copy only inventoried development tools, never the edited working source,
    # account files, environments, build output, or arbitrary workspace extras.
    manifest = strict_json((workspace / 'devkit-inventory.json').read_bytes())
    if manifest.get('schema') != 'runteams.devkit-inventory/1':
        raise ValueError('invalid_devkit_inventory')
    selected = {}
    allowed = {'runteams.py', 'README.md', 'UIKIT.md', 'requirements.txt', '.gitignore', 'AGENTS.md', 'CLAUDE.md',
               '.agents/skills/runteams-creator/SKILL.md'}
    for entry in manifest['files']:
        path = relative(entry['path'])
        if not (path.startswith('_runteams/') or path in allowed):
            continue
        source = workspace / path
        if path in selected or source.is_symlink() or any(p.is_symlink() for p in source.parents if p != workspace and p.is_relative_to(workspace)):
            raise ValueError('invalid_devkit_path')
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('devkit_integrity:' + path)
        selected[path] = source
    if not allowed.issubset(selected) or '_runteams/toolchain.json' not in selected:
        raise ValueError('incomplete_devkit')
    template_cases = '_runteams/templates/mcp/tests.json'
    if template_cases not in selected:
        raise ValueError('incomplete_template')

    # Validate everything before reserving a new directory. Never overwrite or
    # remove an existing workspace, including on a failed copy.
    target.mkdir(parents=True, exist_ok=False)
    for path, source in selected.items():
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy_new(source, destination)
    for path, body in files.items():
        destination = target / 'source' / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    (target / 'dev').mkdir()
    if imported:
        (target/'dev/tests.json').write_bytes(canonical({'schema':'runteams.mcp-dev-tests/1','cases':[]}))
        original=(target/'README.md').read_text()
        (target/'README.md').write_text('# 从产品继续开发\n\nsource/ 是所选源码包的完整原字节，含锁定依赖和 UI Kit。此工作区不含产品账号、试运行输入、记录或日志。\n\n先按下文准备环境，执行 doctor / check / build。dev/tests.json 未复用模板案例；为当前作品补充实际断言后再运行 test。空案例不会被当成通过。preview 的能力与运行授权见下文；本机 MCP 程序可以访问文件和网络，平台权限与发布须回到产品实际验收。\n\n'+original)
    else:shutil.copy2(selected[template_cases], target / 'dev/tests.json')
    (target / 'devkit-inventory.json').write_bytes(canonical(inventory(target)))
    return {'workspace': str(target), 'template': None if imported else 'mcp', 'source_sha256': compiled['source']['sha256'],
            'next': 'Follow README.md to create the project environment, then doctor, check, test, preview.'}
