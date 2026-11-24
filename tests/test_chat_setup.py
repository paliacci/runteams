from contextlib import contextmanager, nullcontext
import json
import sqlite3
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import uuid

from runteams_core.configuration import chat_setup
from runteams_core.configuration.employee_configuration import (
    ConfigurationConflict, ConfigurationInvalid, ConfigurationStore,
)


class ChatSetupTest(TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE device_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.scope = {'account_id': 'testing', 'cache_scope': 'setup-test'}
        self.device = self.enterContext(patch('runteams_core.configuration.employee_configuration.device_data'))
        self.device.identity.return_value = self.scope
        self.device.personal.return_value = True
        self.device.connect.side_effect = self.connect
        self.definition = {'schema': 'runteams.employee-configuration/1', 'groups': [
            {'key': 'setup', 'label': 'Setup', 'fields': [
                {'key': 'audience', 'label': 'Audience', 'type': 'text', 'required': True},
                {'key': 'format', 'label': 'Format', 'type': 'text', 'required': True},
                {'key': 'location', 'label': 'Local file', 'type': 'file_path'},
            ]},
        ]}
        self.store = ConfigurationStore({'employee': 'test'}, self.definition, 'version')
        self.turn = chat_setup.SetupTurn(111, 222, 'epoch', self.scope, 'employee', {'employee': 'test'}, Event())

    @contextmanager
    def connect(self, **options):
        with self.db:
            yield self.db

    def operation(self, **changes):
        return {'operation_id': str(uuid.uuid4()), 'expected_revision': self.store.read()['revision'],
                'definition_sha256': self.store.definition_sha256, **changes}

    def test_safe_partial_save_keeps_unprovided_grants_and_other_values(self):
        wrong_path = '/private/device/input.txt'
        self.store.save(**self.operation(values={'audience': 'Editors', 'format': 'Brief', 'location': wrong_path}))
        # An existing grant stays intact even when its original field is
        # retired. Replacing an unrelated scalar does not touch that grant.
        row = self.store._load(self.db)
        row['bindings'] = {'retired': {'grant_id': 41}}
        self.db.execute('UPDATE device_settings SET value=? WHERE key=?', (json.dumps(row), self.store.key))
        self.db.commit()
        request = self.operation(values={'audience': 'Reviewers'}, patch_values=True)
        result = self.store.save(**request)
        self.assertEqual(result['values'], {'audience': 'Reviewers', 'format': 'Brief', 'location': wrong_path})
        self.assertEqual(self.store._load(self.db)['bindings'], row['bindings'])
        self.assertEqual(self.store.save(**request), result)
        with self.assertRaises(ConfigurationConflict):
            self.store.save(**{**request, 'values': {'audience': 'Changed'}})
        with self.assertRaises(ConfigurationInvalid):
            self.store.save(**self.operation(values={'location': '/tmp/injected'}, patch_values=True))

    def test_setup_turn_checks_partial_readiness_and_rejects_stale_intent(self):
        with patch.object(chat_setup, '_store', return_value=nullcontext(self.store)):
            initial = chat_setup._execute(self.turn, {'operation': 'inspect'}, '')
            self.assertFalse(initial['ready'])
            current = initial['targets'][0]
            self.assertEqual(current['settings_link'], 'runteams://configuration/111')
            update = {'operation': 'save', 'target': 'employee', 'revision': current['revision'],
                      'definition_sha256': current['definition_sha256'], 'values': {'audience': 'Editors'},
                      'intent': '保存受众为 Editors'}
            with self.assertRaises(ValueError):
                chat_setup._execute(self.turn, update, '查看开工配置')
            saved = chat_setup._execute(self.turn, update, '请保存受众为 Editors')
            self.assertEqual(saved['status'], 'saved')
            self.assertFalse(saved['ready'])
            self.assertEqual({item['key']: item['state'] for item in saved['targets'][0]['fields']},
                             {'audience': 'configured', 'format': 'missing', 'location': 'missing'})

    def test_pipeline_visits_own_and_bound_employee_positions(self):
        turn = chat_setup.SetupTurn(111, 222, 'epoch', self.scope, 'pipeline', {'pipeline': 'test'}, Event())
        asset = {'employees': [{'ref': 'reviewer', 'source': 'employees/reviewer.json'}], 'pipeline': {
            'positions': [{'key': 'review', 'name': 'Review', 'kind': 'employee', 'employee_ref': 'reviewer'},
                          {'key': 'approval', 'name': 'Approval', 'kind': 'approval'}]}}
        own = Mock(return_value=nullcontext(self.store))
        role = Mock(return_value=nullcontext(self.store))
        context = SimpleNamespace(definition=lambda ref: ('revision', asset),
                                  own_configuration_store=own, configuration_store=role)
        with patch('runteams_core.pipelines.pipeline_context.current', return_value=context):
            result = chat_setup._execute(turn, {'operation': 'inspect'}, '')
            self.assertEqual([(item['target'], item.get('position'), item['settings_link']) for item in result['targets']],
                             [('pipeline', None, 'runteams://configuration/111'),
                              ('position', 'review', 'runteams://configuration/111?position=review')])
            with self.assertRaises(PermissionError):
                chat_setup._execute(turn, {'operation': 'inspect', 'target': 'position', 'position': 'approval'}, '')
        own.assert_called_once_with(turn.reference)
        role.assert_called_once_with(turn.reference, 'employees/reviewer.json')

    def test_authoring_scope_reuses_source_store_and_background_is_excluded(self):
        source = {'source_id': 'example', 'employee_source': 'employees/main.json'}
        with patch.object(chat_setup.product_store, 'get_chat', return_value={'kind': 'employee_design', 'context': {}}), \
                patch.object(chat_setup.product_store, 'device_chat', return_value=True), \
                patch('runteams_core.automation.chat_automation_tool._binding', return_value=('employee', source)), \
                patch.object(chat_setup.device_data, 'personal', return_value=True), \
                patch.object(chat_setup.configuration, 'for_source', return_value=nullcontext(self.store)) as load:
            kind, reference = chat_setup._binding(111)
            self.assertEqual((kind, reference), ('employee', source))
            turn = chat_setup.SetupTurn(111, 222, 'epoch', self.scope, kind, reference, Event())
            with chat_setup._store(turn, {'target': kind}) as store:
                self.assertIs(store, self.store)
            load.assert_called_once_with(source)
            cancel = Event()
            cancel.background_employee_work = True
            self.assertFalse(chat_setup.bind_turn({'chat_id': 111}, 222, cancel))

    def test_private_values_not_projected(self):
        public = self.store.save(**self.operation(values={'audience': 'Editors', 'format': 'Brief', 'location': '/private/real.txt'}))
        projected = chat_setup._view(111, {'target': 'employee'}, public)
        location = next(field for field in projected['fields'] if field['key'] == 'location')
        self.assertEqual(location['input'], 'settings')
        self.assertEqual(location['state'], 'unavailable')
        self.assertNotIn('value', location)
        self.assertNotIn('/private/real.txt', json.dumps(projected))
