"""Verify the installed community mainline in a fresh, disposable local library."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    args.python = str(Path(args.python).absolute())
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('RUNTEAMS_', 'PYTHON'))}
    environment['RUNTEAMS_AUTOMATION_DISPATCH'] = '0'
    with tempfile.TemporaryDirectory(prefix='runteams-community-install-') as directory:
        environment['HOME'] = directory
        subprocess.run([args.python, '-I', '-B', '-c',
            "from pathlib import Path;from runteams_core import local_database; import os;p=Path(local_database.DB_PATH);assert p.is_relative_to(Path(os.environ['HOME']))"],
            cwd=directory, env=environment, check=True)
        with tempfile.TemporaryFile(mode='w+') as errors:
            process = subprocess.Popen([args.python, '-I', '-B', '-m', 'runteams_core.community',
                '--port', '0', '--data-dir', str(Path(directory) / 'library'), '--owner-stdin'],
                cwd=directory, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors, text=True)
            try:
                descriptor = json.loads(process.stdout.readline())
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                results = {}
                for path in ('/api/health', '/', '/ui/work-page-host.js', '/rich-document/dist/index.html', '/api/library'):
                    request = urllib.request.Request(descriptor['origin'] + path,
                        headers={'Authorization': 'Bearer ' + descriptor['session_token']})
                    with opener.open(request, timeout=15) as response:
                        body = response.read()
                        assert response.status == 200, path
                        if path == '/':
                            assert b'<html' in body and b'/official-ui/' not in body
                        results[path] = {'status': response.status, 'bytes': len(body)}
                subprocess.run([args.python, '-I', '-B', '-c',
                    'import runteams_core.local_work_core, runteams_core.automation_scheduler, runteams_creator_dev.cli'],
                    cwd=directory, env=environment, check=True)
                print(json.dumps(results))
            finally:
                process.stdin.close()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=15)
                if process.returncode:
                    errors.seek(0)
                    raise RuntimeError(errors.read())


if __name__ == '__main__':
    main()
