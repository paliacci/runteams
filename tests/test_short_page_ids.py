from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from runteams_core.storage import page_id_store


class ShortPageIdTests(unittest.TestCase):
    def test_concurrent_collision_is_stable_after_reopen(self):
        candidate = page_id_store._candidate

        def collide(identity, attempt):
            return '0a000000' if attempt == 0 else candidate(identity, attempt)

        with TemporaryDirectory() as folder, patch.object(page_id_store, '_candidate', side_effect=collide):
            directory = Path(folder)
            with ThreadPoolExecutor(4) as workers:
                batches = list(workers.map(lambda keys: page_id_store.resolve(directory, keys),
                                           [('alpha', 'beta'), ('gamma',), ('delta', 'alpha'), ('beta',)]))
            all_ids = page_id_store.resolve(directory, ['alpha', 'beta', 'gamma', 'delta'])
            self.assertEqual(len(set(all_ids.values())), 4)
            for batch in batches:
                for key, value in batch.items():
                    self.assertRegex(value, r'^[0-9][a-z][a-z0-9]{6}$')
                    self.assertEqual(value, all_ids[key])
