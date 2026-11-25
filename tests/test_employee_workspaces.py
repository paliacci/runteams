from pathlib import Path
import tempfile
import unittest

from runteams_core.employees.employee_workspaces import skill_root
from runteams_core.foundation.regular_files import storage_path


class EmployeeWorkspaceTests(unittest.TestCase):
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
