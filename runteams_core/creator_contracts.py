from runteams_core.resources import root as resource_root
"""Portable creator sources; no credentials, local business store or lab imports."""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata

from .contracts import ContractError

ROOT = resource_root() / 'contracts/creator-system'
MAX_FILES = 500
MAX_BYTES = 32 * 1024 * 1024
KEY = re.compile(r'^[a-z][a-z0-9_.-]{0,79}$')


class CreatorContractError(ContractError):
    def __init__(self, code, details=None):
        self.code = code
        self.details = details
        super().__init__('作品无法通过检查：' + details if details else '作品无法通过检查，请查看具体问题后修改。')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CreatorContractError('duplicate_json_key')
            result[key] = value
        return result
    def invalid(_value):
        raise CreatorContractError('invalid_json_number')
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise CreatorContractError('invalid_json_number')
        return number
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite)
    except (ValueError, UnicodeError, RecursionError):
        raise CreatorContractError('invalid_json') from None


def relative(path):
    if (not isinstance(path, str) or not path or len(path) > 240
            or unicodedata.normalize('NFC', path) != path
            or any(p in ('', '.', '..') for p in path.split('/'))
            or re.search(r'[\\\x00-\x1f\x7f:%?#]', path)):
        raise CreatorContractError('invalid_path')
    return path


def contract(name, value, profile='v1'):
    # Byte/tree inspection is also used in the bounded managed archive phase.
    # Load schema machinery only when actually validating a schema contract.
    from jsonschema import Draft202012Validator
    if name in ('project.schema.json','release.schema.json','dependencies.schema.json'):
        profile='mcp-v1'
    schema = strict_json((ROOT / profile / name).read_bytes())
    if next(Draft202012Validator(schema).iter_errors(value), None) is not None:
        raise CreatorContractError('invalid_' + name.split('.')[0])
    return value


def source_files(value):
    """Check complete byte inventory, including hidden files and binary assets."""
    if not isinstance(value, dict) or not value or len(value) > MAX_FILES:
        raise CreatorContractError('asset_limit')
    result, seen, total = {}, set(), 0
    for path, body in sorted(value.items()):
        relative(path)
        if path.casefold() in seen:
            raise CreatorContractError('path_collision')
        seen.add(path.casefold())
        if any(p.casefold() in ('.env', 'auth.json', 'token.json', '.git', 'node_modules')
               for p in path.split('/')):
            raise CreatorContractError('forbidden_asset')
        if not isinstance(body, bytes):
            raise CreatorContractError('invalid_asset')
        total += len(body)
        if total > MAX_BYTES:
            raise CreatorContractError('asset_limit')
        # This rejects recognized secrets, not a claim of exhaustive detection.
        # Both alternatives require one of these literal prefixes. The native
        # byte search avoids running the regex engine over large binary assets
        # with no possible match; the exact recognition rule stays unchanged.
        if ((b'-----BEGIN ' in body or b'ya29.' in body) and
                re.search(rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|ya29\.[A-Za-z0-9_-]{12,}', body)):
            raise CreatorContractError('credential_in_source')
        result[path] = body
    return result


def read_folder(folder):
    root = Path(folder)
    if root.is_symlink() or not root.is_dir():
        raise CreatorContractError('invalid_root')
    files,total = {},0
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise CreatorContractError('invalid_path')
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode) or path.stat().st_nlink != 1:
            raise CreatorContractError('invalid_path')
        if len(files) >= MAX_FILES or path.stat().st_size > MAX_BYTES-total:
            raise CreatorContractError('asset_limit')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
                raise CreatorContractError('invalid_path')
            body=stream.read(MAX_BYTES-total+1)
        total+=len(body)
        if total>MAX_BYTES:raise CreatorContractError('asset_limit')
        files[path.relative_to(root).as_posix()] = body
    return source_files(files)


def encode_files(files):
    return {p: base64.b64encode(b).decode('ascii') for p, b in source_files(files).items()}


def decode_files(value):
    if not isinstance(value, dict) or len(value) > MAX_FILES:
        raise CreatorContractError('asset_limit')
    files = {}
    for path, encoded in value.items():
        relative(path)
        try:
            files[path] = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise CreatorContractError('invalid_base64',
                path + ' 的文件内容不是有效的 base64；请从原文件字节重新编码。') from None
    return source_files(files)


def tree(files):
    return _source_tree(source_files(files))


def _source_tree(files, *, hash_bytes=None):
    """Internal index of an already validated, sorted byte map."""
    hash_bytes = hash_bytes or (lambda body: hashlib.sha256(body).hexdigest())
    entries = [{'path': p, 'size': len(b), 'sha256': hash_bytes(b)}
               for p, b in files.items()]
    return {'schema': 'runteams.source-tree/1', 'files': entries, 'sha256': digest(entries)}


def compile_source(files, *, schema_validator=None):
    """Compile derived indexes. The complete original folder stays authoritative."""
    return _compile_checked_source(source_files(files), schema_validator=schema_validator)


def _compile_checked_source(files, *, schema_validator=None, source_index=None):
    """Internal worker path: files/index must come from canonical byte validation.

    Reusing its index avoids scanning all large binary assets a second time.
    Never call this with caller-provided indexes or bypassed source validation.
    """
    def asset(path):
        if relative(path) not in files:
            raise CreatorContractError('missing_asset', '缺少作品文件：' + path)
        return path
    def read(path):
        return strict_json(files[asset(path)])
    project = contract('project.schema.json', read('project.json'))
    if project['schema']=='runteams.creator-project/2':
        project={**project,**{k:project.get(k,[]) for k in ('operations','data_models','migrations','connections')}}
        project['entrypoints']={**project['entrypoints'],'pipelines':project['entrypoints'].get('pipelines',[]),
                                'ui':project['entrypoints'].get('ui')}
    references = [*project['entrypoints']['employees'], *project['entrypoints']['pipelines'],
                  *([project['entrypoints']['ui']] if project['entrypoints']['ui'] else []), project['dependency_lock'],
                  *project['data_models'], *project['migrations'], *project['connections'],
                  *project['source_access']['public_files']]
    operations = {}
    schemas = []
    for op in project['operations']:
        if op['key'] in operations:
            raise CreatorContractError('duplicate_operation')
        operations[op['key']] = op
        references.extend(op[k] for k in ('handler', 'input', 'output'))
        schemas.extend([read(op['input']), read(op['output'])])
    for ref in references:
        asset(ref)
    employees = {}
    for path in project['entrypoints']['employees']:
        employee = read(path)
        from .creator_definitions import validate_author
        employee = validate_author('employee', employee)
        from .employee_avatars import attachment
        attachment(employee['avatar'], files)
        asset(employee['soul_file'])
        for directory in employee['skill_dirs']:
            asset(relative(directory) + '/SKILL.md')
        employees[path] = employee
    pipelines, pipeline_keys = {}, set()
    for path in project['entrypoints']['pipelines']:
        pipeline = read(path)
        from .creator_definitions import validate_author
        pipeline = validate_author('pipeline', pipeline)
        from .creator_mcp_source import program_sources
        for program in program_sources(pipeline):
            asset(program['source']+'/mcp/manifest.json')
        refs = pipeline['employees']
        if (len({r['ref'] for r in refs}) != len(refs) or
                any('source' in r and relative(r['source']) not in employees for r in refs)):
            raise CreatorContractError('invalid_pipeline_reference')
        key = pipeline.get('key')
        if key:
            if key in pipeline_keys:
                raise CreatorContractError('duplicate_pipeline_key')
            pipeline_keys.add(key)
        from .portable_pipeline import validate_pipeline_bindings
        try:
            from .pipeline_dependency_contracts import skills as member_skills
            validate_pipeline_bindings(pipeline['pipeline'], {
                row['ref']: member_skills(row, employees) for row in refs})
        except ContractError as error:
            raise CreatorContractError('invalid_pipeline_definition', str(error)) from error
        pipelines[path] = pipeline
    lock = contract('dependencies.schema.json', read(project['dependency_lock']))
    if lock['root'] != project['key']:
        raise CreatorContractError('dependency_root_mismatch')
    deps = {d['key']: d for d in lock['dependencies']}
    if len(deps) != len(lock['dependencies']):
        raise CreatorContractError('duplicate_dependency')
    visited = set()
    def visit(key, ancestors):
        if key == project['key'] or key in ancestors:
            raise CreatorContractError('dependency_cycle')
        if key not in deps:
            raise CreatorContractError('missing_dependency')
        if key in visited:
            return
        for child in deps[key]['requires']:
            visit(child, ancestors | {key})
        visited.add(key)
    for key in deps:
        visit(key, set())
    connections = {}
    for path in project['connections']:
        descriptor = contract('connection.schema.json', read(path))
        key = descriptor['key']
        if key in connections:
            raise CreatorContractError('duplicate_connection')
        connections[key] = descriptor
        for endpoint in descriptor['endpoints'].values():
            if ('..' in endpoint['path'].split('/') or '//' in endpoint['path']
                    or endpoint['effect'] == 'read' and endpoint['method'] != 'GET'):
                raise CreatorContractError('invalid_endpoint')
            schemas.extend([endpoint['input'], endpoint['output'], *endpoint['query'].values()])
    for op in operations.values():
        if op['connection'] is not None and op['connection'] not in connections:
            raise CreatorContractError('missing_connection')
    registry = read('ui/views.json') if 'ui/views.json' in files else None
    models = {}
    registrations = {}
    if 'data/models.json' in files:
        data_registry = contract('models.schema.json', read('data/models.json'), 'data-v1')
        for model in data_registry['models']:
            if model['type'] in registrations:
                raise CreatorContractError('duplicate_registration')
            if model['schema'] not in project['data_models']:
                raise CreatorContractError('undeclared_model', model['schema'] + ' 未列入 project.json 的 data_models；这里需要模型 schema 文件路径。')
            registrations[model['type']] = model['schema']
    if registry is not None:
        contract('registry.schema.json', registry, 'ui-v2')
        for group, field in (('views', 'id'), ('models', 'type'), ('operations', 'id')):
            ids = [entry[field] for entry in registry[group]]
            if len(ids) != len(set(ids)):
                raise CreatorContractError('duplicate_registration')
        for model in registry['models']:
            if model['schema'] not in project['data_models']:
                raise CreatorContractError('undeclared_model', model['schema'] + ' 未列入 project.json 的 data_models；这里需要模型 schema 文件路径。')
            if model['type'] in registrations and registrations[model['type']] != model['schema']:
                raise CreatorContractError('model_schema_conflict')
            registrations[model['type']] = model['schema']
        for view in registry['views']:
            asset(view['entry'])
            schemas.extend([read(view['input_schema']), read(view['context_schema'])])
        for op in registry['operations']:
            asset(op['entry'])
            schemas.extend([read(op['input_schema']), read(op['output_schema'])])
    if set(project['data_models']) != set(registrations.values()):
        raise CreatorContractError('unregistered_model')
    for name, path in registrations.items():
        models[name] = read(path)
        schemas.append(models[name])
    # Author schemas run outside the HTTP/Agent process, with CPU, RSS and wall limits.
    if schema_validator is None:
        from .creator_validation import validate_schemas
        schema_validator = validate_schemas
    # A trusted managed worker supplies the same pure validator under its own
    # process budget. No source file or request may select this callback.
    schema_validator(schemas)
    result = {'source': source_index if source_index is not None else _source_tree(files), 'project': project, 'dependencies': lock,
            'employees': employees, 'pipelines': pipelines, 'models': models,
            'operations': operations, 'connections': connections, 'views': registry}
    from .pipeline_closure_contracts import verify as verify_pipeline_closure
    verify_pipeline_closure(files, result)
    return result
