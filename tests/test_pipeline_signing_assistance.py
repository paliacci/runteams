"""A verified signing handoff only resumes the bound task and exact blocked visit."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import json
import uuid

from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_signing_assistance as assistance
from runteams_core.pipelines import source_pipeline_flow as flow
from runteams_core.storage import device_data
from runteams_core.storage.repository import Repository, utc_now
from runteams_core.work.device_work import DeviceWorkStorage


class SigningAssistanceTests(TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(TemporaryDirectory()))
        scope = {'storage_kind': 'local', 'library_id': 'signing-test', 'storage_namespace': 'signing-test'}
        for name, value in [('root', root), ('identity', scope), ('personal', True), ('check', None),
                            ('epoch', 'signing-test-chat')]:
            stack.enter_context(patch.object(device_data, name, return_value=value))
        storage = DeviceWorkStorage()
        storage.initialize()
        self.repo = Repository(storage.path, storage=storage)
        self.core = SimpleNamespace(repository=self.repo, _actor=lambda: None)
        self.reference = {'scope': 'example-pipeline'}
        self.pipeline_state = 'running'
        self.config = {'values': {'apple_team_id': 'A1B2C3D4E5'}, 'states': {'apple_team_id': 'configured'}}
        self.role = {'package': {}, 'context': {'reference': self.reference, 'position_key': 'engineer',
                                                'asset': {'pipeline': {'positions': [{'key': 'engineer', 'kind': 'employee'}]}}},
                     'configuration': None}
        self.verify = stack.enter_context(patch.object(assistance, 'verify', return_value={
            'team_id': 'A1B2C3D4E5', 'bundle_id': 'example.app', 'version': '1', 'build': '2',
            'device_model': 'iPhone'}))
        self.snapshot = Mock(return_value=self.config)
        stack.enter_context(patch.object(assistance.access, 'bound', return_value=self.reference))
        stack.enter_context(patch.object(assistance.access.work, 'verify_context'))
        stack.enter_context(patch.object(flow, 'signing_setup', side_effect=lambda frozen: frozen.get('pipeline_waiting')))
        stack.enter_context(patch.object(flow.control, 'read', side_effect=lambda *_: {'status': self.pipeline_state}))
        stack.enter_context(patch.object(flow.control, 'bundle_for_work', return_value={'roles': {'engineer': self.role}}))
        stack.enter_context(patch('runteams_core.pipelines.pipeline_context.current',
                                  return_value=SimpleNamespace(member_configuration=lambda *_: SimpleNamespace(snapshot=self.snapshot))))
        stack.enter_context(patch.object(flow.work, 'stage_snapshot', side_effect=lambda package, context, configuration:
                                  {'employee_reference': {}, 'package': package, 'pipeline_work': context,
                                   'configuration': configuration}))
        stack.enter_context(patch.object(flow, 'payload_for', return_value={}))
        self.work = self.new_work()
        self.other = self.new_work()
        self.args = {'workflow_id': self.work, 'app_path': '/fixture/App.app', 'device': 'abcd-1234'}

    def new_work(self):
        now = utc_now()
        frozen = {'package': {}, 'pipeline_work': self.role['context'], 'pipeline_visit': 5,
                  'pipeline_generation': 1, 'pipeline_input': {'parameters': {'bundle_id': 'example.app'}},
                  'pipeline_waiting': {'kind': 'result', 'position_key': 'engineer', 'source_run_id': 15,
                                       'result': {'status': 'blocked', 'summary': '等待签名', 'issues': [], 'output': {}}}}
        with self.repo.connect() as connection:
            task = connection.execute("INSERT INTO tasks(employee_reference,title,payload_json,state,created_at,updated_at)"
                                      " VALUES('{}','签名任务','{}','blocked',?,?)", (now, now)).lastrowid
            return connection.execute("INSERT INTO workflow_runs(task_id,state,cursor_key,snapshot_json,created_at,updated_at)"
                                      " VALUES(?,'blocked','engineer',?,?,?)", (task, json.dumps(frozen), now, now)).lastrowid

    def read(self, work):
        with self.repo.connect() as connection:
            row = connection.execute('SELECT state,snapshot_json FROM workflow_runs WHERE id=?', (work,)).fetchone()
        return row['state'], json.loads(row['snapshot_json'])

    def bind(self, work=None):
        assistance.bind(self.core, 100, self.reference, self.work if work is None else work)
        return assistance.binding(self.core, 100)

    def resolve(self, binding, args=None):
        return assistance.resolve(self.core, 100, binding, self.args if args is None else args, actor_id='signing-test')

    def test_resumes_original_role_and_replays_receipt_without_another_visit(self):
        binding = self.bind()
        self.assertEqual(self.bind(), binding)
        receipt = self.resolve(binding)
        self.assertEqual(receipt, self.resolve(binding))
        self.verify.assert_called_once_with('example.app', '/fixture/App.app', 'abcd-1234')
        self.snapshot.assert_called_once_with(task_values={'apple_team_id': 'A1B2C3D4E5'})
        state, frozen = self.read(self.work)
        self.assertEqual((state, frozen['pipeline_visit']), ('ready', 6))
        self.assertEqual(frozen['configuration'], self.config)
        self.assertEqual(frozen['pipeline_signing_verification']['team_id'], 'A1B2C3D4E5')
        self.assertNotIn('pipeline_waiting', frozen)
        self.assertEqual(frozen['pipeline_history'][0]['snapshot']['pipeline_waiting']['result']['status'], 'blocked')
        self.assertEqual(self.read(self.other)[0], 'blocked')
        with self.repo.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM events WHERE type='workflow.signing_verified'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_paused_pipeline_stays_paused_with_verified_work_ready_on_resume(self):
        binding = self.bind()
        self.pipeline_state = 'paused'
        state, frozen = self.read(self.work)
        frozen['pipeline_pause'] = {'previous_state': state}
        with self.repo.connect() as connection:
            connection.execute("UPDATE workflow_runs SET state='paused',snapshot_json=? WHERE id=?",
                               (json.dumps(frozen), self.work))
        self.assertEqual(self.resolve(binding)['state'], 'paused')
        state, frozen = self.read(self.work)
        self.assertEqual((state, frozen['pipeline_pause']['previous_state']), ('paused', 'ready'))

    def test_rebinding_or_choosing_a_different_work_rejects_the_action(self):
        binding = self.bind()
        with self.assertRaises(PermissionError):
            self.resolve(binding, {**self.args, 'workflow_id': self.other})
        self.bind(self.other)
        with self.assertRaises(PermissionError):
            self.resolve(binding)
        self.verify.assert_not_called()

    def test_stale_or_unverified_result_does_not_advance_task(self):
        binding = self.bind()
        self.verify.side_effect = ContractError('device unavailable')
        with self.assertRaisesRegex(ContractError, 'device unavailable'):
            self.resolve(binding)
        state, frozen = self.read(self.work)
        self.assertEqual((state, frozen['pipeline_visit']), ('blocked', 5))
        frozen['pipeline_input']['parameters']['bundle_id'] = 'example.changed'
        with self.repo.connect() as connection:
            connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',
                               (json.dumps(frozen), self.work))
        with self.assertRaisesRegex(ContractError, '任务已经更新'):
            self.resolve(binding)
        self.assertEqual(self.verify.call_count, 1)

    def test_rebind_during_device_verification_keeps_both_tasks_blocked(self):
        binding = self.bind()
        evidence = self.verify.return_value

        def verify_and_rebind(*_):
            self.bind(self.other)
            return evidence

        self.verify.side_effect = verify_and_rebind
        with self.assertRaises(PermissionError):
            self.resolve(binding)
        self.assertEqual(self.read(self.work)[0], 'blocked')
        self.assertEqual(self.read(self.other)[0], 'blocked')

    def test_conversation_entry_and_native_tool_update_the_task(self):
        from runteams_core.agents.tools.agent_tool_registry import dispatch
        from runteams_core.foundation.identity.work_identity import principal
        from runteams_core.pipelines.source_pipeline_operations import dispatch as operation

        with patch('runteams_core.pipelines.source_pipeline_workspace.conversation',
                   return_value={'session': {'id': 100}}):
            _, status = operation(self.core, 'conversation', {'reference': self.reference, 'runtime': {},
                                                               'signing_workflow_id': self.work})
        self.assertEqual(status, 200)
        wake = Mock()
        context = {'actor_id': principal(device_data.identity()), 'chat_id': 100,
                   'signing_assistance': assistance.binding(self.core, 100), 'wake_pipeline_work': wake}
        with patch('runteams_core.work.device_work_services.current', return_value=self.core), \
                patch('runteams_core.automation.automation_dispatch.dispatch_enabled', return_value=True):
            result = dispatch(assistance.TOOL, self.args, context)
        self.assertEqual(result.kind, 'pipeline_signing_verified')
        self.assertEqual(self.read(self.work)[0], 'ready')
        wake.assert_called_once_with(self.work)

    def test_verified_team_is_task_local_and_does_not_override_a_conflicting_value(self):
        from runteams_core.configuration.employee_configuration import ConfigurationConflict, ConfigurationStore

        store = ConfigurationStore({'employee': 'engineer'}, {
            'schema': 'runteams.employee-configuration/1',
            'groups': [{'key': 'signing', 'label': '签名', 'fields': [
                {'key': 'apple_team_id', 'label': 'Apple Team ID', 'type': 'text', 'required': False},
            ]}],
        }, 'test-revision')
        snapshot = store.snapshot(task_values={'apple_team_id': 'A1B2C3D4E5'})
        self.assertEqual(snapshot['values'], {'apple_team_id': 'A1B2C3D4E5'})
        self.assertEqual(store.read()['values'], {})
        store.save(operation_id=str(uuid.uuid4()), expected_revision=0, definition_sha256=store.definition_sha256,
                   values={'apple_team_id': 'Z1Y2X3W4V5'})
        with self.assertRaises(ConfigurationConflict):
            store.snapshot(task_values={'apple_team_id': 'A1B2C3D4E5'})
