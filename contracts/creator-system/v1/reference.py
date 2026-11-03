"""Isolated contract validator; never reads credentials or imports product code."""
from pathlib import Path
import hashlib
import json
import re
import stat
import unicodedata
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parent
class ContractError(ValueError):pass
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def strict_json(raw):
 def pairs(items):
  value={}
  for k,v in items:
   if k in value:raise ContractError('duplicate_json_key')
   value[k]=v
  return value
 def bad(_):raise ContractError('invalid_json_number')
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)
def validate(name,value):
 errors=list(Draft202012Validator(json.loads((ROOT/name).read_text())).iter_errors(value))
 if errors:raise ContractError('invalid_'+name.split('.')[0])
 return value
def safe_schema(schema):
 if not isinstance(schema,dict):raise ContractError('invalid_schema')
 try:Draft202012Validator.check_schema(schema)
 except Exception:raise ContractError('invalid_schema')
 count=[0]
 def walk(value,ancestors,depth):
  count[0]+=1
  if depth>32 or count[0]>4096:raise ContractError('schema_complexity')
  if isinstance(value,list):
   for child in value:walk(child,ancestors,depth+1)
  if not isinstance(value,dict):return
  if id(value) in ancestors:raise ContractError('recursive_schema')
  ancestors=ancestors|{id(value)}
  if any(key in value for key in ('$id','$dynamicRef','$dynamicAnchor')):raise ContractError('external_schema_reference')
  if '$ref' in value:
   ref=value['$ref']
   if not isinstance(ref,str) or (ref!='#' and not ref.startswith('#/')):raise ContractError('external_schema_reference')
   target=schema
   try:
    for part in ref[2:].split('/') if ref!='#' else []:target=target[part.replace('~1','/').replace('~0','~')]
   except (KeyError,TypeError):raise ContractError('missing_schema_reference')
   walk(target,ancestors,depth+1)
  for key,child in value.items():
   if key!='$ref':walk(child,ancestors,depth+1)
 walk(schema,set(),0)
 return schema

def validate_connection(descriptor):
 validate('connection.schema.json',descriptor)
 for endpoint in descriptor['endpoints'].values():
  value=endpoint['path']
  if '..' in value.split('/') or '//' in value:raise ContractError('invalid_endpoint_path')
  if endpoint['effect']=='read' and endpoint['method']!='GET':raise ContractError('invalid_effect')
  safe_schema(endpoint['input']);safe_schema(endpoint['output'])
  for query in endpoint['query'].values():safe_schema(query)
 return descriptor

def relative(path):
 if not isinstance(path,str) or len(path)>240 or unicodedata.normalize('NFC',path)!=path or path.endswith('/') or any(x in ('','.','..') for x in path.split('/')) or re.search(r'[\\\x00-\x1f:%?#]',path):raise ContractError('invalid_path')
 return path

def portable_names(names):
 seen=set()
 for name in names:
  relative(name)
  if name.casefold() in seen:raise ContractError('path_collision')
  seen.add(name.casefold())

def freeze(folder):
 root=Path(folder)
 if root.is_symlink():raise ContractError('invalid_root')
 files={};casefold=set();total=0
 for p in sorted(root.rglob('*')):
  mode=p.lstat().st_mode
  if stat.S_ISLNK(mode):raise ContractError('invalid_path')
  if stat.S_ISDIR(mode):continue
  if not stat.S_ISREG(mode) or p.stat().st_nlink!=1:raise ContractError('invalid_path')
  name=relative(p.relative_to(root).as_posix())
  if name.casefold() in casefold:raise ContractError('path_collision')
  casefold.add(name.casefold())
  if any(part in ('.env','auth.json','token.json','node_modules','.git') for part in name.split('/')):raise ContractError('forbidden_asset')
  data=p.read_bytes();total+=len(data)
  if len(files)>=500 or total>32*1024*1024:raise ContractError('asset_limit')
  files[name]=data
 try:project=validate('project.schema.json',strict_json(files['project.json']))
 except KeyError:raise ContractError('missing_asset')
 refs=[*project['entrypoints']['employees'],*project['entrypoints']['pipelines'],project['entrypoints']['ui'],project['dependency_lock'],*project['data_models'],*project['migrations'],*project['connections'],*project['source_access']['public_files']]
 keys=[]
 for op in project['operations']:
  keys.append(op['key']);refs.extend(op[k] for k in ('input','output','handler'))
 if len(keys)!=len(set(keys)):raise ContractError('duplicate_operation')
 for ref in refs:
  if relative(ref) not in files:raise ContractError('missing_asset')

 for file in project['connections']:
  descriptor=validate_connection(strict_json(files[file]))
  for endpoint in descriptor['endpoints'].values():
   value=endpoint['path']
   if '..' in value.split('/') or '//' in value:raise ContractError('invalid_endpoint_path')
   if endpoint['effect']=='read' and endpoint['method']!='GET':raise ContractError('invalid_effect')
 for file in project['entrypoints']['employees']:
  e=validate('employee-source.schema.json',strict_json(files[file]))
  if e['soul_file'] not in files:raise ContractError('missing_asset')
  for directory in e['skill_dirs']:
   if directory+'/SKILL.md' not in files:raise ContractError('missing_asset')
 for file in project['entrypoints']['pipelines']:
  pipeline=validate('pipeline-source.schema.json',strict_json(files[file]))
  for step in pipeline['steps']:
   if step['employee'] not in project['entrypoints']['employees'] or step['operation'] not in keys:raise ContractError('invalid_pipeline_reference')
 lock=validate('dependencies.schema.json',strict_json(files[project['dependency_lock']]))
 if lock['root']!=project['key']:raise ContractError('dependency_root_mismatch')
 deps={d['key']:d for d in lock['dependencies']}
 if len(deps)!=len(lock['dependencies']):raise ContractError('duplicate_dependency')
 if project['key'] in deps:raise ContractError('dependency_cycle')
 def visit(key,ancestors):
  if key in ancestors:raise ContractError('dependency_cycle')
  if key not in deps:raise ContractError('missing_dependency')
  for child in deps[key]['requires']:visit(child,ancestors|{key})
 for key in deps:visit(key,set())
 entries=[{'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()]
 # Generated artifacts, SDK, helper and dependency blobs are frozen by the
 # separate signed release envelope; the editable tree never self-hashes.
 return {'schema':'runteams.source-tree/1','files':entries,'sha256':hashlib.sha256(canonical(entries)).hexdigest()}
