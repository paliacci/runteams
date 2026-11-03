"""Build an isolated, signed source checker; never installs or starts the app."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=source_root()


def package(output,identity=None):
    output=Path(output).absolute()
    if output.exists():raise ValueError('Output already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='runteams-source-checker-build-') as directory:
        work=Path(directory)
        subprocess.run([sys.executable,'-I','-m','PyInstaller','--noconfirm','--onedir','--name','runteams-source-checker',
            '--paths',str(ROOT),'--add-data',str(ROOT/'contracts')+':contracts',
            *(['--codesign-identity',identity] if identity else []),'--distpath',str(work/'dist'),'--workpath',str(work/'build'),
            '--specpath',str(work),str(ROOT/'runteams_core/devtools/creator_source_checker_entry.py')],check=True,cwd=ROOT)
        built=work/'dist/runteams-source-checker'
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(built/'runteams-source-checker')],check=True)
        # Move only after successful build/verification, retaining the sibling
        # _internal runtime which PyInstaller locates relative to the executable.
        import shutil
        shutil.copytree(built,output,symlinks=True)
    report={'schema':'runteams.source-checker-package/1-dev','frozen':True,
        'executable_sha256':hashlib.sha256((output/'runteams-source-checker').read_bytes()).hexdigest(),
        'files':sum(p.is_file() for p in output.rglob('*')),
        'bytes':sum(p.stat().st_size for p in output.rglob('*') if p.is_file())}
    (output/'package.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);parser.add_argument('--identity')
    args=parser.parse_args();print(json.dumps(package(args.output,args.identity),indent=2))
