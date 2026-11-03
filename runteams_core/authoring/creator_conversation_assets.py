"""Complete local conversation assets; skills and formal work are optional.

These snapshots are local runtime inputs. Product publication continues to use
creator_definitions and its formal work contracts, never this local artifact.
"""
from runteams_core.assets.skills import skill_packages as _skill_packages
import base64
import copy
import hashlib
import threading
from collections import OrderedDict
from pathlib import Path,PurePosixPath
import tempfile

from runteams_core.authoring.creator_contracts import canonical, CreatorContractError
from runteams_core.foundation.contracts import ContractError
from runteams_core.authoring.definition_contracts import validate_definition
from runteams_core.authoring.compilation.creator_mcp_source import definition_files
from runteams_core.assets.skills.skill_metadata import frontmatter as _frontmatter
from runteams_core.assets.skills.skill_metadata import extension as _extension

SCHEMA='runteams.conversation-employee/v1'
CATALOG='runteams.creator-conversation-definitions/1'


# Positive proofs for immutable author metadata only. Live configuration,
# scope, work/program state, grants and rental rights are checked by callers.
# Keep no caller objects: editing even one declaration field changes its key.
_metadata=OrderedDict();_metadata_lock=threading.RLock()
_METADATA_ENTRIES=64;_METADATA_BYTES=4*1024*1024


def _checked_employee_metadata(value):
    try:raw=canonical(value)
    except (TypeError,ValueError,RecursionError):raw=None
    key=hashlib.sha256(raw).digest() if raw is not None else None
    with _metadata_lock:
        if key is not None and key in _metadata:
            _metadata.move_to_end(key);return
    from runteams_core.authoring.creator_definitions import validate_author
    validate_author('employee',value)
    if raw is not None and len(raw)<=_METADATA_BYTES:
        with _metadata_lock:
            _metadata[key]=len(raw);_metadata.move_to_end(key)
            while len(_metadata)>_METADATA_ENTRIES or sum(_metadata.values())>_METADATA_BYTES:
                _metadata.popitem(last=False)


# Only immutable parsed author declarations, keyed by the complete bundle's
# canonical content hash. No scope, configuration, program enablement, grant,
# lease or result is memoized. Return a copy so callers cannot poison the cache.
_extensions=OrderedDict();_extensions_lock=threading.RLock()
def extension(bundle):
    try:key=hashlib.sha256(canonical(bundle)).digest()
    except (TypeError,ValueError,RecursionError):key=None
    with _extensions_lock:
        cached=_extensions.get(key) if key is not None else None
        if cached is not None:
            _extensions.move_to_end(key);return copy.deepcopy(cached[1])
    value=validate_definition('portable_skill_bundle',bundle)
    files={f['path']:base64.b64decode(f['content_base64'],validate=True) for f in value['files']}
    result=_extension(files,_frontmatter(files['SKILL.md'].decode('utf-8')))
    if key is not None:
        with _extensions_lock:
            _extensions[key]=(len(canonical(result)),copy.deepcopy(result));_extensions.move_to_end(key)
            while len(_extensions)>64 or sum(row[0] for row in _extensions.values())>4*1024*1024:_extensions.popitem(last=False)
    return result


def validate_asset(asset):
    if not isinstance(asset,dict) or set(asset) not in ({'schema','employee','skill_bundles'}, {'schema','employee','skill_bundles','avatar_file'}) or asset['schema']!=SCHEMA:
        raise ContractError('员工对话运行包无效。')
    employee=asset['employee']
    if not isinstance(employee,dict) or set(employee) not in (
            {'name','avatar','soul','runtime_requirement'},
            {'name','avatar','soul','runtime_requirement','configuration'}):
        raise ContractError('员工对话身份无效。')
    # Reuse the canonical author metadata schema without manufacturing skills,
    # work declarations, employee IDs or a product publication receipt.
    _checked_employee_metadata({'schema':'runteams.employee-source/3','key':'runtime',
        'name':employee['name'],'avatar':employee['avatar'],'soul_file':'soul.md','skill_dirs':[],
        'runtime_requirement':employee['runtime_requirement'],
        **({'configuration':employee['configuration']} if 'configuration' in employee else {})})
    if not isinstance(employee['soul'],str) or not isinstance(asset['skill_bundles'],list):
        raise ContractError('员工对话资源无效。')
    from runteams_core.employees.employee_avatars import bundled, verify_attachment
    if bundled(employee['avatar']):
        verify_attachment(employee['avatar'], asset.get('avatar_file'))
    elif 'avatar_file' in asset:
        raise ContractError('员工头像附件与配置不一致。')
    keys=set()
    for bundle in asset['skill_bundles']:
        extension(bundle)
        if bundle['package_key'] in keys:raise ContractError('员工技能重复。')
        keys.add(bundle['package_key'])
    return asset


def compile_catalog(files,compiled):
    # Validate program attachments using the original deterministic packer.
    from runteams_core.authoring.compilation.creator_mcp_source import pipeline_programs
    programs=pipeline_programs(files,compiled)
    files=definition_files(files,compiled);employees={}
    with tempfile.TemporaryDirectory(prefix='runteams-conversation-assets-') as directory:
        for path,source in compiled['employees'].items():
            bundles=[];keys=set()
            for declared in source['skill_dirs']:
                key=PurePosixPath(declared).name
                if key in keys:raise CreatorContractError('duplicate_skill_key')
                keys.add(key);prefix=declared+'/'
                values={p[len(prefix):]:body for p,body in files.items() if p.startswith(prefix)}
                root=Path(directory)/'skills'/source['key']/key;root.mkdir(parents=True)
                for relative,body in values.items():
                    target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
                prepared=_skill_packages.prepare(root)
                bundles.append({'package_key':key,'digest':prepared['digest'],'files':[
                    {'path':relative,'size':len(body),'sha256':hashlib.sha256(body).hexdigest(),
                     'content_base64':base64.b64encode(body).decode('ascii')} for relative,body in sorted(values.items())]})
            try:soul=files[source['soul_file']].decode('utf-8')
            except UnicodeError:raise CreatorContractError('invalid_employee_soul') from None
            from runteams_core.employees.employee_avatars import attachment
            picture = attachment(source['avatar'], files)
            employees[path]=validate_asset({'schema':SCHEMA,**({'avatar_file':picture} if picture else {}),'employee':{
                **{key:copy.deepcopy(source[key]) for key in ('name','avatar','runtime_requirement')},'soul':soul,
                **({'configuration':copy.deepcopy(source['configuration'])} if 'configuration' in source else {})},
                'skill_bundles':bundles})
    pipelines = {path: {**copy.deepcopy(source), 'schema':'runteams.conversation-pipeline/v1'}
                 for path, source in compiled['pipelines'].items()}
    return {'schema':CATALOG,'source_sha256':compiled['source']['sha256'],'employees':employees,'pipelines':pipelines,
        **({'pipeline_programs':programs} if programs else {})}


def artifacts(files,compiled):
    # A pipeline references the same employee packages. Adding one must never
    # switch ordinary employees into the separate publication asset format.
    from runteams_core.authoring.creator_definitions import CATALOG_PATH
    return {CATALOG_PATH:canonical(compile_catalog(files,compiled))}
