/* Source workspaces reuse the employee conversation and the existing board.
 * References, applied graphs and work states are always returned by the host. */
(()=>{
 'use strict';
 let rows=[],catalogScope='',catalogError='',catalogErrorScope='',catalogSequence=0,sequence=0,viewSequence=0,reading=false,opening=false;
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
 const sameScope=s=>s?.scope===scope();
 const current=()=>S.surface==='source-pipeline'&&sameScope(S.sourcePipelineWorkspace)?S.sourcePipelineWorkspace:null;
 const matches=(s)=>!!s&&current()===s;
 function navigationTicket(){const owner=scope(),key=workspaceCurrentKey(),route=_routeSequence,switching=_workspaceSwitchSequence;return ()=>owner===scope()&&key===workspaceCurrentKey()&&route===_routeSequence&&switching===_workspaceSwitchSequence;}
 function leaveForBoard(){captureConversationPanelDraft();if(S.conversationPanel?.loading)++_conversationPanelLoadSequence;S.railMode='navigation';S._pendingRailMode='';saveRailLayout();}
 async function request(action,data={}){
  const token=scope(),configuration=action==='configuration'||action==='employee-configuration'||action==='work-configuration';
  const control=action==='control'||action==='control-operation',edit=action==='edit'||action==='edit-operation',flow=action==='flow'||action==='flow-operation';let reply;
  try{reply=await api('/api/device/work/source-pipelines/'+action,'POST',data,{readCurrent:action==='catalog'||action==='workspace'||action==='settings'||action==='work',errorStatus:configuration||control||edit||flow});}
  catch(error){
   if(token!==scope())throw Error('工作区已改变，请重新打开流水线。');
   if((configuration||control||edit||flow)&&error.status>=400&&error.status<500)error.confirmedReply=true;
   if(error.code||(configuration||control||edit||flow)&&error.status)throw error;
   throw Object.assign(Error((['dispatch','control','create','edit','flow'].includes(action)||action==='employee-configuration'&&data.action==='save')?'尚未收到服务回执，请核对原操作。':'本机流水线暂时无法读取，请重试。'),{cause:error});
  }
  if(token!==scope())throw Error('工作区已改变，请重新打开流水线。');
  if(reply?.error)throw Object.assign(Error(reply.error),{code:reply.code,fields:reply.fields,reason:reply.reason,status:reply.status??(reply.code==='employee_configuration_invalid'?422:409),
   confirmedReply:!(control||edit||flow)||reply.status>=400&&reply.status<500});
  if(action==='catalog'&&(!Array.isArray(reply.items)||!Array.isArray(reply.errors)||reply.items.some(row=>!referenceKey(row.reference)||typeof row.name!=='string'||S.localLibrary&&(row.reference.schema!=='runteams.local-pipeline-reference/1'||row.reference.storage_kind!=='local'||row.reference.library_id!==S.localLibrary.library_id))))throw Error('流水线目录回执无效。');
  return reply;
 }
 async function readCatalog(){
  const token=scope();
  if(readCatalog.pending?.token===token)return readCatalog.pending;
  const own=++catalogSequence,active=()=>own===catalogSequence&&token===scope();
  const pending=(async()=>{
   try{
    const reply=await request('catalog');
    if(active()){
     rows=reply.items;catalogScope=token;
     catalogError=reply.errors.length?'incomplete':'';catalogErrorScope=token;
    }
    return reply.items;
   }catch(error){
    if(active()){catalogError='unavailable';catalogErrorScope=token;}
    throw error;
   }
  })();
  pending.token=token;readCatalog.pending=pending;
  if(catalogScope!==token&&catalogErrorScope!==token){
   const status=document.querySelector('[data-pipeline-catalog-status]');
   if(status){status.hidden=false;status.innerHTML=catalogLoadingCopy;window.RunTeamsLocale?.apply(status);}
  }
  window.dispatchEvent(new Event('runteams:pipeline-catalog-changed'));
  try{return await pending;}finally{
   if(readCatalog.pending===pending){
    readCatalog.pending=null;
    window.dispatchEvent(new Event('runteams:pipeline-catalog-changed'));
   }
  }
 }
 function catalogState(){
  const token=scope();
  return {ready:catalogScope===token,loading:readCatalog.pending?.token===token,failed:catalogErrorScope===token&&!!catalogError};
 }
 async function refreshCatalog(){
  if((!S.localLibrary&&!RunTeamsHost.session.ready(S))||RunTeamsHost.session.workspace(S)){++catalogSequence;rows=[];catalogScope='';catalogError='';catalogErrorScope='';return;}
  try{await readCatalog();}catch{/* The current catalog error is shown in the sidebar. */}
  if(!S.booting)render();
 }
 const sidebarPinsKey=()=>`runteams_sidebar_source_pipeline_pins_v1:${durableScope()}`;
 function sidebarPins(){
  try{
   const value=JSON.parse(localStorage.getItem(sidebarPinsKey())||'[]');
   return Array.isArray(value)?value:[];
  }catch{return [];}
 }
 function toggleSidebarPin(id){
  const pins=sidebarPins();
  const next=pins.includes(id)?pins.filter(pin=>pin!==id):[...pins,id];
  try{localStorage.setItem(sidebarPinsKey(),JSON.stringify(next));}
  catch(error){toast(error.message,'err');return;}
  render();
  document.querySelector(`[data-pipeline-row="${CSS.escape(id)}"]>a`)?.focus({preventScroll:true});
 }
 async function renameFromSidebar(row){
  const token=scope(),id=referenceKey(row.reference);
  try{
   if(referenceKey(current()?.reference)!==id)await openFromLink(route(row.reference));
   if(token!==scope()||referenceKey(current()?.reference)!==id)return;
   const heading=document.querySelector('#rgPipelineHead h2[data-pipeline-rename]');
   if(heading)startNameEdit(heading);
   else toast('当前流水线名称不可编辑。','info','pipelineCreate.renameUnavailable');
  }catch(error){if(token===scope())toast(error.message,'err');}
 }
 function sidebarMenu(event){
  if(event.type==='keydown'&&event.key!=='ContextMenu'&&!(event.key==='F10'&&event.shiftKey))return;
  event.preventDefault();event.stopPropagation();
  const element=event.currentTarget.closest('[data-pipeline-row]'),id=element.dataset.pipelineRow;
  const token=scope(),row=catalogScope===token&&rows.find(item=>referenceKey(item.reference)===id);
  if(!row)return;
  const own=fn=>()=>{if(token===scope()&&catalogScope===token&&rows.some(item=>referenceKey(item.reference)===id))return fn();};
  const pinned=sidebarPins().includes(id);
  const items=[{label:pinned?'取消置顶':'置顶',labelKey:pinned?'conversationDetail.unpin':'conversationDetail.pin',icon:pinned?'pin-off':'pin',fn:own(()=>toggleSidebarPin(id))}];
  if(row.reference.schema==='runteams.local-pipeline-reference/1'&&row.allowed_modes?.includes('creator'))items.push({label:'重命名',labelKey:'conversationDetail.rename',icon:'edit',fn:own(()=>renameFromSidebar(row))});
  const extra=RunTeamsHost.assets.uninstallAction?.('pipeline',row);
  if(extra)items.push({divider:true},{...extra,fn:own(extra.fn)});
  const options=event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY}}:{align:'right'};
  const button=element.querySelector('.rail-source-pipeline-more');
  const fromLink=event.type==='keydown'&&event.target!==button;
  const currentRow=()=>token===scope()?document.querySelector(`[data-pipeline-row="${CSS.escape(id)}"]`):null;
  const currentAnchor=()=>currentRow()?.querySelector('.rail-source-pipeline-more');
  const keyboardReturn=()=>token===scope()?((fromLink?currentRow()?.querySelector('a'):currentAnchor())||document.querySelector('.rail-pipelines')):null;
  openMenu(button,items,{variant:'railItem',keyboardReturn,currentAnchor,...options});
 }
 const catalogLoadingCopy='<span role="status" data-app-i18n="globalSearch.pipelinesLoading">正在读取流水线目录…</span>';
 function catalogStatus(token,count){
  const error=catalogErrorScope===token?catalogError:'';
  if(error){
   const key=!count?'catalogUnavailable':error==='incomplete'?'catalogIncomplete':'catalogRefreshFailed';
   const copy=!count?'无法读取流水线。':error==='incomplete'?'部分流水线无法读取。':'无法更新流水线列表。';
   const retry=RunTeamsLoadFailure.button({key:'sidebar-pipeline-catalog',variant:'local',compact:true,labelKey:'globalSearch.retry',busyLabelKey:'globalSearch.pipelinesLoading',retry:'RunTeamsSourcePipelines.refreshCatalog()',focusFallback:'.rail-pipelines'});
   return `<span role="alert" data-app-i18n="pipelineBoard.${key}">${copy}</span> ${retry}`;
  }
  return catalogScope!==token&&readCatalog.pending?.token===token&&!count?catalogLoadingCopy:'';
 }
 function sidebar({active}){
  const token=scope();
  const activeKey=active?referenceKey(current()?.reference):'';
  let selected=false;
  const byId=new Map((catalogScope===token?rows:[]).map(row=>[referenceKey(row.reference),row]));
  const pins=new Set(sidebarPins());
  const ordered=[...pins].filter(id=>byId.has(id)).concat([...byId.keys()].filter(id=>!pins.has(id)));
  const menuAnchor=document.getElementById('popmenu')?._currentAnchor?.();
  const html=ordered.map(id=>{
   const row=byId.get(id),isCurrent=activeKey===id,menuOpen=menuAnchor?.closest('[data-pipeline-row]')?.dataset.pipelineRow===id;
   selected||=isCurrent;
   return `<div class="rl rail-source-pipeline-row" data-pipeline-row="${esc(id)}" oncontextmenu="RunTeamsSourcePipelines.sidebarMenu(event)" onkeydown="RunTeamsSourcePipelines.sidebarMenu(event)" onmouseenter="railMarqueeStart(this)" onmouseleave="railMarqueeStop(this)"><a class="pl${isCurrent?' on':''}${pins.has(id)?' pinned':''}" aria-current="${isCurrent?'page':'false'}" href="${esc(route(row.reference))}" onclick="event.preventDefault();RunTeamsSourcePipelines.openFromLink(this.href)"><span class="rail-pipeline-main"><span class="nm rail-marquee"><span class="rail-marquee-text">${esc(row.name)}</span></span></span></a><button type="button" class="rail-source-pipeline-more rail-item-more${menuOpen?' menu-trigger-active':''}" data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="${menuOpen}" aria-label="${esc(row.name)}的更多操作" data-app-i18n-aria-label="pipelineBoard.rowActionsFor" data-app-i18n-vars="${esc(JSON.stringify({name:row.name}))}" onclick="RunTeamsSourcePipelines.sidebarMenu(event)">${ICON('more')}</button></div>`;
  }).join('');
  const status=catalogStatus(token,ordered.length);
  return {selected,markup:html+`<div class="rail-section-hint" data-pipeline-catalog-status${status?'':' hidden'}>${status}</div>`};
 }
 async function openFromLink(url){await setAppUrl(url);await applyAppRoute();}
 async function openRoute(value){
  const own=++sequence,token=scope(),panelQuery=new URLSearchParams(typeof location==='object'?location.search:'');++viewSequence;opening=false;
  workspaceCaptureCurrent({beforeRoute:true});leaveForBoard();cancelPageTransition();resetDetailWorkspace();
  S.surface='source-pipeline';S.corePipeline=null;S.chatId=null;S.chatMode='';
  const s={scope:token,storageScope:durableScope(),reference:null,data:null,error:'',loading:true,view:'board',restoringConversation:RunTeamsStaticPages.pipelineViewHint()==='conversation',pending:null,composer:null};S.sourcePipelineWorkspace=s;render();
  try{
   const pipeline_source=entryPath(value.entry);
   const [items]=await Promise.all([readCatalog(),RunTeamsWorkState.ready?null:RunTeamsWorkState.connect()]);
   if(sequence!==own||!matches(s))return;
   const entry=items.find(row=>row.reference.source_id===value.sourceId&&row.reference.pipeline_source===pipeline_source);
   if(!entry){s.loading=false;s.restoringConversation=false;s.error='这条流水线不在当前工作区中。';s.errorKey='pipelineBoard.missingPipeline';render();return;}
   s.reference=entry.reference;s.name=entry.name;await setAppUrl(route(s.reference),true);if(sequence!==own||!matches(s))return;
   s.data=await request('workspace',{reference:s.reference});if(sequence!==own||!matches(s))return;
   restorePendingCommands(s);s.loading=false;
   RunTeamsStaticPages.rememberPipelineView(route(s.reference),s.data.ui.view);
   s.restoringConversation=s.data.ui.view==='conversation';
   if(s.restoringConversation)await conversation(false,{restoring:true});
   if(matches(s)&&panelQuery.get('results')==='1'&&window.RunTeamsSourcePipelinePanels){
    const workflowId=Number(panelQuery.get('delivery')?.match(/^workflow-([0-9]+)$/)?.[1]);
    if(Number.isSafeInteger(workflowId)&&workflowId>0)await openWork(workflowId,{showDeliveries:true});
    else await RunTeamsSourcePipelinePanels.records();
   }
  }catch(error){if(matches(s)){s.loading=false;s.restoringConversation=false;s.error=error.message;}}
  if(matches(s))render();
 }
 function restorePendingCommands(s){
  s.pending=loadPending(s);
  if(s.pending)s.composer={position:s.pending.start_column_key,title:s.pending.title||'',objective:s.pending.payload?.objective||'',parameters:s.pending.payload?.parameters||{},loading:false};
  s.admissionUnknown=!!s.pending;
  s.controlPending=loadControl(s);
  s.controlUnknown=!!s.controlPending;
 }
 async function retryRecovery(){
  const s=current();if(!s?.data||!s.errorKey)return;
  try{await RunTeamsWorkState.connect(true);}catch{return;}
  if(!matches(s))return;
  s.error='';delete s.errorKey;
  restorePendingCommands(s);
  render();
 }
 async function refresh({afterEdit=false,silent=false}={}){
  const s=current();if(!s?.reference||reading&&!afterEdit)return false;
  const requestId=s.refreshSequence=(s.refreshSequence||0)+1;
  const active=()=>matches(s)&&s.refreshSequence===requestId;
  reading=true;let repaint=!silent;
  try{
   const data=await request('workspace',{reference:s.reference});if(!active())return false;
   if(data.runtime.status!=='pausing'&&s.controlBusy!=='submitting')delete s.controlLabelKey;
   repaint||=JSON.stringify(s.data)!==JSON.stringify(data)||!!s.error&&!s.errorKey;
   s.data=data;window.RunTeamsWorkRecords?.updateTaskList(s);if(!s.errorKey)s.error='';return true;
  }
  catch(error){if(active()&&!silent&&!s.errorKey)s.error=error.message;}
  finally{if(s.refreshSequence===requestId)reading=false;if(active()&&repaint)render();}
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

 function runtimeLabelKey(data){
  return data.runtime.status==='paused'?'paused':'runtimeRunning';
 }
 function runtimeAction(s,disabled){
  const runtime=s.data?.runtime;
  if(!runtime)return '';
  const loading=s.controlBusy==='submitting'||runtime.status==='pausing';
  const labelKey=loading&&s.controlLabelKey||runtimeLabelKey(s.data);
  const running=labelKey!=='paused',action=running?'pause':'start';
  const label=running?'运行中':'已暂停';
  const accessible=running?'pausePipeline':'startPipeline';
  const actionLabel=running?'暂停流水线':'启动流水线';
  return `<button type="button" class="source-pipeline-runtime-action" ${disabled||s.controlPending||s.controlBusy||loading?'disabled':''} ${loading?'aria-busy="true"':''} onclick="RunTeamsSourcePipelines.control('${action}')"
   aria-label="${actionLabel}" title="${actionLabel}" data-app-i18n-aria-label="pipelineBoard.${accessible}" data-app-i18n-title="pipelineBoard.${accessible}">
   ${loading?'<span class="pipeline-run-spinner" aria-hidden="true"></span>':ICON(running?'pause':'play')}<span data-app-i18n="pipelineBoard.${labelKey}">${label}</span>
  </button>`;
 }
 function boardWorkflows(s){
  const columns=RunTeamsSourcePipelinePanels.columns(s,true),columnKeys=new Set(columns.map(column=>column.key));
  const recordsOnly=new Set((s.data.pipeline.states||[]).filter(column=>column.kind==='done'&&column.records_only===true).map(column=>column.key));
  return s.data.workflows.filter(row=>columnKeys.has(row.cursor_key)&&!(row.state==='completed'&&recordsOnly.has(row.cursor_key)));
 }
 function statusMarkup(s){
  if(!s.data?.runtime)return '';
  const {markup,phases}=RunTeamsHeaderStatus,owner='pipeline:'+referenceKey(s.reference);
  if(s.data.runtime.status==='paused')return '';
  if(s.errorKey||s.error)return '';
  const eligible=boardWorkflows(s).filter(row=>Object.hasOwn(phases,row.state));
  if(!eligible.length)return '';
  const priority=eligible.reduce((best,row)=>Math.min(best,phases[row.state][0]),Infinity);
  return markup(owner,eligible.filter(row=>phases[row.state][0]===priority).map(row=>({
   id:row.id,state:row.state,text:row.title,label:`${phases[row.state][1]}：${row.title}`,
   labelKey:'pipelineBoard.'+row.state,action:'RunTeamsSourcePipelines.openWork(this.dataset.statusId)',
  })));
 }
 function editName(event){
  if(event.type==='keydown'&&(event.isComposing||!['Enter',' '].includes(event.key)))return;
  event.preventDefault();
  startNameEdit(event.currentTarget);
 }
 function startNameEdit(heading){
  const s=current();
  if(!s?.data||s.data.ui.mode!=='creator'||s.reference?.schema!=='runteams.local-pipeline-reference/1'||s.nameEdit||s.renaming)return;
  const input=document.createElement('input'),original=s.data.name;
  input.type='text';input.id=heading.id;input.className='conversation-panel-name pipeline-title pipeline-title-input';input.value=original;
  sizeInlineHeaderName(input,heading);
  input.maxLength=80;input.setAttribute('aria-label','流水线名称');input.dataset.appI18nAriaLabel='pipelineCreate.name';s.nameEdit=input;
  let cancelled=false;
  input.onkeydown=key=>{
   if(key.isComposing||key.keyCode===229||!['Enter','Escape'].includes(key.key))return;
   key.preventDefault();cancelled=key.key==='Escape';input.blur();
  };
  input.onblur=async()=>{
   s.nameEdit=null;
   const name=input.value.trim();
   if(input.isConnected)input.replaceWith(heading);
   if(!matches(s))return;
   if(cancelled){heading.focus({preventScroll:true});render();return;}
   if(!name||name===original){render();return;}
   s.renaming=true;
   try{await RunTeamsSourcePipelinePanels.rename(name,original);await refreshCatalog();}
   catch(error){
    if(matches(s)){
     const key=error.pipelineRenameKey||'renameFailed',fallback=error.pipelineRenameKey?error.message:'无法保存流水线名称。请稍后重试。';
     toast(fallback,'err','pipelineCreate.'+key);
    }
   }
   finally{s.renaming=false;if(matches(s))render();}
  };
  heading.replaceWith(input);window.RunTeamsLocale?.apply(input);input.focus({preventScroll:true});input.setSelectionRange(input.value.length,input.value.length);
 }
 function header(){
  const s=current();if(!s)return '';
  if(s.loading)return RunTeamsSkeletons.workspaceHeader({pipeline:true});
  const name=s.data?.name||s.name||'流水线',disabled=s.loading||!!s.errorKey||!s.data;
  const titleAttributes=`${s.data?.name||s.name?'':' data-app-i18n="pipelineBoard.pipeline"'}${!disabled&&s.data.ui.mode==='creator'&&s.reference.schema==='runteams.local-pipeline-reference/1'?` role="button" tabindex="0" data-pipeline-rename data-app-i18n-aria-label="pipelineBoard.rename" data-app-i18n-vars="${esc(JSON.stringify({name}))}"`+' aria-label="'+esc(name)+'，编辑流水线名称" onclick="RunTeamsSourcePipelines.editName(event)" onkeydown="RunTeamsSourcePipelines.editName(event)"':''}`;
  const identity=RunTeamsShell.workspaceHeading(name,titleAttributes,runtimeAction(s,disabled)+statusMarkup(s));
  const drawerAction=(label,labelKey,icon,action,selected)=>RunTeamsShell.headerAction({label,labelKey,icon:ICON(icon),action,selected,disabled});
  const pipelineDrawer=S.sel?.type==='source-pipeline'?S.sel.id:'';
  const recordsOpen=S.sel?.type==='core-results'&&S.sel.sourceWorkspace===s;
  const controls=`<div class="conversation-panel-controls">${drawerAction('工作记录','workRecords.title','clipboard-clock','RunTeamsSourcePipelinePanels.toggleRecords()',recordsOpen)}${drawerAction('自动化','pipelineBoard.automation','header-automation','RunTeamsEmployeeAutomation.toggle()',pipelineDrawer==='automation')}${s.data?.programs_available?window.RunTeamsCreatorWork?.controls(workContext())||'':''}${drawerAction('设置','pipelineBoard.settings','settings','RunTeamsSourcePipelines.settings()',['settings','members'].includes(pipelineDrawer))}</div>`;
  return RunTeamsShell.pageHeader(identity,controls,true);
 }
 function boardEmpty(s,columns,cards){
  if(s.error||s.pending)return '';
  const visible=new Set(columns.map(column=>column.key));
  if(cards.some(card=>visible.has(card.cursor_key)))return '';
  let key='empty',label='从岗位新建任务，开始这条流水线的工作。';
  if(cards.length){
   key='emptyHiddenTasks';label='当前显示的列中没有任务。可在分组中显示其他列。';
  }else if(s.data.runtime.status==='paused'){
   key='emptyPaused';label='这条流水线已暂停。启动后即可新建任务。';
  }else if(s.data.runtime.status==='pausing'){
   key='emptyPausing';label='这条流水线正在暂停。恢复运行后即可新建任务。';
  }else if(!columns.some(column=>['employee','approval'].includes(column.kind))){
   key='emptyHiddenRoles';label='当前没有显示可接收任务的岗位。可在分组中显示岗位。';
  }
  return `<p class="source-pipeline-empty" data-app-i18n="pipelineBoard.${key}">${label}</p>`;
 }
 async function retryBoard(){
  const s=current();
  if(!await refresh()||!matches(s)||document.activeElement!==document.body)return;
  const board=document.querySelector('.source-pipeline-workspace .core-pipeline-board');
  const target=board?.querySelector('.core-add-task:not(:disabled)')||board?.querySelector('.column-worker-title, .source-pipeline-add-stage:not(:disabled), .source-pipeline-add-role');
  target?.focus({preventScroll:true});
 }
 function workspaceFeedback(s){
  if(!s?.data)return '';
  const hasCards=boardWorkflows(s).length>0;
  const noteKey=s.errorKey?undefined:hasCards?'pipelineBoard.cachedBoard':'pipelineBoard.cachedEmptyBoard';
  const notice=s.error?RunTeamsLoadFailure.markup({variant:'local',title:s.errorKey?s.error:'无法更新进度',titleKey:s.errorKey||'pipelineBoard.refreshFailed',
   note:noteKey?(hasCards?'正在显示上次载入的看板。':'上次载入看板时还没有任务。'):'',noteKey,
   labelKey:'employeeHistory.retry',busyLabelKey:'pipelineBoard.loading',retry:s.errorKey?'RunTeamsSourcePipelines.retryRecovery()':'RunTeamsSourcePipelines.retryBoard()'}):'';
  let runtime='';
  if(s.controlBusy==='checking'){
   runtime='<p class="source-pipeline-runtime-checking" role="status" data-app-i18n="pipelineBoard.checking">正在核对…</p>';
  }else if(s.controlBusy!=='submitting'&&(s.controlPending||s.controlError)){
   runtime=`<div class="source-pipeline-runtime-message">${operationError(s.controlError||{key:'controlCheckHint'})}</div>`;
   if(s.controlPending){
    const [label,key,action]=s.controlCanRetry?['重试操作','retryControl','retryControl()']:
     ['核对操作结果','checkControl',`control('${s.controlPending.action}')`];
    runtime+=`<button type="button" class="btn" data-pipeline-runtime-recovery ${s.errorKey?'disabled':''} onclick="RunTeamsSourcePipelines.${action}" data-app-i18n="pipelineBoard.${key}">${label}</button>`;
   }
  }
  return notice||runtime?`<div class="source-pipeline-workspace-feedback">${notice}${runtime?`<div class="source-pipeline-runtime-feedback">${runtime}</div>`:''}</div>`:'';
 }
 function board(){
  const s=current();if(!s)return '';
  if(s.loading)return RunTeamsSkeletons.pipelineBoard();
  if(!s.data)return `<main class="home-workspace">${RunTeamsLoadFailure.markup({variant:'local',title:s.errorKey?s.error:"无法读取流水线",titleKey:s.errorKey||'pipelineBoard.readFailed',labelKey:'employeeHistory.retry',busyLabelKey:'pipelineBoard.loading',error:s.error,retry:'applyAppRoute()'})}</main>`;
  const columns=RunTeamsSourcePipelinePanels.columns(s);
  const checkColumn=!s.errorKey&&s.pending&&(columns.find(column=>column.key===s.pending.start_column_key&&['employee','approval'].includes(column.kind))||columns.find(column=>['employee','approval'].includes(column.kind)));
  const cards=boardWorkflows(s).map(row=>({...row,task:{title:row.title,payload_json:{objective:row.objective}},pipeline_reference:s.reference}));
  const html=columns.map(column=>{
   const items=cards.filter(row=>row.cursor_key===column.key);
   const accepts=['employee','approval'].includes(column.kind),canCheck=column===checkColumn,canRun=!s.errorKey&&!s.pending&&s.data.runtime.status==='running';
   const selected=S.sel?.type==='source-pipeline'&&S.sel.id==='position'&&S.sel.positionKey===column.key;
   const key=esc(column.key),name=esc(column.name);
   const more=`<button type="button" class="column-more" data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="false" title="更多列操作" aria-label="${name}的更多操作" data-app-i18n-title="pipelineBoard.columnActions" data-app-i18n-aria-label="pipelineBoard.columnActionsFor" data-app-i18n-vars="${esc(JSON.stringify({name:column.name}))}" data-position="${key}" onclick="RunTeamsSourcePipelinePanels.columnMenu(event,this.dataset.position)">${ICON('more')}</button>`;
   return `<div class="col ${accepts?'column-job':'column-status core-state-column'} column-color-${esc(column.tone)} core-pipeline-column${selected?' sel':''}"><div class="col-surface" data-position="${key}" onclick="RunTeamsSourcePipelinePanels.columnClick(event,this.dataset.position)"><div class="chd k-${esc(column.kind)}" data-position="${key}" oncontextmenu="RunTeamsSourcePipelinePanels.columnMenu(event,this.dataset.position)"><button type="button" class="column-worker-title" data-position="${key}" onclick="RunTeamsSourcePipelinePanels.position(this.dataset.position)">${RunTeamsSourcePipelinePanels.columnAvatar(column)}<span class="t">${name}</span></button><div class="column-actions">${more}</div></div><div class="lane" data-node-id="${esc(column.key)}">${items.map(row=>coreWorkflowCard(row,column.kind)).join('')}${accepts?`<button type="button" class="addcard core-add-task" data-position="${esc(column.key)}" onclick="RunTeamsSourcePipelines.compose(this.dataset.position)" ${canRun||canCheck?'':'disabled'}>${ICON(canCheck?'check':'plus')}<span data-app-i18n="pipelineBoard.${canCheck?'checkTask':'newTask'}">${canCheck?'核对任务状态':'新建任务'}</span></button>`:''}</div></div></div>`;
  }).join('');
  const addStage=s.data.ui.mode==='creator'?'<div class="col"><button type="button" class="draft-column-trigger source-pipeline-add-stage" aria-haspopup="dialog" aria-expanded="false" onclick="RunTeamsSourcePipelinePanels.addStageMenu(this)" '+(s.error?'disabled':'')+'>'+ICON('plus')+'<span class="t" data-app-i18n="pipelineBoard.newStage">新环节</span></button></div>':'';
  return `<main class="home-workspace source-pipeline-workspace" aria-label="流水线工作区" data-app-i18n-aria-label="pipelineBoard.workspace"><section class="board core-pipeline-board" aria-label="任务看板" data-app-i18n-aria-label="pipelineBoard.taskBoard"><div class="cols">${html}${addStage}</div>${!columns.length?'<button type="button" class="btn ghost source-pipeline-add-role" onclick="RunTeamsSourcePipelinePanels.columnMenu(event)" data-app-i18n="pipelineEditor.editGroup">编辑分组</button>':''}${s.data.ui.mode==='creator'?'<button type="button" class="btn ghost source-pipeline-add-role" onclick="RunTeamsSourcePipelinePanels.editor()" data-app-i18n="pipelineBoard.editRoles">编辑岗位与流转</button>':''}${boardEmpty(s,columns,cards)}</section></main>`;
 }
 function workspace(){
  const s=current(),expanded=s?.view==='conversation';
  if(s?.restoringConversation)return RunTeamsStaticPages.pipelineConversationPending();
  const label=expanded?'看板':'对话';
  const labelKey=expanded?'board':'chat';
  const action=expanded?'boardView()':'conversation(true)';
  const accessibleLabel=expanded?'返回看板':opening?'正在打开流水线对话…':'打开流水线对话';
  const accessibleKey=expanded?'back':opening?'conversationOpening':'openConversation';
  const toggle=s?.data?`<button type="button" class="source-pipeline-view-toggle" aria-label="${accessibleLabel}" data-app-i18n-aria-label="pipelineBoard.${accessibleKey}" ${opening?'aria-busy="true" disabled':''} onclick="RunTeamsSourcePipelines.${action}">${ICON(expanded?'kanban-columns':'message-circle-more')}<span data-app-i18n="pipelineBoard.${labelKey}">${label}</span></button>`:'';
  return `${workspaceFeedback(s)}<div class="source-pipeline-layers"><div class="source-pipeline-board-layer"${expanded?' inert':''}>${board()}</div>${expanded?`<div class="source-pipeline-conversation-layer">${conversationWorkspaceMain({includeHeader:false})}</div>`:''}${toggle}</div>`;
 }
 async function animateConversation(commit,active,{prepareConversation=false}={}){
  const shell=document.getElementById('rgBody'),head=document.getElementById('rgPipelineHead');
  const mid=document.getElementById('rgMid'),button=document.querySelector('.source-pipeline-view-toggle');
  if(!active())return;
  if(!shell||!head||!mid||!button||matchMedia('(prefers-reduced-motion: reduce)').matches){commit();return;}
  const header=head.getBoundingClientRect(),content=mid.getBoundingClientRect();
  const tab=shell.querySelector('#rgWorkspaceTabs .workspace-tab.on'),tabs=tab?.closest('.workspace-tabs-scroll');
  let x,y,innerRadius,radius;
  const tint=document.createElement('div');
  tint.className='source-pipeline-transition';
  tint.setAttribute('aria-hidden','true');
  const regions=[];
  const waves=[{node:tint,left:0,top:0}];
  const addRegion=(left,top,right,bottom,kind)=>{
   if(right<=left||bottom<=top)return;
   const region=document.createElement('div');
   region.className=kind;
   Object.assign(region.style,{left:left+'px',top:top+'px',width:right-left+'px',height:bottom-top+'px'});
   tint.append(region);
   regions.push({left,top,right,bottom});
   return region;
  };
  addRegion(header.left,content.top,header.right,content.bottom,'source-pipeline-transition-main');
  const headerTint=addRegion(header.left,header.top,header.right,header.bottom,'source-pipeline-transition-header');
  if(headerTint){
   headerTint.setAttribute('aria-hidden','true');
   headerTint.style.left='0';
   headerTint.style.top='0';
   head.prepend(headerTint);
   waves.push({node:headerTint,left:header.left,top:header.top});
  }
  if(tab&&tabs){
   const box=tab.getBoundingClientRect(),viewport=tabs.getBoundingClientRect();
   const corner=parseFloat(getComputedStyle(tab,'::after').width)||0;
   const left=Math.max(box.left-corner,viewport.left),right=Math.min(box.right+corner,viewport.right);
   const region=addRegion(left,box.top,right,header.top,'source-pipeline-transition-tab-clip');
   if(region){
    const shape=document.createElement('div');
    shape.className='source-pipeline-transition-tab';
    Object.assign(shape.style,{left:box.left-left+'px',width:box.width+'px',borderRadius:getComputedStyle(tab).borderRadius});
    shape.style.setProperty('--pipeline-tab-corner',corner+'px');
    region.setAttribute('aria-hidden','true');
    region.style.left=left-box.left+'px';
    region.style.top='0';
    region.append(shape);
    tab.prepend(region);
    waves.push({node:region,left,top:box.top});
   }
  }
  if(!regions.length){commit();return;}
  const alignToButton=()=>{
   const anchor=(document.querySelector('.source-pipeline-view-toggle')||button).getBoundingClientRect();
   innerRadius=anchor.width/2;
   x=anchor.left+innerRadius;y=anchor.top+anchor.height/2;
   radius=Math.ceil(Math.max(...regions.map(({left,top,right,bottom})=>Math.hypot(Math.max(Math.abs(x-left),Math.abs(x-right)),Math.max(Math.abs(y-top),Math.abs(y-bottom))))))+1;
  };
  const center=({left,top})=>`${x-left}px ${y-top}px`;
  const paintCover=r=>{for(const part of waves)part.node.style.clipPath=`circle(${r}px at ${center(part)})`;};
  const paintReveal=r=>{for(const part of waves)part.node.style.maskImage=`radial-gradient(circle at ${center(part)},transparent ${r}px,#000 ${r+.5}px)`;};
  const wave=(paint,initial)=>new Promise(resolve=>{
   let started;
   const step=now=>{
    if(!active()||!tint.isConnected){resolve(false);return;}
    if(headerTint&&!headerTint.isConnected)document.getElementById('rgPipelineHead')?.prepend(headerTint);
    started??=now;
    const progress=Math.min(1,(now-started)/250);
    const eased=progress*progress*(3-2*progress);
    paint(initial+(radius-initial)*eased);
    if(progress===1)resolve(true);else requestAnimationFrame(step);
   };
   requestAnimationFrame(step);
  });
  try{
   if(prepareConversation){
    shell.classList.add('source-pipeline-preparing-conversation');
    commit();
   }
   alignToButton();
   paintCover(innerRadius);
   paintReveal(innerRadius);
   shell.append(tint);
   if(!await wave(paintCover,innerRadius)||!active())return;
   if(prepareConversation)shell.classList.remove('source-pipeline-preparing-conversation');
   else commit();
   alignToButton();
   paintReveal(innerRadius);
   await wave(paintReveal,innerRadius);
  }finally{
   if(prepareConversation)shell.classList.remove('source-pipeline-preparing-conversation');
   for(const {node} of waves)node.remove();
  }
 }
 async function conversation(fromBoard=false,{restoring=false,draft='',signingWorkflowId=null}={}){
  const s=current();if(!s?.data||opening||s.view==='conversation'||(fromBoard&&document.querySelector('.source-pipeline-transition')))return;
  const sourceSelection=draft?S.sel:null;
  const selectionCurrent=()=>!sourceSelection||S.sel===sourceSelection;
  const turn=++viewSequence,active=()=>turn===viewSequence&&matches(s);
  opening=true;render();
  try{
   const config=defaultChatConfig(null),reply=await request('conversation',{reference:s.reference,runtime:{channel_id:config.channel_id,model:config.model,reasoning_effort:config.reasoning_effort},...(signingWorkflowId?{signing_workflow_id:signingWorkflowId}:{})});
   if(!active()||!selectionCurrent())return;
   const session=reply.session,{messages,...summary}=session;s.workPanel=summary;S.chats=[summary,...S.chats.filter(row=>String(row.id)!==String(session.id))];
   const refresh=!!cachedConversationPanel(session.id)?.error;
   const panel=await loadConversationPanelSession(session.id,{railHosted:true,focus:false,expand:false,render:false,refresh,restoreWorkspace:!draft});
   if(!active()||!selectionCurrent())return;
   if(!panel||panel.error)throw Error('Unable to load the pipeline conversation');
   const show=()=>{
    s.boardSelection=S.sel;
    s.signingWorkflowId=signingWorkflowId;
    resetDetailWorkspace();
    s.restoringConversation=false;s.view='conversation';S.railMode='assistant';S._pendingRailMode='';S.railRouteHydrating=false;
    if(draft&&!String(panel.input||'').includes(draft)){
     setConversationDraftValue('panel',[panel.input,draft].filter(Boolean).join('\n\n'));
    }
    opening=false;render();
    restoreConversationReadingPosition(panel);
    if(draft)document.getElementById('conversation_box')?.focus({preventScroll:true});
   };
   if(fromBoard)await animateConversation(show,active,{prepareConversation:true});else show();
   if(!active())return;
   if(fromBoard)document.querySelector('.source-pipeline-view-toggle')?.focus({preventScroll:true});
   if(!restoring)await saveView(s,'conversation');
  }catch{
   if(active()){
    s.restoringConversation=false;leaveForBoard();
    toast('无法打开流水线对话。请重试。','err','pipelineBoard.conversationFailed');
   }
  }finally{
   if(turn===viewSequence&&opening){
    opening=false;
    if(matches(s)){render();if(fromBoard)document.querySelector('.source-pipeline-view-toggle')?.focus({preventScroll:true});}
   }
  }
 }
 async function boardView(){
  const s=current();if(!s||s.view!=='conversation'||s.closingConversation||document.querySelector('.source-pipeline-transition'))return;
  const turn=++viewSequence,active=()=>turn===viewSequence&&matches(s);
  s.closingConversation=true;
  try{
   await animateConversation(()=>{
    captureConversationReadingPosition();leaveForBoard();s.view='board';
    detailWorkspaceController().restore(s.boardSelection||null);delete s.boardSelection;
    render();
   },active);
  }finally{s.closingConversation=false;}
  if(!active())return;
  await setAppUrl(route(s.reference),true);
  if(!matches(s))return;
  const selection=S.sel;
  const signingWorkflowId=s.signingWorkflowId;
  delete s.signingWorkflowId;
  if(signingWorkflowId&&await refresh()&&matches(s)&&S.sel===selection&&Number(selection?.workflowId)===signingWorkflowId){
   await openWork(signingWorkflowId,{returnToRecords:selection.returnToRecords,showDeliveries:selection.workSections?.deliveries});
  }
  if(!active())return;
  render();document.querySelector('.source-pipeline-view-toggle')?.focus({preventScroll:true});
  await saveView(s,'board');
 }
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
     if(!owned())return;s.data.ui=reply.ui;RunTeamsStaticPages.rememberPipelineView(route(s.reference),reply.ui.view);
     if(s.desiredView===desired)return;
    }catch(error){
     if(!owned())return;
     if(!error.confirmedReply||repaired)throw error;repaired=true;
     const latest=await request('workspace',{reference:s.reference});if(!owned())return;s.data.ui=latest.ui;
    }
   }
  })();
  const guarded=saving.catch(()=>{if(matches(s))toast('无法保存视图偏好。','err','pipelineBoard.viewSaveFailed');}).finally(()=>{if(s.viewSaving===guarded)s.viewSaving=null;});
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
 function settings(){
  if(S.sel?.type==='source-pipeline'&&S.sel.id==='settings')return closeDetailWorkspace();
  return RunTeamsSourcePipelinePanels.settings();
 }
 async function control(action){
  const s=current();if(!s?.data||s.errorKey||s.controlBusy)return;
  // Preserve the exact command until its receipt is known. Update never starts.
  const previous=s.controlPending,focus=document.activeElement?.matches?.('.source-pipeline-runtime-action,[data-pipeline-runtime-recovery]');
  s.controlPending||={operation_id:crypto.randomUUID(),reference:s.reference,action,expected_revision:s.data.runtime.revision,...(action==='update'?{source_revision:s.data.source_revision}:{})};
  const command=s.controlPending;try{RunTeamsWorkState.setItem(controlKey(s),JSON.stringify(command));}catch(error){s.controlError={key:'controlNotSent',detail:error.message};s.controlPending=previous;render();return;}
  const checking=!!s.controlUnknown;
  if(!checking)s.controlLabelKey=runtimeLabelKey(s.data);
  s.controlBusy=checking?'checking':'submitting';render();
  try{
   if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();
   const result=await request(checking?'control-operation':'control',command);
   if(!matches(s))return;
   if(result?.operation_id!==command.operation_id)throw Error('Invalid pipeline action receipt');
   if(checking&&result.status==='unknown'){
    s.controlCanRetry=true;s.controlError={key:'controlRetryHint'};return;
   }
   if(result.status!=='committed'||result.receipt?.action!==command.action)throw Error('Unconfirmed pipeline action');
   RunTeamsWorkState.removeItem(controlKey(s));s.controlPending=null;s.controlUnknown=false;s.controlCanRetry=false;s.controlError='';
   await refresh();
  }catch(error){
   if(matches(s)){
    s.controlCanRetry=false;s.controlUnknown=checking||error.code==='operation_unknown'||!error.confirmedReply;
    if(!s.controlUnknown){RunTeamsWorkState.removeItem(controlKey(s));s.controlPending=null;await refresh();}
    s.controlError={key:checking?'controlReadFailed':s.controlUnknown?'controlCheckHint':'controlFailed',detail:error.message};
   }
  }
  finally{
   s.controlBusy=false;
   if(s.data.runtime.status!=='pausing')delete s.controlLabelKey;
   if(s.controlPending&&!matches(s))s.controlUnknown=true;
   if(matches(s)){
    render();
    if(focus&&document.activeElement===document.body){
     const target=document.querySelector('[data-pipeline-runtime-recovery]:not(:disabled),.source-pipeline-runtime-action:not(:disabled)');
     target?.focus({preventScroll:true});
    }
   }
  }
 }
 async function retryControl(){const s=current();if(!s?.controlPending||!s.controlCanRetry||s.controlBusy)return;s.controlUnknown=false;s.controlCanRetry=false;return control(s.controlPending.action);}
 async function retryAdmission(){const s=current();if(!s?.pending||!s.canRetryAdmission||s.sending)return;s.admissionUnknown=false;s.canRetryAdmission=false;return submit();}
 const controlKey=s=>'runteams.pipeline-control:'+s.storageScope+':'+referenceKey(s.reference);
 const pendingKey=s=>'runteams.pipeline-admission:'+s.storageScope+':'+referenceKey(s.reference);
 function readPendingCommand(s,key,valid,errorKey,fallback){
  try{
   const raw=RunTeamsWorkState.getItem(key);
   if(raw===null)return null;
   const command=JSON.parse(raw);
   if(typeof command?.operation_id==='string'&&command.operation_id&&referenceKey(command.reference)===referenceKey(s.reference)&&valid(command))return command;
  }catch{}
  s.error=fallback;s.errorKey=errorKey;
  return null;
 }
 function loadControl(s){
  return readPendingCommand(s,controlKey(s),command=>['start','pause','update'].includes(command.action),'pipelineBoard.controlRecoveryFailed','无法读取上次的流水线操作。');
 }
 function loadPending(s){
  return readPendingCommand(s,pendingKey(s),command=>typeof command.start_column_key==='string'&&!!command.start_column_key&&command.payload?.schema==='runteams.task-input/v2','pipelineBoard.taskRecoveryFailed','无法读取上次提交的任务。');
 }
 async function compose(position,retry=false){
  const s=current();if(!s?.data||s.errorKey)return;
  if(s.pending){select('compose');return;}
  const previous=s.composer?.position===position?s.composer:null;
  if(previous&&(previous.contract||previous.loading)){select('compose');return;}
  const c={loading:true,position,error:'',title:previous?.title||'',objective:previous?.objective||'',parameters:previous?.parameters||{}};
  s.composer=c;select('compose');
  const visible=()=>matches(s)&&s.composer===c&&S.sel?.type==='source-pipeline'&&S.sel.id==='compose';
  try{
   const contract=await request('contract',{reference:s.reference,start_column_key:position});
   if(matches(s)&&s.composer===c)c.contract=contract;
  }catch(error){if(matches(s)&&s.composer===c)c.error=error.message;}
  finally{
   c.loading=false;
   if(visible()){
    render();
    if(retry&&c.contract&&document.activeElement===document.body)document.getElementById('source_pipeline_title')?.focus({preventScroll:true});
   }
  }
 }
 async function submit(){
  const s=current(),form=document.getElementById('source_pipeline_task');if(!s||s.errorKey||s.sending)return;
  const selection=S.sel,focused=document.activeElement?.closest?.('#rgDrawer .source-pipeline-compose-drawer');
  if(!s.pending){
   if(!form)return;
   const values=new FormData(form),title=String(values.get('title')||'').trim(),objective=String(values.get('objective')||'').trim();
   if(!title||!objective){
    s.submitError={key:title?'taskObjectiveRequired':'taskNameRequired'};render();
    document.getElementById(title?'source_pipeline_objective':'source_pipeline_title')?.focus();
    return;
   }
   try{
   const parameters=readCoreTaskParameters(form);
   const command={operation_id:crypto.randomUUID(),reference:s.reference,start_column_key:s.composer.position,title,payload:{schema:'runteams.task-input/v2',objective,context:{},parameters,inputs:[],module_bindings:{},asset_bindings:{}}};
   RunTeamsWorkState.setItem(pendingKey(s),JSON.stringify(command));s.pending=command;s.admissionUnknown=false;
   }catch(error){s.submitError={key:'taskNotSent',detail:error.message,detailKey:error.detailKey,detailVars:error.detailVars};render();return;}
  }
  s.sending=true;s.submitError='';render();
  let completedTask;
  try{
   if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const reply=await request(s.admissionUnknown?'operation':'dispatch',s.pending);if(!matches(s))return;
   if(reply.status==='unknown'){s.canRetryAdmission=true;s.submitError={key:'taskRetryHint'};return;}
   RunTeamsWorkState.removeItem(pendingKey(s));s.pending=null;s.admissionUnknown=false;s.composer=null;
   const showBoard=S.sel?.type==='source-pipeline'&&S.sel.id==='compose';
   if(showBoard)resetDetailWorkspace();
   if(showBoard)completedTask=(reply.result||reply).workflow?.id;
   await refresh({afterEdit:true});
  }catch(error){if(matches(s)){s.canRetryAdmission=false;s.admissionUnknown=error.code==='operation_unknown'||!error.confirmedReply;if(!s.admissionUnknown){RunTeamsWorkState.removeItem(pendingKey(s));s.pending=null;if(!s.composer?.contract&&s.composer?.position)await compose(s.composer.position);}s.submitError={key:s.admissionUnknown?'taskCheckHint':'taskFailed',detail:error.message};}}
  finally{
   s.sending=false;
   if(s.pending&&!matches(s))s.admissionUnknown=true;
   if(matches(s)){
    render();
    if(focused&&document.activeElement===document.body){
     if(completedTask&&!S.sel)document.querySelector(`.source-pipeline-workspace [data-workflow-id="${Number(completedTask)}"]`)?.focus();
     else if(S.sel===selection)document.querySelector('.source-pipeline-compose-drawer [data-task-submit]:not(:disabled)')?.focus({preventScroll:true});
    }
   }
  }
 }
 let activityConnection;
 function activityTarget(){
  const workspace=current(),selection=S.sel;
  if(!workspace||!selection||document.hidden)return;
  if(selection.type==='source-pipeline'&&selection.id==='work'&&selection.workflow?.state==='running'){
   const run=RunTeamsWorkRecords.currentExecutionOutsideHistory(selection.workflow);
   if(run)return {workspace,selection,run,workflowId:Number(selection.workflow.id)};
  }
  const context=selection.attemptContext;
  if(context&&selection.status==='ready'&&context.account===workspaceAccountCacheToken()&&
     referenceKey(selection.scope.source_pipeline_reference)===referenceKey(workspace.reference)){
   const result=selection.data?.results?.find(item=>item.key===selection.resultKey);
   const run=result?.attempts?.[0];
   if(result?.state==='running'&&Number(run?.id)===context.runId)
    return {workspace,selection,run,workflowId:context.workflowId,result};
  }
 }
 function ownsActivity(connection,target){
  return connection&&target&&connection.workspace===target.workspace&&connection.selection===target.selection&&
   connection.workflowId===target.workflowId&&connection.runId===Number(target.run.id);
 }
 function stopActivity(){
  const previous=activityConnection;activityConnection=null;
  previous?.controller.abort();
 }
 function retainActivity(selection,run){
  const connection=activityConnection;
  if(run?.state==='running'&&connection?.received&&!connection.retryAt&&
     connection.selection===selection&&connection.runId===Number(run.id))run.live_activity=connection.snapshot;
 }
 function syncActivity(){
  const target=activityTarget();
  if(ownsActivity(activityConnection,target)&&(!activityConnection.retryAt||Date.now()<activityConnection.retryAt))return;
  stopActivity();
  if(!target)return;
  const {workspace,selection,workflowId,run}=target,runId=Number(run.id);
  if(!Number.isSafeInteger(runId)||runId<=0)return;
  const controller=new AbortController(),connection={workspace,selection,workflowId,runId,controller};
  activityConnection=connection;
  RunTeamsHost.lifecycle.stream('/api/device/work/source-pipelines/work-activity',
   {reference:workspace.reference,workflow_id:workflowId,run_id:runId},event=>{
    if(event.type!=='work_activity'||activityConnection!==connection||!ownsActivity(connection,activityTarget()))return;
    connection.received=true;connection.snapshot=event.activity;
    if(connection.frame)return;
    connection.frame=requestAnimationFrame(()=>{
     connection.frame=null;
     const latest=activityTarget();
     if(activityConnection!==connection||!ownsActivity(connection,latest))return;
     latest.run.live_activity=connection.snapshot;
     const markup=RunTeamsWorkRecords.liveActivityMarkup(latest.run,!latest.result);
     if(latest.result)latest.result.liveActivity=markup;
     const region=document.querySelector(`#rgDrawer [data-pipeline-activity="${runId}"]`);
     if(region&&markup){
      if(region.innerHTML!==markup){
       const focused=region.contains(document.activeElement);
       region.innerHTML=markup;
       region.closest('#rgDrawer').dataset.activityPatched='';
       if(focused)region.querySelector('button')?.focus({preventScroll:true});
      }
     }else if(region||markup){
      if(latest.result)RunTeamsWorkRecords.position(selection);
      render();
      if(latest.result)RunTeamsWorkRecords.restore(selection);
     }
    });
   },{observe:true,signal:controller.signal}).catch(()=>{/* The normal work read continues to refresh the panel. */})
   .finally(()=>{connection.retryAt=Date.now()+1500;});
 }
 function applyWorkReply(owner,reply){
  if(!current()||S.sel!==owner)return false;
  if(!reply?.workflow||Number(reply.workflow.id)!==Number(owner.workflowId))throw Error('任务回执无效。');
  retainActivity(owner,RunTeamsWorkRecords.currentExecutionOutsideHistory(reply.workflow));
  Object.assign(owner,{workflow:reply.workflow,inputContract:reply.input_contract,taskConfiguration:reply.task_configuration,
   signingSetup:reply.signing_setup,humanRequest:reply.human_request,loading:false,error:''});
  RunTeamsSourcePipelinePanels.mountSigningConfiguration(owner);
  return true;
 }
 async function refreshOpenWork(s,owner,{force=false}={}){
  const previous=owner.workflow;
  const card=s.data?.workflows?.find(row=>Number(row.id)===Number(previous?.id));
  const changed=card&&(card.state!==previous?.state||card.cursor_key!==previous?.cursor_key);
  if(owner.refreshingWork||!previous||!force&&!changed&&!['ready','running','waiting_retry'].includes(previous.state))return;
  owner.refreshingWork=true;
  try{
   const reply=await request('work',{reference:s.reference,workflow_id:previous.id});
   if(!matches(s)||S.sel!==owner||owner.workflow!==previous)return;
   const latest=reply.workflow;
   if(latest)retainActivity(owner,RunTeamsWorkRecords.currentExecutionOutsideHistory(latest));
   const businessChanged=latest?.state!==previous.state||latest?.updated_at!==previous.updated_at||latest?.cursor_key!==previous.cursor_key;
   if(!businessChanged){
    const activityKey=work=>{
     const runId=work.snapshot_json?.employee_run_id;
     const run=work.employee_runs?.find(item=>Number(item.id)===Number(runId));
     return JSON.stringify([runId,run?.live_activity,work.snapshot_json?.pipeline_submission?.receipt,
      work.artifacts?.map(item=>[item.id,item.meta_json?.revision])]);
    };
    if(activityKey(latest)===activityKey(previous))return;
   }
   if(applyWorkReply(owner,reply)){render();if(businessChanged)void refresh({silent:true});}
  }catch{/* The task is already open. Keep its last confirmed details and try again on the next poll. */}
  finally{owner.refreshingWork=false;}
 }
 async function openWork(id,options={}){const s=current();if(!s)return;select('work',{workflowId:id,loading:true,...(options.returnToRecords?{returnToRecords:options.returnToRecords}:{}),...(options.showDeliveries?{workSections:{deliveries:true}}:{})});const owner=S.sel;
  try{const reply=await request('work',{reference:s.reference,workflow_id:Number(id)});if(matches(s)&&applyWorkReply(owner,reply))render();}
  catch(error){if(matches(s)&&S.sel===owner){owner.loading=false;owner.error=error.message;render();}}
 }
 const operationErrorFallback={
   "controlNotSent": "无法在这台电脑上保存操作。请重试。",
   "controlRetryHint": "尚未找到操作结果。你可以重试原操作。",
   "flowReadFailed": "无法读取上次的任务操作。",
   "flowMoved": "任务已更新，已显示最新进度。",
   "flowMovedRefresh": "任务已更新。请重新打开任务查看最新进度。",
   "flowReceiptUnavailable": "暂时无法确认这次操作的结果。",
   "flowReceiptMissing": "暂未查到这次操作的结果。重试会沿用原操作。",
   "flowInputInvalid": "请检查输入后重试。",
   "flowDraftFailed": "无法在本机保存输入。请保留此页并重试。",
   "controlCheckHint": "尚未确认操作结果。请先核对结果。",
   "controlReadFailed": "无法核对操作结果。请重试核对。",
   "controlFailed": "无法完成操作。请查看当前状态后重试。",
   "taskNotSent": "无法准备任务。草稿仍在，请检查输入后重试。",
   "taskRetryHint": "尚未确认任务是否已创建。重试不会重复创建任务。",
   "taskCheckHint": "尚未确认任务是否已创建。请先核对结果。",
   "taskFailed": "无法创建任务。请查看详情后重试。",
   "taskNameRequired": "请输入任务名称。",
   "taskObjectiveRequired": "请描述任务要完成什么。"
 };
 function operationError(error,{inline=false}={}){
  if(!error)return '';
  if(inline&&error.detail){
   const translated=error.detailKey?RunTeamsLocale.t(error.detailKey,error.detailVars||{},error.detail):error.detail;
   return `<p role="alert">${esc(translated)}</p>`;
  }
  const details=error.detail?`<details><summary data-app-i18n="pipelineBoard.errorDetails">错误详情</summary><p ${error.detailKey?`data-app-i18n="${esc(error.detailKey)}" data-app-i18n-vars="${esc(JSON.stringify(error.detailVars||{}))}"`:''}>${esc(error.detail)}</p></details>`:'';
  return `<p role="alert" data-app-i18n="pipelineBoard.${error.key}">${operationErrorFallback[error.key]}</p>${details}`;
 }
 function drawer(){
  const s=current(),selection=S.sel;if(!s||selection?.type!=='source-pipeline')return '';
  if(selection.id==='automation')return RunTeamsEmployeeAutomation.drawer();
  if(['settings','members','editor','position'].includes(selection.id)&&window.RunTeamsSourcePipelinePanels)return RunTeamsSourcePipelinePanels.drawer();
  let title='',titleKey='',body='';
  if(selection.id==='compose'){
   title=s.pending?'核对任务状态':'新建任务';titleKey=s.pending?'pipelineBoard.checkTask':'pipelineBoard.newTask';const c=s.composer;
   if(s.pending)body=`<p><b>${esc(s.pending.title)}</b></p><p>${esc(s.pending.payload?.objective||'')}</p><p data-app-i18n="pipelineBoard.pendingHint">输入已保存。确认任务已创建后，它会显示在看板上。</p>${operationError(s.submitError)}`;
   else if(c?.loading)body=RunTeamsSkeletons.region('parameters',undefined,'pipelineBoard.inputLoading');
   else if(c?.error)body=RunTeamsLoadFailure.markup({variant:'local',title:"无法读取任务输入",titleKey:'pipelineBoard.inputFailed',labelKey:'employeeHistory.retry',busyLabelKey:'pipelineBoard.inputLoading',error:c.error,retry:`RunTeamsSourcePipelines.compose(${JSON.stringify(c.position)},true)`});
   else if(c?.contract)body=`<form id="source_pipeline_task" novalidate onsubmit="event.preventDefault();RunTeamsSourcePipelines.submit()"><label class="lbl" for="source_pipeline_title" data-app-i18n="pipelineBoard.taskName">任务名称</label><input class="input" id="source_pipeline_title" name="title" required maxlength="160" value="${esc(c.title)}" oninput="S.sourcePipelineWorkspace.composer.title=this.value"><label class="lbl" for="source_pipeline_objective" data-app-i18n="pipelineBoard.objective">工作目标</label><textarea class="input" id="source_pipeline_objective" name="objective" required oninput="S.sourcePipelineWorkspace.composer.objective=this.value">${esc(c.objective)}</textarea><div oninput="S.sourcePipelineWorkspace.composer.parameters=readCoreTaskParameters(this)">${coreTaskParameterFields(coreWorkflowFrozenParameters(c.contract),c.parameters,'source_pipeline')}</div></form>`;
   if(s.submitError&&!s.pending)body+=operationError(s.submitError);
   if(s.pending||c?.contract)body+=detailDrawerActions(`<button class="btn pri" type="button" data-task-submit aria-busy="${s.sending===true}" ${s.sending||!s.pending&&!c?.contract?'disabled':''} onclick="${s.pending&&s.canRetryAdmission?'RunTeamsSourcePipelines.retryAdmission()':'RunTeamsSourcePipelines.submit()'}" data-app-i18n="pipelineBoard.${s.sending?(s.admissionUnknown?'checking':'submitting'):s.pending?(s.canRetryAdmission?'retryAdmission':'checkTask'):'startWork'}">${s.sending?(s.admissionUnknown?'正在核对…':'正在提交…'):s.pending?s.canRetryAdmission?'重试提交':'核对任务状态':'开始工作'}</button>`);
  }else if(selection.id==='work'){
   return RunTeamsSourcePipelinePanels.workDrawer(selection);
  }
  return detailDrawerShell({className:'source-pipeline-drawer'+(selection.id==='compose'?' source-pipeline-compose-drawer':''),
   header:detailDrawerHeader(title?detailDrawerHeading(title,"","","",{titleKey}):'',"","","","",titleKey?'pipelineBoard.closeTaskPane':undefined),body,
   attrs:titleKey?`aria-label="${title}" data-app-i18n-aria-label="${titleKey}"`:''});
 }
 let creation=null;
 const creationKey=()=> 'runteams.pipeline-create:'+durableScope();
 const creationErrors={
  localSaveFailed:'无法在本机保存创建请求。流水线尚未创建。',
  unconfirmed:'暂时无法确认流水线是否已创建。请核对创建结果。',
  rejected:'无法创建流水线。请核对名称和首个岗位后重试。'
 };
 const creationText=(key,vars,fallback)=>window.RunTeamsLocale?.t('pipelineCreate.'+key,vars,fallback)??fallback;
 const creationVisible=c=>creation===c&&c.scope===scope()&&c.modal?.isConnected&&document.getElementById('modalHost')?.firstChild===c.modal;
 function creationChoiceLabel(row,index){
  const local=row.origin==='创作'||row.dependency?.kind==='source';
  const label=[row.employee_name+' / '+row.skill_name,row.project_name].filter(Boolean).join(' · ');
  const key=local?'localChoice':row.origin==='租用'?'rentedChoice':'downloadedChoice';
  const version=local?String(row.version||'').replace(/^修订\s+/,''):String(row.version||'');
  const vars={label,version};
  return `<option value="${index}" data-app-i18n="pipelineCreate.${key}" data-app-i18n-vars="${esc(JSON.stringify(vars))}">${esc(creationText(key,vars,label))}</option>`;
 }
 async function newPipeline(){
  if(creation&&creationVisible(creation))return;
  const c={scope:scope(),ticket:navigationTicket(),anchor:document.activeElement,choices:[],loading:true,busy:false,error:''};
  creation=c;
  const host=openDialog({
   title:'新建流水线',titleKey:'pipelineCreate.title',closeLabelKey:'employeeSettings.closeDialog',
   attrs:'role="dialog" aria-modal="true" aria-label="新建流水线" data-app-i18n-aria-label="pipelineCreate.title"',
   closeAction:'RunTeamsSourcePipelines.closeCreation()',
   body:'<div data-pipeline-create-fields></div><p role="alert" data-pipeline-create-error hidden></p>',
   footer:'<button class="btn" type="button" onclick="RunTeamsSourcePipelines.closeCreation()" data-app-i18n="pipelineCreate.close">关闭</button><div class="grow"></div><button class="btn pri" type="button" data-pipeline-create-submit onclick="RunTeamsSourcePipelines.create()" disabled></button>'
  });
  c.modal=host.firstChild;
  c.modal.querySelector('.modal-x')?.focus({preventScroll:true});
  await readCreationChoices();
 }
 function closeCreation(){
  const c=creation;if(!c||!creationVisible(c))return;
  closeModal();
  if(c.ticket()&&c.anchor?.isConnected)c.anchor.focus({preventScroll:true});
 }
 async function readCreationChoices(){
  const c=creation;if(!c||!creationVisible(c)||c.reading)return;
  const retry=c.choicesFailed;
  c.loading=true;c.reading=true;c.choicesFailed=false;creationDialog(true);
  const active=()=>creationVisible(c)&&c.ticket();
  try{
   if(!RunTeamsWorkState.ready)await RunTeamsWorkState.connect();
   if(!active())return;
   c.pending=JSON.parse(RunTeamsWorkState.getItem(creationKey())||'null');
   if(c.pending){c.loading=false;creationDialog(true);}
   const reply=await request('creation-choices');
   if(!active())return;
   if(!Array.isArray(reply.items))throw Error('pipeline creation choices missing');
   c.choices=reply.items;c.choiceErrors=Array.isArray(reply.errors)?reply.errors:[];
  }catch(error){if(active())c.choicesFailed=true;}
  finally{
   c.loading=false;c.reading=false;
   if(active()){
    creationDialog(!c.pending);
    if(retry&&!c.choicesFailed&&document.activeElement===document.body){
     c.modal.querySelector('#source_pipeline_create_name, [data-pipeline-create-submit]:not(:disabled)')?.focus({preventScroll:true});
    }
   }else if(creationVisible(c))closeCreation();
  }
 }
 function creationDialog(rebuild=false){
  const c=creation;if(!c||!creationVisible(c))return;
  const fields=c.modal.querySelector('[data-pipeline-create-fields]');
  if(rebuild){
   const form=c.choices.length?`<form id="source_pipeline_create" onsubmit="event.preventDefault();RunTeamsSourcePipelines.create()">
    <label class="lbl" for="source_pipeline_create_name" data-app-i18n="pipelineCreate.name">流水线名称</label>
    <input class="input" style="width:100%" id="source_pipeline_create_name" name="name" required maxlength="80" value="${esc(c.name||'')}" oninput="RunTeamsSourcePipelines.creationName(this.value)">
    <label class="lbl" for="source_pipeline_first_role" data-app-i18n="pipelineCreate.firstRole">第一个岗位</label>
    <select class="input" style="width:100%" id="source_pipeline_first_role" name="choice" required><option value="" data-app-i18n="pipelineCreate.choose">选择员工和技能</option>${c.choices.map(creationChoiceLabel).join('')}</select>
   </form><p data-app-i18n="pipelineCreate.next">创建后，可以直接从岗位添加任务。</p>`:
   '<p data-app-i18n="pipelineCreate.empty">添加一名带有工作技能的员工后，即可创建流水线。</p>';
   const failed=RunTeamsLoadFailure.markup({variant:'local',title:'无法载入员工和技能',titleKey:'pipelineCreate.choicesFailedTitle',
    labelKey:'employeeHistory.retry',busyLabelKey:'pipelineCreate.choicesLoading',retry:'RunTeamsSourcePipelines.readCreationChoices()'});
   const partial=c.choiceErrors?.length?'<p role="status" data-app-i18n="pipelineCreate.partialChoices">部分员工或技能暂时无法载入。</p>':'';
   fields.innerHTML=c.pending?`<p><b>${esc(c.pending.name)}</b></p><p data-app-i18n="pipelineCreate.unconfirmed">无法确认流水线是否已创建。请核对创建结果。</p>`:
    c.loading?RunTeamsSkeletons.region('parameters',undefined,'pipelineCreate.choicesLoading'):
    c.choicesFailed||!c.choices.length&&partial?failed:form+partial;
   const select=fields.querySelector('select');if(select&&c.choice!=null)select.value=c.choice;
  }
  const form=fields.querySelector('form');
  form?.querySelectorAll('input,select').forEach(input=>input.disabled=c.busy||!!c.pending);
  const submit=c.modal.querySelector('[data-pipeline-create-submit]');
  submit.disabled=!c.pending&&(!c.choices.length||c.choicesFailed||c.loading);
  submit.setAttribute('aria-disabled',String(c.busy||submit.disabled));
  submit.setAttribute('aria-busy',String(c.busy));
  const key=c.busy?(c.checking?'checking':'creating'):c.pending?'check':'create';
  submit.setAttribute('data-app-i18n','pipelineCreate.'+key);
  submit.textContent=creationText(key,{},({checking:'正在核对…',creating:'正在创建…',check:'核对创建结果',create:'创建流水线'})[key]);
  const error=c.modal.querySelector('[data-pipeline-create-error]');
  const errorKey=c.pending&&rebuild&&c.error==='unconfirmed'?'':c.error;
  error.hidden=!errorKey;
  if(errorKey)error.setAttribute('data-app-i18n','pipelineCreate.'+errorKey);else error.removeAttribute('data-app-i18n');
  error.textContent=errorKey?creationErrors[errorKey]:'';
  window.RunTeamsLocale?.apply(c.modal);
 }
 async function create(){
  const c=creation;if(!c||c.busy||!creationVisible(c)||!c.ticket())return;const revealTicket=navigationTicket();
  c.checking=!!c.pending;const focus=document.activeElement;
  const form=document.getElementById('source_pipeline_create');
  if(!c.pending){
   if(!form?.reportValidity())return;
   try{
   const values=new FormData(form),choice=c.choices[Number(values.get('choice'))];c.choice=String(values.get('choice'));
   c.name=String(values.get('name')).trim();
   const endName=window.RunTeamsLocale?.t('pipelineEditor.defaultEnd',{},'已完成')??'已完成';
   c.pending={operation_id:crypto.randomUUID(),employee_reference:choice.reference,source_revision:choice.revision,
    skill_key:choice.skill_key,name:c.name,end_name:endName,
    ...(choice.dependency?.kind==='download'?{dependency:structuredClone(choice.dependency)}:{})};
   RunTeamsWorkState.setItem(creationKey(),JSON.stringify(c.pending));
   }catch(error){c.pending=null;c.error='localSaveFailed';creationDialog();return;}
  }
  c.busy=true;c.error='';creationDialog();
  try{if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const reply=await request('create',c.pending);if(c.scope!==scope()||creation!==c)return;const visible=revealTicket()&&c.modal?.isConnected&&document.getElementById('modalHost')?.firstChild===c.modal;RunTeamsWorkState.removeItem(creationKey());if(visible)closeModal();else c.modal?.remove();creation=null;const emptyModal=document.getElementById('modalHost')?.firstChild;await refreshCatalog();if(visible&&revealTicket()&&c.scope===scope()&&document.getElementById('modalHost')?.firstChild===emptyModal)await openFromLink(route(reply.reference));}
  catch(error){if(c.scope===scope()&&creation===c){if(error.confirmedReply&&error.code!=='operation_unknown'){RunTeamsWorkState.removeItem(creationKey());c.pending=null;}c.error=c.pending?'unconfirmed':'rejected';}}
  finally{c.busy=false;
   if(revealTicket()&&creationVisible(c)){
    creationDialog(true);
    if(document.activeElement===document.body){
     const target=(focus?.id&&document.getElementById(focus.id))||c.modal.querySelector('[data-pipeline-create-submit]:not(:disabled)')||c.modal.querySelector('.modal-x');
     target?.focus({preventScroll:true});
    }
   }}
 }
 function reset(){stopActivity();catalogSequence++;sequence++;viewSequence++;rows=[];catalogScope='';catalogError='';catalogErrorScope='';opening=false;reading=false;creation=null;}
 window.addEventListener('runteams:business-scope-will-change',reset);
 setInterval(()=>{
  const s=current();
  if(!document.hidden&&s?.data?.runtime?.status==='pausing'&&!s.sending&&!opening)void refresh();
 },1000);
 async function pollWorkspace({detailOnly=false}={}){
  syncActivity();
  const s=current();
  if(document.hidden||!s?.data||s.sending||opening||s.pollingWorkspace)return;
  if(detailOnly&&!(S.sel?.workflow?.state==='running'||S.sel?.attemptContext&&
   S.sel.data?.results?.some(result=>result.key===S.sel.resultKey&&result.state==='running')))return;
  s.pollingWorkspace=true;
  try{
   if(!detailOnly&&s.view==='board'&&s.data.runtime.status!=='pausing')await refresh({silent:true});
   if(!matches(s))return;
   if(S.sel?.type==='source-pipeline'&&S.sel.id==='work')await refreshOpenWork(s,S.sel);
   else await RunTeamsWorkRecords.refreshOpenAttempt();
  }finally{s.pollingWorkspace=false;}
 }
 setInterval(()=>void pollWorkspace(),8000);
 setInterval(()=>void pollWorkspace({detailOnly:true}),2000);
 window.addEventListener('focus',()=>void pollWorkspace());
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stopActivity();else void pollWorkspace();});
 window.RunTeamsSourcePipelines={workContext,ensureWorkContext,request,select,operationError,current,sameScope,refreshCatalog,catalogState,items:()=>catalogScope===scope()?rows.slice():[],sidebar,sidebarMenu,openRoute,openFromLink,refresh,retryRecovery,route,key,referenceKey,boot,header,editName,board,workspace,conversation,boardView,retryBoard,settings,control,compose,submit,openWork,refreshOpenWork,applyWorkReply,syncActivity,retainActivity,drawer,reset,newPipeline,closeCreation,readCreationChoices,create,retryControl,retryAdmission,creationName:value=>{if(creation)creation.name=value;}};
})();
