"""Local pipelines resolve only their own sources and declared source pins."""
import unittest
from unittest.mock import patch

from runteams_core.pipelines import pipeline_employee_dependencies as dependencies
from runteams_core.pipelines.pipeline_context import current
from runteams_core.pipelines.pipeline_references import REFERENCE
from runteams_core.storage.local_library import LocalLibrary
from runteams_core.storage.storage_context import using
from runteams_core.authoring.creator_contracts import CreatorContractError


class LocalMemberTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(using(LocalLibrary()))
        self.pipeline = {'schema': REFERENCE, 'source_id': 'a' * 64}

    def test_inline_and_pinned_source_revisions(self):
        module = 'runteams_core.employees.source_employee_runtime'
        ref = self.enterContext(patch(module + '.reference', return_value='employee'))
        describe = self.enterContext(patch(module + '.describe', return_value={'asset': {}, 'reference': 'employee', 'revision': 'saved'}))
        self.enterContext(patch(module + '.units', return_value=[{'key': 'review'}]))
        prepare = self.enterContext(patch(module + '.prepare'))
        self.assertEqual(current().allowed_modes(self.pipeline), ['creator'])
        self.assertEqual(current().additional_pipelines(), [])
        dependencies.describe(self.pipeline, {'source': 'employee.json'}, 'head')
        ref.assert_called_with('a' * 64, 'employee.json')
        describe.assert_called_with('employee', revision='head')
        pin = {'kind': 'source', 'source_id': 'b' * 64, 'employee_source': 'pinned.json',
               'revision': 'c' * 64, 'skills': ['review']}
        dependencies.prepare(self.pipeline, {'dependency': pin}, 'operation', 'head', runtime_selection={'model': 'selected'})
        ref.assert_called_with('b' * 64, 'pinned.json')
        describe.assert_called_with('employee', revision=pin['revision'])
        prepare.assert_called_once_with('employee', 'operation', revision='saved', runtime_selection={'model': 'selected'})
        pin['skills'] = ['different']
        with self.assertRaises(CreatorContractError):
            dependencies.prepare(self.pipeline, {'dependency': pin}, 'operation', 'head')
        self.assertEqual(prepare.call_count, 1)

    def test_foreign_assets_rejected(self):
        host = current()
        foreign = {**self.pipeline, 'schema': 'foreign'}
        with self.assertRaises(PermissionError):
            host.allowed_modes(foreign)
        with self.assertRaises(PermissionError):
            dependencies.member_reference(foreign, {'source': 'x'})
        with self.assertRaises(PermissionError):
            host.member_assets(self.pipeline, {}, {'kind': 'download'})
