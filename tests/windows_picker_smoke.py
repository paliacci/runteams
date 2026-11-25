"""Select a Unicode file and work folder in the installed Windows native dialogs."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import tempfile

from windows_desktop_smoke import wait_for


user = ctypes.windll.user32
user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user.SendMessageW.restype = wintypes.LPARAM
callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def visible_windows(pid, parent=None):
    result = []

    @callback
    def visit(handle, unused):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(handle):
            result.append(handle)
        return True

    if parent is None:
        user.EnumWindows(visit, 0)
    else:
        user.EnumChildWindows(parent, visit, 0)
    return result


def class_name(handle):
    name = ctypes.create_unicode_buffer(128)
    user.GetClassNameW(handle, name, len(name))
    return name.value


def select_path(pid, path):
    window = wait_for(lambda: next(h for h in visible_windows(pid) if class_name(h) == '#32770'))
    def control(name, ids):
        return next(h for h in visible_windows(pid, window)
                    if class_name(h) == name and user.GetDlgCtrlID(h) in ids and user.IsWindowEnabled(h))
    # The common file and folder dialogs expose different filename edit IDs.
    edit = wait_for(lambda: control('Edit', {1001, 1148, 1152}))
    text = ctypes.create_unicode_buffer(str(path))
    assert user.SendMessageW(edit, 0x000c, 0, ctypes.addressof(text))  # WM_SETTEXT
    ok = wait_for(lambda: control('Button', {1}))
    assert user.PostMessageW(ok, 0x00f5, 0, 0)  # BM_CLICK


def verify(executable):
    with tempfile.TemporaryDirectory(prefix='runteams-picker-') as directory:
        folder = Path(directory) / '工作 资料'
        folder.mkdir()
        file = folder / '说明 文档.txt'
        file.write_text('fixture', encoding='utf-8')
        for args, path in [(['--files-only', '--single'], file),
                           (['--folders-only', '--single', '--work-folder'], folder),
                           ([], None)]:
            with subprocess.Popen([executable, '--picker', *args], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE) as picker:
                try:
                    if path is None:
                        window = wait_for(lambda: next(iter(visible_windows(picker.pid))))
                        user.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE
                    else:
                        select_path(picker.pid, path)
                    output, error = picker.communicate(timeout=15)
                    assert picker.returncode == 0, error
                    assert json.loads(output) == {'cancelled': path is None,
                                                  'paths': [] if path is None else [str(path)]}
                finally:
                    if picker.poll() is None:
                        picker.terminate()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    verify(parser.parse_args().executable.resolve(strict=True))
    print('Passed native file selection, work folder selection and cancellation.')
