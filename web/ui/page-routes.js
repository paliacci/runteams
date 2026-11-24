/* Public URLs use cloud-issued identities. Domain state continues to use its
 * original keys. This registry is disposable and never grants access. */
(function(global){
'use strict';
const contract=global.RunTeamsPageRouteContract;
if(!contract)throw new Error('页面路由配置没有载入。');
const byId=new Map(),byPublic=new Map(),deviceIds=new Map(),devicePublic=new Map();
let scope='',deviceScope='',loaded=false;
const failure=()=>Object.assign(new Error(global.RunTeamsLocale?.t('pageRoute.unavailable',{},'链接无效，或当前账户无法访问这个内容。')??'链接无效，或当前账户无法访问这个内容。'),{code:'page_route_unavailable'});
const missing=()=>Object.assign(new Error(global.RunTeamsLocale?.t('pageRoute.unloaded',{},'页面链接尚未载入，请重试。')??'页面链接尚未载入，请重试。'),{code:'page_ids_missing'});
const devicePattern=resource=>resource==='chats'?contract.device_page_id_pattern:contract.device_resource_id_pattern;
const publicPattern=resource=>['chats','workflows','artifacts','documents'].includes(resource)?'(?:'+devicePattern(resource)+'|'+contract.id_pattern+')':contract.id_pattern;
const key=(resource,id)=>resource+':'+String(id);
const url=value=>new URL(value,global.location.origin);
// Only the optional local entry injects this metadata. Standalone builds keep
// their original root URLs and require neither the website nor this mount.
const mountValue=global.document?.querySelector?.('meta[name="runteams-app-base"]')?.content||'';
const base=/^\/[a-z][a-z0-9-]*$/.test(mountValue)?mountValue:'';
function unmount(value){
 const target=url(value);if(target.origin!==global.location.origin)throw failure();
 if(base&&(target.pathname===base||target.pathname.startsWith(base+'/')))target.pathname=target.pathname.slice(base.length)||'/';
 return target.pathname+target.search+target.hash;
}
function mount(value){
 const target=url(unmount(value));
 return base+(target.pathname==='/'?'/':target.pathname)+target.search+target.hash;
}
function match(value,side){
 const path=value.replace(/\/+$/,'')||'/';
 for(const route of contract.routes){
  if(route.exclude&&new RegExp(route.exclude).test(path))continue;
  const names=[];
  const pattern=route[side].replace(/\{(\w+)\}/g,(_,name)=>{
   names.push(name);const resource=route.refs?.[name];
   return '('+(resource?(side==='public'?publicPattern(resource):route.internal_keys?.[name]||'[1-9][0-9]*'):route.keys[name])+')';
  });
  const found=path.match(new RegExp('^'+pattern+'$'));
  if(found)return {route,params:Object.fromEntries(names.map((name,i)=>[name,found[i+1]]))};
 }
 return null;
}
function row(resource,id,side){
 const found=(side==='public'?devicePublic:deviceIds).get(key(resource,id))||(side==='public'?byPublic:byId).get(key(resource,id));
 if(!found)throw loaded?failure():missing();
 return found;
}
function fill(pattern,params){return pattern.replace(/\{(\w+)\}/g,(_,name)=>{if(!params[name])throw failure();return params[name];});}
function queryRefs(target,side){
 for(const [name,resource] of Object.entries(contract.query_refs)){
  if(!target.searchParams.has(name))continue;
  const value=target.searchParams.get(name);
  if(name==='chat'&&value==='new')continue;
  const item=row(resource,value,side);
  target.searchParams.set(name,side==='public'?item.id:item.public_id);
 }
 if(target.searchParams.has('source')){
  const value=target.searchParams.get('source').split(':'),resource={employee:'employees'}[value[0]];
  if(value.length!==2||!resource)throw failure();
  const item=row(resource,value[1],side);
  target.searchParams.set('source',value[0]+':'+(side==='public'?item.id:item.public_id));
 }
}
function documentRevision(query){
 const values=query.getAll('revision');
 if(!values.length)return 0;
 const id=Number(values[0]);
 if(values.length!==1||!/^[1-9][0-9]*$/.test(values[0])||!Number.isSafeInteger(id))throw failure();
 return id;
}
function normalizeInternal(target){
 if(target.pathname==='/docs'&&target.searchParams.has('document')){
  target.pathname='/docs/'+target.searchParams.get('document');target.searchParams.delete('document');
 }
 return target;
}
function invalidChatQuery(found,target){
 const chat=target.searchParams.get('chat');
 return chat&&chat!=='new'&&['chat-new','bot','employee-work','source-pipeline'].includes(found.route.kind);
}
function toInternal(value){
 const target=url(unmount(value));if(target.origin!==global.location.origin)throw failure();
 const found=match(target.pathname,'public');if(!found||invalidChatQuery(found,target))throw failure();
 const params={...found.params};
 for(const [name,resource] of Object.entries(found.route.refs||{})){
  if(!params[name])continue;
  const item=row(resource,params[name],'public');
  if(resource==='chats'&&found.route.kind==='chat'&&item.owner_path!==undefined&&chatOwner(params)!==item.owner_path)throw failure();
  params[name]=item.id;
 }
 target.pathname=fill(found.route.internal,params);queryRefs(target,'public');
 if(found.route.kind==='docs-detail'){
  target.pathname='/docs';target.searchParams.set('document',params.document);
 }
 return target;
}
function toPublic(value){
 const target=normalizeInternal(url(unmount(value)));if(target.origin!==global.location.origin)throw failure();
 const found=match(target.pathname,'internal');
 if(!found){
  // A caller may already hold a public URL (workspace tabs/back navigation).
  toInternal(target.href);return mount(target.pathname+target.search+target.hash);
 }
 if(invalidChatQuery(found,target))throw failure();
 // Static/shared path shapes also accept an already canonical query.
 const original=target.pathname+target.search+target.hash;
 try{toInternal(original);return mount(original);}catch(error){if(!['page_route_unavailable','page_ids_missing'].includes(error.code))throw error;}
 const params={...found.params};
 for(const [name,resource] of Object.entries(found.route.refs||{})){
  if(!params[name])continue;
  const item=row(resource,params[name],'internal');
  if(resource==='chats'&&chatOwner(params)&&chatOwner(params)!==item.owner_path)throw failure();
  params[name]=item.public_id;
 }
 const owner=found.route.kind==='chat'&&!chatOwner(params)?row('chats',found.params.chat,'internal').owner_path:'';
 target.pathname=(owner||'')+fill(found.route.public,params);queryRefs(target,'internal');
 return mount(target.pathname+target.search+target.hash);
}
function chatOwner(params){
 if(params.employeePage)return '/employees/'+params.employeePage;
 if(params.pipeline)return '/pipelines/'+params.pipeline;
 return '';
}
function preview(value){
 const target=url(unmount(value)),found=match(target.pathname,'public');if(!found||invalidChatQuery(found,target))return {kind:'invalid'};
 const kind=found.route.kind,q=target.searchParams;
 const contributed=global.RunTeamsHost.routes.preview(found,target);if(contributed!==null)return contributed;
 if(kind==='chat')return {kind,ownerPath:chatOwner(found.params),pending:true};
 if(kind==='employee-work')return {kind,pageId:found.params.employeePage};
 if(kind==='source-pipeline')return {kind,pageId:found.params.pipeline};
 if(kind==='chat-new')return {kind,...(q.get('purpose')==='create-employee'?{purpose:'create-employee'}:{})};
 if(kind.startsWith('bot'))return {kind:'bot',settings:kind==='bot-settings',chatId:q.has('chat')&&q.get('chat')!=='new'?1:'new',pending:true};
 if(kind==='docs-detail')return {kind:'docs',documentId:1,pending:true};
 return {kind,pending:true};
}
function resolve(value){
 if(!loaded)return preview(value);
 const target=normalizeInternal(toInternal(value)),found=match(target.pathname,'internal');
 if(!found)throw failure();
 const kind=found.route.kind,p=found.params,q=target.searchParams;
 const chatId=q.get('chat')&&q.get('chat')!=='new'?Number(q.get('chat')):'new';
 if(kind==='bot'||kind==='bot-settings'){
  const reference=row('employees',p.employee,'internal').reference;
  return {kind:'bot',employeeId:Number(p.employee),settings:kind==='bot-settings',chatId,...(reference?{reference}:{})};
 }
 if(kind==='chat')return {kind,id:Number(p.chat),ownerPath:chatOwner(p)};
 if(kind==='chat-new')return {kind,...(q.get('purpose')==='create-employee'?{purpose:'create-employee'}:{})};
 if(kind==='employee-work')return {kind,pageId:p.employeePage};
 if(kind==='source-pipeline')return {kind,pageId:p.pipeline};
 if(kind==='docs'||kind==='docs-detail'){
  const revisionId=documentRevision(q);
  return {kind:'docs',documentId:Number(p.document)||0,anchor:decodeURIComponent(target.hash.slice(1)),...(revisionId?{revisionId}:{})};
 }
 const contributed=global.RunTeamsHost.routes.resolve(found,target);if(contributed!==null)return contributed;
 if(kind==='design-system')return {kind,theme:['light','dark','system'].includes(q.get('theme'))?q.get('theme'):'system'};
 return {kind};
}
function install(value,nextScope){
 if(value?.version!==1||!Array.isArray(value.items)||!nextScope)throw failure();
 const resources=value.resources;
 if(resources!==undefined&&(!Array.isArray(resources)||!resources.length||new Set(resources).size!==resources.length||resources.some(resource=>!['employees'].includes(resource))))throw failure();
 const ids=new Map(),publics=new Map();
 for(const item of value.items){
  if(!item||typeof item.resource!=='string'||resources&&!resources.includes(item.resource)||typeof item.id!=='string'||!new RegExp('^'+contract.id_pattern+'$').test(item.public_id)||ids.has(key(item.resource,item.id))||publics.has(key(item.resource,item.public_id)))throw failure();
  ids.set(key(item.resource,item.id),item);publics.set(key(item.resource,item.public_id),item);
 }
 // A scoped refresh replaces only the requested link index. Links are not
 // access grants; account/workspace changes still discard the entire index.
 if(resources&&nextScope===scope)for(const item of byId.values())if(!resources.includes(item.resource)){
  ids.set(key(item.resource,item.id),item);publics.set(key(item.resource,item.public_id),item);
 }
 byId.clear();byPublic.clear();ids.forEach((v,k)=>byId.set(k,v));publics.forEach((v,k)=>byPublic.set(k,v));scope=nextScope;loaded=true;
}

function installDevice(items,nextScope){
 if(!Array.isArray(items))throw failure();
 if(nextScope&&nextScope!==deviceScope){deviceIds.clear();devicePublic.clear();deviceScope=nextScope;}
 const ids=new Map(),publics=new Map();
 for(const item of items){
  if(!['chats','workflows','artifacts','documents'].includes(item?.resource)||!/^[1-9][0-9]*$/.test(item.id)||!new RegExp('^'+devicePattern(item.resource)+'$').test(item.public_id)||ids.has(key(item.resource,item.id))||publics.has(key(item.resource,item.public_id)))throw failure();
  const id=key(item.resource,item.id),previous=deviceIds.get(id);
  const registered=previous?.public_id===item.public_id?{...previous,...item}:item;
  ids.set(id,registered);publics.set(key(item.resource,item.public_id),registered);
 }
 ids.forEach((v,k)=>deviceIds.set(k,v));publics.forEach((v,k)=>devicePublic.set(k,v));loaded=true;
}
function isDeviceRoute(value){
 const target=url(unmount(value)),found=match(target.pathname,'public');
 if(found?.route.kind==='docs-detail'){
  try{documentRevision(target.searchParams);}catch(error){return false;}
  return devicePublic.has(key('documents',found.params.document))&&[...target.searchParams].every(([name,id])=>name==='revision'||name==='chat'&&devicePublic.has(key('chats',id)));
 }
 if(found?.route.kind==='chat')return devicePublic.has(key('chats',found.params.chat));
 return false;
}
function clear(){byId.clear();byPublic.clear();deviceIds.clear();devicePublic.clear();scope='';deviceScope='';loaded=false;}
global.addEventListener?.('runteams:business-scope-changed',clear);
global.RunTeamsRoutes={toInternal,toPublic,preview,resolve,install,installDevice,isDeviceRoute,documentRevision,clear,mount,unmount,base,get ready(){return loaded;},get scope(){return scope;}};
if(base)for(const event of ['click','auxclick','contextmenu'])global.document?.addEventListener?.(event,e=>{
 const anchor=e.target.closest?.('a[href]');if(!anchor)return;
 try{const target=url(anchor.href);if(target.origin===global.location.origin&&match(target.pathname,'public'))anchor.href=mount(target.href);}catch(error){}
},true);
})(window);
