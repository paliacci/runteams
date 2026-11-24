from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from runteams_core.configuration.chat_setup import SetupTurn
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import chat_position_runtime as tool


class ChatPositionRuntimeTest(TestCase):
    def setUp(self):
        self.revision = 'a' * 64
        self.ref = {'source_id': 'example'}
        self.core = object()
        self.turn = SetupTurn(11, 22, 'epoch', {}, 'pipeline', self.ref, Event())
        self.asset = {'pipeline': {'positions': [
            {'key': 'produce', 'kind': 'employee', 'name': 'Produce'},
            {'key': 'approve', 'kind': 'approval', 'name': 'Approve'},
            {'key': 'review', 'kind': 'employee', 'name': 'Review'},
        ]}}
        self.handler = Mock(return_value={'source_revision': self.revision, 'selection': None,
                                          'effective': {'channel_id': 2, 'model': 'catalog-model', 'effort': 'low'}})
        self.pipeline = SimpleNamespace(definition=lambda _: (self.revision, self.asset),
                                        position_runtime=self.handler)
        self.selection = {'channel_id': 2, 'model': 'catalog-model', 'effort': 'low'}

    def tool(self, arguments, message=''):
        return tool._execute(self.core, self.pipeline, self.turn, arguments, message)

    def test_inspect_all_employee_positions_only(self):
        result = self.tool({'operation': 'inspect'})
        self.assertEqual([row['position_key'] for row in result['positions']], ['produce', 'review'])
        self.assertEqual([call.args for call in self.handler.call_args_list], [
            (self.core, self.ref, 'produce', None), (self.core, self.ref, 'review', None),
        ])

    def test_setting_and_reset_send_exact_compare_and_swap_to_only_one_position(self):
        intent = 'Set review to catalog-model low'
        args = {'operation': 'set', 'position_key': 'review', 'selection': self.selection,
                'expected_selection': None, 'source_revision': self.revision, 'intent': intent}
        result = self.tool(args, 'Please ' + intent)
        self.assertEqual(result['status'], 'saved')
        self.assertEqual(result['applies_to'], 'new_work_only')
        self.handler.assert_called_once_with(self.core, self.ref, 'review', {
            'source_revision': self.revision, 'expected_selection': None, 'selection': self.selection,
        })
        self.handler.reset_mock()
        del args['selection']
        args.update(operation='reset', expected_selection=self.selection, intent='Reset review only')
        self.assertEqual(self.tool(args, args['intent'])['status'], 'reset')
        self.handler.assert_called_once_with(self.core, self.ref, 'review', {
            'source_revision': self.revision, 'expected_selection': self.selection, 'selection': None,
        })

    def test_rejects_wrong_scope_approval_and_unverified_instruction(self):
        for case in ({'operation': 'inspect', 'position_key': 'approve'},
                     {'operation': 'inspect', 'reference': {'source_id': 'foreign'}},
                     {'operation': 'reset', 'position_key': 'review', 'source_revision': self.revision,
                      'expected_selection': self.selection, 'intent': 'some old instruction'}):
            with self.subTest(case=case), self.assertRaises(ContractError):
                self.tool(case, 'Inspect only')
        self.handler.assert_not_called()

    def test_background_and_employee_chats_cannot_attach_tool(self):
        from runteams_core.storage import device_data
        cancel = Event()
        cancel.background_employee_work = True
        self.assertFalse(tool.bind_turn({'chat_id': 11}, 22, cancel))
        with patch.object(device_data, 'identity', return_value={}), \
                patch.object(tool, 'principal', return_value='actor'), \
                patch('runteams_core.automation.chat_automation_tool._binding', return_value=('employee', self.ref)):
            context = {'chat_id': 11, 'actor_id': 'actor'}
            self.assertFalse(tool.bind_turn(context, 22, Event()))
            self.assertEqual(set(context), {'chat_id', 'actor_id'})
