"""Device work service composition, distinct from the shared business core."""
from .storage_context import current_provider


def current(**kwargs):
    return current_provider().device_work_service(**kwargs)
