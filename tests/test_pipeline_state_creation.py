"""Creating directly in a board state persists there without employee execution."""
import copy
import json
import sqlite3
import tempfile
import uuid
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from runteams_core.pipelines import source_pipeline_work as work
from runteams_core.pipelines import source_pipeline_flow as flow
from runteams_core.pipelines import source_pipeline_control as control
from runteams_core.foundation.contracts import ContractError


class StateCreationTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / 'work.db'
        with self.connect() as c:
            c.executescript('''
                CREATE TABLE tasks(id INTEGER PRIMARY KEY, employee_reference TEXT, title TEXT,
                  payload_json TEXT, state TEXT, start_column_key TEXT, pipeline_snapshot_json TEXT,
                  created_at TEXT, updated_at TEXT, trashed_at TEXT);
                CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY, task_id INTEGER, state TEXT,
                  available_at TEXT, cursor_key TEXT, snapshot_json TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE events(id INTEGER PRIMARY KEY, stream TEXT, type TEXT, data_json TEXT);
            ''')
        self.asset = {'employees': [{'ref': 'writer', 'source': 'writer.json'}], 'pipeline': {
            'name': 'Fixture', 'positions': [
                {'key': 'write', 'kind': 'employee', 'name': 'Writer', 'employee_ref': 'writer', 'skill_key': 'write'},
                {'key': 'review', 'kind': 'approval', 'name': 'Review'}],
            'states': [{'key': k, 'kind': k, 'name': k} for k in ('done', 'dropped', 'pool')]}}
        self.context = {'asset': self.asset, 'reference': {}, 'position_key': 'write'}
        self.role = {'package': {'reference': {}}, 'context': self.context, 'configuration': None}
        self.bundle = {'asset': self.asset, 'revision': 'revision', 'generation': 1, 'roles': {'write': self.role}}
        self.active = {'status': 'running', 'bundle': self.bundle}
        self.core = SimpleNamespace(_actor=lambda: None, repository=SimpleNamespace(connect=self.connect, event=self.event))

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def event(self, stream, kind, data, *, connection):
        connection.execute('INSERT INTO events(stream,type,data_json) VALUES(?,?,?)', (stream, kind, json.dumps(data)))

    def request(self, key):
        return {'operation_id': str(uuid.uuid4()), 'reference': {}, 'start_column_key': key, 'title': 'Recorded task',
                'payload': {'schema': 'runteams.task-input/v2', 'objective': 'Record this task',
                            'context': {}, 'parameters': {}, 'inputs': [], 'module_bindings': {}, 'asset_bindings': {}}}

    @contextmanager
    def runtime(self):
        with ExitStack() as stack:
            for target, value in [
                ('runteams_core.pipelines.pipeline_references.checked_reference', lambda ref: ref),
                ('runteams_core.pipelines.source_pipeline_work.source', lambda ref: SimpleNamespace(locked=nullcontext, _head=lambda: 'revision')),
                ('runteams_core.pipelines.source_pipeline_control.read', lambda *args: self.active),
                ('runteams_core.pipelines.source_pipeline_control.admit', lambda *args: (self.role, 1)),
                ('runteams_core.pipelines.pipeline_position_runtime.refresh_bundle', lambda ref, bundle: bundle),
                ('runteams_core.employees.employee_context.current', lambda: SimpleNamespace(validate_package=lambda p: None)),
                ('runteams_core.pipelines.source_pipeline_work.verify_context', lambda *args, **kwargs: None),
                ('runteams_core.pipelines.source_pipeline_work.stage_snapshot', lambda *args: {'pipeline_work': copy.deepcopy(self.context), 'employee_reference': {}}),
                ('runteams_core.agents.language_policy.snapshot', lambda: {'communication_language': 'en'}),
                ('runteams_core.pipelines.pipeline_task_report.sync', lambda *args: None),
                ('runteams_core.pipelines.source_pipeline_work._project', lambda core, req, identifier, key: identifier),
            ]:
                stack.enter_context(patch(target, value))
            prepare = stack.enter_context(patch.object(flow, 'payload_for', return_value={'objective': 'Prepared'}))
            yield prepare

    def test_states_persist_atomically_and_retry_does_not_duplicate(self):
        with self.runtime() as prepare:
            for key, state in [('done', 'completed'), ('dropped', 'canceled'), ('pool', 'blocked')]:
                request = self.request(key)
                identifier = work.create(self.core, request)
                self.assertEqual(work.create(self.core, request), identifier)
                with self.connect() as c:
                    row = c.execute('SELECT * FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
                    task = c.execute('SELECT * FROM tasks WHERE id=?', (row['task_id'],)).fetchone()
                    self.assertEqual((row['state'], task['state'], row['cursor_key'], task['start_column_key']), (state, state, key, key))
                    self.assertIsNone(row['available_at'])
                    self.assertEqual(json.loads(task['payload_json']), request['payload'])
                    frozen = json.loads(row['snapshot_json'])
                    self.assertNotIn('employee_run_id', frozen)
                    self.assertNotIn('pipeline_waiting', frozen)
                    event = c.execute("SELECT data_json FROM events WHERE stream=? AND type='workflow.created'", ('workflow_run:'+str(identifier),)).fetchone()
                    self.assertEqual(json.loads(event[0])['position_key'], key)
            prepare.assert_not_called()
            with self.connect() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0], 3)

    def test_employee_and_approval_entries_keep_existing_behavior(self):
        with self.runtime() as prepare:
            for key, state in [('write', 'ready'), ('review', 'needs_approval')]:
                identifier = work.create(self.core, self.request(key))
                with self.connect() as c:
                    row = c.execute('SELECT * FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
                    self.assertEqual(row['state'], state)
                    if key == 'review':
                        self.assertEqual(json.loads(row['snapshot_json'])['pipeline_waiting']['position_key'], key)
            prepare.assert_called_once()

    def test_invalid_position_and_paused_pipeline_do_not_create_tasks(self):
        with self.runtime():
            with self.assertRaises(ContractError):
                work.create(self.core, self.request('missing'))
            self.active['status'] = 'paused'
            with self.assertRaises(ContractError):
                work.create(self.core, self.request('done'))
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
