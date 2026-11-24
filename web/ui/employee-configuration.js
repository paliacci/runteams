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
const deviceScope=()=>RunTeamsHost.employeeConfiguration.scope(S);
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
 if(binding?.schema!=='runteams.bound-employee/v1'||!['runteams.acquired-employee-reference/1','runteams.rented-employee-reference/1'].includes(reference?.schema)||!/^r-[a-f0-9]{64}$/.test(binding.source_revision||''))return null;
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
 let value;
 try{
  value=s.entry.pipeline_reference
   ?await RunTeamsSourcePipelinePanels.configurationRequest(s,method,body,receipt)
   :await RunTeamsHost.employeeConfiguration.request(target,method,body,s.deviceScope);
 }catch(error){
  if(!owned(s))throw Error('账户或员工已改变。');
  throw responseError(error,error.status,method,receipt);
 }
 if(!owned(s))throw Error('账户或员工已改变。');
 if(value?.error)throw responseError(value,value.status,method,receipt);
 return value;
}
async function read(s=active){if(s?.credentialQueue)await s.credentialQueue;if(!owned(s)||s.loading)return;s.loading=true;s.error='';paint(s);
 try{const value=await request(s);if(!owned(s))return;const draft=s.draft,bindings=s.bindings;
  if(!Number.isInteger(value?.revision)||s.data&&value.revision<s.data.revision)throw messageError(unavailableMessage('GET',false));
  if(draft&&s.data&&(value.revision!==s.data.revision||value.definition_sha256!==s.data.definition_sha256)){s.conflict=value;s.notice=message('changed','配置已更新。你的修改仍在。');}
  else{accept(s,value);if(draft){s.draft=draft;s.bindings=bindings;}s.notice='';}}
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
 paint(s);if(!s.pending)await read(s);
}
function mountGroup(entries,selection){
 if(!selection||S.sel!==selection)return;
 const previous=inlineGroups.get(selection);
 if(previous&&entries.length===previous.byKey.size&&entries.every(entry=>{
  const session=previous.byKey.get(entry.key);
  return owned(session)&&session.entry.configurationRevision===entry.configurationRevision;
 }))return;
 const byKey=new Map(),byId=new Map(),added=[];
 for(const entry of entries){
  const previousSession=previous?.byKey.get(entry.key),previousEntry=owned(previousSession)?previousSession.entry:null;
  const s=sessionFor(entry);
  s.inlineId||=String(++inlineSequence);
  byKey.set(entry.key,s);byId.set(s.inlineId,s);
  if(!previousEntry||previousEntry.configurationRevision!==entry.configurationRevision)added.push(s);
 }
 inlineGroups.set(selection,{byKey,byId});
 for(const s of added)if(!s.pending)void read(s);
 if(!added.length||added.every(s=>s.pending||s.loading))render();
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
 if(!owned(s))return '<section>'+ownerHeading+RunTeamsSkeletons.region('detail',undefined,'employeeSettings.loading')+'</section>';
 const {content,footer}=formParts(s,owner);
 mountInputs(s);
 return '<section class="pipeline-configuration-session" data-config-session="'+s.inlineId+'">'+content+footer+'</section>';
}
function restore(){if(!owned(active))return;selectDetailWorkspace({type:'employee-configuration',id:active.entry.key});paint();}
async function required(error,chatId){
 const panel=String(S.conversationPanel?.id)===String(chatId)?S.conversationPanel:String(S.chatId)===String(chatId)?{id:S.chatId,context:S.chatCfg?.context,kind:'general'}:null;
 if(panel?.context?.pipeline_work||panel?.context?.source_pipeline_workspace){toast('请在流水线设置中完成配置。','info','employeeSettings.configurePipeline');return true;}
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
  detailDrawerHeading(title||copy(s.entry.pipeline_own?'pipeline':'title',s.entry.pipeline_own?'流水线配置':'员工设置'),employee.description||'','','',{titleKey:title?undefined:titleKey,titleLeading,descriptionMarkdown:true});
 const intro='<section class="workspace-detail-head detail-drawer-intro">'+heading+'</section>';
 mountInputs(s);
 return {intro,...formParts(s)};
}
function drawer(){const s=current();if(!s)return '';
 const {intro,content,footer}=settingsParts(s);
 const heading={toolbar:RunTeamsEmployeeDrawerHeader.markup('configuration'),intro};
 return detailDrawerShell({className:'employee-configuration-drawer',header:heading,introClass:'detail-drawer-summary',body:content+footer,bodyClass:'employee-configuration-body settings-section-stack',attrs:'data-app-i18n-aria-label="employeeSettings.'+(s.entry.pipeline_own?'pipeline':'title')+'" aria-label="'+esc(s.entry.pipeline_own?copy('pipeline','流水线配置'):copy('title','员工设置'))+'"'+(s.loading?' aria-busy="true"':'')});
}
function embeddedSettings(){
 const s=current();if(!s||S.sel?.type!=='creator-assets')return '';
 const {intro,content,footer}=settingsParts(s);
 return '<section class="creator-asset-settings employee-configuration-drawer" aria-label="员工设置" data-app-i18n-aria-label="employeeSettings.title"'+(s.loading?' aria-busy="true"':'')+'><div class="right-detail-scroll" tabindex="-1"><div class="detail-drawer-summary">'+intro+'</div><div class="employee-configuration-body settings-section-stack">'+content+footer+'</div></div></section>';
}
function formParts(s,groupOwner=null){
 const groups=(s.data?.definition.groups||[]).filter(group=>group.fields.length);
 let content=!s.data&&!s.error?RunTeamsSkeletons.region('detail',undefined,'employeeSettings.loading'):'';
 if(s.data){
  if(s.entry.chat_id)content+='<p class="configuration-readiness" data-app-i18n="employeeSettings.workScope">已开始的工作会继续使用原配置。</p>';
  if(!groups.length&&!s.loading&&!s.error)content+='<p class="configuration-readiness" data-app-i18n="employeeSettings.emptyConfiguration">没有可配置的选项。</p>';
   const fields=RunTeamsConfigurationForm.groups({groups,idFor:group=>groupSectionId(s,group),
   renderField:field=>fieldMarkup(s,field),collapsedSections:s.collapsedSections,
   action:'RunTeamsEmployeeConfiguration.toggleSection'});
  content+=RunTeamsConfigurationForm.markup({id:formId(s),body:fields+conflictMarkup(s)});
 }
 if(s.error){
  const reload=s.pending||s.error.key==='reopenSettings'?'':' <button type="button" class="textbutton" data-config-read data-app-i18n="employeeSettings.reload">重新读取</button>';
  content+='<div class="configuration-error" role="alert">'+messageMarkup(s.error)+reload+'</div>';
 }
 if(s.errors?._form)content+='<p class="configuration-error" role="alert">'+fieldErrorMarkup(s.errors._form)+'</p>';
 if(s.notice)content+='<p class="configuration-notice" role="status" tabindex="-1">'+messageMarkup(s.notice)+'</p>';
 if(groupOwner&&!groups.length)content=pipelineGroupHeading(groupOwner.name,groupOwner.labelKey)+content;
 content+=RunTeamsWorkAuthorization.settings(s.entry);
 const footer=s.data?RunTeamsConfigurationForm.footer({state:s,receiptAttrs:'data-config-receipt',inline:true}):'';
 return {content,footer};
}
function inlineParts(key){
 const s=current();
 if(!s?.inlineSelection||s.entry.key!==key||s.data&&!rows(s).length&&!s.error)return null;
 const {content,footer}=formParts(s);
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
 let value;
 try{
  value=await RunTeamsHost.employeeConfiguration.request(target+(body?'':'?'+new URLSearchParams(params)),
   body?'POST':'GET',body,s.deviceScope);
 }catch(error){
  if(!owned(s))throw Error('账户或员工已改变。');
  if(error.status)throw error;
  throw messageError(body?message('collectionUnconfirmed','尚未确认数据集合是否创建。你可以核对创建结果。'):message('resourcesUnavailable','无法读取资料。请重试。'));
 }
 if(!owned(s))throw Error('账户或员工已改变。');
 return value;
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
document.addEventListener('click',event=>{const s=current(event.target),button=event.target.closest('button');if(!s||!button||!button.closest('.employee-configuration-drawer,[data-signing-configuration]'))return;
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
window.addEventListener('runteams:business-scope-will-change',()=>{sessions.clear();active=null;});
window.RunTeamsEmployeeConfiguration={workTarget,open,openConversation,mountInline,mountGroup,groupParts,toggleSection,embeddedSettings,inlineParts,holdInlineInput,restore,required,current,drawer,decorateHeader,capture,leave,close,closeState,read,save,receipt,resources};
})();
