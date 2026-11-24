"""Create and read a document through the mounted desktop app's local server."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import ProxyHandler, Request, build_opener


def check(app, directory):
    resources = app / 'Contents/Resources'
    core = resources / 'core'
    python = core / 'runtime-dependencies/agent-python/bin/python3'
    entry = ('import sys; sys.path.insert(0, sys.argv.pop(1)); sys.path.append(sys.argv.pop(1)); '
             'from runteams_core.application.community import main; main(sys.argv[1:])')
    command = [python, '-I', '-S', '-B', '-u', '-c', entry, core, resources / 'python-packages',
               '--port', '0', '--data-dir', directory / 'library', '--owner-stdin']
    env = {'HOME': str(directory), 'PATH': os.defpath, 'TMPDIR': str(directory),
           'LANG': 'en_US.UTF-8', 'RUNTEAMS_AUTOMATION_DISPATCH': '0'}
    document = {'schema': 'runteams.rich-document/1', 'sources': {}, 'blocks': [
        {'id': 'ci', 'type': 'markdown', 'props': {'text': 'Desktop build check'}, 'children': []}]}
    with subprocess.Popen(command, cwd=directory, env=env, text=True,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE) as process:
        try:
            session = json.loads(process.stdout.readline())
            headers = {'Authorization': 'Bearer ' + session['session_token'], 'Content-Type': 'application/json'}
            url = session['origin'] + '/api/device/work/documents'
            data = json.dumps({'name': 'Desktop CI', 'content_model': 'rich-document',
                               'document': document}).encode()
            client = build_opener(ProxyHandler({}))
            with client.open(Request(url, headers=headers, data=data), timeout=20) as response:
                assert response.status == 201, response.status
                identifier = json.load(response)['id']
            with client.open(Request(f'{url}/{identifier}', headers=headers), timeout=20) as response:
                assert json.loads(json.load(response)['content']) == document
            print('Packaged desktop document write and read passed')
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                raise
    if process.returncode:
        raise RuntimeError(f'Packaged server exited with status {process.returncode}')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='runteams-desktop-check-') as temp:
        check(Path(sys.argv[1]).resolve(), Path(temp))
