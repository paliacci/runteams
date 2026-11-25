from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from library_fixture import temporary_library
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from runteams_core.assets import knowledge_archive as media
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, tree
from runteams_core.authoring.source import knowledge_packages
from runteams_core.authoring.source.creator_local_source import LocalSources, current_store
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.conversations import asset_memory, asset_sources
from runteams_core.storage import device_data, local_database, storage_context
from runteams_core.storage.local_library import LocalLibrary


class PortableMaterialsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(temporary_library())).resolve()
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

    def test_snapshot_personal_materials_by_owner_and_checksum(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(local_database, 'DB_PATH', str(self.root / 'db')))
            stack.enter_context(storage_context.using(LocalLibrary()))
            store = current_store(device_data.identity()['cache_scope'])
            files = {**self.files, self.owner: canonical({'name': 'Topic', 'avatar': '👋'})}
            media.write_archive(self.archive, files, self.blobs.__getitem__)
            report = {**self.report(None), 'source': tree(files)}
            draft = knowledge_packages.receive(store, self.archive, lambda _raw: report)
            identity = draft['id']
            employee = knowledge_packages.source_asset_reference(store, identity, files, self.owner)
            team = knowledge_packages.source_asset_reference(store, identity, files, self.flow)
            employee_bank, team_bank = map(asset_memory.bank_for, (employee, team))
            with device_data.connect() as connection:
                asset_sources._store(connection, employee_bank, 'selected.txt', b'personal', [])
                asset_sources._store(connection, employee_bank, 'unused.txt', b'unelected', [])
                asset_sources._store(connection, team_bank, 'private.txt', b'other asset', [])
            choices = knowledge_packages.personal_choices(store, identity, self.owner, identity)
            self.assertEqual([row['name'] for row in choices['sources']], ['selected.txt', 'unused.txt'])
            row = choices['sources'][0]
            selected = [{key: row[key] for key in ('id', 'sha256')}]
            with self.assertRaises(CreatorContractError):
                with knowledge_packages.personal_snapshot(store, identity, files, self.flow, selected):
                    self.fail('Another asset must not obtain this material')

            revisions = Revisions(store, identity)
            with knowledge_packages.personal_snapshot(store, identity, files, self.owner, selected) as (updated, stage):
                result = revisions.commit(updated, identity, 'select-material', knowledge_stage=stage)
            mapping = media.index(revisions.files_at(result['revision']))
            self.assertEqual([row['path'] for row in mapping[self.owner]], ['reference.txt', 'selected.txt'])
            self.assertEqual(mapping[self.flow], self.mapping[self.flow])

            with device_data.connect() as connection:
                original = connection.execute('SELECT original FROM asset_sources WHERE id=?', (row['id'],)).fetchone()[0]
                self.assertEqual(original, b'personal')
                asset_sources._store(connection, employee_bank, 'selected.txt', b'changed!', [])
            with self.assertRaisesRegex(CreatorContractError, '已更新'):
                with knowledge_packages.personal_snapshot(store, identity, files, self.owner, selected):
                    self.fail('A stale selection must not be staged')

            with knowledge_packages.download(store, identity, result['revision']) as (stream, _):
                with ZipFile(stream) as archive:
                    self.assertEqual(archive.read('knowledge/' + row['sha256']), b'personal')
