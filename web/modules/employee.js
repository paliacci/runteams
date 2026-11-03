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

/* module-function:employeeWrite */
async function employeeWrite(value,change){
 const entry=RunTeamsEmployeeDirectory.entryFor(value)||RunTeamsEmployeeDirectory.assetEntry(value);if(!entry)throw Error('员工目录已变化，请重新打开。');
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
  if(!source||!path)throw Error('员工缺少原 SDK 源码。');
  const root='/api/creator-source/drafts/'+source;
  const request=async(suffix,body)=>{employeeAssertBusinessScope(sequence);const response=await fetch(root+suffix,{method:body?'POST':'GET',headers:{...sourceHeaders,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});const result=await response.json();employeeAssertBusinessScope(sequence);if(!response.ok||result.error)throw Object.assign(Error(result.error||'源码未能保存。'),{rejected:response.status>=400&&response.status<500});return result;};
  const storageKey='runteams.employee.sdk.source-edit.'+entry.key;
  let original=JSON.parse(RunTeamsBusinessStorage.getItem(storageKey)||'null');
  if(original){
    if(original.source!==source||original.path!==path||!(original.body?.employee_source===path||original.body?.changes?.length===1&&original.body.changes[0].path===path))throw Error('原源码保存请求需要在原工程中核对。');
    const receipt=await request('/receipt?operation_key='+encodeURIComponent(original.body.operation_key));
    if(receipt.state!=='confirmed'){
      try{await request(original.body.employee_source?'/identity':'/edit',original.body);}catch(error){employeeAssertBusinessScope(sequence);if(error.rejected)RunTeamsBusinessStorage.removeItem(storageKey);throw error;}
    }
    RunTeamsBusinessStorage.removeItem(storageKey);
  }
  const workspace=await request('/workspace'),file=await request('/file?path='+encodeURIComponent(path));
  if(workspace.source.files.find(row=>row.path===path)?.sha256!==file.sha256)throw Error('源码已更新，请重新打开后修改。');
  const value=JSON.parse(file.content),identity={name:value.name,avatar:value.avatar};change(identity);
  if(Object.keys(identity).some(key=>!['name','avatar'].includes(key))||typeof identity.name!=='string'||!identity.name.trim()||identity.name.length>160||!(typeof identity.avatar==='string'&&identity.avatar||identity.avatar&&typeof identity.avatar==='object'&&Object.keys(identity.avatar).length===1&&typeof identity.avatar.content_base64==='string'))throw Error('员工名称或头像无效。');
  if(original?.body.employee_source===path&&JSON.stringify(identity.avatar)===JSON.stringify(original.body.avatar))identity.avatar=value.avatar;
  if(identity.name===value.name&&identity.avatar===value.avatar){
    const saved=await request('/identity?employee_source='+encodeURIComponent(path));
    RunTeamsEmployeeDirectory.accept({...opened.session.employee,record:{...opened.session.employee.record,avatar_src:null,...saved}});
    return {...saved,source_revision:workspace.revision};
  }
  const body={base_revision:workspace.revision,operation_key:crypto.randomUUID(),employee_source:path,...identity};
  RunTeamsBusinessStorage.setItem(storageKey,JSON.stringify({source,path,body}));
  let result;try{result=await request('/identity',body);}catch(error){employeeAssertBusinessScope(sequence);if(error.rejected)RunTeamsBusinessStorage.removeItem(storageKey);throw error;}
  if(!result.identity||typeof result.identity.name!=='string'||typeof result.identity.avatar!=='string')throw Error('员工资料保存回执无效，请重新读取。');
  RunTeamsBusinessStorage.removeItem(storageKey);
  if(typeof RunTeamsCreatorAuthor!=='undefined')queueMicrotask(()=>void RunTeamsCreatorAuthor.sync());
  RunTeamsEmployeeDirectory.accept({...opened.session.employee,record:{...opened.session.employee.record,avatar_src:null,...result.identity}});
  toast('员工设置已保存。','ok');return {...result.identity,source_revision:result.revision};
}
/* module-function:coreEmployeeRuntimeChannel */
function coreEmployeeRuntimeChannel(runtime){return (S.channels||[]).find(item=>Number(item.id)===Number(runtime?.channel_id))||null;}

/* module-function:trashCoreEmployee */
function trashCoreEmployee(id){const scope=_employeeBusinessScopeSequence,item=RunTeamsEmployeeDirectory.assets().find(row=>Number(row.id)===Number(id));if(!item)return;confirmModal("将这名员工移到垃圾箱？","员工草稿和发布版本保留在云端垃圾箱，可恢复。本机已有工作和文件不受影响。",async()=>{try{const out=await employeeScopedApi(`/api/core/employees/${Number(id)}/trash`,"POST",{},scope);if(out.error){toast(out.error,"err");return;}await refreshCoreTeam();employeeAssertBusinessScope(scope);render();toast("员工已移到垃圾箱","ok");}catch(error){if(scope===_employeeBusinessScopeSequence)toast(error.message||'员工未能移到垃圾箱','err');}},true);}

/* module-function:coreEmployeeRowMenu */
function coreEmployeeRowMenu(event,id){event.preventDefault();event.stopPropagation();const item=employeeSummary(id);if(!item)return;const items=[{label:'员工设置',icon:'settings',fn:()=>openCoreEmployeeEditor(id)},{label:'工作记录',icon:'clock',fn:()=>openContextResults({employee_id:Number(id)})},{divider:true},{label:'移到垃圾箱',icon:'trash',fn:()=>trashCoreEmployee(id)}];openMenu(event.currentTarget,items,{variant:'workerAction',...(event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY}}:{})});}
/* module-function:openCoreEmployeeEditor */
async function openCoreEmployeeEditor(id){
  const entry=RunTeamsEmployeeDirectory.entryFor(id)||RunTeamsEmployeeDirectory.assetEntry(id);
  if(entry)return RunTeamsEmployeeConfiguration.open(entry);
  const scope=_employeeBusinessScopeSequence;id=employeeSettingsTargetId(id);if(!id||!employeeSummary(id))return toast('员工不存在','err');
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
  const body=loading?RunTeamsSkeletons.region('detail'):failed?RunTeamsLoadFailure.markup({variant:'modal',title:'设置暂时无法加载',retry:`openCoreEmployeeEditor(${id})`,error:S.sel?.error}):employeeLifecycleSection(item,id)+employeeMCPSection(item,id)+(window.RunTeamsWorkResources?.section(item,id)||'');
  return `<aside class="drawer right-detail-drawer employee-settings-drawer" data-rt-ui aria-label="员工设置"${loading?' aria-busy="true"':''}><div id="employee_settings_header"></div><div class="employee-settings-identity detail-employee-summary">${identity}</div><div class="employee-settings-content" data-sdk-settings-slot>${body}</div></aside>`;
}
function decorateCoreEmployeeSettings(){
  const node=document.getElementById('employee_settings_header');if(!node){_employeeSettingsHeader?.dispose();_employeeSettingsHeader=null;return;}
  if(!window.RunTeamsUIComponents)return;
  if(!_employeeSettingsHeader)_employeeSettingsHeader=RunTeamsEmployeeDrawerHeader.create({kind:'author',onCollapse:closeCoreEmployeeEditor});
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
  return `<section class="employee-lifecycle rt-section">${item?.active_release?`<button type="button" class="btn" onclick="employeeStartWork(${id})">交办工作</button>`:''}</section>`;
}
async function employeeStartWork(id){if(employeeSummary(id)?.active_release)return openBotConversation(id,{forceNew:true});}

/* Current-work dialogs share the same service consent component. */
function employeeWorkChat(value){const panel=S.conversationPanel,entry=RunTeamsEmployeeDirectory.entryFor(value)||RunTeamsEmployeeDirectory.assetEntry(value);return panel?.kind==='general'&&entry&&RunTeamsEmployeeDirectory.matches(entry,panel)?panel:null;}
function employeeConnectionMarkup(d,s,index,row,prefix='employee_mcp_connection',handler='employeeMCPConnection',subject='员工'){
  const pending=row.pending,authorized=row.authorized;let body='';
      body+=`<section class="employee-sdk-connection" data-connection="${esc(row.key)}"><div class="employee-sdk-connection-heading"><h3>${esc(new URL(row.origin).hostname)}</h3><span>${authorized?'本机已授权':pending?'授权结果待核对':'尚未授权'}</span></div><p class="employee-sdk-note">访问地址：${esc(row.origin)}</p><p class="employee-sdk-note">授权范围：${row.scopes.map(esc).join('，')||'无额外范围'}</p>`;
      if(row.program_name)body+=`<p class="employee-sdk-note">使用程序：${esc(row.program_name)}</p>`;
      if(authorized)body+=`<p class="employee-sdk-note">本次授权至 ${esc(new Date(row.expires_at*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}))}，到期后需重新授权。</p><button type="button" class="btn" onclick="${handler}Revoke(${index})" ${s.busy?'disabled':''}>撤销授权</button>`;
      else if(pending)body+=`<button class="btn" type="button" onclick="${handler}Resume(${index})" ${s.busy?'disabled':''}>继续原授权操作</button>`;
      else{
        body+=`<div class="field"><label for="${prefix}_credential_${index}">本机凭据</label><select class="inp" id="${prefix}_credential_${index}" onchange="${handler}Credential(${index})" ${s.busy?'disabled':''}><option value="">选择本机凭据</option>${d.credential_names.map((name,i)=>`<option value="${i}">${esc(name)}</option>`).join('')}<option value="new">添加访问令牌</option></select></div><div class="field" id="${prefix}_token_field_${index}" hidden><label for="${prefix}_token_${index}">访问令牌</label><input class="inp" id="${prefix}_token_${index}" type="password" autocomplete="off" spellcheck="false" maxlength="8192" oninput="${handler}Enable(${index})" ${s.busy?'disabled':''}><p class="employee-sdk-note">仅存入本机凭据保险箱，不进入作品或工作备份。</p></div><label class="employee-sdk-consent"><input type="checkbox" id="${prefix}_consent_${index}" onchange="${handler}Enable(${index})" ${s.busy?'disabled':''}><span>允许此${subject}使用所选凭据访问此服务，最长1小时。实际可用性以服务响应为准。</span></label><button class="btn pri" type="button" id="${prefix}_authorize_${index}" onclick="${handler}Authorize(${index})" disabled>授权此连接</button>`;
      }
      body+='</section>';
  return body;
}

/* Current employee version: local extension trust and official confirmations. */
let _employeeMCPDialog=null,_employeeMCPPolling=false;
function employeeMCPSection(item,id){
  if(!item?.local_mcp||RunTeamsHost.session.workspace(S))return '';
  const chat=employeeWorkChat(id);
  return `<section class="employee-sdk-section rt-section"><div class="rt-section-heading"><h3 class="rt-section-heading-label">本机功能</h3><button type="button" class="rt-button rt-section-action" onclick="${chat?`employeeMCPOpen(${id},this)`:`openBotConversation(${id})`}">${chat?'管理':'打开对话'}</button></div></section>`;
}
async function employeeMCPRequest(s,body,observe=false){
  employeeAssertBusinessScope(s.scope);
  employeeMCPAssertPrivateWork(s);
  const path=`/api/chat/${s.chat}/${s.pipeline?'pipeline-mcp':'employee-mcp'}${observe?'?observe=1':''}`;
  if(S.localLibrary){const result=await api(path,body?'POST':'GET',body||undefined);employeeAssertBusinessScope(s.scope);employeeMCPAssertPrivateWork(s);if(result.error)throw Error(result.error);return result;}
  const response=await RunTeamsRequests.request(path,{method:body?'POST':'GET',device:true,readCurrent:!body,
    headers:{'Content-Type':'application/json','X-RunTeams-Device-Scope':s.deviceScope},...(body?{body:JSON.stringify(body)}:{})},s.deviceScope);
  employeeAssertBusinessScope(s.scope);employeeMCPAssertPrivateWork(s);
  const value=JSON.parse(response.text);
  if(response.status!==200||value.error)throw Error(value.error||'本机功能暂时无法核对。');
  return value;
}
function employeeMCPAssertPrivateWork(s){
  if(s.privateWork&&window.RunTeamsSourcePipelinePanels?.programContext()!==s.privateWork)throw Error('岗位工作已改变，请从原工作记录重新打开。');
}
async function employeeMCPOpen(id,trigger,pipelinePanel=null,privateWork=null){
  if(privateWork&&privateWork!==window.RunTeamsSourcePipelinePanels?.programContext())return;
  const pipeline=pipelinePanel&&pipelinePanel===window.RunTeamsSourcePipelines?.workContext()&&!RunTeamsHost.session.workspace(S);
  const panel=S.conversationPanel,chat=privateWork&&!RunTeamsHost.session.workspace(S)?privateWork:pipeline?pipelinePanel:id==null&&RunTeamsEmployeeDirectory.employeePanel(panel)&&panel.identity?.local_mcp&&!RunTeamsHost.session.workspace(S)?panel:employeeWorkChat(id);if(!chat)return;
  const s={chat:chat.id,id,pipeline:!!pipeline,privateWork,scope:_employeeBusinessScopeSequence,deviceScope:RunTeamsHost.session.deviceScope(S),trigger,loading:true,busy:false,error:'',data:null};
  _employeeMCPDialog=s;openDialog(employeeMCPOptions());await employeeMCPRead(s);
}
function employeeMCPOptions(){
  const s=_employeeMCPDialog,d=s?.data;if(!s)return {};
  const pending=d?.approvals?.[0];let body=s.loading?'<p class="employee-sdk-note" role="status">正在读取本机功能…</p>':'';
  if(d){
    if(!d.available)body+=`<p class="modal-copy">此${s.pipeline?'流水线':'员工'}版本没有本机程序。</p>`;
    else if(!d.enabled){
      body+=`<p class="modal-copy">此版本包含本机程序，启用后会以你的普通用户身份在这台电脑运行。它可能访问本机文件和网络，访问范围受系统权限与实际运行条件影响。</p><p class="employee-sdk-note">${d.packages.map(p=>esc(p.name)+' '+esc(p.version)).join('、')}。第三方账号和平台业务仍需各自授权。</p>`;
      const credentialKeys=[...new Set(d.packages.flatMap(p=>p.credential_keys||[]))];
      if(credentialKeys.length)body+=`<p class="employee-sdk-note">启用后，此版本可使用你在配置中明确选择的同名本机凭据。</p><details><summary>查看所需凭据</summary><p class="employee-sdk-note">${credentialKeys.map(esc).join('、')}</p></details>`;
      body+=s.pipeline&&(!d.applied||d.pipeline_status!=='running')?'<p class="employee-sdk-note">请先在流水线设置中应用更新并启动流水线。</p>':d.runtime_available?'<label class="employee-sdk-consent"><input id="employee_mcp_consent" type="checkbox" onchange="document.getElementById(\'employee_mcp_enable\').disabled=!this.checked"><span>我信任并允许此'+(s.pipeline?'流水线':'员工')+'版本在本机运行。</span></label>':'<p class="employee-sdk-error" role="alert">当前应用尚未包含所需运行资源。</p>';
    }else{
      body+=`<p class="modal-copy" role="status">${d.suspended?'本次运行已关闭。':'此版本的本机功能已启用。'}</p><p class="employee-sdk-note">关闭运行会保留本机工作和已有结果；下次打开不重做结果未知的操作。</p>`;
      if(d.calls.some(c=>c.state==='unknown'))body+='<p class="employee-sdk-error" role="alert">有操作的结果尚未确认。请核对原结果，系统不会自动重做。</p>';
    }
    const services=(d.connection_services||[]).flatMap(service=>service.connections.map(row=>({...row,package:service.package,program_name:service.program_name,credential_names:service.credential_names})));
    for(const [index,row] of services.entries())body+=employeeConnectionMarkup({credential_names:row.credential_names},s,index,row,'employee_mcp_connection','employeeMCPConnection',s.pipeline?'流水线':'员工');
    if(window.RunTeamsWorkResources)body+=RunTeamsWorkResources.entry(s);
    if(pending){
      const p=pending.params||{},officialTool=p._meta?.codex_approval_kind==='mcp_tool_call',description=(officialTool?p._meta.tool_description:p.reason||p.message||p.request?.message||p.questions?.map(q=>q.question).join('；')||p.name)||'此操作需要你的确认。',arguments_=p.arguments??p._meta?.tool_params;
      body+=`<section class="rt-section"><h3 class="rt-section-heading-label">操作确认</h3><p class="modal-copy">${esc(description)}</p>${p.command?`<pre class="employee-mcp-args">${esc(Array.isArray(p.command)?p.command.join(' '):p.command)}</pre>`:''}${arguments_?`<details><summary>查看操作内容</summary><pre class="employee-mcp-args">${esc(JSON.stringify(arguments_,null,2))}</pre></details>`:''}<p class="employee-sdk-note">只确认本次操作，不授予后续操作永久权限。</p>${pending.can_accept===false?'<p class="employee-sdk-error" role="alert">此操作需要的确认方式尚未接通，暂时无法执行。</p>':''}</section>`;
    }
  }
  if(s.error)body+=`<p class="employee-sdk-error" role="alert">${esc(s.error)}</p>`;
  let actions='';
  if(pending)actions=`<button class="btn" type="button" onclick="employeeMCPAnswer('decline')" ${s.busy?'disabled':''}>拒绝</button><button class="btn pri" type="button" onclick="employeeMCPAnswer('accept')" ${s.busy||pending.can_accept===false?'disabled':''}>允许本次操作</button>`;
  else if(d?.available&&!d.enabled&&d.runtime_available&&(!s.pipeline||d.applied&&d.pipeline_status==='running'))actions='<button class="btn pri" id="employee_mcp_enable" type="button" onclick="employeeMCPAction({action:\'enable\',confirm:true})" disabled>启用本机功能</button>';
  else if(d?.enabled)actions=`<button class="btn ghost" type="button" onclick="employeeMCPAction({action:'disable'})" ${s.busy?'disabled':''}>停用此版本</button><button class="btn" type="button" onclick="employeeMCPAction({action:'${d.suspended?'resume':'close'}'})" ${s.busy||!d.suspended&&!d.running||s.pipeline&&d.suspended&&d.pipeline_status!=='running'?'disabled':''}>${d.suspended?'继续运行':'关闭运行'}</button>`;
  return {className:'employee-sdk-setup',title:'本机功能',body,closeAction:'employeeMCPClose()',attrs:'role="dialog" aria-modal="true" aria-label="本机功能" onkeydown="employeeMCPKey(event)"',footer:`<button class="btn" type="button" onclick="employeeMCPClose()" ${s.busy?'disabled':''}>关闭</button><div class="grow"></div>${s.error?'<button class="btn" type="button" onclick="employeeMCPConnectionRead()" '+(s.busy?'disabled':'')+'>核对结果</button>':''}${actions}`};
}
function employeeMCPPaint(){if(_employeeMCPDialog){replaceDialog(employeeMCPOptions());document.querySelector('.employee-sdk-setup .modal-x')?.focus();}}
async function employeeMCPRead(s){
  if(s.connectionEditing&&!s.busy)return;
  const sequence=s.readSequence=(s.readSequence||0)+1,current=()=>_employeeMCPDialog===s&&s.readSequence===sequence;
  try{const data=await employeeMCPRequest(s);if(!current())return;if(data.schema!==(s.pipeline?'runteams.pipeline-mcp-work/1':'runteams.employee-mcp-work/1')||data.chat_id!==s.chat)throw Error('工作引用已变化。');const changed=JSON.stringify(data)!==JSON.stringify(s.data);s.data=data;s.loading=false;s.error='';if(changed)employeeMCPPaint();}
  catch(e){if(current()){s.loading=false;s.error=e.message;employeeMCPPaint();}}
}
async function employeeMCPAction(body){
  const s=_employeeMCPDialog;if(!s?.data||s.busy)return;
  if(body.action==='enable'&&!document.getElementById('employee_mcp_consent')?.checked)return;
  s.readSequence=(s.readSequence||0)+1;s.busy=true;s.error='';employeeMCPPaint();
  try{await employeeMCPRequest(s,{...body,binding_sha256:s.data.binding_sha256});if(_employeeMCPDialog===s){await employeeMCPRead(s);if(['enable','resume'].includes(body.action))window.RunTeamsCreatorWork?.sync();}}
  catch(e){if(_employeeMCPDialog===s)s.error=e.message;}
  finally{if(_employeeMCPDialog===s){s.busy=false;employeeMCPPaint();}}
}
function employeeMCPConnectionRow(index){return (_employeeMCPDialog?.data?.connection_services||[]).flatMap(service=>service.connections.map(row=>({...row,package:service.package,program_name:service.program_name,credential_names:service.credential_names})))[index];}
function employeeMCPConnectionCredential(index){
 const s=_employeeMCPDialog;if(!s||s.busy)return;s.connectionEditing=true;
 const select=document.getElementById('employee_mcp_connection_credential_'+index),field=document.getElementById('employee_mcp_connection_token_field_'+index),input=document.getElementById('employee_mcp_connection_token_'+index);
 if(field)field.hidden=select.value!=='new';if(input)input.value='';employeeMCPConnectionEnable(index);if(select.value==='new')input?.focus();
}
function employeeMCPConnectionEnable(index){
 const s=_employeeMCPDialog;if(!s||s.busy)return;s.connectionEditing=true;
 const choice=document.getElementById('employee_mcp_connection_credential_'+index)?.value,token=document.getElementById('employee_mcp_connection_token_'+index)?.value,consent=document.getElementById('employee_mcp_connection_consent_'+index)?.checked,button=document.getElementById('employee_mcp_connection_authorize_'+index);
 if(button)button.disabled=!consent||!choice||choice==='new'&&!token;
}
async function employeeMCPConnectionRead(){const s=_employeeMCPDialog;if(!s||s.busy)return;s.connectionEditing=false;await employeeMCPRead(s);}
async function employeeMCPConnectionAction(index,body){
 const s=_employeeMCPDialog,row=employeeMCPConnectionRow(index);if(!s||!row||s.busy)return;
 s.busy=true;s.connectionEditing=false;s.readSequence=(s.readSequence||0)+1;s.error='';employeeMCPPaint();
 try{await employeeMCPRequest(s,{...body,package:row.package,connection:row.key,binding_sha256:row.binding_sha256});if(_employeeMCPDialog===s)await employeeMCPRead(s);}
 catch(error){if(_employeeMCPDialog===s)s.error='授权结果未能确认，请先核对结果。';}
 finally{if(body.token)body.token='';if(_employeeMCPDialog===s){s.busy=false;employeeMCPPaint();}}
}
function employeeMCPConnectionAuthorize(index){
 const row=employeeMCPConnectionRow(index),select=document.getElementById('employee_mcp_connection_credential_'+index),input=document.getElementById('employee_mcp_connection_token_'+index);
 if(!row||document.getElementById('employee_mcp_connection_authorize_'+index)?.disabled)return;
 const body={action:'connection-authorize',confirm:document.getElementById('employee_mcp_connection_consent_'+index)?.checked===true,...(select.value==='new'?{token:input.value}:{credential_name:row.credential_names[Number(select.value)]})};
 if(input)input.value='';return employeeMCPConnectionAction(index,body);
}
function employeeMCPConnectionRevoke(index){const row=employeeMCPConnectionRow(index);if(row?.authorized)return employeeMCPConnectionAction(index,{action:'connection-revoke'});}

function employeeMCPAnswer(decision){const row=_employeeMCPDialog?.data?.approvals?.[0];if(row)return employeeMCPAction({action:'answer',id:row.id,decision});}
async function employeeMCPClose(){const s=_employeeMCPDialog;if(s?.busy)return;if(s?.data?.approvals?.length)await employeeMCPAnswer('cancel');if(_employeeMCPDialog!==s)return;_employeeMCPDialog=null;closeModal();if(s?.trigger?.isConnected)s.trigger.focus();}
function employeeMCPKey(event){if(event.key==='Escape'){event.preventDefault();event.stopPropagation();void employeeMCPClose();return;}if(event.key==='Tab'){const nodes=[...document.querySelectorAll('.employee-sdk-setup button:not([disabled]),.employee-sdk-setup input:not([disabled]),.employee-sdk-setup select:not([disabled]),.employee-sdk-setup summary')].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}}
function employeeMCPContext(){
  if(RunTeamsHost.session.workspace(S))return null;
  const privateWork=window.RunTeamsSourcePipelinePanels?.programContext();
  if(privateWork)return {panel:privateWork,pipeline:false,privateWork};
  const own=window.RunTeamsSourcePipelines?.workContext();
  if(own)return {panel:own,pipeline:true};
  const panel=S.conversationPanel,item=downloadedEmployeeSummary(panel?.context?.target_employee_id);
  return Number.isSafeInteger(panel?.id)&&(item?.local_mcp||panel?.identity?.local_mcp)?{panel,pipeline:false}:null;
}
async function employeeMCPNotify(chat){
  const current=employeeMCPContext(),p=current?.panel;
  if(Number(p?.id)!==Number(chat)||document.getElementById('modalHost'))return;
  return employeeMCPOpen(current.privateWork?null:current.pipeline?null:p.context?.local_employee_package?null:Number(p.context?.target_employee_id),null,current.pipeline?p:null,current.privateWork||null);
}
if(typeof window!=='undefined'){
  window.addEventListener?.('runteams:business-scope-changed',()=>{if(_employeeMCPDialog){_employeeMCPDialog=null;closeModal();}});
  // Read-only polling also delivers direct App confirmations while no model is
  // running. It neither starts author code nor grants or replays an operation.
  window.setInterval?.(async()=>{
    const current=employeeMCPContext(),p=current?.panel;
    if(_employeeMCPPolling||!p)return;
    _employeeMCPPolling=true;
    try{
      if(_employeeMCPDialog?.busy)return;
      const s=_employeeMCPDialog||{chat:p.id,pipeline:current.pipeline,privateWork:current.privateWork,scope:_employeeBusinessScopeSequence,deviceScope:RunTeamsHost.session.deviceScope(S)};
      if(s.chat!==p.id||s.pipeline!==current.pipeline)return;
      const d=await employeeMCPRequest(s,null,true),latest=employeeMCPContext();
      if(latest?.panel!==p||latest.pipeline!==current.pipeline||d.schema!=='runteams.mcp-observation/1'||d.chat_id!==p.id||d.owner!==(current.pipeline?'pipeline':'employee')||typeof d.version!=='string')return;
      if(_employeeMCPDialog===s){if(d.version!==s.data?.notification_version||(s.data?.connection_services||[]).some(service=>service.connections.some(row=>row.authorized&&row.expires_at<=Date.now()/1000)))await employeeMCPRead(s);}
      else if(!_employeeMCPDialog&&d.pending)await employeeMCPNotify(p.id);
    }catch(e){}finally{_employeeMCPPolling=false;}
  },1200);
}
