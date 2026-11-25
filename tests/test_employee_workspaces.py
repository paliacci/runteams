from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runteams_core.employees.employee_workspaces import skill_root
from runteams_core.foundation.regular_files import storage_path


class EmployeeWorkspaceTests(unittest.TestCase):
    def deep_workspace(self):
        folder = tempfile.TemporaryDirectory(dir=storage_path(tempfile.gettempdir()))
        self.addCleanup(folder.cleanup)
        root = Path(tempfile.gettempdir()) / Path(folder.name).name
        return root / ('资料-' + 'a' * 80) / ('团队-' + 'b' * 80) / ('员工-' + 'c' * 80)

    def test_configuration_in_deep_employee_workspace(self):
        from runteams_core.configuration.employee_configuration import _materialize
        work = self.deep_workspace()
        result = _materialize({'values': {}, 'states': {}, 'bindings': {}}, work)
        self.assertEqual(result['resources'], {})
        self.assertTrue(storage_path(work / '.runteams/configuration').is_dir())

    def test_handoff_report_in_deep_employee_workspace(self):
        from runteams_core.pipelines.source_pipeline_flow import _export_report
        work = self.deep_workspace()
        storage_path(work).mkdir(parents=True)
        with patch('runteams_core.documents.document_export.export_document', return_value=(b'report', None, None)), \
             patch('runteams_core.employees.employee_workspaces.workspace', return_value=work):
            result = _export_report(None, 1, {'id': 2})
            self.assertEqual(Path(result['path']).read_bytes(), b'report')
            self.assertEqual(_export_report(None, 1, {'id': 2}), result)

    def test_task_inputs_in_deep_employee_workspace(self):
        from runteams_core.work import task_inputs
        work = self.deep_workspace()
        root = work.parents[2]
        source = root / '原始输入.txt'
        source.write_text('复核资料', encoding='utf-8')
        with patch.object(task_inputs, '_source_for_item', return_value=source):
            result = task_inputs.materialize(root, 1, [{'name': '复核.txt'}], work)
        relative = Path(result[0]['path'])
        self.assertEqual(relative, Path('.runteams/inputs/复核.txt'))
        saved = storage_path(work / relative)
        self.assertEqual(saved.read_text(encoding='utf-8'), '复核资料')
        self.assertEqual(task_inputs.materialize(root, 1, [], work), [])
        self.assertFalse(saved.exists())

    def test_reopen_skill_in_deep_release_directory(self):
        with tempfile.TemporaryDirectory(dir=storage_path(tempfile.gettempdir())) as directory:
            # Call the public entry with the ordinary path a library binding supplies.
            work = Path(tempfile.gettempdir()) / Path(directory).name
            for name in ('资料库', 'employee-workspaces', '员工工作目录'):
                work /= name + '-' + 'a' * 60
            digest = 'f' * 64
            root = skill_root(work, digest)
            skill = root / 'bundle' / 'SKILL.md'
            self.assertGreater(len(str(skill)), 260)
            skill.parent.mkdir()
            skill.write_text('技能内容', encoding='utf-8')
            reopened = skill_root(work, digest)
            self.assertEqual((reopened / 'bundle' / 'SKILL.md').read_text(encoding='utf-8'), '技能内容')
