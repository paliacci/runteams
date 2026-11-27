"""Open a user-selected document or show an authorized path in the native shell."""
import os
from pathlib import Path
import subprocess
import sys


_EXPLORER_OPEN_TYPES = frozenset('.pdf .wav .mp3 .m4a .ogg .flac .mp4 .mov'.split())


def open_path(path):
    if sys.platform == 'win32':
        target = Path(path)
        if target.suffix.casefold() in _EXPLORER_OPEN_TYPES and target.is_file():
            try:
                _invoke_explorer_open(path)
                return
            except OSError as error:
                # Some file associations register only a default verb other than "open".
                if getattr(error, 'winerror', None) != 1155:  # ERROR_NO_ASSOCIATION
                    raise
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


def _invoke_explorer_open(path):
    """Invoke the file's Explorer Open command on the HTTP request thread."""
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
            ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
            ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
            ('lpIDList', wintypes.LPVOID), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
            ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE),
        ]

    ole = ctypes.OleDLL('ole32')
    ole.CoInitializeEx.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    ole.CoUninitialize.restype = None
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    # INVOKEIDLIST uses Explorer's context-menu handler. NOASYNC completes dispatch
    # before this request thread releases its COM apartment.
    info = ShellExecuteInfo(cbSize=ctypes.sizeof(ShellExecuteInfo), fMask=0x0C | 0x100,
                            lpVerb='open', lpFile=os.fspath(path), nShow=1)
    ole.CoInitializeEx(None, 0x2 | 0x4)  # APARTMENTTHREADED | DISABLE_OLE1DDE
    try:
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        ole.CoUninitialize()


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
