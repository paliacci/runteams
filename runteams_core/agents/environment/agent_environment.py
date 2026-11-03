"""Workspace environment discovery shared by every Agent CLI.

Only application-owned runtimes are executed during discovery. Project virtual
environments are reported as candidates; inspecting a folder never runs its code.
No downloads, package installation, shell profile edits or global PATH changes.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tomllib

from runteams_core.foundation.resources import root as resource_root

ROOT = resource_root()


def runtime_root():
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent)) / 'agent-python'
    return ROOT / 'runtime-dependencies' / 'agent-python'


def platform_key():
    machine = platform.machine().lower()
    machine = {'aarch64': 'arm64', 'amd64': 'x86_64'}.get(machine, machine)
    return sys.platform + '-' + machine


def payload_files(root):
    """Stable files only; Python may create disposable bytecode caches."""
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if '__pycache__' in path.parts or name in ('runtime.json', 'runtime.sha256'):
            continue
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Python runtime link leaves its directory')
            result[name] = {'link': os.readlink(path)}
        elif path.is_file():
            result[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'bytes': path.stat().st_size}
    return result


@lru_cache(maxsize=4)
def _verified(root, raw, signature):
    manifest = json.loads(raw)
    if payload_files(root) != manifest['files']:
        raise ValueError('Python runtime files changed; prepare the application runtime again')
    return manifest


def verify_runtime(root):
    root = Path(root).absolute()
    raw = (root / 'runtime.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != (root / 'runtime.sha256').read_text().strip():
        raise ValueError('Python runtime manifest checksum mismatch')
    manifest = json.loads(raw)
    if manifest.get('schema') != 'runteams.agent-python/1' or manifest.get('platform') != platform_key():
        raise ValueError('Python runtime platform or format mismatch')
    lock_raw = (ROOT / 'contracts/agent-python.lock.json').read_bytes()
    lock = json.loads(lock_raw)
    if (manifest.get('lock_sha256') != hashlib.sha256(lock_raw).hexdigest()
            or manifest.get('archive_sha256') != lock['assets'][platform_key()]['sha256']
            or manifest.get('version') != lock['version']):
        raise ValueError('Python runtime does not match the application release lock')
    # Stat signatures invalidate the hash cache after replacement or modification.
    signature = []
    for name in manifest.get('files', {}):
        path = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Invalid Python runtime path')
        stat = path.lstat()
        signature.append((name, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    # Include additions, too. Never authorize a newly injected package from cache.
    signature.append(tuple(p.relative_to(root).as_posix() for p in root.rglob('*')
                           if '__pycache__' not in p.parts))
    checked = _verified(str(root), raw, tuple(signature))
    expected_executable = 'python.exe' if os.name == 'nt' else 'bin/python3'
    if checked.get('executable') != expected_executable:
        raise ValueError('Unexpected Python executable path')
    executable = root / checked['executable']
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('Python runtime executable is unavailable')
    return checked


def managed_python():
    root = runtime_root()
    if not root.exists():
        return {'status': 'unavailable', 'source': 'managed', 'reason': 'runtime_not_bundled'}
    try:
        manifest = verify_runtime(root)
        return {'status': 'ready', 'source': 'managed', 'verified': True,
                'executable': str(root / manifest['executable']), 'version': manifest['version'],
                'modules': manifest['modules']}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return {'status': 'error', 'source': 'managed', 'reason': 'runtime_integrity_failed'}


def _small_text(path):
    if path.is_file() and path.stat().st_size <= 128 * 1024:
        return path.read_text(encoding='utf-8')
    return ''


def describe(cwd):
    workspace = Path(cwd).absolute() if cwd else None
    managed = managed_python()
    selected = deepcopy(managed)
    requirement = {}
    if workspace is not None:
        try:
            version = _small_text(workspace / '.python-version').strip()
            project = tomllib.loads(_small_text(workspace / 'pyproject.toml'))
            metadata = project.get('project') or {}
            if not isinstance(metadata, dict):
                raise ValueError('Invalid project metadata')
            requires = metadata.get('requires-python')
            if version:
                requirement['python_version_file'] = version[:240]
            if isinstance(requires, str):
                requirement['requires_python'] = requires[:240]
        except (OSError, ValueError, TypeError, RecursionError):
            requirement['status'] = 'unreadable'
        for name in ('.venv', 'venv'):
            folder = workspace / name
            cfg = folder / 'pyvenv.cfg'
            executable = folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            if not cfg.exists() and not executable.exists():
                continue
            selected = {'status': 'detected' if executable.is_file() and os.access(executable, os.X_OK) else 'unavailable',
                        'source': 'project', 'verified': False, 'environment': str(folder),
                        'reason': 'verify_with_native_shell_before_use'}
            if selected['status'] == 'detected':
                # Retain the venv path: resolving its symlink loses venv identity.
                selected['executable'] = str(executable)
            try:
                for line in _small_text(cfg).splitlines():
                    key, sep, value = line.partition('=')
                    if sep and key.strip() in ('version', 'version_info'):
                        selected['version_hint'] = value.strip()[:80]
            except OSError:
                pass
            break
    if requirement:
        selected['project_compatibility'] = 'unverified'
    return {'schema': 'runteams.workspace-environment/1', 'cwd': str(workspace) if workspace else '',
            'python': selected, 'managed_python': managed, 'project_requirement': requirement}


def execution_env(base_env, cwd, snapshot=None):
    """Child-process additions; native login shell may still reorder PATH."""
    env = dict(base_env)
    if getattr(sys, 'frozen', False):
        # Frozen-app library search paths belong to the backend, not external
        # CLIs or their standalone Python children. Preserve original user paths.
        for key in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
            if key in env and str(getattr(sys, '_MEIPASS', '')) in env[key]:
                original = env.get(key + '_ORIG')
                if original:
                    env[key] = original
                else:
                    env.pop(key, None)
    python = (snapshot if snapshot is not None else describe(cwd))['python']
    executable = python.get('executable')
    if executable and python.get('status') not in ('invalid', 'unavailable', 'error'):
        env['RUNTEAMS_PYTHON'] = executable
        env.pop('PYTHONHOME', None)
        if python.get('environment'):
            env['VIRTUAL_ENV'] = python['environment']
        else:
            env.pop('VIRTUAL_ENV', None)
        env['PATH'] = os.pathsep.join(dict.fromkeys([str(Path(executable).parent)] +
                                      env.get('PATH', '').split(os.pathsep)))
    else:
        env.pop('RUNTEAMS_PYTHON', None)
        if (snapshot or {}).get('binding'):
            env.pop('VIRTUAL_ENV', None)
    return env


def tool(arguments, context):
    from runteams_core.agents.tools import agent_tool_registry as registry
    if arguments:
        raise registry.AgentToolError('环境查询不接受路径或其他参数。')
    snapshot = (context.get('runtime') or {}).get('workspace_environment')
    if not isinstance(snapshot, dict):
        raise registry.AgentToolError('本轮没有已绑定的执行环境，请重新开始工作。')
    identity = None
    if context.get('chat_id'):
        from runteams_core.storage import product_store
        if product_store.device_chat(context['chat_id']):
            from runteams_core.storage import device_data
            identity = device_data.identity()
            if identity.get('storage_kind') == 'local':
                if context.get('library_id') != identity['library_id']:
                    raise PermissionError('本机资料库已变化，请重新开始工作。')
            elif context.get('actor_id') != identity['account_id']:
                raise PermissionError('账户已变化，请重新开始工作。')
        if not product_store.get_chat(context['chat_id'], include_messages=False):
            raise registry.AgentToolError('本轮对话已不可用，请重新开始工作。')
    if snapshot.get('binding'):
        from runteams_core.agents.environment.work_environment import BindingStore
        store = BindingStore.record(snapshot['binding']['record'])
        if store.key != snapshot['binding']['work_key']:
            raise registry.AgentToolError('工作环境绑定身份不一致。')
        result = store.current()
        if snapshot['binding'].get('read_only_state'):
            result['python']['launcher_argv'].append('--read-only-state')
            result['binding']['read_only_state'] = True
    else:
        result = describe(snapshot['cwd'])
    if identity is not None:
        device_data.check(identity)
    return registry.AgentToolResult('environment', '已读取本轮工作目录和 Python 环境。', result)
