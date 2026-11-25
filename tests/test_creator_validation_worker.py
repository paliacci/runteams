"""Exercise the exit race without depending on the runner's scheduling or OS."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from runteams_core.authoring.creator_process_memory import process_rss
from runteams_core.authoring.compilation.creator_validation import validate_data
from runteams_core.authoring.creator_contracts import CreatorContractError


class WorkerMemoryTests(unittest.TestCase):
    def check_missing_sample(self, exit_before_sample):
        spawn = subprocess.Popen
        child = None
        reader, writer = os.pipe()
        self.addCleanup(os.close, reader)
        self.addCleanup(os.close, writer)

        def start(*args, **kwargs):
            nonlocal child
            child = spawn(*args, pass_fds=(reader,), **kwargs)
            return child

        def sample(_pid):
            if exit_before_sample:
                os.write(writer, b'1')
                child.wait(timeout=2)
                return 0
            raise PermissionError('unreadable memory sample')

        script = f"import os; os.read({reader}, 1); print('{{\"valid\":true}}')"
        with patch('runteams_core.authoring.workers.creator_worker_process.command',
                   return_value=[sys.executable, '-Ic', script]), \
             patch('subprocess.Popen', side_effect=start), \
             patch('runteams_core.authoring.creator_process_memory.process_rss', side_effect=sample) as measured:
            try:
                validate_data({'type': 'string'}, 'sample')
            finally:
                measured.assert_called()
                self.assertIsNotNone(child.returncode)

    def test_completed_worker_result_survives_missing_sample(self):
        self.check_missing_sample(True)

    def test_live_worker_without_memory_measurement_fails(self):
        with self.assertRaises(CreatorContractError):
            self.check_missing_sample(False)

    @unittest.skipUnless(sys.platform == 'linux', 'requires Linux procfs')
    def test_resident_pages_of_live_exited_and_reaped_children(self):
        with subprocess.Popen([sys.executable, '-Ic', 'import sys; print("ready", flush=True); sys.stdin.read(1)'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as child:
            self.assertEqual(child.stdout.readline(), b'ready\n')
            self.assertGreater(process_rss(child.pid), 0)
            child.stdin.close()
            os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
            self.assertEqual(process_rss(child.pid), 0)
            self.assertEqual(child.wait(), 0)
            self.assertEqual(process_rss(child.pid), 0)
