from contextlib import contextmanager, nullcontext
import json
import sqlite3
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from runteams_core.automation import automation_rerun as rerun
from runteams_core.authoring.creator_contracts import digest
from runteams_core.foundation.contracts import ContractError


class AutomationRerunTest(TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE events(id INTEGER PRIMARY KEY, stream TEXT, type TEXT, data_json TEXT);
            CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY, task_id INTEGER, snapshot_json TEXT);
        ''')
        repository = SimpleNamespace(read_snapshot=lambda: nullcontext(self.db), connect=self.connect, event=self.event)
        self.core = SimpleNamespace(repository=repository, dispatch_task=Mock(side_effect=self.dispatch))
        wake = Mock()
        self.backend = SimpleNamespace(controller_factory=lambda: SimpleNamespace(core=self.core, wake=wake),
                                       validate_skill_parameters=Mock())
        self.host = SimpleNamespace(backend=lambda _: self.backend)
        self.reference = {'schema': 'runteams.business-reference/v1', 'id': 'employee'}
        self.original = {'run_key': 'automation:10', 'title': 'Morning review', 'status': 'completed',
                         'source': 'automation', 'frozen_schedule_input': {
                             'objective': 'Original objective', 'skill_key': 'review',
                             'parameters': {'audience': 'original', 'length': 'short'},
                         }}
        self.knowledge = {'sources': [], 'preferences': digest('')}
        self.enterContext(patch('runteams_core.storage.device_data.identity', return_value={'cache_scope': 'test'}))
        self.selected = self.enterContext(patch.object(rerun, 'selected', return_value=self.original))
        self.enterContext(patch.object(rerun, '_inventory', side_effect=lambda _: self.knowledge))
        self.enterContext(patch('runteams_core.automation.device_employee_schedules.record_id', return_value=34))
        self.enterContext(patch('runteams_core.automation.device_employee_schedules.employee', return_value={'id': 34}))

    @contextmanager
    def connect(self):
        with self.db:
            yield self.db

    def event(self, stream, kind, payload, *, connection):
        connection.execute('INSERT INTO events(stream,type,data_json) VALUES(?,?,?)', (stream, kind, json.dumps(payload)))

    def dispatch(self, title, payload, **options):
        self.db.execute('INSERT INTO workflow_runs VALUES(33,50,?)', (json.dumps({'definition': {}}),))
        return {'workflow_id': 33}

    def execute(self, changes=None, token=None, turn='chat-epoch:5'):
        arguments = {'run_key': 'automation:10'}
        if changes is not None:
            arguments['changes'] = changes
        if token is not None:
            arguments['knowledge_confirmation'] = token
        return rerun.execute(self.host, kind='employee', reference=self.reference, turn_key=turn, arguments=arguments)

    def test_downloaded_employee_work_admits_merged_frozen_inputs_once(self):
        changes = {'parameters': {'audience': 'new'}}
        result = self.execute(changes)
        self.assertEqual(result, self.execute(changes))
        self.assertEqual(result['source_run_key'], 'automation:10')
        self.assertEqual(result['run_key'], 'work:33')
        payload = self.core.dispatch_task.call_args.args[1]
        self.assertEqual(payload['parameters'], {'audience': 'new', 'length': 'short'})
        self.assertEqual(payload['objective'], 'Original objective')
        self.assertEqual(payload['skill_key'], 'review')
        self.assertEqual(self.original['frozen_schedule_input']['parameters']['audience'], 'original')
        self.assertEqual(self.core.dispatch_task.call_args.kwargs['employee_id'], 34)
        frozen = json.loads(self.db.execute('SELECT snapshot_json FROM workflow_runs').fetchone()[0])
        self.assertEqual(frozen['rerun']['source_run_key'], 'automation:10')
        with self.assertRaises(ContractError):
            self.execute({'objective': 'different'})
        self.assertEqual(self.core.dispatch_task.call_count, 1)

    def test_pipeline_rerun_uses_queued_revision_instead_of_original_schedule_or_later_handoffs(self):
        self.db.executescript("CREATE TABLE tasks(id INTEGER PRIMARY KEY, start_column_key TEXT,"
                              " payload_json TEXT, trashed_at TEXT); INSERT INTO tasks VALUES(50,'review','{}',NULL);")
        initial = {'objective': 'Original objective', 'parameters': {'region': 'east'}}
        queued = {'objective': 'Edited objective', 'parameters': {'region': 'south'}}
        snapshot = {'initial_pipeline_input': initial, 'queued_pipeline_input': queued,
                    'pipeline_input': {**queued, 'parameters': {'region': 'south', 'derived': 'handoff'}}}
        self.db.execute('INSERT INTO workflow_runs VALUES(33,50,?)', (json.dumps(snapshot),))
        original = {**self.original, 'workflow_id': 33}
        work, position, _ = rerun._source(self.core, original)
        self.assertEqual(work['objective'], queued['objective'])
        self.assertEqual(work['parameters'], queued['parameters'])
        self.assertEqual(position, 'review')

    def test_legacy_disclosure_requires_later_confirmation_for_exact_knowledge(self):
        self.knowledge['preferences'] = digest('New instructions')
        choices = self.execute()
        self.assertEqual(choices['status'], 'knowledge_confirmation_required')
        token = choices['knowledge_confirmation']
        self.assertEqual(self.execute(token=token)['status'], 'knowledge_confirmation_required')
        self.assertEqual(self.execute(token=token, turn='different-chat:8')['status'], 'knowledge_confirmation_required')
        self.knowledge['preferences'] = digest('Second revision')
        updated = self.execute(token=token, turn='chat-epoch:8')
        self.assertEqual(updated['status'], 'knowledge_confirmation_required')
        self.core.dispatch_task.assert_not_called()
        latest = updated['knowledge_confirmation']
        accepted = self.execute(token=latest, turn='chat-epoch:9')
        self.assertEqual(accepted['status'], 'queued')
        self.assertEqual(accepted, self.execute(token=latest, turn='chat-epoch:10'))
        self.core.dispatch_task.assert_called_once()

    def test_scheduled_source_employee_without_workflow_admits_work_card(self):
        from runteams_core.employees.employee_references import SOURCE_SCHEMA
        self.reference = {'schema': SOURCE_SCHEMA, 'source_id': 'example', 'employee_source': 'employee.json'}
        def admit(core, reference, package, title, payload, link):
            with self.db:
                rerun.record(core, self.db, link, 33, 50, title)
        with patch('runteams_core.employees.source_employee_runtime.prepare', return_value={'package': True}) as prepare, \
                patch('runteams_core.employees.employee_chat_work.admit_rerun', side_effect=admit) as submit:
            result = self.execute({'objective': 'New objective'})
            self.assertEqual(result['source_run_key'], 'automation:10')
            self.assertEqual(result['workflow_id'], 33)
            self.assertEqual(prepare.call_args.args[0], self.reference)
            self.assertEqual(submit.call_args.args[4]['objective'], 'New objective')
            self.assertEqual(submit.call_args.args[4]['parameters']['audience'], 'original')
            self.assertNotIn('workflow_id', self.original)
        self.core.dispatch_task.assert_not_called()

    def test_team_uses_frozen_schedule_start_and_input(self):
        self.original['start_column_key'] = 'review'
        self.original['inputs'] = {'objective': 'Later stage details', 'parameters': {'audience': 'different'}}
        def create(core, data, *, rerun):
            with self.db:
                from runteams_core.automation.automation_rerun import record
                record(core, self.db, rerun, 33, 50, data['title'])
        with patch('runteams_core.pipelines.source_pipeline_work.create', side_effect=create) as submit:
            result = rerun.execute(self.host, kind='pipeline', reference={'pipeline_source': 'pipeline.json'},
                                   turn_key='chat-epoch:5', arguments={'run_key': 'automation:10'})
            data = submit.call_args.args[1]
            self.assertEqual(data['start_column_key'], 'review')
            self.assertEqual(data['payload']['objective'], 'Original objective')
            self.assertEqual(data['payload']['parameters']['audience'], 'original')
            self.assertEqual(result['run_key'], 'work:33')

    def test_changed_knowledge_after_native_admission_blocks_worker(self):
        from runteams_core.work.source_work_service import SourceWorkService

        worker = Mock(return_value='completed')
        class NativeWorker:
            execute_claimed_workflow = worker

        class Core(SourceWorkService, NativeWorker):
            repository = self.core.repository

        runtime = object()
        self.execute()
        core = Core()
        self.assertEqual(core.execute_claimed_workflow(33, runtime), 'completed')
        worker.assert_called_once_with(33, runtime, 3, 5)
        worker.reset_mock()
        self.knowledge = {'sources': [{'id': 1, 'name': 'New file', 'version': 'new'}],
                          'preferences': digest('')}
        with patch('runteams_core.employees.employee_chat_work.finish', return_value='needs_human') as finish:
            self.assertEqual(core.execute_claimed_workflow(33, runtime), 'needs_human')
            self.assertEqual(finish.call_args.args[:3], (core, 33, 'blocked'))
        worker.assert_not_called()

    def test_legacy_read_preview_proves_material_replacement(self):
        original = {**self.original, 'knowledge_evidence': [
            {'name': 'Reference.txt', 'method': 'excerpt', 'excerpt_preview': 'Old evidence'},
        ]}
        current = {'preferences': digest(''), 'sources': [
            {'id': 1, 'name': 'Reference.txt', 'version': 'new'},
        ]}
        with patch('runteams_core.assets.bundled_knowledge.catalog', return_value={}), \
                patch('runteams_core.conversations.asset_memory.bank_for', return_value='test'), \
                patch('runteams_core.conversations.asset_sources.excerpt', return_value={'text': 'New evidence'}):
            changes = rerun._knowledge_changes(self.reference, original, current, None)
        self.assertEqual(changes, [{'name': 'Reference.txt', 'change': 'changed'}])

    def test_excerpt_hash_is_distinct_from_source_revision(self):
        proof = {'name': 'Reference.txt', 'method': 'excerpt', 'source': 1, 'sha256': 'excerpt-hash'}
        original = {**self.original, 'knowledge_evidence': [proof]}
        current = {'preferences': digest(''), 'sources': [
            {'id': 1, 'name': 'Reference.txt', 'origin': 'personal', 'version': 'revision'},
        ]}
        self.assertEqual(rerun._knowledge_changes(self.reference, original, current, None),
                         [{'name': 'Reference.txt', 'change': 'historical_version_unverified'}])
        proof['revision'] = 'revision'
        self.assertEqual(rerun._knowledge_changes(self.reference, original, current, None), [])
        proof['revision'] = 'earlier-revision'
        self.assertEqual(rerun._knowledge_changes(self.reference, original, current, None),
                         [{'name': 'Reference.txt', 'change': 'changed'}])

    def test_known_knowledge_inventory_describes_precise_changes(self):
        baseline = {'preferences': 'x', 'sources': [
            {'id': 1, 'name': 'Same name', 'version': 'old'},
            {'id': 2, 'name': 'Old file', 'version': 'old'},
        ]}
        current = {'preferences': 'y', 'sources': [
            {'id': 1, 'name': 'Same name', 'version': 'new'},
            {'id': 3, 'name': 'New file', 'version': 'new'},
        ]}
        changes = rerun._knowledge_changes(self.reference, self.original, current, baseline)
        self.assertEqual(changes, [
            {'name': 'Same name', 'change': 'changed'},
            {'name': 'Old file', 'change': 'removed'},
            {'name': 'New file', 'change': 'added'},
            {'name': '长期偏好', 'change': 'changed'},
        ])
