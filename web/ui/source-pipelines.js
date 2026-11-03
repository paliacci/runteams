/* Source workspaces reuse the employee conversation and the existing board.
 * References, applied graphs and work states are always returned by the host. */
(()=>{
 'use strict';
 let rows=[],catalogScope='',catalogError='',catalogErrorScope='',sequence=0,viewSequence=0,reading=false,opening=false;
 const scope=()=>JSON.stringify([_workspaceBusinessGeneration,workspaceAccountCacheToken(),workspaceDeviceStorageScope()]);
 const durableScope=()=>workspaceDeviceStorageScope();
 const referenceKey=ref=>{
  if(!ref||!['runteams.local-pipeline-reference/1','runteams.rented-pipeline-reference/1'].includes(ref.schema))return '';
  const fields=['schema','source_id','pipeline_source',...(ref.storage_kind==='local'?['storage_kind','library_id']:['account_id','deployment_id','storage_namespace'])];
  return fields.every(field=>typeof ref[field]==='string'&&ref[field])?JSON.stringify(fields.map(field=>ref[field])):'';
 };
 const entryToken=path=>btoa(unescape(encodeURIComponent(path))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
 const entryPath=token=>decodeURIComponent(escape(atob(token.replace(/-/g,'+').replace(/_/g,'/'))));
 const route=ref=>`/pipelines/local/${ref.source_id}/${entryToken(ref.pipeline_source)}`;
 const key=ref=>'pipeline-local:'+ref.source_id+':'+entryToken(ref.pipeline_source);
 const current=()=>S.surface==='source-pipeline'&&S.sourcePipelineWorkspace?.scope===scope()?S.sourcePipelineWorkspace:null;
 const matches=(s)=>!!s&&current()===s;
 function navigationTicket(){const owner=scope(),key=workspaceCurrentKey(),route=_routeSequence,switching=_workspaceSwitchSequence;return ()=>owner===scope()&&key===workspaceCurrentKey()&&route===_routeSequence&&switching===_workspaceSwitchSequence;}
 function leaveForBoard(){captureConversationPanelDraft();if(S.conversationPanel?.loading)++_conversationPanelLoadSequence;S.railMode='navigation';S._pendingRailMode='';saveRailLayout();}
 async function request(action,data={}){
  const token=scope();let reply;
  try{reply=await api('/api/device/work/source-pipelines/'+action,'POST',data);}
  catch(error){
   if(token!==scope())throw Error('工作区已改变，请重新打开流水线。');
   if(error.code)throw error;
   throw Object.assign(Error((['dispatch','control','create','edit','flow'].includes(action)||action==='employee-configuration'&&data.action==='save')?'尚未收到服务回执，请核对原操作。':'本机流水线暂时无法读取，请重试。'),{cause:error});
  }
  if(token!==scope())throw Error('工作区已改变，请重新打开流水线。');
  if(reply.error)throw Object.assign(Error(reply.error),{code:reply.code,fields:reply.fields,status:reply.code==='employee_configuration_invalid'?422:409,confirmedReply:true});
  if(action==='catalog'&&(!Array.isArray(reply.items)||!Array.isArray(reply.errors)||reply.items.some(row=>!referenceKey(row.reference)||typeof row.name!=='string'||S.localLibrary&&(row.reference.schema!=='runteams.local-pipeline-reference/1'||row.reference.storage_kind!=='local'||row.reference.library_id!==S.localLibrary.library_id))))throw Error('流水线目录回执无效。');
  return reply;
 }
 async function refreshCatalog(){
  if((!S.localLibrary&&!RunTeamsHost.session.ready(S))||RunTeamsHost.session.workspace(S)){rows=[];catalogScope='';catalogError='';catalogErrorScope='';return;}
  const token=scope();
  try{const reply=await request('catalog');if(token!==scope())return;rows=reply.items;catalogScope=token;catalogError=reply.errors.map(row=>row.error).join('；');catalogErrorScope=token;}
  catch(error){if(token===scope()){catalogError=error.message;catalogErrorScope=token;}}
  if(!S.booting)render();
 }
 function sidebar(){
  const error=catalogErrorScope===scope()?catalogError:'';
  if(catalogScope!==scope()&&!error)return '';
  const html=(catalogScope===scope()?rows:[]).map(row=>`<div class="rl"><a class="pl ${referenceKey(current()?.reference)===referenceKey(row.reference)?'on':''}" href="${esc(route(row.reference))}" onclick="event.preventDefault();RunTeamsSourcePipelines.openFromLink(this.href)"><span class="rail-pipeline-main"><span class="nm rail-marquee"><span class="rail-marquee-text">${esc(row.name)}</span></span></span></a></div>`).join('');
  return html+(error?`<div class="rail-section-hint">流水线草稿未能完整读取 <button type="button" class="btn ghost sm" onclick="RunTeamsSourcePipelines.refreshCatalog()">重试</button></div>`:'');
 }
 async function openFromLink(url){await setAppUrl(url);await applyAppRoute();}
 async function openRoute(value){
  const own=++sequence,token=scope(),panelQuery=new URLSearchParams(typeof location==='object'?location.search:'');++viewSequence;opening=false;
  workspaceCaptureCurrent({beforeRoute:true});leaveForBoard();cancelPageTransition();resetDetailWorkspace();
  S.surface='source-pipeline';S.corePipeline=null;S.chatId=null;S.chatMode='';
  const s={scope:token,storageScope:durableScope(),reference:null,data:null,error:'',loading:true,view:'board',pending:null,composer:null};S.sourcePipelineWorkspace=s;render();
  try{
   if(!RunTeamsWorkState.ready)await RunTeamsWorkState.connect();if(sequence!==own||!matches(s))return;
   const pipeline_source=entryPath(value.entry);
   const cached=await request('catalog');if(sequence!==own||!matches(s))return;
   rows=cached.items;catalogScope=token;
   const entry=rows.find(row=>row.reference.source_id===value.sourceId&&row.reference.pipeline_source===pipeline_source);
   if(!entry)throw Error('这条流水线不在当前本机工作区中。');
   s.reference=entry.reference;await setAppUrl(route(s.reference),true);if(sequence!==own||!matches(s))return;
   s.data=await request('workspace',{reference:s.reference});if(sequence!==own||!matches(s))return;
   s.pending=loadPending(s);if(s.pending)s.composer={position:s.pending.start_column_key,title:s.pending.title||'',objective:s.pending.payload?.objective||'',parameters:s.pending.payload?.parameters||{},loading:false};s.admissionUnknown=!!s.pending;s.controlPending=loadControl(s);s.controlUnknown=!!s.controlPending;s.loading=false;
   if(s.data.ui.view==='conversation')await conversation();
   if(matches(s)&&panelQuery.get('results')==='1'&&window.RunTeamsSourcePipelinePanels)await RunTeamsSourcePipelinePanels.records(panelQuery.get('delivery')?.match(/^workflow-([0-9]+)$/)?.[1]||null);
  }catch(error){if(matches(s)){s.loading=false;s.error=error.message;}}
  if(matches(s))render();
 }
 async function refresh(){
  const s=current();if(!s?.reference||reading)return false;reading=true;
  try{const data=await request('workspace',{reference:s.reference});if(!matches(s))return false;s.data=data;s.error='';return true;}
  catch(error){if(matches(s))s.error=error.message;}
  finally{reading=false;if(matches(s))render();}
 }
 // The board uses the same immutable workspace chat without navigating or sending.
 const workContext=()=>{const s=current();return s?.data&&!s.loading&&!s.error?s.workPanel||null:null;};
 async function ensureWorkContext(){
  const s=current();if(!s?.data?.programs_available||s.loading||s.error)return null;
  if(s.workPanel)return s.workPanel;
  if(s.workReading)return s.workReading;
  const config=defaultChatConfig(null);
  s.workReading=(async()=>{
   try{const reply=await request('conversation',{reference:s.reference,runtime:{channel_id:config.channel_id,model:config.model,reasoning_effort:config.reasoning_effort}});
    if(!matches(s))return null;
    const {messages,...panel}=reply.session;s.workPanel=panel;return panel;
   }finally{s.workReading=null;}
  })();return s.workReading;
 }
 async function managePrograms(trigger){
  const s=current();if(!s)return;
  try{const panel=await ensureWorkContext();if(matches(s)&&panel)return employeeMCPOpen(null,trigger,panel);}
  catch(error){if(matches(s))toast(error.message,'err');}
 }
 function status(s){
  const runtime=s.data?.runtime;if(!runtime)return '';
  if(runtime.status==='pausing')return '正在暂停';if(runtime.status==='paused')return '已暂停';
  const count=s.data.workflows.filter(row=>['ready','running','waiting_retry'].includes(row.state)).length;
  const attention=s.data.workflows.filter(row=>['blocked','needs_human','needs_approval','interrupted'].includes(row.state)).length;
  return [count?`${count} 项进行中`:'',attention?`${attention} 项待处理`:''].filter(Boolean).join('，')||'空闲';
 }
 function header(){
  const s=current();if(!s)return '';
  const name=s.data?.name||'流水线',disabled=s.loading||!!s.error||!s.data;
  const identity=`<span class="conversation-panel-heading"><span class="conversation-panel-title-wrap"><h2 id="conversation_panel_title" class="conversation-panel-name pipeline-title">${esc(name)}</h2><button type="button" class="conversation-header-action conversation-employee-session conversation-session-switcher" title="流水线会话" aria-label="打开流水线会话" onclick="RunTeamsSourcePipelines.conversation()" ${disabled||opening?'disabled':''}>${ICON('message-circle-more')}</button><span class="employee-desk-now" title="${esc(status(s))}">${esc(status(s))}</span></span></span>`;
  const controls=`<div class="conversation-panel-controls">${window.RunTeamsCreatorWork?.controls(workContext())||''}${s.view==='conversation'?`<button class="conversation-header-action creator-work-trigger" type="button" onclick="RunTeamsSourcePipelines.boardView()" aria-label="返回看板">${ICON('flow')}<span>看板</span></button>`:''}<button class="conversation-header-action creator-work-trigger" type="button" aria-label="工作记录" onclick="RunTeamsSourcePipelinePanels.toggleRecords()" ${disabled?'disabled':''}>${ICON('clock')}<span>工作记录</span></button><button class="conversation-header-action creator-work-trigger" type="button" aria-label="自动化" onclick="RunTeamsEmployeeAutomation.toggle()" ${disabled?'disabled':''}>${ICON('repeat')}<span>自动化</span></button><button class="conversation-header-action creator-work-trigger" type="button" aria-label="设置" onclick="RunTeamsSourcePipelines.settings()" ${disabled?'disabled':''}>${ICON('settings')}<span>设置</span></button></div>`;
  return RunTeamsShell.pageHeader(identity,controls,true);
 }
 function board(){
  const s=current();if(!s)return '';
  if(s.loading)return `<main class="home-workspace" aria-busy="true"><div class="board core-pipeline-board">${RunTeamsSkeletons.region('pipeline-board')}</div></main>`;
  if(!s.data)return `<main class="home-workspace">${RunTeamsLoadFailure.markup({variant:'local',title:'流水线暂时无法读取',error:s.error,retry:'applyAppRoute()'})}</main>`;
  const columns=[...s.data.pipeline.positions,...s.data.pipeline.states];
  const checkColumn=s.pending&&(columns.find(column=>column.key===s.pending.start_column_key&&['employee','approval'].includes(column.kind))||columns.find(column=>['employee','approval'].includes(column.kind)));
  const notice=s.error?RunTeamsLoadFailure.markup({variant:'local',title:'进度暂未更新',error:s.error,retry:'RunTeamsSourcePipelines.refresh()'}):'';
  const cards=s.data.workflows.map(row=>({...row,task:{title:row.title,payload_json:{objective:row.objective}},pipeline_reference:s.reference}));
  const html=columns.map(column=>{
   const items=cards.filter(row=>row.cursor_key===column.key);
   const accepts=['employee','approval'].includes(column.kind),canCheck=column===checkColumn,canRun=!s.pending&&s.data.runtime.status==='running';
   return `<div class="col core-pipeline-column ${accepts?'':'core-state-column'}"><div class="col-surface"><div class="chd"><span class="column-worker-title"><span>${esc(column.name)}</span></span>${s.data.ui.mode==='creator'?`<button type="button" class="btn ghost sm" aria-label="编辑${esc(column.name)}" data-position="${esc(column.key)}" onclick="RunTeamsSourcePipelinePanels.editor(this.dataset.position)">${ICON('more')}</button>`:''}${items.length?`<span class="cnt">${items.length}</span>`:''}</div><div class="lane" data-node-id="${esc(column.key)}">${items.map(row=>coreWorkflowCard(row).replace(' aria-haspopup="menu"','')).join('')}${accepts?`<button type="button" class="addcard core-add-task" data-position="${esc(column.key)}" onclick="RunTeamsSourcePipelines.compose(this.dataset.position)" ${canRun||canCheck?'':'disabled'}>${ICON(canCheck?'check':'plus')}<span>${canCheck?'核对受理结果':'新建任务'}</span></button>`:''}</div></div></div>`;
  }).join('');
  return `<main class="home-workspace source-pipeline-workspace" aria-label="流水线工作区"><main class="board core-pipeline-board"><div class="cols">${html}</div>${s.data.ui.mode==='creator'?'<button type="button" class="btn ghost source-pipeline-add-role" onclick="RunTeamsSourcePipelinePanels.editor()">编辑岗位与流转</button>':''}${notice}${!cards.length&&!s.pending?'<p class="source-pipeline-empty">从任一岗位新建任务，开始这条流水线的工作。</p>':''}</main></main>`;
 }
 async function conversation(){
  const s=current();if(!s?.data||opening)return;const previousView=s.view,turn=++viewSequence,active=()=>turn===viewSequence&&matches(s);opening=true;render();
  try{
   const config=defaultChatConfig(null),reply=await request('conversation',{reference:s.reference,runtime:{channel_id:config.channel_id,model:config.model,reasoning_effort:config.reasoning_effort}});
   if(!active())return;
   const session=reply.session,{messages,...summary}=session;s.workPanel=summary;S.chats=[summary,...S.chats.filter(row=>String(row.id)!==String(session.id))];
   s.view='conversation';S.railMode='assistant';S._pendingRailMode='';
   const panel=await loadConversationPanelSession(session.id,{pipelineId:null,enforcePipeline:false,railHosted:true,focus:false,expand:false});if(!active())return;if(panel?.error)throw Error(panel.error);
   s.view='conversation';await saveView(s,'conversation');if(!active())return;S.railMode='assistant';S.railRouteHydrating=false;resetDetailWorkspace();await setAppUrl(route(s.reference),true);render();
  }catch(error){if(active()){s.view=previousView;if(previousView==='board')leaveForBoard();toast(error.message,'err');}}
  finally{if(turn===viewSequence)opening=false;if(matches(s))render();}
 }
 async function boardView(){const s=current();if(!s)return;++viewSequence;opening=false;captureConversationPanelDraft();leaveForBoard();s.view='board';resetDetailWorkspace();await setAppUrl(route(s.reference),true);if(!matches(s))return;render();await saveView(s,'board');}
 async function saveView(s,view){
  s.desiredView=view;
  if(s.viewSaving)return s.viewSaving;
  const owned=()=>s.scope===scope();
  const saving=(async()=>{
   let repaired=false;
   while(owned()){
    const desired=s.desiredView;
    try{
     const reply=await request('preferences',{reference:s.reference,expected_revision:s.data.ui.revision,view:desired});
     if(!owned())return;s.data.ui=reply.ui;
     if(s.desiredView===desired)return;
    }catch(error){
     if(!owned())return;
     if(!error.confirmedReply||repaired)throw error;repaired=true;
     const latest=await request('workspace',{reference:s.reference});if(!owned())return;s.data.ui=latest.ui;
    }
   }
  })();
  const guarded=saving.catch(error=>{if(matches(s))toast(error.message,'err');}).finally(()=>{if(s.viewSaving===guarded)s.viewSaving=null;});
  s.viewSaving=guarded;return guarded;
 }
 async function boot(accountRead,measurement){
  try{
   await accountRead;if(S.accountSessionError||!RunTeamsHost.session.ready(S))throw Error(S.accountSessionError||'请先登录。');
   S.deviceSessionActor=String(RunTeamsHost.session.actor(S));S.workspaceWindows=loadWorkspaceWindows();S.conversationPanelDrafts=loadConversationPanelDrafts();
   S.booting=false;S.bootError=null;S.workspaceStartup=null;restoreModelCatalogDisplay();if(RunTeamsRoutes.preview(location.href).kind==='source-pipeline'){const target=new URL(location.href);for(const name of [...target.searchParams.keys()])if(!['results','delivery'].includes(name))target.searchParams.delete(name);await setAppUrl(target.pathname+target.search,true);}
   void refreshDeviceDirectory().catch(()=>{});void refreshWorkspaceNavigation().catch(()=>{});
   const token=scope();
   void Promise.allSettled([accountSettingsReadPreferences(),modelChannelData().configuration(true)]).then(results=>{
    if(token!==scope())return;const reply=results[1].status==='fulfilled'?results[1].value:null;
    if(reply&&!reply.error){S.channels=reply.channels||[];S.providerCatalog=reply.providers||[];if(reply.catalog?.channels){S.modelCatalog=reply.catalog.channels;S.modelCatalogReady=true;}}
    render();
   });
   await applyAppRoute({initial:true});RunTeamsRequests.finishPage(measurement,'settled');
  }catch(error){S.booting=true;S.bootError=error;renderBootShell(S.bootRoute,error);}
 }
 function select(kind,extra={}){selectDetailWorkspace({type:'source-pipeline',id:kind,...extra});render();}
 function settings(){return RunTeamsSourcePipelinePanels.settings();}
 async function setMode(mode){const s=current();if(!s?.data)return;
  try{const reply=await request('preferences',{reference:s.reference,expected_revision:s.data.ui.revision,mode});if(!matches(s))return;s.data.ui=reply.ui;render();}
  catch(error){if(matches(s)){toast(error.message,'err');await refresh();}}
 }
 async function control(action){
  const s=current();if(!s?.data||s.controlBusy)return;
  // Preserve the exact command until its receipt is known. Update never starts.
  s.controlPending||={operation_id:crypto.randomUUID(),reference:s.reference,action,expected_revision:s.data.runtime.revision,...(action==='update'?{source_revision:s.data.source_revision}:{})};
  const command=s.controlPending;try{RunTeamsWorkState.setItem(controlKey(s),JSON.stringify(command));}catch(error){s.controlError='本机保存失败，尚未提交控制操作。';s.controlPending=null;render();return;}s.controlBusy=true;render();
  try{if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const result=await request(s.controlUnknown?'control-operation':'control',command);if(!matches(s))return;if(result.status==='unknown'){s.controlCanRetry=true;s.controlError='尚未查到原操作回执，可以沿原操作重试。';return;}RunTeamsWorkState.removeItem(controlKey(s));s.controlPending=null;s.controlUnknown=false;s.controlCanRetry=false;s.controlError='';await refresh();}
  catch(error){if(matches(s)){s.controlCanRetry=false;s.controlUnknown=error.code==='operation_unknown'||!error.confirmedReply;if(!s.controlUnknown){RunTeamsWorkState.removeItem(controlKey(s));s.controlPending=null;await refresh();}s.controlError=error.message;}}
  finally{s.controlBusy=false;if(s.controlPending&&!matches(s))s.controlUnknown=true;if(matches(s))render();}
 }
 async function retryControl(){const s=current();if(!s?.controlPending||!s.controlCanRetry||s.controlBusy)return;s.controlUnknown=false;s.controlCanRetry=false;return control(s.controlPending.action);}
 async function retryAdmission(){const s=current();if(!s?.pending||!s.canRetryAdmission||s.sending)return;s.admissionUnknown=false;s.canRetryAdmission=false;return submit();}
 const controlKey=s=>'runteams.pipeline-control:'+s.storageScope+':'+referenceKey(s.reference);
 function loadControl(s){try{return JSON.parse(RunTeamsWorkState.getItem(controlKey(s))||'null');}catch(error){s.error='原控制操作未能读取，请先核对本机存储。';return null;}}
 const pendingKey=s=>'runteams.pipeline-admission:'+s.storageScope+':'+referenceKey(s.reference);
 function loadPending(s){try{return JSON.parse(RunTeamsWorkState.getItem(pendingKey(s))||'null');}catch(error){s.error='上次受理记录未能读取，请先核对本机存储。';return null;}}
 async function compose(position){
  const s=current();if(!s?.data)return;if(s.pending){select('compose');return;}
  if(s.composer?.position===position&&s.composer.contract){select('compose');return;}
  const draft=s.composer?.position===position?s.composer:null;
  select('compose');s.composer={loading:true,position,error:'',title:draft?.title||'',objective:draft?.objective||'',parameters:draft?.parameters||{}};render();
  try{const contract=await request('contract',{reference:s.reference,start_column_key:position});if(matches(s)&&s.composer?.position===position){s.composer.contract=contract;s.composer.loading=false;render();}}
  catch(error){if(matches(s)&&s.composer?.position===position){s.composer.error=error.message;s.composer.loading=false;render();}}
 }
 async function submit(){
  const s=current(),form=document.getElementById('source_pipeline_task');if(!s||s.sending)return;
  if(!s.pending){
   if(!form?.reportValidity())return;
   try{
   const values=new FormData(form),parameters=readCoreTaskParameters(form);
   const command={operation_id:crypto.randomUUID(),reference:s.reference,start_column_key:s.composer.position,title:String(values.get('title')).trim(),payload:{schema:'runteams.task-input/v2',objective:String(values.get('objective')).trim(),context:{},parameters,inputs:[],module_bindings:{},asset_bindings:{}}};
   RunTeamsWorkState.setItem(pendingKey(s),JSON.stringify(command));s.pending=command;s.admissionUnknown=false;
   }catch(error){s.submitError=error.message||'本机保存失败，任务尚未受理。';render();return;}
  }
  s.sending=true;s.submitError='';render();
  try{
   if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const reply=await request(s.admissionUnknown?'operation':'dispatch',s.pending);if(!matches(s))return;
   if(reply.status==='unknown'){s.canRetryAdmission=true;s.submitError='尚未查到受理回执。重试会沿原操作继续，不会另建任务。';return;}
   RunTeamsWorkState.removeItem(pendingKey(s));s.pending=null;s.admissionUnknown=false;s.composer=null;resetDetailWorkspace();await refresh();
  }catch(error){if(matches(s)){s.canRetryAdmission=false;s.admissionUnknown=error.code==='operation_unknown'||!error.confirmedReply;if(!s.admissionUnknown){RunTeamsWorkState.removeItem(pendingKey(s));s.pending=null;if(!s.composer?.contract&&s.composer?.position)await compose(s.composer.position);}s.submitError=error.message;}}
  finally{s.sending=false;if(s.pending&&!matches(s))s.admissionUnknown=true;if(matches(s))render();}
 }
 async function openWork(id){const s=current();if(!s)return;select('work',{workflowId:id,loading:true});const owner=S.sel;
  try{const reply=await request('work',{reference:s.reference,workflow_id:Number(id)});if(matches(s)&&S.sel===owner){owner.workflow=reply.workflow;owner.inputContract=reply.input_contract;owner.loading=false;render();}}
  catch(error){if(matches(s)&&S.sel===owner){owner.loading=false;owner.error=error.message;render();}}
 }
 function drawer(){
  const s=current(),selection=S.sel;if(!s||selection?.type!=='source-pipeline')return '';
  if(selection.id==='automation')return RunTeamsEmployeeAutomation.drawer();
  if(['settings','editor'].includes(selection.id)&&window.RunTeamsSourcePipelinePanels)return RunTeamsSourcePipelinePanels.drawer();
  let title='',body='',footer='';
  if(selection.id==='compose'){
   title=s.pending?'核对受理结果':'新建任务';const c=s.composer;
   if(s.pending)body=`<p><b>${esc(s.pending.title)}</b></p><p>${esc(s.pending.payload?.objective||'')}</p><p>原输入已保留，受理确认后会显示在看板中。</p>${s.submitError?`<p role="alert">${esc(s.submitError)}</p>`:''}`;
   else if(c?.loading)body=RunTeamsSkeletons.region('parameters');
   else if(c?.error)body=RunTeamsLoadFailure.markup({variant:'local',title:'任务输入暂时无法读取',error:c.error,retry:`RunTeamsSourcePipelines.compose('${c.position}')`});
   else if(c?.contract)body=`<form id="source_pipeline_task" onsubmit="event.preventDefault();RunTeamsSourcePipelines.submit()"><label class="lbl" for="source_pipeline_title">任务名称</label><input class="input" id="source_pipeline_title" name="title" required maxlength="160" value="${esc(c.title)}" oninput="S.sourcePipelineWorkspace.composer.title=this.value"><label class="lbl" for="source_pipeline_objective">工作目标</label><textarea class="input" id="source_pipeline_objective" name="objective" required oninput="S.sourcePipelineWorkspace.composer.objective=this.value">${esc(c.objective)}</textarea><div oninput="S.sourcePipelineWorkspace.composer.parameters=readCoreTaskParameters(this)">${coreTaskParameterFields(coreWorkflowFrozenParameters(c.contract),c.parameters,'source_pipeline')}</div></form>`;
   if(s.submitError&&!s.pending)body+=`<p role="alert">${esc(s.submitError)}</p>`;
   footer=`<div class="run-footer"><button class="btn pri" type="button" ${s.sending||!s.pending&&!c?.contract?'disabled':''} onclick="${s.pending&&s.canRetryAdmission?'RunTeamsSourcePipelines.retryAdmission()':'RunTeamsSourcePipelines.submit()'}">${s.sending?'正在核对':s.pending?s.canRetryAdmission?'重试原受理':'核对受理结果':'开始工作'}</button></div>`;
  }else if(selection.id==='work'){
   return RunTeamsSourcePipelinePanels.workDrawer(selection);
  }
  return detailDrawerShell({className:'source-pipeline-drawer',header:`<div class="dh"><span class="dt">${esc(title)}</span><div class="grow"></div><button type="button" class="btn ghost sm" aria-label="关闭详情" onclick="closeDetailWorkspace()">${ICON('x')}</button></div>`,body,footer});
 }
 let creation=null;
 const creationKey=()=> 'runteams.pipeline-create:'+durableScope();
 async function newPipeline(){
  const token=scope(),ticket=navigationTicket(),previousModal=document.getElementById('modalHost')?.firstChild;
  try{
   if(!RunTeamsWorkState.ready)await RunTeamsWorkState.connect();const reply=await request('creation-choices');if(token!==scope()||!ticket()||document.getElementById('modalHost')?.firstChild!==previousModal)return;
   creation={scope:token,choices:reply.items,choiceErrors:reply.errors||[],pending:JSON.parse(RunTeamsWorkState.getItem(creationKey())||'null'),busy:false,error:''};
   creationDialog();
  }catch(error){if(token===scope()&&ticket())toast(error.message,'err');}
 }
 function creationDialog(){
  if(!creation||creation.scope!==scope())return;
  const c=creation,disabled=c.busy||!!c.pending;
  openDialog({title:'新建流水线',body:`${c.choices.length?`<form id="source_pipeline_create" onsubmit="event.preventDefault();RunTeamsSourcePipelines.create()"><label class="lbl" for="source_pipeline_create_name">流水线名称</label><input class="input" style="width:100%" id="source_pipeline_create_name" name="name" required maxlength="80" value="${esc(c.name||c.pending?.name||'')}" oninput="RunTeamsSourcePipelines.creationName(this.value)" ${disabled?'disabled':''}><label class="lbl" for="source_pipeline_first_role">第一个岗位</label><select class="input" style="width:100%" id="source_pipeline_first_role" name="choice" required ${disabled?'disabled':''}><option value="">选择已有员工和技能</option>${c.choices.map((row,index)=>`<option value="${index}">${esc(row.employee_name+' / '+row.skill_name+(row.project_name?' · '+row.project_name:'')+' · '+(row.origin||'创作')+' '+(row.version||''))}</option>`).join('')}</select></form><p>创建后可直接从岗位新建任务，无需发布。</p>`:'<p>先准备或取得一名带有工作技能的完整员工，再把它加入流水线。</p>'}${c.error?`<p role="alert">${esc(c.error)}</p>`:''}`,footer:`<button class="btn" type="button" onclick="closeModal()">关闭</button><div class="grow"></div><button class="btn pri" type="button" onclick="RunTeamsSourcePipelines.create()" ${c.busy||!c.pending&&!c.choices.length?'disabled':''}>${c.busy?'正在创建':c.pending?'核对创建结果':'创建流水线'}</button>`});c.modal=document.getElementById('modalHost')?.firstChild;
 }
 async function create(){
  const c=creation;if(!c||c.busy||c.scope!==scope())return;const revealTicket=navigationTicket();
  const form=document.getElementById('source_pipeline_create');
  if(!c.pending){
   if(!form?.reportValidity())return;
   try{
   const values=new FormData(form),choice=c.choices[Number(values.get('choice'))];
   c.name=String(values.get('name')).trim();c.pending={operation_id:crypto.randomUUID(),employee_reference:choice.reference,source_revision:choice.revision,skill_key:choice.skill_key,name:c.name,...(choice.dependency?.kind==='download'?{dependency:structuredClone(choice.dependency)}:{})};
   RunTeamsWorkState.setItem(creationKey(),JSON.stringify(c.pending));
   }catch(error){c.pending=null;c.error=error.message||'本机保存失败，尚未创建流水线。';creationDialog();return;}
  }
  c.busy=true;creationDialog();
  try{if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const reply=await request('create',c.pending);if(c.scope!==scope()||creation!==c)return;const visible=revealTicket()&&c.modal?.isConnected&&document.getElementById('modalHost')?.firstChild===c.modal;RunTeamsWorkState.removeItem(creationKey());if(visible)closeModal();else c.modal?.remove();creation=null;const emptyModal=document.getElementById('modalHost')?.firstChild;await refreshCatalog();if(visible&&revealTicket()&&c.scope===scope()&&document.getElementById('modalHost')?.firstChild===emptyModal)await openFromLink(route(reply.reference));}
  catch(error){if(c.scope===scope()&&creation===c){if(error.confirmedReply){RunTeamsWorkState.removeItem(creationKey());c.pending=null;}c.error=error.message;}}
  finally{c.busy=false;if(creation===c&&revealTicket()&&c.scope===scope()&&c.modal?.isConnected&&document.getElementById('modalHost')?.firstChild===c.modal)creationDialog();}
 }
 function reset(){sequence++;viewSequence++;rows=[];catalogScope='';catalogError='';catalogErrorScope='';opening=false;reading=false;creation=null;}
 window.addEventListener('runteams:business-scope-will-change',reset);
 setInterval(()=>{if(!document.hidden&&current()?.data&&!S.sourcePipelineWorkspace.sending&&!opening&&!S.sel&&current().view==='board')void refresh();},8000);
 window.RunTeamsSourcePipelines={workContext,ensureWorkContext,managePrograms,request,select,status,current,refreshCatalog,items:()=>catalogScope===scope()?rows.slice():[],sidebar,openRoute,openFromLink,refresh,route,key,referenceKey,boot,header,board,conversation,boardView,settings,setMode,control,compose,submit,openWork,drawer,reset,newPipeline,create,retryControl,retryAdmission,creationName:value=>{if(creation)creation.name=value;}};
})();
