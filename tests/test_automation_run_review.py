from contextlib import nullcontext
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import json

from runteams_core.automation import automation_run_review as review


class AutomationRunReviewTest(TestCase):
    def setUp(self):
        self.schedule = sqlite3.connect(':memory:')
        self.schedule.row_factory = sqlite3.Row
        self.schedule.executescript("""
          CREATE TABLE schedules(id INTEGER PRIMARY KEY, reference TEXT, name TEXT);
          CREATE TABLE occurrences(id INTEGER PRIMARY KEY, schedule_id INTEGER, status TEXT,
            reason TEXT, scheduled_for TEXT, snapshot TEXT, chat_id INTEGER, workflow_id INTEGER, operation_id TEXT);
        """)
        self.work = sqlite3.connect(':memory:')
        self.work.row_factory = sqlite3.Row
        self.work.executescript("""
          CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT, employee_reference TEXT,
            payload_json TEXT, trashed_at TEXT, pipeline_id INTEGER);
          CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY, task_id INTEGER, state TEXT,
            snapshot_json TEXT, created_at TEXT, updated_at TEXT DEFAULT '2026-11-23T01:00:00+00:00');
          CREATE TABLE employee_runs(id INTEGER PRIMARY KEY, workflow_run_id INTEGER, position_key TEXT,
            state TEXT, input_json TEXT, output_json TEXT, created_at TEXT, employee_release_id INTEGER);
          CREATE TABLE employee_releases(id INTEGER PRIMARY KEY, source_ref_json TEXT);
          CREATE TABLE events(id INTEGER PRIMARY KEY, stream TEXT, type TEXT, data_json TEXT);
          CREATE TABLE artifacts(id INTEGER PRIMARY KEY, employee_run_id INTEGER, name TEXT,
            ref TEXT, meta_json TEXT, trashed_at TEXT, created_at TEXT DEFAULT '2026-11-23T00:00:00+00:00');
        """)
        self.chats = sqlite3.connect(':memory:')
        self.chats.row_factory = sqlite3.Row
        self.chats.executescript("""
          CREATE TABLE chats(id INTEGER PRIMARY KEY, context_json TEXT, kind TEXT, subject_type TEXT);
          CREATE TABLE device_chat_index(chat_id INTEGER PRIMARY KEY, deleted INTEGER);
          CREATE TABLE chat_messages(id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, text TEXT, metadata TEXT, ts TEXT);
        """)
        self.addCleanup(self.schedule.close)
        self.addCleanup(self.work.close)
        self.addCleanup(self.chats.close)
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.core = SimpleNamespace(
            repository=SimpleNamespace(read_snapshot=lambda: nullcontext(self.work)), root=Path(folder.name),
            historical_document_detail=Mock(return_value={'name': 'Saved report', 'document_root_id': 79,
                                                          'revision': 1, 'content': 'Evidence matched.'}),
            is_document_artifact=lambda meta, name: meta.get('purpose') == 'document')
        self.host = SimpleNamespace(start=Mock(), artifact_downloads=True, backend=lambda _: SimpleNamespace(
            connection=lambda: nullcontext(self.schedule), controller_factory=lambda: SimpleNamespace(core=self.core)))
        self.enterContext(patch.object(review.device_data, 'connect', lambda **_: nullcontext(self.chats)))
        self.enterContext(patch('runteams_core.employees.employee_references.same', lambda l, r: l == r))
        self.enterContext(patch.object(review.work_reports, 'catalog', return_value=[]))

    def run_review(self, kind, ref, **arguments):
        for connection in (self.schedule, self.work, self.chats):
            connection.execute('PRAGMA query_only=ON')
        result = review.execute(self.host, kind=kind, reference=ref, arguments=arguments)
        self.host.start.assert_not_called()
        return result

    def add_schedule(self, ref, *, old_chat=None, workflow_id=None):
        self.schedule.execute('INSERT INTO schedules VALUES(1,?,?)', (review.canonical(ref), 'Old plan'))
        snapshot = {'reference': ref, 'name': 'Frozen plan', 'payload': {'parameters': {'prompt': 'actual old'}}}
        self.schedule.execute(
            "INSERT INTO occurrences VALUES(1,1,'completed','','2026-11-22T01:00:00+00:00',?,?,?,'occurrence-one')",
            (json.dumps(snapshot), old_chat, workflow_id))
        self.schedule.execute(
            "INSERT INTO occurrences VALUES(2,1,'queued','','2026-11-24T01:00:00+00:00',?,NULL,NULL,'next')",
            (json.dumps(snapshot),))

    def add_work(self, kind, ref):
        frozen = {'pipeline_work': {'reference': ref}} if kind == 'pipeline' else {'employee_reference': ref}
        payload = {'objective': 'Use the confirmed brief.', 'parameters': {'prompt': 'actual new'}}
        self.work.execute('INSERT INTO tasks VALUES(8,?,?,?,NULL,NULL)', ('Manual review', json.dumps(ref), json.dumps(payload)))
        self.work.execute("INSERT INTO workflow_runs(id,task_id,state,snapshot_json,created_at) "
                          "VALUES(10,8,'completed',?,'2026-11-23T00:00:00+00:00')",
                          (json.dumps(frozen),))
        self.work.execute(
            "INSERT INTO employee_runs VALUES(100,10,'review','completed',?,?,'2026-11-23T01:00:00+00:00',NULL)",
            (json.dumps({'payload': payload, 'chat_id': 45}), json.dumps({'output': {'token': 'RUN-10'}})))
        if kind == 'pipeline':
            for identifier, state in [(77, 'ready'), (79, 'completed'), (83, 'completed')]:
                self.add_artifact(identifier, {'source': 'pipeline_task_report', 'purpose': 'document',
                                   'pipeline_task_report': {'task_id': 8, 'workflow_id': 10, 'state': state}})
        self.chats.execute("INSERT INTO chats VALUES(45,?,'general','employee')",
                           (json.dumps({'employee_work': {'workflow_id': 10}}),))
        self.chats.execute('INSERT INTO device_chat_index VALUES(45,0)')
        proof = {'method': 'excerpt', 'name': 'reference.md', 'page': 1, 'offset': 0,
                 'excerpt_preview': 'RUN-10'}
        self.add_message(45, 1, 'user', 'Original handoff', {'background_work_operation': 'employee-work:10'})
        self.add_message(45, 2, 'bot', 'RUN-10', {'trace': {'complete': True, 'knowledge_reads': [proof]}})
        self.add_message(45, 3, 'user', 'A different turn', {})
        self.add_message(45, 4, 'bot', 'WRONG TURN', {'trace': {'complete': True}})

    def add_message(self, chat, mid, role, text, metadata):
        self.chats.execute('INSERT INTO chat_messages VALUES(?,?,?,?,?,?)',
                           (mid, chat, role, text, json.dumps(metadata), '2026-11-23T01:00:00+00:00'))

    def add_artifact(self, identifier, metadata, name='Saved report', ref=''):
        self.work.execute('INSERT INTO artifacts(id,name,ref,meta_json) VALUES(?,?,?,?)',
                          (identifier, name, ref, json.dumps(metadata)))

    def test_unspecified_review_prefers_actual_manual_work_to_old_automation(self):
        ref = {'schema': 'source-employee', 'source_id': 'source', 'employee_source': 'employee.json'}
        self.add_schedule(ref)
        self.add_work('employee', ref)
        artifact = self.core.root / 'artifacts' / 'data.csv'
        artifact.parent.mkdir()
        artifact.write_text('token\nRUN-10\n')
        self.add_artifact(20, {'workflow_id': 10}, name='data.csv', ref=str(artifact))
        result = self.run_review('employee', ref)
        self.assertEqual(result['source'], 'work_card')
        self.assertEqual(result['inputs']['parameters'], {'prompt': 'actual new'})
        self.assertEqual(result['knowledge_status'], 'excerpt_recorded')
        self.assertEqual(result['stages'][0]['saved_reply'], 'RUN-10')
        self.assertEqual(result['deliverables'][0]['download_link'], '/api/device/work/artifacts/20/content?download=1')
        self.host.artifact_downloads = False
        local_result = review.execute(self.host, kind='employee', reference=ref, arguments={})
        self.assertEqual(local_result['deliverable_status'], 'registered_without_link')
        self.assertEqual(local_result['deliverables'][0]['name'], 'data.csv')
        self.assertNotIn('download_link', local_result['deliverables'][0])
        result = self.run_review('employee', ref, id=1)
        self.assertEqual(result['frozen_schedule_input']['parameters'], {'prompt': 'actual old'})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['latest_trigger']['status'], 'queued')
        self.assertEqual(result['knowledge_status'], 'unverifiable')
        stranger = {**ref, 'source_id': 'different'}
        self.assertEqual(self.run_review('employee', stranger, id=1), {'status': 'no_execution_record'})

    def test_formal_worker_uses_only_host_run_knowledge_events(self):
        ref = {'schema': 'source-employee', 'source_id': 'source', 'employee_source': 'employee.json'}
        self.add_work('employee', ref)
        forged = {'method': 'excerpt', 'name': 'different-run.txt'}
        self.work.execute('UPDATE employee_runs SET input_json=?,output_json=? WHERE id=100',
            (json.dumps({'objective': 'Confirm ledger', 'parameters': {'text': 'actual SDK input'}}),
             json.dumps({'summary': 'Claims a read', 'knowledge_reads': [forged]})))
        self.work.execute("INSERT INTO events VALUES(1,'employee_run:99','knowledge.source_read',?)",
                          (json.dumps(forged),))
        self.work.execute("INSERT INTO events VALUES(2,'employee_run:100','employee.output',?)",
                          (json.dumps(forged),))
        self.work.execute("INSERT INTO events VALUES(3,'employee_run:100','knowledge.source_read',?)",
                          (json.dumps({'method': 'excerpt', 'name': 'ledger.txt', 'source': 'frozen-ledger',
                                       'page': 1, 'offset': 0, 'sha256': 'f' * 64}),))
        evidence = self.run_review('employee', ref)
        self.assertEqual(evidence['knowledge_status'], 'excerpt_recorded')
        self.assertEqual([item['name'] for item in evidence['knowledge_evidence']], ['ledger.txt'])
        self.assertEqual(evidence['stages'][0]['inputs']['parameters'], {'text': 'actual SDK input'})

    def test_pipeline_review_uses_scoped_work_and_can_open_existing_report(self):
        ref = {'schema': 'source-pipeline', 'source_id': 'source', 'pipeline_source': 'pipeline.json'}
        self.add_schedule(ref, workflow_id=10)
        self.add_work('pipeline', ref)
        result = self.run_review('pipeline', ref, automation_only=True)
        self.assertEqual(result['workflow_id'], 10)
        self.assertEqual(result['knowledge_evidence'][0]['name'], 'reference.md')
        self.assertEqual(result['stages'][0]['result'], {'token': 'RUN-10'})
        self.assertEqual(result['deliverables'][0]['internal_link'], 'runteams://document/79?revision=79')
        self.assertTrue(result['deliverables'][0]['final_revision'])
        self.core.historical_document_detail.assert_called_once_with(79)

    def test_pipeline_review_keeps_old_projection_without_claiming_final_delivery(self):
        ref = {'schema': 'source-pipeline', 'source_id': 'source', 'pipeline_source': 'pipeline.json'}
        self.add_work('pipeline', ref)
        self.work.execute('DELETE FROM artifacts')
        self.add_artifact(79, {'source': 'pipeline_task_report', 'purpose': 'document',
                              'pipeline_task_report': {'task_id': 8, 'workflow_id': 10}})
        result = self.run_review('pipeline', ref)
        projection, = result['deliverables']
        self.assertEqual(projection['internal_link'], 'runteams://document/79?revision=79')
        self.assertEqual(projection['revision_basis'], 'saved_task_projection')
        self.assertFalse(projection['final_revision'])

    def test_pipeline_review_uses_accepted_pin_and_never_substitutes_newer_revision(self):
        ref = {'schema': 'source-pipeline', 'source_id': 'source', 'pipeline_source': 'pipeline.json'}
        self.add_work('pipeline', ref)
        self.work.execute('DELETE FROM artifacts')
        frozen = {'pipeline_work': {'reference': ref}, 'pipeline_lineage': [100]}
        self.work.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=10', (json.dumps(frozen),))
        accepted = 'This is what the employee submitted.'
        digest = hashlib.sha256(accepted.encode()).hexdigest()
        pin = {'id': 79, 'artifact_id': 80, 'revision': 2, 'sha256': digest}
        self.work.execute('UPDATE employee_runs SET output_json=? WHERE id=100',
                          (json.dumps({'report_references': [pin]}),))
        for item, author in [(79, 'agent'), (80, 'agent'), (81, 'human'), (82, 'agent')]:
            self.add_artifact(item, {'revision_of': 79, 'purpose': 'document', 'author': author,
                                    'work_report': {'schema': review.work_reports.SCHEMA,
                                                    'workflow_id': 10, 'employee_run_id': 100}})
        self.core.historical_document_detail.return_value.update(revision=2, content=accepted)
        result = review._workflow_evidence(self.core, 'pipeline', ref, 10)
        self.assertEqual([item['internal_link'] for item in result['deliverables']],
                         ['runteams://document/79?revision=80'])
        self.assertEqual(result['deliverables'][0]['saved_excerpt'], accepted)
        self.core.historical_document_detail.assert_called_once_with(80)
        self.core.historical_document_detail.return_value['content'] = 'Changed bytes'
        result = review._workflow_evidence(self.core, 'pipeline', ref, 10)
        self.assertEqual(result['deliverables'], [])
        self.assertEqual(result['unavailable_report_revisions'][0]['revision'], 2)
        self.assertEqual(result['stages'][0]['saved_reply'], 'RUN-10')

    def test_scheduled_chat_review_does_not_treat_retrieved_file_or_self_report_as_read(self):
        ref = {'schema': 'source-employee', 'source_id': 'source', 'employee_source': 'employee.json'}
        self.add_schedule(ref, old_chat=45)
        self.schedule.execute("UPDATE occurrences SET status='cancelled' WHERE id=1")
        self.chats.execute("INSERT INTO chats VALUES(45,?,'general','employee')", (json.dumps({'source_employee': ref}),))
        self.chats.execute('INSERT INTO device_chat_index VALUES(45,0)')
        self.add_message(45, 1, 'user', 'Original request', {'background_work_operation': 'occurrence-one'})
        self.add_message(45, 2, 'bot', 'I read it', {'trace': {'cancelled': True,
            'knowledge_reads': [{'method': 'original', 'name': 'file.xlsx'}]}})
        result = self.run_review('employee', ref, automation_only=True)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['knowledge_status'], 'original_retrieved')
        self.assertEqual(result['accepted_message'], 'Original request')
        self.assertEqual(result['deliverable_status'], 'no_openable_record_found')

    def test_history_uses_actual_start_filters_and_scoped_keys(self):
        from runteams_core.automation import automation_run_history as history

        ref = {'schema': 'source-employee', 'source_id': 'source', 'employee_source': 'employee.json'}
        self.add_schedule(ref, workflow_id=10)
        self.add_work('employee', ref)
        for database in (self.work, self.schedule, self.chats):
            database.execute('PRAGMA query_only=ON')

        def query(**arguments):
            return history.execute(self.host, kind='employee', reference=ref, operation='history', arguments=arguments)

        found = query(query='Old plan', status='completed', since='2026-11-23T09:00:00+08:00',
                      until='2026-11-24T00:00:00+08:00')
        self.assertEqual([item['run_key'] for item in found['items']], ['automation:1'])
        self.assertEqual(query()['total'], 1)  # The work card is already in the schedule history.
        self.assertEqual(query(offset=1)['items'], [])
        self.assertEqual(query(until='2026-11-23T09:00:00+08:00')['items'], [])
        with self.assertRaises(ValueError):
            query(since='2026-11-23')
        for key in ('automation:1', 'work:10'):
            with self.assertRaises(ValueError):
                history.selected(self.host, 'employee', {**ref, 'source_id': 'stranger'}, key)
        self.assertEqual(history.selected(self.host, 'employee', ref, 'automation:1')['workflow_id'], 10)
        self.host.start.assert_not_called()
