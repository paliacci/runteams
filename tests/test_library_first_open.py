from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import tempfile
import unittest
import uuid

from runteams_core.foundation.durable_files import publish_json
from runteams_core.foundation.regular_files import storage_path
from runteams_core.foundation.identity import device_namespace, library_identity
from runteams_core.storage.local_library import LocalLibrary


class LibraryFirstOpenTests(unittest.TestCase):
    def test_replace_json_in_deep_restore_directory(self):
        with tempfile.TemporaryDirectory(dir=storage_path(tempfile.gettempdir())) as folder:
            root = Path(tempfile.gettempdir()) / Path(folder).name
            parent = root / ('恢复-' + 'a' * 80) / ('资料-' + 'b' * 80) / ('对话-' + 'c' * 60)
            storage_path(parent).mkdir(parents=True)
            record = parent / 'folders.json'
            publish_json(record, {'state': '创建'})
            publish_json(record, {'state': '恢复'}, replace=True)
            self.assertEqual(json.loads(storage_path(record).read_bytes()), {'state': '恢复'})
            self.assertEqual([p.name for p in storage_path(parent).iterdir()], ['folders.json'])

    def test_concurrent_first_launch_and_account_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / '资料 库'
            with ThreadPoolExecutor(max_workers=4) as pool:
                libraries = list(pool.map(lambda _: LocalLibrary().resolve(base), range(8)))
            self.assertTrue(all(item == libraries[0] for item in libraries))
            scope = {'deployment_id': 'https://example.test/auth/v1', 'account_id': '测试'}
            with ThreadPoolExecutor(max_workers=4) as pool:
                records = list(pool.map(lambda _: device_namespace.resolve(base, scope), range(8)))
            self.assertTrue(all(record == records[0] for record in records))
            root = base / records[0]['storage_namespace']
            with ThreadPoolExecutor(max_workers=4) as pool:
                ids = list(pool.map(lambda _: library_identity.identity(root, str(uuid.uuid4())), range(8)))
            self.assertEqual(len(set(ids)), 1)
            self.assertEqual(library_identity.identity(root, str(uuid.uuid4())), ids[0])

    def test_failed_write_preserves_previous_record_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / '账户.json'
            publish_json(record, {'state': '原始'})
            with self.assertRaises(FileExistsError):
                publish_json(record, {'state': 'duplicate'})
            with self.assertRaises(TypeError):
                publish_json(record, {'invalid': object()}, replace=True)
            self.assertEqual(json.loads(record.read_bytes()), {'state': '原始'})
            self.assertEqual(list(record.parent.iterdir()), [record])
            publish_json(record, {'state': '更新'}, replace=True)
            self.assertEqual(json.loads(record.read_bytes()), {'state': '更新'})
