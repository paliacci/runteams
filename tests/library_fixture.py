"""Disposable library whose teardown can traverse deep content-addressed trees."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile

from runteams_core.foundation.regular_files import storage_path


@contextmanager
def temporary_library():
    parent = Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(dir=storage_path(parent)) as directory:
        # Give the app an ordinary user path. Only cleanup uses the extended path.
        yield str(parent / Path(directory).name)


def assert_private_vault(test, path):
    if os.name != 'nt':
        test.assertEqual(path.stat().st_mode & 0o777, 0o600)
        return
    # Query the actual on-disk access rules independently of the writer.
    result = subprocess.check_output(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         "[IO.File]::GetAccessControl($env:TEST_VAULT_PATH).GetSecurityDescriptorSddlForm('Access')"],
        env={**os.environ, 'TEST_VAULT_PATH': str(path)}, text=True)
    test.assertEqual(result.strip(), 'D:P(A;;FA;;;OW)')
