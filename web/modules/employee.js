/* SDK employee metadata/settings host. Business views belong to the isolated SDK host. */
let _coreEmployeeEditorReturn=null,_coreEmployeeEditor=null,_employeeBusinessScopeSequence=0;
const _employeeSummarySequences=new Map();
let _employeeSettingsHeader=null;
const _employeeSourceWrites=new Map();
/* module-function:employeeResetBusinessScope */
function employeeResetBusinessScope(){
  ++_employeeBusinessScopeSequence;
  _employeeSummarySequences.clear();_employeeSourceWrites.clear();
  _coreEmployeeEditor=null;_coreEmployeeEditorReturn=null;
  _employeeSettingsHeader?.dispose();_employeeSettingsHeader=null;
}
if(typeof window!=='undefined')window.addEventListener?.('runteams:business-scope-changed',employeeResetBusinessScope);
/* module-function:employeeAssertBusinessScope */
function employeeAssertBusinessScope(sequence){if(sequence!==_employeeBusinessScopeSequence){const error=new Error('工作区或账户已切换，请重新打开员工设置');error.code='business_scope_changed';throw error;}}

/* module-function:employeeScopedApi */
async function employeeScopedApi(path,method,body,sequence=_employeeBusinessScopeSequence){employeeAssertBusinessScope(sequence);try{const result=await (RunTeamsHost.assets.request?RunTeamsHost.assets.request(path,method,body):api(path,method,body));employeeAssertBusinessScope(sequence);return result;}catch(error){employeeAssertBusinessScope(sequence);throw error;}}

/* module-function:employeeCanEdit */
function employeeCanEdit(item){return item?.editable===true;}
function employeeUsesFolder(item){return item?.source_mode==='folder';}
/* module-function:downloadedEmployeeSummary */
function downloadedEmployeeSummary(id){
  if(RunTeamsHost.session.workspace(S)||!RunTeamsHost.session.ready(S)||false||S.deviceSessionActor!==String(RunTeamsHost.session.actor(S)||''))return null;
  const item=RunTeamsEmployeeDirectory.downloaded().find(row=>Number(row.id)===Number(id)&&row.schema==='runteams.downloaded-employee/v1');
  return item?{...item,editable:false}:null;
}

/* module-function:employeeSummary */
function employeeSummary(id){const entry=RunTeamsEmployeeDirectory.entryFor(id);if(entry)return entry.record;const current=RunTeamsEmployeeDirectory.assets().find(row=>Number(row.id)===Number(id));return current?.schema==='runteams.downloaded-employee/v1'?downloadedEmployeeSummary(id):current||downloadedEmployeeSummary(id);}

function employeeSettingsTargetId(id){
  id=Number(id);const local=downloadedEmployeeSummary(id),ref=local?.native_asset?.employee_reference;
  if(!ref||RunTeamsHost.session.workspace(S))return id;
  const fields=['schema','deployment_id','workspace_id','data_epoch','resource','id'];
  const owned=RunTeamsEmployeeDirectory.assets().find(row=>row.schema==='runteams.native-employee-summary/v1'&&row.editable===true&&fields.every(k=>row.reference?.[k]===ref[k]));
  return owned?Number(owned.id):id;
}

/* module-function:employeeApiResult */
function employeeApiResult(result){if(result?.error){const error=new Error(result.error);error.code=result.code;throw error;}return result;}

/* module-function:loadCoreEmployeeDetail */
async function loadCoreEmployeeDetail(id){
  const local=employeeSummary(id);if(local?.schema==='runteams.downloaded-employee/v1')return local;
  const scope=_employeeBusinessScopeSequence;id=Number(id);const seq=(_employeeSummarySequences.get(id)||0)+1;_employeeSummarySequences.set(id,seq);
  const result=employeeApiResult(await employeeScopedApi(`/api/core/employees/${id}`,undefined,undefined,scope));
  if(result?.schema!=='runteams.native-employee-summary/v1'||Number(result.id)!==id||typeof result.editable!=='boolean')throw new Error('员工设置服务尚未接通，请稍后重试');
  if(_employeeSummarySequences.get(id)===seq){RunTeamsEmployeeDirectory.upsertAsset(result);if(!employeeCanEdit(result)&&Number(_coreEmployeeEditor?.id)===id)_coreEmployeeEditor.editable=false;}
  return result;
}

function employeeIdentityError(key,message){
  return Object.assign(new Error(message),{messageKey:"employeeSettings."+key});
}

/* module-function:employeeWrite */
async function employeeWrite(value,change){
 const entry=RunTeamsEmployeeDirectory.entryFor(value)||RunTeamsEmployeeDirectory.assetEntry(value);if(!entry)throw employeeIdentityError('missingEmployee','找不到这名员工。');
 const sequence=_employeeBusinessScopeSequence,previous=_employeeSourceWrites.get(entry.key)||Promise.resolve();
 const pending=previous.catch(()=>{}).then(()=>employeeWriteSource(entry,change,sequence));_employeeSourceWrites.set(entry.key,pending);
 try{return await pending;}finally{if(_employeeSourceWrites.get(entry.key)===pending)_employeeSourceWrites.delete(entry.key);}
}
/* module-function:employeeWriteSource */
async function employeeWriteSource(entry,change,sequence){
  employeeAssertBusinessScope(sequence);const sourceHeaders=RunTeamsHost.session.headers(S);
  const local=entry;
  const opened=local?.source?{session:{employee:local,context:{creator_local_source_id:local.source.id,creator_employee_source:local.source.path}}}:await RunTeamsHost.assets.authoring(entry.asset?.id||entry.work?.id,draftRuntimeConfig());employeeAssertBusinessScope(sequence);
  const context=opened.session?.context,source=context?.creator_local_source_id,path=context?.creator_employee_source;
  if(!source||!path)throw employeeIdentityError('identityUnavailable','这名员工的源码不可用。');
  const root='/api/creator-source/drafts/'+source;
  const request=async(suffix,body)=>{
    employeeAssertBusinessScope(sequence);
    const response=await fetch(root+suffix,{method:body?'POST':'GET',headers:{...sourceHeaders,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
    const result=await response.json();employeeAssertBusinessScope(sequence);
    if(!response.ok||result.error){
      const error=suffix==='/identity'&&result.code==='invalid_employee_avatar'
        ?employeeIdentityError('avatarInvalid','无法使用这张图片。请选择另一张 PNG、JPEG 或 WebP 图片。')
        :Error(result.error||'源码未能保存。');
      throw Object.assign(error,{rejected:response.status>=400&&response.status<500});
    }
    return result;
  };
  const storageKey='runteams.employee.sdk.source-edit.'+entry.key;
  let original=JSON.parse(RunTeamsBusinessStorage.getItem(storageKey)||'null');
  if(original){
    if(original.source!==source||original.path!==path||!(original.body?.employee_source===path||original.body?.changes?.length===1&&original.body.changes[0].path===path))throw employeeIdentityError('identityPrevious','请在原项目中核对上次保存的结果。');
    const receipt=await request('/receipt?operation_key='+encodeURIComponent(original.body.operation_key));
    if(receipt.state!=='confirmed'){
      try{await request(original.body.employee_source?'/identity':'/edit',original.body);}catch(error){employeeAssertBusinessScope(sequence);if(error.rejected)RunTeamsBusinessStorage.removeItem(storageKey);throw error;}
    }
    RunTeamsBusinessStorage.removeItem(storageKey);
  }
  const workspace=await request('/workspace'),file=await request('/file?path='+encodeURIComponent(path));
  if(workspace.source.files.find(row=>row.path===path)?.sha256!==file.sha256)throw employeeIdentityError('identityChanged','源码已更新。请重新打开员工设置后再修改。');
  const value=JSON.parse(file.content),identity={name:value.name,avatar:value.avatar};change(identity);
  if(Object.keys(identity).some(key=>!['name','avatar'].includes(key))||typeof identity.name!=='string'||!identity.name.trim()||identity.name.length>160||!(typeof identity.avatar==='string'&&identity.avatar||identity.avatar&&typeof identity.avatar==='object'&&Object.keys(identity.avatar).length===1&&typeof identity.avatar.content_base64==='string'))throw employeeIdentityError('identityInvalid','请检查员工名称和头像。');
  if(original?.body.employee_source===path&&JSON.stringify(identity.avatar)===JSON.stringify(original.body.avatar))identity.avatar=value.avatar;
  function acceptIdentity(saved,revision){
    const employee=opened.session.employee;
    RunTeamsEmployeeDirectory.accept({...employee,source:{...employee.source,revision},
      record:{...employee.record,avatar_src:null,...saved}});
    return {...saved,source_revision:revision};
  }
  if(identity.name===value.name&&identity.avatar===value.avatar){
    const saved=await request('/identity?employee_source='+encodeURIComponent(path));
    return acceptIdentity(saved,workspace.revision);
  }
  const body={base_revision:workspace.revision,operation_key:crypto.randomUUID(),employee_source:path,...identity};
  RunTeamsBusinessStorage.setItem(storageKey,JSON.stringify({source,path,body}));
  let result;
  try{result=await request('/identity',body);}
  catch(error){
    employeeAssertBusinessScope(sequence);
    if(error.rejected){RunTeamsBusinessStorage.removeItem(storageKey);throw error;}
    throw employeeIdentityError('identityUnknown','暂时无法确认是否已保存。再次保存前会先核对上次结果。');
  }
  if(!result.identity||typeof result.identity.name!=='string'||typeof result.identity.avatar!=='string')throw employeeIdentityError('identityUnknown','暂时无法确认是否已保存。再次保存前会先核对上次结果。');
  RunTeamsBusinessStorage.removeItem(storageKey);
  if(typeof RunTeamsCreatorAuthor!=='undefined')queueMicrotask(()=>void RunTeamsCreatorAuthor.sync());
  const saved=acceptIdentity(result.identity,result.revision);
  toast('员工资料已保存。','ok','employeeSettings.identitySaved');return saved;
}
/* module-function:coreEmployeeRuntimeChannel */
function coreEmployeeRuntimeChannel(runtime){return (S.channels||[]).find(item=>Number(item.id)===Number(runtime?.channel_id))||null;}

function employeeSettingsCopy(key,fallback){
 return window.RunTeamsLocale?.t('employeeSettings.'+key,{},fallback)??fallback;
}
/* module-function:coreEmployeeRowMenu */
function coreEmployeeRowMenu(event,id){event.preventDefault();event.stopPropagation();const item=employeeSummary(id);if(!item)return;const items=[{label:employeeSettingsCopy('title','员工设置'),labelKey:'employeeSettings.title',icon:'settings',fn:()=>openCoreEmployeeEditor(id)},{label:employeeSettingsCopy('records','工作记录'),labelKey:'employeeSettings.records',icon:'clock',fn:()=>openContextResults({employee_id:Number(id)})}];openMenu(event.currentTarget,items,{variant:'workerAction',...(event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY}}:{})});}
/* module-function:openCoreEmployeeEditor */
async function openCoreEmployeeEditor(id){
  const entry=RunTeamsEmployeeDirectory.entryFor(id)||RunTeamsEmployeeDirectory.assetEntry(id);
  if(entry)return RunTeamsEmployeeConfiguration.open(entry);
  const scope=_employeeBusinessScopeSequence;id=employeeSettingsTargetId(id);if(!id||!employeeSummary(id))return toast('找不到这名员工。','err','employeeSettings.missingEmployee');
  const summary=employeeSummary(id);if(RunTeamsEmployeeDirectory.sourceFor(id)||summary?.schema==='runteams.native-employee-summary/v1'&&employeeCanEdit(summary))return RunTeamsCreatorAuthor.openEmployee(id);
  if(S.sel?.type!=='core-employee-editor')_coreEmployeeEditorReturn=null;
  closeTransientMenus();if(document.getElementById('modalHost'))closeModal();
  selectDetailWorkspace({type:'core-employee-editor',id,status:'loading',error:''});const selection=S.sel,sequence=_detailOpenSequence;_coreEmployeeEditor=null;render();
  try{const item=await loadCoreEmployeeDetail(id);if(scope!==_employeeBusinessScopeSequence||sequence!==_detailOpenSequence||S.sel!==selection)return;
    _coreEmployeeEditor={id,editable:employeeCanEdit(item)};selection.status='ready';render();
  }catch(error){if(scope===_employeeBusinessScopeSequence&&sequence===_detailOpenSequence&&S.sel===selection){selection.status='error';selection.error=error.message;render();}}
}
/* module-function:coreEmployeeEditorDrawer */
function coreEmployeeEditorDrawer(){
  const id=Number(S.sel?.id)||0,item=employeeSummary(id)||{},loading=S.sel?.status==='loading',failed=S.sel?.status==='error';
  const identity=detailDrawerEmployeeIdentity({...item,skills:[],description:item.description||''});
  const body=loading?RunTeamsSkeletons.region('detail',undefined,'employeeSettings.loading'):failed?RunTeamsLoadFailure.markup({variant:'modal',title:'无法读取员工设置',titleKey:'employeeSettings.legacyUnavailable',labelKey:'employeeSettings.reload',busyLabelKey:'employeeSettings.loading',retry:`openCoreEmployeeEditor(${id})`,error:S.sel?.error}):employeeLifecycleSection(item,id);
  const header={toolbar:'<div id="employee_settings_header"></div>',intro:identity};
  return detailDrawerShell({className:'employee-settings-drawer',header,introClass:'employee-settings-identity detail-employee-summary',body:`<div data-sdk-settings-slot>${body}</div>`,bodyClass:'employee-settings-content',attrs:'data-rt-ui data-app-i18n-aria-label="employeeSettings.title" aria-label="员工设置"'+(loading?' aria-busy="true"':'')});
}
function decorateCoreEmployeeSettings(){
  const node=document.getElementById('employee_settings_header');if(!node){_employeeSettingsHeader?.dispose();_employeeSettingsHeader=null;return;}
  if(!window.RunTeamsUIComponents)return;
  if(!_employeeSettingsHeader)_employeeSettingsHeader=RunTeamsEmployeeDrawerHeader.create({kind:'author',onCollapse:closeCoreEmployeeEditor});
  const close=_employeeSettingsHeader.collapseButton;
  close.setAttribute('data-app-i18n-aria-label','employeeSettings.close');
  close.setAttribute('data-app-i18n-title','employeeSettings.close');
  const id=Number(S.sel?.id),item=employeeSummary(id);
  _employeeSettingsHeader.setExtras({actions:[],text:!employeeCanEdit(item)&&item?.active_release?String(item.origin?.listing_version||pipelineReleaseSemanticVersion(item.active_release)):''});
  if(node.firstChild!==_employeeSettingsHeader.element)node.replaceChildren(_employeeSettingsHeader.element);
}
/* module-function:toggleCoreEmployeeEditor */
function toggleCoreEmployeeEditor(id){id=employeeSettingsTargetId(id);const entry=RunTeamsEmployeeDirectory.entryFor(id)||RunTeamsEmployeeDirectory.assetEntry(id);if(entry&&RunTeamsEmployeeConfiguration.current()?.entry.key===entry.key)return RunTeamsEmployeeConfiguration.close();if(typeof RunTeamsCreatorAuthor!=='undefined'&&RunTeamsCreatorAuthor.current()?.assetRecordId===id)return RunTeamsCreatorAuthor.close();if(S.sel?.type==='core-employee-editor'&&Number(S.sel.id)===id)closeCoreEmployeeEditor();else return openCoreEmployeeEditor(id);}
function leaveCoreEmployeeEditor(){
  _coreEmployeeEditor=null;_coreEmployeeEditorReturn=null;
  _employeeSettingsHeader?.dispose();_employeeSettingsHeader=null;
}
function closeCoreEmployeeEditor(){return closeDetailWorkspace();}
if(typeof window!=='undefined')window.addEventListener?.('runteams-ui-ready',()=>decorateCoreEmployeeSettings());

function employeeLifecycleSection(item,id){
  return `<section class="employee-lifecycle rt-section">${item?.active_release?`<button type="button" class="btn" onclick="employeeStartWork(${id})" data-app-i18n="employeeSettings.assignWork">交办工作</button>`:''}</section>`;
}
async function employeeStartWork(id){if(employeeSummary(id)?.active_release)return openBotConversation(id,{forceNew:true});}

/* Current-work dialogs share the same service consent component. */
function employeeWorkChat(value){const panel=S.conversationPanel,entry=RunTeamsEmployeeDirectory.entryFor(value)||RunTeamsEmployeeDirectory.assetEntry(value);return panel?.kind==='general'&&entry&&RunTeamsEmployeeDirectory.matches(entry,panel)?panel:null;}
function employeeConsentText(key,fallback,parameters={}){
 const vars=Object.keys(parameters).length?' data-app-i18n-vars="'+esc(JSON.stringify(parameters))+'"':'';
 const value=window.RunTeamsLocale?.t('employeeConsent.'+key,parameters,fallback)??fallback.replace('{time}',parameters.time??'');
 return '<span data-app-i18n="employeeConsent.'+key+'"'+vars+'>'+esc(value)+'</span>';
}
function employeeConsentExpiry(timestamp){
 const options={month:'short',day:'numeric',hour:'numeric',minute:'2-digit'};
 const locale=globalThis.RunTeamsLocale;
 return locale?locale.formatDate(timestamp,options):new Intl.DateTimeFormat('zh-CN',options).format(timestamp);
}
globalThis.RunTeamsLocale?.onChange(()=>{
 for(const row of document.querySelectorAll('[data-employee-consent-expiry]')){
  const label=row.querySelector('[data-app-i18n="employeeConsent.expires"]');
  if(!label)continue;
  label.dataset.appI18nVars=JSON.stringify({time:employeeConsentExpiry(Number(row.dataset.employeeConsentExpiry))});
  globalThis.RunTeamsLocale.apply(label);
 }
});
function employeeConnectionMarkup(d,s,index,row,prefix='employee_mcp_connection',handler='workResources',subject='员工'){
  const action=verb=>typeof handler==='function'?handler(verb,index):handler+verb+'('+index+')';
  const pending=row.pending,authorized=row.authorized,locked=s.busy||s.connectionPending;
  const awaiting=s.connectionPending&&s.connectionPending.package===row.package&&s.connectionPending.key===row.key;
  const status=awaiting&&s.connectionPending.revoke?employeeConsentText('revokePending','尚未确认撤销结果'):
    awaiting||pending&&!authorized?employeeConsentText('pending','尚未确认授权结果'):
    authorized?employeeConsentText('authorized','已在本机授权'):employeeConsentText('unauthorized','尚未授权');
  let body=`<section class="employee-sdk-connection" data-connection="${esc(row.key)}"><div class="employee-sdk-connection-heading"><h3>${esc(new URL(row.origin).hostname)}</h3><span>${status}</span></div><p class="employee-sdk-note">${employeeConsentText("address","访问地址：")}${esc(row.origin)}</p><p class="employee-sdk-note">${employeeConsentText("scope","授权范围：")}${row.scopes.map(esc).join('，')||employeeConsentText("noScope","无额外权限")}</p>`;
      if(row.program_name)body+=`<p class="employee-sdk-note">${employeeConsentText("program","使用程序：")}${esc(row.program_name)}</p>`;
      if(awaiting)return body+'</section>';
      if(authorized){
        const expiresAt=Number(row.expires_at)*1000;
        if(Number.isFinite(expiresAt)&&expiresAt>0&&expiresAt<=8.64e15)body+=`<p class="employee-sdk-note" data-employee-consent-expiry="${expiresAt}">${employeeConsentText('expires','授权将于 {time} 到期。到期后需要重新授权。',{time:employeeConsentExpiry(expiresAt)})}</p>`;
        body+=`<button type="button" class="btn" onclick="${action('Revoke')}" ${locked?'disabled':''}>${employeeConsentText("revoke","撤销授权")}</button>`;
      }else if(pending)body+=`<button class="btn" type="button" onclick="${action('Read')}" ${s.busy?'disabled':''}>${employeeConsentText("checkResult","核对结果")}</button>`;
      else{
        body+=`<div class="field"><label for="${prefix}_credential_${index}">${employeeConsentText("credential","本机凭据")}</label><select class="inp" id="${prefix}_credential_${index}" onchange="${action('Credential')}" ${locked?'disabled':''}><option value="" data-app-i18n="employeeConsent.chooseCredential">选择本机凭据</option>${d.credential_names.map((name,i)=>`<option value="${i}">${esc(name)}</option>`).join('')}<option value="new" data-app-i18n="employeeConsent.addToken">添加访问令牌</option></select></div><div class="field" id="${prefix}_token_field_${index}" hidden><label for="${prefix}_token_${index}">${employeeConsentText("token","访问令牌")}</label><input class="inp" id="${prefix}_token_${index}" type="password" autocomplete="off" spellcheck="false" maxlength="8192" oninput="${action('Enable')}" ${locked?'disabled':''}><p class="employee-sdk-note">${employeeConsentText("tokenStorage","访问令牌仅保存在这台电脑的凭据保险箱中，不会加入作品或工作备份。")}</p></div><label class="employee-sdk-consent"><input type="checkbox" id="${prefix}_consent_${index}" onchange="${action('Enable')}" ${locked?'disabled':''}><span>${subject==='智能体团队'?employeeConsentText('allowPipeline','允许此智能体团队使用所选凭据访问此服务，最长 1 小时。'):employeeConsentText('allowEmployee','允许此员工使用所选凭据访问此服务，最长 1 小时。')}</span></label><button class="btn pri" type="button" id="${prefix}_authorize_${index}" onclick="${action('Authorize')}" disabled>${employeeConsentText("authorize","授权连接")}</button>`;
      }
      body+='</section>';
  return body;
}

/* Work authorization belongs to the initiating work and its settings. */
window.RunTeamsWorkAuthorization=(()=>{
 const states=new Map();let sequence=0,dialog=null,polling=false,boardIndex=0;
 const text=(key,fallback)=>RunTeamsLocale?.t('workAuthorization.'+key,{},fallback)||fallback;
 const copy=(key,fallback)=>'<span data-app-i18n="workAuthorization.'+key+'">'+esc(text(key,fallback))+'</span>';
 const equal=(a,b)=>!!a&&!!b&&JSON.stringify(a)===JSON.stringify(b);
 function context(includeWorkbench=true){
  if(RunTeamsHost.session.workspace(S))return null;
  const workbench=includeWorkbench&&window.RunTeamsCreatorWork?.authorizationContext();
  if(workbench&&S.sel?.type==='creator-work')return workbench;
  const privateWork=window.RunTeamsSourcePipelinePanels?.programContext();
  if(privateWork)return {panel:privateWork,privateWork,pipeline:false};
  const own=window.RunTeamsSourcePipelines?.workContext();if(own)return {panel:own,pipeline:true};
  const panel=S.conversationPanel,item=downloadedEmployeeSummary(panel?.context?.target_employee_id);
  return Number.isSafeInteger(panel?.id)&&(item?.local_mcp||panel?.identity?.local_mcp)?{panel,pipeline:false}:null;
 }
 function assertCurrent(s){
  employeeAssertBusinessScope(s.scope);
  if(Number(s.workbenchId??s.panel?.id)!==Number(s.chat))throw Error(text('changed','工作已变化，请返回原工作重新打开。'));
  if(s.deviceScope!==RunTeamsHost.session.deviceScope(S))throw Error(text('changed','工作已变化，请返回原工作重新打开。'));
  if(s.boardOwner){if(window.RunTeamsSourcePipelines?.current()!==s.boardOwner||!s.boardOwner.data?.workflows?.some(w=>w.id===s.workflowId&&w.work_chat_id===s.chat))throw Error(text('changed','工作已变化，请返回原工作重新打开。'));return;}
  if(s.privateWork){if(window.RunTeamsSourcePipelinePanels?.programContext()!==s.privateWork)throw Error(text('changed','工作已变化，请返回原工作重新打开。'));}
  else if(s.panel!==(s.pipeline?window.RunTeamsSourcePipelines?.workContext():S.conversationPanel))throw Error(text('changed','工作已变化，请返回原工作重新打开。'));
  if(s.workbenchId&&window.RunTeamsCreatorWork?.authorizationContext()?.workbenchId!==s.workbenchId)throw Error(text('changed','工作已变化，请返回原工作重新打开。'));
 }
 function state(c){
  if(!c?.panel)return null;
  const id=c.workbenchId??c.panel.id;
  let s=[...states.values()].find(s=>s.panel===c.panel&&s.chat===id&&s.scope===_employeeBusinessScopeSequence&&s.deviceScope===RunTeamsHost.session.deviceScope(S));
  if(!s){s={...c,key:++sequence,chat:id,scope:_employeeBusinessScopeSequence,deviceScope:RunTeamsHost.session.deviceScope(S),data:null,loading:false,busy:false,error:''};states.set(s.key,s);}
  return s;
 }
 async function request(s,body,observe=false){
  assertCurrent(s);
  const path=`/api/chat/${s.chat}/${s.pipeline?'pipeline-mcp':'employee-mcp'}${observe?'?observe=1':''}`;
  let value;
  if(S.localLibrary)value=await api(path,body?'POST':'GET',body||undefined);
  else{
   const response=await RunTeamsRequests.request(path,{method:body?'POST':'GET',device:true,readCurrent:!body,headers:{'Content-Type':'application/json','X-RunTeams-Device-Scope':s.deviceScope},...(body?{body:JSON.stringify(body)}:{})},s.deviceScope);
   value=JSON.parse(response.text);if(response.status!==200)throw Error(text('unavailable','无法读取工作授权，请重试。'));
  }
  assertCurrent(s);if(value.error)throw Error(value.error);return value;
 }
 const services=s=>(s.data?.connection_services||[]).flatMap(service=>service.connections.map(row=>({...row,package:service.package,program_name:service.program_name,credential_names:service.credential_names})));
 function settingsBody(s){
  if(s.loading&&!s.data)return '';
  const d=s.data;let body='';
  if(d?.available){
   if(d.enabled)body=`<button class="detail-head-more" type="button" data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="false" aria-label="更多操作" data-app-i18n-aria-label="automationList.more" onclick="RunTeamsWorkAuthorization.settingsMenu(${s.key},this)" ${s.busy?'disabled':''}>${ICON('more')}</button>`;
   if(d.calls?.some(row=>row.state==='unknown'))body+='<p class="employee-sdk-error" role="alert">'+employeeConsentText('unknownResult','有操作的结果尚未确认。请核对结果。')+'</p>';
   for(const [index,row] of services(s).entries())body+=employeeConnectionMarkup({credential_names:row.credential_names},s,index,row,'work_connection_'+s.key,(verb,i)=>`RunTeamsWorkAuthorization.connection${verb}(${s.key},${i})`,s.pipeline?'智能体团队':'员工');
  }
  if(s.error)body+=`<p class="employee-sdk-error" role="alert">${esc(s.error)}</p>`;
  if(s.error||s.connectionPending)body+=`<button class="btn sm" type="button" onclick="RunTeamsWorkAuthorization.read(${s.key})" ${s.busy?'disabled':''}>${employeeConsentText('checkResult','核对结果')}</button>`;
  return body;
 }
 function settingsMenu(id,anchor){
  const s=states.get(id);if(!s||s.busy||!s.data?.enabled)return;
  try{assertCurrent(s);}catch{return;}
  openMenu(anchor,[{label:text('revoke','撤销授权'),labelKey:'workAuthorization.revoke',fn:()=>revoke(id)}]);
 }
 function paint(s){
  for(const node of document.querySelectorAll('[data-work-authorization="'+s.key+'"]')){
   if(s.editing&&!s.busy)continue;
   const focused=node.contains(document.activeElement)?document.activeElement.id:null;
   node.innerHTML=settingsBody(s);window.RunTeamsLocale?.apply(node);
   if(focused)node.querySelector('#'+CSS.escape(focused))?.focus({preventScroll:true});
  }
  if(dialog?.state===s){replaceDialog(dialogOptions());}
 }
 async function read(value){
  const s=typeof value==='object'?value:states.get(value);if(!s)return;
  if(s.reading)return s.reading;
  s.editing=false;s.loading=true;
  const revision=s.readRevision=(s.readRevision||0)+1,current=()=>s.readRevision===revision;
  s.reading=(async()=>{
   try{
    const d=await request(s);if(!current())return s.data;
    if(d.schema!==(s.pipeline?'runteams.pipeline-mcp-work/1':'runteams.employee-mcp-work/1')||d.chat_id!==s.chat)throw Error(text('changed','工作已变化，请返回原工作重新打开。'));
    s.data=d;s.error='';s.uncertain=false;s.connectionPending=null;
   }catch(error){if(current())s.error=error.message||text('unavailable','无法读取工作授权，请重试。');}
   finally{if(current()){s.loading=false;s.reading=null;paint(s);}}
   return s.data;
  })();return s.reading;
 }
 function invalidate(s){s.readRevision=(s.readRevision||0)+1;s.reading=null;s.loading=false;}
 function settings(entry){
  let s=entry.authorizationContext;
  if(!s){
   const own=entry.pipeline_own&&window.RunTeamsSourcePipelines?.workContext();
   const c=own?{panel:own,pipeline:true}:context();if(!c)return '';
   if(entry.pipeline_own){if(!c.pipeline||!equal(c.panel.context?.source_pipeline_workspace,entry.pipeline_reference))return '';}
   else if(c.privateWork){if(!entry.pipeline_reference||!equal(c.privateWork.snapshot?.package?.reference,entry.source?.reference))return '';}
   else if(c.pipeline||entry.pipeline_reference)return '';
   else if(entry.chat_id!==c.panel.id&&RunTeamsEmployeeDirectory.forPanel(c.panel)?.key!==entry.key)return '';
   s=state(c);
  }
  try{assertCurrent(s);}catch{return '';}
  if(!s.data&&!s.error&&!s.reading)requestAnimationFrame(()=>{if(document.querySelector('[data-work-authorization="'+s.key+'"]'))void read(s);});
  return '<section class="work-authorization-settings" data-work-authorization="'+s.key+'">'+settingsBody(s)+'</section>';
 }
 async function configure(s){
  assertCurrent(s);
  if(s.privateWork)return RunTeamsSourcePipelinePanels.configureWork(s.privateWork,s);
  if(s.pipeline)return RunTeamsSourcePipelinePanels.configureOwn(s);
  const entry=RunTeamsEmployeeConfiguration.workTarget(s.panel)||RunTeamsEmployeeDirectory.forPanel(s.panel);
  if(entry)return RunTeamsEmployeeConfiguration.openConversation({...entry,authorizationContext:s},RunTeamsEmployeeDirectory.forPanel(s.panel));
 }
 function pending(s){return s.data?.approvals?.[0];}
 function trust(s){return dialog?.kind==='trust'||pending(s)?.method==='runteams/work-authorization';}
 function dialogOptions(){
  const s=dialog.state,d=s.data,row=pending(s),isTrust=trust(s),title=isTrust?text('trustTitle','允许运行此版本？'):text('operationTitle','确认操作');
  let body='',actions='';
  if(isTrust){
   body=`<p class="modal-copy">${esc(d?.subject||s.panel.identity?.name||s.panel.title||'')}</p><p class="modal-copy">${copy('risk','此版本包含在电脑上运行的程序，可按系统权限访问文件和网络，并使用你在设置中为它配置的凭据。')}</p><p class="employee-sdk-note">${(d?.packages||[]).map(p=>esc(p.name)+' '+esc(p.version)).join('、')}</p><p class="employee-sdk-note">${copy('versionScope','授权仅适用于此版本，可在设置中撤销。')}</p>`;
   if(!d?.runtime_available)body+='<p class="employee-sdk-error" role="alert">'+employeeConsentText('runtimeMissing','此版本的应用缺少运行所需的组件。')+'</p>';
   actions=`<button class="btn pri" type="button" onclick="RunTeamsWorkAuthorization.confirm()" ${s.busy||s.loading||s.uncertain||!d?.runtime_available?'disabled':''}>${copy('allowContinue','允许并继续')}</button>`;
  }else if(row){
   const p=row.params||{},official=p._meta?.codex_approval_kind==='mcp_tool_call',description=official?p._meta.tool_description:p.reason||p.message||p.request?.message||p.questions?.map(q=>q.question).join('；')||p.name,args=p.arguments??p._meta?.tool_params;
   body=`<p class="modal-copy">${description?esc(description):employeeConsentText('approvalPrompt','此操作需要你的确认。')}</p>${p.command?`<pre class="employee-mcp-args">${esc(Array.isArray(p.command)?p.command.join(' '):p.command)}</pre>`:''}${args?`<details><summary>${employeeConsentText('viewDetails','查看操作内容')}</summary><pre class="employee-mcp-args">${esc(JSON.stringify(args,null,2))}</pre></details>`:''}<p class="employee-sdk-note">${employeeConsentText('once','授权仅适用于本次操作。')}</p>`;
   actions=`<button class="btn pri" type="button" onclick="RunTeamsWorkAuthorization.confirm()" ${s.busy||s.uncertain||row.can_accept===false?'disabled':''}>${employeeConsentText('allowOnce','允许本次操作')}</button>`;
  }else body='<p class="modal-copy">'+copy('resolved','本次确认已处理或已失效。')+'</p>';
  if(s.error)body+='<p class="employee-sdk-error" role="alert">'+esc(s.error)+'</p>';
  const retry=s.error?`<button class="btn" type="button" onclick="RunTeamsWorkAuthorization.check()" ${s.busy?'disabled':''}>${employeeConsentText('checkResult','核对结果')}</button>`:'';
  return {className:'employee-sdk-setup work-authorization-dialog',title,body,closeAction:'RunTeamsWorkAuthorization.close()',attrs:'role="dialog" aria-modal="true" aria-label="'+esc(title)+'" onkeydown="RunTeamsWorkAuthorization.key(event)"',footer:`<button class="btn" type="button" onclick="RunTeamsWorkAuthorization.close()" ${s.busy?'disabled':''}>${isTrust?copy('cancel','暂不运行'):employeeConsentText('decline','拒绝')}</button><div class="grow"></div>${retry}${actions}`};
 }
 function dismiss(accepted=false){const old=dialog;if(!old)return;dialog=null;closeModal();old.resolve?.(accepted);old.trigger?.isConnected&&old.trigger.focus();}
 function show(s,kind){
  if(dialog)return dialog.state===s?dialog.promise:Promise.resolve(false);
  if(document.getElementById('modalHost'))return Promise.resolve(false);
  const previous=document.activeElement;
  let resolve;const promise=new Promise(done=>{resolve=done;});dialog={state:s,kind,promise,resolve,trigger:previous};openDialog(dialogOptions());return promise;
 }
 async function confirm(){
  const current=dialog,s=current?.state;if(!s||s.busy||s.loading||s.uncertain)return;
  const row=pending(s),isTrust=trust(s);if(!isTrust&&!row)return;
  invalidate(s);s.busy=true;s.error='';paint(s);
  try{
   await request(s,{...(row?{action:'answer',id:row.id,decision:'accept'}:{action:'enable',confirm:true}),binding_sha256:s.data.binding_sha256});
   await read(s);if(dialog!==current)return;
   if(s.error)return;
   if(isTrust&&!s.data.enabled)throw Error(text('unconfirmed','尚未确认授权结果，请核对状态。'));
   if(row&&pending(s)?.id===row.id)throw Error(text('unconfirmed','尚未确认授权结果，请核对状态。'));
   dismiss(true);
  }catch(error){s.uncertain=true;s.error=text('unconfirmed','尚未确认授权结果，请核对状态。');}
  finally{s.busy=false;paint(s);}
 }
 async function check(){
  const current=dialog;if(!current||current.state.busy)return;
  const previous=pending(current.state)?.id;await read(current.state);if(dialog!==current||current.state.error)return;
  if(current.kind==='trust'&&current.state.data.enabled)dismiss(true);
  else if(previous&&pending(current.state)?.id!==previous)dismiss(false);
 }
 async function close(){
  const current=dialog,s=current?.state;if(!s||s.busy)return;
  const row=pending(s);
  if(row){invalidate(s);s.busy=true;paint(s);try{await request(s,{action:'answer',id:row.id,decision:'cancel',binding_sha256:s.data.binding_sha256});}catch{ s.error=text('unconfirmed','尚未确认授权结果，请核对状态。');s.busy=false;paint(s);return; }s.busy=false;}
  if(dialog===current)dismiss(false);
 }
 function key(event){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();void close();}
  if(event.key!=='Tab')return;
  const nodes=[...document.querySelectorAll('.work-authorization-dialog button:not([disabled]),.work-authorization-dialog summary')].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
 }
 async function prepare(c=context()){
  const s=state(c);if(!s)return true;
  await read(s);try{assertCurrent(s);}catch{return false;}if(s.error){await configure(s);return false;}
  if(!s.data.available)return true;
  if(!s.data.enabled&&!await show(s,'trust'))return false;
  try{assertCurrent(s);}catch{return false;}
  if(services(s).some(row=>row.required!==false&&(!row.authorized||row.expires_at&&row.expires_at<=Date.now()/1000))){await configure(s);return false;}
  // A prior stop is resumed by this explicit work action, never by polling.
  if(s.data.suspended){try{await request(s,{action:'resume',binding_sha256:s.data.binding_sha256});await read(s);}catch(error){s.error=error.message;await configure(s);return false;}}
  return !s.error;
 }
 async function beforeSend(id){const c=context(false);return Number(c?.panel.id)===Number(id)?prepare(c):true;}
 async function notify(chat){
  const c=context();if(Number(c?.workbenchId??c?.panel.id)!==Number(chat)||dialog||document.getElementById('modalHost'))return;
  const s=state(c);await read(s);
  try{assertCurrent(s);}catch{return;}
  if(!s.error&&pending(s))void show(s,'operation');
 }
 async function revoke(id){
  const s=states.get(id);if(!s?.data?.enabled||s.busy)return;invalidate(s);s.busy=true;s.error='';paint(s);
  try{await request(s,{action:'disable',binding_sha256:s.data.binding_sha256});await read(s);}catch{s.error=text('unconfirmed','尚未确认授权结果，请核对状态。');}
  finally{s.busy=false;paint(s);}
 }
 const element=(s,part,index)=>document.getElementById('work_connection_'+s.key+'_'+part+'_'+index);
 function connectionCredential(id,index){const s=states.get(id);if(!s||s.busy)return;s.editing=true;const select=element(s,'credential',index),field=element(s,'token_field',index),input=element(s,'token',index);if(field)field.hidden=select.value!=='new';if(input)input.value='';connectionEnable(id,index);if(select.value==='new')input?.focus();}
 function connectionEnable(id,index){const s=states.get(id);if(!s||s.busy)return;s.editing=true;const choice=element(s,'credential',index)?.value,token=element(s,'token',index)?.value,consent=element(s,'consent',index)?.checked,button=element(s,'authorize',index);if(button)button.disabled=!consent||!choice||choice==='new'&&!token;}
 async function connectionAction(id,index,body){
  const s=states.get(id),row=s&&services(s)[index];if(!row||s.busy||s.connectionPending)return;
  invalidate(s);s.busy=true;s.editing=false;s.error='';s.connectionPending={package:row.package,key:row.key,revoke:body.action==='connection-revoke'};paint(s);
  try{await request(s,{...body,package:row.package,connection:row.key,binding_sha256:row.binding_sha256});await read(s);}catch{s.error=text('unconfirmed','尚未确认授权结果，请核对状态。');}
  finally{if(body.token)body.token='';s.busy=false;paint(s);}
 }
 function connectionAuthorize(id,index){const s=states.get(id),row=s&&services(s)[index];if(!row||element(s,'authorize',index)?.disabled)return;const select=element(s,'credential',index),input=element(s,'token',index),body={action:'connection-authorize',confirm:element(s,'consent',index)?.checked===true,...(select.value==='new'?{token:input.value}:{credential_name:row.credential_names[Number(select.value)]})};if(input)input.value='';return connectionAction(id,index,body);}
 function connectionRevoke(id,index){return connectionAction(id,index,{action:'connection-revoke'});}
 async function boardConfirmation(){
  const owner=window.RunTeamsSourcePipelines?.current();
  if(!owner||S.sel||dialog||document.getElementById('modalHost'))return;
  const rows=(owner.data?.workflows||[]).filter(row=>row.state==='running'&&Number.isSafeInteger(row.work_chat_id));
  if(!rows.length)return;
  const row=rows[(boardIndex++)%rows.length],selection=S.sel;
  const s={panel:{id:row.work_chat_id},chat:row.work_chat_id,boardOwner:owner,workflowId:row.id,pipeline:false,scope:_employeeBusinessScopeSequence,deviceScope:RunTeamsHost.session.deviceScope(S)};
  const hint=await request(s,null,true);
  if(hint.schema!=='runteams.mcp-observation/1'||hint.owner!=='employee'||hint.chat_id!==s.chat||!hint.pending||S.sel!==selection||dialog||document.getElementById('modalHost'))return;
  await RunTeamsSourcePipelines.openWork(row.id);
  if(window.RunTeamsSourcePipelines.current()===owner&&S.sel?.workflowId===row.id)await notify(s.chat);
 }
 window.addEventListener('runteams:business-scope-changed',()=>{dismiss(false);states.clear();});
 window.setInterval(async()=>{
  if(polling)return;
  if(dialog){try{assertCurrent(dialog.state);}catch{dismiss(false);}}
  polling=true;let s;
  try{
   await boardConfirmation();
   const c=context();if(!c)return;s=state(c);
   assertCurrent(s);
   if(dialog&&dialog.state!==s){dismiss(false);}
   if(s.busy||s.editing)return;
   const hint=await request(s,null,true);
   if(hint.schema!=='runteams.mcp-observation/1'||hint.chat_id!==s.chat||hint.owner!==(s.pipeline?'pipeline':'employee'))return;
   if(hint.pending&&!dialog&&!document.getElementById('modalHost'))await notify(s.chat);
   else if(dialog?.state===s||document.querySelector('[data-work-authorization="'+s.key+'"]')){
    if(hint.version!==s.data?.notification_version||services(s).some(row=>row.authorized&&row.expires_at<=Date.now()/1000))await read(s);
   }
  }catch{if(s&&dialog?.state===s)dismiss(false);}finally{polling=false;}
 },1200);
 return {request,assertCurrent,context,settings,settingsMenu,state,read,configure,prepare,beforeSend,notify,revoke,confirm,check,close,key,get:id=>states.get(id),connectionCredential,connectionEnable,connectionAuthorize,connectionRevoke,connectionRead:read};
})();
