"""Exercise the public MCP bundles in the desktop WKWebView with an in-memory service."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Thread


def check(bundles: Path):
    tests = Path(__file__).resolve().parent
    fixture = tests / 'fixtures/mcp-webview'
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        site = root / 'site'
        views = site / 'views'
        views.mkdir(parents=True)
        for page in ('mcp-host.html', 'mcp-app.html'):
            shutil.copyfile(fixture / page, views / page)
        for script in ('app-host.js', 'creator-app.js'):
            shutil.copyfile(bundles / script, site / script)
        executable = root / 'check-webview'
        subprocess.run(['swiftc', tests.parent / 'desktop/creator/CreatorWebHost.swift',
                        fixture / 'CheckWebView.swift', '-o', executable], check=True)
        handler = partial(SimpleHTTPRequestHandler, directory=site)
        with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                subprocess.run([executable, f'http://127.0.0.1:{server.server_port}'],
                               check=True, timeout=45)
            finally:
                server.shutdown()
                thread.join()


if __name__ == '__main__':
    check(Path(sys.argv[1]))
