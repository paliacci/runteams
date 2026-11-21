import sqlite3
import unittest
from unittest.mock import patch
import uuid

from runteams_core.configuration.asset_onboarding import remaining_steps
from runteams_core.configuration.configuration_schema import validate_declaration
from runteams_core.configuration.employee_configuration import ConfigurationConflict, ConfigurationInvalid, ConfigurationStore
from runteams_core.employees.mcp.composio_connections import ComposioError, compatible_applications


class AssetGuideTests(unittest.TestCase):
    def definition(self):
        return {
            'schema': 'runteams.employee-configuration/1',
            'groups': [{'key': 'setup', 'label': 'Setup', 'fields': [
                {'key': 'audience', 'label': 'Audience', 'type': 'text'},
                {'key': 'scope', 'label': 'Scope', 'type': 'text', 'default': 'All'},
                {'key': 'details', 'label': 'Details', 'type': 'textarea'},
            ]}],
            'application_requirements': [{'key': 'email', 'label': 'Connect email',
                                          'operations': ['mail.read', 'mail.draft']}],
            'onboarding': [
                {'title': 'Before you start', 'description': 'How to use this employee', 'questions': []},
                {'title': 'How to work', 'description': '', 'questions': [
                    {'field': key, 'prompt': key} for key in ('audience', 'scope', 'details')]},
                {'title': 'Connect', 'description': '', 'questions': [], 'application': 'email'},
            ],
        }

    def test_partial_projection_and_ready(self):
        definition = validate_declaration(self.definition())
        steps = remaining_steps(definition, {'audience': 'missing', 'scope': 'configured', 'details': 'needs_review'})
        self.assertEqual([question['field'] for question in steps[1]['questions']], ['audience', 'scope', 'details'])

    def test_model_cannot_invent_fields_or_connections(self):
        for key in ('application', 'field'):
            with self.subTest(key=key):
                definition = self.definition()
                item = definition['onboarding'][-1] if key == 'application' else definition['onboarding'][1]['questions'][0]
                item[key] = 'invented'
                with self.assertRaises(ValueError):
                    validate_declaration(definition)

    def test_guide_preserves_examples_for_text_inputs(self):
        definition = self.definition()
        question = definition['onboarding'][1]['questions'][0]
        question['placeholder'] = '  For example, the project team  '
        checked = validate_declaration(definition)
        steps = remaining_steps(checked, {'audience': 'missing'})
        self.assertEqual(steps[1]['questions'][0]['placeholder'], 'For example, the project team')
        definition['groups'][0]['fields'][0].update(
            type='select', options=[{'value': 'team', 'label': 'Project team'}])
        with self.assertRaisesRegex(ValueError, '文字输入'):
            validate_declaration(definition)

    def test_guide_save_preserves_settings_and_replays_original_receipt(self):
        import contextlib

        @contextlib.contextmanager
        def connect(**kwargs):
            with db:
                yield db

        with contextlib.closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE device_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            with patch('runteams_core.configuration.employee_configuration.device_data') as device:
                device.personal.return_value = True
                device.connect.side_effect = connect
                definition = self.definition()
                definition['groups'][0]['fields'].append({'key': 'outside', 'label': 'Outside', 'type': 'text', 'required': True})
                store = ConfigurationStore({'asset': 'guide'}, definition, 'r1')
                settings = ConfigurationStore({'asset': 'guide'}, definition, 'r1')
                request = {'operation_id': str(uuid.uuid4()), 'expected_revision': 0,
                           'definition_sha256': store.definition_sha256}
                settings.save(**{**request, 'values': {'scope': 'Existing', 'outside': 'Keep me'}})
                request.update(operation_id=str(uuid.uuid4()), expected_revision=1,
                               values={'audience': 'Team', 'scope': 'Updated'})
                result = store.save(**request, onboarding=True)
                self.assertEqual(result['values'], {'audience': 'Team', 'scope': 'Updated', 'outside': 'Keep me'})
                self.assertEqual(settings.read(), result)
                self.assertEqual(settings.snapshot()['values'], result['values'])
                self.assertEqual(store.save(**request, onboarding=True), result)
                with self.assertRaises(ConfigurationConflict):
                    store.save(**{**request, 'operation_id': str(uuid.uuid4())}, onboarding=True)
                with self.assertRaises(ConfigurationInvalid):
                    store.save(**{**request, 'expected_revision': 2, 'operation_id': str(uuid.uuid4()),
                                  'values': {'outside': 'Not in guide'}}, onboarding=True)
                self.assertEqual(store.read()['revision'], 2)

    def test_market_conversation_exposes_same_revision_as_configuration(self):
        from runteams_core.employees.employee_binding import summary
        revision = 'a' * 64
        reference = {'schema': 'runteams.business-reference/v1', 'resource': 'employees', 'id': 73}
        employee = {'name': 'Assistant', 'avatar': '👤', 'market_delivery': True,
                    'active_release': {'digest': revision, 'snapshot_json': {'work_units': []}}}
        self.assertEqual(summary({'employee': employee, 'reference': reference, 'package': None})['source_revision'],
                         revision)

    def test_provider_match_checks_exact_owned_operations_and_supports_pinning(self):
        toolkit = lambda slug: {'slug': slug}
        def read_tool(slug):
            return {'slug': slug, 'version': '1', 'toolkit': {'slug': slug.split('_')[0].lower()}}
        self.assertEqual([row['slug'] for row in compatible_applications(['mail.read', 'mail.draft'], toolkit, read_tool)],
                         ['gmail', 'outlook'])
        self.assertEqual([row['slug'] for row in compatible_applications(['mail.read'], toolkit, read_tool, toolkit_required='gmail')],
                         ['gmail'])
        def missing_drafts(slug):
            if slug == 'OUTLOOK_CREATE_DRAFT':
                raise ComposioError('Missing tool', status=404)
            return read_tool(slug)
        self.assertEqual([row['slug'] for row in compatible_applications(['mail.read', 'mail.draft'], toolkit, missing_drafts)],
                         ['gmail'])


if __name__ == '__main__':
    unittest.main()
