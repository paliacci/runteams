"""Open a user-selected document or show an authorized path in the native shell."""
import os
from pathlib import Path
import subprocess
import sys


def open_path(path):
    if sys.platform == 'win32':
        os.startfile(os.fspath(path))
    else:
        opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
        subprocess.run([opener, os.fspath(path)], check=True, capture_output=True, timeout=15)


def reveal(path):
    path = Path(path)
    if path.is_dir() and not (sys.platform == 'darwin' and path.suffix.lower() == '.app'):
        open_path(path)
    elif sys.platform == 'win32':
        _select_in_explorer(path)
    elif sys.platform == 'darwin':
        subprocess.run(['open', '-R', str(path)], check=True, capture_output=True, timeout=10)
    else:
        open_path(path.parent)


def _select_in_explorer(path):
    import ctypes
    from ctypes import wintypes

    ole = ctypes.OleDLL('ole32')
    shell = ctypes.OleDLL('shell32')
    ole.CoInitializeEx.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    ole.CoUninitialize.restype = None
    ole.CoTaskMemFree.argtypes = [wintypes.LPVOID]
    ole.CoTaskMemFree.restype = None
    pidl = ctypes.c_void_p()
    shell.SHParseDisplayName.argtypes = [
        wintypes.LPCWSTR, wintypes.LPVOID, ctypes.POINTER(ctypes.c_void_p),
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    shell.SHOpenFolderAndSelectItems.argtypes = [
        wintypes.LPVOID, wintypes.UINT, wintypes.LPVOID, wintypes.DWORD]
    # The HTTP handler's thread owns this COM initialization. OleDLL raises
    # on failed HRESULTs, including a shell failure to show the selection.
    ole.CoInitializeEx(None, 2)
    try:
        shell.SHParseDisplayName(str(path), None, ctypes.byref(pidl), 0, None)
        try:
            shell.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        finally:
            ole.CoTaskMemFree(pidl)
    finally:
        ole.CoUninitialize()
