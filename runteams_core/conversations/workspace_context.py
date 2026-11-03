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

_mobile_command=ContextVar('runteams_mobile_command',default='')
_mobile_actor=ContextVar('runteams_mobile_actor',default='')
@contextmanager
def mobile_command(command_id,actor_id=""):
    actor=str(uuid.UUID(str(actor_id))) if actor_id else ""
    token=_mobile_command.set(command_id);actor_token=_mobile_actor.set(actor)
    try:yield
    finally:_mobile_command.reset(token);_mobile_actor.reset(actor_token)
def selected_mobile_command():return _mobile_command.get()
def selected_mobile_actor():return _mobile_actor.get()
