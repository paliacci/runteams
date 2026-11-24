"""Disposable first-role display rows. Creation still resolves the exact employee pin."""
from functools import cache
import hashlib
import json
import os
from pathlib import Path
import sys

from runteams_core.storage.device_files import _publish, _raw
from runteams_core.storage.local_library import private_directory

_LIMIT = 8 * 1024 * 1024


def _cache_root():
    base = Path(os.environ.get('XDG_CACHE_HOME') or
                (Path.home() / 'Library' / 'Caches' if sys.platform == 'darwin' else Path.home() / '.cache'))
    return base / 'RunTeams-pipeline-choices'


@cache
def _build_identity():
    try:
        package = Path(__file__).resolve().parents[1] / 'package_identity.json'
        return json.loads(package.read_bytes())['source_sha256']
    except FileNotFoundError:
        return 'source-checkout'



class ChoiceIndex:
    """One bounded snapshot per library and projection, replaced atomically."""
    def __init__(self, directory, scope, projection):
        # Increment the projection version when validation or display semantics change.
        binding = json.dumps([str(directory), scope, projection, _build_identity()], sort_keys=True).encode()
        self._binding = binding
        self.path = _cache_root() / (hashlib.sha256(binding).hexdigest() + '.json')
        self.previous = {}
        self.updated = {}
        try:
            if self.path.parent.is_symlink():
                return
            header, payload = _raw(self.path, _LIMIT).split(b'\n', 1)
            if hashlib.sha256(binding + payload).hexdigest().encode() == header:
                rows = json.loads(payload)
                if isinstance(rows, dict):
                    self.previous = rows
        except (ValueError, OSError, RecursionError):
            pass

    def save(self):
        if self.updated == self.previous or self.path.parent.is_symlink():
            return
        try:
            payload = json.dumps(self.updated, ensure_ascii=False, separators=(',', ':')).encode()
            header = hashlib.sha256(self._binding + payload).hexdigest().encode()
            raw = header + b'\n' + payload
            if len(raw) <= _LIMIT:
                directory = private_directory(self.path.parent)
                _publish(directory, directory, self.path, raw)
        except (ValueError, OSError):
            pass  # An unavailable disposable index cannot prevent a live read.
