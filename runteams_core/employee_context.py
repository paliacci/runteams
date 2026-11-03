"""Host-owned employee context, separate from ordinary local storage and tools.

The selected provider supplies the capability. Session/context data cannot pick
an official adapter, and a general work/document service is not this capability.
"""
from .storage_context import current_provider


def current():
    return current_provider().employee_context()
