"""Exercise the exit race without depending on the runner's scheduling or OS."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from runteams_core.authoring.workers import creator_worker_process
from runteams_core.authoring.compilation.creator_validation import validate_data
from runteams_core.authoring.creator_contracts import CreatorContractError


class WorkerMemoryTests(unittest.TestCase):
    def check_missing_sample(self, exit_before_sample):
        launch = creator_worker_process.start
        child = None
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        ready = Path(directory.name) / 'continue'

        def start(*args, **kwargs):
            nonlocal child
            child = launch(*args, **kwargs)
            return child

        def sample(_pid):
            if exit_before_sample:
                ready.touch()
                child.wait(timeout=2)
            raise StopIteration('no VmRSS')

        script = (
            'from pathlib import Path\nimport sys, time\n'
            'while not Path(sys.argv[1]).exists(): time.sleep(.01)\n'
            """print('{"valid":true}')"""
        )
        with patch.object(creator_worker_process, 'command',
                          return_value=[sys.executable, '-Ic', script, str(ready)]), \
             patch.object(creator_worker_process, 'start', side_effect=start), \
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
