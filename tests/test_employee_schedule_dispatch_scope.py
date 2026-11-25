from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
import unittest
from unittest.mock import Mock, patch

from runteams_core.automation import local_schedules
from runteams_core.automation.device_employee_schedules import EmployeeSchedules, PreparationUnknown
from runteams_core.foundation.contracts import ContractError


class LocalScheduleCommandTests(unittest.TestCase):
    def test_only_confirmed_command_rejections_release_pending_operations(self):
        for kind in ('employee', 'pipeline'):
            with self.subTest(kind=kind):
                path = '/api/device/' + kind + '-schedules'
                runtime = Mock()
                host = runtime.schedule_host.return_value
                backend = host.backend.return_value
                backend.api_path = path
                backend.command.side_effect = ContractError('unfinished run')
                response = local_schedules.dispatch(runtime, 'POST', path, {})
                self.assertEqual((response.status, response.payload), (400, {
                    'error': 'unfinished run', 'code': 'schedule_command_rejected'}))
                host.start.assert_not_called()

                backend.command.side_effect = PreparationUnknown('preparation pending')
                response = local_schedules.dispatch(runtime, 'POST', path, {})
                self.assertEqual((response.status, response.payload['state']), (409, 'unknown'))

                backend.command.side_effect = None
                host.start.side_effect = OSError('scheduler unavailable after commit')
                response = local_schedules.dispatch(runtime, 'POST', path, {})
                self.assertEqual((response.status, response.payload['state']), (503, 'unknown'))
                host.start.assert_called_once_with(kind)


class EmployeeDispatchScopeTests(unittest.TestCase):
    def test_maintenance_dispatch_only_runs_selected_employee_schedule(self):
        scope = {'account_id': 'owner', 'storage_service_url': 'local',
                 'storage_namespace': 'library', 'deployment_id': 'preview'}
        fingerprint = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        approval = {'schema': 'runteams.automation-dispatch-scope/1', 'backend': 'employee-schedules',
                    'binding_sha256': fingerprint, 'schedule_ids': [2], 'expires_at': None}

        schedules = EmployeeSchedules.__new__(EmployeeSchedules)
        schedules.scope = scope
        schedules.recovering = True
        database = sqlite3.connect(':memory:')
        self.addCleanup(database.close)
        database.row_factory = sqlite3.Row
        database.executescript('''
            CREATE TABLE schedules(id INTEGER PRIMARY KEY, enabled INTEGER, deleted INTEGER,
              next_run_at TEXT, schedule_kind TEXT, interval_sec INTEGER, schedule TEXT, reference TEXT);
            CREATE TABLE occurrences(id INTEGER PRIMARY KEY, schedule_id INTEGER, scheduled_for TEXT,
              operation_id TEXT, status TEXT, snapshot TEXT, workflow_id INTEGER, chat_id INTEGER, reason TEXT DEFAULT '');
            INSERT INTO schedules VALUES
              (1,1,0,'2020-01-01T00:00:00+00:00','interval',900,'{}','{}'),
              (2,1,0,'2020-01-01T00:00:00+00:00','interval',900,'{}','{}');
            INSERT INTO occurrences(id,schedule_id,status) VALUES(1,1,'queued');
        ''')

        @contextmanager
        def connection(write=False):
            with database:
                yield database

        schedules.connection = connection
        with (patch.dict(os.environ, {'RUNTEAMS_AUTOMATION_DISPATCH': '0',
                                     'RUNTEAMS_AUTOMATION_SCOPE': json.dumps(approval)}),
              patch('runteams_core.storage.device_data.check'),
              patch('runteams_core.employees.managed_employee_data.writer_busy', return_value=False)):
            self.assertTrue(schedules.scoped_dispatch_enabled())
            self.assertEqual(schedules.seconds_until_due(), 0)
            schedules.materialize_due_automations()
            job = schedules.claim_next_automation_run()
            self.assertEqual(job['schedule_id'], 2)
            self.assertIsNone(schedules.claim_next_automation_run())
            self.assertEqual(database.execute('SELECT status FROM occurrences WHERE id=1').fetchone()[0], 'queued')
            self.assertEqual(database.execute('SELECT next_run_at FROM schedules WHERE id=1').fetchone()[0],
                             '2020-01-01T00:00:00+00:00')
            self.assertGreater(datetime.fromisoformat(
                database.execute('SELECT next_run_at FROM schedules WHERE id=2').fetchone()[0]),
                datetime.now(timezone.utc))

        with patch.dict(os.environ, {'RUNTEAMS_AUTOMATION_DISPATCH': '0', 'RUNTEAMS_AUTOMATION_SCOPE': ''}):
            with patch('runteams_core.storage.device_data.check'):
                self.assertFalse(schedules.scoped_dispatch_enabled())
                self.assertIsNone(schedules.claim_next_automation_run())
