"""Versioned author sources compiled from their complete immutable byte tree.

Portable employees/pipelines use the existing product-model validators and
installer compiler. This stage allocates no machine IDs or runtime authority.
"""
from runteams_core.assets.skills import skill_packages as _skill_packages
import base64
import copy
import hashlib
from pathlib import Path, PurePosixPath
import tempfile

from jsonschema import Draft202012Validator

from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, relative
from runteams_core.authoring.definition_contracts import contract_catalog

CATALOG_PATH = 'definitions/creator.json'


def definition_target(compiled):
    return 'employee-bundle/v1'


def compiler_identity():
    root = Path(__file__).resolve().parents[1]
    return {'contracts': contract_catalog()['digest'], 'implementation': {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in
        ('authoring/creator_definitions.py', 'authoring/creator_contracts.py', 'authoring/creator_schema_validation.py', 'authoring/definition_contracts.py', 'authoring/creator_conversation_assets.py',
         'assets/skills/skill_packages.py', 'assets/skills/skill_provenance.py', 'assets/skills/skill_icons.py', 'agents/capability_runtime.py', 'configuration/configuration_schema.py', 'employees/portable_employee.py', 'assets/skills/skill_metadata.py', 'assets/skills/skill_bundles.py', 'assets/collections/collection_schema.py', 'pipelines/portable_pipeline.py', 'authoring/compilation/creator_mcp_source.py', 'employees/mcp/employee_mcp_package.py', 'employees/employee_avatars.py', 'pipelines/pipeline_dependency_contracts.py', 'pipelines/pipeline_closure_contracts.py', 'foundation/identity/resource_ids.py')}}


def author_schema(kind, *, version='3'):
    """Reuse the canonical fields; never maintain a second work definition."""
    catalog = contract_catalog()
    definitions = catalog['definitions']['$defs']
    if kind == 'employee':
        return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            'type': 'object', 'additionalProperties': False,
            'required': ['schema', 'key', 'name', 'avatar', 'soul_file', 'skill_dirs', 'runtime_requirement'],
            'properties': {'schema': {'const': 'runteams.employee-source/' + version},
                'key': {'type': 'string', 'pattern': '^[a-z][a-z0-9-]{0,79}$'},
                'name': definitions['portable_employee']['properties']['name'],
                'avatar': {**definitions['portable_employee']['properties']['avatar'],
                    'description':'员工包内图片的工程根目录相对路径，如 assets/avatar.webp；图片须随源码保存。未自定义时可用 preset:bottts:nova。'},
                'soul_file': {'type': 'string', 'minLength': 1, 'maxLength': 240},
                'skill_dirs': {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 240},
                    'maxItems': 64, 'uniqueItems': True},
                'runtime_requirement': definitions['portable_runtime'],
                'configuration': definitions['employee_configuration']}}
    if kind == 'pipeline':
        from runteams_core.pipelines.pipeline_dependency_contracts import schema as dependency_schema
        schema = catalog['extensions']['marketplace_pipeline']
        return {'$schema': schema['$schema'], '$defs': schema['$defs'],
            'type': 'object', 'additionalProperties': False,
            'required': ['schema', 'pipeline', 'employees'], 'properties': {
                'schema': {'const': 'runteams.pipeline-source/' + version},
                **({'key': {'type':'string','pattern':'^[a-z][a-z0-9-]{0,79}$'},
                    'description': {'type':'string','maxLength':12000},
                    'configuration': definitions['employee_configuration'],
                    'programs': {'type':'array','maxItems':64,
                        'items':{'$ref':'#/$defs/pipeline_program_source'}}} if version == '3' else {}),
                'pipeline': {'$ref': '#/$defs/pipeline'},
                'employees': {'type': 'array', 'minItems': 1, 'maxItems': 64,
                    'items': {'type': 'object', 'additionalProperties': False,
                        'required': ['ref'], 'oneOf': [{'required': ['source']}, {'required': ['dependency']}],
                        'properties': {
                            'ref': {'type': 'string', 'pattern': '^[a-z][a-z0-9-]{0,79}$'},
                            'source': {'type': 'string', 'minLength': 1, 'maxLength': 240},
                            'dependency': dependency_schema()}}}}}
    if kind == 'skill':
        # Only the transitive definition closure is exposed to the author.
        wanted, done = {'skill_extension'}, {}
        def refs(value):
            if isinstance(value, dict):
                if str(value.get('$ref', '')).startswith('#/$defs/'):
                    wanted.add(value['$ref'].split('/')[-1])
                for child in value.values(): refs(child)
            elif isinstance(value, list):
                for child in value: refs(child)
        while wanted:
            name = wanted.pop()
            if name not in done:
                done[name] = definitions[name]; refs(done[name])
            wanted.difference_update(done)
        return {'$schema': catalog['definitions']['$schema'], '$defs': done, '$ref': '#/$defs/skill_extension'}
    raise CreatorContractError('unknown_author_schema')


def validate_author(kind, value):
    version = str(value.get('schema', '')).rsplit('/', 1)[-1] if kind != 'skill' else '3'
    if version != '3' or next(Draft202012Validator(author_schema(kind, version=version)).iter_errors(value), None) is not None:
        raise CreatorContractError('invalid_' + kind + '_source')
    if kind in ('employee', 'pipeline') and 'configuration' in value:
        from runteams_core.configuration.configuration_schema import validate_declaration
        try:
            validate_declaration(value['configuration'])
        except ValueError as error:
            raise CreatorContractError('invalid_' + kind + '_configuration', str(error)) from error
    return value


def compile_definitions(files, compiled, *, require=False):
    """Freeze the current complete sources without runtime or machine authority."""
    from runteams_core.authoring.compilation.creator_mcp_source import definition_files, pipeline_programs
    programs=pipeline_programs(files,compiled)
    files=definition_files(files,compiled)
    from runteams_core.employees.portable_employee import verify as verified_employee_asset
    from runteams_core.assets.skills.skill_bundles import extension as _extension
    from runteams_core.pipelines.portable_pipeline import verified_pipeline_asset
    sources = compiled['employees']; pipelines = compiled['pipelines']
    if any('dependency' in row for pipeline in pipelines.values() for row in pipeline['employees']):
        raise CreatorContractError('local_employee_dependency_not_publishable',
            '这条流水线含本机精确员工引用，暂不能发布；不会打包本机授权或转发租用员工。')
    versions = [v['schema'].rsplit('/', 1)[-1] for v in [*sources.values(), *pipelines.values()]]
    if not versions or set(versions) != {'3'}:
        raise CreatorContractError('independent_employee_source_required')
    employees, by_key, skill_digests = {}, set(), {}
    with tempfile.TemporaryDirectory(prefix='runteams-creator-definitions-') as tmp:
        for source_path, employee in sources.items():
            if not employee['skill_dirs']:
                raise CreatorContractError('missing_work', '尚未声明工作技能，请补齐技能的工作声明后再编译。')
            if employee['key'] in by_key:
                raise CreatorContractError('duplicate_employee_key')
            by_key.add(employee['key'])
            bundles, keys = [], set()
            for directory in employee['skill_dirs']:
                prefix = relative(directory) + '/'
                name = PurePosixPath(directory).name
                if name in keys: raise CreatorContractError('duplicate_skill_key')
                keys.add(name)
                package_files = {p[len(prefix):]: b for p, b in files.items() if p.startswith(prefix)}
                # PackageStore performs the same frontmatter, paths, resources,
                # tool and native-credential checks as ordinary product skills.
                root = Path(tmp) / 'employees' / employee['key'] / name
                root.mkdir(parents=True)
                for path, body in package_files.items():
                    target = root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
                prepared = _skill_packages.prepare(root)
                if prepared['manifest']['schema'] != 'runteams.package-extension/v3':
                    raise CreatorContractError('independent_skill_required',
                        '员工的技能须使用独立工作声明 /v3，全部技能资产随作品打包。')
                bundles.append({'package_key': name, 'digest': prepared['digest'], 'files': [
                    {'path': p, 'sha256': hashlib.sha256(b).hexdigest(), 'size': len(b),
                        'content_base64': base64.b64encode(b).decode('ascii')}
                    for p, b in sorted(package_files.items())]})
            try: soul = files[employee['soul_file']].decode('utf-8')
            except UnicodeError: raise CreatorContractError('invalid_employee_soul') from None
            from runteams_core.employees.employee_avatars import attachment
            picture = attachment(employee['avatar'], files)
            asset = verified_employee_asset({'schema': 'runteams.marketplace-employee/v2',
                **({'avatar_file':picture} if picture else {}),
                'employee': {k: copy.deepcopy(employee[k]) for k in ('name', 'avatar', 'runtime_requirement')} |
                    {'soul': soul, 'skill_refs': [{'package_key': b['package_key'], 'digest': b['digest']} for b in bundles]} |
                    ({'configuration': copy.deepcopy(employee['configuration'])} if 'configuration' in employee else {}),
                'skill_bundles': bundles})
            for bundle in bundles:
                ext = _extension(bundle)
                if any(a['target']['skill_key'] not in keys for a in ext['work']['result_actions']):
                    raise CreatorContractError('missing_result_action_skill')
            employees[source_path] = asset
    result_pipelines, pipeline_keys = {}, set()
    for path, pipeline in pipelines.items():
        if pipeline.get('key'):
            if pipeline['key'] in pipeline_keys: raise CreatorContractError('duplicate_pipeline_key')
            pipeline_keys.add(pipeline['key'])
        result_pipelines[path] = verified_pipeline_asset({'schema': 'runteams.marketplace-pipeline/v2',
            'pipeline': pipeline['pipeline'], 'employees': [
                {'ref': row['ref'], 'asset': employees[row['source']]} for row in pipeline['employees']],
            **({'configuration':copy.deepcopy(pipeline['configuration'])} if 'configuration' in pipeline else {}),
            **({'program_bundles':programs[path]} if path in programs else {})})
    return {'schema': 'runteams.creator-definitions/1', 'source_sha256': compiled['source']['sha256'],
        'employees': employees, 'pipelines': result_pipelines}


def definition_artifacts(files, compiled, *, require=False):
    from runteams_core.foundation.contracts import ContractError
    try:
        value = compile_definitions(files, compiled, require=require)
    except CreatorContractError:
        raise
    except ContractError as error:
        raise CreatorContractError('invalid_product_definition', str(error)[:1000]) from error
    return {} if value is None else {CATALOG_PATH: canonical(value)}
