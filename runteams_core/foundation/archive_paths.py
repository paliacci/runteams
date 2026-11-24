"""Validate package member names before using them as native relative paths."""
import os
from pathlib import PureWindowsPath


def windows_compatible(name):
    for part in name.split('/'):
        if (not part or part.endswith((' ', '.')) or PureWindowsPath(part).is_reserved()
                or any(c in '<>:"|?*\\' or ord(c) < 32 for c in part)):
            return False
        try:
            if len(part.encode('utf-16-le')) > 510:
                return False
        except UnicodeEncodeError:
            return False
    return True


def valid_relative(name):
    return (isinstance(name, str) and bool(name) and '\\' not in name and '\0' not in name
            and all(part not in ('', '.', '..') for part in name.split('/'))
            and (os.name != 'nt' or windows_compatible(name)))
