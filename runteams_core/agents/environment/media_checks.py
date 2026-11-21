"""Functional device probes. Skill metadata can select a check, never a command."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import wave

from runteams_core.foundation.contracts import ContractError

from runteams_core.assets.skills.skill_metadata import ENVIRONMENT_TOOLS

_cache = {}
_lock = threading.Lock()


def _executable(name):
    directories = ['/opt/homebrew/bin', '/usr/local/bin', *os.get_exec_path()]
    return shutil.which(name, path=os.pathsep.join(p for p in directories if os.path.isabs(p)))


def _probe(name, executable):
    if not executable:
        return 'missing'
    pcm = b'\x18\x01' * 800
    # ffprobe needs a seekable file to report the container duration.
    try:
        with tempfile.TemporaryDirectory(prefix='runteams-media-check-') as folder:
            sample = Path(folder) / 'sample.wav'
            with wave.open(str(sample), 'wb') as wav:
                wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                wav.writeframes(pcm)
            args = (['-nostdin', '-xerror', '-i', str(sample), '-f', 's16le', '-'] if name == 'ffmpeg'
                    else ['-show_entries', 'format=duration', '-of', 'json', str(sample)])
            output = subprocess.run([executable, '-v', 'error', *args], stdin=subprocess.DEVNULL,
                                    capture_output=True, check=True, timeout=5).stdout
            valid = (output == pcm if name == 'ffmpeg' else
                     abs(float(json.loads(output)['format']['duration']) - 0.1) < 0.001)
            return 'ready' if valid else 'failed'
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return 'failed'


def check(data):
    names = data.get('tools')
    if (set(data) != {'tools'} or not isinstance(names, list) or not 1 <= len(names) <= len(ENVIRONMENT_TOOLS)
            or any(n not in ENVIRONMENT_TOOLS for n in names) or len(set(names)) != len(names)):
        raise ContractError('运行环境检查项目无效。')
    result = {}
    with _lock:
        for name in names:
            path = _executable(name)
            try:
                stat = os.stat(path) if path else None
            except OSError:
                stat = None
            stamp = (path, stat and (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size))
            cached = _cache.get(name)
            if cached and cached[0] == stamp and cached[1] > time.monotonic():
                result[name] = cached[2]
            else:
                status = _probe(name, path)
                _cache[name] = (stamp, time.monotonic() + (10 if status == 'ready' else 0), status)
                result[name] = status
    return {'checks': result}
