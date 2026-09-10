# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import tempfile
import unittest

import execution_backend


@unittest.skipUnless(os.name == "posix", "POSIX resource limits")
class ExecutionBackendTests(unittest.TestCase):
    def test_v3_launcher_enforces_file_size_limit(self):
        with tempfile.TemporaryDirectory(prefix="runteams-limits-") as root:
            target = os.path.join(root, "large.bin")
            limits = {"memory_mb": 1024, "cpu_seconds": 30, "processes": 4,
                      "file_size_mb": 1, "open_files": 64}
            command = [sys.executable,
                       os.path.join(os.path.dirname(execution_backend.__file__),
                                    "capability_launcher.py"),
                       execution_backend._encoded_limits(limits), "--",
                       "/bin/dd", "if=/dev/zero", "of=" + target,
                       "bs=1048576", "count=2"]
            completed = subprocess.run(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, timeout=10)
            self.assertNotEqual(completed.returncode, 0)
            self.assertTrue(os.path.exists(target))
            self.assertLessEqual(os.path.getsize(target), 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
