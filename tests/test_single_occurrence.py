from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runteams_core.automation import single_occurrence
from runteams_core.automation.device_employee_schedules import EmployeeSchedules, canonical
from runteams_core.automation.source_pipeline_schedules import PipelineSchedules
from runteams_core.foundation.contracts import ContractError


NOW = '2040-04-11T12:00:00+00:00'
FIRST = '2040-04-11T12:10:00+00:00'
SECOND = '2040-04-11T12:20:00+00:00'
THIRD = '2040-04-11T12:30:00+00:00'
REFERENCE = {'fixture': 'owned-schedule'}


class Clock(datetime):
    value = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.fromisoformat(cls.value).astimezone(tz)


class Host:
    def __init__(self, backend):
        self.store = backend
        self.starts = []

    def backend(self, kind):
        return self.store

    def start(self, kind):
        self.starts.append(kind)


class SingleOccurrenceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(Clock, 'value', NOW))
        self.enterContext(patch.object(single_occurrence, 'datetime', Clock))
        self.enterContext(patch('runteams_core.automation.device_employee_schedules.datetime', Clock))
        self.enterContext(patch('runteams_core.automation.automation_time.now', side_effect=lambda: Clock.value))
        self.enterContext(patch('runteams_core.storage.device_data.check'))
        self.enterContext(patch('runteams_core.storage.device_data.personal', return_value=True))
        self.enterContext(patch('runteams_core.storage.device_data.connect', side_effect=lambda **_: nullcontext()))
        self.enterContext(patch('runteams_core.employees.managed_employee_data.writer_busy', return_value=False))
        self.enterContext(patch('runteams_core.automation.source_pipeline_schedules.control.read',
                                return_value={'status': 'running'}))
        self.temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def schedule(self, backend_type):
        backend = backend_type.__new__(backend_type)
        backend.scope = {}
        backend.path = self.temporary / backend.directory / 'schedules.sqlite3'
        backend.binding = lambda: {}
        backend.dispatch_ids = lambda: None
        if backend_type is PipelineSchedules:
            backend.core = lambda: object()
        with backend.connection(write=True) as connection:
            connection.execute(
                'INSERT INTO schedules VALUES(1,0,0,?,?,?,?,1,\'interval\',600,?,?,0)',
                (canonical(REFERENCE), '', 'Recurring job', canonical({'start_column_key': 'start'}),
                 '{"timezone":"UTC"}', FIRST))
        return backend

    def apply(self, host, operation, previous, revision, *, turn='request', **kwargs):
        return single_occurrence.execute(
            host, kind='test', reference=REFERENCE, turn_key=turn, operation=operation,
            arguments={'id': 1, 'expected_revision': revision, 'expected_next_run_at': previous, **kwargs})

    def read(self, backend):
        with backend.connection() as connection:
            row = connection.execute('SELECT * FROM schedules').fetchone()
            return backend.record(connection, row)

    def linked_pipeline(self, state):
        backend = self.schedule(PipelineSchedules)
        ledger = sqlite3.connect(':memory:')
        self.addCleanup(ledger.close)
        ledger.execute('CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY,state TEXT)')
        ledger.execute("INSERT INTO workflow_runs VALUES(42,?)",(state,))
        repository = SimpleNamespace(read_snapshot=lambda: nullcontext(ledger),
                                     storage=SimpleNamespace(assert_executable=lambda _: None))
        def workflow(identifier):
            row = ledger.execute('SELECT state FROM workflow_runs WHERE id=?',(identifier,)).fetchone()
            return {'state': row[0]} if row else None
        backend.core = lambda: SimpleNamespace(repository=repository,workflow=workflow)
        backend._executing = set()
        return backend,ledger

    def test_failed_pipeline_occurrence_follows_a_retry_of_its_original_workflow(self):
        backend,ledger = self.linked_pipeline('running')
        with backend.connection(write=True) as connection:
            schedule = connection.execute('SELECT * FROM schedules').fetchone()
            backend.fire(connection, schedule, FIRST)
            connection.execute("UPDATE occurrences SET status='failed',workflow_id=42")
            with self.assertRaises(ContractError):
                backend.fire(connection, schedule, SECOND)
        self.assertEqual(self.read(backend)['runs'][0]['status'], 'waiting')
        ledger.execute("UPDATE workflow_runs SET state='interrupted' WHERE id=42")
        self.assertEqual(self.read(backend)['runs'][0]['status'], 'blocked')
        with backend.connection(write=True) as connection:
            connection.execute("UPDATE occurrences SET status='waiting'")
        self.assertEqual(self.read(backend)['runs'][0]['status'], 'blocked')
        with backend.connection(write=True) as connection:
            connection.execute("UPDATE occurrences SET status='failed'")
        ledger.execute("UPDATE workflow_runs SET state='completed' WHERE id=42")
        run, = self.read(backend)['runs']
        self.assertEqual((run['status'],run['workflow_id'],run['scheduled_for']), ('completed',42,FIRST))
        self.assertFalse(backend.reconcile())
        with backend.connection() as connection:
            stored = connection.execute('SELECT status,workflow_id FROM occurrences').fetchall()
        self.assertEqual([tuple(row) for row in stored], [('completed',42)])

    def test_pipeline_occurrence_reports_what_the_user_must_do(self):
        backend,ledger = self.linked_pipeline('needs_approval')
        with backend.connection(write=True) as connection:
            schedule = connection.execute('SELECT * FROM schedules').fetchone()
            backend.fire(connection,schedule,FIRST)
            connection.execute("UPDATE occurrences SET status='waiting',workflow_id=42")
        for state in ('needs_approval','needs_human'):
            ledger.execute('UPDATE workflow_runs SET state=? WHERE id=42',(state,))
            run, = self.read(backend)['runs']
            self.assertEqual((run['status'],run['workflow_state']), ('blocked',state))
            self.assertTrue(backend.reconcile())
            with backend.connection(write=True) as connection:
                self.assertEqual(connection.execute('SELECT status FROM occurrences').fetchone()[0],'blocked')
                with self.assertRaises(ContractError):
                    backend.fire(connection,schedule,SECOND)
        ledger.execute("UPDATE workflow_runs SET state='completed' WHERE id=42")
        self.assertFalse(backend.reconcile())
        run, = self.read(backend)['runs']
        self.assertEqual((run['status'],run['workflow_id']), ('completed',42))
        self.assertNotIn('workflow_state',run)

    def tick(self, backend, stamp):
        Clock.value = stamp
        backend.materialize_due_automations()
        backend.materialize_due_automations()
        with backend.connection(write=True) as connection:
            connection.execute("UPDATE occurrences SET status='completed' WHERE status='queued'")

    def test_move_earlier_survives_restart_and_preserves_interval(self):
        moved = '2040-04-11T12:05:00+00:00'
        for backend_type in (EmployeeSchedules, PipelineSchedules):
            with self.subTest(backend=backend_type.__name__):
                Clock.value = NOW
                backend = self.schedule(backend_type)
                host = Host(backend)
                result = self.apply(host, 'move_next', FIRST, 0, move_to='2040-04-11T20:05:00+08:00')
                self.assertEqual(host.starts, ['test'])
                self.assertEqual(result['following_regular_at'], SECOND)
                self.assertEqual(backend.seconds_until_due(), 300)
                self.assertEqual(self.read(backend)['next_run_at'], moved)
                self.assertEqual(self.apply(Host(backend), 'move_next', FIRST, 0,
                                            move_to='2040-04-11T20:05:00+08:00'), result)
                self.tick(backend, moved)
                self.tick(backend, FIRST)
                self.assertEqual(self.read(backend)['next_run_at'], SECOND)
                self.tick(backend, SECOND)
                plan = self.read(backend)
                self.assertEqual(plan['next_run_at'], THIRD)
                self.assertEqual([(item['scheduled_for'], item['status']) for item in plan['runs']],
                                 [(SECOND, 'completed'), (moved, 'completed')])

    def test_move_later_keeps_earlier_regular_trigger_and_current_work(self):
        moved = '2040-04-11T12:25:00+00:00'
        backend = self.schedule(EmployeeSchedules)
        with backend.connection(write=True) as connection:
            connection.execute("INSERT INTO occurrences(schedule_id,scheduled_for,operation_id,status,snapshot,workflow_id) "
                               "VALUES(1,'manual:fixture','current','waiting','{}',42)")
        result = self.apply(Host(backend), 'move_next', FIRST, 0, move_to=moved)
        self.assertEqual(result['next_run_at'], SECOND)
        self.assertEqual(self.read(backend)['runs'][0]['workflow_id'], 42)
        with backend.connection(write=True) as connection:
            connection.execute("UPDATE occurrences SET status='completed' WHERE operation_id='current'")
        self.tick(backend, SECOND)
        self.assertEqual(self.read(backend)['next_run_at'], moved)
        self.tick(backend, moved)
        self.assertEqual(self.read(backend)['next_run_at'], THIRD)

    def test_skip_is_durable_cannot_duplicate_and_preserves_existing_work(self):
        backend = self.schedule(PipelineSchedules)
        host = Host(backend)
        self.apply(host, 'skip_next', FIRST, 0)
        with self.assertRaises(ContractError):
            self.apply(host, 'move_next', SECOND, 1, turn='different', move_to=FIRST)
        self.assertEqual(self.read(backend)['next_run_at'], SECOND)
        self.tick(backend, FIRST)
        self.tick(backend, SECOND)
        self.assertEqual([(item['scheduled_for'], item['status']) for item in self.read(backend)['runs']],
                         [(SECOND, 'completed'), (FIRST, 'skipped')])

    def test_revalidates_stale_or_in_flight_slot_and_rejects_ambiguous_target(self):
        backend = self.schedule(EmployeeSchedules)
        host = Host(backend)
        for target in ('2040-04-11T12:05:00', NOW, SECOND, THIRD):
            with self.assertRaises(ContractError):
                self.apply(host, 'move_next', FIRST, 0, move_to=target)
        Clock.value = FIRST
        with self.assertRaises(ContractError):
            self.apply(host, 'skip_next', FIRST, 0)
        self.tick(backend, FIRST)
        with self.assertRaises(ContractError):
            self.apply(host, 'skip_next', FIRST, 0)
        self.assertEqual(self.read(backend)['next_run_at'], SECOND)

    def test_concurrent_commands_only_change_the_expected_slot_once(self):
        backend = self.schedule(EmployeeSchedules)
        rendezvous = Barrier(2)

        def skip(turn):
            rendezvous.wait(timeout=5)
            try:
                return self.apply(Host(backend), 'skip_next', FIRST, 0, turn=turn)
            except ContractError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(result is not None for result in executor.map(skip, ('a', 'b'))), 1)
        plan = self.read(backend)
        self.assertEqual(plan['revision'], 1)
        self.assertEqual(plan['next_run_at'], SECOND)
        self.assertEqual(len(plan['runs']), 1)
        self.assertEqual(plan['runs'][0]['scheduled_for'], FIRST)

    def test_migrates_existing_schedule_and_clears_exception_when_cadence_is_replaced(self):
        backend = self.schedule(EmployeeSchedules)
        with backend.connection(write=True) as connection:
            connection.execute('DROP TRIGGER clear_occurrence_moves')
            connection.execute('DROP TABLE occurrence_moves')
        self.assertEqual(self.read(backend)['next_run_at'], FIRST)
        self.apply(Host(backend), 'move_next', FIRST, 0, move_to='2040-04-11T12:05:00+00:00')
        with backend.connection(write=True) as connection:
            connection.execute("UPDATE schedules SET interval_sec=1200,next_run_at=?", (THIRD,))
        self.assertEqual(self.read(backend)['next_run_at'], THIRD)

    def test_daily_and_weekly_follow_local_time_through_clock_change(self):
        for kind, config, expected in (
            ('daily', {'time': '09:00', 'timezone': 'America/New_York'}, '2026-03-08T13:00:00+00:00'),
            ('weekly', {'time': '09:00', 'weekdays': [5], 'timezone': 'America/New_York'},
             '2026-03-14T13:00:00+00:00'),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(single_occurrence.following({'schedule_kind': kind, 'schedule': json.dumps(config)},
                                                            '2026-03-07T14:00:00+00:00'), expected)


if __name__ == '__main__':
    unittest.main()
