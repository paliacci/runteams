"""Exercise an installed RunTeams Local Windows window against a disposable library."""
import argparse
import ctypes
from contextlib import closing
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

import websocket


def wait_for(check, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, StopIteration):
            pass
        time.sleep(.2)
    raise TimeoutError(f'Timed out at {check.__name__}')


def close_window(process):
    user32 = ctypes.windll.user32
    windows = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(window, unused):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == process.pid and user32.IsWindowVisible(window):
            windows.append(window)
        return True

    user32.EnumWindows(collect, 0)
    if len(windows) != 1:
        raise RuntimeError('Expected one desktop window')
    user32.PostMessageW(windows[0], 0x0010, 0, 0)  # WM_CLOSE


def check_theme_contrast(origin, command, evaluate):
    command('Page.navigate', {'url': origin + '/design-system?theme=system'})
    wait_for(lambda: evaluate("!!document.querySelector('[data-design-theme=system]')"))
    for palette in ('light', 'dark'):
        command('Emulation.setEmulatedMedia', {'features': [
            {'name': 'forced-colors', 'value': 'active'},
            {'name': 'prefers-color-scheme', 'value': palette},
        ]})
        assert evaluate("""(() => {
            const buttons = [...document.querySelectorAll('[data-design-theme]')];
            const sample = document.createElement('span');
            sample.style.cssText = 'forced-color-adjust:none;background:Highlight;color:HighlightText';
            document.body.append(sample);
            const colors = getComputedStyle(sample);
            const result = buttons.length === 3 && buttons.every(button => {
                button.click();
                const selected = buttons.filter(b => b.getAttribute('aria-pressed') === 'true');
                const style = getComputedStyle(button);
                return selected.length === 1 && selected[0] === button &&
                    style.backgroundColor === colors.backgroundColor && style.color === colors.color;
            });
            sample.remove();
            return matchMedia('(forced-colors: active)').matches && result;
        })()"""), f'Active theme does not use the {palette} forced-color selection'


def exercise(executable, root):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        debug_port = reservation.getsockname()[1]
    environment = {**os.environ, 'WEBVIEW2_USER_DATA_FOLDER': str(root / 'webview'),
                   'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS': f'--remote-debugging-port={debug_port}'}
    connection = build_opener(ProxyHandler({}))

    def page():
        with connection.open(f'http://127.0.0.1:{debug_port}/json/list', timeout=2) as response:
            return next(tab for tab in json.load(response) if tab['type'] == 'page'
                        and tab['url'].startswith('http://127.0.0.1:'))

    with subprocess.Popen([executable, '--data-dir', root / '本机资料 QA'], env=environment) as app:
        try:
            target = wait_for(page)
            origin = 'http://' + urlsplit(target['url']).netloc
            with closing(websocket.create_connection(target['webSocketDebuggerUrl'], timeout=8, suppress_origin=True)) as ws:
                def command(method, params):
                    ws.send(json.dumps({'id': 1, 'method': method, 'params': params}))
                    while True:
                        reply = json.loads(ws.recv())
                        if reply.get('id') == 1:
                            if 'error' in reply:
                                raise AssertionError(reply['error'])
                            return reply['result']

                def evaluate(script):
                    result = command('Runtime.evaluate', {
                        'expression': script, 'awaitPromise': True, 'returnByValue': True})
                    if 'exceptionDetails' in result:
                        raise AssertionError(result['exceptionDetails']['text'])
                    return result['result'].get('value')

                wait_for(lambda: evaluate("!!window.RunTeamsLocalDesktop && !!document.querySelector('.rail-top-search')"))
                wait_for(lambda: evaluate("S.appInfo?.native_attachment_picker === true"))
                assert evaluate("document.querySelector('.rail-top-search').getAttribute('aria-keyshortcuts')") == 'Control+K'
                evaluate("""document.querySelector('[data-app-i18n="shell.documents"]').closest('button,a').click()""")
                wait_for(lambda: evaluate("location.pathname === '/documents' && !!window.RunTeamsLocalDesktop && !!document.querySelector('.rail-settings-button')"))
                evaluate("document.querySelector('.rail-settings-button').click()")
                wait_for(lambda: evaluate("!!document.querySelector('#settingsPanel #settings_send_mode')"))
                assert evaluate("""(async () => {
                    const library = await (await fetch('/api/library')).json();
                    const r = await fetch('/api/settings', {headers: {
                        'X-RunTeams-Library': library.library_id, 'X-RunTeams-Library-Generation': library.generation}});
                    return r.ok && (await r.json()).library_id === library.library_id;
                })()""")
                check_theme_contrast(origin, command, evaluate)
                wait_for(lambda: evaluate("window.RunTeamsLocalDesktop.checkClose(false) === 'ready'"))
            close_window(app)
            if app.wait(timeout=20) != 0:
                raise RuntimeError('Desktop host exited with an error')

            def service_closed():
                try:
                    with connection.open(origin + '/api/health', timeout=1):
                        return False
                except OSError:
                    return True

            wait_for(service_closed, 15)
        finally:
            if app.poll() is None:
                app.terminate()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    folder = tempfile.TemporaryDirectory(prefix='runteams-desktop-qa-')
    try:
        exercise(args.executable.resolve(strict=True), Path(folder.name))
    finally:
        # Edge can retain the test profile briefly after its host window exits.
        wait_for(lambda: folder.cleanup() is None, 15)
    print('Passed installed desktop startup, document navigation, settings, and service shutdown.')
