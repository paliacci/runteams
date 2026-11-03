"""Portable typed work facts only. No service or account authority is granted."""
import re,uuid
from runteams_core.authoring.creator_contracts import digest
from runteams_core.foundation.identity import local_connection_identity as local
SCHEMA='runteams.official-mcp-connection-binding/1'
EXTRA={'reference','installation_id','asset_release_id','asset_sha256','account_id','deployment_id','storage_namespace'}
def valid_binding(value):
 if isinstance(value,dict) and value.get('schema')==local.SCHEMA:return local.valid_binding(value)
 if not isinstance(value,dict) or value.get('schema')!=SCHEMA:return False
 contextual=isinstance(value.get('reference'),dict) and value['reference'].get('schema')!='runteams.business-reference/v1'
 if set(value)!=(local.FIELDS|EXTRA|({'resource_binding'} if contextual else set())):return False
 try:
  if contextual:
   ref=value['reference'];kind=value['owner_kind']
   if ref.get('schema')=='runteams.acquired-employee-reference/1':
    from runteams_core.employees.employee_references import checked_source_reference
    checked_source_reference(ref,value)
    if kind!='employee':return False
   elif ref.get('schema') in ('runteams.rented-employee-reference/1','runteams.rented-pipeline-reference/1'):
    from runteams_core.assets.rented_references import checked
    checked(ref,value,employee=kind=='employee')
   else:return False
   resource=value['resource_binding']
   if (set(resource)!={'schema','scope','chat_id','chat_identity','installation_id','release_id','release_digest','source_path','reference','owner_kind','work'} or resource['schema']!='runteams.mcp-sdk-resource-binding/1' or resource['reference']!=ref or resource['owner_kind']!=kind or resource['chat_identity']!=value['work_id'] or type(resource['chat_id']) is not int or resource['chat_id']<=0):return False
   if any(resource[k]!=value[v] for k,v in (('installation_id','installation_id'),('release_id','asset_release_id'),('release_digest','asset_sha256'))):return False
   if resource['source_path']!=ref['employee_source' if kind=='employee' else 'pipeline_source']:return False
   if any(resource['scope'].get(k)!=value[k] for k in ('account_id','deployment_id','storage_namespace')):return False
   from runteams_core.employees.mcp.employee_mcp import WorkBinding, PipelineWorkBinding
   work=WorkBinding(**resource['work']) if kind=='employee' else PipelineWorkBinding(**resource['work'])
   if work.work_id!=value['work_id'] or work.release_digest!=value['release_digest']:return False
   if kind=='pipeline' and work.pipeline_id!=digest(ref):return False
  else:
   from runteams_core.assets.asset_references import BusinessReference
   ref=BusinessReference.from_json(value['reference'])
   if ref.resource!='employees' or ref.deployment_id!=value['deployment_id'] or ref.workspace_id!=value['account_id'] or value['owner_kind']!='employee':return False
  if value['source_id']!=digest(value['reference']) or value['owner_sha256']!=digest(value['reference']):return False
  if not isinstance(value['asset_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['asset_sha256']) or value['source_revision']!='r-'+value['asset_sha256']:return False
  for k in ('installation_id','asset_release_id','account_id'): 
   if str(uuid.UUID(value[k]))!=value[k]:return False
  if not isinstance(value['storage_namespace'],str) or not value['storage_namespace']:return False
  projected={k:value[k] for k in local.FIELDS};projected['schema']=local.SCHEMA
  return local.valid_binding(projected)
 except (TypeError,ValueError,KeyError,AttributeError,PermissionError):return False

def for_authority(binding):
 if binding.get('schema')==local.SCHEMA:return local.for_authority(binding)
 if not valid_binding(binding):raise ValueError('官方MCP工作身份无效。')
 # Official facts are scoped to one actual work, never portable grants.
 return dict(binding)

def matches_scope(binding,scope):
 if not valid_binding(binding) or binding['library_id']!=scope.get('library_id'):return False
 if binding['schema']==local.SCHEMA:return True
 return scope.get('storage_kind')!='local' and all(binding[k]==scope.get(k) for k in ('account_id','deployment_id','storage_namespace'))
