"""Same-name selections over the existing host vault and MCP enablement.

A saved user selection is not program enablement. Original private MCP trust
still authorizes each exact release; neither portable records nor key presence
starts code. Plaintext remains in app_secrets and the declared child env only.
"""
from contextlib import contextmanager
import hmac
import base64
import binascii
import re
from runteams_core.employees.mcp.employee_mcp_package import credential_key
from runteams_core.storage import device_data
from runteams_core.foundation.identity.work_identity import schedule_binding

SCHEMA='runteams.configuration-credential/1'

def supports(field):
 binding=field.get('binding',{});key=binding.get('key')
 return (field.get('type')=='secret' and binding.get('provider')=='native_credential' and credential_key(key))

def _values(keys):
 from runteams_core.configuration.credentials import app_secrets
 values=app_secrets.resolve(keys)
 if set(values)!=set(keys) or any(not isinstance(v,str) or not 1<=len(v.encode('utf-8'))<=8192 or '\0' in v for v in values.values()):
  raise ValueError('请先在本机保存此项所需的凭据。')
 return values

def available(field):
 if not supports(field):return False
 try:_values((field['binding']['key'],));return True
 except (ValueError,OSError):return False

def filename(field, legacy=''):
 if not field.get('file_input'):return ''
 from runteams_core.configuration.credentials import app_secrets
 name=app_secrets.file_name(field['binding']['key'])
 return legacy if name is None else name

def verify_record(field,value,scope):
 if (not supports(field) or not isinstance(value,dict) or set(value)!={'schema','owner','key'}
   or value['schema']!=SCHEMA or value['key']!=field['binding']['key']):raise ValueError('请选择此项声明的同名本机凭据。')
 if value['owner']!=schedule_binding(scope):raise PermissionError('凭据选择不属于当前资料库。')

def reveal_text(field,selection,scope):
 if field.get('file_input'):raise ValueError('文件凭据不能显示明文。')
 verify_record(field,selection,scope)
 key=field['binding']['key']
 return _values((key,))[key]

def select(field,selection):
 scope=device_data.identity()
 if not supports(field) or not isinstance(selection,dict) or set(selection) not in ({'key'},{'schema','owner','key'}):raise ValueError('请选择此项声明的同名本机凭据。')
 value={'schema':SCHEMA,'owner':schedule_binding(scope),'key':field['binding']['key']}
 if selection.get('key')!=value['key']:raise ValueError('不能将其他名称的凭据绑定到此项。')
 if set(selection)!={'key'}:verify_record(field,selection,scope)
 _values((value['key'],));device_data.check(scope);return value

def file_value(field, value):
 """Decode a bounded credential file, never a resource attachment or path."""
 if not isinstance(value,dict) or set(value)!={'filename','content_base64'}:
  raise ValueError('请选择密钥文件。')
 name=value['filename'];encoded=value['content_base64']
 if (not isinstance(name,str) or not 1<=len(name)<=255 or any(ord(c)<32 for c in name)
     or '/' in name or '\\' in name or not name.lower().endswith(field['file_input']['accept'])
     or not isinstance(encoded,str) or not 1<=len(encoded)<=10924):
  raise ValueError('请选择声明类型的密钥文件，最多8 KB。')
 try:
  raw=base64.b64decode(encoded,validate=True)
  text=raw.decode('utf-8-sig')
 except (ValueError,UnicodeError,binascii.Error):raise ValueError('密钥文件内容无效。') from None
 if not 1<=len(raw)<=8192 or not text.strip() or '\0' in text:
  raise ValueError('密钥文件内容无效，最多8 KB。')
 if field['file_input']['accept']=='.p8':
  match=re.fullmatch(r'\s*-----BEGIN PRIVATE KEY-----\s+([A-Za-z0-9+/=\r\n]+)\s+-----END PRIVATE KEY-----\s*',text)
  try:
   der=base64.b64decode(re.sub(r'\s','',match[1]),validate=True) if match else b''
  except binascii.Error:der=b''
  if len(der)<32 or der[0]!=48:raise ValueError('请选择有效的 .p8 私钥文件。')
 return text,name

def update(field,value):
 filename=None
 if supports(field) and field.get('file_input'):
  value,filename=file_value(field,value)
 if not supports(field) or not isinstance(value,str) or not value.strip() or not 1<=len(value.encode('utf-8'))<=8192 or '\0' in value:
  raise ValueError('请填写有效凭据，最多8192字节。')
 scope=device_data.identity()
 from runteams_core.configuration.credentials import app_secrets
 app_secrets.set_secret(field['binding']['key'],value,filename=filename)
 device_data.check(scope)
 return {'selection':select(field,{'key':field['binding']['key']}),'available':True,**({'filename':filename} if filename else {})}

@contextmanager
def lease(definition,snapshot,required,check):
 from runteams_core.configuration.configuration_schema import fields
 from runteams_core.employees.mcp.employee_mcp import MCPBoundCredentials
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
