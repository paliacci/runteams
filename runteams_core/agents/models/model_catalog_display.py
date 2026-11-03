"""Disposable model-menu snapshots. Execution always uses model_channels validation."""
import copy
import json
import os
import threading
import time
from concurrent.futures import Future

from runteams_core.agents.environment import cli_discovery
from runteams_core.agents.models import model_channels

_LOCK = threading.RLock()
_ENTRIES = {}
_RECHECK_SECONDS = 30
_MAX_AGE_SECONDS = 300


def _stamp(path):
    return cli_discovery.executable_stamp(os.path.expanduser(path))


def _profile(channel):
    return model_channels.config_directory(channel)


def _identity(channels, scope):
    files = []
    for channel in channels:
        root = _profile(channel)
        names = ('auth.json', 'config.toml') if channel.get('provider') == 'codex' else ('.credentials.json', 'settings.json', 'settings.local.json')
        files.extend((root + '/' + name, _stamp(root + '/' + name)) for name in names)
        if channel.get('provider') == 'claude-code':
            # Claude may use the macOS login keychain instead of a credentials file.
            files.extend((name, _stamp(name)) for name in ('~/.claude.json', '~/Library/Keychains/login.keychain-db'))
    environment = tuple((name, os.environ.get(name, '')) for name in
                        ('HOME', 'PATH', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'CODEX_BIN', 'CLAUDE_BIN'))
    return (scope, json.dumps(channels, sort_keys=True, separators=(',', ':')), environment, tuple(files))


def invalidate(channel):
    """A confirmed failure in a real probe immediately retires display successes."""
    with _LOCK:
        for entry in _ENTRIES.values():
            if any(item.get('provider') == channel.get('provider') and _profile(item) == _profile(channel)
                   for item in entry['channels']):
                entry['result'] = None
                profile = (channel.get('provider'), _profile(channel))
                entry['invalidations'][profile] = entry['invalidations'].get(profile, 0) + 1


def catalog(channels, scope, *, refresh=False, wait=False):
    channels = copy.deepcopy(channels)
    key = _identity(channels, scope)
    now = time.monotonic()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry and any(_stamp(path) != stamp for path, stamp in entry['binaries']):
            entry = None
            _ENTRIES.pop(key, None)
        age = now - entry['checked'] if entry else float('inf')
        if entry and entry['result'] is not None and age < _RECHECK_SECONDS and not refresh and not wait:
            return copy.deepcopy(dict(entry['result'], cached=True, revalidating=False))
        if not entry:
            # Old identities cannot be looked up again; bound their retention.
            for old in list(_ENTRIES):
                if (old[0] == scope and _ENTRIES[old]['future'].done()
                        and {row.get('id') for row in _ENTRIES[old]['channels']} == {row.get('id') for row in channels}):
                    _ENTRIES.pop(old)
            if len(_ENTRIES) >= 32:
                for old in list(_ENTRIES):
                    if _ENTRIES[old]['future'].done():
                        _ENTRIES.pop(old)
                        break
                if len(_ENTRIES) >= 32:
                    raise RuntimeError('模型目录正在更新，请稍后重试。')
            entry = {'channels': channels, 'result': None, 'checked': 0, 'binaries': [], 'future': Future(), 'invalidations': {}}
            _ENTRIES[key] = entry
            start = True
        else:
            start = entry['future'].done() and (refresh or entry['result'] is None or age >= _RECHECK_SECONDS)
            if start:
                entry['future'] = Future()
        future = entry['future']
        if start:
            expected_binaries = tuple(entry['binaries'])
            expected_invalidations = dict(entry['invalidations'])
            def load():
                try:
                    result = model_channels.global_catalog(channels, refresh=True)
                    binaries = []
                    for channel in channels:
                        if channel.get('enabled', 1):
                            path = cli_discovery.cached_display_executable(channel.get('provider'), channel.get('executable') or '')
                            if path:
                                binaries.append((path, _stamp(path)))
                    if _identity(channels, scope) != key or any(_stamp(path) != stamp for path, stamp in expected_binaries):
                        raise RuntimeError('模型渠道配置已改变，请重新读取。')
                    with _LOCK:
                        for row in result['channels']:
                            channel = next((item for item in channels if item.get('id') == row.get('channel_id')), None)
                            if channel and row.get('status') == 'ready':
                                profile = (channel.get('provider'), _profile(channel))
                                if entry['invalidations'].get(profile, 0) != expected_invalidations.get(profile, 0):
                                    raise RuntimeError('模型渠道状态已改变，请重新读取。')
                        entry.update(result=result, checked=time.monotonic(), binaries=binaries)
                    future.set_result(result)
                except Exception as error:
                    with _LOCK:
                        entry['result'] = None
                    future.set_exception(error)
            threading.Thread(target=load, name='model-menu-refresh', daemon=True).start()
        if not refresh and not wait and entry['result'] is not None and age < _MAX_AGE_SECONDS:
            return copy.deepcopy(dict(entry['result'], cached=True, revalidating=not future.done()))
    # First read, changed credentials/binary, explicit refresh, or an old snapshot
    # needs an actual result. Concurrent reads join the same native query.
    return copy.deepcopy(dict(future.result(timeout=30), cached=False, revalidating=False))
