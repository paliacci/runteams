"""Immediate, versioned internal documents owned by the bound employee.

Reuses the original document store and owner context. No configurable dataset,
caller-selected owner/path, separate ledger, or deferred proposal is introduced.
"""
import copy
import json
from runteams_core.foundation.contracts import ContractError

INPUT_SCHEMA={'type':'object','additionalProperties':False,'required':['operation','document_key'],
 'properties':{'operation':{'enum':['read','write']},'document_key':{'type':'string','pattern':'^[a-z0-9][a-z0-9._-]{0,119}$'},
 'name':{'type':'string','minLength':1,'maxLength':200},'content':{'type':'string','minLength':1,'maxLength':2000000},
 'base_revision':{'type':'integer','minimum':0}}}


def operate(core,arguments):
 """Caller holds the verified employee document owner and actor scopes."""
 from jsonschema import Draft202012Validator
 from runteams_core.documents import rich_documents
 if next(Draft202012Validator(INPUT_SCHEMA).iter_errors(arguments),None):raise ContractError('内部文档参数无效。')
 if not core._document_employee_owner().get('employee_reference'):raise PermissionError('内部文档必须属于当前员工。')
 key=arguments['document_key'];action=arguments['operation']
 if action=='read' and set(arguments)!={'operation','document_key'}:raise ContractError('读取内部文档只接受文档标识。')
 if action=='write' and (not arguments.get('content','').strip() or 'base_revision' not in arguments):raise ContractError('请先读取文档，并提供内容和 base_revision。')
 with core.repository.definition_lock(),core.repository.connect() as c:
  row=core._find_agent_document(c,key)
  if row and json.loads(row['meta_json']).get('work_report'):
   raise ContractError('工作汇报请使用原汇报入口，不能作为内部台账修改。')
  if not row:
   from runteams_core.employees.employee_references import same
   for trashed in c.execute("SELECT meta_json FROM artifacts WHERE trashed_at IS NOT NULL AND json_extract(meta_json,'$.document_key')=?",(key,)):
    meta=json.loads(trashed['meta_json'])
    if meta.get('employee_reference') and same(meta['employee_reference'],core._document_employee_owner()['employee_reference']):
     raise ContractError('原内部文档已在垃圾箱，请恢复后继续维护。')
  current=core.document_detail(row['id']) if row else None
  if action=='write':
   title=(arguments.get('name') or (current or {}).get('name') or '').strip()
   if not title:raise ContractError('首次创建内部文档需要名称。')
   value=rich_documents.from_markdown(arguments['content']);value['blocks'][0]['id']='internal-document-body'
   if current:
    old=rich_documents.validate(current['content']);value['sources']=old['sources']
    value['blocks'] += [b for b in old['blocks'] if b['type'] in {'dataTable','barChart','jsonData','metric'}]
   result=rich_documents.write(core,name=title,document=value,document_key=key,
    document_id=row['id'] if row else None,base_revision=arguments['base_revision'],author='agent')
   if result.get('conflict'):return result
   current=core.document_detail(result['id'])
  if not current:
   from runteams_core.storage import device_data
   from runteams_core.foundation.contracts import digest
   owner=core._document_employee_owner()['employee_reference']
   with device_data.connect(readonly=True) as seed_connection:
    seed_row=seed_connection.execute('SELECT value FROM device_settings WHERE key=?',('employee-document-seed:'+digest(owner)+':'+key,)).fetchone()
   seed=json.loads(seed_row[0]) if seed_row else {}
   if seed and (seed.get('employee_reference')!=owner or seed.get('document_key')!=key):raise PermissionError('历史文档资料归属未能核对。')
   return {'ok':True,'exists':False,'document_key':key,'revision':0,
           **({'seed_content':seed['content'],'seed_provenance':seed['provenance']} if seed else {})}
  meta=json.loads(c.execute('SELECT meta_json FROM artifacts WHERE id=?',(current['id'],)).fetchone()[0])
  identifier=int(meta.get('revision_of') or current['id'])
  return {'ok':True,'exists':True,'document_id':identifier,'document_key':key,'revision':current['revision'],
   'name':current['name'],'content':rich_documents.narrative(rich_documents.validate(current['content'])),
   'internal_link':'runteams://document/'+str(identifier)}


def employee_call(arguments,context):
 from runteams_core.storage import device_data,product_store
 from runteams_core.foundation.identity.work_identity import principal
 from runteams_core.employees.employee_context import current
 from runteams_core.work.device_work_services import current as work_service
 expected=device_data.identity();host=current()
 if not device_data.personal() or context.get('actor_id')!=principal(expected):raise PermissionError('内部文档不属于当前资料库。')
 if host.resolve(context) is None:raise PermissionError('请在绑定员工的工作对话维护内部文档。')
 session=product_store.get_chat(context['chat_id'])
 if session.get('kind')!='general' or not any(m.get('role')=='user' for m in session.get('messages',[])):
  raise PermissionError('原员工工作请求不存在。')
 work=work_service(channel_resolver=product_store.get_channel)
 with work.repository.audit_context(actor_id=principal(expected),source='agent_tool'),host.document_owner(session):
  work._actor();result=operate(work,copy.deepcopy(arguments));device_data.check(expected);return result
