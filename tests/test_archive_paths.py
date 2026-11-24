from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runteams_core.assets.file_trees import safe_relative
from runteams_core.authoring.creator_contracts import relative
from runteams_core.employees.mcp.employee_mcp_package import safe_path
from runteams_core.foundation import archive_paths
from runteams_core.storage.backups.backup_files import safe_name


class ArchivePathTests(unittest.TestCase):
    def test_windows_readers_reject_names_that_change_on_disk(self):
        with patch.object(archive_paths, 'os', SimpleNamespace(name='nt')):
            for reader in (relative, safe_path, safe_relative, safe_name):
                for name in ('AUX.txt', 'a/NUL/file', 'out/data.', 'a /report',
                             'a.txt:notes', 'LPT¹.log', 'a/C:/b', 'out/a*b'):
                    with self.subTest(reader=reader.__name__, name=name), self.assertRaises(ValueError):
                        reader(name)
                self.assertEqual(reader('项目 a/开会 1.txt'), '项目 a/开会 1.txt')

    def test_existing_posix_package_names_can_still_be_read_on_mac(self):
        with patch.object(archive_paths, 'os', SimpleNamespace(name='posix')):
            self.assertEqual(relative('examples/AUX.txt'), 'examples/AUX.txt')
