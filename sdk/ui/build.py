"""Build the portable SDK UI from the shared platform components. No network access."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
checking = '--check' in sys.argv

def emit(path, data):
    if checking:
        if not path.is_file() or path.read_bytes() != data:
            raise SystemExit('Generated UI artifact is stale: ' + str(path.relative_to(ROOT)))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

package = ROOT / 'sdk/ui'
components = ROOT / 'web/ui/kit/components'
foundation = package / 'foundation/theme.css'
files = {'foundation/theme.css': foundation}
for source in sorted(components.rglob('*')):
    if source.is_file() and source.suffix in {'.js', '.css'}:
        files['components/' + source.relative_to(components).as_posix()] = source
manifest = {
    'schemaVersion': 1,
    'version': json.loads((package / 'package.json').read_text())['version'],
    'canonicalComponents': components.relative_to(ROOT).as_posix(),
    'canonicalFoundation': foundation.relative_to(ROOT).as_posix(),
    'files': {},
}
for name, source in files.items():
    data = source.read_bytes()
    emit(package / 'dist' / name, data)
    manifest['files']['dist/' + name] = {
        'source': source.relative_to(ROOT).as_posix(),
        'sha256': hashlib.sha256(data).hexdigest(),
    }
emit(package / 'build-manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
print('Shared SDK UI artifacts ' + ('verified' if checking else 'built'))
