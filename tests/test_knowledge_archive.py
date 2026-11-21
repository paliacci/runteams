from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

from runteams_core.assets import knowledge_archive as media
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, tree
from runteams_core.authoring.source import knowledge_packages
from runteams_core.authoring.source.creator_local_source import LocalSources


class PortableMaterialsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.owner = 'employees/topic.json'
        self.flow = 'pipelines/team.json'
        self.source = {'project.json': canonical({'entrypoints': {'employees': [self.owner], 'pipelines': [self.flow]}})}
        folder = self.root / 'selected'
        folder.mkdir()
        (folder / 'reference.txt').write_text('original')
        self.files, self.blobs = media.inventory(self.source, {self.owner: folder, self.flow: folder})
        self.mapping = media.index(self.files)
        self.archive = self.root / 'example.zip'
        media.write_archive(self.archive, self.files, self.blobs.__getitem__)

    def report(self, _raw):
        return {'scope': 'local-preflight', 'source': tree(self.files), 'employees': 1, 'pipelines': 1,
                'dependencies': [], 'project': {'name': 'test', 'version': '1', 'key': 'test'}}

    def test_transfer_and_retry_with_original_removed(self):
        self.blobs[next(iter(self.blobs))].unlink()
        with ZipFile(self.archive) as archive:
            self.assertEqual(len(archive.infolist()), 2)
        store = LocalSources(self.root / 'other-library')
        def receive(_):
            return knowledge_packages.receive(store, self.archive, self.report)['id']
        with ThreadPoolExecutor(2) as pool:
            first, second = pool.map(receive, range(2))
        self.assertEqual(first, second)
        folder = knowledge_packages.location(store._directory(first), self.mapping)
        from runteams_core.conversations import asset_sources
        workspace = self.root / 'new-workspace'
        workspace.mkdir()
        for owner in (self.owner, self.flow):
            row = self.mapping[owner][0]
            bundled = {'verified': {**row, 'file': folder / row['sha256']}}
            self.assertEqual(asset_sources.excerpt('', 'verified', 1, 0, bundled=bundled)['text'], 'original')
            result = asset_sources.original('', 'verified', bundled, workspace)
            self.assertEqual(Path(result['path']).read_text(), 'original')
        Path(result['path']).write_text('modified')
        with self.assertRaises(CreatorContractError):
            asset_sources.original('', 'verified', bundled, workspace)

    def test_rejects_truncated_replaced_and_extra_objects(self):
        for case in ('missing', 'modified', 'extra', 'truncated'):
            with self.subTest(case=case):
                bad = self.root / (case + '.zip')
                if case == 'truncated':
                    bad.write_bytes(self.archive.read_bytes()[:-2])
                else:
                    with ZipFile(self.archive) as source, ZipFile(bad, 'w') as target:
                        for name in source.namelist():
                            if name != media.SOURCE and case == 'missing':
                                continue
                            body = source.read(name)
                            if name != media.SOURCE and case == 'modified':
                                body = bytes(len(body))
                            target.writestr(ZipInfo(name), body)
                        if case == 'extra':
                            target.writestr('../extra', b'x')
                store = LocalSources(self.root / case)
                with self.assertRaises(CreatorContractError):
                    knowledge_packages.receive(store, bad, self.report)
                self.assertEqual(store.list()['items'], [])

    def test_owner_escape_and_secret_files(self):
        for name in ('../image.png', '/tmp/test.png', 'auth.json', '.env', 'temp/tool.sh'):
            with self.assertRaises(CreatorContractError):
                media.file_name(name)
        with self.assertRaises(CreatorContractError):
            media.index({**self.files, media.INDEX: canonical({'employees/other.json': self.mapping[self.owner]})})
