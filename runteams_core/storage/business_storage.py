"""Explicit storage routing for platform services and device-owned work.

Providers are keyed by an exact database identity so subprocesses and modules
cannot accidentally select a different store. No path/URL failure selects SQLite.
"""
from pathlib import Path
import threading

_REGISTRY = {}
_LOCK = threading.RLock()


def bind_storage(path, provider):
    key = str(Path(path).resolve())
    with _LOCK:
        _REGISTRY[key] = provider
    return provider


def bound_storage(path):
    with _LOCK:
        return _REGISTRY.get(str(Path(path).resolve()))


def storage_for(path):
    key = str(Path(path).resolve())
    with _LOCK:
        provider = _REGISTRY.get(key)
    if provider is not None:
        return provider
    from runteams_core.work.device_work import recognizes, DeviceWorkStorage
    if recognizes(path):
        return DeviceWorkStorage(path)
    from runteams_core.storage.host_storage import HostStorage
    return HostStorage(key)
