/* Trusted employee settings. Definitions/values come from the local platform API. */
(()=>{
'use strict';
let active=null,painting=false;
const sessions=new Map();
const scope=()=>workspaceAccountCacheToken();
const deviceScope=()=>S.localLibrary?.cache_scope||S.account?.device_data_scope;
const owned=s=>s&&s.scope===scope()&&s.deviceScope===deviceScope()&&sessions.get(s.cacheKey)===s&&(!s.entry.chat_id||workTarget()?.key===s.entry.key);
const current=()=>owned(active)&&S.sel?.type==='employee-configuration'&&S.sel.id===active.entry.key?active:null;
const publicFields=()=>RunTeamsConfigurationFields.create({icon:ICON,singleSelect:csel});
const rows=s=>(s.data?.definition.groups||[]).flatMap(g=>g.fields);
const ordinary=s=>rows(s).filter(f=>!['resource','connection','runtime','secret'].includes(f.type));
const storageKey=s=>'runteams.employee.configuration.'+s.cacheKey;
const sourceTarget=s=>s.entry.source;
const url=s=>s.entry.chat_id?'/api/chat/'+s.entry.chat_id+'/employee-configuration':sourceTarget(s)?'/api/creator-source/drafts/'+s.entry.source.id+'/configuration':'/api/device/employees/'+Number(s.entry.work?.id||s.entry.asset?.id)+'/configuration';
function workTarget(panel=S.conversationPanel){
 const binding=panel?.employee_binding,reference=binding?.reference;
 if(panel!==S.conversationPanel||panel?.kind!=='general'||panel.loading||panel.error||panel.employee_error||panel.debug_preview||!Number.isSafeInteger(panel.id)||panel.id<=0||panel.context?.pipeline_work||panel.context?.source_pipeline_workspace)return null;
 if(binding?.schema!=='runteams.bound-employee/v1'||!['runteams.acquired-employee-reference/1','runteams.rented-employee-reference/1'].includes(reference?.schema)||!/^r-[a-f0-9]{64}$/.test(binding.source_revision||''))return null;
 const owner=window.RunTeamsEmployeeWindows?.identity(panel,S.account,S.activeOrganization,null,S.localLibrary);
 if(!owner)return null;
 return {key:JSON.stringify(['work-settings',panel.id,owner.key,binding.source_revision]),chat_id:panel.id,reference:structuredClone(owner.reference),definition_revision:binding.source_revision,record:{name:binding.name,avatar:binding.avatar}};
}
function persist(s){if(!owned(s))return;try{if(s.draft||s.pending||s.resourcePending)RunTeamsBusinessStorage.setItem(storageKey(s),JSON.stringify({draft:s.draft,bindings:s.bindings,pending:s.pending,resourcePending:s.resourcePending,base:s.data}));else RunTeamsBusinessStorage.removeItem(storageKey(s));}catch(error){s.error='输入仍保留在此页面，关闭前请保存。';}}
function capture(){const s=current(),form=document.getElementById('employee_configuration_form');if(painting||!s?.data||!form||s.saving||s.pending)return;
 const values=publicFields().collect(ordinary(s),form,s.draft||s.data.values);
 for(const f of ordinary(s))if(!f.required&&values[f.key]===''&&['number','select','date'].includes(f.type))values[f.key]=null;
 for(const f of ordinary(s))if(!Object.hasOwn(s.data.values,f.key)&&(values[f.key]===''||values[f.key]===null))delete values[f.key];
 s.draft=JSON.stringify(values)!==JSON.stringify(s.data.values)||JSON.stringify(s.bindings)!==JSON.stringify(s.data.bindings||{})?values:null;
 persist(s);
}
function paint(s=active){if(current()!==s)return;const previous=painting;painting=true;try{render();}finally{painting=previous;}}
function accept(s,value){
 if(value?.schema!=='runteams.employee-configuration-state/1'||!Number.isInteger(value.revision)||!value.definition||!Array.isArray(value.definition.groups)||!value.values||!value.states||typeof value.definition_sha256!=='string')throw Error('配置回执未能完整核对。');
 if(s.entry.chat_id&&(RunTeamsEmployeeDirectory.referenceKey(s.entry.reference)!==RunTeamsEmployeeDirectory.referenceKey(value.reference)||s.entry.definition_revision!==value.definition_revision))throw Error('工作引用已变化，请重新打开设置核对。');
 if(s.data&&JSON.stringify(s.data.reference)!==JSON.stringify(value.reference))throw Error('员工配置的归属已改变。');
 s.data=value;s.bindings=structuredClone(value.bindings||{});
}
async function request(s,method='GET',body=null,receipt=false){
 if(!owned(s))throw Error('账户或员工已改变。');
 if(s.entry.pipeline_reference)return RunTeamsSourcePipelinePanels.configurationRequest(s,method,body,receipt);
 const query=new URLSearchParams();if(sourceTarget(s)&&method==='GET')query.set('employee_source',s.entry.source.path);
 if(receipt)query.set('operation_id',s.pending.operation_id);
 const target=url(s)+(query.size?'?'+query:'');
 if(S.localLibrary){
  const value=await api(target,method,body||undefined);if(!owned(s))throw Error('资料库已改变。');
  if(value.error)throw Object.assign(Error(value.error),{status:value.status,code:value.code,fields:value.fields});return value;
 }
 let response,value;try{response=await fetch(target,{method,headers:{'X-RunTeams-Device-Scope':s.deviceScope,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});value=await response.json();}
 catch(error){throw Error(method==='POST'?'暂时未收到保存结果。输入已保留，请核对保存结果。':'暂时无法读取配置，请稍后重试。');}
 if(!owned(s))throw Error('账户已改变。');
 if(!response.ok||value.error)throw Object.assign(Error(value.error||'配置未能保存。'),{status:response.status,code:value.code,fields:value.fields});
 return value;
}
async function read(s=active){if(!owned(s)||s.loading)return;s.loading=true;s.error='';paint(s);
 try{const value=await request(s);if(!owned(s))return;const draft=s.draft,bindings=s.bindings;
  if(draft&&s.data&&(value.revision!==s.data.revision||value.definition_sha256!==s.data.definition_sha256)){s.conflict=value;s.notice='配置已有更新，输入已保留。';}
  else{accept(s,value);if(draft){s.draft=draft;s.bindings=bindings;}s.notice='';}}
 catch(error){if(owned(s))s.error=error.message;}
 finally{if(owned(s)){s.loading=false;paint(s);}}
}
async function open(value){
 if(S.sel?.type==='core-pipeline-parameters'&&requestDetailWorkspaceLeave(()=>open(value)))return;
 capture();const entry=typeof value==='object'?value:RunTeamsEmployeeDirectory.entryFor(value)||RunTeamsEmployeeDirectory.assetEntry(value);
 if(!entry)throw Error('员工目录已变化，请重新打开。');
 const cacheKey=scope()+'|'+deviceScope()+'|'+entry.key;
 let s=sessions.get(cacheKey);
 if(!s){s={cacheKey,entry,scope:scope(),deviceScope:deviceScope(),data:null,bindings:{},draft:null,pending:null,loading:false,saving:false,error:'',errors:{},notice:'',scroll:0};sessions.set(cacheKey,s);
  try{const saved=JSON.parse(RunTeamsBusinessStorage.getItem(storageKey(s))||'null');if(saved?.base?.schema==='runteams.employee-configuration-state/1'){accept(s,saved.base);s.draft=saved.draft;s.bindings=saved.bindings||{};s.pending=saved.pending;s.resourcePending=saved.resourcePending;}}catch(error){s.error='上次输入未能读取，请先核对已保存配置。';}}
 active=s;selectDetailWorkspace({type:'employee-configuration',id:entry.key});paint(s);if(!s.pending)await read(s);
}
function restore(){if(!owned(active))return;selectDetailWorkspace({type:'employee-configuration',id:active.entry.key});paint();}
async function required(error,chatId){
 const panel=String(S.conversationPanel?.id)===String(chatId)?S.conversationPanel:String(S.chatId)===String(chatId)?{id:S.chatId,context:S.chatCfg?.context,kind:'general'}:null;
 if(panel?.context?.pipeline_work||panel?.context?.source_pipeline_workspace){toast('请在流水线设置中完成配置。','info');return true;}
 const entry=panel&&(workTarget(panel)||RunTeamsEmployeeDirectory.forPanel(panel));if(!entry)return false;
 const token=scope(),device=deviceScope();await open(entry);
 const s=current();if(!s||s.entry.key!==entry.key||token!==scope()||device!==deviceScope())return;
 s.errors=error.fields||{};s.notice='补齐以下配置后，请回到对话发送原请求。';paint(s);
 requestAnimationFrame(()=>{if(current()===s){const target=document.querySelector('#employee_configuration_form [aria-invalid="true"]');target?.scrollIntoView({block:'center'});target?.focus();}});
 return true;
}
function close(){capture();if(current()?.entry.pipeline_reference)return RunTeamsSourcePipelinePanels.settings();closeDetailWorkspace();}
function leave(){capture();}
function closeState(){
 capture();const scoped=[...sessions.values()].filter(s=>s.scope===scope()&&s.deviceScope===deviceScope());
 return {pending:scoped.some(s=>!!(s.saving||s.resourceBusy||s.pending||s.resourcePending)),dirty:scoped.some(s=>!!s.draft)};
}
function resources(){const s=current();if(!s||s.entry.pipeline_reference||s.entry.chat_id)return;capture();const back=()=>{if(owned(s)){active=s;restore();}};
 if(s.entry.source)RunTeamsCreatorAuthor.openSource(s.entry.source,{onBack:back});
 else RunTeamsCreatorAuthor.openEmployee(s.entry.asset?.id||s.entry.work?.id,{onBack:back});
}
function visibleValue(s,field){return field.type==='resource'?String(s.bindings[field.key]?.collection_id||s.bindings[field.key]?.grant_id||s.bindings[field.key]?.document_id||''):(s.draft||s.data.values)[field.key];}
const resourceSelectionKey=value=>JSON.stringify([value?.grant_id,value?.identity,value?.document_id,value?.collection_id,value?.model_sha256,Object.entries(value?.owner||{}).sort(([a],[b])=>a.localeCompare(b))]);
function fieldMarkup(s,field){
 const collection=field.type==='resource'&&field.binding.provider==='local_collection';
 const documentInput=field.type==='resource'&&field.binding.provider==='sdk_resource'&&field.binding.resource_kind==='document';
 const collectionInput=field.type==='resource'&&field.binding.provider==='sdk_resource'&&field.binding.resource_kind==='collection';
 const resourceInput=documentInput||collectionInput;
 const supported=resourceInput||field.type==='resource'&&['local_asset','local_collection'].includes(field.binding.provider);
 const credential=field.type==='secret'&&Object.hasOwn(s.data.credential_fields||{},field.key);
 if(credential){
  const locked=s.saving||s.resourceBusy||!!s.pending||s.loading,available=s.data.credential_fields[field.key].available,selected=!!s.bindings[field.key];
  const control=publicFields().field({...field,disabled:locked,note:(field.note?field.note+' ':'')+'仅保存在这台电脑的凭据保险箱，不进入对话、作品或便携备份。'},'',s.errors[field.key]);
  const status=selected?(available?'已选择本机凭据。':'原凭据已不可用，请重新保存或选择。'):(available?'已有同名本机凭据，可以直接选择。':'尚未保存此项所需的本机凭据。');
  return control.slice(0,-6)+'<p class="help">'+status+'</p><div><button type="button" class="btn sm" data-credential-save="'+esc(field.key)+'" '+(locked?'disabled':'')+'>'+(s.credentialBusy===field.key?'正在保存…':'保存凭据并选择')+'</button> '+(available&&!selected?'<button type="button" class="btn sm" data-credential-use="'+esc(field.key)+'" '+(locked?'disabled':'')+'>使用已保存的凭据</button> ':'')+(selected?'<button type="button" class="textbutton" data-credential-clear="'+esc(field.key)+'" '+(locked?'disabled':'')+'>取消选择</button>':'')+'</div></div>';
 }
 const connection=s.data.connection_fields?.[field.key];
 if(field.type==='connection'&&connection){
  const selected=!!s.bindings[field.key],locked=s.saving||s.resourceBusy||!!s.pending||s.loading;
  return publicFields().field({...field,disabled:locked,account:connection.origin,access:connection.origin+'；权限：'+(connection.scopes.join('，')||'无额外范围'),connectionStatus:selected?'已选择服务':'尚未选择服务',connectionAction:selected?'取消选择':'选择服务',note:(field.note?field.note+' ':'')+'保存服务选择后，使用前还需在本机功能中授权。'},selected?'selected':'missing',s.errors[field.key]);
 }
 const runtime=field.type==='runtime'&&s.data.runtime_fields?.includes(field.key);
 if(runtime)return publicFields().field({...field,disabled:s.saving||s.resourceBusy||!!s.pending||s.loading},({configured:'ready',unavailable:'unavailable'})[s.data.states[field.key]]||'unknown',s.errors[field.key]);
 if(['resource','connection','runtime','secret'].includes(field.type)&&!supported){
  const word=s.data.states[field.key]==='configured'?'已配置':'暂时无法配置';
  return '<div class="field configuration-dependency" '+(s.errors[field.key]?'tabindex="-1" aria-invalid="true"':'')+'><div class="resource-heading"><label>'+esc(field.label)+(field.required?'<span class="required-mark" aria-hidden="true">*</span>':'')+'</label></div><p class="resource-summary">'+word+(field.note?' · '+esc(field.note):'')+'</p><p class="help">'+(field.required?'此员工需要创作者完善这项配置。':'此项不影响已具备条件的工作。')+'</p></div>';
 }
 const binding=s.bindings[field.key];
 const locked=s.saving||s.resourceBusy||!!s.pending||s.loading;
 const choices=s.resourceChoices?.[field.key]||[];
 const options=collection||resourceInput?[...choices,...(binding&&!choices.some(c=>(c.collection_id||c.document_id)===(binding.collection_id||binding.document_id))?[binding]:[])].map(c=>[String(c.collection_id||c.document_id),c.name]):binding?[[String(binding.grant_id),binding.name]]:[];
 const pending=s.resourcePending?.field===field.key;
 const selectionPending=binding&&resourceSelectionKey(binding)!==resourceSelectionKey(s.data.bindings?.[field.key]);
 const pickerActions=collection?(s.resourceBusy?'<p role="status">正在读取数据集合…</p>':(!choices.length?'<p>还没有匹配的数据集合，可以新建。</p>':'')+'<label for="collection_name_'+esc(field.key)+'">新集合名称</label><input class="inp" id="collection_name_'+esc(field.key)+'" data-collection-name="'+esc(field.key)+'" maxlength="80" value="'+esc(pending?s.resourcePending.name:s.collectionNames?.[field.key]||field.label)+'" '+(pending?'disabled':'')+'><button type="button" class="btn sm" data-collection-create="'+esc(field.key)+'" '+(locked?'disabled':'')+'>'+(pending?'核对原创建请求':'新建并选择')+'</button>'):resourceInput?(s.resourceBusy?'<p role="status">正在读取资料…</p>':!choices.length?'<p>'+ (documentInput?'还没有可选文档，请先在文档中保存资料。':'还没有可选数据集合。')+'</p>':''):'';
 const f={...field,...(s.entry.pipeline_own?{pickerTitle:'选择流水线可以使用的资料'}:{}),disabled:locked,options:supported?options:field.options,
  ...(supported?{access:collection?(field.binding.access==='read'?'仅查看':'查看、添加和更新'):'仅查看副本',state:selectionPending?'pending':s.data.states[field.key]==='unavailable'?'expired':'',pickerOpen:(collection||resourceInput)&&(s.resourceOpen===field.key||pending),pickerActions}:{})};
 return publicFields().field(f,visibleValue(s,field),s.errors[field.key]);
}
function conflictMarkup(s){if(!s.conflict)return '';
 const current=s.conflict,local=s.draft||s.data.values;
 const readable=(f,v)=>{if(v==null)return '未填写';if(f.type==='checkbox')return v?'是':'否';const label=v=>(f.options||[]).find(o=>o.value===v)?.label??v;return Array.isArray(v)?v.map(label).join('、'):String(label(v));};
 const differences=ordinary(s).filter(f=>JSON.stringify(local[f.key])!==JSON.stringify(current.values[f.key]));
 return '<section class="configuration-conflict" role="alert"><p>配置已有更新，你的输入已保留。</p><details><summary>查看差异</summary><table><thead><tr><th>配置项</th><th>你的输入</th><th>已保存</th></tr></thead><tbody>'+differences.map(f=>'<tr><td>'+esc(f.label)+'</td><td>'+esc(readable(f,local[f.key]))+'</td><td>'+esc(readable(f,current.values[f.key]))+'</td></tr>').join('')+'</tbody></table></details><button type="button" class="btn sm" data-config-merge>以最新配置为基础继续修改</button></section>';
}
function drawer(){const s=current();if(!s)return '';
 const employee=s.data?.employee||s.entry.record||{};
 const introAction=employee.description?.length>60?'<button type="button" class="textbutton configuration-intro-toggle" data-config-intro aria-expanded="'+!!s.introExpanded+'">'+(s.introExpanded?'收起介绍':'展开介绍')+'</button>':'';
 const heading={toolbar:RunTeamsEmployeeDrawerHeader.markup('configuration'),intro:'<section class="workspace-detail-head detail-drawer-intro">'+detailDrawerHeading(employee.name||s.entry.record?.name||'员工设置',employee.description||'','',introAction)+'</section>'};
 let content=s.loading&&!s.data?RunTeamsSkeletons.region('detail'):'';
 if(s.data){
  const scopeNote=s.entry.pipeline_reference?'<p class="configuration-readiness">'+esc('仅用于「'+s.entry.pipeline_name+'」。保存后，暂停并应用更新，再启动流水线。')+'</p>':s.entry.chat_id?'<p class="configuration-readiness">配置按这次工作的员工版本读取。已开始的工作保留原配置。</p>':'';
  content+=scopeNote;
  const status=s.loading?'正在核对配置…':!s.error&&!s.data.ready&&rows(s).length?'还有配置需要处理':'';
  const groups=s.data.definition.groups.filter(group=>group.fields.length);
  content+=(status?'<p class="configuration-readiness" role="status">'+esc(status)+'</p>':'')+'<form id="employee_configuration_form" class="configuration-surface" novalidate>'+groups.map(group=>'<section class="group">'+(groups.length===1&&group.fields.length===1&&group.label===group.fields[0].label?'':'<h3>'+esc(group.label)+'</h3>')+group.fields.map(f=>fieldMarkup(s,f)).join('')+'</section>').join('')+conflictMarkup(s)+'</form>';
 }
 if(s.error)content+='<div class="configuration-error" role="alert">'+esc(s.error)+' <button type="button" class="textbutton" data-config-read>重新读取</button></div>';
 if(s.notice)content+='<p class="configuration-notice" role="status">'+esc(s.notice)+'</p>';
 const footer=s.pending?'<footer class="employee-configuration-save"><span>保存结果待核对</span><button type="button" class="btn pri" data-config-receipt '+(s.saving?'disabled':'')+'>'+(s.retry?'重试原保存':'核对保存结果')+'</button></footer>':s.data?'<footer class="employee-configuration-save" '+(s.draft?'':'hidden')+'><span>有未保存的修改</span><button type="button" class="btn" data-config-cancel '+(s.saving?'disabled':'')+'>取消</button><button type="submit" form="employee_configuration_form" class="btn pri" '+(s.saving?'disabled':'')+'>'+(s.saving?'正在保存…':'保存配置')+'</button></footer>':'';
 requestAnimationFrame(()=>{if(current()!==s)return;decorateHeader();const body=document.querySelector('.employee-configuration-body');if(body)body.scrollTop=s.scroll;});
 return detailDrawerShell({className:'employee-configuration-drawer',header:heading,fixedIntroClass:'detail-drawer-summary employee-configuration-summary'+(s.introExpanded?' is-expanded':''),body:content,bodyClass:'employee-configuration-body',footer,attrs:'aria-label="'+(s.entry.pipeline_own?'流水线配置':'员工设置')+'"'+(s.loading?' aria-busy="true"':'')});
}
function decorateHeader(){const s=current();if(!s)return;const canCreate=!s.entry.pipeline_reference&&(!!s.entry.source||s.entry.asset?.editable===true);
 RunTeamsEmployeeDrawerHeader.mount('configuration',s,{kind:'settings',onCollapse:close,extras:{actions:[...(canCreate?[{id:'resources',label:'资源',onPress:resources}]:[]),...(S.conversationPanel?.identity?.local_mcp&&(RunTeamsEmployeeDirectory.forPanel(S.conversationPanel)?.key===s.entry.key||s.entry.chat_id&&workTarget()?.key===s.entry.key)?[{id:'programs',label:'本机功能',onPress:()=>employeeMCPOpen(null)}]:[])]}});
}
async function save(retry=false){const s=current();if(!s||s.saving||s.resourceBusy||!s.data||s.pending&&!retry)return;capture();
 if(s.resourcePending){s.error='请先核对数据集合的创建结果，再保存配置。';paint(s);return;}
 if(s.conflict){s.error='请先核对最新配置，再保存你的修改。';paint(s);return;}
 if(!s.pending){s.retry=false;s.pending={operation_id:crypto.randomUUID(),expected_revision:s.data.revision,definition_sha256:s.data.definition_sha256,values:structuredClone(s.draft||s.data.values),bindings:Object.fromEntries(Object.entries(s.bindings).map(([key,value])=>[key,value.schema==='runteams.configuration-connection/1'?structuredClone(value):value.schema==='runteams.configuration-credential/1'||Object.keys(value).length===1&&value.key?{key:value.key}:value.document_id?{document_id:value.document_id,owner:structuredClone(value.owner)}:value.collection_id||Object.hasOwn(value,'identity')?structuredClone(value):{grant_id:value.grant_id}])),...(sourceTarget(s)?{employee_source:s.entry.source.path}:{})};persist(s);}
 s.saving=true;s.error='';s.errors={};s.notice='';paint(s);
 try{const result=await request(s,'POST',s.pending);if(!owned(s))return;accept(s,result);s.pending=null;s.retry=false;s.draft=null;s.conflict=null;s.notice='配置已保存。';persist(s);}
 catch(error){if(owned(s)){s.error=error.message;s.errors=error.fields||{};if(error.status>=400&&error.status<500){s.pending=null;if(error.code==='employee_configuration_conflict'){try{s.conflict=await request(s);}catch(readError){s.error=readError.message;}}persist(s);}}}
 finally{if(owned(s)){s.saving=false;paint(s);requestAnimationFrame(()=>{if(current()===s)document.querySelector('#employee_configuration_form [aria-invalid="true"]')?.focus();});}}
}
async function receipt(){const s=current();if(!s?.pending||s.saving)return;if(s.retry)return save(true);s.saving=true;s.error='';paint(s);
 try{const result=await request(s,'GET',null,true);if(!owned(s))return;if(result.state==='confirmed'){
  accept(s,result.result);s.pending=null;s.retry=false;s.draft=null;s.notice='保存结果已确认。';persist(s);
  try{accept(s,await request(s));}catch(error){s.error='原保存已成功，最新配置暂时无法读取。';}
 }else{s.retry=true;s.error='尚未找到保存结果，可以用原请求重试。';}}
 catch(error){if(owned(s))s.error=error.message;}
 finally{if(owned(s)){s.saving=false;paint(s);}}
}
function resourceTarget(s){return s.entry.chat_id?{chat_id:s.entry.chat_id}:s.entry.pipeline_reference?{pipeline_reference:JSON.stringify(s.entry.pipeline_reference),...(!s.entry.pipeline_own?{employee_source:s.entry.source.path}:{})}:s.entry.source?{source_id:s.entry.source.id,employee_source:s.entry.source.path}:{employee_id:Number(s.entry.work?.id||s.entry.asset?.id)};}
async function resourceRequest(s,field,body=null){
 const target='/api/employee-configuration/resources',params={...resourceTarget(s),field};
 if(S.localLibrary)return api(target+(body?'':'?'+new URLSearchParams(params)),body?'POST':'GET',body||undefined);
 let response,value;try{response=await fetch(target+(body?'':'?'+new URLSearchParams(params)),{method:body?'POST':'GET',headers:{'X-RunTeams-Device-Scope':s.deviceScope,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});value=await response.json();}
 catch(error){throw Error(body?'创建结果暂时无法确认，原请求已保留。':'暂时无法读取资料，请稍后重试。');}
 if(!owned(s))throw Error('账户已改变。');if(!response.ok||value.error)throw Error(value.error||'数据集合暂时不可用。');return value;
}
function chooseConnection(key){
 const s=current(),field=s&&rows(s).find(f=>f.key===key),selection=s?.data?.connection_fields?.[key];if(!s||!field||!selection||s.saving||s.resourceBusy||s.pending||s.loading)return;
 capture();if(s.bindings[key])delete s.bindings[key];else s.bindings[key]=structuredClone(selection);
 s.draft=structuredClone(s.draft||s.data.values);s.error='';s.errors={};s.notice='请保存配置后使用。';persist(s);paint(s);
}
function chooseCredential(key,clear=false){
 const s=current(),field=s&&rows(s).find(f=>f.key===key);if(!s||s.saving||s.resourceBusy||s.pending||!field||!Object.hasOwn(s.data.credential_fields||{},key))return;
 capture();if(clear)delete s.bindings[key];else s.bindings[key]={key:field.binding.key};
 s.draft=structuredClone(s.draft||s.data.values);s.error='';s.errors={};s.notice='请保存配置后使用。';persist(s);paint(s);
}
async function saveCredential(key){
 const s=current(),field=s&&rows(s).find(f=>f.key===key);if(!s||s.saving||s.resourceBusy||s.pending||!field||!Object.hasOwn(s.data.credential_fields||{},key))return;
 const input=[...document.querySelectorAll('#employee_configuration_form input[data-key]')].find(n=>n.dataset.key===key),value=input?.value||'';
 if(!value.trim()){s.errors={[key]:'请填写凭据。'};paint(s);return;}
 if(input)input.value='';capture();s.resourceBusy=true;s.credentialBusy=key;s.error='';s.errors={};paint(s);
 try{
  const result=await request(s,'POST',{action:'credential',field:key,definition_sha256:s.data.definition_sha256,value,...(sourceTarget(s)?{employee_source:s.entry.source.path}:{})});
  if(!owned(s))return;if(!result.available||result.selection?.key!==field.binding.key)throw Error('凭据保存结果未能完整核对。');
  s.bindings[key]=structuredClone(result.selection);s.data.credential_fields[key].available=true;s.draft=structuredClone(s.draft||s.data.values);s.notice='凭据已保存并选中，请保存配置后使用。';persist(s);
 }catch(error){if(owned(s)){s.error=error.status>=400&&error.status<500?error.message:'凭据保存结果未能确认。请先重新读取；需要替换时再输入并保存。';s.errors=error.fields||{};}}
 finally{if(owned(s)){s.resourceBusy=false;s.credentialBusy=null;paint(s);}}
}
async function pickResource(key){const s=current();if(!s||s.saving||s.resourceBusy||s.pending)return;capture();
 if(s.resourceOpen===key){s.resourceOpen=null;paint(s);return;}
 s.resourceOpen=key;s.resourceBusy=true;s.error='';paint(s);
 try{const result=await resourceRequest(s,key);if(owned(s)){if(!Array.isArray(result.items))throw Error('资料列表未能完整读取。');s.resourceChoices={...s.resourceChoices,[key]:result.items};}}
 catch(error){if(owned(s))s.error=error.message;}
 finally{if(owned(s)){s.resourceBusy=false;paint(s);}}
}
async function createCollection(key){const s=current();if(!s||s.saving||s.resourceBusy||s.pending)return;capture();
 if(s.resourcePending&&s.resourcePending.field!==key){s.error='请先核对另一项数据集合的创建结果。';paint(s);return;}
 if(!s.resourcePending){const input=document.getElementById('collection_name_'+key),name=input?.value?.trim();if(!name){s.error='请填写新集合名称。';paint(s);return;}
  s.resourcePending={...resourceTarget(s),...(s.entry.pipeline_reference?{pipeline_reference:s.entry.pipeline_reference}:{}),field:key,name,operation_id:crypto.randomUUID(),definition_sha256:s.data.definition_sha256};persist(s);}
 s.resourceBusy=true;s.error='';paint(s);
 try{const result=await resourceRequest(s,key,s.resourcePending);if(!owned(s))return;if(!result.selection?.collection_id)throw Error('创建回执未能完整核对。');
  s.bindings[key]=result.selection;s.draft=structuredClone(s.draft||s.data.values);s.resourcePending=null;s.resourceOpen=null;s.notice='数据集合已创建并选中，请保存配置后使用。';persist(s);
 }catch(error){if(owned(s))s.error=error.message;}
 finally{if(owned(s)){s.resourceBusy=false;paint(s);}}
}
async function pick(key){const s=current(),field=rows(s).find(f=>f.key===key);if(!s||s.saving||s.pending||!field)return;capture();s.saving=true;s.error='';paint(s);
 if(field.binding.provider==='local_collection'||field.binding.provider==='sdk_resource'&&['document','collection'].includes(field.binding.resource_kind)){s.saving=false;return pickResource(key);}
 try{if(!S.appInfo?.native_attachment_picker)throw Error('请在这台电脑的 RunTeams 桌面端选择资料。');
  const picked=await api('/api/local-references/pick','POST',{kind:field.binding.resource_kind});if(!owned(s))return;if(picked.error)throw Error(picked.error);
  const references=picked.references||[];if(picked.pending?.length){const result=await api('/api/local-references/confirm','POST',{tokens:picked.pending.map(p=>p.token)});if(!owned(s))return;if(result.error)throw Error(result.error);references.push(...(result.references||[]));}
  const reference=references.find(r=>r.local_kind===field.binding.resource_kind);if(!reference)return;s.bindings[key]={grant_id:reference.grant_id,name:reference.name,kind:reference.local_kind};s.draft=structuredClone(s.draft||s.data.values);s.notice='';persist(s);
 }catch(error){if(owned(s))s.error=error.message;}
 finally{if(owned(s)){s.saving=false;paint(s);}}
}
function merge(){const s=current();if(!s?.conflict)return;const old=s.data,local=s.draft||old.values,remote=s.conflict;
 const index=new Map(remote.definition.groups.flatMap(g=>g.fields).map(f=>[f.key,f]));
 if(ordinary(s).some(f=>JSON.stringify(local[f.key])!==JSON.stringify(old.values[f.key])&&index.get(f.key)?.type!==f.type)){s.error='字段已变化。原输入仍保留，请先核对创作者的更新。';paint(s);return;}
 const next=structuredClone(remote.values);for(const field of ordinary(s))if(JSON.stringify(local[field.key])!==JSON.stringify(old.values[field.key]))next[field.key]=local[field.key];
 const bindings=structuredClone(remote.bindings||{});for(const key of new Set([...Object.keys(old.bindings||{}),...Object.keys(s.bindings)])){
  if(JSON.stringify(s.bindings[key])!==JSON.stringify(old.bindings?.[key])){if(s.bindings[key])bindings[key]=s.bindings[key];else delete bindings[key];}
 }
 accept(s,remote);s.bindings=bindings;s.draft=next;s.conflict=null;s.errors={};s.error='';persist(s);paint(s);
}
function refreshActions(){const s=current(),footer=document.querySelector('.employee-configuration-save');if(footer&&!s?.pending)footer.hidden=!s?.draft;if(s?.draft){s.notice='';const notice=document.querySelector('.configuration-notice');if(notice)notice.textContent='';}}
document.addEventListener('input',event=>{if(!event.target.closest('#employee_configuration_form'))return;if(event.target.dataset?.collectionName&&current()){const s=current();s.collectionNames={...s.collectionNames,[event.target.dataset.collectionName]:event.target.value};return;}capture();refreshActions();});
document.addEventListener('change',event=>{if(!event.target.closest('#employee_configuration_form'))return;const s=current(),key=event.target.dataset?.key;
 if(s&&event.target.closest('[data-picker]')&&s.resourceChoices?.[key]){if(s.saving||s.resourceBusy||s.pending)return;const selected=s.resourceChoices[key].find(c=>String(c.collection_id||c.document_id)===event.target.value);if(selected){capture();s.bindings[key]=structuredClone(selected);s.draft=structuredClone(s.draft||s.data.values);s.resourceOpen=null;s.notice='';persist(s);paint(s);return;}}
 capture();refreshActions();});
document.addEventListener('scroll',event=>{if(event.target?.classList?.contains('employee-configuration-body')&&current())current().scroll=event.target.scrollTop;},true);
document.addEventListener('click',event=>{const s=current(),button=event.target.closest('button');if(!s||!button||!button.closest('.employee-configuration-drawer'))return;
 if(button.dataset.expand||button.dataset.reconnect)void pick(button.dataset.expand||button.dataset.reconnect);
 if(button.dataset.collectionCreate)void createCollection(button.dataset.collectionCreate);
 if(button.dataset.connect)chooseConnection(button.dataset.connect);
 if(button.dataset.credentialSave)void saveCredential(button.dataset.credentialSave);
 if(button.dataset.credentialUse)chooseCredential(button.dataset.credentialUse);
 if(button.dataset.credentialClear)chooseCredential(button.dataset.credentialClear,true);
 if(button.hasAttribute('data-config-read'))void read(s);
 if(button.hasAttribute('data-check')&&!s.saving&&!s.pending&&!s.resourceBusy)void read(s);
 if(button.hasAttribute('data-config-intro')){s.introExpanded=!s.introExpanded;paint(s);}
 if(button.hasAttribute('data-config-receipt'))void receipt();
 if(button.hasAttribute('data-config-merge'))merge();
 if(button.hasAttribute('data-config-cancel')){if(s.conflict)accept(s,s.conflict);s.draft=null;s.bindings=structuredClone(s.data.bindings||{});s.errors={};s.error='';s.conflict=null;s.notice='未保存的修改已取消。';persist(s);paint(s);}
 if(button.dataset.secret){const input=document.getElementById(button.dataset.secret),show=input.type==='password';input.type=show?'text':'password';button.setAttribute('aria-pressed',String(show));button.setAttribute('aria-label',show?'隐藏明文':'显示明文');button.innerHTML=ICON(show?'eye-off':'eye');}
});
document.addEventListener('submit',event=>{if(event.target.id==='employee_configuration_form'){event.preventDefault();void save();}});
window.addEventListener('runteams:business-scope-will-change',()=>{sessions.clear();active=null;});
window.RunTeamsEmployeeConfiguration={workTarget,open,restore,required,current,drawer,decorateHeader,capture,leave,close,closeState,read,save,receipt,resources};
})();
