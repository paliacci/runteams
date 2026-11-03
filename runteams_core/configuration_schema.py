"""Pure employee/pipeline configuration declarations, without user values or authority."""
import copy
from datetime import date
from decimal import Decimal
import math
from jsonschema import Draft202012Validator
from . import collection_schema

PRIVATE=frozenset(("secret","resource","connection","runtime"))
CHOICES=frozenset(("select","multiselect","checklist"))


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def declaration_schema():
    from .definition_contracts import definition_schema
    schema = definition_schema('employee_configuration')
    return {'$schema': schema['$schema'], **schema['$defs']['employee_configuration']}


def fields(definition):
    return [field for group in definition['groups'] for field in group['fields']]


def managed_fields(definition):
    return [{**copy.deepcopy(row), 'type':'resource', 'required':True}
            for row in definition.get('managed_resources', [])]


def data_fields(definition):
    return fields(definition) + managed_fields(definition)


def _value_error(field, value):
    kind, constraints = field['type'], field.get('constraints', {})
    if kind in PRIVATE:
        return '此项必须通过平台的资料选择、连接或凭据入口配置。'
    if value is None:
        return '请填写此项。' if field.get('required') else ''
    if kind in ('text', 'textarea', 'date', 'select'):
        if not isinstance(value, str):
            return '请填写文本。'
        if field.get('required') and not value.strip():
            return '请填写此项。'
        if len(value) > constraints.get('max_length', 20000) or len(value) < constraints.get('min_length', 0):
            return '文本长度不符合要求。'
        if kind == 'date' and value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    return '请选择有效日期。'
            except ValueError:
                return '请选择有效日期。'
        if kind == 'select' and value and value not in {o['value'] for o in field['options']}:
            return '选项已变化，请重新选择。'
    elif kind == 'number':
        if not _finite(value):
            return '请填写有效数字。'
        if value < constraints.get('min', -math.inf) or value > constraints.get('max', math.inf):
            return '数字超出允许范围。'
        if 'step' in constraints:
            quotient = (Decimal(str(value)) - Decimal(str(constraints.get('min', 0)))) / Decimal(str(constraints['step']))
            if quotient != quotient.to_integral_value():
                return '数字精度不符合要求。'
    elif kind == 'checkbox':
        if type(value) is not bool:
            return '请选择是或否。'
    elif kind in ('multiselect', 'checklist'):
        if (not isinstance(value, list) or any(not isinstance(v, str) for v in value)
                or len(value) != len(set(value))):
            return '请选择有效且不重复的选项。'
        if field.get('required') and not value:
            return '请至少选择一项。'
        if set(value) - {o['value'] for o in field['options']}:
            return '选项已变化，请重新选择。'
    return ''


def validate_declaration(value):
    if next(Draft202012Validator(declaration_schema()).iter_errors(value), None):
        raise ValueError('员工配置声明无效。')
    groups = [g['key'] for g in value['groups']]
    rows = fields(value)
    keys = [f['key'] for f in data_fields(value)]
    if len(groups) != len(set(groups)) or len(keys) != len(set(keys)) or len(keys) > 128:
        raise ValueError('配置分组或字段身份重复，或数量超过限制。')
    for field in data_fields(value):
        kind = field['type']
        if kind in PRIVATE and 'default' in field:
            raise ValueError('资料、连接、凭据和运行条件不能带使用者默认值。')
        if kind in CHOICES:
            options = field.get('options', [])
            if not options or len({o['value'] for o in options}) != len(options):
                raise ValueError('请选择项必须有唯一的稳定值。')
        elif 'options' in field:
            raise ValueError('此配置类型不接受选项。')
        allowed = {'min', 'max', 'step'} if kind == 'number' else {'min_length', 'max_length'} if kind in ('text', 'textarea') else set()
        constraints = field.get('constraints', {})
        if set(constraints) - allowed or any(not _finite(v) for v in constraints.values()):
            raise ValueError('配置校验条件不适用于此类型。')
        if constraints.get('min', -math.inf) > constraints.get('max', math.inf) or constraints.get('min_length', 0) > constraints.get('max_length', 20000):
            raise ValueError('配置校验范围无效。')
        if kind in PRIVATE:
            if 'binding' not in field:
                raise ValueError('此配置必须声明平台接入来源。')
            provider = field['binding']['provider']
            expected = {'resource': ('local_asset', 'sdk_resource', 'local_collection'), 'connection': ('sdk_connection',),
                        'secret': ('native_credential',), 'runtime': ('runtime',)}[kind]
            if provider not in expected:
                raise ValueError('配置类型与平台接入来源不符。')
            resource_kind = field['binding'].get('resource_kind')
            if kind == 'resource':
                supported = ('file', 'folder') if provider == 'local_asset' else ('collection',) if provider == 'local_collection' else ('document', 'collection')
                if resource_kind not in supported:
                    raise ValueError('资料类型与选择入口不符。')
            elif resource_kind is not None:
                raise ValueError('此依赖不接受资料类型。')
            if provider == 'local_collection':
                collection_schema.validate_binding(field['binding'])
            elif set(field['binding']) & {'access', 'record_schema'}:
                raise ValueError('此依赖不接受本机集合字段或权限声明。')
        elif 'binding' in field:
            raise ValueError('普通配置不能声明权限绑定。')
        if 'default' in field and _value_error(field, field['default']):
            raise ValueError('配置默认值不符合字段声明。')
    return copy.deepcopy(value)

