"""Storage exhaustion stays a typed read failure, never an empty successful list."""
from http.client import HTTPConnection
from pathlib import Path
import json
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from runteams_core.storage.local_read_errors import read_failure
from runteams_core.application.local_application import LocalApplication
from runteams_core.application.http.local_http import LocalServer


def full_error():
    # Bound SQLite itself rather than filling the user's real disk.
    with sqlite3.connect(':memory:') as connection:
        connection.execute('CREATE TABLE items(body BLOB)')
        pages = connection.execute('PRAGMA page_count').fetchone()[0]
        connection.execute('PRAGMA max_page_count=' + str(pages))
        try:
            connection.execute('INSERT INTO items VALUES(zeroblob(65536))')
        except sqlite3.Error as error:
            return error
    raise AssertionError('SQLite exhaustion fixture did not fail')


class LocalStorageReadFailureTests(unittest.TestCase):
    def test_real_sqlite_full_has_distinct_status_and_actionable_safe_copy(self):
        error = full_error()
        self.assertEqual(error.sqlite_errorcode, sqlite3.SQLITE_FULL)
        payload, status = read_failure(error)
        self.assertEqual((status, payload['code']), (507, 'local_storage_full'))
        self.assertIn('磁盘空间', payload['error'])

    def test_other_io_failures_never_claim_corruption_or_expose_private_details(self):
        error = sqlite3.OperationalError('/private/account-token: inaccessible')
        error.sqlite_errorcode = sqlite3.SQLITE_IOERR_READ
        payload, status = read_failure(error)
        self.assertEqual((status, payload['code']), (503, 'local_storage_read_failed'))
        self.assertNotIn('account-token', json.dumps(payload))

    def test_local_http_returns_a_full_error_then_recovers_without_replaying_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            application = LocalApplication(Path(directory));server = LocalServer(application, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            headers = {'Authorization': 'Bearer ' + server.session_token}
            try:
                with patch.object(application, 'dispatch', side_effect=full_error()) as dispatch:
                    connection.request('GET', '/api/chats?device=1', headers=headers)
                    response = connection.getresponse();body = json.loads(response.read())
                    self.assertEqual((response.status, body['code']), (507, 'local_storage_full'))
                    self.assertNotIn('chats', body)
                    self.assertEqual(dispatch.call_count, 1)
                connection.request('GET', '/api/employee-avatars', headers=headers)
                response = connection.getresponse();body = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertEqual(len(body['presets']), 14)
            finally:
                connection.close();server.shutdown();thread.join(5);server.server_close()


if __name__ == '__main__':
    unittest.main()
