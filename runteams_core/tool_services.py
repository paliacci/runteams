"""Explicit tool-service binding and authority-scoped lazy construction."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import threading


class ToolServiceUnavailable(ValueError):
    pass


_bound = ContextVar('runteams_tool_service', default=None)


@contextmanager
def using(service):
    if not hasattr(service, 'repository'):
        raise TypeError('Tool service must own a repository')
    token = _bound.set(service)
    try:
        yield service
    finally:
        _bound.reset(token)


def current():
    service = _bound.get()
    if service is not None:
        return service
    from .storage_context import current_provider
    return current_provider().tool_service()


class ServiceCache:
    """One current service; a failed or changed authority is never published."""
    def __init__(self, factory, root, scope):
        self.factory, self.root, self.scope = factory, root, scope
        self._lock = threading.RLock()
        self._key = None
        self._service = None

    def _identity(self):
        scope = self.scope()
        if not isinstance(scope, tuple):
            raise TypeError('Service authority must be an immutable scope tuple')
        return os.path.realpath(self.root()), scope

    def get(self):
        with self._lock:
            try:
                key = self._identity()
                if key != self._key:
                    self._key = self._service = None
                service = self._service
                if service is None:
                    service = self.factory(key[0])
                if self._identity() != key:
                    raise PermissionError('工作服务账户或工作区已变化，请重新打开。')
                self._key, self._service = key, service
                return service
            except BaseException:
                self._key = self._service = None
                raise
