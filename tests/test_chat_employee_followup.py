from contextlib import nullcontext
import json
import sqlite3
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from runteams_core.employees import chat_employee_followup as followup
from runteams_core.foundation.contracts import ContractError


class EmployeeFollowupTests(TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT, employee_reference TEXT,
              payload_json TEXT, state TEXT, trashed_at TEXT, pipeline_snapshot_json TEXT, updated_at TEXT);
            CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY, task_id INTEGER, state TEXT,
              available_at TEXT, snapshot_json TEXT, updated_at TEXT);
            CREATE TABLE employee_runs(id INTEGER PRIMARY KEY, workflow_run_id INTEGER, attempt INTEGER, state TEXT);
            CREATE TABLE events(id INTEGER PRIMARY KEY, stream TEXT, type TEXT, data_json TEXT);
        ''')
        self.reference = {'published': 'account-owned fixture reference'}
        self.scope = {'account_id':'fixture'}
        self.wake = Mock()
        self.turn = followup._Turn(3, 8, self.scope, self.reference, 'epoch1', Event(), self.wake)
        self.message = {'role': 'user', 'text': '使用本轮补充附件及内容 B，续办原工单。', 'attachments': [
            {'id': 'fixture-attachment', 'kind': 'file', 'name': 'source.txt'}]}
        repository = SimpleNamespace(connect=lambda: self.db, read_snapshot=lambda: nullcontext(self.db),
                                     storage=SimpleNamespace(assert_executable=Mock()), event=self.event)
        self.core = SimpleNamespace(repository=repository, _actor=Mock(), root='/not-used-by-test')
        self.enterContext(patch.object(followup, '_message', return_value=self.message))
        self.enterContext(patch.object(followup.employee_references, 'same', side_effect=lambda a,b:a==b))
        self.enterContext(patch.object(followup.employee_references, 'key', side_effect=lambda ref:json.dumps(ref)))
        self.copy = self.enterContext(patch('runteams_core.work.task_inputs.copy_chat_attachment', return_value={
            'name': 'source.txt', 'id': 'pinned-id', 'ref': 'immutable-fixture-copy'}))

    def event(self, stream, kind, value, *, connection):
        connection.execute('INSERT INTO events(stream,type,data_json) VALUES(?,?,?)',
                           (stream, kind, json.dumps(value)))

    def fixture(self, identifier=11, state='needs_human', *, attempted=True, reference=None):
        reference = self.reference if reference is None else reference
        frozen = {'schema': followup.employee_work_contracts.SCHEMA, 'employee_reference': reference}
        if attempted:
            frozen.update(work_chat_id=45, employee_run_id=80+identifier, send_admitted=True)
        with self.db as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,NULL,?,?)', (100+identifier, 'Original', json.dumps(reference),
                       json.dumps({'objective':'original objective','parameters':{'region':'east'}, 'inputs':[]}),
                       state, json.dumps(frozen), 'updated'))
            db.execute('INSERT INTO workflow_runs VALUES(?,?,?,?,?,?)', (identifier, 100+identifier,
                       state, None, json.dumps(frozen), 'updated'))
            self.event(f'workflow_run:{identifier}', f'workflow.{state}', {'reason':'missing required attachment'},
                       connection=db)
            if attempted:
                db.execute('INSERT INTO employee_runs VALUES(?,?,?,?)', (frozen['employee_run_id'], identifier, 1, state))

    def call(self, operation, **arguments):
        return followup._execute(self.core, self.turn, {'operation': operation, **arguments})

    def test_current_attachment_queues_existing_order_once(self):
        self.fixture()
        inspect = self.call('inspect', workflow_id=11)
        self.assertEqual(inspect['actions'], ['continue_work'])
        self.assertEqual(inspect['reason'], 'missing required attachment')
        args = dict(workflow_id=11, revision=inspect['revision'], intent=self.message['text'],
                    response='内容 B', attachment_ids=['fixture-attachment'])
        receipt = self.call('continue_work', **args)
        self.assertEqual(receipt, self.call('continue_work', **args))
        self.assertEqual(receipt, self.call('receipt', workflow_id=11, action='continue_work'))
        self.assertEqual(receipt['receipt']['task_id'], 111)
        self.wake.assert_called_once_with(11)
        self.copy.assert_called_once()
        self.assertEqual(self.db.execute('SELECT id,attempt,state FROM employee_runs').fetchone()[:], (91,1,'needs_human'))
        row = self.db.execute('SELECT state,snapshot_json FROM workflow_runs').fetchone()
        self.assertEqual(row['state'], 'ready')
        self.assertEqual(json.loads(row['snapshot_json'])['work_chat_id'], 45)
        updated = json.loads(self.db.execute('SELECT payload_json FROM tasks').fetchone()[0])
        self.assertEqual(updated['objective'], 'original objective')
        self.assertEqual(updated['parameters'], {'region':'east'})
        self.assertEqual(updated['inputs'][0]['ref'], 'immutable-fixture-copy')
        with self.assertRaises(ContractError):
            self.call('continue_work', **{**args, 'response':'续办原工单'})

    def test_old_attachment_stale_revision_and_unknown_send_do_not_enqueue(self):
        self.fixture()
        good = self.call('inspect', workflow_id=11)
        args = dict(workflow_id=11, revision=good['revision'], intent=self.message['text'],
                    attachment_ids=['old-attachment'])
        with self.assertRaises(PermissionError):
            self.call('continue_work', **args)
        self.db.execute("UPDATE workflow_runs SET state='interrupted' WHERE id=11")
        self.db.commit()
        args['attachment_ids'] = ['fixture-attachment']
        with self.assertRaises(ContractError):
            self.call('continue_work', **args)
        self.assertEqual(self.call('inspect', workflow_id=11)['actions'], [])
        self.copy.assert_not_called()
        self.wake.assert_not_called()

    def test_list_filters_completed_and_foreign_before_paging(self):
        self.fixture(11, attempted=False)
        self.fixture(12, attempted=False)
        self.fixture(13, 'completed')
        self.fixture(14, reference={'other': 'employee'})
        first = self.call('list', limit=1)
        self.assertEqual([item['workflow_id'] for item in first['items']], [12])
        self.assertEqual(first['next_before_id'], 12)
        second = self.call('list', limit=1, before_id=12)
        self.assertEqual([item['workflow_id'] for item in second['items']], [11])
        self.assertIsNone(second['next_before_id'])
        with self.assertRaises(PermissionError):
            self.call('inspect', workflow_id=14)

    def test_retry_only_for_known_unsent_original(self):
        self.fixture(attempted=False)
        inspected = self.call('inspect', workflow_id=11)
        self.assertEqual(inspected['actions'], ['continue_work','retry'])
        result = self.call('retry', workflow_id=11, revision=inspected['revision'], intent=self.message['text'])
        self.assertEqual(result['receipt']['previous_attempt_count'], 0)
        self.wake.assert_called_once_with(11)
