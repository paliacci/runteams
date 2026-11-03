"""Exact vendored byte closure shared by preflight and trusted compilation."""
import hashlib

from runteams_core.authoring.creator_contracts import CreatorContractError, digest, relative, strict_json


def validate_dependency_sources(files, compiled, *, source_index=None):
    # Optional internal fast path: index must come from byte-verified canonical
    # archive inspection (or an authenticated phase over the exact same bytes).
    # Never accept a caller-supplied inventory as validation evidence.
    dependencies = compiled['dependencies']['dependencies']
    sources = {}
    if dependencies:
        if 'dependencies.sources.json' not in files:
            raise CreatorContractError('dependency_sources_required')
        sources = strict_json(files['dependencies.sources.json'])
        if not isinstance(sources, dict) or set(sources) != {d['key'] for d in dependencies}:
            raise CreatorContractError('dependency_closure')
    prefixes = []
    for dep in dependencies:
        prefix = relative(sources[dep['key']]) + '/'
        if any(prefix.startswith(p) or p.startswith(prefix) for p in prefixes):
            raise CreatorContractError('dependency_closure')
        prefixes.append(prefix)
        if source_index is None:
            entries = [{'path': p[len(prefix):], 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
                for p, b in sorted(files.items()) if p.startswith(prefix)]
        else:
            entries = [{**row, 'path': row['path'][len(prefix):]}
                for row in source_index['files'] if row['path'].startswith(prefix)]
        if not entries or digest(entries) != dep['sha256']:
            raise CreatorContractError('dependency_integrity')
        if prefix + 'package.json' in files:
            metadata = strict_json(files[prefix + 'package.json'])
            if not isinstance(metadata, dict) or metadata.get('name') != dep['key'] or metadata.get('version') != dep['version']:
                raise CreatorContractError('dependency_identity')
    return sources
