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
