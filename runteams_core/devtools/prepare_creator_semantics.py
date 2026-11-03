"""Stage a fixed managed Python validation closure, without install scripts."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import hashlib
import io
import importlib.util
import importlib._bootstrap_external
import sys
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

ROOT = source_root()
def platform_sources():
    """Select the actual canonical compiler dependency closure and its resources."""
    from .python_sources import closure
    seeds = (
        'runteams_core/authoring/creator_contracts.py',
        'runteams_core/authoring/creator_definitions.py',
        'runteams_core/authoring/creator_schema_validation.py',
        'runteams_core/authoring/compilation/creator_dependencies.py',
        'runteams_core/authoring/source/creator_source_archive.py',
        'runteams_core/agents/capability_runtime.py',
    )
    sources = {name:(ROOT/name).read_bytes() for name in closure(ROOT,seeds)}
    sources['VERSION'] = (ROOT/'VERSION').read_bytes()
    for path in (ROOT/'contracts/creator-system').rglob('*.json'):
        sources[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in ('product-model-v2.json','marketplace-pipeline-v2.json'):
        sources['contracts/'+name] = (ROOT/'contracts'/name).read_bytes()
    return sources


def prepare_semantics(stage, *, candidate):
    candidate = Path(candidate).resolve(strict=True)
    lock_file = candidate/'python-dependencies.lock.json'
    import httpx
    stage = Path(stage)
    lock = json.loads(lock_file.read_text())
    inventory = {}
    members = {}
    def add(name, body):
        path = PurePosixPath(name)
        if not name or path.is_absolute() or '..' in path.parts or '\\' in name or name in members:
            raise ValueError('Invalid dependency member')
        if len(body) > 8*1024*1024 or len(members) >= 5000:
            raise ValueError('Dependency budget exceeded')
        members[name] = body
    with httpx.Client(timeout=45) as client:
        for row in lock['packages']:
            response = client.get(row['url']); response.raise_for_status(); raw = response.content
            if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('Pinned dependency changed: ' + row['name'])
            inventory[row['name']] = {'version': row['version'], 'sha256': row['sha256']}
            if row['kind'] == 'pyodide-wheel':
                # The runtime lock provides the sole supported native Wasm
                # extension. loadPackage reads this local file, never a CDN.
                runtime = json.loads((stage/'_runtime/pyodide-lock.json').read_text())['packages'][row['name']]
                if runtime['file_name'] != row['filename'] or runtime['sha256'] != row['sha256']:
                    raise ValueError('Python ABI dependency mismatch')
                (stage/'_runtime'/row['filename']).write_bytes(raw)
            elif row['kind'] == 'pure-wheel':
                if not row['filename'].endswith('-py3-none-any.whl'):
                    raise ValueError('Expected pure Python wheel')
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    for info in archive.infolist():
                        if info.is_dir(): continue
                        if (info.external_attr >> 16) & 0o170000 == 0o120000 or info.file_size > 8*1024*1024:
                            raise ValueError('Invalid wheel member')
                        if info.filename.endswith(('.so','.pth')):
                            raise ValueError('Unsupported wheel code loader')
                        add(info.filename, archive.read(info))
            elif row['kind'] == 'yaml-source':
                # SafeLoader is pure Python in the canonical package too.
                # Retain its release source/license; never invoke setup.py.
                prefix = 'pyyaml-' + row['version'] + '/'
                with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
                    for info in archive:
                        if info.name == prefix[:-1] and info.isdir(): continue
                        relative = info.name.removeprefix(prefix)
                        if not info.name.startswith(prefix): raise ValueError('Unexpected source root')
                        if relative.startswith('lib/yaml/') and info.isfile() and relative.endswith('.py'):
                            add(relative[4:], archive.extractfile(info).read())
                        if relative == 'LICENSE': add('yaml/LICENSE', archive.extractfile(info).read())
            else: raise ValueError('Unsupported dependency type')
    if sum(map(len,members.values())) > 16*1024*1024: raise ValueError('Dependency closure too large')
    def bytecode(content, prefix, *, zip_import=False):
        # Only platform/locked third-party Python is compiled, never archive
        # input. CPython's hash-checked caches retain the original source and
        # reject mismatches. Patch releases with this exact magic share the
        # bytecode format; the runtime independently checks it before imports.
        if sys.implementation.name != 'cpython' or sys.version_info[:2] != (3,12):
            raise RuntimeError('Managed bytecode builder requires CPython 3.12')
        result = dict(content)
        for name, body in content.items():
            if not name.endswith('.py'): continue
            path = PurePosixPath(name)
            cache = str(path.with_suffix('.pyc') if zip_import else path.parent/'__pycache__'/(path.stem+'.'+sys.implementation.cache_tag+'.pyc'))
            code = compile(body, prefix+'/'+name, 'exec', dont_inherit=True, optimize=0)
            result[cache] = bytes(importlib._bootstrap_external._code_to_hash_pyc(
                code, importlib.util.source_hash(body), checked=True))
        return result
    def bundle(path, content, *, compress=False):
        with zipfile.ZipFile(path, 'w') as archive:
            for name, body in sorted(content.items()):
                info = zipfile.ZipInfo(name, (1980,1,1,0,0,0)); info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
                archive.writestr(info, body)
    with zipfile.ZipFile(stage/'_runtime/python_stdlib.zip') as archive:
        stdlib = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
    bundle(stage/'_canonical/python-stdlib.bytecode.zip', bytecode(stdlib, '/lib/python312.zip', zip_import=True), compress=True)
    bundle(stage/'_canonical/python-dependencies.zip', bytecode(members, '/python-dependencies.zip', zip_import=True))
    sources = platform_sources()
    payload = {name:body for name,body in sources.items() if not name.endswith('.py')}
    payload.update(bytecode(sources, '/platform'))
    bundle(stage/'_canonical/platform-semantics.zip', payload)
    bytecode_info = {'builder': sys.version, 'magic': importlib.util.MAGIC_NUMBER.hex(),
        'cache_tag': sys.implementation.cache_tag, 'invalidation': 'checked-hash',
        'stdlib_source_sha256': hashlib.sha256((stage/'_runtime/python_stdlib.zip').read_bytes()).hexdigest()}
    (stage/'_canonical/bytecode.json').write_text(json.dumps(bytecode_info)+'\n')
    for name in ('semantic-runtime.ts','semantic-entry.ts'):
        (stage/'shared'/name).write_bytes((candidate/name).read_bytes())
    (stage/'_canonical/semantic_phase.py').write_bytes((candidate/'semantic_phase.py').read_bytes())
    return {'bytecode': bytecode_info, 'lock_sha256': hashlib.sha256(lock_file.read_bytes()).hexdigest(), 'packages': inventory,
        'candidate_sha256':{name:hashlib.sha256((candidate/name).read_bytes()).hexdigest()
            for name in ('semantic-runtime.ts','semantic-entry.ts','semantic_phase.py')},
        'platform_sha256': {name:hashlib.sha256(body).hexdigest() for name,body in sources.items()},
        'artifacts':{name:hashlib.sha256((stage/'_canonical'/name).read_bytes()).hexdigest()
            for name in ('python-dependencies.zip','platform-semantics.zip','semantic_phase.py','bytecode.json','python-stdlib.bytecode.zip')}}
