"""Read and atomically replace the long digest-named records used by MCP calls."""
import os
from pathlib import Path
import tempfile
import threading
import unittest

from runteams_core.foundation.regular_files import storage_path
from runteams_core.storage.device_files import _publish, _read


class DeviceRecordTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing and MAX_PATH')
    def test_long_record_replaced_after_reader_releases_it(self):
        with tempfile.TemporaryDirectory(dir=storage_path(tempfile.gettempdir())) as directory:
            root = Path(tempfile.gettempdir()) / Path(directory).name
            target = root / ('a' * 64) / ('b' * 64) / ('c' * 64) / ('d' * 64 + '.json')
            storage_path(target.parent).mkdir(parents=True)
            _publish(root, target, b'{"state":"pending"}')
            self.assertEqual(_read(target)['state'], 'pending')
            # A regular Windows CRT reader disallows deletion until it closes.
            with storage_path(target).open('rb') as reader:
                release = threading.Timer(.15, reader.close)
                release.start()
                try:
                    _publish(root, target, b'{"state":"completed"}')
                finally:
                    release.join()
            self.assertEqual(_read(target)['state'], 'completed')
