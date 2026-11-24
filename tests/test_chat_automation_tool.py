"""Scoped provider tools for direct employee and pipeline conversations."""
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from runteams_core.agents.tools import agent_tool_registry as registry, agent_tools_mcp
from runteams_core.automation import chat_automation_tool as tool


class ChatAutomationToolTests(TestCase):
    def setUp(self):
        self.scope = {'storage_kind': 'local', 'library_id': 'scope'}
        self.context = {'actor_id': 'scope', 'chat_id': 27, 'allowed_tools': [tool.TOOL]}
        self.session = {'id': 27, 'kind': 'general', 'subject_type': 'employee', 'context': {}}
        self.reference = {'schema': 'fixture-ref'}
        self.cancel = Event()
        self.invoke = Mock(return_value={'items': []})
        self.enterContext(patch.object(tool.device_data, 'identity', lambda: dict(self.scope)))
        self.enterContext(patch.object(tool.device_data, 'personal', return_value=True))
        self.enterContext(patch.object(tool.device_data, 'epoch', return_value='stored-chat-epoch'))
        self.enterContext(patch.object(tool.product_store, 'device_chat', side_effect=lambda chat: chat == 27))
        self.enterContext(patch.object(tool.product_store, 'get_chat', return_value=self.session))
        self.message = self.enterContext(patch.object(tool.product_store, 'get_chat_message', return_value={'role': 'user'}))
        self.enterContext(patch('runteams_core.employees.employee_binding.resolve',
                                return_value={'reference': self.reference}))

    def rpc(self, arguments, context=None):
        value = agent_tools_mcp.dispatch_rpc({
            'jsonrpc': '2.0', 'id': 52, 'method': 'tools/call',
            'params': {'name': tool.TOOL, 'arguments': arguments},
        }, self.context if context is None else context)
        return value['result']

    def test_mcp_and_codex_use_host_owned_reference_and_accepted_message(self):
        self.assertTrue(tool.bind_turn(self.context, 8, self.cancel, self.invoke))
        result = self.rpc({'operation': 'list'})
        self.assertFalse(result['isError'])
        self.assertEqual(result['structuredContent']['data'], {'items': []})
        self.invoke.assert_called_once_with(kind='employee', reference=self.reference,
                                            turn_key='stored-chat-epoch:8', operation='list', arguments={})
        self.assertEqual(registry.codex_dynamic_definitions([tool.TOOL])[0]['inputSchema'],
                         registry.mcp_definitions([tool.TOOL])[0]['inputSchema'])

    def test_background_non_asset_and_assignment_turns_are_denied(self):
        self.cancel.background_employee_work = True
        self.assertFalse(tool.bind_turn(self.context, 8, self.cancel, self.invoke))
        self.cancel.background_employee_work = False
        for key in ('pipeline_work', 'employee_work', 'employee_schedule_operation'):
            self.session['context'] = {key: {}}
            self.assertFalse(tool.bind_turn(self.context, 8, self.cancel, self.invoke))
        self.session.update(subject_type='workspace', context={})
        self.assertFalse(tool.bind_turn(self.context, 8, self.cancel, self.invoke))
        self.assertTrue(self.rpc({'operation': 'list'})['isError'])
        self.invoke.assert_not_called()

    def test_missing_asset_does_not_prevent_ordinary_conversation(self):
        for error in (PermissionError('Expired asset'), FileNotFoundError('Retired asset')):
            with patch('runteams_core.employees.employee_binding.resolve', side_effect=error):
                self.assertFalse(tool.bind_turn(self.context, 8, self.cancel, self.invoke))
        self.invoke.assert_not_called()

    def test_pipeline_uses_verified_binding_and_rechecks_scope_and_message(self):
        self.session.update(subject_type='workspace', context={'source_pipeline_workspace': {'untrusted': True}})
        pipeline_context = Mock()
        pipeline_context.binding.return_value = self.reference
        with patch('runteams_core.pipelines.pipeline_context.current', return_value=pipeline_context):
            self.assertTrue(tool.bind_turn(self.context, 8, self.cancel, self.invoke))
            self.assertTrue(self.rpc({'operation': 'list'}, {**self.context, 'chat_id': 91})['isError'])
            self.message.return_value = {'role': 'bot'}
            self.assertTrue(self.rpc({'operation': 'list'})['isError'])
            self.message.return_value = {'role': 'user'}
            pipeline_context.binding.return_value = {'schema': 'new-reference'}
            self.assertTrue(self.rpc({'operation': 'list'})['isError'])
            self.invoke.assert_not_called()
            pipeline_context.binding.return_value = self.reference
            self.assertFalse(self.rpc({'operation': 'list'})['isError'])
        self.invoke.assert_called_once_with(kind='pipeline', reference=self.reference,
                                            turn_key='stored-chat-epoch:8', operation='list', arguments={})

    def test_author_chat_binds_only_the_selected_owned_employee(self):
        self.session.update(kind='employee_design', subject_type='workspace', context={
            'context_type': 'worker', 'intent': 'create', 'phase': 'design',
            'creator_local_scope': 'library', 'creator_authoring': True,
            'creator_local_source_id': 'source', 'creator_employee_source': 'employees/main.json'})
        self.scope['cache_scope'] = 'library'
        with patch('runteams_core.employees.employee_directory.for_session') as lookup:
            lookup.return_value = {'source': {'reference': self.reference}}
            self.assertTrue(tool.bind_turn(self.context, 8, self.cancel, self.invoke))
            self.assertFalse(self.rpc({'operation': 'history'})['isError'])
            lookup.return_value = {'trashed': True, 'source': {'reference': self.reference}}
            self.assertTrue(self.rpc({'operation': 'history'})['isError'])
            self.session['context']['creator_local_scope'] = 'someone-else'
            self.assertFalse(tool.bind_turn(self.context, 8, self.cancel, self.invoke))
