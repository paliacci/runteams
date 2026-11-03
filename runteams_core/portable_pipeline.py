from runteams_core.resources import root as resource_root
"""Strict portable v2 pipeline shape, semantics and ID localization.

The independent schema references the canonical employee/skill definitions.
Normalization is the existing pipeline authority; there is no v1 conversion.
"""
import copy
from functools import lru_cache
import json
import math
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .contracts import ContractError, normalize_pipeline_definition
from .definition_contracts import contract_catalog

SCHEMA = 'runteams.marketplace-pipeline/v2'
SCHEMA_PATH = resource_root() / 'contracts/marketplace-pipeline-v2.json'


@lru_cache(maxsize=1)
def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def pipeline_schema():
    return copy.deepcopy(_schema())


@lru_cache(maxsize=1)
def _validator():
    schema = _schema()
    canonical = contract_catalog()['definitions']
    registry = Registry().with_resources([(canonical['$id'], Resource.from_contents(canonical)),
                                          (schema['$id'], Resource.from_contents(schema))])
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError('流水线不能包含非JSON数值')
    if isinstance(value, dict):
        for child in value.values(): _finite(child)
    elif isinstance(value, list):
        for child in value: _finite(child)


def _default_is_portable(value):
    if isinstance(value, list):
        for child in value: _default_is_portable(child)
    elif isinstance(value, str) and (value.startswith(('/', '~/', '~\\', 'file:', './', '../')) or re.match(r'^[A-Za-z]:[\\/]', value)):
        raise ContractError('流水线参数默认值不能引用本机原件路径')


def _unique(rows, key, label):
    values = [row[key] for row in rows]
    if len(values) != len(set(values)): raise ContractError(label+'重复')


def _local_definition(pipeline, employee_ids, skill_maps):
    result = copy.deepcopy(pipeline)
    result.pop('name')
    for position in result['positions']:
        if position['kind'] == 'approval': continue
        ref = position.pop('employee_ref')
        position['employee_id'] = employee_ids[ref]
        position['skill_key'] = skill_maps[ref][position['skill_key']]
    for standard in result.get('standards', []):
        if 'employee_refs' in standard:
            standard['employee_ids'] = [employee_ids[ref] for ref in standard.pop('employee_refs')]
    # Validate against the same authority as authored pipelines. Return the exact
    # mapped structure so declared fields are not silently discarded/coerced.
    normalize_pipeline_definition(result)
    return result


def validate_pipeline_bindings(pipeline, skills):
    """Check canonical routing against fixed employee skill keys, without IDs.

    Callers validate their source/asset shape first. The positive handles used
    by normalization are local to this pure check, never employee identities.
    Return routing uses the same graph authority as authored native pipelines.
    """
    _finite(pipeline)
    positions, states = pipeline['positions'], pipeline.get('states', [])
    _unique(positions+states, 'key', '流水线列键')
    _unique(pipeline.get('parameters', []), 'key', '流水线参数')
    _unique(pipeline.get('standards', []), 'key', '流水线标准')
    position_keys = {position['key'] for position in positions}
    used = set()
    maps = {ref: {key: key for key in keys} for ref, keys in skills.items()}
    for position in positions:
        if position['kind'] == 'approval': continue
        ref = position['employee_ref']
        if ref not in maps or position['skill_key'] not in maps[ref]:
            raise ContractError('流水线岗位必须引用指定员工的固定工作')
        used.add(ref)
    if used != set(maps): raise ContractError('流水线不能包含未引用员工')
    for parameter in pipeline.get('parameters', []):
        for field in ('writers','visible_to','producers'):
            if set(parameter.get(field, []))-position_keys:
                raise ContractError('流水线参数引用了无效岗位')
        if 'default' in parameter: _default_is_portable(parameter['default'])
    for standard in pipeline.get('standards', []):
        if set(standard.get('employee_refs', []))-used:
            raise ContractError('流水线标准引用了无效员工')
    ids = {ref:index+1 for index,ref in enumerate(maps)}
    _local_definition(pipeline, ids, maps)


def verified_pipeline_asset(value):
    _finite(value)
    if next(_validator().iter_errors(value), None) is not None:
        raise ContractError('市场流水线不符合完整v2合同')
    if 'configuration' in value:
        from .configuration_schema import validate_declaration
        validate_declaration(value['configuration'])
    from .creator_mcp_source import verify_pipeline_programs
    if 'program_bundles' in value:
        try:verify_pipeline_programs(value['program_bundles'])
        except ValueError as error:raise ContractError('流水线程序附件校验失败：'+str(error)) from error
    from .portable_employee import verify as verified_employee_asset
    by_ref = {}
    for row in value['employees']:
        if row['ref'] in by_ref: raise ContractError('流水线员工引用重复')
        by_ref[row['ref']] = verified_employee_asset(row['asset'])
    pipeline = value['pipeline']
    validate_pipeline_bindings(pipeline, {
        ref: [entry['package_key'] for entry in asset['employee']['skill_refs']]
        for ref, asset in by_ref.items()})
    # Return/rework edges use the same graph authority as source work.
    # The execution ledger's visit guard bounds loops; publication cannot erase them.
    return copy.deepcopy(value)


def localize_pipeline(asset, employee_ids, skill_maps):
    asset = verified_pipeline_asset(asset)
    refs = {row['ref'] for row in asset['employees']}
    if set(employee_ids) != refs or set(skill_maps) != refs or len(set(employee_ids.values())) != len(refs) or any(type(value) is not int or value<=0 for value in employee_ids.values()):
        raise ContractError('安装流水线缺少本机员工身份')
    try:
        return _local_definition(asset['pipeline'],employee_ids,skill_maps)
    except KeyError:
        raise ContractError('安装流水线缺少本机技能映射') from None


def portable_definition(pipeline, employee_refs):
    """Map a trusted frozen local definition; assets are attached by the exporter."""
    if set(pipeline)-{'schema','name','origin','positions','edges','states','parameters','standards'}:
        raise ContractError('流水线包含未知导出字段')
    result = copy.deepcopy(pipeline)
    result.pop('schema',None);result.pop('origin',None)
    for position in result['positions']:
        if position.get('kind') == 'approval': continue
        employee_id = position.pop('employee_id')
        if employee_id not in employee_refs: raise ContractError('缺少流水线冻结员工')
        position['employee_ref'] = employee_refs[employee_id]
        position.pop('employee_release_id',None)
    for parameter in result.get('parameters', []):
        if parameter.get('type') == 'secret' and 'default' in parameter:
            raise ContractError('秘密参数不能携带默认值')
    for standard in result.get('standards', []):
        if 'employee_ids' in standard:
            try: standard['employee_refs'] = [employee_refs[employee_id] for employee_id in standard.pop('employee_ids')]
            except KeyError: raise ContractError('流水线标准引用了未导出员工') from None
    return result
