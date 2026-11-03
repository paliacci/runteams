"""Storage composition, with a local library as the account-free default."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import threading
import uuid


@dataclass(frozen=True)
class StorageBinding:
    root: Path
    library_id: str
    scope: dict


_default = None
_lock = threading.RLock()
_override = ContextVar('runteams_storage_provider', default=None)


def set_default_provider(provider):
    """Application composition only; selecting an account is not this operation."""
    if provider is not None and not callable(getattr(provider, 'resolve', None)):
        raise TypeError('Storage provider must resolve a library binding')
    global _default
    with _lock:
        previous, _default = _default, provider
    return previous


@contextmanager
def using(provider):
    if not callable(getattr(provider, 'resolve', None)):
        raise TypeError('Storage provider must resolve a library binding')
    token = _override.set(provider)
    try:
        yield
    finally:
        _override.reset(token)


def current_provider():
    """The explicitly selected edition provider; no account or cloud imports."""
    provider = _override.get()
    if provider is None:
        with _lock:
            provider = _default
        if provider is None:
            from .local_library import LocalLibrary
            provider = LocalLibrary()
    return provider


def resolve(base):
    value = current_provider().resolve(Path(base))
    if not isinstance(value, StorageBinding) or str(uuid.UUID(value.library_id)) != value.library_id:
        raise ValueError('Invalid library binding')
    root, parent = value.root.resolve(), Path(base).resolve()
    if not root.is_relative_to(parent) or root == parent:
        raise ValueError('Library must remain within its own data root')
    return value


def notify_saved(scope):
    """Optional host maintenance; local persistence does not start cloud work."""
    provider = _override.get()
    if provider is None:
        with _lock:
            provider = _default
    hook = getattr(provider, 'after_commit', None)
    if hook is not None:
        hook(scope)
