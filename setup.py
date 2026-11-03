"""Standard wheel build; copy the canonical source assets into package data."""
from pathlib import Path
import hashlib
import json
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
DATA_DIRS = ('web', 'contracts', 'sdk', 'agent_skills', 'builtin_skills', 'frontend')
EXCLUDED = {'node_modules', '__pycache__', '.git', 'build', '.build'}


def resource_inputs():
    result = [ROOT / 'VERSION']
    for folder in DATA_DIRS:
        result.extend(p for p in (ROOT / folder).rglob('*')
                      if p.is_file() and not any(x in EXCLUDED or x.startswith('.') for x in p.relative_to(ROOT).parts))
    return sorted(set(result))


class Build(build_py):
    def run(self):
        from runteams_core.devtools.check_ui_boundary import check
        check(ROOT)
        build = Path(self.build_lib)
        if build.exists():
            shutil.rmtree(build)
        super().run()
        target = Path(self.build_lib) / 'runteams_core'
        assets = resource_inputs()
        code = list(ROOT.glob('*.py'))
        package_suffixes = {'.py', '.json', '.js', '.cjs', '.mjs', '.css', '.html', '.svg', '.sh', '.ts', '.md', '.txt'}
        for package in ('runteams_core', 'runteams_creator_dev'):
            code.extend(p for p in (ROOT / package).rglob('*')
                        if p.is_file() and p.suffix in package_suffixes
                        and p.name != 'package_identity.json' and '_resources' not in p.relative_to(ROOT).parts)
        for folder in ('desktop', 'tooling', '.github/workflows'):
            code.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and not any(x in EXCLUDED for x in p.relative_to(ROOT).parts))
        files = sorted(set(assets + code + [ROOT / name for name in ('pyproject.toml','requirements/runtime.txt','requirements/build.txt','README.md','LICENSE','docs/legal/LICENSING.md','docs/legal/THIRD_PARTY_DOCUMENTS.md','docs/legal/THIRD_PARTY_INVENTORY.json','CONTRIBUTING.md','SECURITY.md')]))
        hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
                  if not any(x in EXCLUDED for x in p.relative_to(ROOT).parts)}
        identity = {'schema': 'runteams.core-package/1', 'version': (ROOT / 'VERSION').read_text().strip(),
                    'source_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), 'inputs': hashes}
        (target / 'package_identity.json').write_text(json.dumps(identity, indent=2) + '\n')
        for source in assets:
            output = target / '_resources' / source.relative_to(ROOT)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, output)


setup(cmdclass={'build_py': Build})
