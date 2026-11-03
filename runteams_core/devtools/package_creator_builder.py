"""Stage trusted build resources, outside any author source package."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.content_hashes import sha256 as sha
from runteams_core.creator_contracts import canonical
from runteams_core.creator_build_tools import load


def package(output, tools):
    output = Path(output).resolve()
    if output.exists(): raise ValueError('output_exists')
    output.mkdir(parents=True, mode=0o700)
    config = {'schema':'runteams.platform-builder/2', 'platform':'darwin-arm64'}
    for name in ('esbuild',):
        source = Path(tools[name])
        if source.is_symlink() or not source.is_file(): raise ValueError('invalid_tool')
        shutil.copy2(source, output / name)
        (output / name).chmod(0o755)
        config[name] = {'sha256':sha((output / name).read_bytes())}
    (output / 'toolchain.json').write_bytes(canonical(config))
    load(output)


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    for name in ('output','esbuild'):p.add_argument('--'+name,required=True)
    args=vars(p.parse_args());output=args.pop('output');package(output,args)
