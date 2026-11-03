"""Build one reproducible core wheel from its committed source checkout."""
from runteams_core.devtools.source_root import root as source_root
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = source_root()


def build(output):
    output = Path(output).absolute()
    if subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain']):
        raise ValueError('Commit source changes before building the locked core artifact.')
    epoch = subprocess.check_output(['git', '-C', str(ROOT), 'show', '-s', '--format=%ct', 'HEAD'], text=True).strip()
    environment = {**os.environ, 'SOURCE_DATE_EPOCH': epoch, 'PYTHONHASHSEED': '0'}
    subprocess.run([sys.executable, '-I', '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
                    str(ROOT), '--wheel-dir', str(output)], check=True, env=environment)
    return {'source_date_epoch': int(epoch), 'output': str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output)))


if __name__ == '__main__':
    main()
