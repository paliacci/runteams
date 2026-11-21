"""Compress immutable runtime files on macOS without changing their contents."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def compact(directory):
    # ditto also preserves executable modes, signatures and extended attributes.
    # PostgreSQL data and credentials are outside the selected directories.
    with TemporaryDirectory(dir=directory.parent) as temporary:
        copy = Path(temporary) / 'copy'
        subprocess.run(['/usr/bin/ditto', '--noclone', '--hfsCompression',
                        directory, copy], check=True)
        for candidate in copy.rglob('*'):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            original = directory / candidate.relative_to(copy)
            if candidate.stat().st_blocks < original.stat().st_blocks:
                os.replace(candidate, original)


if __name__ == '__main__':
    for argument in sys.argv[1:]:
        compact(Path(argument))
