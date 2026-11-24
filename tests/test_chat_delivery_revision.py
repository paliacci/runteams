import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from runteams_core.application.local_work_core import LocalWorkCore
from runteams_core.configuration.chat_setup import SetupTurn
from runteams_core.documents import chat_delivery_revision as tool, document_ownership
from runteams_core.foundation.contracts import ContractError
from runteams_core.storage import device_data


class DeliveryRevisionTest(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        scope = {'storage_kind': 'local', 'library_id': 'test', 'storage_namespace': 'test'}
        self.enterContext(patch.object(device_data, 'root', return_value=Path(directory)))
        self.enterContext(patch.object(device_data, 'identity', return_value=scope))
        self.enterContext(patch.object(device_data, 'personal', return_value=True))
        self.enterContext(patch('runteams_core.employees.employee_references.same', side_effect=lambda a, b: a == b))
        self.enterContext(patch('runteams_core.configuration.chat_setup._current_message', return_value='恢复第一版'))
        self.core = LocalWorkCore()
        self.employee = {'schema': 'employee', 'id': 'owned'}
        self.pipeline = {'schema': 'pipeline', 'id': 'owned'}
        self.employee_turn = SetupTurn(10, 15, 'epoch', scope, 'employee', self.employee, Event())
        self.pipeline_turn = SetupTurn(20, 16, 'epoch', scope, 'pipeline', self.pipeline, Event())

    def make(self, owner, *, name='Acceptance', previous='Saved version', latest='Current version'):
        marker = document_ownership._document_owner.set(owner)
        try:
            first = self.core.create_agent_document(name, previous)
        finally:
            document_ownership._document_owner.reset(marker)
        second = self.core.update_agent_document(first['id'], content=latest)
        return first, second

    def inspect(self, turn, identifier):
        return tool._execute(self.core, turn, {'operation': 'inspect', 'document_id': identifier}, '')['document']

    def arguments(self, turn, identifier, revision=1):
        current = self.inspect(turn, identifier)
        return {'operation': 'restore', 'document_id': identifier, 'revision': revision, 'intent': '恢复第一版',
                'expected_current_revision': current['current_revision'],
                'expected_current_token': current['current_revision_token']}

    def restore(self, turn, arguments):
        return tool._execute(self.core, turn, arguments, '请恢复第一版')

    def test_employee_exact_history_and_idempotent_receipt(self):
        first, second = self.make({'employee_reference': self.employee})
        args = self.arguments(self.employee_turn, first['id'])
        result = self.restore(self.employee_turn, args)
        self.assertEqual(result, self.restore(self.employee_turn, args))
        self.assertEqual(result['revision'], 3)
        self.assertEqual(self.core.document_detail(first['id'])['content'],
                         self.core.historical_document_detail(first['id'])['content'])
        latest = self.core.historical_document_detail(second['id'])
        self.assertIn('Current version', latest['content'])
        self.assertEqual(len(self.core.document_revisions(first['id'])), 3)
        self.assertIn('恢复自', self.core.document_revisions(first['id'])[-1]['note'])
        self.assertTrue(self.core.repository.verify_event_chain())

    def test_team_restore_creates_revision_even_when_body_identical_to_current(self):
        first, _ = self.make({'pipeline_reference': self.pipeline})
        self.core.update_agent_document(first['id'], content='Saved version')
        result = self.restore(self.pipeline_turn, self.arguments(self.pipeline_turn, first['id']))
        self.assertEqual(result['revision'], 4)
        self.assertEqual(self.inspect(self.pipeline_turn, first['id'])['current_artifact_id'], result['artifact_id'])

    def test_scope_and_stale_current_token_protect_existing_content(self):
        first, second = self.make({'employee_reference': self.employee})
        with self.assertRaises(PermissionError):
            self.inspect(self.pipeline_turn, first['id'])
        request = self.arguments(self.employee_turn, first['id'])
        with self.core.repository.connect() as connection:
            row = connection.execute('SELECT meta_json FROM artifacts WHERE id=?', (second['id'],)).fetchone()
            meta = json.loads(row[0])
            meta['note'] = 'Edited the same revision'
            connection.execute('UPDATE artifacts SET meta_json=? WHERE id=?', (json.dumps(meta), second['id']))
        with self.assertRaisesRegex(ContractError, '文档已被更新'):
            self.restore(self.employee_turn, request)
        self.assertEqual(len(self.core.document_revisions(first['id'])), 2)

    def test_formal_reports_cannot_be_restored_even_when_they_are_owned(self):
        first, second = self.make({'pipeline_reference': self.pipeline})
        with self.core.repository.connect() as connection:
            now = '2025-02-01T00:00:00+00:00'
            task = connection.execute(
                "INSERT INTO tasks(employee_reference,title,payload_json,state,created_at,updated_at) "
                "VALUES(?,'Task','{}','completed',?,?)", (json.dumps(self.employee), now, now)).lastrowid
            snapshot = {'pipeline_work': {'reference': self.pipeline}, 'pipeline_submission': {'reports': [{'id': first['id']}]}}
            work = connection.execute(
                "INSERT INTO workflow_runs(task_id,state,snapshot_json,created_at,updated_at) "
                "VALUES(?,'completed',?,?,?)", (task, json.dumps(snapshot), now, now)).lastrowid
            for item in (first, second):
                connection.execute("UPDATE artifacts SET meta_json=json_set(meta_json,'$.workflow_id',?) WHERE id=?",
                                   (work, item['id']))
        current = self.inspect(self.pipeline_turn, first['id'])
        self.assertEqual(current['reason'], 'formal_report')
        with self.assertRaisesRegex(ContractError, '正式汇报'):
            self.restore(self.pipeline_turn, self.arguments(self.pipeline_turn, first['id']))
        self.assertEqual(len(self.core.document_revisions(first['id'])), 2)

    def test_unowned_document_is_hidden_and_cannot_be_restored_by_the_team(self):
        first, _ = self.make({})
        view = tool._execute(self.core, self.pipeline_turn, {'operation': 'inspect'}, '')
        self.assertEqual(view['documents'], [])
        with self.assertRaises(PermissionError):
            self.inspect(self.pipeline_turn, first['id'])
        self.assertEqual(len(self.core.document_revisions(first['id'])), 2)
