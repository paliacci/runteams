"""Assemble portable UI distribution from the single component source. No registry access."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_ui_tokens import render_foundation

checking = '--check' in sys.argv

def emit(path, data):
    if isinstance(data, str):
        data = data.encode()
    if checking:
        if not path.is_file() or path.read_bytes() != data:
            raise SystemExit('Generated UI artifact is stale: ' + str(path.relative_to(ROOT)))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

package = ROOT / 'sdk/ui'
spec = json.loads((ROOT / 'design/ui-tokens.json').read_text())
foundation = render_foundation(spec)
source_theme = ROOT / 'packages/ui-foundation/theme.css'
if source_theme.read_text() != foundation:
    raise SystemExit('Run python3 runteams_official/devtools/build_ui_tokens.py before building UI')
files = {'foundation/theme.css':source_theme}
for source in sorted((ROOT / 'packages/ui-components').rglob('*')):
    if source.is_file() and source.suffix in {'.js', '.css'}:
        files['components/' + source.relative_to(ROOT / 'packages/ui-components').as_posix()] = source
manifest = {'schemaVersion':1, 'version':json.loads((package/'package.json').read_text())['version'], 'canonicalTokens':'design/ui-tokens.json',
            'tokensSha256':hashlib.sha256((ROOT / 'design/ui-tokens.json').read_bytes()).hexdigest(), 'files':{}}
for name, source in files.items():
    data = source.read_bytes()
    target = package / 'dist' / name
    emit(target, data)
    manifest['files']['dist/' + name] = {'source':source.relative_to(ROOT).as_posix(), 'sha256':hashlib.sha256(data).hexdigest()}
emit(package/'build-manifest.json', json.dumps(manifest,indent=2)+'\n')


# The platform imports these same component bytes. Its token adapter references
# the existing global contract, so theme preferences stay device-owned.
web = ROOT / 'web/ui/kit'
for name, source in files.items():
    if not name.startswith('components/'):
        continue
    target = web / name
    emit(target, source.read_bytes())
aliases = '\n'.join(f'  --rt-{role.replace("/", "-")}: var(--{role.replace("/", "-")});' for role in spec['colors'])
sizes = '\n'.join(f'  --rt-{name}: {value}px;' for section in ('space','radius') for name,value in spec[section].items())
emit(web/'theme.css', '/* Generated from design/ui-tokens.json by sdk/ui/build.py. */\n[data-rt-ui] {\n'+aliases+'\n'+sizes+'\n  --rt-font: var(--ui);\n}\n')
emit(web/'index.js', "// Generated entry; shared source lives in packages/ui-components.\nimport * as components from './components/index.js';\nwindow.RunTeamsUIComponents = components;\nwindow.dispatchEvent(new Event('runteams-ui-ready'));\n")

print('Shared SDK and platform UI artifacts ' + ('verified' if checking else 'built'))
