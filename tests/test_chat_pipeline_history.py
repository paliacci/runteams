from contextlib import nullcontext
from unittest import TestCase
from unittest.mock import Mock, patch

from runteams_core.authoring.creator_contracts import canonical
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import chat_pipeline_history as history


class ChatPipelineHistoryTests(TestCase):
    def setUp(self):
        self.reference = {'source_id': 'f' * 64, 'pipeline_source': 'pipelines/main.json'}
        self.old_revision, self.new_revision = 'r-' + 'a' * 64, 'r-' + 'b' * 64
        self.old_item = {'revision': self.old_revision, 'revision_number': 1, 'version': '修订 1'}
        self.new_item = {'revision': self.new_revision, 'revision_number': 2, 'version': '修订 2'}
        self.records = {'items': [self.new_item, self.old_item], 'storage_scope': 'device'}

        def asset(name, approval):
            graph = {'name': name, 'team_standard': name + '规范',
                     'positions': [{'key': 'review', 'kind': 'employee', 'name': 'Review',
                                    'employee_ref': 'reviewer', 'skill_key': 'review'}],
                     'states': [{'key': 'done', 'kind': 'done', 'name': 'Done'}],
                     'edges': [{'from': 'review', 'to': 'approval' if approval else 'done', 'when': 'completed'}]}
            if approval:
                graph['positions'].append({'key': 'approval', 'kind': 'approval', 'name': 'Approval'})
                graph['edges'].append({'from': 'approval', 'to': 'done', 'when': 'approved'})
            return {'key': 'main', 'pipeline': graph, 'avatar': name,
                    'employees': [{'ref': 'reviewer', 'source': f'employees/{name}.json'}]}

        self.original = asset('A', False)
        self.current = asset('B', True)
        snapshots = {
            self.old_revision: {'employees/A.json': canonical({'name': '员工甲'}), 'asset': self.original},
            self.new_revision: {'employees/B.json': canonical({'name': '员工乙'}), 'asset': self.current},
        }
        self.core = Mock()
        self.enterContext(patch.object(history.settings, 'history', return_value=self.records))
        self.enterContext(patch.object(history.settings, '_asset', side_effect=lambda files, ref: files['asset']))
        self.revisions = Mock()
        self.revisions.files_at.side_effect = snapshots.__getitem__
        self.revisions.locked.side_effect = nullcontext
        self.revisions._head.return_value = self.new_revision
        self.enterContext(patch.object(history.work, 'source', return_value=self.revisions))

        def save(core, data, before_commit):
            before_commit()
            return {'revision': 'r-' + 'c' * 64, 'pipeline': data['asset']['pipeline']}

        self.edit = self.enterContext(patch.object(history.settings, 'edit', side_effect=save))

    def restore(self, intent, **kwargs):
        return history.execute(self.core, self.reference, {
            'operation': 'restore_draft', 'history_revision': self.old_revision,
            'source_revision': self.new_revision}, inspected_revision=kwargs.pop('inspected_revision', self.new_revision),
            operation_id='test-uuid', check_intent=lambda: intent, **kwargs)

    def test_compare_reports_actual_employee_change_under_same_member_key_and_routes(self):
        result = history.execute(self.core, self.reference, {'operation': 'compare_drafts',
                                 'from_revision': self.old_revision, 'to_revision': self.new_revision})
        changes = result['definition_changes']
        reviewer = next(position for position in changes['positions'] if position['key'] == 'review')
        self.assertEqual(reviewer['before']['employee']['name'], '员工甲')
        self.assertEqual(reviewer['after']['employee']['name'], '员工乙')
        route = next(route for route in changes['routes'] if route['key'] == 'review')
        self.assertEqual(route['before'][0]['to'], 'done')
        self.assertEqual(route['after'][0]['to'], 'approval')
        self.edit.assert_not_called()

    def test_read_history_requires_the_current_team_revision(self):
        listing = history.execute(self.core, self.reference, {'operation': 'draft_history'})
        self.assertEqual(listing['items'], self.records['items'])
        read = history.execute(self.core, self.reference, {'operation': 'draft_history',
                               'history_revision': self.old_revision})
        self.assertEqual(read['positions'][0]['employee']['name'], '员工甲')
        with self.assertRaises(ContractError):
            history.execute(self.core, self.reference, {'operation': 'draft_history',
                            'history_revision': 'r-' + 'd' * 64})
        self.edit.assert_not_called()

    def test_restore_previous_reconciles_real_members_and_preserves_current_team_properties(self):
        result = self.restore('请把上一版恢复为新流程草稿。')
        self.assertEqual(result['status'], 'restored')
        request = self.edit.call_args.args[1]
        self.assertEqual(request['base_revision'], self.new_revision)
        self.assertEqual(request['asset'], {
            **self.current, 'employees': self.original['employees'],
            'pipeline': {**self.original['pipeline'], 'name': 'B', 'team_standard': 'B规范'},
        })

    def test_restore_requires_the_inspected_baseline_and_verified_target(self):
        with self.assertRaises(ContractError):
            self.restore('把修订 1 恢复为流程草稿。', inspected_revision='stale')
        with self.assertRaises(PermissionError):
            self.restore('把修订 2 恢复为流程草稿。')
        with self.assertRaises(PermissionError):
            self.restore('恢复刚才比较的旧版。', compared_from=self.new_revision)
        for message in ('请只比较修订 1。', '不要恢复修订 1。', '比较修订 1，恢复修订 2。',
                        'Compare revision 1. Restore revision 2.', "Don't restore revision 1."):
            with self.subTest(message=message), self.assertRaises(PermissionError):
                self.restore(message)
        self.edit.assert_not_called()

    def test_identical_flow_is_unchanged_even_when_member_order_differs(self):
        self.current['pipeline'].update({key: value for key, value in self.original['pipeline'].items()
                                         if key not in ('name', 'team_standard')})
        additional = {'ref': 'producer', 'source': 'employees/another.json'}
        position = {'key': 'produce', 'name': 'Produce', 'kind': 'employee',
                    'employee_ref': 'producer', 'skill_key': 'produce'}
        self.original['pipeline']['positions'].append(position)
        self.original['employees'].append(additional)
        self.current['employees'] = list(reversed(self.original['employees']))
        self.assertEqual(self.restore('请恢复上一版，只保存草稿。')['status'], 'unchanged')
        self.edit.assert_not_called()

    def test_contextual_restore_requires_selection_without_a_verified_comparison(self):
        confirmation = Mock(return_value={})
        self.assertEqual(self.restore('Restore the revision we just compared.', confirm=confirmation,
                                     policy={'communication_language': 'en'}), {'status': 'cancelled'})
        question = confirmation.call_args.args[0][0]
        self.assertIn('Revision 1', question['question'])
        self.assertIn(self.old_revision[:14], question['question'])
        self.edit.assert_not_called()

        confirmation.return_value = {'answers': {question['id']: {'answers': ['Revision 1']}}}
        self.assertEqual(self.restore('Restore the revision we just compared.', confirm=confirmation,
                                     policy={'communication_language': 'en'})['status'], 'restored')

    def test_restore_after_verified_comparison_uses_the_compared_source(self):
        confirm = Mock()
        result = self.restore('恢复刚才比较的旧版。', compared_from=self.old_revision, confirm=confirm)
        self.assertEqual(result['status'], 'restored')
        confirm.assert_not_called()
