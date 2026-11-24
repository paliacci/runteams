"""Cross-process checks for the lock files used by authoring and local builds."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from runteams_core.foundation.file_locks import acquire


class FileLockTests(unittest.TestCase):
    def test_empty_lock_contention_wait_and_release_after_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.lock'
            path.touch()
            ready = Path(directory) / 'ready'
            owner_code = (
                'from runteams_core.foundation.file_locks import acquire\n'
                'from pathlib import Path\n'
                'import sys, time\n'
                'fd = acquire(sys.argv[1])\n'
                'Path(sys.argv[2]).touch()\n'
                'time.sleep(15)\n'
            )
            contender_code = (
                'from runteams_core.foundation.file_locks import acquire\n'
                'import os, sys\n'
                'os.close(acquire(sys.argv[1]))\n'
            )
            owner = subprocess.Popen([sys.executable, '-c', owner_code, str(path), str(ready)])
            try:
                deadline = time.monotonic() + 5
                while not ready.exists():
                    self.assertIsNone(owner.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
                with self.assertRaises(BlockingIOError):
                    acquire(path, blocking=False)
                with subprocess.Popen([sys.executable, '-c', contender_code, str(path)]) as waiter:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        waiter.wait(timeout=.2)
                    owner.kill()
                    owner.wait(timeout=3)
                    self.assertEqual(waiter.wait(timeout=3), 0)
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.wait(timeout=3)
            os.close(acquire(path, blocking=False))
            self.assertEqual(path.read_bytes(), b'')

    def test_readers_share_existing_record_and_exclude_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '旧资料.lock'
            with self.assertRaises(FileNotFoundError):
                acquire(path, readonly=True)
            path.write_text('legacy', encoding='utf-8')
            reader = acquire(path, readonly=True)
            try:
                os.close(acquire(path, readonly=True, blocking=False))
                with self.assertRaises(BlockingIOError):
                    acquire(path, blocking=False)
                self.assertEqual(path.read_text(encoding='utf-8'), 'legacy')
            finally:
                os.close(reader)
            os.close(acquire(path, blocking=False))

    def test_reject_hard_link(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data'
            path.write_bytes(b'original')
            link = Path(directory) / 'lock'
            os.link(path, link)
            with self.assertRaises(ValueError):
                acquire(link, blocking=False)
            self.assertEqual(path.read_bytes(), b'original')
