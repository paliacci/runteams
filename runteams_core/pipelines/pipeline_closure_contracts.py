"""Pure byte/lineage checks for a portable employee dependency closure.

No source acquisition, author authorization, publication send or runtime choice.
"""
import copy
import re
from pathlib import PurePosixPath
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, digest, relative, strict_json, tree


MANIFEST = 'pipeline-dependencies.json'


PREFIX = 'pipeline-dependencies/'


SCHEMA = 'runteams.pipeline-publication-closure/1'


def _fail(code='pipeline_closure_integrity', message=None):
    raise CreatorContractError(code, message)


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def portable_employee(files, compiled, path):
    """The original complete employee compiler, isolated from other pipelines."""
    from runteams_core.authoring.creator_conversation_assets import compile_catalog
    from runteams_core.employees.portable_employee import verify
    one = {**compiled, 'employees': {path: compiled['employees'][path]}, 'pipelines': {}}
    asset = compile_catalog(files, one)['employees'][path]
    definition = {**asset['employee'], 'skill_refs': [
        {'package_key': b['package_key'], 'digest': b['digest']} for b in asset['skill_bundles']]}
    return verify({'schema': 'runteams.marketplace-employee/v2', 'employee': definition,
                   'skill_bundles': asset['skill_bundles']})


def _origin(value):
    if not isinstance(value, dict): _fail()
    common = {'kind', 'employee_source', 'source_sha256'}
    if value.get('kind') == 'source':
        if set(value) != common | {'source_id', 'revision'} or not _sha(value['source_id']): _fail()
        if not isinstance(value['revision'], str) or not re.fullmatch('(r-)?[a-f0-9]{64}', value['revision']): _fail()
    elif value.get('kind') == 'author-release':
        from runteams_core.foundation.identity.resource_ids import resource_id
        if set(value) != common | {'project_id', 'release_id', 'sha256'} or not _sha(value['sha256']): _fail()
        resource_id(value['project_id']); resource_id(value['release_id'])
    else:
        _fail('pipeline_dependency_not_owned', '租用使用权不能作为随作品发布或转授权的依据。')
    relative(value['employee_source'])
    if not _sha(value['source_sha256']): _fail()
    return value


def verify(files, compiled):
    """Pure closed-tree verification; no machine, catalog or account fallback."""
    generated = {p for p in files if p.startswith(PREFIX)}
    if MANIFEST not in files:
        if generated: _fail('pipeline_closure_missing')
        return None
    manifest = strict_json(files[MANIFEST])
    if (not isinstance(manifest, dict) or set(manifest) != {'schema', 'draft_source_sha256', 'employees'}
            or manifest['schema'] != SCHEMA or not _sha(manifest['draft_source_sha256'])
            or not isinstance(manifest['employees'], dict) or not 0 < len(manifest['employees']) <= 64): _fail()
    if any('dependency' in m for p in compiled['pipelines'].values() for m in p['employees']): _fail('pipeline_closure_incomplete')
    expected_files = set()
    for path, record in manifest['employees'].items():
        relative(path)
        if (not isinstance(record, dict) or set(record) != {'pipeline_source', 'employee_ref', 'pin_sha256', 'origin', 'files_sha256', 'asset_sha256'}
                or any(not _sha(record[k]) for k in ('pin_sha256', 'files_sha256', 'asset_sha256'))): _fail()
        _origin(record['origin'])
        prefix = str(PurePosixPath(path).parent) + '/'
        if not re.fullmatch('pipeline-dependencies/[a-f0-9]{64}/employee.json', path): _fail()
        employee = compiled['employees'].get(path)
        if (employee is None or employee['key'] != 'dep-' + prefix.split('/')[1]
                or employee['soul_file'] != prefix + 'soul.md'
                or any(not d.startswith(prefix + 'skills/') or len(PurePosixPath(d).parts) != 4 for d in employee['skill_dirs'])): _fail()
        asset = compiled['pipelines'].get(record['pipeline_source'])
        member = next((m for m in (asset or {}).get('employees', []) if m['ref'] == record['employee_ref']), None)
        if member is None or member.get('source') != path: _fail('pipeline_closure_binding_changed')
        values = {p: b for p, b in files.items() if p.startswith(prefix)}
        allowed = {path, employee['soul_file']} | {p for p in values if any(p.startswith(d + '/') for d in employee['skill_dirs'])}
        if set(values) != allowed or tree(values)['sha256'] != record['files_sha256']: _fail()
        if digest(portable_employee(files, compiled, path)) != record['asset_sha256']: _fail('pipeline_closure_employee_changed')
        expected_files.update(values)
    if generated != expected_files or {p for p in compiled['employees'] if p.startswith(PREFIX)} != set(manifest['employees']): _fail()
    return manifest


def verify_prepared(original, files, compiled):
    """Bind the closed tree to the exact saved draft, without resolving again."""
    manifest = verify(files, compiled)
    if manifest is None or manifest['draft_source_sha256'] != tree(original)['sha256']: _fail('pipeline_closure_draft_changed')
    project = strict_json(original['project.json'])
    expected = dict(original)
    expected_project = copy.deepcopy(project)
    expected_project['entrypoints']['employees'] += sorted(manifest['employees'])
    expected['project.json'] = canonical(expected_project)
    remaining = set(manifest['employees'])
    for path in project['entrypoints'].get('pipelines', []):
        pipeline = strict_json(original[path]); changed = False
        for member in pipeline['employees']:
            if 'dependency' not in member: continue
            matches = [(p, record) for p, record in manifest['employees'].items()
                       if record['pipeline_source'] == path and record['employee_ref'] == member['ref']]
            if len(matches) != 1 or digest(member['dependency']) != matches[0][1]['pin_sha256']: _fail()
            destination, record = matches[0]
            pin = member.pop('dependency'); member['source'] = destination; changed = True; remaining.remove(destination)
            if record['origin']['kind'] == 'source' and pin['kind'] == 'download': _fail('pipeline_dependency_authority_changed')
        if changed: expected[path] = canonical(pipeline)
    if remaining: _fail('pipeline_closure_unbound_employee')
    actual_root = {p: b for p, b in files.items() if p != MANIFEST and not p.startswith(PREFIX)}
    if actual_root != expected: _fail('pipeline_closure_root_changed')
    return manifest


def check_original(files, origin, expected_asset):
    from runteams_core.authoring.creator_contracts import compile_source
    if tree(files)['sha256'] != origin['source_sha256']: _fail('pipeline_dependency_source_changed')
    compiled = compile_source(files)
    if origin['employee_source'] not in compiled['employees'] or digest(portable_employee(files, compiled, origin['employee_source'])) != expected_asset:
        _fail('pipeline_dependency_version_changed')
