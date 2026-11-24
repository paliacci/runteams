"""Exercise the exit race without depending on the runner's scheduling or OS."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from runteams_core.authoring.compilation.creator_validation import validate_schemas
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
            raise StopIteration('no VmRSS')

        script = f"import os; os.read({reader}, 1); print('{{\"valid\":true}}')"
        with patch('runteams_core.authoring.workers.creator_worker_process.command',
                   return_value=[sys.executable, '-Ic', script]), \
             patch('subprocess.Popen', side_effect=start), \
             patch('runteams_core.authoring.creator_process_memory.process_rss', side_effect=sample) as measured:
            try:
                validate_schemas([])
            finally:
                measured.assert_called()
                self.assertIsNotNone(child.returncode)

    def test_completed_worker_result_survives_missing_sample(self):
        self.check_missing_sample(True)

    def test_live_worker_without_memory_measurement_fails(self):
        with self.assertRaises(CreatorContractError):
            self.check_missing_sample(False)
