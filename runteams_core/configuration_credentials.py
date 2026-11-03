"""Same-name selections over the existing host vault and MCP enablement.

A saved user selection is not program enablement. Original private MCP trust
still authorizes each exact release; neither portable records nor key presence
starts code. Plaintext remains in app_secrets and the declared child env only.
"""
from contextlib import contextmanager
import hmac
from .employee_mcp_package import credential_key
from . import device_data
from .work_identity import schedule_binding

SCHEMA='runteams.configuration-credential/1'

def supports(field):
 binding=field.get('binding',{});key=binding.get('key')
 return (field.get('type')=='secret' and binding.get('provider')=='native_credential' and credential_key(key))

def _values(keys):
 import app_secrets
 values=app_secrets.resolve(keys)
 if set(values)!=set(keys) or any(not isinstance(v,str) or not 1<=len(v.encode('utf-8'))<=8192 or '\0' in v for v in values.values()):
  raise ValueError('请先在本机保存此项所需的凭据。')
 return values

def available(field):
 if not supports(field):return False
 try:_values((field['binding']['key'],));return True
 except (ValueError,OSError):return False

def verify_record(field,value,scope):
 if (not supports(field) or not isinstance(value,dict) or set(value)!={'schema','owner','key'}
   or value['schema']!=SCHEMA or value['key']!=field['binding']['key']):raise ValueError('请选择此项声明的同名本机凭据。')
 if value['owner']!=schedule_binding(scope):raise PermissionError('凭据选择不属于当前资料库。')

def select(field,selection):
 scope=device_data.identity()
 if not supports(field) or not isinstance(selection,dict) or set(selection) not in ({'key'},{'schema','owner','key'}):raise ValueError('请选择此项声明的同名本机凭据。')
 value={'schema':SCHEMA,'owner':schedule_binding(scope),'key':field['binding']['key']}
 if selection.get('key')!=value['key']:raise ValueError('不能将其他名称的凭据绑定到此项。')
 if set(selection)!={'key'}:verify_record(field,selection,scope)
 _values((value['key'],));device_data.check(scope);return value

def update(field,value):
 if not supports(field) or not isinstance(value,str) or not value.strip() or not 1<=len(value.encode('utf-8'))<=8192 or '\0' in value:
  raise ValueError('请填写有效凭据，最多8192字节。')
 scope=device_data.identity()
 import app_secrets
 app_secrets.set_secret(field['binding']['key'],value)
 device_data.check(scope)
 return {'selection':select(field,{'key':field['binding']['key']}),'available':True}

@contextmanager
def lease(definition,snapshot,required,check):
 from .configuration_schema import fields
 from .employee_mcp import MCPBoundCredentials
 scope=device_data.identity();index={f['binding']['key']:f for f in fields(definition) if supports(f)}
 if set(required)-set(index):raise PermissionError('程序凭据与原配置声明不符。')
 def authorize():
  check();device_data.check(scope)
  for name in required:
   field=index[name];value=snapshot.get('bindings',{}).get(field['key'])
   if snapshot.get('states',{}).get(field['key'])!='configured':raise PermissionError('程序所需凭据尚未明确选择。')
   verify_record(field,value,scope)
  try:return _values(required)
  except ValueError:raise PermissionError('程序所需的本机凭据已不可用。') from None
 values=authorize()
 def current():
  try:
   now=authorize()
   return all(hmac.compare_digest(now[name].encode(),values[name].encode()) for name in required)
  except (ValueError,PermissionError,OSError):return False
 yield MCPBoundCredentials(values,current)
