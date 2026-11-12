"""Per-operation workspace selection, never an authorization grant."""
from contextvars import ContextVar
from contextlib import contextmanager
import uuid
_selected = ContextVar('runteams_selected_workspace', default='')

def selected():
    return _selected.get()

@contextmanager
def use(organization_id=''):
    try:value=str(uuid.UUID(str(organization_id))) if organization_id else ''
    except (ValueError,TypeError,AttributeError):
        raise PermissionError('工作区选择无效，请重新选择工作区。') from None
    token=_selected.set(value)
    try:yield value
    finally:_selected.reset(token)
