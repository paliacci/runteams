"""Library-owned role summaries. Creation still resolves the exact employee pin."""
import hashlib
import json
from pathlib import Path

from runteams_core.storage.device_files import _publish, _raw
from runteams_core.storage.local_library import private_directory

_LIMIT = 8 * 1024 * 1024


def _index_directory(directory):
    return Path(directory) / '.pipeline-role-index'


class ChoiceIndex:
    """One bounded snapshot per library and projection, replaced atomically."""
    def __init__(self, directory, scope, projection):
        # Increment the projection version when validation or display semantics change.
        binding = json.dumps([str(directory), scope, projection], sort_keys=True).encode()
        self._binding = binding
        self.path = _index_directory(directory) / (hashlib.sha256(binding).hexdigest() + '.json')
        self.previous = {}
        self.updated = {}
        try:
            if self.path.parent.is_symlink() or self.path.parent.parent.is_symlink():
                return
            header, payload = _raw(self.path, _LIMIT).split(b'\n', 1)
            if hashlib.sha256(binding + payload).hexdigest().encode() == header:
                rows = json.loads(payload)
                if isinstance(rows, dict):
                    self.previous = rows
        except (ValueError, OSError, RecursionError):
            pass

    def save(self):
        if self.updated == self.previous or self.path.parent.is_symlink() or self.path.parent.parent.is_symlink():
            return
        try:
            payload = json.dumps(self.updated, ensure_ascii=False, separators=(',', ':')).encode()
            header = hashlib.sha256(self._binding + payload).hexdigest().encode()
            raw = header + b'\n' + payload
            if len(raw) <= _LIMIT:
                directory = private_directory(self.path.parent)
                _publish(directory, self.path, raw)
        except (ValueError, OSError):
            pass  # An unavailable disposable index cannot prevent a live read.
