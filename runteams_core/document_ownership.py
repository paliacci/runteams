"""Document owner context set only after the host resolves its session binding."""
from copy import deepcopy
from contextvars import ContextVar

_document_owner = ContextVar('employee_document_owner', default=None)


def current_document_owner():
    return deepcopy(_document_owner.get() or {})

