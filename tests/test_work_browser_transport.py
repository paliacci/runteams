"""The browser bridge retains a bounded reply budget for each tool family."""
import json
import unittest
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch

from runteams_core.work.hosts.browser_work_host import transport


class BrowserWorkTransportTests(unittest.TestCase):
    def test_local_workspace_and_library_generation_are_independent(self):
        from runteams_core.application.local_runtime import LocalRuntime
        backups = SimpleNamespace(generation='first')
        app = SimpleNamespace(binding=SimpleNamespace(library_id='test-library'), backups=backups,
                              work_frame_host='work-' + '0' * 32 + '.localhost')
        router = SimpleNamespace(discover=lambda chat, workspace: {'chat': chat, 'workspace': workspace})
        runtime = SimpleNamespace(lock=RLock(), app=app, _browser_work=None, work_router=lambda: router)
        def send(action, **fields):
            return LocalRuntime.browser_work(runtime, dict(action=action, **fields), 'http://127.0.0.1:8000')
        client = send('register')['client']
        self.addCleanup(runtime._browser_work.close)
        self.assertEqual(send('discover', client=client, chat_id=1, workspace_id=''), {'chat': 1, 'workspace': ''})
        with self.assertRaises(PermissionError):
            send('discover', client=client, chat_id=1, workspace_id='first')
        backups.generation = 'restored'
        with self.assertRaises(PermissionError):
            send('heartbeat', client=client)

    def test_mcp_tool_reply_above_ordinary_ui_budget_reaches_the_app(self):
        config = {'control': 'http://127.0.0.1:8500', 'nonce': 'fixture'}
        reply = {'schema': 'runteams.ui-context/2', 'ok': True,
                 'result': {'structuredContent': {'data': 'a' * 220_000}}}
        body = json.dumps(reply).encode()
        with patch('runteams_core.work.hosts.browser_work_host.http.client.HTTPConnection') as connect:
            response = connect.return_value.getresponse.return_value
            response.status = 200
            response.read.side_effect = lambda limit: body[:limit]
            self.assertEqual(transport(config, '/message', {'method': 'mcp.tools.call'}), reply)
            with self.assertRaisesRegex(RuntimeError, 'work_reply_unknown'):
                transport(config, '/message', {'method': 'context.read'})
