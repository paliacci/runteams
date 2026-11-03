"""Host-observed runtime conditions, never a program/model execution grant.

Keys are the existing SDK protocol (mcp) or native CLI provider identifiers.
No author/client ready flag, runtime path or executable is accepted. Frozen
work rechecks its original observation, independently of current defaults.
"""
import copy
import re
from . import device_data
from .work_identity import schedule_binding

SCHEMA='runteams.configuration-runtime/1'
KEYS=frozenset(('mcp','codex','claude-code'))

def supports(field):
    binding=field.get('binding',{})
    return field.get('type')=='runtime' and binding.get('provider')=='runtime' and binding.get('key') in KEYS

def observe(field):
    if not supports(field):raise ValueError('此运行条件尚未接通。')
    key=field['binding']['key'];scope=device_data.identity()
    if key=='mcp':
        from .employee_mcp import platform_runtime
        # The original platform loader verifies the pin and every resource byte.
        runtime=platform_runtime()
        value={'kind':'mcp','manifest_sha256':runtime.manifest_sha256}
    else:
        from .source_employee_runtime import resolve_runtime
        value={'kind':'model-channel','runtime':resolve_runtime({'provider':key,'model':'','effort':''})}
    device_data.check(scope)
    return {'schema':SCHEMA,'owner':schedule_binding(scope),'key':key,**value}

def verify_record(field,selected,scope):
    """Portable observation record, without a live runtime/channel lookup."""
    if not supports(field) or not isinstance(selected,dict) or selected.get('schema')!=SCHEMA or selected.get('key')!=field['binding']['key']:
        raise ValueError('运行条件与原声明不符。')
    if selected.get('owner')!=schedule_binding(scope):raise PermissionError('运行条件不属于当前资料库。')
    key=field['binding']['key'];base={'schema','owner','key','kind'}
    if key=='mcp':
        if (set(selected)!=base|{'manifest_sha256'} or selected['kind']!='mcp' or not isinstance(selected['manifest_sha256'],str)
                or not re.fullmatch('[a-f0-9]{64}',selected['manifest_sha256'])):raise ValueError('原运行条件记录无效。')
    else:
        if set(selected)!=base|{'runtime'} or selected['kind']!='model-channel':raise ValueError('原运行条件无效。')
        from .definition_contracts import validate_definition
        runtime=validate_definition('runtime_snapshot',selected['runtime'])
        if set(runtime)!={'provider','channel_id','model','effort'} or runtime['provider']!=key:raise ValueError('原模型运行条件无效。')


def verify(field,selected):
    scope=device_data.identity();verify_record(field,selected,scope)
    key=field['binding']['key'];base={'schema','owner','key','kind'}
    if key=='mcp':
        if set(selected)!=base|{'manifest_sha256'} or selected['kind']!='mcp' or selected!=observe(field):
            raise ValueError('原工作所需的包内运行环境已变化，请重新核对。')
    else:
        if set(selected)!=base|{'runtime'} or selected['kind']!='model-channel':raise ValueError('原运行条件无效。')
        import product_store,model_channels
        from .definition_contracts import validate_definition
        runtime=validate_definition('runtime_snapshot',selected['runtime'])
        if set(runtime)!={'provider','channel_id','model','effort'}:raise ValueError('原模型运行条件无效。')
        channel=product_store.get_channel(runtime['channel_id'])
        if not channel or not channel.get('enabled') or channel['provider']!=key or runtime['provider']!=key:
            raise ValueError('原模型渠道尚未连接。')
        catalog=model_channels.require_catalog(channel)
        if not any(item['value']==runtime['model'] for item in catalog['models']):raise ValueError('原工作所需的模型已不可用。')
        model,effort=model_channels.normalize_selection(channel,runtime['model'],runtime['effort'],catalog=catalog)
        if (model,effort)!=(runtime['model'],runtime['effort']):raise ValueError('原模型运行条件已变化。')
    device_data.check(scope)
    return copy.deepcopy(selected)
