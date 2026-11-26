"""The same ownership contract runs against native processes on both platforms."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from runteams_core.foundation import process_tree


class ProcessTreeTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows process working directories')
    def test_deep_working_directory_without_short_names_preserves_edits_on_failure(self):
        import os
        from unittest.mock import patch
        from runteams_core.foundation.regular_files import storage_path
        from runteams_core.foundation.windows_working_directory import working_directory

        with tempfile.TemporaryDirectory(dir=storage_path(tempfile.gettempdir())) as temporary:
            deep = Path(temporary) / ('项目' * 34) / ('资料' * 34) / ('目录' * 34) / ('源码' * 34)
            deep.mkdir(parents=True)
            with patch('_winapi.GetShortPathName', side_effect=OSError('unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    with working_directory(deep) as alias:
                        self.assertTrue(os.path.samefile(alias, deep))
                        process_tree.run([sys.executable, '-c',
                                          'from pathlib import Path; Path("source.txt").write_bytes(b"edited")'],
                                         cwd=alias, timeout=10).check_returncode()
                        raise RuntimeError('interrupted')
            self.assertFalse(os.path.lexists(alias))
            self.assertEqual((deep/'source.txt').read_bytes(), b'edited')

    def start_family(self, leader_exits):
        # The grandchild holds stdout open and ignores a graceful POSIX stop.
        # EOF proves it exited even when the leader was already reaped.
        child = (
            'import pathlib, signal, sys, time; '
            'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
            'pathlib.Path(sys.argv[1]).touch(); time.sleep(15)'
        )
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        ready = Path(directory.name, 'child-ready')
        parent = (
            'import subprocess, sys, time; '
            'subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]]); '
            + ('sys.exit(0)' if leader_exits else 'time.sleep(15)')
        )
        process = process_tree.start([sys.executable, '-c', parent, child, str(ready)],
                                     stdout=subprocess.PIPE)
        self.addCleanup(process.stdout.close)
        self.addCleanup(process_tree.stop, process, grace=0)
        deadline = time.monotonic() + 5
        while not ready.exists():
            self.assertLess(time.monotonic(), deadline, 'child did not start')
            time.sleep(.01)
        return process

    def test_stop_after_leader_exit_releases_descendant_pipe(self):
        process = self.start_family(leader_exits=True)
        self.assertEqual(process.wait(timeout=3), 0)
        process_tree.stop(process)
        self.assertEqual(process.communicate(timeout=3)[0], b'')
        self.assertEqual(process.returncode, 0)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Job Object limits')
    def test_process_ceiling_applies_before_leader_can_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'started'
            grandchild = 'import pathlib, sys; pathlib.Path(sys.argv[1]).touch()'
            parent = (
                'import subprocess, sys\n'
                'try: subprocess.run([sys.executable, "-c", *sys.argv[1:]], timeout=5)\n'
                'except OSError: pass'
            )
            # A Windows venv's python.exe is a redirector that starts another
            # process. Exercise the real interpreter inside the one-process job.
            result = process_tree.run([sys._base_executable, '-c', parent, grandchild, str(marker)],
                                      windows_limits={'processes': 1}, timeout=8)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_concurrent_cancellation_leaves_another_job_running(self):
        other = self.start_family(leader_exits=False)
        process = self.start_family(leader_exits=False)
        with ThreadPoolExecutor(max_workers=2) as pool:
            stops = [pool.submit(process_tree.stop, process, grace=0) for _ in range(2)]
            for stop in stops:
                stop.result(timeout=5)
        self.assertEqual(process.communicate(timeout=3)[0], b'')
        self.assertIsNone(other.poll())

    def test_probe_preserves_output_exit_code_and_timeout(self):
        code = 'import sys; print("out"); print("err", file=sys.stderr); sys.exit(7)'
        result = process_tree.run([sys.executable, '-c', code], timeout=3,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual((result.stdout, result.stderr, result.returncode), ('out\n', 'err\n', 7))
        with self.assertRaises(subprocess.TimeoutExpired):
            process_tree.run([sys.executable, '-c', 'import time; time.sleep(15)'], timeout=.1)

    def test_probe_leaves_owner_input_for_the_service(self):
        owner = (
            'import subprocess, sys\n'
            'from runteams_core.foundation import process_tree\n'
            'probe = "import sys; print(repr(sys.stdin.buffer.read()))"\n'
            'result = process_tree.run([sys.executable, "-c", probe], timeout=5, stdout=subprocess.PIPE)\n'
            'print(result.stdout.decode().strip())\n'
            'print(repr(sys.stdin.buffer.read()))\n'
        )
        result = subprocess.run([sys.executable, '-c', owner], input=b'owner', stdout=subprocess.PIPE,
                                check=True, timeout=10)
        self.assertEqual(result.stdout.splitlines(), [b"b''", b"b'owner'"])
