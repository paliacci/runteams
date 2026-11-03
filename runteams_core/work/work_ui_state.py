"""Library/device-owned UI recovery breadcrumbs, never work or execution authority."""
import hashlib,json,uuid
from runteams_core.storage import device_data
from runteams_core.foundation.contracts import ContractError
from runteams_core.foundation.identity.work_identity import schedule_binding

PREFIX='work-ui-state:'
KINDS={'pipeline-admission','pipeline-control','pipeline-create','pipeline-settings','pipeline-flow','employee-schedule-operation'}
MAX_VALUE=2*1024*1024

def key(value):
    if not isinstance(value,str) or len(value.encode())>4096 or value.split(':',1)[0] not in KINDS or '\0' in value:
        raise ContractError('工作界面保存位置无效。')
    return value

def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)

def owner():
    if not device_data.personal():raise PermissionError('请在个人本机工作区核对原操作。')
    return schedule_binding(device_data.identity())

def checked(value,scope):
    if (not isinstance(value,dict) or set(value)!={'schema','owner','revision','value','receipts'} or value['schema']!='runteams.work-ui-state/1'
            or value['owner']!=scope or type(value['revision']) is not int or value['revision']<1
            or value['value'] is not None and (not isinstance(value['value'],str) or len(value['value'].encode())>MAX_VALUE)
            or not isinstance(value['receipts'],dict) or len(value['receipts'])>128):raise ContractError('原操作界面资料无效。')
    if value['value'] is not None:json.loads(value['value'])
    for op,receipt in value['receipts'].items():
        if str(uuid.UUID(op))!=op or not isinstance(receipt,dict) or set(receipt)!={'digest','revision'} or not isinstance(receipt['digest'],str) or len(receipt['digest'])!=64 or any(ch not in '0123456789abcdef' for ch in receipt['digest']) or type(receipt['revision']) is not int or not 1<=receipt['revision']<=value['revision']:raise ContractError('原操作界面回执无效。')
    return value

def records(c,scope):
    result={}
    for name,raw in c.execute('SELECT key,value FROM device_settings WHERE key LIKE ?', (PREFIX+'%',)):
        name=key(name.removeprefix(PREFIX));value=checked(json.loads(raw),scope)
        result[name]={'revision':value['revision'],'value':value['value']}
    if sum(item['value'] is not None for item in result.values())>512:raise ContractError('工作界面待核对记录过多，请先完成原操作。')
    return result

def read():
    scope=owner()
    with device_data.connect(readonly=True) as c:return {'schema':'runteams.work-ui-state-list/1','owner':scope,'items':records(c,scope),'storage_scope':'device'}

def save(data):
    if not isinstance(data,dict) or set(data)!={'key','value','expected_revision','operation_id'}:raise ContractError('界面保存请求无效。')
    name=key(data['key']);raw=data['value'];op=data['operation_id'];revision=data['expected_revision']
    if not isinstance(op,str) or str(uuid.UUID(op))!=op or type(revision) is not int or revision<0 or raw is not None and (not isinstance(raw,str) or len(raw.encode())>MAX_VALUE):raise ContractError('界面保存操作无效。')
    if raw is not None:json.loads(raw)
    scope=owner();digest=hashlib.sha256(canonical(data).encode()).hexdigest()
    with device_data.connect() as c:
        stored=c.execute('SELECT value FROM device_settings WHERE key=?',(PREFIX+name,)).fetchone()
        old=checked(json.loads(stored[0]),scope) if stored else {'revision':0,'receipts':{}}
        receipt=old['receipts'].get(op)
        if receipt:
            if receipt['digest']!=digest:raise ContractError('原界面保存操作内容已变化。')
            return {'operation_id':op,'revision':receipt['revision'],'storage_scope':'device'}
        if old['revision']!=revision:return {'error':'另一窗口已保存原操作，请重新打开核对。','code':'work_ui_state_conflict'},409
        if raw is not None and (not stored or old['value'] is None) and c.execute("SELECT count(*) FROM device_settings WHERE key LIKE ? AND json_extract(value,'$.value') IS NOT NULL",(PREFIX+'%',)).fetchone()[0]>=512:raise ContractError('工作界面保存记录超过上限。')
        receipts={**old['receipts'],op:{'digest':digest,'revision':revision+1}}
        receipts=dict(sorted(receipts.items(),key=lambda item:item[1]['revision'])[-128:])
        value={'schema':'runteams.work-ui-state/1','owner':scope,'revision':revision+1,'value':raw,'receipts':receipts}
        c.execute('INSERT INTO device_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(PREFIX+name,canonical(value)))
        return {'operation_id':op,'revision':revision+1,'storage_scope':'device'}

def verify(connection,scope):
    records(connection,schedule_binding(scope))
