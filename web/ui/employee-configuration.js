/* Trusted employee settings. Definitions/values come from the local platform API. */
(()=>{
'use strict';
let active=null,painting=false;
const sessions=new Map(),embeddedSessions=new WeakMap(),inlineGroups=new WeakMap();
let inlineSequence=0;
const copy=(key,fallback)=>window.RunTeamsLocale?.t("employeeSettings."+key,{},fallback)??fallback;
const message=(key,fallback)=>({key,fallback});
const messageError=value=>Object.assign(Error(value.fallback),{uiMessage:value});
function messageMarkup(value){
 if(typeof value==='string')return esc(value);
 return '<span data-app-i18n="employeeSettings.'+value.key+'">'+esc(copy(value.key,value.fallback))+'</span>';
}
const fieldErrorMarkup=value=>RunTeamsConfigurationFields.errorMarkup(value);
const scope=()=>workspaceAccountCacheToken();
const deviceScope=()=>S.localLibrary?.cache_scope||RunTeamsHost.session.deviceScope(S);
const owned=s=>s&&s.scope===scope()&&s.deviceScope===deviceScope()&&sessions.get(s.cacheKey)===s&&(!s.entry.chat_id||workTarget()?.key===s.entry.key);
const inlineGroup=()=>S.sel&&inlineGroups.get(S.sel);
function current(node){
 const group=inlineGroup();
 if(group){
  const id=node?.closest?.('[data-config-session]')?.dataset.configSession;
  const s=id&&group.byId.get(id);
  return owned(s)?s:null;
 }
 if(S.sel?.type==='creator-assets'){
  const s=embeddedSessions.get(S.sel);
  return owned(s)?s:null;
 }
 return owned(active)&&(active.inlineSelection?S.sel===active.inlineSelection:S.sel?.type==='employee-configuration'&&S.sel.id===active.entry.key)?active:null;
}
const grouped=s=>!!s&&inlineGroup()?.byId.get(s.inlineId)===s;
const displayed=s=>owned(s)&&(grouped(s)||current()===s);
const formId=s=>grouped(s)?'employee_configuration_form_'+s.inlineId:'employee_configuration_form';
const fieldPrefix=s=>grouped(s)?'employee_config_'+s.inlineId+'_':'employee_config_';
const collectionId=(s,key)=>grouped(s)?'collection_name_'+s.inlineId+'_'+key:'collection_name_'+key;
const formFor=s=>document.getElementById(formId(s));
const configQuery=(s,selector,defaultScope='')=>document.querySelector((grouped(s)?'[data-config-session="'+s.inlineId+'"] ':defaultScope)+selector);
const publicFields=s=>RunTeamsConfigurationFields.create({icon:ICON,singleSelect:csel,idPrefix:fieldPrefix(s),errorMarkup:fieldErrorMarkup});
const rows=s=>(s.data?.definition.groups||[]).flatMap(g=>g.fields);
const ordinary=s=>rows(s).filter(f=>!['resource','connection','runtime','secret'].includes(f.type));
const storageKey=s=>'runteams.employee.configuration.'+s.cacheKey;
const sourceTarget=s=>s.entry.source;
const url=s=>s.entry.chat_id?'/api/chat/'+s.entry.chat_id+'/employee-configuration':sourceTarget(s)?'/api/creator-source/drafts/'+s.entry.source.id+'/configuration':'/api/device/employees/'+Number(s.entry.work?.id||s.entry.asset?.id)+'/configuration';
function workTarget(panel=S.conversationPanel){
 const binding=panel?.employee_binding,reference=binding?.reference;
 if(panel!==S.conversationPanel||panel?.kind!=='general'||panel.loading||panel.error||panel.employee_error||panel.debug_preview||!Number.isSafeInteger(panel.id)||panel.id<=0||panel.context?.pipeline_work||panel.context?.source_pipeline_workspace)return null;
 if(binding?.schema!=='runteams.bound-employee/v1')return null;
 const revision=binding.source_revision||'';
 const source=['runteams.acquired-employee-reference/1','runteams.rented-employee-reference/1'].includes(reference?.schema)&&/^r-[a-f0-9]{64}$/.test(revision);
 const market=reference?.schema==='runteams.business-reference/v1'&&reference.resource==='employees'&&/^[a-f0-9]{64}$/.test(revision);
 if(!source&&!market)return null;
 const owner=window.RunTeamsEmployeeWindows?.identity(panel,S,null);
 if(!owner)return null;
 return {key:JSON.stringify(['work-settings',panel.id,owner.key,binding.source_revision]),chat_id:panel.id,reference:structuredClone(owner.reference),definition_revision:binding.source_revision,record:{name:binding.name,avatar:binding.avatar}};
}
function persist(s,strict=false){if(!owned(s))return;try{if(s.draft||s.pending||s.resourcePending)RunTeamsBusinessStorage.setItem(storageKey(s),JSON.stringify({draft:s.draft,bindings:s.bindings,pending:s.pending,resourcePending:s.resourcePending,base:s.data}));else RunTeamsBusinessStorage.removeItem(storageKey(s));}catch(error){s.error=message('draftStorage','暂时无法保留草稿。请保持此窗口打开。');if(strict)throw messageError(s.error);}}
function capture(s=current(document.activeElement)){if(painting||!s?.data||s.saving||s.pending)return;const form=formFor(s);if(!form)return;
 const values=publicFields(s).collect(ordinary(s),form,s.draft||s.data.values);
 s.draft=RunTeamsConfigurationForm.draft(ordinary(s),values,s.data.values,s.bindings,s.data.bindings||{});
 persist(s);
}
function paint(s=active){if(!displayed(s))return;const previous=painting;painting=true;try{render();}finally{painting=previous;}}
function accept(s,value){
 if(value?.schema!=='runteams.employee-configuration-state/1'||!Number.isInteger(value.revision)||!value.definition||!Array.isArray(value.definition.groups)||!value.values||!value.states||typeof value.definition_sha256!=='string')throw messageError(message("invalidResponse","无法确认配置结果。请重新读取。"));
 if(s.entry.chat_id&&(RunTeamsEmployeeDirectory.referenceKey(s.entry.reference)!==RunTeamsEmployeeDirectory.referenceKey(value.reference)||s.entry.definition_revision!==value.definition_revision))throw messageError(message("workChanged","工作设置已变更。请关闭后重新打开设置。"));
 if(s.data&&JSON.stringify(s.data.reference)!==JSON.stringify(value.reference))throw messageError(message("ownerChanged","员工设置已变更。请关闭后重新打开设置。"));
 if(!s.data || s.data.definition_sha256!==value.definition_sha256){
  s.collapsedSections=new Set(value.definition.groups.filter(group=>group.initially_collapsed)
   .map(group=>groupSectionId(s,group)));
 }
 s.data=value;s.bindings=structuredClone(value.bindings||{});
}
function unavailableMessage(method,receipt){
 if(method==='POST')return message('saveInterrupted','尚未确认是否保存。你的修改仍在，请核对保存结果。');
 if(receipt)return message('receiptUnavailable','无法核对保存结果。请重试。');
 return message('readUnavailable','无法读取配置。请重试。');
}
function responseError(value,status,method,receipt){
 const copyByCode={
  employee_configuration_conflict:message('changed','配置已更新。你的修改仍在。'),
  employee_configuration_invalid:message('reviewFields','请检查标出的配置项。'),
  employee_configuration_reopen:message('reopenSettings','请关闭并重新打开员工设置。'),
  employee_configuration_unavailable:unavailableMessage(method,receipt),
 };
 const rejected=method==='POST'&&status>=400&&status<500;
 const uiMessage=Object.hasOwn(copyByCode,value?.code)?copyByCode[value.code]:(
  rejected?message('saveRejected','无法保存设置。你的修改仍在，请重试。'):unavailableMessage(method,receipt)
 );
 return Object.assign(messageError(uiMessage),{status,code:value?.code,fields:value?.fields});
}
async function request(s,method='GET',body=null,receipt=false){
 if(!owned(s))throw Error('账户或员工已改变。');
 const query=new URLSearchParams();if(sourceTarget(s)&&method==='GET')query.set('employee_source',s.entry.source.path);
 if(receipt)query.set('operation_id',s.pending.operation_id);
 const target=url(s)+(query.size?'?'+query:'');
 if(s.entry.pipeline_reference||S.localLibrary){
  let value;
  try{
   value=s.entry.pipeline_reference?await RunTeamsSourcePipelinePanels.configurationRequest(s,method,body,receipt):await api(target,method,body||undefined);
  }catch(error){throw responseError(error,error.status,method,receipt);}
  if(!owned(s))throw Error('资料库已改变。');
  if(value?.error)throw responseError(value,value.status,method,receipt);
  return value;
 }
 let response,value;try{response=await fetch(target,{method,headers:{'X-RunTeams-Device-Scope':s.deviceScope,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});value=await response.json();}
 catch(error){throw messageError(unavailableMessage(method,receipt));}
 if(!owned(s))throw Error('账户已改变。');
 if(!response.ok||value?.error)throw responseError(value,response.status,method,receipt);
 return value;
}
function applyRead(s,value){
 const draft=s.draft,bindings=s.bindings;
  if(!Number.isInteger(value?.revision)||s.data&&value.revision<s.data.revision)throw messageError(unavailableMessage('GET',false));
  if(draft&&s.data&&(value.revision!==s.data.revision||value.definition_sha256!==s.data.definition_sha256)){s.conflict=value;s.notice=message('changed','配置已更新。你的修改仍在。');}
  else{accept(s,value);if(draft){s.draft=draft;s.bindings=bindings;}s.notice='';}
}
async function read(s=active){if(s?.credentialQueue)await s.credentialQueue;if(!owned(s)||s.loading)return;s.loading=true;s.error='';paint(s);
 try{const value=await request(s);if(!owned(s))return;applyRead(s,value);}
 catch(error){if(owned(s))s.error=error.uiMessage||error.message;}
 finally{if(owned(s)){s.loading=false;paint(s);}}
}
async function open(value){
 if(S.sel?.type==='core-pipeline-parameters'&&requestDetailWorkspaceLeave(()=>open(value)))return;
 const entry=typeof value==='object'?value:RunTeamsEmployeeDirectory.entryFor(value)||RunTeamsEmployeeDirectory.assetEntry(value);
 if(!entry)throw messageError(message("directoryChanged","员工列表已变更。请重新打开设置。"));
 return activate(entry,null);
}
async function openConversation(entry,author=entry){
 if(author?.source)return RunTeamsCreatorAuthor.openSource(author.source,{settings:entry});
 if(author?.asset?.editable===true)return RunTeamsCreatorAuthor.openEmployee(author.asset.id,{settings:entry});
 return open(entry);
}
function mountInline(entry,selection){
 const displayed=current();
 if(!selection||S.sel!==selection||displayed?.inlineSelection===selection&&displayed.entry.key===entry.key)return;
 return activate(entry,selection);
}
function sessionFor(entry){
 const cacheKey=scope()+'|'+deviceScope()+'|'+entry.key;
 let s=sessions.get(cacheKey);
 if(!s){s={cacheKey,entry,scope:scope(),deviceScope:deviceScope(),data:null,bindings:{},draft:null,pending:null,loading:false,saving:false,error:'',errors:{},notice:'',scroll:0};sessions.set(cacheKey,s);
  try{const saved=JSON.parse(RunTeamsBusinessStorage.getItem(storageKey(s))||'null');if(saved?.base?.schema==='runteams.employee-configuration-state/1'){accept(s,saved.base);s.draft=saved.draft;s.bindings=saved.bindings||{};s.pending=saved.pending;s.resourcePending=saved.resourcePending;}}catch(error){s.error=message('draftUnavailable','无法读取上次的修改。请先查看已保存的配置。');}}
 s.entry=entry;
 return s;
}
async function activate(entry,inlineSelection){
 capture();
 const s=sessionFor(entry);
 if(!inlineSelection)selectDetailWorkspace({type:'employee-configuration',id:entry.key});
 if(inlineSelection?.type==='creator-assets')embeddedSessions.set(inlineSelection,s);
 else{active=s;s.inlineSelection=inlineSelection;}
 s.applicationLoadState=null;
 paint(s);if(!s.pending)await read(s);
}
function mountGroup(entries,selection,snapshot,loading){
 const waiting=loading&&!snapshot;
 if(!selection||S.sel!==selection)return;
 const previous=inlineGroups.get(selection);
 if(previous&&previous.snapshot===snapshot&&previous.waiting===waiting&&entries.length===previous.byKey.size&&entries.every(entry=>{
  const session=previous.byKey.get(entry.key);
  return owned(session)&&session.entry.configurationRevision===entry.configurationRevision;
 }))return;
 const byKey=new Map(),byId=new Map();
 for(const entry of entries){
  const s=sessionFor(entry);
  s.inlineId||=String(++inlineSequence);
  byKey.set(entry.key,s);byId.set(s.inlineId,s);
 }
 inlineGroups.set(selection,{byKey,byId,snapshot,waiting});
 for(const s of byKey.values()){
  if(waiting||s.pending||s.saving||s.loading||s.credentialQueue)continue;
  const value=snapshot?.[s.entry.pipeline_own?'':s.entry.source.path];
  if(!value||value.definition_revision!==s.entry.configurationRevision){void read(s);continue;}
  if(s.data&&value.revision<s.data.revision)continue;
  try{applyRead(s,value);s.error='';}catch(error){s.error=error.uiMessage||error.message;}
 }
 render();
}
const groupSectionId=(s,group)=>formId(s)+'-group-'+encodeURIComponent(group.key);
function toggleSection(button){
 const s=current(button);
 if(!displayed(s)||!button.isConnected)return;
 RunTeamsEmployeeDrawerHeader.toggleSection(button,s.collapsedSections||=new Set());
}
function revealFieldErrors(s){
 if(!s.collapsedSections||!Object.keys(s.errors).length)return;
 RunTeamsConfigurationForm.revealErrors(s.data?.definition.groups||[],group=>groupSectionId(s,group),s.collapsedSections,s.errors);
}
function pipelineGroupHeading(title,titleKey=''){
 return '<h3 class="settings-section-label"'+(titleKey?' data-app-i18n="'+titleKey+'"':'')+'>'+esc(title)+'</h3>';
}
function groupParts(key,owner){
 const s=inlineGroup()?.byKey.get(key);
 const ownerHeading=pipelineGroupHeading(owner.name,owner.labelKey);
 if(!owned(s))return RunTeamsAssetOverview.pipeline()?RunTeamsSkeletons.region('overview-configuration',1,'employeeSettings.loading'):
  '<section>'+ownerHeading+RunTeamsSkeletons.region('detail',undefined,'employeeSettings.loading')+'</section>';
 const {content,footer}=formParts(s,owner);
 if(!content&&!footer)return '';
 mountInputs(s);
 return '<section class="pipeline-configuration-session" data-config-session="'+s.inlineId+'">'+content+footer+'</section>';
}
function restore(){if(!owned(active))return;selectDetailWorkspace({type:'employee-configuration',id:active.entry.key});paint();}
async function required(error,chatId){
 const panel=String(S.conversationPanel?.id)===String(chatId)?S.conversationPanel:String(S.chatId)===String(chatId)?{id:S.chatId,context:S.chatCfg?.context,kind:'general'}:null;
 if(panel?.context?.pipeline_work||panel?.context?.source_pipeline_workspace){toast('请在智能体团队设置中完成配置。','info','employeeSettings.configurePipeline');return true;}
 const entry=panel&&(workTarget(panel)||RunTeamsEmployeeDirectory.forPanel(panel));if(!entry)return false;
 const token=scope(),device=deviceScope();
 if(panel===S.conversationPanel)await openConversation(entry,RunTeamsEmployeeDirectory.forPanel(panel));else await open(entry);
 const s=current();if(!s||s.entry.key!==entry.key||token!==scope()||device!==deviceScope())return;
 s.errors=error.fields||{};revealFieldErrors(s);s.notice=message('returnToChat','完成以下配置后，回到对话重新发送请求。');paint(s);
 requestAnimationFrame(()=>{if(current()===s){const target=document.querySelector('#employee_configuration_form [aria-invalid="true"]');target?.scrollIntoView({block:'center'});target?.focus();}});
 return true;
}
function close(){leave();if(current()?.entry.pipeline_reference)return RunTeamsSourcePipelinePanels.settings();closeDetailWorkspace();}
function leave(){
 const group=inlineGroup(),sessions=group?[...group.byId.values()]:[current()].filter(Boolean);
 for(const s of sessions){
  for(const [key,value] of s.credentialEdits||[])if(!s.credentialErrors?.[key])queueCredential(s,key,value);
  capture(s);
  if(!s.error)queueSave(s);
 }
}
function closeState(){
 if(inlineGroup())for(const s of inlineGroup().byId.values())capture(s);else capture();const scoped=[...sessions.values()].filter(s=>s.scope===scope()&&s.deviceScope===deviceScope());
 return {pending:scoped.some(s=>!!(s.saving||s.resourceBusy||s.pending||s.resourcePending||s.credentialWrites?.size)),dirty:scoped.some(s=>!!s.draft)};
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
  const key=field.key;
  return publicFields(s).field({...field,disabled:s.saving||s.resourceBusy||!!s.pending||s.loading||!!s.credentialWrites?.has(key),
   localCredential:{pipelineName:s.entry.pipeline_name,state:s.data.states[key],filename:s.data.credential_fields[key].filename,
    mask_length:s.data.credential_fields[key].mask_length,
    selected:!!s.data.bindings?.[key]}},'',s.credentialErrors?.[key]||s.errors[key]);
 }
 const connection=s.data.connection_fields?.[field.key];
 if(field.type==='connection'&&connection){
  const selected=!!s.bindings[field.key],locked=s.saving||s.resourceBusy||!!s.pending||s.loading;
  return publicFields(s).field({...field,disabled:locked,account:connection.origin,localService:true,serviceScopes:connection.scopes},selected?'selected':'missing',s.errors[field.key]);
 }
 const runtime=field.type==='runtime'&&s.data.runtime_fields?.includes(field.key);
 if(runtime)return publicFields(s).field({...field,disabled:s.saving||s.resourceBusy||!!s.pending||s.loading},({configured:'ready',unavailable:'unavailable'})[s.data.states[field.key]]||'unknown',s.errors[field.key]);
 if(['resource','connection','runtime','secret'].includes(field.type)&&!supported){
  const word=s.data.states[field.key]==='configured'?messageMarkup(message('configured','已配置')):messageMarkup(message('cannotConfigure','暂时无法配置'));
  return '<div class="field configuration-dependency" '+(s.errors[field.key]?'tabindex="-1" aria-invalid="true"':'')+'><div class="resource-heading"><label>'+esc(field.label)+(field.required?'<span class="required-mark" aria-hidden="true">*</span>':'')+'</label></div><p class="resource-summary">'+word+(field.note?' · '+esc(field.note):'')+'</p><p class="help">'+(field.required?messageMarkup(message('creatorRequired','此项需要由创作者配置。')):messageMarkup(message('optionalDependency','已就绪的工作可以继续。')))+'</p>'+(s.errors[field.key]?'<p class="error">'+fieldErrorMarkup(s.errors[field.key])+'</p>':'')+'</div>';
 }
 const binding=s.bindings[field.key];
 const locked=s.saving||s.resourceBusy||!!s.pending||s.loading;
 const choices=s.resourceChoices?.[field.key]||[];
 const options=collection||resourceInput?[...choices,...(binding&&!choices.some(c=>(c.collection_id||c.document_id)===(binding.collection_id||binding.document_id))?[binding]:[])].map(c=>[String(c.collection_id||c.document_id),c.name]):binding?[[String(binding.grant_id),binding.name]]:[];
 const pending=s.resourcePending?.field===field.key;
 const selectionPending=binding&&resourceSelectionKey(binding)!==resourceSelectionKey(s.data.bindings?.[field.key]);
 const resourceError=s.resourceOpen===field.key&&s.resourceReadError;
 const retry=resourceError?'<p role="alert">'+messageMarkup(resourceError)+'</p><button type="button" class="btn sm" data-resource-retry="'+esc(field.key)+'" data-app-i18n="employeeHistory.retry">重试</button>':'';
 const pickerActions=retry||(collection?(s.resourceBusy?'<p role="status">'+messageMarkup(message('loadingCollections','正在读取数据集合…'))+'</p>':(!choices.length?'<p>'+messageMarkup(message('noMatchingCollections','没有匹配的数据集合。你可以新建一个。'))+'</p>':'')+'<label for="'+esc(collectionId(s,field.key))+'">'+messageMarkup(message('newCollectionName','集合名称'))+'</label><input class="inp" id="'+esc(collectionId(s,field.key))+'" data-collection-name="'+esc(field.key)+'" maxlength="80" value="'+esc(pending?s.resourcePending.name:s.collectionNames?.[field.key]||field.label)+'" '+(pending?'disabled':'')+'><button type="button" class="btn sm" data-collection-create="'+esc(field.key)+'" '+(locked?'disabled':'')+'>'+(pending?messageMarkup(message('checkCollection','核对创建结果')):messageMarkup(message('createCollection','新建并选择')))+'</button>'):resourceInput?(s.resourceBusy?'<p role="status">'+messageMarkup(message('loadingResources','正在读取资料…'))+'</p>':!choices.length?'<p>'+ (documentInput?messageMarkup(message('noDocuments','没有可选文档。请先在「文档」中保存资料。')):messageMarkup(message('noCollections','没有可选的数据集合。')))+'</p>':''):'');
 const f={...field,...(s.entry.pipeline_own?{pipelinePicker:true}:{}),disabled:locked,options:supported?options:field.options,
  ...(supported?{resourceAccess:collection?(field.binding.access==='read'?'view':'edit'):'copy',state:selectionPending?'pending':s.data.states[field.key]==='unavailable'?'expired':'',pickerOpen:(collection||resourceInput)&&(s.resourceOpen===field.key||pending),pickerActions}:{})};
 return publicFields(s).field(f,visibleValue(s,field),s.errors[field.key]);
}
function conflictMarkup(s){if(!s.conflict)return '';
 const current=s.conflict,local=s.draft||s.data.values;
 const readable=(field,value)=>{
  if(value==null)return messageMarkup(message('emptyValue','未填写'));
  if(field.type==='checkbox')return value?messageMarkup(message('yes','是')):messageMarkup(message('no','否'));
  const label=option=>(field.options||[]).find(item=>item.value===option)?.label??option;
  return esc(Array.isArray(value)?value.map(label).join('、'):label(value));
 };
 const differences=ordinary(s).filter(f=>JSON.stringify(local[f.key])!==JSON.stringify(current.values[f.key]));
 return '<section class="configuration-conflict" role="alert"><p data-app-i18n="employeeSettings.conflict">配置已更新。你的修改仍在。</p><details><summary data-app-i18n="employeeSettings.compare">查看差异</summary><table><thead><tr><th data-app-i18n="employeeSettings.field">配置项</th><th data-app-i18n="employeeSettings.yourChanges">你的修改</th><th data-app-i18n="employeeSettings.saved">已保存</th></tr></thead><tbody>'+differences.map(f=>'<tr><td>'+esc(f.label)+'</td><td>'+readable(f,local[f.key])+'</td><td>'+readable(f,current.values[f.key])+'</td></tr>').join('')+'</tbody></table></details><button type="button" class="btn sm" data-config-merge data-app-i18n="employeeSettings.merge">在最新配置上继续修改</button></section>';
}
function settingsParts(s){
 const employee=s.data?.employee||s.entry.record||{};
 const record=window.RunTeamsEmployeeDirectory?.entryFor(s.entry.key)?.record||s.entry.record;
 const identity={...employee,...record},title=identity.name;
 const titleKey=s.entry.pipeline_own?'employeeSettings.pipeline':'employeeSettings.title';
 const titleLeading=!s.entry.pipeline_own&&title?'<span class="node-detail-avatar">'+workerAvatarMarkup(identity)+'</span>':'';
 const heading=!s.data&&!s.error?
  RunTeamsSkeletons.drawerHeading({title,leading:titleLeading,description:true}):
  detailDrawerHeading(title||copy(s.entry.pipeline_own?'pipeline':'title',s.entry.pipeline_own?'智能体团队配置':'员工设置'),employee.description||'','','',{titleKey:title?undefined:titleKey,titleLeading,descriptionMarkdown:true});
 const intro='<section class="workspace-detail-head detail-drawer-intro">'+heading+'</section>';
 mountInputs(s);
 return {intro,...formParts(s)};
}
function drawer(){const s=current();if(!s)return '';
 const {intro,content,footer}=settingsParts(s);
 const heading={toolbar:RunTeamsEmployeeDrawerHeader.markup('configuration'),intro};
 return detailDrawerShell({className:'employee-configuration-drawer',header:heading,introClass:'detail-drawer-summary',body:content+footer,bodyClass:'employee-configuration-body settings-section-stack',attrs:'data-app-i18n-aria-label="employeeSettings.'+(s.entry.pipeline_own?'pipeline':'title')+'" aria-label="'+esc(s.entry.pipeline_own?copy('pipeline','智能体团队配置'):copy('title','员工设置'))+'"'+(s.loading?' aria-busy="true"':'')});
}
function embeddedSettings(){
 const s=current();if(!s||S.sel?.type!=='creator-assets')return '';
 const {intro,content,footer}=settingsParts(s);
 return '<section class="creator-asset-settings employee-configuration-drawer" aria-label="员工设置" data-app-i18n-aria-label="employeeSettings.title"'+(s.loading?' aria-busy="true"':'')+'><div class="right-detail-scroll" tabindex="-1"><div class="detail-drawer-summary">'+intro+'</div><div class="employee-configuration-body settings-section-stack">'+content+footer+'</div></div></section>';
}
// Device connections are shared. This list stores only the employee's selections.
const applicationOwner=entry=>entry.chat_id?RunTeamsEmployeeDirectory.entryFor(entry.reference):entry;
const hasApplications=s=>!!employeeApplicationReference(applicationOwner(s.entry))&&!!applicationOwner(s.entry)?.key&&!s.entry.pipeline_reference&&!s.entry.pipeline_own&&
 !RunTeamsHost.session.workspace(S)&&!RunTeamsHost.session.readOnly(S);
const applicationKey=s=>'runteams.employee.applications.'+applicationOwner(s.entry).key;
const applicationId=row=>row.provider+':'+row.id;
const employeeApplicationReference=entry=>entry?.source?.reference||entry?.reference||entry?.work?.native_asset?.employee_reference;
const applicationMigrations=new Map();
async function migrateEmployeeApplications(entry){
 const employee=employeeApplicationReference(entry);
 if(!entry?.key||!employee||RunTeamsHost.session.workspace(S)||RunTeamsHost.session.readOnly(S))return;
 const storage='runteams.employee.applications.'+entry.key;
 const previous=RunTeamsBusinessStorage.getItem(storage);
 if(!previous)return;
 const key=scope()+'|'+deviceScope()+'|'+entry.key;
 if(!applicationMigrations.has(key)){
  const pending=(async()=>{
   const rows=legacyApplications({entry});
   const result=await accountMcpTestRequest({action:'employee-apps-import',employee,rows});
   if(key===scope()+'|'+deviceScope()+'|'+entry.key&&RunTeamsBusinessStorage.getItem(storage)===previous)
    RunTeamsBusinessStorage.removeItem(storage);
   return result;
  })();
  applicationMigrations.set(key,pending);
  pending.then(()=>applicationMigrations.delete(key),()=>applicationMigrations.delete(key));
 }
 return applicationMigrations.get(key);
}
async function prepareApplications(panel){
 const entry=RunTeamsEmployeeDirectory.forPanel(panel);
 if(entry)await migrateEmployeeApplications(entry);
}
function bindingsState(s){
 const owner=applicationOwner(s.entry);
 return owner?.key?sessionFor(owner):null;
}
function publishApplicationBindings(state,rows){
 if(!owned(state))return;
 state.applicationReadFailed=false;
 state.applications=rows;
 for(const session of sessions.values()){
  if(displayed(session)&&hasApplications(session)&&bindingsState(session)===state)paintApplicationRows(session);
 }
}
async function readApplicationBindings(state){
 if(state.applicationRead)return state.applicationRead;
 const previous=state.applications;
 state.applicationRead=(async()=>{
  const migrated=await migrateEmployeeApplications(state.entry);
  const result=migrated||await accountMcpTestRequest({action:'employee-apps-read',employee:employeeApplicationReference(state.entry)});
  if(state.applications===previous)publishApplicationBindings(state,result.applications);
 })();
 try{await state.applicationRead;}finally{state.applicationRead=null;}
}
async function loadApplicationBindings(s,state){
 try{
  await readApplicationBindings(state);
  if(displayed(s))await refreshEmployeeApplicationNames(s);
 }catch(error){
  if(displayed(s)){
   state.applicationReadFailed=true;
   paintApplicationRows(s);
   toast(error.message,'err');
  }
 }
}
function applications(s){
 const rows=bindingsState(s)?.applications;
 if(rows)return rows;
 return legacyApplications(s);
}
function legacyApplications(s){
 try{
  const rows=JSON.parse(RunTeamsBusinessStorage.getItem(applicationKey(s))||'[]');
  return Array.isArray(rows)?rows.filter(row=>row&&['mcp','composio'].includes(row.provider)&&
   typeof row.id==='string'&&typeof row.name==='string'&&(!row.account||typeof row.account.name==='string')):[];
 }catch{return [];}
}
async function changeApplication(s,row,remove=false){
 if(!displayed(s)||!hasApplications(s))return;
 try{
  const state=bindingsState(s),owner=state.entry;
  await migrateEmployeeApplications(owner);
  if(!displayed(s))return;
  const result=await accountMcpTestRequest({action:'employee-apps-set',
   employee:employeeApplicationReference(owner),row,remove});
  publishApplicationBindings(state,result.applications);
 }catch{
  toast(copy('appsSaveFailed','无法保存应用配置。'),'err','employeeSettings.appsSaveFailed');
  return false;
 }
 return true;
}
function paintApplicationRows(s){
 const slot=document.getElementById(formId(s)+'-applications');
 if(!!slot!==showApplicationSection(s)){
  paint(s);
  return;
 }
 if(slot){
  slot.innerHTML=applicationRows(s);RunTeamsLocale?.apply(slot);
  const dialog=document.getElementById('childModalHost');
  if(dialog?.querySelector('[data-employee-app-dialog]'))dialog._returnFocus=slot.querySelector('[data-employee-app-add]');
 }
}
function applicationMark(row){
 const logo=row.logo||(row.provider==='composio'&&/^[A-Za-z0-9_-]+$/.test(row.id||'')?'https://logos.composio.dev/api/'+row.id:'');
 const trusted=typeof logo==='string'&&/^https:\/\/(?:logos\.composio\.dev\/api\/[A-Za-z0-9_-]+|(?:assets\.composio\.dev\/logos\/|cdn\.jsdelivr\.net\/gh\/ComposioHQ\/open-logos@[A-Za-z0-9_-]+\/)[A-Za-z0-9_.-]+\.(?:png|svg|webp|jpe?g))$/.test(logo);
 const image=trusted?'<img src="'+esc(logo)+'" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.classList.add(\'is-loaded\')" onerror="this.remove()">':'';
 return '<span class="employee-application-mark" aria-hidden="true">'+esc(Array.from(row.name)[0]||'•')+image+'</span>';
}
const gmailApplication=row=>row.provider==='composio'&&row.id==='gmail';
const mailboxName=name=>typeof name==='string'&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(name);
function applicationAccount(s,row){
 const id=applicationId(row),pending=s.applicationConnections?.get(id);
 const refreshed=s.applicationNames?.get(id);
 const accountName=refreshed?.id===row.account?.id?refreshed?.name:row.account?.name;
 const gmail=gmailApplication(row)&&row.account?.id;
 const loading=gmail&&!mailboxName(accountName)&&refreshed?.id!==row.account.id;
 if(pending)return '<span class="employee-application-pending"><span class="env-spinner" aria-hidden="true"></span><span class="sr-only" role="status">'+
  messageMarkup(pending.label)+'</span>'+
  (pending.url?' <a href="'+esc(pending.url)+'" target="_blank" rel="noopener noreferrer">'+toolsCopy('composioAuthorize','前往授权')+'</a>':'')+'</span>';
 if(loading)return '<span class="employee-application-placeholder" role="status"><span class="skeleton-block" aria-hidden="true"></span>'+
  '<span class="sr-only">'+messageMarkup(message('appsLoading','正在读取…'))+'</span></span>';
 if(row.account){
  const name=gmail&&!mailboxName(accountName)?toolsText('connected','已连接'):accountName;
  return applicationAccountLabel(name);
 }
 return '<button type="button" class="btn" data-employee-app-connect="'+esc(id)+'">'+messageMarkup(message('appsConnect','连接'))+'</button>';
}
async function refreshEmployeeApplicationNames(s){
 const saved=applications(s).filter(row=>row.provider==='composio'&&row.account?.id);
 if(!saved.length)return;
 const selection=S.sel;
 const current=()=>displayed(s)&&S.sel===selection;
 function apply(row,name){
  if(!current())return;
  const id=applicationId(row),rows=applications(s);
  const latest=rows.find(item=>applicationId(item)===id);
  if(latest?.account?.id!==row.account.id||s.applicationConnections?.has(id))return;
  (s.applicationNames||=new Map()).set(id,{id:row.account.id,name});

  const slot=document.getElementById(formId(s)+'-applications');
  const node=slot?.querySelector('[data-employee-app-menu="'+CSS.escape(id)+'"]')?.previousElementSibling;
  if(node?.matches('.employee-application-account,.employee-application-placeholder,.employee-application-pending'))node.outerHTML=applicationAccount(s,latest);
 }
 let connection;
 try{connection=await accountComposioRequest({},'status');}catch{}
 if(!current())return;
 for(const row of saved){
  let name=row.account.name;
  try{
   if(connection?.configured){
    const {accounts}=await accountComposioRequest(connection,'accounts',{toolkit:row.id});
    const account=accounts.find(item=>item.id===row.account.id&&item.status==='ACTIVE'&&!item.disabled);
    if(account&&(!gmailApplication(row)||mailboxName(account.name)))name=account.name;
   }
  }catch{
   // Keep the last known display name if Composio is temporarily unavailable.
  }
  if(!current())return;
  apply(row,name);
 }
}
function listedApplications(s){
 const saved=applications(s),items=new Map(saved.map(row=>[applicationId(row),row]));
 for(const requirement of s.data?.definition.application_requirements||[]){
  if(!requirement.toolkit)continue;
  const row={provider:'composio',id:requirement.toolkit,name:requirement.label};
  if(!items.has(applicationId(row)))items.set(applicationId(row),row);
 }
 return [...items.values()];
}
function showApplicationSection(s){
 return listedApplications(s).length>0||bindingsState(s)?.applicationReadFailed===true;
}
function applicationRow(row,actions){
 const name=esc(row.name);
 return '<div class="employee-application-row">'+applicationMark(row)+
  '<strong class="employee-application-name" title="'+name+'">'+name+'</strong>'+actions+'</div>';
}
function applicationAccountLabel(name){
 return '<span class="employee-application-account" title="'+esc(name)+'">'+esc(name)+'</span>';
}
function applicationRows(s){
 const label=(key,fallback)=>messageMarkup(message(key,fallback));
 const state=bindingsState(s);
 if(state?.applicationReadFailed&&!state.applications?.length)return '<button type="button" class="btn" data-employee-app-retry data-app-i18n="employeeHistory.retry">重试</button>';
 if(!state?.applications){
  return RunTeamsSkeletons.region('detail',1,'employeeSettings.loading');
 }
 return listedApplications(s).map(row=>{
  const pending=s.applicationConnections?.get(applicationId(row));
  const id=esc(applicationId(row)),account=applicationAccount(s,row);
  return applicationRow(row,account+(applications(s).some(saved=>applicationId(saved)===applicationId(row))?'<button type="button" class="btn ghost employee-application-more" data-menu-trigger="quiet" data-employee-app-menu="'+id+'" aria-haspopup="menu" aria-expanded="false"'+(pending?' disabled':'')+' aria-label="'+esc(copy('appsMore','更多操作')+' · '+row.name)+'">'+ICON('more')+'</button>':''));
 }).join('')+'<div class="employee-application-footer"><button type="button" class="btn" data-employee-app-add>'+label('appsAdd','添加应用')+'</button></div>';
}
function applicationSection(s){
 if(!hasApplications(s))return '';
 const state=bindingsState(s);
 if(s.applicationLoadState!==state){
  s.applicationLoadState=state;
  void loadApplicationBindings(s,state);
 }
 if(!showApplicationSection(s))return '';
 const id=formId(s)+'-applications';
 return RunTeamsEmployeeDrawerHeader.section({
  id:id+'-section',title:messageMarkup(message('appsTitle','应用连接')),
  body:'<div id="'+id+'">'+applicationRows(s)+'</div>',
  collapsedSections:s.collapsedSections,action:'RunTeamsEmployeeConfiguration.toggleSection'
 });
}
function applicationDialog(s,title,body,className,headerHtml){
 const selection=S.sel;
 const host=openChildDialog({title,body,className,headerHtml,manageFocus:true,attrs:'role="dialog" aria-modal="true" data-employee-app-dialog aria-label="'+esc(title)+'"'});
 host.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing){event.stopPropagation();closeChildDialog();}});
 RunTeamsLocale?.apply(host);
 return {host,current:()=>host.isConnected&&S.sel===selection&&displayed(s)};
}
function applicationStatus(node,value,error=false){
 node.textContent=value;node.setAttribute('role',error?'alert':'status');
}
function openApplicationPicker(s,initialTab='apps'){
 const label=(key,fallback)=>messageMarkup(message(key,fallback));
 const title=copy('appsAdd','添加应用');
 const employee=s.entry.record?.name||s.data?.employee?.name;
 const header='<div class="employee-app-picker-heading"><div class="tt">'+esc(title)+'</div>'+
  (employee?'<p class="employee-app-picker-target">'+esc(RunTeamsLocale?.t('employeeSettings.appsTarget',{name:employee},'添加到 '+employee)||'添加到 '+employee)+'</p>':'')+'</div>'+
  '<label class="employee-app-picker-search rt-search-field">'+ICON('search')+'<input type="search" autocomplete="off"></label>'+
  '<button type="button" class="x modal-x" aria-label="'+esc(copy('closeDialog','关闭弹窗'))+'" onclick="closeChildDialog()">'+ICON('x')+'</button>';
 const {host,current}=applicationDialog(s,title,
  '<div class="employee-app-picker-tabs" role="tablist" aria-label="'+esc(title)+'">'+
  '<button type="button" role="tab" id="employee_app_tab_apps" data-app-tab="apps" aria-controls="employee_app_picker_panel">'+label('appsCatalog','应用目录')+'</button>'+
  '<button type="button" role="tab" id="employee_app_tab_mcp" data-app-tab="mcp" aria-controls="employee_app_picker_panel">'+label('appsLocalMcp','本机 MCP')+'</button></div>'+
  '<div role="tabpanel" id="employee_app_picker_panel">'+
  '<div class="employee-app-picker-scroll" tabindex="0" data-employee-app-catalog><div role="list" data-app-results></div><div data-app-load-state></div>'+
  '<div class="employee-app-picker-custom" data-app-custom-wrap hidden><button type="button" class="btn" data-employee-app-custom>'+label('appsCustomMcp','添加自定义 MCP')+'</button></div></div></div>',
  'employee-app-picker',header);
 const search=host.querySelector('input'),panel=host.querySelector('[role=tabpanel]');
 const tabs=[...host.querySelectorAll('[data-app-tab]')];
 const list=host.querySelector('[data-employee-app-catalog]'),results=host.querySelector('[data-app-results]');
 const status=host.querySelector('[data-app-load-state]'),customWrap=host.querySelector('[data-app-custom-wrap]');
 let tab='',query='',cursor='',generation=0,timer,busy=false,failed=false;
 let request=Promise.resolve();
 const rows=new Map(),seenCursors=new Set();
 const fallbackDescriptions={
  gmail:['appsGmail','收发和整理邮件'],slack:['appsSlack','读取消息并发送团队更新'],
  instagram:['appsInstagram','查看已授权账号的内容表现'],tiktok:['appsTikTok','查看此应用支持的功能']
 };
 function rowDescription(row){
  if(row.provider==='mcp')return {
   preset:copy('appsPresetMcp','预置 MCP'),sample:copy('appsSampleMcp','本机示例 · 无需账号')
  }[row.kind]||copy('appsCustomSource','自定义 MCP');
  const known=fallbackDescriptions[row.id];
  return known?copy(...known):row.description||'';
 }
 function appendRows(items){
  const existing=new Set(applications(s).map(applicationId));
  for(const row of items){
   const id=applicationId(row);
   if(rows.has(id))continue;
   rows.set(id,row);
   const added=existing.has(id),description=esc(rowDescription(row)),name=esc(row.name);
   results.insertAdjacentHTML('beforeend','<div class="employee-app-picker-row" role="listitem">'+
    applicationMark(row)+
    '<span class="employee-application-name"><strong title="'+name+'">'+name+'</strong><small title="'+description+'">'+description+'</small></span>'+
    '<div class="employee-app-picker-action">'+(added?label('appsAdded','已添加'):
    '<button type="button" class="btn" data-choice="'+esc(id)+'" aria-label="'+esc(copy('appsAddOne','添加')+' '+row.name)+'">'+label('appsAddOne','添加')+'</button>')+'</div></div>');
  }
 }
 function loadStatus(markup='',isError=false){
  status.innerHTML=markup;
  status.setAttribute('role',isError?'alert':'status');
 }
 function showLoading(more=false){
  list.setAttribute('aria-busy','true');
  const loadingText=more?label('appsLoadingMore','正在加载更多应用…'):label('appsLoading','正在读取…');
  const row='<div class="employee-app-picker-row" data-skeleton-row>'+
   '<span class="skeleton-block employee-app-skeleton-icon"></span>'+
   '<span class="employee-application-name"><span class="skeleton-block employee-app-skeleton-name"></span>'+
   '<span class="skeleton-block employee-app-skeleton-description"></span></span>'+
   '<span class="skeleton-block employee-app-skeleton-action"></span></div>';
  loadStatus('<span class="sr-only">'+loadingText+'</span><div data-skeleton-list aria-hidden="true" inert>'+
   row.repeat(more?2:tab==='mcp'?3:6)+'</div>');
 }
 function maybeLoadMore(){
  if(current()&&tab==='apps'&&cursor&&!busy&&!failed&&list.scrollHeight-list.clientHeight-list.scrollTop<=40)load(true);
 }
 function load(more=false){
  if(!current()||busy||(more&&!cursor))return;
  const version=generation,selected=tab,term=query,after=more?cursor:'';
  const owns=()=>current()&&version===generation;
  busy=true;failed=false;
  showLoading(more);
  request=request.then(async()=>{
   if(!owns())return;
   try{
    if(selected==='mcp'){
     const local=await accountMcpTestRequest();
     if(!owns())return;
     appendRows(local.connections.filter(row=>row.kind!=='composio'&&row.name.toLocaleLowerCase().includes(term.toLocaleLowerCase()))
      .map(row=>({provider:'mcp',id:row.id,name:row.name,kind:row.kind})));
    }else{
     const connection=await accountComposioRequest({},'status');
     if(!owns())return;
     if(!connection.configured){
      loadStatus('<div class="employee-app-picker-notice"><strong>'+label('appsSetupTitle','先配置 Composio')+'</strong><p>'+
       label('appsSetupHint','配置后可搜索应用目录。已有 MCP 可在「本机 MCP」中添加。')+'</p><button type="button" class="btn" data-composio-setup>'+
       label('appsSetup','配置 Composio')+'</button></div>');
      return;
     }
     const page=await accountComposioRequest(connection,'catalog',{search:term,cursor:after});
     if(!owns())return;
     appendRows(page.items.map(row=>({provider:'composio',id:row.slug,name:row.name,description:row.description,logo:row.logo,noAuth:row.no_auth===true})));
     cursor=page.next_cursor&&!seenCursors.has(page.next_cursor)?page.next_cursor:'';
     if(cursor)seenCursors.add(cursor);
    }
    if(rows.size)loadStatus();
    else loadStatus('<div class="employee-app-picker-empty"><strong>'+label(selected==='mcp'?'appsNoMcp':'appsNoResults',selected==='mcp'?'未找到 MCP':'未找到应用')+'</strong>'+
     (term?'<p>'+label('appsTrySearch','换个名称试试。')+'</p><button type="button" class="btn" data-app-clear>'+label('appsClearSearch','清除搜索')+'</button>':'')+'</div>');
   }catch(error){
    if(!owns())return;
    failed=true;
    loadStatus('<div class="employee-app-picker-empty"><strong>'+label('appsReadFailed','暂时无法读取列表')+'</strong><p>'+esc(error.message)+'</p>'+
     '<button type="button" class="btn" data-app-retry>'+label('reload','重新读取')+'</button></div>',true);
   }finally{
    if(owns()){
     busy=false;
     list.setAttribute('aria-busy','false');
     requestAnimationFrame(maybeLoadMore);
    }
   }
  });
 }
 function reset(delay=0){
  clearTimeout(timer);
  generation++;busy=false;failed=false;cursor='';
  query=search.value.trim();rows.clear();seenCursors.clear();results.replaceChildren();list.scrollTop=0;
  if(delay){
   showLoading();
   timer=setTimeout(()=>load(),delay);
  }else load();
 }
 function select(next){
  if(next===tab)return;
  tab=next;search.value='';
  const local=tab==='mcp';
  const placeholder=copy(local?'appsSearchMcp':'appsSearchCatalog',local?'搜索本机 MCP':'搜索应用名称');
  search.placeholder=placeholder;search.setAttribute('aria-label',placeholder);
  for(const button of tabs){
   const active=button.dataset.appTab===tab;
   button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;
   if(active)panel.setAttribute('aria-labelledby',button.id);
  }
  customWrap.hidden=!local;
  reset();
 }
 search.addEventListener('input',()=>reset(250));
 search.addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!event.isComposing){event.preventDefault();reset();}
 });
 for(const button of tabs)button.onclick=()=>select(button.dataset.appTab);
 tabs[0].parentElement.addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  event.preventDefault();
  const next=event.key==='Home'?'apps':event.key==='End'?'mcp':tab==='apps'?'mcp':'apps';
  select(next);tabs.find(button=>button.dataset.appTab===next).focus();
 });
 list.addEventListener('scroll',maybeLoadMore,{passive:true});
 host.addEventListener('click',async event=>{
  const button=event.target.closest('button');
  if(!current()||!button)return;
  if(button.hasAttribute('data-choice')){
   const row=rows.get(button.dataset.choice);
   if(!row||button.disabled||applications(s).some(item=>applicationId(item)===applicationId(row)))return;
   button.disabled=true;
   const added=await changeApplication(s,{provider:row.provider,id:row.id,name:row.name,...(row.logo?{logo:row.logo}:{}),...(row.noAuth?{noAuth:true}:{})});
   if(!current()||!button.isConnected)return;
   if(!added){button.disabled=false;return;}
   const action=button.parentElement;
   action.innerHTML=label('appsAdded','已添加');action.setAttribute('role','status');
   const actions=[...results.querySelectorAll('[data-choice]')];
   const next=actions.find(item=>action.compareDocumentPosition(item)&Node.DOCUMENT_POSITION_FOLLOWING);
   (next||actions.at(-1)||list).focus({preventScroll:true});
  }else if(button.hasAttribute('data-app-retry'))load(Boolean(cursor));
  else if(button.hasAttribute('data-app-clear')){search.value='';reset();search.focus();}
  else if(button.hasAttribute('data-composio-setup')){
   closeChildDialog();openSettingsPage('tools');
   if(document.getElementById('settingsPanel')){accountMcpTestOpen();accountComposioOpen();}
  }else if(button.hasAttribute('data-employee-app-custom')){
   const returnFocus=host._returnFocus;
   openApplicationMcp(s,undefined,()=>{
    document.querySelector('#'+formId(s)+'-applications [data-employee-app-add]')?.focus();
    openApplicationPicker(s,'mcp');
   },returnFocus);
  }
 });
 select(initialTab);
 search.focus();
}
function openApplicationMcp(s,row,onConnected,returnFocus){
 const {host,current}=applicationDialog(s,row?.name||toolsText('mcpAddCustom','添加自定义连接'),
  '<form class="settings-mcp-connection-form">'+(row?'':'<label>'+toolsCopy('mcpName','连接名称')+'<input required name="name" maxlength="80"></label><label>'+toolsCopy('mcpUrl','服务地址')+'<input required name="url" type="url" maxlength="2048" placeholder="https://example.com/mcp"></label>')+
  (row?.id==='sample'?'':'<label>'+toolsCopy('mcpToken','访问令牌（可选）')+'<input name="token" type="password" autocomplete="off" maxlength="8192"></label>')+
  '<p data-connection-status role="status"></p><div class="employee-application-footer"><button type="submit" class="btn pri">'+messageMarkup(message('appsConnect','连接'))+'</button></div></form>');
 if(returnFocus?.isConnected)host._returnFocus=returnFocus;
 const form=host.querySelector('form'),status=host.querySelector('[data-connection-status]'),button=form.querySelector('button');
 // Keep a created connection available for retry if the server cannot be reached yet.
 let connection=row;
 form.onsubmit=async event=>{
  event.preventDefault();
  if(!current()||button.disabled)return;
  button.disabled=true;
  applicationStatus(status,toolsText('mcpReading','正在读取工具…'));
  const token=form.elements.token?.value.trim()||'';
  try{
   if(!connection){
    const result=await accountMcpTestRequest({action:'save',name:form.elements.name.value,url:form.elements.url.value,token});
    connection={provider:'mcp',id:result.connection.id,name:result.connection.name};
    if(!current())return;
    if(!await changeApplication(s,connection))return;
    form.elements.name.disabled=form.elements.url.disabled=true;
   }else if(token&&connection.id!=='sample'){
    await accountMcpTestRequest({action:'save',id:connection.id,token});
   }
   if(!current())return;
   if(form.elements.token)form.elements.token.value='';
   await accountMcpTestRequest({action:'inspect',id:connection.id});
   if(current()&&await changeApplication(s,{...connection,account:{name:connection.name}})&&current()){closeChildDialog();onConnected?.();}
  }catch(error){if(current())applicationStatus(status,error.message,true);}
  finally{button.disabled=false;}
 };
}
function connectEmployeeComposio(s,row,reconnect,context=null){
 const available=context?.current||(()=>displayed(s)&&hasApplications(s));
 if(!available())return;

 const states=s.applicationConnections||=new Map(),id=applicationId(row);
 if(states.has(id))return;
 const state={label:message('appsConnecting','正在连接…')};
 states.set(id,state);
 const current=()=>available()&&states.get(id)===state&&(context||listedApplications(s).some(item=>applicationId(item)===id));
 const paintState=()=>{
  if(context){context.status(state);return;}
  const slot=document.getElementById(formId(s)+'-applications');
  if(slot){slot.innerHTML=applicationRows(s);RunTeamsLocale?.apply(slot);}
 };
 const finish=async account=>{
  if(account){
   (s.applicationNames||=new Map()).set(id,account);
   if(context)await context.complete(account);
   else await changeApplication(s,{...row,account});
  }
  states.delete(id);
  if(context)context.status(null);
  else if(displayed(s))paintState();
 };
 async function start(){
  paintState();
  try{
   const connection=await accountComposioRequest({},'status');
   if(!current())return;
   if(!connection.configured)throw messageError(message('appsSetupFirst','请先在工具设置中配置 Composio。'));
   const request=action=>accountComposioRequest(connection,action,{toolkit:row.id});
   const accounts=async()=>(await request('accounts')).accounts.filter(item=>item.status==='ACTIVE'&&!item.disabled);
   if(!reconnect){
    if(row.noAuth)return await finish({name:toolsText('composioNoAuth','无需应用账号')});
    const [account]=await accounts();
    if(!current())return;
    if(account)return await finish({id:account.id,name:account.name});
   }
   const link=await request('connect');
   if(!current())return;
   const url=new URL(link.redirect_url);
   if(!['https://connect.composio.dev','https://app.composio.dev'].includes(url.origin)||!url.pathname.startsWith('/link/')||url.username||url.password)
    throw messageError(message('appsInvalidAuth','无法识别授权地址。'));
   if(!link.connected_account_id)throw messageError(message('appsAuthUnverified','暂时无法核对授权结果，请重试。'));
   state.url=url.href;
   state.label=message('appsWaitingAuth','等待授权');
   paintState();
   window.open(url.href,'_blank','noopener,noreferrer');
   const deadline=Date.now()+120000;
   while(current()&&Date.now()<deadline){
    await new Promise(resolve=>setTimeout(resolve,2500));
    if(!current())return;
    const active=await accounts();
    if(!current())return;
    const account=active.find(item=>item.id===link.connected_account_id);
    if(account)return await finish({id:account.id,name:account.name});
   }
   if(current())throw messageError(message('appsAuthPending','授权尚未完成，请重试。'));
  }catch(error){
   if(current()){
    if(context)context.error(error.uiMessage?copy(error.uiMessage.key,error.uiMessage.fallback):error.message);
    else toast(error.uiMessage?copy(error.uiMessage.key,error.uiMessage.fallback):error.message,'err',error.uiMessage&&'employeeSettings.'+error.uiMessage.key);
   }
  }finally{
   if(states.get(id)===state){
    if(current())finish();
    else states.delete(id);
   }
  }
 }
 void start();
}
function applicationAction(s,button){
 if(!hasApplications(s))return;
 if(button.hasAttribute('data-employee-app-retry'))return loadApplicationBindings(s,bindingsState(s));
 if(button.hasAttribute('data-employee-app-add'))return openApplicationPicker(s);
 const id=button.dataset.employeeAppMenu??button.dataset.employeeAppConnect;
 const row=listedApplications(s).find(item=>applicationId(item)===id);
 if(!row)return;
 const connect=reconnect=>row.provider==='mcp'?openApplicationMcp(s,row):connectEmployeeComposio(s,row,reconnect);
 if(button.hasAttribute('data-employee-app-connect'))return connect(false);
 const items=row.account?[{label:copy('appsReconnect','重新连接'),labelKey:'employeeSettings.appsReconnect',icon:'refresh',fn:()=>connect(true)}]:[];
 items.push({label:copy('appsDelete','删除'),labelKey:'employeeSettings.appsDelete',icon:'trash',danger:true,fn:async()=>{
  if(await changeApplication(s,row,true)&&displayed(s))document.querySelector('#'+formId(s)+'-applications [data-employee-app-add]')?.focus();
 }});
 openMenu(button,items,{variant:'workerAction',align:'right',keyboardReturn:()=>button,dismissOnScroll:'.right-detail-scroll'});
}

function formParts(s,groupOwner=null){
 const groups=(s.data?.definition.groups||[]).filter(group=>group.fields.length);
 let content=!s.data&&!s.error?RunTeamsSkeletons.region(groupOwner&&RunTeamsAssetOverview.pipeline()?'overview-configuration':'detail',undefined,'employeeSettings.loading'):'';
 if(s.data){
  if(s.entry.chat_id&&groups.length)content+='<p class="configuration-readiness" data-app-i18n="employeeSettings.workScope">已开始的工作会继续使用原配置。</p>';
   const labeledGroups=groupOwner?.qualifyGroups?groups.map(group=>({...group,label:groupOwner.name+' · '+group.label})):groups;
   const fields=RunTeamsConfigurationForm.groups({groups:labeledGroups,idFor:group=>groupSectionId(s,group),
   renderField:field=>fieldMarkup(s,field),collapsedSections:s.collapsedSections,
   action:'RunTeamsEmployeeConfiguration.toggleSection'});
  const formBody=fields+conflictMarkup(s);
  if(formBody)content+=RunTeamsConfigurationForm.markup({id:formId(s),body:formBody});
  content+=applicationSection(s);
 }
 if(s.error){
  const reload=s.pending||s.error.key==='reopenSettings'?'':' <button type="button" class="textbutton" data-config-read data-app-i18n="employeeSettings.reload">重新读取</button>';
  content+='<div class="configuration-error" role="alert">'+messageMarkup(s.error)+reload+'</div>';
 }
 if(s.errors?._form)content+='<p class="configuration-error" role="alert">'+fieldErrorMarkup(s.errors._form)+'</p>';
 if(s.notice)content+='<p class="configuration-notice" role="status" tabindex="-1">'+messageMarkup(s.notice)+'</p>';
 content+=RunTeamsWorkAuthorization.settings(s.entry);
 const footer=s.data?RunTeamsConfigurationForm.footer({state:s,receiptAttrs:'data-config-receipt',inline:true}):'';
 if(groupOwner&&!groups.length&&(content||footer))content=pipelineGroupHeading(groupOwner.name,groupOwner.labelKey)+content;
 return {content,footer};
}
function inlineParts(key){
 const s=current();
 if(!s?.inlineSelection||s.entry.key!==key)return null;
 const {content,footer}=formParts(s);
 if(!content&&!footer)return null;
 mountInputs(s);
 return {body:content+footer};
}
function holdInlineInput(){
 const input=document.activeElement,s=current(input);
 if(!s||s.saving||s.pending||s.loading||!formFor(s)?.contains(input))return false;
 return RunTeamsConfigurationForm.holdInput(input,()=>displayed(s),()=>render());
}
function mountInputs(s){
 requestAnimationFrame(()=>{if(!displayed(s))return;
  for(const [key,value] of s.credentialEdits||[]){const input=credentialInput(s,key);if(input&&!input.value)RunTeamsConfigurationFields.restoreCredentialInput(input,value);}
  if(S.sel?.type==='employee-configuration')decorateHeader();
  if(S.sel?.type!=='employee-configuration'&&S.sel?.type!=='creator-assets')return;
  const body=document.querySelector('.employee-configuration-drawer > .right-detail-scroll');if(body)body.scrollTop=s.scroll;
 });
}
function decorateHeader(){const s=current();if(!s||S.sel?.type!=='employee-configuration')return;const canCreate=!s.entry.pipeline_reference&&(!!s.entry.source||s.entry.asset?.editable===true);
 RunTeamsEmployeeDrawerHeader.mount('configuration',s,{kind:'settings',onCollapse:close,collapseLabelKey:'employeeSettings.close',extras:{actions:[...(canCreate?[{id:'resources',label:'资源',labelKey:'employeeSettings.resources',onPress:resources}]:[])]}});
}
function queueSave(s){
 if(s.draft&&!s.pending&&!s.conflict)RunTeamsConfigurationForm.scheduleSave(s,current=>save(false,s,current));
}
async function save(retry=false,s=current(),scheduled=()=>true){if(s?.credentialQueue)await s.credentialQueue;
 if(!scheduled()||!owned(s)||s.saving||s.resourceBusy||s.loading||!s.data||(retry?!s.pending:s.pending||!s.draft))return;
 if(s.resourcePending){s.error=message('checkCollectionFirst','请先核对数据集合是否已创建，再保存配置。');paint(s);return;}
 if(s.conflict){s.error=message('reviewBeforeSave','请先查看最新配置，再保存修改。');paint(s);return;}
 await configurationTransaction(s);
}
async function configurationTransaction(s,receipt=false){
 return RunTeamsConfigurationForm.transact(s,{
  prepare:()=>({expected_revision:s.data.revision,definition_sha256:s.data.definition_sha256,values:structuredClone(s.draft||s.data.values),bindings:Object.fromEntries(Object.entries(s.bindings).map(([key,value])=>[key,value.schema==='runteams.configuration-connection/1'?structuredClone(value):value.schema==='runteams.configuration-credential/1'||Object.keys(value).length===1&&value.key?{key:value.key}:value.document_id?{document_id:value.document_id,owner:structuredClone(value.owner)}:value.collection_id||Object.hasOwn(value,'identity')?structuredClone(value):{grant_id:value.grant_id}])),...(sourceTarget(s)?{employee_source:s.entry.source.path}:{})}),
  owned:()=>owned(s),paint:()=>paint(s),form:()=>displayed(s)?formFor(s):null,persist:()=>persist(s,true),
  send:async(pending,checking)=>{
   const result=await request(s,checking?'GET':'POST',checking?null:pending,checking);
   if(!checking)return {status:'committed',value:result};
   if(result?.state==='confirmed'){
    if(result.result?.revision!==pending.expected_revision+1)throw messageError(unavailableMessage('GET',true));
    return {status:'committed',value:result.result};
   }
   return {status:result?.state==='not_found'?'not_found':'unknown'};
  },
  accept:value=>accept(s,value),confirmedError:error=>error.status>=400&&error.status<500,
  rejected:async error=>{
   revealFieldErrors(s);
   if(!s.pending&&error.code==='employee_configuration_conflict'){
    try{const latest=await request(s);if(owned(s))s.conflict=latest;}catch(readError){if(owned(s))s.error=readError.uiMessage||readError.message;}
   }
  },
  accepted:async checking=>{
   if(!checking)return;
   // Keep the confirmed receipt durable before attempting a newer read.
   persist(s);
   try{const latest=await request(s);if(!owned(s))return;
    if(latest?.revision<s.data.revision)throw Error('Stale configuration');accept(s,latest);
   }catch{if(owned(s))s.error=message('savedReloadFailed','配置已保存。当前显示已确认的版本。');}
  }
 },{receipt});
}
async function receipt(s=current()){if(!s?.pending||s.saving)return;
 const focused=document.activeElement===document.body||document.activeElement?.hasAttribute('data-config-receipt');
 const restoreFocus=()=>{
  if(!focused||!displayed(s)||document.activeElement!==document.body)return;
  const target=configQuery(s,'[data-config-receipt]:not(:disabled)','.employee-configuration-drawer ')||
    formFor(s)?.querySelector('[data-key]:not(:disabled)')||formFor(s)?.querySelector('.settings-section-toggle');
  target?.focus({preventScroll:true});
 };
 if(s.retry){await save(true,s);restoreFocus();return;}
 await configurationTransaction(s,true);restoreFocus();
}
function resourceTarget(s){return s.entry.chat_id?{chat_id:s.entry.chat_id}:s.entry.pipeline_reference?{pipeline_reference:JSON.stringify(s.entry.pipeline_reference),...(!s.entry.pipeline_own?{employee_source:s.entry.source.path}:{})}:s.entry.source?{source_id:s.entry.source.id,employee_source:s.entry.source.path}:{employee_id:Number(s.entry.work?.id||s.entry.asset?.id)};}
async function resourceRequest(s,field,body=null){
 const target='/api/employee-configuration/resources',params={...resourceTarget(s),field};
 if(S.localLibrary)return api(target+(body?'':'?'+new URLSearchParams(params)),body?'POST':'GET',body||undefined);
 let response,value;try{response=await fetch(target+(body?'':'?'+new URLSearchParams(params)),{method:body?'POST':'GET',headers:{'X-RunTeams-Device-Scope':s.deviceScope,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});value=await response.json();}
 catch(error){throw messageError(body?message('collectionUnconfirmed','尚未确认数据集合是否创建。你可以核对创建结果。'):message('resourcesUnavailable','无法读取资料。请重试。'));}
 if(!owned(s))throw Error('账户已改变。');if(!response.ok||value.error)throw Error(value.error||'数据集合暂时不可用。');return value;
}
async function editLocation(s,button){
 const input=button.closest('.field')?.querySelector('input[data-key]');
 if(s.locationPicker||!input||input.disabled||button.disabled||!formFor(s)?.contains(input))return;
 const key=input.dataset.key,previous=input.value,definition=s.data.definition_sha256;
 const currentInput=()=>displayed(s)&&s.data?.definition_sha256===definition?document.getElementById(fieldPrefix(s)+key):null;
 const kind=button.dataset.locationPick;
 let path;
 const target='/api/employee-configuration/pick-location',body={kind,language:globalThis.RunTeamsLocale?.language??'zh-CN'};
 s.locationPicker=true;button.disabled=true;
 try{
  let result;
  if(S.localLibrary)result=await api(target,'POST',body);
  else{
   const response=await fetch(target,{method:'POST',headers:{'Content-Type':'application/json','X-RunTeams-Device-Scope':s.deviceScope},body:JSON.stringify(body)});
   if(!response.ok)throw Error();
   result=await response.json();
  }
  if(result?.path===null)return;
  if(typeof result?.path!=='string'||!result.path)throw Error();
  path=result.path;
 }catch{
  if(currentInput())toast('无法选择本机位置，请重试。','err','configurationField.pickLocationFailed');
  return;
 }finally{s.locationPicker=false;button.disabled=false;}
 const field=currentInput();
 if(!field||!formFor(s)?.contains(field)||field.disabled||field.value!==previous||field.value===path)return;
 field.value=path;
 field.dispatchEvent(new Event('change',{bubbles:true}));
}
function chooseConnection(s,key){
 const field=s&&rows(s).find(f=>f.key===key),selection=s?.data?.connection_fields?.[key];if(!s||!field||!selection||s.saving||s.resourceBusy||s.pending||s.loading)return;
 capture(s);if(s.bindings[key])delete s.bindings[key];else s.bindings[key]=structuredClone(selection);
 s.draft=structuredClone(s.draft||s.data.values);s.error='';s.errors={};s.notice='';persist(s);paint(s);queueSave(s);
}
function credentialInput(s,key){return document.getElementById(fieldPrefix(s)+key);}
function updateCredentialField(s,key){
 if(!displayed(s))return;
 const input=credentialInput(s,key),row=input?.closest('.credential-field');
 if(!row)return;
 const focused=row.contains(document.activeElement),show=focused&&input.type==='text';
 const selection=focused&&document.activeElement===input?[input.selectionStart,input.selectionEnd]:null;
 const markup=fieldMarkup(s,rows(s).find(f=>f.key===key));
 const previous=painting;painting=true;
 try{row.outerHTML=markup;}finally{painting=previous;}
 const next=credentialInput(s,key);
 const edit=s.credentialEdits?.get(key);
 if(edit&&!next.disabled){
  RunTeamsConfigurationFields.restoreCredentialInput(next,edit,focused);
  if(show)next.parentElement.querySelector('[data-secret]')?.click();
  if(selection)next.setSelectionRange(...selection);
 }else if(focused)RunTeamsConfigurationFields.focusCredentialAction(next);
 window.RunTeamsLocale?.apply(next.closest('.credential-field'));
}
function queueCredential(s,key,value){
 if(!owned(s)||!s.data?.credential_fields?.[key]||s.saving||s.resourceBusy||s.pending||s.loading)return;
 const writes=s.credentialWrites??=new Map();
 if(writes.has(key)&&writes.get(key)===value)return;
 writes.set(key,value);
 if(rows(s).find(f=>f.key===key)?.file_input)updateCredentialField(s,key);
 else if(typeof value==='string'&&value){
  const input=credentialInput(s,key);
  if(input)input.readOnly=true;
 }
 const definition=s.data.definition_sha256;
 s.credentialQueue=(s.credentialQueue||Promise.resolve()).then(async()=>{
  if(!owned(s))return;
  try{
   const previous=s.data;
   const result=await request(s,'POST',{action:'credential',field:key,definition_sha256:definition,value,...(sourceTarget(s)?{employee_source:s.entry.source.path}:{})});
   if(!owned(s))return;
   const draft=s.draft,bindings=s.bindings;
   accept(s,result);
   if(draft){
    if(result.revision!==previous.revision+1){s.data=previous;s.bindings=bindings;s.conflict=result;paint(s);}
    else {
     if(result.bindings?.[key])bindings[key]=result.bindings[key];else delete bindings[key];
     s.bindings=bindings;
    }
   }
   if(s.credentialEdits?.get(key)===value||value==='')s.credentialEdits?.delete(key);
   if(s.credentialErrors)delete s.credentialErrors[key];
   delete s.errors[key];
   persist(s);
  }catch(error){
   if(owned(s))(s.credentialErrors??={})[key]=rows(s).find(f=>f.key===key)?.file_input?message('credentialFileRetry','未能保存密钥文件。请重新选择有效文件。'):message('credentialRetry','未能确认保存。请检查输入后按回车重试。');
  }finally{
   if(writes.get(key)===value)writes.delete(key);
   if(owned(s))updateCredentialField(s,key);
  }
 });
}
async function uploadCredentialFile(s,key,input){
 const file=input.files?.[0],field=rows(s).find(f=>f.key===key),definition=s.data.definition_sha256;
 input.value='';if(!file||!field?.file_input)return;
 if(!file.name.toLowerCase().endsWith(field.file_input.accept)||!file.size||file.size>8192){
  (s.credentialErrors??={})[key]=message('credentialFileInvalid','请选择有效的密钥文件，最多8 KB。');updateCredentialField(s,key);return;
 }
 try{
  const bytes=new Uint8Array(await file.arrayBuffer());
  if(!owned(s)||s.data.definition_sha256!==definition)return;
  const content_base64=btoa(String.fromCharCode(...bytes));
  queueCredential(s,key,{filename:file.name,content_base64});
 }catch(error){if(owned(s)){(s.credentialErrors??={})[key]=message('credentialFileRead','无法读取文件，请重新选择。');updateCredentialField(s,key);}}
}
async function pickResource(s,key,retry=false){if(!s||s.saving||s.resourceBusy||s.pending)return;capture(s);
 const focused=document.activeElement;
 const restoreFocus=focused===document.body||focused?.closest('.resource-field')?.dataset.field===key;
 const focusPicker=()=>{
  if(!restoreFocus||document.activeElement!==document.body||!displayed(s))return;
  const row=[...(formFor(s)?.querySelectorAll('.resource-field')||[])].find(node=>node.dataset.field===key);
  (row?.querySelector('[data-resource-retry]')||row?.querySelector('[data-expand], [data-reconnect]'))?.focus({preventScroll:true});
 };
 if(s.resourceOpen===key&&!retry){s.resourceOpen=null;paint(s);focusPicker();return;}
 s.resourceOpen=key;s.resourceBusy=true;s.resourceReadError=null;s.error='';paint(s);
 try{const result=await resourceRequest(s,key);if(owned(s)){if(!Array.isArray(result.items))throw messageError(message('invalidResources','无法读取资料列表。请重试。'));s.resourceChoices={...s.resourceChoices,[key]:result.items};}}
 catch(error){if(owned(s))s.resourceReadError=error.uiMessage||message('resourcesUnavailable','无法读取资料。请重试。');}
 finally{if(owned(s)){
  s.resourceBusy=false;paint(s);focusPicker();
  if(!s.error)queueSave(s);
 }}
}
async function createCollection(s,key){if(!s||s.saving||s.resourceBusy||s.pending)return;capture(s);
 if(s.resourcePending&&s.resourcePending.field!==key){s.error=message('checkOtherCollection','请先核对另一个数据集合是否已创建。');paint(s);return;}
 if(!s.resourcePending){const input=document.getElementById(collectionId(s,key)),name=input?.value?.trim();if(!name){s.error=message('collectionNameRequired','请输入集合名称。');paint(s);return;}
  s.resourcePending={...resourceTarget(s),...(s.entry.pipeline_reference?{pipeline_reference:s.entry.pipeline_reference}:{}),field:key,name,operation_id:crypto.randomUUID(),definition_sha256:s.data.definition_sha256};persist(s);}
 s.resourceBusy=true;s.error='';paint(s);
 try{const result=await resourceRequest(s,key,s.resourcePending);if(!owned(s))return;if(!result.selection?.collection_id)throw messageError(message("invalidCollectionResponse","尚未确认集合是否创建。请核对创建结果。"));
  s.bindings[key]=result.selection;s.draft=structuredClone(s.draft||s.data.values);s.resourcePending=null;s.resourceOpen=null;s.notice='';persist(s);
 }catch(error){if(owned(s))s.error=error.uiMessage||error.message;}
 finally{if(owned(s)){s.resourceBusy=false;paint(s);if(!s.error)queueSave(s);}}
}
async function pick(s,key){const field=s&&rows(s).find(f=>f.key===key);if(!s||s.saving||s.pending||!field)return;
 if(field.binding.provider==='local_collection'||field.binding.provider==='sdk_resource'&&['document','collection'].includes(field.binding.resource_kind))return pickResource(s,key);
 capture(s);s.saving=true;s.error='';paint(s);
 try{if(!S.appInfo?.native_attachment_picker)throw messageError(message("desktopPicker","请在这台电脑的 RunTeams 应用中选择资料。"));
  const picked=await api('/api/local-references/pick','POST',{kind:field.binding.resource_kind});if(!owned(s))return;if(picked.error)throw Error(picked.error);
  const references=picked.references||[];if(picked.pending?.length){const result=await api('/api/local-references/confirm','POST',{tokens:picked.pending.map(p=>p.token)});if(!owned(s))return;if(result.error)throw Error(result.error);references.push(...(result.references||[]));}
  const reference=references.find(r=>r.local_kind===field.binding.resource_kind);if(!reference)return;s.bindings[key]={grant_id:reference.grant_id,name:reference.name,kind:reference.local_kind};s.draft=structuredClone(s.draft||s.data.values);s.notice='';persist(s);
 }catch(error){if(owned(s))s.error=error.uiMessage||error.message;}
 finally{if(owned(s)){s.saving=false;paint(s);if(!s.error)queueSave(s);}}
}
function merge(s){if(!s?.conflict)return;const old=s.data,local=s.draft||old.values,remote=s.conflict;
 const index=new Map(remote.definition.groups.flatMap(g=>g.fields).map(f=>[f.key,f]));
 if(ordinary(s).some(f=>JSON.stringify(local[f.key])!==JSON.stringify(old.values[f.key])&&index.get(f.key)?.type!==f.type)){s.error=message('fieldsChanged','配置项已变更。你的修改仍在，请先查看创作者的更新。');paint(s);return;}
 const next=structuredClone(remote.values);for(const field of ordinary(s))if(JSON.stringify(local[field.key])!==JSON.stringify(old.values[field.key]))next[field.key]=local[field.key];
 const bindings=structuredClone(remote.bindings||{});for(const key of new Set([...Object.keys(old.bindings||{}),...Object.keys(s.bindings)])){
  if(JSON.stringify(s.bindings[key])!==JSON.stringify(old.bindings?.[key])){if(s.bindings[key])bindings[key]=s.bindings[key];else delete bindings[key];}
 }
 accept(s,remote);s.bindings=bindings;s.draft=RunTeamsConfigurationForm.draft(ordinary(s),next,remote.values,bindings,remote.bindings||{});s.conflict=null;s.errors={};s.error='';persist(s);paint(s);queueSave(s);
}
function clearNotice(s){if(s.notice){s.notice='';const notice=configQuery(s,'.configuration-notice');if(notice)notice.textContent='';}}
document.addEventListener('input',event=>{const s=current(event.target),key=event.target.dataset?.key;if(!s||!event.target.closest('#'+formId(s)))return;
 if(s&&key&&event.target.closest('.credential-field')){if(event.target.type==='file')return;const edits=s.credentialEdits??=new Map();if(event.target.value.trim()&&!RunTeamsConfigurationFields.isUnchangedCredential(event.target))edits.set(key,event.target.value);else edits.delete(key);return;}
 if(event.target.dataset?.collectionName){s.collectionNames={...s.collectionNames,[event.target.dataset.collectionName]:event.target.value};return;}
 RunTeamsConfigurationForm.cancelSave(s);capture(s);clearNotice(s);
});
document.addEventListener('change',event=>{const s=current(event.target),key=event.target.dataset?.key;if(!s||!event.target.closest('#'+formId(s)))return;
 if(event.target.matches('.credential-file-field input[type=file]')){void uploadCredentialFile(s,key,event.target);return;}
 if(event.target.closest('.credential-field')||event.target.dataset?.collectionName)return;
 if(event.target.closest('[data-picker]')&&s.resourceChoices?.[key]){if(s.saving||s.resourceBusy||s.pending)return;const selected=s.resourceChoices[key].find(c=>String(c.collection_id||c.document_id)===event.target.value);if(selected){capture(s);s.bindings[key]=structuredClone(selected);s.draft=structuredClone(s.draft||s.data.values);s.resourceOpen=null;s.notice='';persist(s);paint(s);queueSave(s);return;}}
 capture(s);clearNotice(s);queueSave(s);
});
document.addEventListener('scroll',event=>{if(event.target?.matches?.('.employee-configuration-drawer > .right-detail-scroll')&&current())current().scroll=event.target.scrollTop;},true);
document.addEventListener('click',event=>{const s=current(event.target),button=event.target.closest('button');
 if(s&&button?.matches('[data-location-pick]')){void editLocation(s,button);return;}
 if(!s||!button||!button.closest('.employee-configuration-drawer,[data-signing-configuration]'))return;
 if(button.matches('[data-employee-app-retry],[data-employee-app-add],[data-employee-app-connect],[data-employee-app-menu]'))return applicationAction(s,button);
 if(button.dataset.expand||button.dataset.reconnect)void pick(s,button.dataset.expand||button.dataset.reconnect);
 if(button.dataset.resourceRetry)void pickResource(s,button.dataset.resourceRetry,true);
 if(button.dataset.collectionCreate)void createCollection(s,button.dataset.collectionCreate);
 if(button.dataset.connect)chooseConnection(s,button.dataset.connect);
 if(button.dataset.credentialFile)credentialInput(s,button.dataset.credentialFile)?.click();
 if(button.hasAttribute('data-config-read'))void read(s);
 if(button.hasAttribute('data-check')&&!s.saving&&!s.pending&&!s.resourceBusy)void read(s);
 if(button.hasAttribute('data-config-receipt'))void receipt(s);
 if(button.hasAttribute('data-config-merge'))merge(s);
});
async function revealCredential(s,key){
 const data=s.data;
 if(!displayed(s)||!data||s.loading||s.saving||s.pending||s.credentialWrites?.has(key))return null;
 const reply=await request(s,'POST',{action:'reveal-credential',field:key,definition_sha256:data.definition_sha256,
  ...(sourceTarget(s)?{employee_source:s.entry.source.path}:{})});
 return displayed(s)&&s.data===data?reply.value:null;
}
RunTeamsConfigurationFields.bindCredentialEditor(target=>{
 const s=current(target);return !painting&&s&&formFor(s)?.contains(target)?s:null;
},(s,key,value)=>queueCredential(s,key,value),revealCredential);
document.addEventListener('submit',event=>{const s=current(event.target);if(s&&event.target.id===formId(s)){event.preventDefault();capture(s);queueSave(s);}});
window.addEventListener('runteams:business-scope-will-change',()=>{if(document.querySelector('[data-employee-app-dialog]'))closeChildDialog();sessions.clear();active=null;});
async function showOnboarding(panel){
 const entry=workTarget(panel);
 if(!entry||panel.messages?.length||panel.busy||panel.onboardingChecked)return;
 panel.onboardingChecked=true;
 const s=sessionFor(entry),selected=S.sel;
 const currentPanel=()=>owned(s)&&S.conversationPanel===panel&&S.sel===selected&&!panel.messages?.length&&!panel.busy;
 const seenKey='runteams.employee.onboarding:'+JSON.stringify([RunTeamsEmployeeDirectory.referenceKey(entry.reference),entry.definition_revision]);
 const deviceSeenKey=(S.localLibrary?.library_id||deviceScope())&&JSON.stringify([RunTeamsHost.session.storageScope(S),seenKey]);
 const seen=()=>{try{return (deviceSeenKey&&localStorage.getItem(deviceSeenKey)==='1')||RunTeamsBusinessStorage.getItem(seenKey)==='1';}catch{return false;}};
 function remember(){
  if(!currentPanel())return;
  try{if(deviceSeenKey)localStorage.setItem(deviceSeenKey,'1');else RunTeamsBusinessStorage.setItem(seenKey,'1');}catch{}
 }
 let model;
 try{
  if(seen())return;
  model=await request(s);
  if(RunTeamsEmployeeDirectory.referenceKey(model?.reference)!==RunTeamsEmployeeDirectory.referenceKey(entry.reference)||model?.definition_revision!==entry.definition_revision)return;
 }catch{panel.onboardingChecked=false;return;}
 if(!currentPanel()||document.getElementById('modalHost')||document.getElementById('childModalHost')||seen()){panel.onboardingChecked=false;return;}
 const all=model?.definition?.onboarding;
 if(!Array.isArray(all)||!all.length)return;
 const index=new Map(model.definition.groups.flatMap(group=>group.fields).map(field=>[field.key,field]));
 const requirements=new Map((model.definition.application_requirements||[]).map(item=>[item.key,item]));
 const appEntry=RunTeamsEmployeeDirectory.forPanel(panel);
 const appSession=appEntry&&sessionFor(appEntry);
 const connections=new Map(), candidates=new Map();
 async function readCandidates(requirement){
  const status=await accountComposioRequest({},'status');
  if(!status.configured)throw Error(copy('appsSetupFirst','请先在工具设置中配置 Composio。'));
  const {items}=await accountComposioRequest(status,'compatible-applications',{operations:requirement.operations,toolkit:requirement.toolkit||''});
  return await Promise.all(items.map(async item=>{
   const {accounts}=await accountComposioRequest(status,'accounts',{toolkit:item.slug});
   return {row:{provider:'composio',id:item.slug,name:item.name,logo:item.logo},
    accounts:accounts.filter(account=>account.status==='ACTIVE'&&!account.disabled)};
  }));
 }
 if(appSession&&all.some(step=>step.application)){
  try{await readApplicationBindings(appSession);}catch{panel.onboardingChecked=false;return;}
  if(!currentPanel())return;
  try{
   for(const step of all.filter(item=>item.application)){
    const requirement=requirements.get(step.application);
    const bound=applications(appSession).filter(row=>row.provider==='composio'&&row.account?.id&&(!requirement.toolkit||requirement.toolkit===row.id));
    if(!bound.length)continue;
    if(requirement.toolkit){connections.set(step.application,bound[0]);continue;}
    const compatible=await readCandidates(requirement);candidates.set(step.application,compatible);
    const chosen=bound.find(row=>compatible.some(candidate=>candidate.row.id===row.id&&candidate.accounts.some(account=>account.id===row.account.id)));
    if(chosen)connections.set(step.application,chosen);
   }
  }catch{}
 }
 if(!currentPanel()||document.getElementById('modalHost')||document.getElementById('childModalHost')){panel.onboardingChecked=false;return;}
 const initiallyConnected=new Set(connections.keys());
 const visible=()=>{
  const hasSetup=step=>step.questions.length||step.application;
  const steps=all.map(step=>({...step,application:appSession&&!initiallyConnected.has(step.application)?step.application:null}))
   .filter((step,i)=>step.application||step.questions.some(question=>['missing','needs_review'].includes(model.states[question.field]))||!hasSetup(all[i]));
  return all.some(hasSetup)&&!steps.some(hasSetup)?[]:steps;
 };
 const empty=value=>value==null||typeof value==='string'&&!value.trim()||Array.isArray(value)&&!value.length;
 const comparable=value=>empty(value)?null:Array.isArray(value)?JSON.stringify([...value].sort()):value;
 const initialValues=steps=>Object.fromEntries(steps.flatMap(step=>step.questions)
  .filter(question=>model.states[question.field]==='configured'&&Object.hasOwn(model.values||{},question.field))
  .map(question=>[question.field,model.values[question.field]]));
 let steps=visible(),position=0,base=initialValues(steps),values=structuredClone(base),errors={},busy=false,host=null,pending=null;
 if(!steps.length)return;
 const t=(key,text,vars={})=>window.RunTeamsLocale?.t('employeeOnboarding.'+key,vars,text)??text;
 function finish(){
  remember();
  if(host?.isConnected)closeChildDialog();
 }
 function fields(){
  return steps[position].questions.map(question=>({...index.get(question.field),label:question.prompt,
   placeholder:question.placeholder,helpTooltip:false,showRequiredHint:false}));
 }
 const controls=RunTeamsConfigurationFields.create({
  icon:ICON,idPrefix:'employee_onboarding_',
  singleSelect:(id,items,selected,_change,{disabled,required,accessibleAttrs})=>'<select class="inp" id="'+esc(id)+'" data-key="'+esc(id.slice('employee_onboarding_'.length))+'" '+accessibleAttrs+
   (disabled?' disabled':'')+(required?' aria-required="true"':'')+'><option value="">'+esc(t('choose','选一项'))+'</option>'+
   items.map(({value,label})=>'<option value="'+esc(value)+'"'+(value===selected?' selected':'')+'>'+esc(label)+'</option>').join('')+'</select>'
 });
 function capture(){
  if(!host?.isConnected)return;
  for(const el of host.querySelectorAll('select[data-key]'))el.dataset.value=el.value;
  values=controls.collect(fields(),host,values);
 }
 async function applicationPicker(requirement){
  capture();
  if(!currentPanel()||!host?.isConnected)return;
  let status,list;
  const current=()=>currentPanel()&&!!status?.isConnected;
  const buttons=()=>list?list.querySelectorAll('button'):[host.querySelector('[data-guide-application]')];
  function showError(error){status.textContent=error;status.setAttribute('role','alert');}
  async function bind(row,account){
   const controls=buttons();
   if(!current())return;
   for(const button of controls)button.disabled=true;
   const next={...row,account:{id:account.id,name:account.name}};
   try{
    const result=await accountMcpTestRequest({action:'employee-apps-set',employee:employeeApplicationReference(appEntry),row:next,remove:false});
    publishApplicationBindings(appSession,result.applications);
    if(!current())return;
   }finally{
    for(const button of controls)button.disabled=false;
   }
   connections.set(requirement.key,next);
   if(position===steps.length-1&&steps.every(step=>!step.questions.length&&(!step.application||connections.has(step.application))))remember();
   errors={};
   paint();
  }
  function authorize(row){
   connectEmployeeComposio(appSession,row,true,{
    current,complete:account=>bind(row,account),error:showError,
    status:state=>{
     if(!current())return;
     for(const button of buttons())button.disabled=!!state;
     if(!state)return;
     status.setAttribute('role','status');
     status.textContent=copy(state.label.key,state.label.fallback);
     if(state.url){
      const link=document.createElement('a');link.href=state.url;link.target='_blank';link.rel='noopener noreferrer';
      link.textContent=toolsText('composioAuthorize','前往授权');status.append(' ',link);
     }
    }
   });
  }
  if(requirement.toolkit){
   status=host.querySelector('[data-guide-auth-status]');
   authorize({provider:'composio',id:requirement.toolkit,name:requirement.label});
   return;
  }
  const title=t('chooseApp','选择应用');
  const guide=host;
  const options={className:'employee-app-picker employee-guide-app-picker',title,showClose:false,scrimHandler:'void 0',scrimClass:'employee-onboarding-scrim',
   attrs:'role="dialog" aria-modal="true" aria-label="'+esc(title)+'"',
   headerHtml:'<div class="employee-app-picker-heading"><div class="tt">'+esc(title)+'</div><p class="employee-app-picker-target">'+esc(requirement.label)+'</p></div>'+
    '<button type="button" class="x modal-x" data-guide-picker-back aria-label="'+esc(t('back','上一步'))+'">'+ICON('x')+'</button>',
   body:'<div class="employee-app-picker-scroll" data-guide-app-list></div><p data-guide-app-status role="status"></p>'};
  replaceChildDialog(options);
  list=guide.querySelector('[data-guide-app-list]');status=guide.querySelector('[data-guide-app-status]');
  const back=guide.querySelector('[data-guide-picker-back]');
  back.onclick=paint;back.focus();
  function rowMarkup(row,detail,action){
   return '<div class="employee-app-picker-row">'+applicationMark(row)+'<span class="employee-application-name"><strong>'+esc(row.name)+'</strong><small>'+
    esc(detail)+'</small></span><div class="employee-app-picker-action"><button type="button" class="btn">'+esc(action)+'</button></div></div>';
  }
  try{
   status.textContent=t('loadingApps','正在读取可用应用…');
   const compatible=candidates.get(requirement.key)||await readCandidates(requirement);
   if(!current())return;
   status.textContent='';
   if(!compatible.length){status.textContent=t('noApps','暂时没有符合要求的应用。');return;}
   const actions=[];
   const markup=[];
   for(const {row,accounts} of compatible){
    for(const account of accounts){
     markup.push(rowMarkup(row,account.name,t('useApp','使用')));
     actions.push(()=>bind(row,account).catch(error=>{if(current())showError(error.message);}));
    }
    if(accounts.length)continue;
    markup.push(rowMarkup(row,t('newAccount','连接新账号'),t('connectApp','连接')));
    actions.push(()=>authorize(row));
   }
   list.innerHTML=markup.join('');
   [...list.querySelectorAll('button')].forEach((button,i)=>button.onclick=actions[i]);
  }catch(error){if(current())showError(error.message);}
 }
 function paint(){
  if(!currentPanel())return;
  const step=steps[position],last=position===steps.length-1,application=requirements.get(step.application),connection=connections.get(step.application);
  const progress=steps.length>1?'<div class="employee-onboarding-progress" aria-label="'+
   esc(t('step','第 {current} 步，共 {total} 步',{current:position+1,total:steps.length}))+'" role="img">'+
   steps.map((_,i)=>'<span aria-hidden="true"'+(i<=position?' class="is-reached"':'')+'></span>').join('')+'</div>':'';
  const buttons=(position?'<button type="button" class="btn ghost" data-guide-back>'+esc(t('back','上一步'))+'</button>':'')+
   (step.questions.length||application||steps.length>1?'<button type="button" class="btn ghost" data-guide-skip>'+esc(t('later','稍后再说'))+'</button>':'')+
   '<button type="button" class="btn pri" data-guide-next>'+esc(busy?t('saving','保存中…'):errors._form?t('retry','重新保存'):!last?t('next','下一步'):steps.some(row=>row.questions.length)?t('start','开始使用'):application?t('finish','完成'):t('done','知道了'))+'</button>';
  const options={attrs:'role="dialog" aria-modal="true" aria-labelledby="employee-onboarding-title"'+
   (step.description?' aria-describedby="employee-onboarding-description"':''),showClose:false,
   scrimHandler:'void 0',closeOnScrim:false,className:'employee-onboarding-dialog',scrimClass:'employee-onboarding-scrim',
   body:'<div class="employee-onboarding-intro"><h2 id="employee-onboarding-title">'+esc(step.title)+'</h2>'+
    (step.description?'<p id="employee-onboarding-description">'+esc(step.description)+'</p>':'')+'</div>'+
    fields().map(field=>controls.field({...field,disabled:busy},values[field.key],errors[field.key])).join('')+
    (application?applicationRow(connection||{provider:'composio',id:application.toolkit,name:application.label},
     (connection?applicationAccountLabel(connection.account.name):'')+
     '<button type="button" class="btn" data-guide-application>'+esc(connection?t('changeApp','更换连接'):t('connectApp','连接'))+'</button>'):'')+
    (application?.toolkit?'<p class="employee-guide-auth-status" data-guide-auth-status role="status"></p>':'')+
    (errors._form?'<p role="alert" class="error">'+esc(errors._form)+'</p>':''),footer:progress+'<div class="employee-onboarding-actions">'+buttons+'</div>'};
  if(host?.isConnected)replaceChildDialog(options);
  else{
   host=openChildDialog({...options,manageFocus:true});
   host.addEventListener('keydown',event=>{
    if(event.isComposing||busy)return;
    if(event.key==='Escape'){
     event.preventDefault();event.stopPropagation();
     const pickerBack=host.querySelector('[data-guide-picker-back]');
     if(pickerBack)pickerBack.click();else finish();
    }
    if(event.key==='Enter'&&event.target.matches('input[type="text"]')){
     event.preventDefault();host.querySelector('[data-guide-next]')?.click();
    }
   });
  }
  for(const button of host.querySelectorAll('button'))button.disabled=busy;
  const onBack=host.querySelector('[data-guide-back]'),onSkip=host.querySelector('[data-guide-skip]');
  if(onBack)onBack.onclick=()=>{capture();position--;paint();};
  if(onSkip)onSkip.onclick=finish;
  const next=host.querySelector('[data-guide-next]');
  next.onclick=advance;
  if(application&&!connection)next.disabled=true;
  const appButton=host.querySelector('[data-guide-application]');
  if(appButton)appButton.onclick=()=>applicationPicker(application);
  (host.querySelector('[aria-invalid="true"]')||host.querySelector('input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [data-guide-application], [data-guide-next]:not([disabled])'))?.focus();
 }
 async function advance(){
  if(busy||!currentPanel())return;
  capture();
  if(steps[position].application&&!connections.has(steps[position].application))return;
  errors={};
  for(const f of fields())if(f.required&&empty(values[f.key]))errors[f.key]=
   ['select','multiselect','checklist'].includes(f.type)?t('missingChoice','请至少选一项。'):t('missingText','这项还没填。');
  if(Object.keys(errors).length){paint();return;}
  if(position<steps.length-1){position++;paint();return;}
  const supplied=Object.fromEntries(Object.entries(values).filter(([key,value])=>comparable(value)!==comparable(base[key]))
   .map(([key,value])=>[key,empty(value)?null:value]));
  if(!Object.keys(supplied).length){finish();return;}
  const prior=JSON.stringify(supplied);
  if(!pending||pending.valuesKey!==prior)pending={valuesKey:prior,body:{action:'save-onboarding',operation_id:crypto.randomUUID(),
   expected_revision:model.revision,definition_sha256:model.definition_sha256,values:supplied}};
  busy=true;paint();
  try{
   const saved=await request(s,'POST',pending.body);
   if(!s.loading&&!s.saving&&!s.pending&&!s.draft&&!s.resourcePending&&(!s.data||saved.revision>=s.data.revision))accept(s,saved);
   if(currentPanel())finish();
  }catch(error){
   if(!currentPanel())return;
   errors=error.fields||{_form:error.uiMessage?.fallback||error.message};
   if(error.status===409){
    try{
     const fresh=await request(s);
     if(!currentPanel())return;
     if(fresh.definition_sha256!==model.definition_sha256){errors={_form:t('changed','引导内容已更新，请重新打开员工。')};return;}
     const previousBase=base;
     model=fresh;
     steps=visible();base=initialValues(steps);pending=null;
     const keys=new Set(steps.flatMap(step=>step.questions.map(question=>question.field)));
     values={...base,...Object.fromEntries(Object.entries(supplied).filter(([key])=>keys.has(key)&&
      comparable(base[key])===comparable(previousBase[key])))};
     if(!steps.length){finish();return;}
     position=Math.min(position,steps.length-1);
     errors={_form:t('settingsUpdated','员工设置已更新。请核对当前内容后继续。')};
    }catch{}
   }
   const errorStep=steps.findIndex(step=>step.questions.some(question=>errors[question.field]));
   if(errorStep!==-1)position=errorStep;
  }finally{
   busy=false;
   if(host?.isConnected&&currentPanel())paint();
  }
 }
 paint();
}

window.RunTeamsEmployeeConfiguration={showOnboarding,prepareApplications,workTarget,open,openConversation,mountInline,mountGroup,groupParts,toggleSection,embeddedSettings,inlineParts,holdInlineInput,restore,required,current,drawer,decorateHeader,capture,leave,close,closeState,read,save,receipt,resources};
})();
