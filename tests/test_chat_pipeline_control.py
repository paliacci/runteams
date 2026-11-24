from contextlib import nullcontext
import json
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import chat_pipeline_control as runtime
from runteams_core.pipelines import source_pipeline_control as control


class ChatPipelineControlTests(TestCase):
    def setUp(self):
        self.reference = {'source_id': 'a' * 64, 'pipeline_source': 'pipelines/main.json'}
        self.message = {'role': 'user', 'text': '应用这次更新，然后恢复整个团队。'}
        flow = runtime.chat
        self.scope = {'storage_kind': 'local', 'library_id': 'library'}
        self.enterContext(patch.object(flow.device_data, 'identity', return_value=self.scope))
        self.enterContext(patch.object(flow.device_data, 'check'))
        self.enterContext(patch.object(flow.device_data, 'epoch', return_value='test-epoch'))
        self.binding = self.enterContext(patch.object(flow.access, 'bound', return_value=self.reference))
        self.enterContext(patch.object(flow.product_store, 'get_chat_message', return_value=self.message))
        self.confirm = Mock(side_effect=lambda options: {'answers': {
            options[0]['id']: {'answers': [options[0]['options'][0]['label']]}}})
        self.wake = Mock()
        self.context = {'chat_id': 71, 'actor_id': 'library'}
        self.assertTrue(runtime.bind_turn(self.context, 13, Event(), self.confirm, lambda: (), self.wake))
        self.bound = self.context['pipeline_runtime_turn']
        self.core = SimpleNamespace(_actor=Mock(), repository=SimpleNamespace(read_snapshot=nullcontext))
        self.definition = {'positions': [{'key': 'review', 'kind': 'employee'}], 'edges': [], 'states': []}
        self.pending = {'positions': [{'key': 'review', 'kind': 'employee', 'name': '核查'}], 'edges': [], 'states': []}
        self.state = {'revision': 9, 'applied_revision': 'b' * 64, 'status': 'paused'}
        self.saved = {'reference': self.reference, 'revision': 9,
                      'bundle': {'asset': {'pipeline': self.definition}}}
        self.row = {'id': 47, 'task_title': '原工单', 'cursor_key': 'review', 'state': 'paused', 'trashed_at': None,
                    'payload_json': '{}', 'snapshot_json': json.dumps({
                        'pipeline_work': {'position_key': 'review', 'asset': {'pipeline': self.definition}},
                        'pipeline_pause': {'previous_state': 'interrupted'}, 'send_admitted': True})}
        self.rows = [self.row]
        self.enterContext(patch.object(runtime, '_source', return_value=('r-' + 'c' * 64, self.pending)))
        self.enterContext(patch.object(control, 'state', return_value=self.state))
        self.enterContext(patch.object(control, 'read', return_value=self.saved))
        self.enterContext(patch.object(control, '_rows', return_value=self.rows))
        self.command = self.enterContext(patch.object(control, 'command', return_value={'status': 'committed'}))
        self.receipt = self.enterContext(patch.object(control, 'control_operation', return_value={'status': 'committed'}))

    def execute(self, operation, **kwargs):
        arguments = {'operation': operation, **kwargs}
        runtime.access._validate(runtime.INPUT_SCHEMA, arguments)
        return runtime._execute(self.core, self.bound, arguments, None)

    def update(self):
        preview = self.execute('preview_update', revision=9)
        return {key: preview[key] for key in ('revision', 'source_revision', 'impact')}

    def test_preview_identifies_unresolved_work_and_only_native_confirmation_allows_apply(self):
        preview = self.execute('preview_update')
        self.assertEqual(preview['impact_counts'], {'reconciliation_before_execution': 1})
        self.assertEqual(preview['definition_changes']['edited'], ['review'])
        self.confirm.assert_not_called()
        self.command.assert_not_called()
        update = self.update()
        self.assertEqual(self.execute('apply_update', intent='应用这次更新', **update)['status'], 'committed')
        self.assertIn('47', self.confirm.call_args[0][0][0]['question'])
        request = self.command.call_args[0][1]
        self.assertEqual(request['expected_impact'], preview['impact'])
        self.assertEqual(request['reference'], self.reference)
        self.assertEqual(request['action'], 'update')
        self.execute('apply_update', intent='应用这次更新', **update)
        self.execute('receipt', action='apply_update')
        self.confirm.assert_called_once()
        self.command.assert_called_once()
        self.assertEqual(self.receipt.call_count, 2)
        self.wake.assert_not_called()

    def test_changed_work_rejects_a_prior_preview_before_confirmation(self):
        update = self.update()
        self.row['payload_json'] = '{"changed":true}'
        with self.assertRaisesRegex(ContractError, '已变化'):
            self.execute('apply_update', intent='应用这次更新', **update)
        self.confirm.assert_not_called()
        self.command.assert_not_called()

    def test_declined_confirmation_does_not_apply_and_cannot_reopen_in_same_turn(self):
        update = self.update()
        self.confirm.side_effect = None
        self.confirm.return_value = {}
        for _ in range(2):
            self.assertEqual(self.execute('apply_update', intent='应用这次更新', **update), {'status': 'cancelled'})
        with self.assertRaisesRegex(ContractError, '保持暂停'):
            self.execute('resume', revision=9, intent='恢复整个团队')
        self.confirm.assert_called_once()
        self.command.assert_not_called()

    def test_rebinding_while_confirmation_is_open_blocks_commit(self):
        update = self.update()
        def changed(questions):
            self.binding.return_value = {'source_id': 'b' * 64}
            return {'answers': {questions[0]['id']: {'answers': [questions[0]['options'][0]['label']]}}}
        self.confirm.side_effect = changed
        with self.assertRaises(PermissionError):
            self.execute('apply_update', intent='应用这次更新', **update)
        self.command.assert_not_called()

    def test_resume_reuses_operation_and_wakes_only_after_first_commit(self):
        self.enterContext(patch('runteams_core.automation.automation_dispatch.dispatch_enabled', return_value=False))
        self.command.return_value = {'status': 'committed', 'state': {'workflows': [
            {'id': 47, 'state': 'interrupted'}, {'id': 48, 'state': 'ready'}, {'id': 49, 'state': 'paused'},
        ]}}
        with self.assertRaises(PermissionError):
            self.execute('resume', revision=9, intent='本轮没有说这句话')
        for _ in range(2):
            self.execute('resume', revision=9, intent='恢复整个团队')
        self.command.assert_called_once()
        self.assertEqual(self.command.call_args[0][1]['action'], 'start')
        self.wake.assert_called_once_with(48)

    def test_market_download_needs_named_version_and_original_dialogue(self):
        from runteams_core.assets.rented_references import PIPELINE
        self.reference['schema'] = PIPELINE
        self.bound.market = Mock(return_value={'status': 'downloaded'})
        market = runtime.chat_pipeline_market
        self.enterContext(patch.object(market.device_data, 'personal', return_value=True))
        self.enterContext(patch.object(market.product_store, 'get_chat', return_value={'context': {}}))
        self.enterContext(patch.object(market, '_previous', return_value=None))
        self.assertEqual(self.execute('market_versions'), {'status': 'downloaded'})
        self.message['text'] = '请下载本团队 11.0.0，先不应用。'
        with self.assertRaises(PermissionError):
            self.execute('download_market_version', version='1.0.0', intent=self.message['text'])
        with self.assertRaises(PermissionError):
            self.execute('download_market_version', version='11.0.0', intent='下载其他版本 11.0.0')
        for text in (
                '请下载 11.0.0。先不下载。',
                'Download v11.0.0. Do not download it yet.',
                'Download v11.0.0. Please download v12.0.0.',
                'Download v11.0.0, v12.0.0.',
                '请下载 11.0.0。再下载 12.0.0。'):
            with self.subTest(text=text), self.assertRaises(PermissionError):
                self.message['text'] = text
                self.execute('download_market_version', version='11.0.0', intent=text)
        self.message['text'] = 'Download v11.0.0. Leave the current version running.'
        self.execute('download_market_version', version='11.0.0', intent=self.message['text'])
        arguments = self.bound.market.call_args[0]
        self.assertEqual(arguments[:4], (self.core, self.reference, 'download_market_version', '11.0.0'))
        self.binding.return_value = {'source_id': 'b' * 64}
        with self.assertRaises(PermissionError):
            arguments[4]()
        self.command.assert_not_called()

    def test_market_control_is_unavailable_for_local_source(self):
        self.bound.market = Mock()
        with self.assertRaises(PermissionError):
            self.execute('market_versions')
        self.bound.market.assert_not_called()
