import unittest
from unittest.mock import patch

from runteams_core.pipelines.source_pipeline_settings import _settings_employees


class SettingsMembersTests(unittest.TestCase):
    def setUp(self):
        self.members = [{'ref': key, 'source': key + '.json'} for key in ('one', 'two', 'unused')]
        self.members.append({'ref': 'external', 'dependency': {'kind': 'source'}})
        self.asset = {
            'employees': self.members,
            'pipeline': {'positions': [{'name': name, 'employee_ref': name}
                                       for name in ('one', 'two', 'external')]},
        }
        self.files = {'project.json': b'{}'}
        self.ref = {'source_id': 'project'}
        self.catalog = {'employees': {m['source']: {'employee': {'name': m['ref']}}
                                      for m in self.members if 'source' in m}}

    def read(self, *, invalid=False, rented=False):
        with patch('runteams_core.authoring.source.creator_source_import.compile_source') as validate, \
             patch('runteams_core.authoring.compilation.creator_mcp_source.packages'), \
             patch('runteams_core.authoring.source.creator_source_import.validate_dependency_sources'), \
             patch('runteams_core.authoring.creator_conversation_assets.compile_catalog', return_value=self.catalog) as compile_catalog, \
             patch('runteams_core.employees.employee_references.source_reference', side_effect=lambda _, path: path), \
             patch('runteams_core.assets.rented_references.is_rented', return_value=rented), \
             patch('runteams_core.pipelines.pipeline_employee_dependencies.describe', return_value={
                 'reference': 'bound', 'asset': {'employee': {'name': 'Bound'}}, 'revision': 'pinned'}) as resolve:
            if invalid:
                validate.side_effect = ValueError('invalid source')
            rows = _settings_employees(self.ref, 'head', self.files, self.asset)
            if rented:
                validate.assert_not_called()
                self.assertEqual(resolve.call_count, 3)
            else:
                validate.assert_called_once_with(self.files)
                resolve.assert_called_once_with(self.ref, self.members[-1], 'head')
                if not invalid:
                    compile_catalog.assert_called_once_with(self.files, validate.return_value)
            return rows

    def test_shared_snapshot_is_compiled_once_and_dependencies_keep_their_revision(self):
        rows = self.read()
        self.assertEqual([r['name'] for r in rows], ['one', 'two', 'Bound'])
        self.assertEqual([r['revision'] for r in rows], ['head', 'head', 'pinned'])

    def test_invalid_shared_snapshot_keeps_independent_member_settings_available(self):
        rows = self.read(invalid=True)
        self.assertEqual([r.get('error') for r in rows], ['invalid source', 'invalid source', None])

    def test_rented_members_use_the_existing_individual_resolver(self):
        self.assertTrue(all(r['reference'] == 'bound' for r in self.read(rented=True)))
