"""Host-only discovery of official Agent CLIs, shared by settings and execution.

Only verified locations are cached in memory. No credentials, login or business
state are inferred from discovery, and no model requests are sent.
"""
import ctypes
import glob
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from runteams_core.agents.environment import cli_compatibility

_PROVIDERS = {
    'codex': ('codex', 'CODEX_BIN', 'Codex', ('com.openai.codex', 'com.openai.chat')),
    'claude-code': ('claude', 'CLAUDE_BIN', 'Claude Code', ('com.anthropic.claudefordesktop',)),
}
_CACHE = {}
_DISPLAY_PATHS = {}
_LOCKS = {provider: threading.RLock() for provider in _PROVIDERS}
_CACHE_SECONDS = 30
_DISCOVERY_SECONDS = 8
_COMMAND_SECONDS = 2


class DiscoveryError(RuntimeError):
    def __init__(self, message, *, status='error', installed=False, executable=''):
        super().__init__(message)
        self.status, self.installed, self.executable = status, installed, executable


def _absolute(value):
    value = os.path.expanduser(str(value or '').strip())
    return os.path.abspath(value) if value and os.path.isabs(value) else ''


def executable_stamp(path):
    try:
        stat = os.stat(path)
        link = os.lstat(path)
        return (os.path.realpath(path), stat.st_dev, stat.st_ino, stat.st_size,
                stat.st_mtime_ns, stat.st_ctime_ns, link.st_mtime_ns, stat.st_mode)
    except OSError:
        return None


def _path_parts(value):
    # Empty/relative PATH entries must not make the current project a CLI source.
    return list(dict.fromkeys(p for p in str(value or '').split(os.pathsep)
                              if p and os.path.isabs(p)))


def _tool_dirs():
    common = ['~/.local/bin', '~/.npm-global/bin', '~/.volta/bin', '~/.asdf/shims',
              '~/.local/share/mise/shims', '/opt/homebrew/bin', '/usr/local/bin']
    if os.name == 'nt':
        common += [os.path.join(os.environ.get('APPDATA', ''), 'npm')]
    return [os.path.expanduser(p) for p in common if os.path.isabs(os.path.expanduser(p))]


def _versioned_dirs():
    # Bounded installation directories, never a scan of the user's disk.
    result = []
    for pattern in ['~/.nvm/versions/node/*/bin', '~/.local/share/fnm/node-versions/*/installation/bin',
                    '~/Library/Application Support/fnm/node-versions/*/installation/bin',
                    '~/.local/share/mise/installs/node/*/bin', '~/.asdf/installs/nodejs/*/bin']:
        found = glob.glob(os.path.expanduser(pattern))
        result.extend(sorted(found, key=lambda p: (executable_stamp(p) or ('', 0, 0, 0, 0))[4],
                             reverse=True)[:16])
    return result


def _registered_apps(identifiers):
    """Read LaunchServices directly; no Spotlight index or scripting permission."""
    if sys.platform != 'darwin':
        return []
    result = []
    try:
        cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        ls = ctypes.CDLL('/System/Library/Frameworks/CoreServices.framework/CoreServices')
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]; cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFURLGetFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p, ctypes.c_long]
        cf.CFURLGetFileSystemRepresentation.restype = ctypes.c_bool
        cf.CFRelease.argtypes = [ctypes.c_void_p]; cf.CFRelease.restype = None
        ls.LSCopyApplicationURLsForBundleIdentifier.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        ls.LSCopyApplicationURLsForBundleIdentifier.restype = ctypes.c_void_p
        for identifier in identifiers:
            key = cf.CFStringCreateWithCString(None, identifier.encode(), 0x08000100)
            if not key:
                continue
            try:
                array = ls.LSCopyApplicationURLsForBundleIdentifier(key, None)
                if not array:
                    continue
                try:
                    for index in range(min(cf.CFArrayGetCount(array), 12)):
                        url = cf.CFArrayGetValueAtIndex(array, index)
                        buffer = ctypes.create_string_buffer(4096)
                        if cf.CFURLGetFileSystemRepresentation(url, True, buffer, len(buffer)):
                            result.append(os.fsdecode(buffer.value))
                finally:
                    cf.CFRelease(array)
            finally:
                cf.CFRelease(key)
    except (OSError, AttributeError, ValueError):
        pass
    return list(dict.fromkeys(result))


def _bundle_candidates(app, binary):
    root = Path(app) / 'Contents'
    resources = root / 'Resources'
    # Fast paths are hints; bounded traversal below handles future bundle layouts.
    for path in [resources / 'codex-cli/CodexCLI.app/Contents/MacOS' / binary,
                 resources / binary, root / 'MacOS' / binary]:
        yield str(path)
    seen = 0
    if not resources.is_dir():
        return
    for current, directories, files in os.walk(resources, followlinks=False):
        seen += 1
        if seen > 96:
            break
        depth = len(Path(current).relative_to(resources).parts)
        directories[:] = sorted(d for d in directories if depth < 6 and
                                 not d.startswith('.') and d not in ('node_modules', 'Frameworks', 'assets', 'locales'))[:32]
        if binary in files:
            yield os.path.join(current, binary)
        if 'Info.plist' in files and Path(current).name == 'Contents':
            try:
                with open(os.path.join(current, 'Info.plist'), 'rb') as handle:
                    name = plistlib.load(handle).get('CFBundleExecutable', '')
                if name and os.path.basename(name) == name and binary in name.lower():
                    yield os.path.join(current, 'MacOS', name)
            except (OSError, ValueError, plistlib.InvalidFileException):
                pass


def _command(argv, env, timeout, cwd=None):
    # Private files bound output memory and keep shell startup chatter/CLI logs
    # out of public diagnostics. Kill the whole probe group on timeout.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=(os.name != 'nt'))
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name != 'nt':
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            else:
                process.kill()
            process.wait()
            raise
        output.seek(0)
        text = output.read(65536).decode('utf-8', errors='replace')
        return subprocess.CompletedProcess(argv, process.returncode, text, '')


def _login_shell(deadline):
    if os.name == 'nt' or time.monotonic() >= deadline:
        return {}, []
    try:
        import pwd
        shell = pwd.getpwuid(os.getuid()).pw_shell
        if os.path.basename(shell) not in ('zsh', 'bash', 'sh', 'fish'):
            return {}, []
        marker = '__RUNTEAMS_' + uuid.uuid4().hex + '__'
        command = ("printf '\\n{m}\\n'; command -v codex; printf '\\n{m}\\n'; "
                   "command -v claude; printf '\\n{m}\\n%s\\n{m}\\n' \"$PATH\"").format(m=marker)
        result = _command([shell, '-ilc', command], os.environ.copy(),
                          min(2, max(.05, deadline - time.monotonic())), str(Path.home()))
        fields = result.stdout.split(marker)
        if len(fields) != 5:
            return {}, []
        commands = {}
        for name, value in zip(('codex', 'claude'), fields[1:3]):
            lines = value.strip().splitlines()
            if len(lines) == 1 and _absolute(lines[0]):
                commands[name] = _absolute(lines[0])
        return commands, _path_parts(fields[3].strip())
    except (OSError, subprocess.TimeoutExpired, KeyError):
        return {}, []


def execution_env(provider, executable, base_env):
    """Keep native configuration; expose the selected CLI's companion toolchain."""
    env = dict(base_env)
    key = _cache_key(provider)
    cached = _CACHE.get(key) or {}
    selected = _absolute(executable) or cached.get('path', '')
    additions = []
    if selected:
        additions.append(os.path.dirname(selected))
        # Keep the symlink's bin directory (npm's node lives beside the symlink).
        additions.extend(cached.get('extra_path', []))
    additions.extend(_tool_dirs())
    env['PATH'] = os.pathsep.join(dict.fromkeys(additions + _path_parts(env.get('PATH', ''))))
    return env


def _cache_key(provider):
    entry = _PROVIDERS[provider]
    return (provider, str(Path.home()), os.environ.get('PATH', ''), os.environ.get(entry[1], ''))


def _fingerprint(path, env):
    node = shutil.which('node', path=env.get('PATH', ''))
    return (executable_stamp(path), node, executable_stamp(node) if node else None)


def _verify(provider, path, env, deadline):
    label = _PROVIDERS[provider][2]
    if not os.path.isfile(path):
        return None
    if not os.access(path, os.X_OK):
        raise DiscoveryError(f'{label} 运行程序无法执行，请检查文件权限后重新连接。', installed=True, executable=path)
    def run(argv, _env, timeout=8):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DiscoveryError(f'{label} 运行程序检测超时，请稍后重新连接。',
                                 installed=True, executable=path)
        try:
            return _command(argv, _env, min(timeout, _COMMAND_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            raise DiscoveryError(f'{label} 运行程序检测超时，请稍后重新连接。',
                                 installed=True, executable=path) from None
        except OSError:
            raise DiscoveryError(f'{label} 运行程序启动失败，请修复安装后重新连接。',
                                 installed=True, executable=path) from None
    try:
        version = run([path, '--version'], env)
        signature = r'\bcodex(?:-cli)?\s+\d' if provider == 'codex' else r'\bClaude Code\b'
        if version.returncode != 0 or not re.search(signature, version.stdout, re.I):
            raise DiscoveryError(f'{label} 运行程序启动失败，请修复安装后重新连接。', installed=True, executable=path)
        compatibility = cli_compatibility.check(provider, path, env, run=run)
        if not compatibility['compatible']:
            raise DiscoveryError(f'{label} 版本暂不兼容，请更新官方程序后重新连接。',
                                 status='incompatible', installed=True, executable=path)
    except (OSError, subprocess.TimeoutExpired) as exc:
        message = (f'{label} 运行程序检测超时，请稍后重新连接。' if isinstance(exc, subprocess.TimeoutExpired)
                   else f'{label} 运行程序启动失败，请修复安装后重新连接。')
        raise DiscoveryError(message, installed=True, executable=path) from None
    return path


def cached_display_executable(provider, explicit=''):
    """Reuse a verified command path for display only; never authorize execution."""
    if provider not in _PROVIDERS:
        return ''
    # A display read must not queue behind native discovery's long-running lock.
    # Retain the last verified immutable record while discovery replaces _CACHE.
    key = _cache_key(provider)
    cached = _CACHE.get(key) or _DISPLAY_PATHS.get(key)
    configured = str(explicit or os.environ.get(_PROVIDERS[provider][1], '')).strip()
    if cached and (not configured or _absolute(configured) == cached['path']):
        env = execution_env(provider, cached['path'], os.environ)
        env['PATH'] = os.pathsep.join(dict.fromkeys([os.path.dirname(cached['path'])] +
            list(cached.get('extra_path', [])) + _path_parts(env.get('PATH', ''))))
        if os.access(cached['path'], os.X_OK) and cached['fingerprint'] == _fingerprint(cached['path'], env):
            return cached['path']
    return ''


def resolve(provider, explicit='', refresh=False):
    if provider not in _PROVIDERS:
        raise ValueError('Unsupported Agent CLI')
    binary, override, label, identifiers = _PROVIDERS[provider]
    key = _cache_key(provider)
    with _LOCKS[provider]:
        configured = str(explicit or os.environ.get(override, '')).strip()
        cached = _CACHE.get(key)
        if cached and not refresh and (not configured or _absolute(configured) == cached['path']):
            env = execution_env(provider, cached['path'], os.environ)
            if (time.monotonic() - cached['checked'] < _CACHE_SECONDS and
                    os.access(cached['path'], os.X_OK) and
                    cached['fingerprint'] == _fingerprint(cached['path'], env)):
                return cached['path']
        _CACHE.pop(key, None)
        deadline = time.monotonic() + _DISCOVERY_SECONDS
        seen, failures = set(), []
        def attempt(candidate, extra=()):
            path = _absolute(candidate)
            identity = (path, tuple(extra))
            if not path or identity in seen or time.monotonic() >= deadline:
                return None
            seen.add(identity)
            env = execution_env(provider, path, os.environ)
            env['PATH'] = os.pathsep.join(dict.fromkeys([os.path.dirname(path)] + list(extra) + _path_parts(env['PATH'])))
            try:
                found = _verify(provider, path, env, deadline)
            except DiscoveryError as exc:
                failures.append(exc)
                return None
            if found:
                _CACHE[key] = {'path': found, 'checked': time.monotonic(), 'extra_path': list(extra),
                               'fingerprint': _fingerprint(found, env)}
                _DISPLAY_PATHS[key] = _CACHE[key]
                if len(_DISPLAY_PATHS) > 32:
                    _DISPLAY_PATHS.pop(next(iter(_DISPLAY_PATHS)))
            return found
        if configured:
            found = attempt(configured)
            if found:
                return found
            if failures:
                raise failures[0]
            raise DiscoveryError(f'配置的 {label} 路径不可用，请检查 {override} 或移除该覆盖后重新连接。')
        for directory in _path_parts(os.environ.get('PATH', '')) + _tool_dirs():
            found = attempt(shutil.which(binary, path=directory) or os.path.join(directory, binary))
            if found:
                return found
        # Preserve fast desktop hints, then use the OS registry for moved/renamed apps.
        apps = []
        if sys.platform == 'darwin':
            names = ('Codex.app', 'ChatGPT.app') if provider == 'codex' else ('Claude.app',)
            for root in ('/Applications', os.path.expanduser('~/Applications')):
                apps.extend(os.path.join(root, name) for name in names)
            for app in apps:
                for candidate in _bundle_candidates(app, binary):
                    found = attempt(candidate)
                    if found:
                        return found
            for app in _registered_apps(identifiers):
                if app in apps:
                    continue
                for candidate in _bundle_candidates(app, binary):
                    found = attempt(candidate)
                    if found:
                        return found
        # Recover the user's selected version-manager CLI before examining other versions.
        commands, shell_path = _login_shell(deadline)
        found = attempt(commands.get(binary), shell_path)
        if found:
            return found
        for directory in shell_path + _versioned_dirs():
            found = attempt(shutil.which(binary, path=directory) or os.path.join(directory, binary), shell_path)
            if found:
                return found
        if failures:
            raise next((e for e in failures if e.status == 'incompatible'), failures[0])
        if time.monotonic() >= deadline:
            raise DiscoveryError(f'{label} 自动检测超时，请稍后重新连接。')
        raise DiscoveryError(f'未检测到可用的 {label} 运行程序。请确认已安装，然后重新连接。', status='missing')
