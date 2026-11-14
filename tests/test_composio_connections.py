"""Composio wire contracts, scoped credentials and non-replayed external effects."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from runteams_core.employees.mcp import composio_connections as composio
from runteams_core.employees.mcp import employee_applications, mcp_connections

KEY = 'test-only-project-key-never-a-real-credential'
DEFINITION = {'slug': 'SLACK_SEND', 'name': 'Send', 'description': 'Send message',
              'toolkit': {'slug': 'slack'}, 'version': '20261113_00', 'no_auth': False,
              'input_parameters': {'type': 'object', 'required': ['text'], 'properties': {'text': {'type': 'string'}}}}


class ComposioConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.scope = 'a' * 64
        self.calls = []; self.effects = 0; self.mode = 'completed'
        self.extra_accounts = []
        for target, value in [('device_data.personal', lambda: True),
                              ('device_data.identity', lambda: {'cache_scope': self.scope}),
                              ('local_database.DB_PATH', str(Path(self.temp.name) / 'main.sqlite3'))]:
            p = patch('runteams_core.employees.mcp.mcp_connections.' + target, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(composio, 'request', side_effect=self.remote); p.start(); self.addCleanup(p.stop)
        self.revision = self.call('save', token=KEY)['revision']
        self.employee = {'schema': 'runteams.local-employee-reference/1', 'source_id': 'a' * 64,
                         'employee_source': 'employee.ts', 'storage_kind': 'local',
                         'library_id': str(uuid.uuid4())}
        self.enterContext(patch.object(employee_applications.employee_references, 'key',
                                      side_effect=lambda ref: json.dumps(ref, sort_keys=True)))

    def settings(self, action, **fields):
        return employee_applications.bindings({'action': 'employee-apps-' + action,
                                                'employee': self.employee, **fields})

    def turn(self, rows, activity, cancel=None):
        for row in rows:
            self.settings('set', row=row, remove=False)
        return employee_applications.ApplicationTurn(employee_applications.storage_key(self.employee),
                                                     {'cache_scope': self.scope}, activity, cancel)

    def call(self, action, **fields):
        return mcp_connections.dispatch('POST', {'id': 'composio', 'action': action, **fields}, None)

    def remote(self, key, method, path, **kw):
        self.assertEqual(key, KEY); self.calls.append((method, path, kw))
        if path == '/toolkits':
            return {'items': [{'slug': 'slack', 'name': 'Slack', 'meta': {'tools_count': 99}}], 'next_cursor': 'page-two', 'total_items': 1742}
        if path == '/toolkits/slack':
            return {'slug': 'slack', 'name': 'Slack', 'no_auth': False}
        if path == '/tools': return {'items': [copy.deepcopy(DEFINITION)], 'next_cursor': None, 'total_items': 1}
        if path == '/tools/SLACK_SEND': return copy.deepcopy(DEFINITION)
        if path == '/connected_accounts':
            user = kw['query']['user_ids']
            return {'items': [
                {'id': 'ca_own', 'user_id': user, 'toolkit': {'slug': 'slack'}, 'status': 'ACTIVE', 'state': {'val': {'displayName': 'Team workspace', 'access_token': 'do-not-expose'}}},
                {'id': 'ca_foreign', 'user_id': 'other', 'toolkit': {'slug': 'slack'}, 'status': 'ACTIVE'},
                {'id': 'ca_wrong_app', 'user_id': user, 'toolkit': {'slug': 'gmail'}, 'status': 'ACTIVE'},
                *[{**account, 'user_id': user} for account in self.extra_accounts]]}
        if path == '/tool_router/session':
            self.assertEqual(kw['body']['toolkits'], {'enable': ['slack']})
            self.assertTrue(kw['body']['multi_account']['require_explicit_selection'])
            return {'session_id': 'trs_test'}
        if path.endswith('/link'):
            return {'redirect_url': 'https://connect.composio.dev/link/test-only',
                    'link_token': 'not-for-ui', 'connected_account_id': 'ca_new'}
        if path.endswith('/execute'):
            self.effects += 1
            if self.mode == 'timeout': raise composio.ComposioError(composio.UNKNOWN, 'outcome_unknown')
            return {'result_type': self.mode, 'data': {'echo': KEY}, 'error': None, 'log_id': 'log_test'}
        raise AssertionError(path)

    def test_catalog_filters_and_pagination_are_passed_to_current_api(self):
        result = self.call('catalog', revision=self.revision, search='Slack & Mail', cursor='page+2=')
        self.assertEqual(result['total_items'], 1742)
        self.assertEqual(self.calls[-1][2]['query']['cursor'], 'page+2=')
        self.assertNotIn(KEY, json.dumps(result))
        listed = mcp_connections.dispatch('GET', {}, None)['connections']
        self.assertEqual(next(r for r in listed if r['id'] == 'composio')['has_token'], True)

    def test_empty_search_is_omitted_from_catalog_and_tools(self):
        self.call('catalog', revision=self.revision, search='', cursor='')
        self.assertNotIn('search', self.calls[-1][2]['query'])
        self.call('tools', revision=self.revision, toolkit='slack', search='', cursor='')
        self.assertNotIn('query', self.calls[-1][2]['query'])
        self.call('tools', revision=self.revision, toolkit='slack', search='send', cursor='')
        self.assertEqual(self.calls[-1][2]['query']['query'], 'send')

    def test_keys_stay_private_and_scopes_do_not_share_connections(self):
        self.assertTrue(self.call('status')['configured'])
        vault = next(Path(self.temp.name).rglob('*.secrets.json'))
        self.assertEqual(vault.stat().st_mode & 0o777, 0o600)
        self.scope = 'b' * 64
        self.assertFalse(self.call('status')['configured'])
        self.assertEqual(self.call('catalog', revision=self.revision, search='', cursor='')['code'], 'not_configured')

    def test_account_results_are_allowlisted_and_filtered(self):
        result = self.call('accounts', revision=self.revision, toolkit='slack')
        self.assertEqual([r['id'] for r in result['accounts']], ['ca_own'])
        self.assertEqual(result['accounts'][0]['name'], 'Team workspace')
        self.assertNotIn('do-not-expose', json.dumps(result))

    def test_link_is_hosted_and_does_not_return_token(self):
        result = self.call('connect', revision=self.revision, toolkit='slack')
        self.assertEqual(set(result), {'redirect_url', 'connected_account_id'})
        self.assertEqual(result['connected_account_id'], 'ca_new')
        self.assertTrue(result['redirect_url'].startswith('https://connect.composio.dev/'))

    def test_catalog_and_tools_never_create_session_or_execute(self):
        self.call('tools', revision=self.revision, toolkit='slack', search='', cursor='')
        self.assertFalse(any(path.startswith('/tool_router') for _, path, _ in self.calls))

    def body(self):
        return dict(revision=self.revision, toolkit='slack', tool='SLACK_SEND', version='20261113_00',
                    account='ca_own', arguments={'text': 'fixture'}, operation_id=str(uuid.uuid4()))

    def test_execution_receipt_replay_sends_once_and_redacts_key(self):
        body = self.body(); first = self.call('test', **body)
        self.assertEqual(first, self.call('test', **body)); self.assertEqual(self.effects, 1)
        self.assertFalse(first['result']['isError']); self.assertNotIn(KEY, json.dumps(first))
        with self.assertRaises(ValueError): self.call('test', **{**body, 'arguments': {'text': 'different'}})
        self.assertEqual(self.effects, 1)

    def test_employee_write_runs_directly_and_replay_does_not_repeat(self):
        row = {'provider': 'composio', 'id': 'slack', 'name': 'Slack',
               'account': {'id': 'ca_own', 'name': 'Team workspace'}}
        activity = Mock()
        turn = self.turn([row], activity)
        args = {'operation': 'call', 'application': 'composio:slack', 'tool': 'SLACK_SEND',
                'version': DEFINITION['version'], 'arguments': {'text': 'fixture'}}
        context = {'call_id': 'fixture-call'}
        first = turn.execute(args, context)
        self.assertFalse(first['result']['isError'])
        self.assertEqual(first, turn.execute(args, context))
        self.assertEqual(self.effects, 1)
        self.settings('set', row={**row, 'account': {'id': 'ca_foreign', 'name': 'Other account'}}, remove=False)
        with self.assertRaises(employee_applications.AccountRequired):
            turn.execute(args, {'call_id': 'another-call'})
        self.assertEqual(self.effects, 1)
        activity.request_user_input.assert_not_called()

    def test_employee_mcp_call_runs_directly_and_excludes_app_only_tools(self):
        row = {'provider': 'mcp', 'id': 'slack', 'name': 'Slack', 'account': {'name': 'Slack'}}
        activity = Mock()
        turn = self.turn([row], activity)
        args = {'operation': 'call', 'application': 'mcp:slack', 'tool': 'search',
                'arguments': {'query': 'fixture'}}
        catalog = {'result': {'tools': [{'name': 'search'}, {'name': 'app_only',
                   '_meta': {'ui': {'visibility': ['app']}}}]}}
        response = {'result': {'content': [{'type': 'text', 'text': 'fixture result'}]}}
        with patch.object(turn, 'request', side_effect=[catalog, response, catalog]) as request:
            self.assertEqual(turn.execute(args, {}), response)
            request.assert_called_with(action='test', id='slack', tool='search', arguments=args['arguments'])
            with self.assertRaisesRegex(ValueError, '未对员工开放'):
                turn.execute({**args, 'tool': 'app_only'}, {})
            self.assertEqual(request.call_count, 3)
        activity.request_user_input.assert_not_called()

    def test_employee_must_save_its_connection_before_calling_even_with_a_device_account(self):
        activity = Mock()
        turn = self.turn([], activity)
        args = {'operation': 'call', 'application': 'composio:slack', 'tool': 'SLACK_SEND',
                'version': DEFINITION['version'], 'arguments': {'text': 'fixture'}}
        with self.assertRaises(employee_applications.AccountRequired):
            turn.execute(args, {})
        self.assertEqual(self.effects, 0)
        self.assertEqual(turn.execute({'operation': 'connect', 'application': 'composio:slack'}, {}),
                         {'state': 'connected'})
        activity.request_user_input.assert_not_called()
        self.assertEqual(self.settings('read')['applications'][0]['account']['id'], 'ca_own')
        self.assertFalse(self.turn([], activity).execute(args, {'call_id': 'fixture-call'})['result']['isError'])
        self.assertEqual(self.effects, 1)
        self.assertFalse(any(path.startswith('/connected_accounts/link') for _, path, _ in self.calls))
        activity.on_event.assert_not_called()
        activity.request_user_input.assert_not_called()

    def test_multiple_accounts_need_selection_before_any_effect(self):
        self.extra_accounts = [{'id': 'ca_second', 'toolkit': {'slug': 'slack'}, 'status': 'ACTIVE',
                                'state': {'val': {'displayName': 'Second workspace'}}}]
        row = {'provider': 'composio', 'id': 'slack', 'name': 'Slack'}
        turn = self.turn([row], Mock())
        args = {'operation': 'call', 'application': 'composio:slack', 'tool': 'SLACK_SEND',
                'version': DEFINITION['version'], 'arguments': {'text': 'fixture'}}
        with self.assertRaises(employee_applications.AccountRequired):
            turn.execute(args, {})
        result = turn.connect('composio:slack')
        self.assertEqual(result['state'], 'account_choice_required')
        self.assertEqual([account['id'] for account in result['accounts']], ['ca_own', 'ca_second'])
        self.assertEqual(self.effects, 0)
        connect = {'operation': 'connect', 'application': 'composio:slack', 'account': 'ca_own'}
        with self.assertRaises(employee_applications.AccountRequired):
            turn.execute({**connect, 'account': 'ca_foreign'}, {})
        self.assertEqual(turn.execute(connect, {}), {'state': 'connected'})
        with self.assertRaises(employee_applications.AccountRequired):
            turn.execute({**connect, 'account': 'ca_second'}, {})
        self.assertFalse(turn.execute(args, {'call_id': 'selected-call'})['result']['isError'])
        self.assertEqual(self.effects, 1)

    def test_explicit_gmail_read_continues_after_saving_without_an_extra_question(self):
        activity = Mock()
        turn = self.turn([], activity)
        row = {'provider': 'composio', 'id': 'gmail', 'name': 'Gmail'}
        account = {'ca_wrong_app': {'id': 'ca_wrong_app', 'name': 'Example mailbox'}}
        args = {'operation': 'call', 'application': 'composio:gmail', 'tool': 'GMAIL_FETCH_EMAILS',
                'version': 'fixture', 'arguments': {'user_id': 'me', 'max_results': 5}}
        receipt = {'result': {'content': [{'text': 'Synthetic message'}]}}
        with (
            patch.object(turn, 'catalog_application', return_value=row),
            patch.object(turn, 'active', return_value=account),
            patch.object(turn, 'tool_definition', return_value={'version': 'fixture', 'no_auth': False}),
            patch.object(turn, 'composio', return_value=receipt) as execute,
        ):
            with self.assertRaises(employee_applications.AccountRequired):
                turn.execute(args, {})
            execute.assert_not_called()
            self.assertEqual(turn.connect('composio:gmail', args['tool']), {'state': 'connected'})
            self.assertEqual(self.settings('read')['applications'][0]['account']['id'], 'ca_wrong_app')
            self.assertEqual(turn.execute(args, {}), receipt)
            self.assertEqual(execute.call_args.kwargs['account'], 'ca_wrong_app')
        activity.request_user_input.assert_not_called()

    def test_settings_change_during_authorization_does_not_restore_removed_connection(self):
        row = {'provider': 'composio', 'id': 'slack', 'name': 'Slack'}
        activity = Mock()
        activity.on_event.side_effect = lambda event: (
            self.settings('set', row=row, remove=True) if event['kind'] == 'employee_app_authorization' else None)
        cancel = Mock()
        cancel.is_set.return_value = False
        turn = self.turn([row], activity, cancel)
        account = {'ca_new': {'id': 'ca_new', 'name': 'New workspace'}}
        with (
            patch('webbrowser.open'),
            patch.object(turn, 'active', side_effect=[{}, account]),
            self.assertRaisesRegex(employee_applications.AccountRequired, '配置已更新'),
        ):
            turn.connect('composio:slack')
        self.assertEqual(self.settings('read')['applications'], [])
        self.assertEqual(activity.on_event.call_args.args[0]['state'], 'interrupted')

    def test_github_repository_list_uses_saved_connection_without_confirmation(self):
        activity = Mock()
        turn = self.turn([], activity)
        args = {'operation': 'call', 'application': 'composio:github',
                'tool': 'GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER', 'version': 'fixture',
                'arguments': {'per_page': 5, 'sort': 'updated', 'direction': 'desc', 'type': 'all'}}
        row = {'provider': 'composio', 'id': 'github', 'name': 'GitHub',
               'account': {'id': 'ca_fixture', 'name': 'Example GitHub account'}}
        receipt = {'result': {'repositories': ['example/repo']}}
        with (
            patch.object(turn, 'active', return_value={'ca_fixture': row['account']}),
            patch.object(turn, 'tool_definition', return_value={'version': 'fixture', 'no_auth': False}),
            patch.object(turn, 'composio', return_value=receipt) as execute,
        ):
            with self.assertRaises(employee_applications.AccountRequired):
                turn.execute(args, {})
            execute.assert_not_called()
            self.settings('set', row=row, remove=False)
            self.assertEqual(turn.execute(args, {}), receipt)
            self.assertEqual(execute.call_args.kwargs['account'], 'ca_fixture')
            self.assertEqual(execute.call_args.kwargs['arguments'], args['arguments'])
        activity.request_user_input.assert_not_called()

    def test_authorization_opens_validated_url_and_confirms_exact_account(self):
        from runteams_core.agents.agent_stream import present_trace_events
        row = {'provider': 'composio', 'id': 'slack', 'name': 'Slack',
               'account': {'id': 'ca_inactive', 'name': 'Old workspace'}}
        activity = Mock()
        cancel = Mock()
        cancel.is_set.return_value = False
        turn = self.turn([row], activity, cancel)
        def active(_row):
            return {'ca_new': {'id': 'ca_new', 'name': 'New workspace'}} if activity.on_event.called else {}
        with patch.object(turn, 'active', side_effect=active), patch('webbrowser.open', return_value=True) as open_tab:
            self.assertEqual(turn.connect('composio:slack'), {'state': 'connected'})
            open_tab.assert_called_once_with('https://connect.composio.dev/link/test-only', new=2)
        events = [call.args[0] for call in activity.on_event.call_args_list]
        self.assertTrue(events[0]['opened'])
        self.assertEqual(events[1]['state'], 'connected')
        self.assertEqual(self.settings('read')['applications'][0]['account']['id'], 'ca_new')
        activity.request_user_input.assert_not_called()
        history = present_trace_events([{'type': 'agent_event', 'event': event} for event in events])
        self.assertEqual(len(history), 1)
        self.assertNotIn('https://', json.dumps(history))
        with patch('webbrowser.open') as open_tab, self.assertRaises(ValueError):
            employee_applications.open_authorization('https://untrusted.test/link/a')
        open_tab.assert_not_called()

    def test_failed_without_error_string_is_never_success(self):
        self.mode = 'failed'; result = self.call('test', **self.body())
        self.assertTrue(result['result']['isError']); self.assertEqual(result['result']['result_type'], 'failed')

    def test_unknown_outcome_replay_does_not_repeat_effect(self):
        self.mode = 'timeout'; body = self.body()
        for _ in range(2): self.assertEqual(self.call('test', **body)['code'], 'outcome_unknown')
        self.assertEqual(self.effects, 1)

    def test_bad_schema_account_version_and_injected_endpoint_never_execute(self):
        body = self.body()
        for override in ({'account': 'ca_foreign'}, {'tool': '../slack'}, {'version': 'old'}):
            with self.subTest(override=override), self.assertRaises(ValueError): self.call('test', **{**body, **override})
        self.assertEqual(self.call('test', **{**body, 'arguments': {}})['code'], 'invalid_arguments')
        with self.assertRaises(ValueError): self.call('test', **body, user_id='other')
        self.assertEqual(self.effects, 0)

    def test_remove_key_rejects_stale_calls_and_retains_existing_mcp(self):
        self.call('remove', revision=self.revision)
        self.assertFalse(self.call('status')['configured'])
        self.assertEqual(len(mcp_connections.dispatch('GET', {}, None)['connections']), 3)
        self.assertEqual(self.call('test', **self.body())['code'], 'not_configured')


class HTTPTransportTests(unittest.TestCase):
    def test_fixed_origin_encoded_filters_no_redirect_and_bounded_reads(self):
        with patch.object(http.client, 'HTTPSConnection') as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 200; response.read.return_value = b'{"items":[]}'
            result = composio.request(KEY, 'GET', '/toolkits', query={'search': 'a&b', 'cursor': '+=/'})
            factory.assert_called_once_with('backend.composio.dev', timeout=35)
            self.assertIn('search=a%26b', factory.return_value.request.call_args.args[1])
            self.assertEqual(result, {'items': []})
            response.status = 302
            with self.assertRaises(composio.ComposioError): composio.request(KEY, 'GET', '/toolkits')
            response.status = 200; response.read.return_value = b'x' * (composio.MAX_RESPONSE + 1)
            with self.assertRaises(composio.ComposioError): composio.request(KEY, 'GET', '/toolkits')

    def test_transport_error_on_write_is_unknown_without_retry(self):
        with patch.object(http.client, 'HTTPSConnection') as factory:
            factory.return_value.getresponse.side_effect = TimeoutError()
            with self.assertRaises(composio.ComposioError) as caught:
                composio.request(KEY, 'POST', '/tool_router/session/trs_x/execute', body={}, execution=True)
            self.assertEqual(caught.exception.code, 'outcome_unknown')
            factory.return_value.request.assert_called_once()


if __name__ == '__main__': unittest.main()
