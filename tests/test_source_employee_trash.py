"""Exercise roster removal through the local application's public endpoints."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from runteams_core.application.local_application import LocalApplication
from runteams_core.authoring.source.creator_local_source import current_store
from runteams_core.storage import device_data
from test_employee_pipeline_groups import member, save_project


class SourceEmployeeTrashTests(unittest.TestCase):
    def test_trashing_original_preserves_separate_installed_market_employee(self):
        from runteams_core.assets.asset_references import BusinessReference
        from runteams_core.employees.employee_directory import assemble
        ref = BusinessReference('https://test.invalid/auth/v1', '11111111-1111-4111-8111-111111111111',
                                '22222222-2222-4222-8222-222222222222', 'employees', 1).to_json()
        source = {'key': 'source:test', 'record': {'name': 'Original'}, 'source': {'id': 'test'}, 'reference': ref}
        installed = {'id': 42, 'name': 'Installed', 'native_asset': {'employee_reference': ref},
                     'origin': {'kind': 'marketplace'}}
        self.assertEqual(assemble([source], [], [installed])[0]['key'], source['key'])
        copy, = assemble([{**source, 'trashed': True}], [], [installed])
        self.assertIsNone(copy['source'])
        self.assertEqual(copy['work'], installed)
        grouped = {**source, 'trashed': True, 'pipeline_groups': [{'key': 'team'}]}
        self.assertEqual(assemble([grouped], [], [installed]), [])

    def test_one_employee_can_be_restored_without_changing_shared_pipeline_sources(self):
        with TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c',
                            'import runpy, sys; sys.path.insert(0, sys.argv[1]); '
                            'runpy.run_path(sys.argv[2])["check"](sys.argv[3])',
                            str(Path(__file__).parent), __file__, directory], check=True, timeout=45,
                           env={**os.environ, 'RUNTEAMS_DATA': directory, 'RUNTEAMS_AUTOMATION_DISPATCH': '0'})


def check(directory):
    app = LocalApplication(Path(directory))
    test = unittest.TestCase()
    def roster():
        return app.dispatch('GET', '/api/employee-directory', {})['items']
    def trash():
        return app.dispatch('GET', '/api/device/work/trash', {}).payload['items']
    def change(action, **data):
        return app.dispatch('POST', '/api/device/work/source-employees/' + action, data)
    try:
        with app.runtime.scope():
            store = current_store(device_data.identity()['cache_scope'])
            save_project(store, 'team', [('first', '同名员工', '👤'), ('second', '同名员工', '👤')],
                         [('team', 'Team', [member('first')])])
        sibling, target = sorted(roster(), key=lambda row: not row.get('pipeline_groups'))
        with test.assertRaisesRegex(ValueError, '属于流水线'):
            change('trash', reference=sibling['source']['reference'])
        test.assertEqual(trash(), [])
        def pipeline(action, **data):
            return app.dispatch('POST', '/api/device/work/source-pipelines/' + action, data)
        parent, = pipeline('catalog')['items']
        pipeline('trash', reference=parent['reference'])
        test.assertEqual([row['key'] for row in roster()], [target['key']])
        with test.assertRaisesRegex(ValueError, '先恢复'):
            app.dispatch('POST', '/api/employee-directory/open', {'key': sibling['key'], 'runtime': {}})
        deleted, = pipeline('trash-catalog')['items']
        pipeline('restore', reference=parent['reference'], id=deleted['id'])
        test.assertEqual({row['key'] for row in roster()}, {target['key'], sibling['key']})
        ref = target['source']['reference']
        app.dispatch('POST', '/api/employee-directory/open', {'key': target['key'], 'runtime': {}})
        test.assertTrue(change('trash', reference=ref)['trashed'])
        test.assertTrue(change('trash', reference=ref)['trashed'])
        test.assertEqual([row['key'] for row in roster()], [sibling['key']])
        item, = trash()
        test.assertEqual((item['kind'], item['reference'], item['can_delete']), ('employee', ref, False))
        with test.assertRaisesRegex(ValueError, '先恢复'):
            app.dispatch('POST', '/api/employee-directory/open', {'key': target['key'], 'runtime': {}})
        test.assertFalse(change('restore', reference=ref, id=item['id'])['trashed'])
        restored = next(row for row in roster() if row['key'] == target['key'])
        test.assertEqual(restored['page_id'], target['page_id'])
        test.assertFalse(restored.get('pipeline_groups'))
        test.assertIsNotNone(restored['source']['chat_id'])
        test.assertEqual(trash(), [])
        change('trash', reference=ref)
        with test.assertRaisesRegex(ValueError, '记录已变化'):
            change('restore', reference=ref, id=item['id'])
        test.assertEqual([row['key'] for row in roster()], [sibling['key']])
    finally:
        app.close()
