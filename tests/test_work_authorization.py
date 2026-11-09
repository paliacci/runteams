"""First-use approval remains version-bound and separate from tool approval."""
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from runteams_core.employees.mcp.device_employee_mcp import EmployeeMCPWork
from runteams_core.foundation.contracts import digest


class Host(EmployeeMCPWork):
    def __init__(self, directory):
        self.lock = threading.RLock()
        self.pending, self.sessions, self.turns, self.views = {}, {}, {}, {}
        self.connection_calls, self.connection_requests = {}, {}
        self.binding = SimpleNamespace(work_id='work', release_digest='version-1')
        self.packages = {'package': SimpleNamespace()}
        self.work = Path(directory)
        self.grants = {}
        self.closed_chats = []
        self.notice_revision = 0
        self.runtime = SimpleNamespace(verify=lambda: ('node', 'worker'))
        self.closed = False
    def check(self): pass
    def _identity(self, chat): return {}, self.packages, self.work, self.binding
    def _trust_path(self, binding, package): return digest([binding.__dict__, package])
    def enabled(self, binding, package): return self.grants.get(self._trust_path(binding, package), {}).get('enabled', False)
    def _write(self, path, value): self.grants[path] = value
    def load(self, chat, pin=False): return self._identity(chat)[:3]
    def resume(self, chat, expected):
        if expected != digest(self.binding.__dict__) or not all(self.enabled(self.binding,p) for p in self.packages):
            raise PermissionError('changed')
    def state(self, chat): return {'enabled': all(self.enabled(self.binding,p) for p in self.packages)}
    def close_work(self, chat): self.closed_chats.append(chat)


class WorkAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = Host(self.temp.name)
    def start(self, fn):
        notified = threading.Event()
        result = []
        def run():
            try: result.append(fn(notified.set))
            except BaseException as error: result.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(notified.wait(2))
        return thread, result, next(iter(self.host.pending))
    def test_first_use_waits_for_explicit_matching_version(self):
        h=self.host
        t,result,key=self.start(lambda notify:h.authorize_runtime(1,notify=notify))
        self.assertFalse(h.state(1)['enabled'])
        self.assertEqual(h.pending[key]['public']['method'],'runteams/work-authorization')
        with self.assertRaises(PermissionError): h.answer(1,'stale',key,'accept')
        self.assertTrue(t.is_alive())
        h.answer(1,digest(h.binding.__dict__),key,'accept')
        t.join(2)
        self.assertEqual(result,[None]);self.assertTrue(h.state(1)['enabled'])
        self.assertFalse(h.pending)
    def test_cancel_does_not_create_permission(self):
        h=self.host;t,result,key=self.start(lambda notify:h.authorize_runtime(1,notify=notify))
        h.answer(1,digest(h.binding.__dict__),key,'cancel');t.join(2)
        self.assertIsInstance(result[0],PermissionError);self.assertFalse(h.grants)
    def test_version_change_invalidates_confirmation(self):
        h=self.host;t,result,key=self.start(lambda notify:h.authorize_runtime(1,notify=notify))
        old=digest(h.binding.__dict__)
        h.binding=SimpleNamespace(work_id='work',release_digest='version-2')
        with self.assertRaises(PermissionError):h.answer(1,old,key,'accept')
        # Original turn cancellation is independent of the newly selected version.
        h.pending[key]['decision']='cancel';h.pending[key]['done'].set();t.join(2)
        self.assertIsInstance(result[0],PermissionError);self.assertFalse(h.grants)
    def test_generic_tool_request_cannot_grant_initial_trust(self):
        with self.assertRaises(PermissionError):
            self.host.ask(1,'runteams/work-authorization',{})
        self.assertFalse(self.host.grants);self.assertFalse(self.host.pending)
    def test_existing_permission_needs_no_new_confirmation(self):
        h=self.host;h.enable(1,digest(h.binding.__dict__),True)
        h.authorize_runtime(1,notify=lambda:self.fail('Unneeded approval'))
        self.assertFalse(h.pending)
    def test_tool_decline_does_not_revoke_version_permission(self):
        h=self.host;h.enable(1,digest(h.binding.__dict__),True)
        with patch('runteams_core.employees.mcp.device_employee_mcp.approval_response',side_effect=lambda m,p,d:{'accepted':d=='accept'}):
            t,result,key=self.start(lambda notify:h.ask(1,'tool',{},notify=notify))
            h.answer(1,digest(h.binding.__dict__),key,'decline');t.join(2)
        self.assertEqual(result,[{'accepted':False}]);self.assertTrue(h.state(1)['enabled'])
    def test_finished_turn_releases_programs_without_manual_close(self):
        h=self.host;h.enable(1,digest(h.binding.__dict__),True)
        @contextmanager
        def serve(dispatch):yield 'endpoint','token'
        with patch('runteams_core.foundation.transport.loopback_rpc.serve_rpc',serve):
            with h.runtime_scope(1):self.assertIn(1,h.turns)
        self.assertEqual(h.closed_chats,[1]);self.assertFalse(h.turns)
    def test_live_view_retains_program_until_last_user_finishes(self):
        h=self.host;h.enable(1,digest(h.binding.__dict__),True)
        @contextmanager
        def serve(dispatch):yield 'endpoint','token'
        h.retain_view(1)
        with patch('runteams_core.foundation.transport.loopback_rpc.serve_rpc',serve):
            with h.runtime_scope(1):pass
        self.assertFalse(h.closed_chats)
        h.release_view(1);self.assertEqual(h.closed_chats,[1])
    def test_closing_view_during_turn_does_not_interrupt_turn(self):
        h=self.host;h.turns[1]=None;h.retain_view(1);h.release_view(1)
        self.assertFalse(h.closed_chats)

if __name__=='__main__':unittest.main()
