"""Explicit host pipeline assets, configuration and native recovery authority."""
from .storage_context import current_provider


def current():
    return current_provider().pipeline_context()
