"""The title-only board command reaches the selected position's execution boundary."""
import copy
import json
import threading
import uuid
from contextlib import ExitStack, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from runteams_core.application.http.local_pipeline_http import dispatch
from runteams_core.application.local_runtime import LocalRuntime
from runteams_core.application.local_work_core import LocalWorkCore
from runteams_core.employees import employee_context
from runteams_core.pipelines import pipeline_position_runtime, pipeline_task_report, source_pipeline_control as control
from runteams_core.pipelines import source_pipeline_flow as flow, source_pipeline_work as work
from runteams_core.storage import device_data
from runteams_core.storage.repository import Repository
from runteams_core.work.device_work import DeviceWorkStorage
from runteams_core.work.work_ledger import WorkLedger


class CardDispatchTests(TestCase):
    def setUp(self):
        stack = ExitStack(); self.addCleanup(stack.close)
        root = Path(stack.enter_context(TemporaryDirectory()))
        identity = {'storage_kind': 'local', 'library_id': 'card-dispatch-test', 'storage_namespace': 'card-dispatch-test'}
        for key, value in [('root', root), ('identity', identity), ('personal', True), ('check', None)]:
            stack.enter_context(patch.object(device_data, key, return_value=value))
        storage = DeviceWorkStorage(); storage.initialize()
        repository = Repository(storage.path, storage=storage)
        self.reference = {'schema': 'runteams.local-pipeline-reference/1', 'storage_kind': 'local', 'library_id': 'card-dispatch-test', 'source_id': 'a'*64, 'pipeline_source': 'pipelines/example.json'}
        asset = {'employees': [{'ref': 'first-worker'}, {'ref': 'second-worker'}], 'pipeline': {
            'name': 'Isolated pipeline', 'positions': [
                {'key': 'first', 'kind': 'employee', 'name': 'First', 'employee_ref': 'first-worker', 'skill_key': 'work'},
                {'key': 'second', 'kind': 'employee', 'name': 'Second', 'employee_ref': 'second-worker', 'skill_key': 'work'}],
            'edges': [], 'states': []}}
        roles = {key: {'package': {'reference': {}, 'runtime': {}}, 'configuration': None,
                      'context': {'reference': self.reference, 'asset': asset, 'position_key': key}}
                 for key in ('first', 'second')}
        candidate = {'asset': asset, 'roles': roles, 'revision': 'fixed', 'generation': 1}
        self.state = {'status': 'running', 'bundle': candidate}
        self.executed = []; self.done = threading.Event()
        test = self

        class Core(WorkLedger):
            _workflow_claim_filter = LocalWorkCore._workflow_claim_filter
            def _actor(self): pass
            def runtime(self): return 'isolated-execution-boundary'
            def execute_claimed_workflow(self, identifier, runtime):
                # Stop at the executor boundary; this test never invokes a model.
                with self.repository.connect() as connection:
                    row = connection.execute('SELECT * FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
                    test.executed.append((identifier, row['state'], row['cursor_key'],
                                          json.loads(row['snapshot_json'])['pipeline_work']['position_key'], runtime))
                    connection.execute("UPDATE workflow_runs SET state='completed' WHERE id=?", (identifier,))
                    connection.execute("UPDATE tasks SET state='completed' WHERE id=?", (row['task_id'],))
                test.done.set()

        self.core = Core(); self.core.repository = repository
        self.core._cancel_lock = threading.Lock(); self.core._cancel_events = {}
        runtime = SimpleNamespace(lock=threading.RLock(), employee_jobs={}, _pending_work_wakes=set(), closing=False,
            app=SimpleNamespace(request=nullcontext, binding=SimpleNamespace(library_id='card-dispatch-test')),
            scope=nullcontext, work_core=lambda: self.core, schedule_host=lambda: SimpleNamespace(activate_existing=lambda: None))
        runtime.activate_employee_host = lambda: LocalRuntime.activate_employee_host(runtime)
        runtime.schedule_employee_work = lambda cards: LocalRuntime.schedule_employee_work(runtime, cards)
        self.runtime = runtime
        self.addCleanup(lambda: [thread.join(2) for thread in list(runtime.employee_jobs.values())])
        with repository.connect() as connection:
            repository.event('source-pipeline-runtime:' + self.reference['source_id'] + ':' + self.reference['pipeline_source'],
                             'pipeline.runtime_state', {'status': 'running'}, connection=connection)
        revisions = SimpleNamespace(locked=nullcontext, _head=lambda: 'fixed')
        for target, name, replacement in [
            (work, 'source', lambda _: revisions), (work, 'verify_context', lambda *_args, **_kwargs: None),
            (work.rented_references, 'is_rented', lambda _: False),
            (employee_context, 'current', lambda: SimpleNamespace(validate_package=lambda _: None)),
            (control, 'read', lambda *_args, **_kwargs: self.state),
            (pipeline_position_runtime, 'refresh_bundle', lambda _ref, bundle: bundle),
            (pipeline_task_report, 'sync', lambda *_args: None),
            (work, 'stage_snapshot', lambda package, context, configuration: {
                'schema': 'runteams.employee-chat-work/v1', 'package': package,
                'employee_reference': {}, 'definition': {'positions': [], 'edges': []}, 'pipeline_work': context}),
            (flow, 'payload_for', lambda _core, _connection, frozen, _role: copy.deepcopy(frozen['pipeline_input']))]:
            stack.enter_context(patch.object(target, name, side_effect=replacement))
        stack.enter_context(patch('runteams_core.pipelines.pipeline_task_configuration.fields', return_value=[]))
        stack.enter_context(patch('runteams_core.agents.language_policy.snapshot', return_value={'communication_language': 'zh-CN'}))
        def project(core, request, identifier, key):
            with repository.connect() as connection:
                row = connection.execute('SELECT id,state,cursor_key FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
                return {'workflow': dict(row)}
        stack.enter_context(patch.object(work, '_project', side_effect=project))
        self.command = {'operation_id': str(uuid.uuid4()), 'reference': self.reference,
            'start_column_key': 'second', 'title': 'Title-only fixture', 'payload': {
                'schema': 'runteams.task-input/v2', 'objective': 'Title-only fixture', 'parameters': {},
                'context': {}, 'inputs': [], 'module_bindings': {}, 'asset_bindings': {}}}

    def test_admission_starts_selected_position_once_and_receipt_replay_does_not_start_again(self):
        result = dispatch(self.runtime, 'POST', '/api/device/work/source-pipelines/dispatch', self.command)
        self.assertTrue(self.done.wait(2), 'admitted work did not reach the execution boundary')
        for thread in list(self.runtime.employee_jobs.values()): thread.join(2)
        self.assertEqual(self.executed, [(result['workflow']['id'], 'running', 'second', 'second', 'isolated-execution-boundary')])
        dispatch(self.runtime, 'POST', '/api/device/work/source-pipelines/dispatch', self.command)
        for thread in list(self.runtime.employee_jobs.values()): thread.join(2)
        self.assertEqual(len(self.executed), 1)
        with self.core.repository.connect() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events WHERE type='workflow.claimed'").fetchone()[0], 1)

    def test_paused_pipeline_refuses_admission_and_does_not_wake_executor(self):
        self.state['status'] = 'paused'
        from runteams_core.foundation.contracts import ContractError
        wake = Mock(); self.runtime.activate_employee_host = wake
        with self.assertRaisesRegex(ContractError, '已暂停'):
            dispatch(self.runtime, 'POST', '/api/device/work/source-pipelines/dispatch', self.command)
        wake.assert_not_called(); self.assertEqual(self.executed, [])

    def card(self, action, identifier=None, **fields):
        from runteams_core.pipelines.pipeline_card_actions import command
        if identifier is None:
            identifier = work.create(self.core, self.command)['workflow']['id']
        with self.core.repository.connect() as connection:
            frozen = json.loads(connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()[0])
        data = {'operation_id': str(uuid.uuid4()), 'reference': self.reference, 'workflow_id': identifier,
                'expected_visit': frozen['pipeline_visit'], 'action': action, **fields}
        return command(self.core, data), data

    def test_pause_prevents_claim_and_receipt_replay_does_not_pause_again(self):
        from runteams_core.pipelines.pipeline_card_actions import command
        out, data = self.card('pause'); identifier = out['workflow']['id']
        self.assertEqual(out['workflow']['state'], 'paused')
        self.assertIsNone(self.core.claim_workflow(identifier))
        self.card('resume', identifier)
        replay = command(self.core, data)
        self.assertEqual(replay['workflow']['state'], 'ready')
        self.assertEqual(replay['receipt']['action'], 'pause')

    def test_editor_preserves_manual_pause_and_queued_edit_gets_five_seconds(self):
        out, _ = self.card('pause'); identifier = out['workflow']['id']
        self.card('edit', identifier, title='Changed', expected_title='Title-only fixture', resume_after_edit=False)
        self.assertIsNone(self.core.claim_workflow(identifier))
        out, _ = self.card('edit', identifier, title='Changed again', expected_title='Changed', resume_after_edit=True)
        self.assertEqual(out['workflow']['state'], 'ready')
        self.assertIsNone(self.core.claim_workflow(identifier), 'editing must not start work before the grace period')
        with self.core.repository.connect() as connection:
            row = connection.execute('SELECT title,payload_json FROM tasks').fetchone()
            self.assertEqual(row['title'], 'Changed again')
            self.assertEqual(json.loads(row['payload_json'])['objective'], 'Changed again')

    def test_edit_rejects_claim_races_and_stale_titles_without_losing_saved_title(self):
        from runteams_core.foundation.contracts import ContractError
        identifier = work.create(self.core, self.command)['workflow']['id']
        with self.assertRaisesRegex(ContractError, '已被修改'):
            self.card('edit', identifier, title='Stale overwrite', expected_title='Old', resume_after_edit=False)
        self.assertEqual(self.core.claim_workflow(identifier), identifier)
        with self.assertRaisesRegex(ContractError, '已经开始'):
            self.card('edit', identifier, title='Too late', expected_title='Title-only fixture', resume_after_edit=False)

    def test_trash_retains_rows_and_restore_never_claims_automatically(self):
        from runteams_core.pipelines.pipeline_card_actions import trash_catalog
        out, _ = self.card('trash'); identifier = out['workflow']['id']
        self.assertTrue(out['workflow']['trashed_at'])
        items = trash_catalog(self.core)
        self.assertEqual(items[0]['id'], identifier)
        self.assertFalse(items[0]['can_delete'])
        out, _ = self.card('restore', identifier)
        self.assertEqual(out['workflow']['state'], 'paused')
        self.assertIsNone(out['workflow']['trashed_at'])
        self.assertEqual(trash_catalog(self.core), [])
        self.assertIsNone(self.core.claim_workflow(identifier))
        self.card('resume', identifier)
        self.assertEqual(self.core.claim_workflow(identifier), identifier)

    def test_restore_completed_stays_completed_and_sent_work_requires_review(self):
        out, _ = self.card('trash'); identifier = out['workflow']['id']
        with self.core.repository.connect() as connection:
            connection.execute("UPDATE workflow_runs SET state='completed' WHERE id=?", (identifier,))
        out, _ = self.card('restore', identifier)
        self.assertEqual(out['workflow']['state'], 'completed')
        self.card('trash', identifier)
        with self.core.repository.connect() as connection:
            row = connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
            frozen = json.loads(row[0]); frozen['send_admitted'] = True
            connection.execute("UPDATE workflow_runs SET state='canceled',snapshot_json=? WHERE id=?", (json.dumps(frozen), identifier))
        self.card('restore', identifier)
        out, _ = self.card('resume', identifier)
        self.assertEqual(out['workflow']['state'], 'interrupted')
        self.assertIsNone(self.core.claim_workflow(identifier))

    def test_card_operations_validate_ownership_replay_and_global_pause(self):
        from runteams_core.foundation.contracts import ContractError
        from runteams_core.pipelines.pipeline_card_actions import command
        out, data = self.card('pause'); identifier = out['workflow']['id']
        self.state['status'] = 'paused'
        with self.assertRaisesRegex(ContractError, '启动流水线'):
            self.card('resume', identifier)
        with self.assertRaises(PermissionError):
            command(self.core, {**data, 'reference': {**self.reference, 'source_id': 'b'*64}})
        with self.assertRaisesRegex(ContractError, '其他内容'):
            command(self.core, {**data, 'action': 'resume'})
        missing = command(self.core, {**data, 'operation_id': str(uuid.uuid4()), 'action': 'resume'}, read_only=True)
        self.assertEqual(missing['status'], 'unknown')
        self.assertEqual(self.executed, [])

    def test_stopping_waits_for_execution_settlement_before_trashing(self):
        from runteams_core.pipelines.pipeline_card_actions import command, capabilities
        identifier = work.create(self.core, self.command)['workflow']['id']
        self.core.workflow = lambda identifier: {'id': identifier}
        self.core.claim_workflow(identifier)
        with self.core.repository.connect() as connection:
            row = connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
            frozen = json.loads(row[0]); frozen['pipeline_execution'] = {'active': True}; frozen['send_admitted'] = True
            connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?', (json.dumps(frozen), identifier))
        out, _ = self.card('stop', identifier)
        self.assertEqual(out['workflow']['state'], 'canceled')
        self.assertFalse(out['workflow']['card_actions']['trash'])
        from runteams_core.pipelines import source_pipeline_flow as flow
        flow.finish_turn(self.core, identifier, 'canceled')
        out, _ = self.card('trash', identifier)
        self.assertTrue(out['workflow']['trashed_at'])
        self.card('restore', identifier)
        out, _ = self.card('resume', identifier)
        self.assertEqual(out['workflow']['state'], 'interrupted')
        self.assertIsNone(self.core.claim_workflow(identifier))

    def test_stopped_unsent_task_restarts_once_with_same_visit_and_receipt(self):
        from runteams_core.pipelines.pipeline_card_actions import command
        self.core.workflow = lambda identifier: {'id': identifier}
        out, _ = self.card('stop'); identifier = out['workflow']['id']
        self.assertTrue(out['workflow']['card_actions']['resume'])
        out, request = self.card('resume', identifier)
        self.assertEqual(out['workflow']['state'], 'ready')
        self.assertEqual(self.core.claim_workflow(identifier), identifier)
        replay = command(self.core, request)
        self.assertEqual(replay['workflow']['state'], 'running')
        self.assertEqual(replay['workflow']['card_actions']['visit'], request['expected_visit'])
        self.assertIsNone(self.core.claim_workflow(identifier))
        with self.core.repository.connect() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 1)

    def test_legacy_stopped_human_decision_returns_to_original_wait_without_resending(self):
        identifier = work.create(self.core, self.command)['workflow']['id']
        with self.core.repository.connect() as connection:
            row = connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
            frozen = json.loads(row[0]); frozen.update(send_admitted=True, pipeline_applied_result=True,
                pipeline_waiting={'kind': 'result', 'state': 'needs_human', 'result': {'summary': 'Keep the draft'}})
            connection.execute("UPDATE workflow_runs SET state='canceled',snapshot_json=? WHERE id=?", (json.dumps(frozen), identifier))
        out, _ = self.card('resume', identifier)
        self.assertEqual(out['workflow']['state'], 'needs_human')
        self.assertIsNone(self.core.claim_workflow(identifier))
        with self.core.repository.connect() as connection:
            saved = json.loads(connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()[0])
            self.assertEqual(saved['pipeline_waiting'], frozen['pipeline_waiting'])

    def test_stopped_sent_task_waits_for_settlement_then_requires_original_result_review(self):
        from runteams_core.foundation.contracts import ContractError
        self.core.workflow = lambda identifier: {'id': identifier}
        identifier = work.create(self.core, self.command)['workflow']['id']
        with self.core.repository.connect() as connection:
            row = connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
            frozen = json.loads(row[0]); frozen.update(send_admitted=True, pipeline_execution={'active': True})
            connection.execute("UPDATE workflow_runs SET state='running',snapshot_json=? WHERE id=?", (json.dumps(frozen), identifier))
        out, _ = self.card('stop', identifier)
        self.assertFalse(out['workflow']['card_actions']['resume'])
        self.assertTrue(out['workflow']['card_actions']['settling'])
        with self.assertRaisesRegex(ContractError, '收尾'):
            self.card('resume', identifier)
        flow.finish_turn(self.core, identifier, 'canceled')
        out, _ = self.card('resume', identifier)
        self.assertEqual(out['workflow']['state'], 'interrupted')
        self.assertIsNone(self.core.claim_workflow(identifier))

    def test_worker_waits_for_grace_period_and_then_claims_once(self):
        from datetime import datetime, timedelta, timezone
        identifier = work.create(self.core, self.command)['workflow']['id']
        with self.core.repository.connect() as connection:
            due = (datetime.now(timezone.utc) + timedelta(milliseconds=100)).isoformat()
            connection.execute('UPDATE workflow_runs SET available_at=? WHERE id=?', (due, identifier))
        self.assertIsNone(self.core.claim_workflow(identifier))
        self.runtime.activate_employee_host()
        self.assertTrue(self.done.wait(2))
        for thread in list(self.runtime.employee_jobs.values()): thread.join(2)
        self.assertEqual(len(self.executed), 1)

    def test_card_recovery_breadcrumb_is_registered_with_owned_work_ui_state(self):
        from runteams_core.work import work_ui_state
        operation = str(uuid.uuid4()); key = 'pipeline-card:fixture:7'
        with patch.object(work_ui_state, 'owner', return_value={'fixture': 'owner'}):
            reply = work_ui_state.save({'key': key, 'value': json.dumps({'pending': self.command}),
                                        'operation_id': operation, 'expected_revision': 0})
            self.assertEqual(reply['revision'], 1)
            row = work_ui_state.read()['items'][key]
            self.assertEqual(json.loads(row['value'])['pending']['operation_id'], self.command['operation_id'])
