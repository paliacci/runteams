"""Rebuild a wheel from the source distribution and compare it to the checkout build."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def verify(root, wheel, epoch):
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch), PYTHONHASHSEED='0')
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        subprocess.run([sys.executable, '-B', '-c',
                        'import sys; from setuptools.build_meta import build_sdist; build_sdist(sys.argv[1])',
                        directory], cwd=root, env=env, check=True)
        archive, = output.glob('*.tar.gz')
        with tarfile.open(archive) as source:
            for name in source.getnames():
                if {'node_modules', '__pycache__', '.build'} & set(Path(name).parts):
                    raise ValueError(f'Development files in source distribution: {name}')
        subprocess.run([sys.executable, '-I', '-m', 'pip', 'wheel', '--no-deps',
                        '--no-build-isolation', '--no-cache-dir', '--wheel-dir', directory,
                        archive], cwd=output, env=env, check=True)
        rebuilt = output / wheel.name
        if hashlib.sha256(wheel.read_bytes()).digest() != hashlib.sha256(rebuilt.read_bytes()).digest():
            raise ValueError(f'Source distribution produced a different wheel: {wheel.name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--wheel', required=True, type=Path)
    parser.add_argument('--epoch', required=True, type=int)
    args = parser.parse_args()
    verify(args.root.resolve(), args.wheel.resolve(), args.epoch)
