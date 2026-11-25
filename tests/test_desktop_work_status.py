"""Only the desktop owner can poll the activity that drives its sleep request."""
from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from runteams_core.application.http.local_http import LocalServer
from runteams_core.application.local_application import LocalApplication
from runteams_core.storage import local_database


class DesktopWorkStatusTests(unittest.TestCase):
    def test_owner_observes_active_to_idle_without_polling_starting_a_runtime(self):
        with TemporaryDirectory() as directory, patch.object(
                local_database, 'DB_PATH', str(Path(directory) / 'runteams.db')):
            app = LocalApplication(Path(directory))
            server = LocalServer(app, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def poll(headers):
                client = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    client.request('GET', '/api/desktop/work-active', headers=headers)
                    response = client.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    client.close()

            try:
                owner = {'Authorization': 'Bearer ' + server.session_token}
                self.assertEqual(poll({})[0], 401)
                self.assertEqual(poll({'Cookie': server.cookie_name + '=' + server.browser_token})[0], 403)
                self.assertEqual(poll(owner), (200, False))
                self.assertIsNone(app._runtime)
                with patch.dict(app.runtime.employee_jobs, {1: object()}):
                    self.assertEqual(poll(owner), (200, True))
                self.assertEqual(poll(owner), (200, False))
            finally:
                server.shutdown()
                thread.join(5)
                server.server_close()
                app.close()
