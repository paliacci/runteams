"""Ensure repository checks reject leaked local files and broken contributor links."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from runteams_core.devtools.check_repository import REQUIRED, check
from runteams_core.devtools.command_inventory import inventory


class RepositoryHygieneTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / 'runteams_core/devtools').mkdir(parents=True)
        for name in REQUIRED:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Project documentation\n')
        (self.root / 'tooling/commands.json').write_text(json.dumps(inventory(self.root, 'runteams_core')))
        (self.root / 'tooling/core-domains.json').write_text(json.dumps({
            'schema': 'runteams.core-domains/1', 'root_files': ['__init__.py'],
            'packages': {'devtools': 'Maintainer tools'}, 'subpackages': {}}))
        (self.root / 'docs/core-domains.md').write_text('Core domain navigation\n')
        self.stage()

    def stage(self):
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)

    def test_clean_source_with_internal_documentation_links(self):
        (self.root / 'README.md').write_text('[Development](docs/development.md)\n')
        self.stage()
        self.assertEqual(check(self.root, 'runteams_core')['repository_hygiene'], 'passed')

    def test_rejects_tracked_local_database_and_private_environment(self):
        for name in ['local.db', '.env.production']:
            with self.subTest(name=name):
                path = self.root / name
                path.write_text('disposable test fixture\n')
                self.stage()
                with self.assertRaisesRegex(ValueError, 'private local file'):
                    check(self.root, 'runteams_core')
                path.unlink()
                self.stage()

    def test_rejects_broken_contributor_navigation(self):
        (self.root / 'README.md').write_text('[Missing](docs/not-present.md)\n')
        self.stage()
        with self.assertRaisesRegex(ValueError, 'documentation link'):
            check(self.root, 'runteams_core')

    def test_rejects_business_modules_added_to_the_repository_root(self):
        (self.root / 'business.py').write_text('pass\n')
        self.stage()
        with self.assertRaisesRegex(ValueError, 'business Python source belongs in its package'):
            check(self.root, 'runteams_core')

    def test_rejects_core_modules_outside_an_owned_domain(self):
        (self.root / 'runteams_core/chat.py').write_text('pass\n')
        self.stage()
        with self.assertRaisesRegex(ValueError, 'core source belongs in its business domain'):
            check(self.root, 'runteams_core')


if __name__ == '__main__':
    unittest.main()
