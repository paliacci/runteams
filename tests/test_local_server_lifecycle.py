"""A failed listener must leave the application with its current owner."""
import unittest
from unittest.mock import Mock, patch

from runteams_core.application import community
from runteams_core.application.http.local_http import LocalServer


class LocalServerLifecycleTests(unittest.TestCase):
    def test_second_bind_cannot_close_application_owned_by_live_listener(self):
        app = Mock()
        with LocalServer(app, 0) as first:
            with self.assertRaises(OSError):
                LocalServer(app, first.server_port)
            app.close.assert_not_called()
        app.close.assert_called_once_with()

    def test_cli_closes_its_new_application_when_port_is_occupied(self):
        app = Mock()
        with LocalServer(Mock(), 0) as first, patch.object(community, 'LocalApplication', return_value=app), \
                patch.dict(community.os.environ), patch('sys.stderr'):
            with self.assertRaises(SystemExit) as failure:
                community.main(['--port', str(first.server_port)])
        self.assertEqual(failure.exception.code, 2)
        app.close.assert_called_once_with()
