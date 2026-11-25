"""Employee navigation reuses editable conversations without changing work history."""
from pathlib import Path
from library_fixture import temporary_library
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from runteams_core.application.local_application import LocalApplication
from runteams_core.authoring.creator_local_authoring import workspace
from runteams_core.authoring.source.creator_local_source import current_store
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.storage import device_data, product_store


class UnifiedEmployeeConversationTests(unittest.TestCase):
    def test_same_entry_editing_and_idempotent_new_conversations(self):
        source = str(Path(__file__).resolve().parents[1])
        python_path = os.environ.get('PYTHONPATH')
        if python_path:
            source += os.pathsep + python_path
        with temporary_library() as directory:
            subprocess.run([sys.executable, '-B', __file__, directory], check=True, timeout=45,
                           env={**os.environ, 'PYTHONPATH': source,
                                'RUNTEAMS_DATA': directory, 'RUNTEAMS_AUTOMATION_DISPATCH': '0'})


def verify(directory):
    from test_employee_pipeline_groups import save_project
    app = LocalApplication(Path(directory))
    check = unittest.TestCase()
    try:
        with app.runtime.scope():
            store = current_store(device_data.identity()['cache_scope'])
            source_id = save_project(store, 'team', [('one', 'Employee one', '👤'), ('two', 'Employee two', '👤')])
            single_source = save_project(store, 'single', [('one', 'Single employee', '👤')])

        def open_employee(source, name='one', **extra):
            payload = {'key': f'source:{source}:employees/{name}.json', 'runtime': {}, **extra}
            return app.dispatch('POST', '/api/employee-directory/open', payload)['session']

        catalog_path = 'runteams_core.agents.models.model_channels.require_catalog'

        def only_codex(channel, **_):
            if channel['provider'] != 'codex':
                raise ValueError('渠道尚未连接')
            return {'models': [{'value': 'fixture-codex', 'efforts': ['low', 'high']}]}

        with patch(catalog_path, side_effect=only_codex):
            first = open_employee(source_id)
        check.assertEqual((first['channel_id'], first['model']), (2, 'fixture-codex'))
        check.assertEqual(first['kind'], 'employee_design')
        check.assertEqual(first['id'], open_employee(source_id)['id'])
        check.assertNotEqual(first['id'], open_employee(source_id, 'two')['id'])

        # Reading a saved employee in conversation does not require a builder.
        from runteams_core.agents.tools.agent_tool_registry import dispatch
        from runteams_core.foundation.identity.work_identity import principal
        with app.runtime.scope(), patch(
            'runteams_core.employees.source_employee_runtime.prepare',
            side_effect=AssertionError('Employee context must not start a build'),
        ):
            context = {'chat_id': first['id'], 'actor_id': principal(device_data.identity())}
            for tool in ('runteams_get_context', 'runteams_get_employee'):
                employee = dispatch(tool, {}, context).data['employee']
                check.assertEqual(employee['name'], 'Employee one')
                check.assertEqual(employee['reference']['employee_source'], 'employees/one.json')
                check.assertTrue(employee['source_revision'])

        # Editing uses the existing validated revision path, then both entries
        # still resolve the same chat even though the employee version changed.
        with app.runtime.scope():
            product_store.add_chat_message(first['id'], 'user', 'Remember my instructions.')
            with workspace(first) as files:
                (files/'soul.md').write_text('Revised employee instructions.', encoding='utf-8')
            revision = Revisions(store, source_id).current()['revision']
            check.assertEqual(Revisions(store, source_id).files_at(revision)['soul.md'], b'Revised employee instructions.')
        reopened = open_employee(source_id)
        check.assertEqual(reopened['id'], first['id'])
        check.assertEqual(reopened['messages'][0]['text'], 'Remember my instructions.')

        with app.runtime.scope():
            device_data.update_settings({'default_model': '1::fixture-claude'})

        def both_channels(channel, **_):
            return (only_codex(channel) if channel['provider'] == 'codex' else
                    {'models': [{'value': 'fixture-claude', 'efforts': ['low', 'high']}]})

        with patch(catalog_path, side_effect=both_channels):
            chosen = open_employee(source_id, operation_id='db5ec288-8ef2-46ad-a329-89d20d0a1dbc')
        check.assertEqual((chosen['channel_id'], chosen['model']), (1, 'fixture-claude'))

        new_request = {'operation_id': '8f368467-2303-4ca3-8e15-f1549374485d'}
        with patch(catalog_path, side_effect=ValueError('渠道尚未连接')):
            fresh = open_employee(source_id, **new_request)
        check.assertIsNone(fresh['channel_id'])
        check.assertEqual(fresh['model'], '')
        check.assertNotEqual(fresh['id'], first['id'])
        check.assertEqual(fresh['id'], open_employee(source_id, **new_request)['id'])
        check.assertEqual(fresh['id'], open_employee(source_id)['id'])
        with check.assertRaises(ValueError):
            open_employee(source_id, 'two', **new_request)

        # A single-employee original creation conversation is reusable.
        from runteams_core.authoring.creator_local_authoring import session_for
        with app.runtime.scope():
            original = session_for(store, single_source, device_data.identity()['cache_scope'], {})
        check.assertEqual(open_employee(single_source)['id'], original['id'])
    finally:
        app.close()


if __name__ == '__main__':
    if len(sys.argv) == 2:
        verify(sys.argv[1])
    else:
        unittest.main()
