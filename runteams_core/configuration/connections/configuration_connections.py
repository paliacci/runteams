"""Explicit service selection in existing configuration, never native authority.

Portable records fix the source/owner/service descriptor. Actual service consent,
vault lease and original program enablement remain checked by WorkConnections.
"""
import re
from runteams_core.storage import device_data
from runteams_core.authoring.creator_contracts import compile_source, digest
from runteams_core.configuration.configuration_schema import data_fields
from runteams_core.foundation.identity.work_identity import checked_source_scope, schedule_binding

SCHEMA='runteams.configuration-connection/1'

def supports(field):
 return field.get('type')=='connection' and field.get('binding',{}).get('provider')=='sdk_connection'

def checked_scope(reference,scope):
 if isinstance(reference,dict) and reference.get('schema')=='runteams.business-reference/v1':
  from runteams_core.assets.asset_references import BusinessReference
  value=BusinessReference.from_json(reference)
  if (scope.get('storage_kind')=='local' or value.resource!='employees' or value.deployment_id!=scope.get('deployment_id') or value.workspace_id!=scope.get('account_id')):
   raise PermissionError('员工不属于当前账户或部署。')
 else:checked_source_scope(reference,scope)

def package_asset_binding(package):
 if package.get('reference',{}).get('schema')!='runteams.acquired-employee-reference/1':return None
 return {**package['acquisition'],'employee_source':package['reference']['employee_source']}

def _bundle(reference,revision,definition,asset=None):
 scope=device_data.identity();checked_scope(reference,scope)
 keys={field['binding']['key'] for field in data_fields(definition) if supports(field)} if definition else set()
 if not keys:return {'descriptors':{},'asset_binding':None}
 if reference.get('schema') not in ('runteams.local-employee-reference/1','runteams.local-pipeline-reference/1'):
  from runteams_core.employees.employee_context import current
  return current().connection_assets(reference,revision,definition,asset)
 if not scope.get('library_id') or asset is not None:raise PermissionError('请在原源码资产中选择本机服务。')
 from runteams_core.authoring.source.creator_source_revisions import Revisions, REV
 from runteams_core.authoring.source.creator_local_source import current_store
 if revision!=reference['source_id'] and (not isinstance(revision,str) or not REV.fullmatch(revision)):raise ValueError('连接源码修订无效。')
 # Config source callers already hold the edit lock. Immutable saved bytes are
 # verified by the original revision reader; never reread or follow the head.
 store=current_store(scope['cache_scope']);versions=Revisions(store,reference['source_id'])
 if revision!=versions.identity and revision not in [m['revision'] for m in versions._history()]:raise ValueError('源码基线已变化，请核对原修订。')
 files=versions._files(revision)
 compiled=compile_source(files)
 if keys-set(compiled['connections']):raise ValueError('连接声明与原源码工程不符。')
 device_data.check(scope);return {'descriptors':{key:compiled['connections'][key] for key in sorted(keys)},'asset_binding':None}

def descriptors(reference,revision,definition):
 return _bundle(reference,revision,definition)['descriptors']

def record(field,reference,revision,descriptor,scope,asset=None):
 return {'schema':SCHEMA,'owner':schedule_binding(scope),'reference_sha256':digest(reference),
  'source_revision':revision,'connection':field['binding']['key'],'descriptor_sha256':digest(descriptor),
  'origin':descriptor['origin'],'scopes':sorted(descriptor['oauth']['scopes']),**({'asset_binding':asset} if asset is not None else {})}

def options(reference,revision,definition,asset=None):
 bundle=_bundle(reference,revision,definition,asset);declared=bundle['descriptors'];scope=device_data.identity()
 return {f['key']:record(f,reference,revision,declared[f['binding']['key']],scope,bundle['asset_binding']) for f in data_fields(definition) if supports(f)}

def verify_record(field,value,scope,reference,revision):
 if (not supports(field) or not isinstance(value,dict) or set(value)!=({'schema','owner','reference_sha256','source_revision','connection','descriptor_sha256','origin','scopes'}|({'asset_binding'} if reference.get('schema') not in ('runteams.local-employee-reference/1','runteams.local-pipeline-reference/1') else set()))
   or value.get('schema')!=SCHEMA or value['connection']!=field['binding']['key'] or value['reference_sha256']!=digest(reference)
   or value['source_revision']!=revision):raise ValueError('连接选择与原资产版本不符。')
 checked_scope(reference,scope)
 if 'asset_binding' in value:verify_asset_binding(value['asset_binding'],reference)
 if value['owner']!=schedule_binding(scope):raise PermissionError('服务选择不属于原资料库。')
 if (not isinstance(value['descriptor_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['descriptor_sha256'])
   or not isinstance(value['origin'],str) or not value['origin'].startswith('https://')
   or not isinstance(value['scopes'],list) or any(not isinstance(x,str) for x in value['scopes'])
   or value['scopes']!=sorted(set(value['scopes']))):raise ValueError('原连接记录无效。')

def verify_asset_binding(value,reference):
 from runteams_core.foundation.identity.resource_ids import resource_id
 from runteams_core.authoring.creator_contracts import relative
 path='pipeline_source' if reference.get('schema')=='runteams.rented-pipeline-reference/1' else 'employee_source'
 if (not isinstance(value,dict) or set(value)-{'rental_source_id'}!={'installation_id','release_id',path}):raise ValueError('原签名资产绑定无效。')
 resource_id(value['installation_id']);resource_id(value['release_id']);relative(value[path])
 if path in reference and value[path]!=reference[path]:raise PermissionError('配置不属于原签名资产入口。')
 if 'rental_source_id' in value and (not isinstance(value['rental_source_id'],str) or not re.fullmatch('[a-f0-9]{64}',value['rental_source_id'])):raise ValueError('原租用资产绑定无效。')
 if reference.get('schema')=='runteams.acquired-employee-reference/1':
  from runteams_core.employees.employee_acquisition_refs import source_id
  if reference['source_id']!=source_id(value):raise PermissionError('配置不属于原取得资产。')

def select(field,value,reference,revision,asset=None):
 if not supports(field):raise ValueError('此项未声明本机服务。')
 if not isinstance(value,dict) or value.get('connection')!=field['binding']['key']:raise ValueError('请选择此项声明的服务。')
 if asset is not None and value.get('asset_binding',asset)!=asset:raise PermissionError('配置的签名资产绑定已变化。')
 expected=options(reference,revision,{'groups':[{'fields':[field]}]},asset or value.get('asset_binding'))[field['key']]
 if set(value)=={'connection'}:return expected
 verify_record(field,value,device_data.identity(),reference,revision)
 if value!=expected:raise ValueError('服务地址或授权范围已变化，请重新选择。')
 return expected
