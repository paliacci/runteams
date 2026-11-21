/* Source workspaces reuse the employee conversation and the existing board.
 * References, applied graphs and work states are always returned by the host. */
(()=>{
 'use strict';
 let rows=[],catalogScope='',catalogError='',catalogErrorScope='',catalogSequence=0,sequence=0,reading=false;
 const scope=()=>JSON.stringify([_workspaceBusinessGeneration,workspaceAccountCacheToken(),workspaceDeviceStorageScope()]);
 const durableScope=()=>workspaceDeviceStorageScope();
 const referenceKey=ref=>{
  if(!ref||!['runteams.local-pipeline-reference/1','runteams.rented-pipeline-reference/1'].includes(ref.schema))return '';
  const fields=['schema','source_id','pipeline_source',...(ref.storage_kind==='local'?['storage_kind','library_id']:['account_id','deployment_id','storage_namespace'])];
  return fields.every(field=>typeof ref[field]==='string'&&ref[field])?JSON.stringify(fields.map(field=>ref[field])):'';
 };
 function catalogEntry(ref){
  const identity=referenceKey(ref);
  return identity&&catalogScope===scope()?rows.find(item=>referenceKey(item.reference)===identity):null;
 }
 const pageRoute=ref=>{const row=catalogEntry(ref);return row?'/pipelines/'+row.page_id:null;};
 const key=ref=>{const row=catalogEntry(ref);return row?'pipeline:'+row.page_id:null;};
 async function openReference(ref){
  const ticket=navigationTicket();
  if(!catalogEntry(ref))await readCatalog();
  if(!ticket())return;
  const path=pageRoute(ref);
  if(!path)throw Error('这个智能体团队不在当前工作区中。');
  await openFromLink(path);
 }
 const sameScope=s=>s?.scope===scope();
 const current=()=>S.surface==='source-pipeline'&&sameScope(S.sourcePipelineWorkspace)?S.sourcePipelineWorkspace:null;
 const matches=(s)=>!!s&&current()===s;
 function taskWorkspace(){
  const board=current();if(board)return board;
  const seen=new Set();let selection=S.sel;
  while(selection&&!seen.has(selection)){
   seen.add(selection);
   const workspace=selection.employeeTaskWorkspace;
   if(workspace&&sameScope(workspace)&&String(workspace.employeePanelId)===String(S.conversationPanel?.id))return workspace;
   selection=selection.returnTo;
  }
  return null;
 }
 const ownsTask=s=>!!s&&taskWorkspace()===s;
 function navigationTicket(){const owner=scope(),key=workspaceCurrentKey(),route=_routeSequence,switching=_workspaceSwitchSequence;return ()=>owner===scope()&&key===workspaceCurrentKey()&&route===_routeSequence&&switching===_workspaceSwitchSequence;}
 function leaveForBoard(){captureConversationPanelDraft();if(S.conversationPanel?.loading)++_conversationPanelLoadSequence;S.railMode='navigation';S._pendingRailMode='';saveRailLayout();}
 async function request(action,data={},options={}){
  const token=scope(),configuration=action==='configuration'||action==='employee-configuration'||action==='work-configuration';
  const control=action==='control'||action==='control-operation',edit=action==='edit'||action==='edit-operation',flow=['flow','flow-operation','card','card-operation'].includes(action);let reply;
  try{reply=await api('/api/device/work/source-pipelines/'+action,'POST',data,{readPriority:options.readPriority,retryOnDisconnect:options.retryOnDisconnect,readCurrent:action==='records'||action==='catalog'||action==='trash-catalog'||action==='workspace'||action==='settings'||action==='work',errorStatus:configuration||control||edit||flow});}
  catch(error){
   if(token!==scope())throw Error('工作区已改变，请重新打开智能体团队。');
   if((configuration||control||edit||flow)&&error.status>=400&&error.status<500)error.confirmedReply=true;
   if(error.code||(configuration||control||edit||flow)&&error.status)throw error;
   throw Object.assign(Error((['dispatch','control','create','edit','flow'].includes(action)||action==='employee-configuration'&&data.action==='save')?'尚未收到服务回执，请核对原操作。':'本机智能体团队暂时无法读取，请重试。'),{cause:error});
  }
  if(token!==scope())throw Error('工作区已改变，请重新打开智能体团队。');
  if(reply?.error)throw Object.assign(Error(reply.error),{code:reply.code,fields:reply.fields,reason:reply.reason,status:reply.status??(reply.code==='employee_configuration_invalid'?422:409),
   confirmedReply:!(control||edit||flow)||reply.status>=400&&reply.status<500});
  if(action==='catalog'&&(!Array.isArray(reply.items)||!Array.isArray(reply.errors)||reply.items.some(row=>!/^[0-9][a-z][a-z0-9]{6}$/.test(row.page_id)||!referenceKey(row.reference)||typeof row.name!=='string'||S.localLibrary&&(row.reference.schema!=='runteams.local-pipeline-reference/1'||row.reference.storage_kind!=='local'||row.reference.library_id!==S.localLibrary.library_id))))throw Error('智能体团队目录回执无效。');
  return reply;
 }
 async function readCatalog({readPriority}={}){
  const token=scope();
  if(readCatalog.pending?.token===token)return readCatalog.pending;
  const own=++catalogSequence,active=()=>own===catalogSequence&&token===scope();
  const pending=(async()=>{
   try{
    const reply=await request('catalog',{},{readPriority,retryOnDisconnect:catalogScope===token&&readPriority==='background'});
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
 async function refreshCatalog(options={}){
  if((!S.localLibrary&&!RunTeamsHost.session.ready(S))||RunTeamsHost.session.workspace(S)){++catalogSequence;rows=[];catalogScope='';catalogError='';catalogErrorScope='';return;}
  try{await readCatalog(options);}catch{/* The current catalog error is shown in the sidebar. */}
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
 function trashFromSidebar(row){
  const token=scope(),windowKey=key(row.reference);
  confirmModal('将智能体团队移到垃圾箱？','可以从垃圾箱恢复整个智能体团队。原有任务、对话和文档会随智能体团队保留。',async()=>{
   if(token!==scope())return;
   try{
    const result=await request('trash',{reference:row.reference});
    if(result.trashed!==true)throw Error('未能确认垃圾箱状态。');
    await refreshCatalog();
    if(token!==scope())return;
    if(S.activeWorkspaceKey===windowKey&&S.workspaceWindows?.length===1)await openTrash();
    else closeWorkspaceWindow(windowKey);
    if(S.surface==='trash')await refreshTrash({source:'device'});
    toast('已移到垃圾箱','ok','pipelineBoard.trashed');
   }catch(error){if(token===scope())toast(error.message,'err');}
  },true,{titleKey:'pipelineBoard.trashTitle',messageKey:'pipelineBoard.trashDetails',action:'移到垃圾箱',actionKey:'pipelineBoard.trash',focusCancel:true});
 }
 const pendingDiscussions=new Map();
 async function newDiscussion(row){
  const token=scope(),key=token+':'+referenceKey(row.reference);
  let pending=pendingDiscussions.get(key);
  if(pending?.busy)return;
  if(!pending){pending={id:crypto.randomUUID()};pendingDiscussions.set(key,pending);}
  pending.busy=true;
  try{
   const config=defaultChatConfig(null);
   const {session}=await request('conversation',{reference:row.reference,discussion_id:pending.id,
    runtime:{channel_id:config.channel_id,model:config.model,reasoning_effort:config.reasoning_effort}});
   if(scope()!==token)return;
   const {messages,...summary}=session;
   S.chats=[summary,...S.chats.filter(chat=>String(chat.id)!==String(session.id))];
   deviceChatRemember(session);
   await openRailConversationSession(session.id,{device:true});
   pendingDiscussions.delete(key);
  }catch{
   if(scope()===token)toast('无法打开新对话。请重试。','err','employeeChat.newConversationFailed');
  }finally{pending.busy=false;}
 }
 function sidebarMenu(event){
  if(event.type==='keydown'&&event.key!=='ContextMenu'&&!(event.key==='F10'&&event.shiftKey))return;
  event.preventDefault();event.stopPropagation();
  const element=event.currentTarget.closest('[data-pipeline-row]'),id=element.dataset.pipelineRow;
  const token=scope(),row=catalogScope===token&&rows.find(item=>referenceKey(item.reference)===id);
  if(!row)return;
  const own=fn=>()=>{if(token===scope()&&catalogScope===token&&rows.some(item=>referenceKey(item.reference)===id))return fn();};
  const pinned=sidebarPins().includes(id);
  const items=[{label:'新对话',labelKey:'shell.newChat',icon:'message-circle-more',fn:own(()=>newDiscussion(row))},
   {label:pinned?'取消置顶':'置顶',labelKey:pinned?'conversationDetail.unpin':'conversationDetail.pin',icon:pinned?'pin-off':'pin',fn:own(()=>toggleSidebarPin(id))}];
  if(row.reference.schema==='runteams.local-pipeline-reference/1'&&row.allowed_modes?.includes('creator')){
   items.push({label:'移到垃圾箱',labelKey:'pipelineBoard.trash',icon:'trash',fn:own(()=>trashFromSidebar(row))});
  }
  const extra=RunTeamsHost.assets.uninstallAction?.('pipeline',row);
  if(extra)items.push({divider:true},{...extra,fn:own(extra.fn)});
  const options=event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY}}:{align:'right'};
  const button=element.querySelector('.rail-source-pipeline-more');
  const fromLink=event.type==='keydown'&&event.target!==button;
  const currentRow=()=>token===scope()?document.querySelector(`[data-pipeline-row="${CSS.escape(id)}"]`):null;
  const currentAnchor=()=>currentRow()?.querySelector('.rail-source-pipeline-more');
  const keyboardReturn=()=>token===scope()?((fromLink?currentRow()?.querySelector('a'):currentAnchor())||document.querySelector('.rail-pipelines')):null;
  openMenu(button,items,{variant:'railItem',keyboardReturn,currentAnchor,dismissOnScroll:'#rgRail .railmid',...options});
 }
 function catalogErrorMarkup(token,count){
  const error=catalogErrorScope===token?catalogError:'';
  if(!error)return '';
  const key=!count?'catalogUnavailable':error==='incomplete'?'catalogIncomplete':'catalogRefreshFailed';
  const copy=!count?'无法读取智能体团队。':error==='incomplete'?'部分智能体团队无法读取。':'无法更新智能体团队列表。';
  const retry=RunTeamsLoadFailure.button({key:'sidebar-pipeline-catalog',variant:'local',compact:true,labelKey:'globalSearch.retry',busyLabelKey:'globalSearch.pipelinesLoading',retry:'RunTeamsSourcePipelines.refreshCatalog()',focusFallback:'.rail-pipelines'});
  return `<div class="rail-section-hint" data-pipeline-catalog-status><span role="alert" data-app-i18n="pipelineBoard.${key}">${copy}</span> ${retry}</div>`;
 }
 function sidebarAvatar(value){
  const src=typeof value==='string'&&/^(?:https:\/\/|\/worker-avatars\/|data:image\/(?:png|jpeg|webp|svg\+xml);base64,)/i.test(value)?value:'';
  const image=src?`<img src="${esc(src)}" alt="" decoding="async" onerror="this.remove()">`:'';
  return `<span class="rail-pipeline-avatar" aria-hidden="true">${image}${ICON('flow')}</span>`;
 }
 function sidebar({active}){
  const token=scope();
  const activeKey=active?referenceKey(current()?.reference):'';
  let selected=false;
  const byId=new Map((catalogScope===token?rows:[]).filter(row=>!RunTeamsHost.assets?.placeholderPipeline?.(row)).map(row=>[referenceKey(row.reference),row]));
  const ownerKey=referenceKey(byId.get(activeKey)?.creator_reference);
  const visibleActiveKey=byId.has(ownerKey)?ownerKey:activeKey;
  for(const [id,row] of byId){
   const creator=referenceKey(row.creator_reference);
   if(creator&&creator!==id&&byId.has(creator))byId.delete(id);
  }
  const pins=new Set(sidebarPins());
  const ordered=[...pins].filter(id=>byId.has(id)).concat([...byId.keys()].filter(id=>!pins.has(id)));
  const menuAnchor=document.getElementById('popmenu')?._currentAnchor?.();
  const html=ordered.map(id=>{
   const row=byId.get(id),isCurrent=visibleActiveKey===id,menuOpen=menuAnchor?.closest('[data-pipeline-row]')?.dataset.pipelineRow===id;
   const target=isCurrent&&current()?.reference||row.reference;
   selected||=isCurrent;
   return `<div class="rl rail-source-pipeline-row" data-pipeline-row="${esc(id)}" oncontextmenu="RunTeamsSourcePipelines.sidebarMenu(event)" onkeydown="RunTeamsSourcePipelines.sidebarMenu(event)" onmouseenter="railMarqueeStart(this)" onmouseleave="railMarqueeStop(this)"><a class="pl${isCurrent?' on':''}${pins.has(id)?' pinned':''}" aria-current="${isCurrent?'page':'false'}" href="${esc(pageRoute(target))}" onclick="event.preventDefault();RunTeamsSourcePipelines.openFromLink(this.href)"><span class="rail-pipeline-main">${sidebarAvatar(row.avatar_src)}<span class="nm rail-marquee"><span class="rail-marquee-text">${esc(row.name)}</span></span></span></a><button type="button" class="rail-source-pipeline-more rail-item-more${menuOpen?' menu-trigger-active':''}" data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="${menuOpen}" aria-label="${esc(row.name)}的更多操作" data-app-i18n-aria-label="pipelineBoard.rowActionsFor" data-app-i18n-vars="${esc(JSON.stringify({name:row.name}))}" onclick="RunTeamsSourcePipelines.sidebarMenu(event)">${ICON('more')}</button></div>`;
  }).join('');
  return {selected,markup:html+(RunTeamsHost.assets?.marketRows?.('pipeline')||'')+catalogErrorMarkup(token,ordered.length)};
 }
 async function openFromLink(url){await setAppUrl(url);await applyAppRoute();}
 async function openVersion(s,reference,creationMode){
  if(!matches(s)||!referenceKey(reference)||referenceKey(s.reference)===referenceKey(reference))return false;
  const from=key(s.reference),active=navigationTicket();
  const cached=catalogScope===scope()?rows:[];
  const known=cached.some(row=>referenceKey(row.reference)===referenceKey(reference));
  const [catalog,workspace]=await Promise.all([known?cached:readCatalog(),request('workspace',{reference})]);
  if(!active()||!matches(s)||!catalog.some(row=>referenceKey(row.reference)===referenceKey(reference))||
     referenceKey(workspace.reference)!==referenceKey(reference))return false;
  if(!await setAppUrl(pageRoute(reference),true)||!matches(s))return false;
  await applyAppRoute({pipelineVersion:{catalog,workspace,creationMode}});
  if(key(current()?.reference||{})!==key(reference)||!current()?.data)return false;
  closeWorkspaceWindow(from);
  return true;
 }
 async function openRoute(value,version){
  const own=++sequence,token=scope(),panelQuery=new URLSearchParams(typeof location==='object'?location.search:'');
  workspaceCaptureCurrent({beforeRoute:true});leaveForBoard();cancelPageTransition();resetDetailWorkspace();
  S.surface='source-pipeline';S.corePipeline=null;S.chatId=null;S.chatMode='';
  const s={scope:token,storageScope:durableScope(),reference:value.session?.context?.source_pipeline_workspace||null,data:null,error:'',loading:true,view:'board',pending:null,composer:null};S.sourcePipelineWorkspace=s;render();
  try{
   const [items]=await Promise.all([version?.catalog||readCatalog(),RunTeamsWorkState.ready?null:RunTeamsWorkState.connect()]);
   if(sequence!==own||!matches(s))return;
   const entry=items.find(row=>row.page_id===value.pageId);
   if(!entry){s.loading=false;s.error='这个智能体团队不在当前工作区中。';s.errorKey='pipelineBoard.missingPipeline';render();return;}
   s.reference=entry.reference;s.name=entry.name;s.requestedChat=value.session;
   const path=pageRoute(s.reference)+(s.requestedChat?'/chats/'+s.requestedChat.id:'');
   await setAppUrl(path+(typeof location==='object'?location.search+location.hash:''),true);if(sequence!==own||!matches(s))return;
   s.data=referenceKey(version?.workspace?.reference)===referenceKey(s.reference)?version.workspace:await request('workspace',{reference:s.reference});if(sequence!==own||!matches(s))return;
   restoreMessageVisibility(s);
   restorePendingCommands(s);s.loading=false;
   if(s.data===version?.workspace)s.creationMode=version.creationMode;
   RunTeamsHost.pipeline?.readCreationMode(s);
   render();
   void prepareDock(s);
   if(matches(s)&&panelQuery.get('results')==='1'&&window.RunTeamsSourcePipelinePanels){
    const workflowId=Number(panelQuery.get('delivery')?.match(/^workflow-([0-9]+)$/)?.[1]);
    if(Number.isSafeInteger(workflowId)&&workflowId>0)await openWork(workflowId,{showDeliveries:true});
    else await RunTeamsSourcePipelinePanels.settings({activityExpanded:true});
   }
  }catch(error){if(matches(s)){s.loading=false;s.error=error.message;}}
  if(matches(s))render();
 }
 function restorePendingCommands(s){
  s.pending=loadPending(s);
  if(s.pending){s.composer={position:s.pending.start_column_key,title:s.pending.title||'',parameters:s.pending.payload?.parameters||{},loading:false};s.pendingComposer=s.composer;}
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
  const s=taskWorkspace();if(!s?.reference||reading&&!afterEdit)return false;
  const requestId=s.refreshSequence=(s.refreshSequence||0)+1;
  const active=()=>ownsTask(s)&&s.refreshSequence===requestId;
  reading=true;let repaint=!silent;
  try{
   const backgroundRevision=s.data?.source_revision;
   const data=await request('workspace',{reference:s.reference,...(backgroundRevision?{background_revision:backgroundRevision}:{})});if(!active())return false;
   if(data.source_revision===backgroundRevision && s.data?.workspace_background_src && !Object.hasOwn(data,'workspace_background_src')){
    data.workspace_background_src=s.data.workspace_background_src;
    data.workspace_background_color=s.data.workspace_background_color;
   }
   if(data.runtime.status!=='pausing'&&s.controlBusy!=='submitting')delete s.controlLabelKey;
   repaint||=JSON.stringify(s.data)!==JSON.stringify(data)||!!s.error&&!s.errorKey;
   s.data=data;if(!s.errorKey)s.error='';return true;
  }
  catch(error){if(active()&&!silent&&!s.errorKey)s.error=error.message;}
  finally{if(s.refreshSequence===requestId)reading=false;if(active()&&repaint)render();}
 }

 // The board uses the same immutable workspace chat without navigating or sending.
 const workContext=()=>{const s=current();return s?.data&&!s.loading&&!s.error?s.workPanel||null:null;};
 async function ensureWorkContext(){
  const s=current();if(!s?.data?.programs_available||s.loading||s.error)return null;
  if(s.workPanel)return s.workPanel;
  if(s.dockRequest){await s.dockRequest;return matches(s)?s.workPanel:null;}
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
  const actionLabel=running?'暂停智能体团队':'启动智能体团队';
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
  input.maxLength=80;input.setAttribute('aria-label','智能体团队名称');input.dataset.appI18nAriaLabel='pipelineCreate.name';s.nameEdit=input;
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
     const key=error.pipelineRenameKey||'renameFailed',fallback=error.pipelineRenameKey?error.message:'无法保存智能体团队名称。请稍后重试。';
     toast(fallback,'err','pipelineCreate.'+key);
    }
   }
   finally{s.renaming=false;if(matches(s))render();}
  };
  heading.replaceWith(input);window.RunTeamsLocale?.apply(input);input.focus({preventScroll:true});input.setSelectionRange(input.value.length,input.value.length);
 }
 const canEditIcon=s=>s?.data?.ui?.mode==='creator'&&s.reference.schema==='runteams.local-pipeline-reference/1'&&!s.loading&&!s.errorKey;
 function editIcon(event){
  const s=current();if(!canEditIcon(s))return;
  return openWorkerAvatarPicker(event,{
   current:()=>matches(s)&&canEditIcon(s),
   identity:()=>s.data,
   async save(avatar){
    const operation_id=crypto.randomUUID(),reference=s.reference;
    try{await request('edit',{reference,operation_id,base_revision:s.data.source_revision,avatar});}
    catch(error){
     if(error.confirmedReply){if(matches(s))await refresh({afterEdit:true});throw error;}
     const receipt=await request('edit-operation',{reference,operation_id}).catch(()=>null);
     if(receipt?.state!=='confirmed')throw error;
    }
    if(matches(s))await Promise.all([refresh({afterEdit:true}),refreshCatalog()]);
   },
  });
 }
 function pipelineIcon(s,allowEdit=true){
  const src=s.data?.avatar_src,editable=allowEdit&&canEditIcon(s),tag=editable?'button':'span';
  const attrs=editable?` type="button" onclick="RunTeamsSourcePipelines.editIcon(event)" aria-label="更换智能体团队图标" title="更换智能体团队图标" data-app-i18n-aria-label="pipelineBoard.iconChange" data-app-i18n-title="pipelineBoard.iconChange" aria-haspopup="dialog" aria-expanded="false"`:' aria-hidden="true"';
  return `<${tag} ${allowEdit?'id="pipeline_avatar"':''} class="av pipeline-avatar ${src?'has-image':'is-default'}${editable?' worker-avatar-button':''}"${attrs}>${src?`<img src="${esc(src)}" alt="" onerror="workerAvatarLoadFailed(this)">`:ICON('flow')}</${tag}>`;
 }
 function header(){
  const s=current();if(!s)return '';
  if(s.loading)return RunTeamsSkeletons.workspaceHeader({pipeline:true});
  const name=s.data?.name||s.name||'智能体团队',disabled=s.loading||!!s.errorKey||!s.data;
  const canRename=!disabled&&s.data.ui.mode==='creator'&&s.reference.schema==='runteams.local-pipeline-reference/1';
  const titleAttributes=`${s.data?.name||s.name?'':' data-app-i18n="pipelineBoard.pipeline"'}${canRename?` role="button" tabindex="0" data-pipeline-rename data-app-i18n-aria-label="pipelineBoard.rename" data-app-i18n-vars="${esc(JSON.stringify({name}))}"`+' aria-label="'+esc(name)+'，编辑智能体团队名称" onclick="RunTeamsSourcePipelines.editName(event)" onkeydown="RunTeamsSourcePipelines.editName(event)"':''}`;
  const icon=`<span class="conversation-panel-context-icon bot">${pipelineIcon(s)}</span>`;
  const heading=RunTeamsShell.workspaceHeading(name,titleAttributes,statusMarkup(s),canRename);
  const controls=`<div class="conversation-panel-controls">${runtimeAction(s,disabled)}${RunTeamsAssetOverview.trigger(disabled)}</div>`;
  return RunTeamsShell.pageHeader(icon+heading,controls,true);
 }
 function boardEmpty(s,columns,cards){
  if(s.error||s.pending)return '';
  const visible=new Set(columns.map(column=>column.key));
  if(cards.some(card=>visible.has(card.cursor_key)))return '';
  let key='empty',label='从岗位新建任务，开始这个智能体团队的工作。';
  if(cards.length){
   key='emptyHiddenTasks';label='当前显示的列中没有任务。可在分组中显示其他列。';
  }else if(s.data.runtime.status==='paused'){
   key='emptyPaused';label='这个智能体团队已暂停。启动后即可新建任务。';
  }else if(s.data.runtime.status==='pausing'){
   key='emptyPausing';label='这个智能体团队正在暂停。恢复运行后即可新建任务。';
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
  if(!s.data)return `<main class="home-workspace">${RunTeamsLoadFailure.markup({variant:'local',title:s.errorKey?s.error:"无法读取智能体团队",titleKey:s.errorKey||'pipelineBoard.readFailed',labelKey:'employeeHistory.retry',busyLabelKey:'pipelineBoard.loading',error:s.error,retry:'applyAppRoute()'})}</main>`;
  captureComposer(s);
  const columns=RunTeamsSourcePipelinePanels.columns(s);
  const checkColumn=!s.errorKey&&s.pending&&(columns.find(column=>column.key===s.pending.start_column_key)||columns[0]);
  const cards=boardWorkflows(s).map(row=>({...row,task:{title:row.title,payload_json:{objective:row.objective}},pipeline_reference:s.reference}));
  const html=columns.map(column=>{
   const items=cards.filter(row=>row.cursor_key===column.key);
   const accepts=['employee','approval'].includes(column.kind),canCheck=column===checkColumn,canRun=!s.errorKey&&!s.pending&&s.data.runtime.status==='running';
   const selected=S.sel?.type==='source-pipeline'&&S.sel.id==='position'&&S.sel.positionKey===column.key,deferred=s.composerDrafts?.[column.key];
   const key=esc(column.key),name=esc(column.name);
   const more=`<button type="button" class="column-more" data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="false" title="更多列操作" aria-label="${name}的更多操作" data-app-i18n-title="pipelineBoard.columnActions" data-app-i18n-aria-label="pipelineBoard.columnActionsFor" data-app-i18n-vars="${esc(JSON.stringify({name:column.name}))}" data-position="${key}" onclick="RunTeamsSourcePipelinePanels.columnMenu(event,this.dataset.position)">${ICON('more')}</button>`;
   return `<div class="col ${accepts?'column-job':'column-status core-state-column'} column-color-${esc(column.tone)} core-pipeline-column${selected?' sel':''}"><div class="col-surface" data-position="${key}" onclick="RunTeamsSourcePipelinePanels.columnClick(event,this.dataset.position)"><div class="chd k-${esc(column.kind)}" data-position="${key}" oncontextmenu="RunTeamsSourcePipelinePanels.columnMenu(event,this.dataset.position)"><button type="button" class="column-worker-title" data-position="${key}" onclick="RunTeamsSourcePipelinePanels.position(this.dataset.position)">${RunTeamsSourcePipelinePanels.columnAvatar(column)}<span class="t">${name}</span></button><div class="column-actions">${more}</div></div><div class="lane" data-node-id="${esc(column.key)}">${items.map(row=>coreWorkflowCard(row,column.kind)).join('')}${s.composer?.position===column.key?composeCard(s,column):deferred&&(deferred.autoStartAt||deferred.submitError||deferred.error)?queuedComposeCard(s,column,deferred):`<button type="button" class="addcard core-add-task" data-position="${esc(column.key)}" onclick="RunTeamsSourcePipelines.compose(this.dataset.position)" ${canRun||canCheck?'':'disabled'}>${ICON(canCheck?'check':'plus')}<span data-app-i18n="pipelineBoard.${canCheck?'checkTask':'newTask'}">${canCheck?'核对任务状态':'新建任务'}</span></button>`}</div></div></div>`;
  }).join('');
  const addStage=s.data.ui.mode==='creator'?'<div class="col"><button type="button" class="draft-column-trigger source-pipeline-add-stage" aria-haspopup="dialog" aria-expanded="false" onclick="RunTeamsSourcePipelinePanels.addStageMenu(this)" '+(s.error?'disabled':'')+'>'+ICON('plus')+'<span class="t" data-app-i18n="pipelineBoard.newStage">新环节</span></button></div>':'';
  return `<main class="home-workspace source-pipeline-workspace" aria-label="智能体团队工作区" data-app-i18n-aria-label="pipelineBoard.workspace"><section class="board core-pipeline-board" aria-label="任务看板" data-app-i18n-aria-label="pipelineBoard.taskBoard"><div class="cols">${html}${addStage}</div>${!columns.length?'<button type="button" class="btn ghost source-pipeline-add-role" onclick="RunTeamsSourcePipelinePanels.columnMenu(event)" data-app-i18n="pipelineEditor.editGroup">编辑分组</button>':''}${boardEmpty(s,columns,cards)}</section></main>`;
 }
 function dockPanel(s=current()){
  const panel=S.conversationPanel;
  return s?.workPanel&&panel&&!panel.loading&&!panel.error&&String(s.workPanel.id)===String(panel.id)?panel:null;
 }
 // A restored multiline draft may already be taller than a single line.
 // Reserve its last size while this tab resolves the pipeline's conversation.
 const composerSizeKey='runteams.pipeline-composer-size.v1';
 function rememberComposerSize(){
  const s=current(),panel=dockPanel(s),box=document.querySelector('.pipeline-chat-dock .conversation-composer');
  try{
   if(!panel||!box){sessionStorage.removeItem(composerSizeKey);return;}
   const height=box.getBoundingClientRect().height;
   sessionStorage.setItem(composerSizeKey,JSON.stringify({reference:referenceKey(s.reference),draft:conversationPanelDraftKey(panel),width:innerWidth,height}));
  }catch{}
 }
 function pendingComposerSize(s){
  try{
   const saved=JSON.parse(sessionStorage.getItem(composerSizeKey));
   if(saved?.reference===referenceKey(s.reference)&&saved.width===innerWidth&&S.conversationPanelDrafts?.[saved.draft]&&Number.isFinite(saved.height)&&saved.height>0){
    return `style="--pipeline-composer-min-height:${saved.height}px"`;
   }
  }catch{}
  return '';
 }
 async function prepareDock(s){
  if(dockPanel(s))return dockPanel(s);
  if(s.dockRequest)return s.dockRequest;
  s.dockError=false;
  s.dockRequest=(async()=>{
   try{
    const config=defaultChatConfig(null);
    const session=s.requestedChat||(await request('conversation',{reference:s.reference,runtime:{channel_id:config.channel_id,model:config.model,reasoning_effort:config.reasoning_effort}})).session;
    deviceChatRemember(session);
    if(!matches(s))return null;
    const {messages,...summary}=session;
    s.workPanel=summary;
    S.chats=[summary,...S.chats.filter(chat=>String(chat.id)!==String(session.id))];
    // Load through the shared chat reader so paging and active turns work in the dock.
    const panel=await loadConversationPanelSession(session.id,{embedded:s,session:s.requestedChat,railHosted:true,focus:false,expand:false,render:false,restoreWorkspace:false,refresh:!!cachedConversationPanel(session.id)?.error});
    if(!matches(s))return null;
    if(!panel||panel.error)throw Error();
    delete s.requestedChat;
    return panel;
   }catch{
    if(matches(s))s.dockError=true;
    return null;
   }finally{
    delete s.dockRequest;
    if(matches(s)){
     render();
     const panel=dockPanel(s);
     if(panel)restoreConversationReadingPosition(panel);
    }
   }
  })();
  return s.dockRequest;
 }
 function messageVisibilityKey(s){
  return 'runteams.pipeline-messages-collapsed.v1:'+s.storageScope+':'+referenceKey(s.reference);
 }
 function restoreMessageVisibility(s){
  try{s.messagesCollapsed=localStorage.getItem(messageVisibilityKey(s))==='1';}catch{}
 }
 function animateComposer(s){
  if(!s?.data)return;
  const duration=220,now=performance.now();
  if(s.composerEnteredAt!=null&&now-s.composerEnteredAt>=duration)return;
  const input=document.querySelector('.pipeline-chat-dock .rail-assistant-input');
  if(!input||input.dataset.entered)return;
  s.composerEnteredAt??=now;
  input.dataset.entered='true';
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  // Hydration can replace the loading frame. Continue from the first paint.
  input.animate([{opacity:0,transform:'translateY(6px)'},{opacity:1,transform:'none'}],
   {duration,delay:s.composerEnteredAt-now,easing:'cubic-bezier(.2,.75,.25,1)'});
 }
 function messageToggle(s){
  const expanded=!s.messagesCollapsed;
  return `<button type="button" class="pipeline-messages-toggle" aria-expanded="${expanded}" aria-controls="conversation_scroll" onclick="RunTeamsSourcePipelines.toggleMessages(this)"><span data-app-i18n="pipelineBoard.collapseMessages">收起消息</span><span data-app-i18n="pipelineBoard.expandMessages">展开消息</span>${ICON('chev')}</button>`;
 }
 function selectDockChat(){
  const s=current(),panel=dockPanel(s);
  if(!panel||!s.reference)return;
  const path=pageRoute(s.reference);
  if(path&&parseAppRoute().kind==='source-pipeline')setAppUrl(path+'/chats/'+panel.id+location.search+location.hash,false);
 }
 function toggleMessages(button){
  const s=current(),panel=dockPanel(s);
  if(!panel)return;
  if(!s.messagesCollapsed)captureConversationReadingPosition();
  s.messagesCollapsed=!s.messagesCollapsed;
  try{
   if(s.messagesCollapsed)localStorage.setItem(messageVisibilityKey(s),'1');
   else localStorage.removeItem(messageVisibilityKey(s));
  }catch{}
  button.setAttribute('aria-expanded',String(!s.messagesCollapsed));
  button.closest('.pipeline-chat-dock').querySelector('.conversation-scroll-shell').inert=s.messagesCollapsed;
  if(!s.messagesCollapsed)restoreConversationReadingPosition(panel);
  syncRailChatActivity();
 }
 function workspace(){
  const s=current();
  let dock='';
  if(s?.data){
   const panel=dockPanel(s);
   const input=panel?railConversation({includeHeader:false,pipelineDock:s}):`<section class="rail-assistant conversation-main"><div class="rail-assistant-input">${s.dockError?RunTeamsLoadFailure.markup({variant:'local',title:'无法打开智能体团队对话。请重试。',titleKey:'pipelineBoard.conversationFailed',labelKey:'employeeHistory.retry',retry:'RunTeamsSourcePipelines.conversation()'}):RunTeamsStaticPages.composer(null,{placeholder:'聊聊这个智能体团队的工作…',placeholderKey:'pipelineBoard.chatPrompt',attributes:pendingComposerSize(s)})}</div></section>`;
   dock=`<div class="pipeline-chat-dock" onfocusin="RunTeamsSourcePipelines.selectDockChat()" onclick="RunTeamsSourcePipelines.selectDockChat()" data-session="${esc(String(panel?.id||''))}">${input}</div>`;
  }
  return `${workspaceFeedback(s)}<div class="source-pipeline-layers"><div class="source-pipeline-board-layer">${board()}</div>${dock}</div>`;
 }
 async function conversation(_fromBoard=false,{draft='',signingWorkflowId=null}={}){
  const s=current(),selection=S.sel;
  if(!s?.data)return;
  const panel=await prepareDock(s);
  if(!matches(s)||!panel||draft&&selection!==S.sel)return;
  selectDockChat();
  if(signingWorkflowId){
   try{await request('conversation',{reference:s.reference,runtime:{channel_id:panel.channel_id,model:panel.model,reasoning_effort:panel.reasoning_effort},signing_workflow_id:signingWorkflowId});}
   catch{if(matches(s))toast('无法打开智能体团队对话。请重试。','err','pipelineBoard.conversationFailed');return;}
   if(!matches(s)||selection!==S.sel)return;
  }
  if(draft&&!String(panel.input||'').includes(draft)){
   setConversationDraftValue('panel',[panel.input,draft].filter(Boolean).join('\n\n'));render();
  }
  document.getElementById('conversation_box')?.focus({preventScroll:true});
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
  return readPendingCommand(s,controlKey(s),command=>['start','pause','update'].includes(command.action),'pipelineBoard.controlRecoveryFailed','无法读取上次的智能体团队操作。');
 }
 function loadPending(s){
  return readPendingCommand(s,pendingKey(s),command=>typeof command.start_column_key==='string'&&!!command.start_column_key&&command.payload?.schema==='runteams.task-input/v2','pipelineBoard.taskRecoveryFailed','无法读取上次提交的任务。');
 }
 function composeDraft(form){
  const s=current(),c=s?.composer;if(!c||s.pendingComposer===c||form?.dataset.position!==c.position)return;
  c.title=form.querySelector('[name="title"]')?.value||'';
  c.controls=[...form.querySelectorAll('input,textarea,select')].map(node=>({id:node.id,value:node.value,checked:node.checked}));
 }
 function cardState(s,id){
  const key='runteams.pipeline-card:'+s.storageScope+':'+referenceKey(s.reference)+':'+id;
  s.cardStates??={};if(!s.cardStates[id]){try{s.cardStates[id]={...JSON.parse(RunTeamsWorkState.getItem(key)||'{}'),key,busy:false,unknown:true};}catch{s.cardStates[id]={key,error:'任务操作记录暂时无法读取。'};}}
  return s.cardStates[id];
 }
 function cardFeedback(row){
  const s=current();if(!s||referenceKey(row.pipeline_reference)!==referenceKey(s.reference))return '';
  const f=cardState(s,row.id);
  return (f.error?`<div class="task-card-feedback" role="status">${esc(f.error)}${f.pending?`<button type="button" onclick="event.stopPropagation();RunTeamsSourcePipelines.cardCommand(${Number(row.id)})" data-app-i18n="pipelineBoard.checkControl">核对操作结果</button>`:''}</div>`:'');
 }
 function cardKeydown(event,id){
  if(event.target!==event.currentTarget||event.isComposing)return;
  if(event.key==='ContextMenu'||event.key==='F10'&&event.shiftKey)cardMenu(event,id);
 }
 function openCardMenu(anchor,items,options){
  const onClose=options.onClose;
  const dismiss=event=>{const menu=document.getElementById('popmenu');if(!menu?.contains(event.target))closePop();};
  openMenu(anchor,items,{...options,onClose:()=>{document.removeEventListener('scroll',dismiss,true);window.removeEventListener('resize',dismiss);onClose?.();}});
  if(!document.getElementById('popmenu'))return;
  document.addEventListener('scroll',dismiss,true);window.addEventListener('resize',dismiss);
 }
 function cardMenuItems(s,row,f){
  const id=Number(row.id),caps=row.card_actions||{},pending=!!(f.pending||f.busy),running=s.data.runtime.status==='running';
  const action=(label,labelKey,icon,enabled,reason,fn)=>({label,labelKey,icon,disabled:pending||!enabled,
   disabledReason:RunTeamsLocale.t('pipelineCard.'+(pending?'pendingAction':reason),{},pending?'请先核对当前操作结果。':{
    editUnavailable:'当前任务状态不支持编辑。',startUnavailable:'当前任务不能直接开始，请查看详情。',
    autoStart:'任务已排队，将自动开始。',alreadyRunning:'任务已经在工作。',
   settling:'原任务正在停止收尾，请稍后再开始。',
    pipelinePaused:'请先启动智能体团队。',ended:'任务已经结束。',stopBeforeTrash:'请先停止任务并等待收尾。'}[reason]),
   fn:()=>{if(!pending&&enabled&&matches(s))fn();}});
  const items=[
   {label:'查看详情',labelKey:'pipelineCard.details',icon:'doc',fn:()=>openWork(id)},
   action('编辑任务','workflowDetail.editTask','edit',!!caps.edit,'editUnavailable',()=>editCard(null,id)),
   action('开始任务','pipelineCard.start','play',!!caps.resume&&running,!running?'pipelinePaused':caps.settling?'settling':['ready','waiting_retry'].includes(row.state)?'autoStart':row.state==='running'?'alreadyRunning':['completed','failed','canceled'].includes(row.state)?'ended':'startUnavailable',()=>cardCommand(id,'resume')),
   action('停止任务','workflowDetail.stop','stop',!!caps.stop,'ended',()=>cardCommand(id,'stop')),
   action('移到垃圾箱','workflowDetail.trashTask','trash',!!caps.trash,'stopBeforeTrash',()=>cardCommand(id,'trash'))
  ];
  if(f.pending)items.push({label:'核对操作结果',labelKey:'pipelineBoard.checkControl',icon:'refresh',disabled:f.busy,fn:()=>{if(!f.busy)void cardCommand(id);}});
  return items;
 }
 function cardMenu(event,id){
  event.preventDefault();event.stopPropagation();const s=current(),row=s?.data?.workflows.find(row=>Number(row.id)===Number(id));if(!row)return;
  const anchor=event.currentTarget,card=anchor.closest('.card'),items=cardMenuItems(s,row,cardState(s,id));
  openCardMenu(anchor,items,{variant:'cardContext',align:'right',positionAnchor:card,keyboardReturn:()=>document.querySelector(`.source-pipeline-workspace [data-workflow-id="${Number(id)}"]`),...(event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY}}:{})});
 }
 async function cardCommand(id,action,extra={}){
  const s=current(),row=s?.data?.workflows.find(row=>Number(row.id)===Number(id));if(!row)return null;
  const f=cardState(s,id);if(f.busy)return null;
  if(!f.pending){if(!action||!row.card_actions?.visit)return null;f.pending={operation_id:crypto.randomUUID(),reference:s.reference,workflow_id:Number(id),expected_visit:row.card_actions.visit,action,...extra};f.unknown=false;}
  const command=f.pending;
  try{RunTeamsWorkState.setItem(f.key,JSON.stringify({pending:command,unknown:true}));}catch{f.error='无法保存操作记录，请重试。';render();return null;}
  f.busy=true;f.error='';render();
  try{
   if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();
   let result=await request(f.unknown?'card-operation':'card',command);
   if(!sameScope(s))return null;
   if(result.status==='unknown')result=await request('card',command);
   if(result.operation_id!==command.operation_id||result.status!=='committed'||Number(result.workflow?.id)!==Number(id))throw Error('任务回执尚未确认。');
   RunTeamsWorkState.removeItem(f.key);f.pending=null;f.unknown=false;
   workCommitted(s,id);
   if(matches(s)){
    if(command.action==='trash'&&Number(S.sel?.workflowId)===Number(id))resetDetailWorkspace();
    await refresh({silent:true});
    if(S.sel?.id==='work'&&Number(S.sel.workflowId)===Number(id))await refreshOpenWork(s,S.sel,{force:true});
    if(command.action==='resume'&&['interrupted','needs_human','blocked','needs_approval'].includes(result.workflow.state))await openWork(id);
   }
   return result;
  }catch(error){if(sameScope(s)){if(error.confirmedReply){RunTeamsWorkState.removeItem(f.key);f.pending=null;}else f.unknown=true;f.error=error.confirmedReply?error.message:'操作结果尚未确认，请核对原操作。';}return null;}
  finally{f.busy=false;if(matches(s))render();}
 }
 async function editCard(event,id){
  event?.preventDefault();event?.stopPropagation();const s=current();let row=s?.data?.workflows.find(row=>Number(row.id)===Number(id));if(!row?.card_actions?.edit)return;
  const resume=row.card_actions.pause;
  if(resume){if(!await cardCommand(id,'pause'))return;if(!matches(s))return;row=s.data.workflows.find(row=>Number(row.id)===Number(id));}
  const title=row.title,host=openDialog({className:'modal-input modal-rename',title:'编辑任务',titleKey:'workflowDetail.editTask',closeOnScrim:false,closeLabelKey:'employeeSettings.closeDialog',body:`<label class="field"><span data-app-i18n="taskEdit.name">任务名称</span><input class="inp" id="pipeline_card_title" maxlength="200" value="${esc(title)}" autocomplete="off"></label><p class="field-error" role="alert" hidden></p>`,footer:'<div class="grow"></div><button type="button" class="btn" data-card-cancel data-app-i18n="employeeSettings.cancel">取消</button><button type="button" class="btn pri" data-card-save data-app-i18n="taskEdit.save">保存</button>'});
  const input=host.querySelector('input'),error=host.querySelector('[role="alert"]'),save=host.querySelector('[data-card-save]');
  let saving=false;
  const finish=async cancel=>{
   if(cancel&&!resume&&!saving){closeModal();document.querySelector(`.source-pipeline-workspace [data-workflow-id="${Number(id)}"]`)?.focus({preventScroll:true});return;}
   if(saving||!matches(s))return;const value=cancel?title:input.value.trim();if(!value){input.focus();return;}
   saving=true;save.disabled=true;
   const result=await cardCommand(id,'edit',{title:value,expected_title:title,resume_after_edit:resume});
   if(result){closeModal();requestAnimationFrame(()=>document.querySelector(`.source-pipeline-workspace [data-workflow-id="${Number(id)}"]`)?.focus({preventScroll:true}));}
   else if(host.isConnected){const f=cardState(s,id);error.hidden=false;error.textContent=f.error;input.disabled=!!f.pending;save.textContent=RunTeamsLocale.t(f.pending?'pipelineBoard.checkControl':'taskEdit.save',{},f.pending?'核对操作结果':'保存');save.disabled=false;saving=false;}
  };
  host.querySelector('[data-card-cancel]').onclick=()=>finish(true);host.querySelector('.modal-x').onclick=()=>finish(true);save.onclick=()=>finish(false);
  input.onkeydown=event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();void finish(false);}};
  RunTeamsLocale.apply(host);input.focus();input.select();
 }
 async function restoreCard(item){
  const command=item.restoreCommand??={operation_id:crypto.randomUUID(),reference:item.pipeline_reference,workflow_id:Number(item.id),expected_visit:item.pipeline_visit,action:'restore'};
  const result=await request('card',command);if(result.status==='committed')workCommitted({reference:item.pipeline_reference},item.id);return result;
 }
 function draftMenu(event,position){
  event.preventDefault();event.stopPropagation();const s=current(),c=s?.composer?.position===position?s.composer:s?.composerDrafts?.[position];if(!c||s.pendingComposer===c||s.sending)return;
  if(s.composer===c)composeDraft(document.getElementById('source_pipeline_task'));stopComposerTimer(c);c.editing=false;c.menuOpen=true;
  const anchor=event.currentTarget,card=anchor.closest('.card');
  const items=[{label:'编辑标题',labelKey:'pipelineCard.editTitle',icon:'edit',fn:()=>{c.editing=true;void compose(position);}},{label:'取消创建',labelKey:'pipelineCard.cancelCreation',icon:'x',fn:()=>{c.discarded=true;stopComposerTimer(c);if(s.composer===c)cancelCompose();else{delete s.composerDrafts[position];render();}}}];
  openCardMenu(anchor,items,{variant:'cardContext',align:'right',positionAnchor:card,keyboardReturn:()=>document.querySelector(`#source_pipeline_task[data-position="${position}"],.source-pipeline-workspace .card[data-position="${position}"]`),onClose:()=>{c.menuOpen=false;queueMicrotask(()=>{if(!c.discarded&&!c.editing&&sameScope(s))deferComposer(s,c);});},...(event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY}}:{})});
 }
 function focusComposer(s,c,{initial=false}={}){
  requestAnimationFrame(()=>{
   if(!matches(s)||s.composer!==c)return;
   const form=document.getElementById('source_pipeline_task');if(!form||form.dataset.position!==c.position)return;
   if(s.pendingComposer!==c&&c.controls){
    const nodes=[...form.querySelectorAll('input,textarea,select')];
    c.controls.forEach((value,index)=>{const node=nodes[index];if(node&&node.id===value.id){node.value=value.value;if(node.type==='checkbox')node.checked=value.checked;}});
   }
   const saved=c.focus;delete c.focus;
   if(!initial&&!saved)return;
   if(!initial&&document.activeElement!==document.body&&document.activeElement?.isConnected)return;
   const target=initial?form.querySelector(s.pendingComposer===c?'[data-task-submit]':'[name="title"]'):form.querySelectorAll('input,textarea,select,button')[saved.index];
   if(target&&!target.disabled){target.focus({preventScroll:true});if(saved?.start!=null&&target.setSelectionRange)try{target.setSelectionRange(saved.start,saved.end);}catch{}if(initial)target.scrollIntoView({block:'nearest',inline:'nearest'});}
  });
 }
 function captureComposer(s){
  const c=s.composer,active=document.activeElement,form=active?.closest?.('#source_pipeline_task');
  if(!c)return;
  if(form?.dataset.position===c.position){composeDraft(form);c.focus={index:[...form.querySelectorAll('input,textarea,select,button')].indexOf(active),start:active.selectionStart,end:active.selectionEnd};}
  focusComposer(s,c);
 }
 function cancelCompose(){
  const s=current();if(!s?.composer||s.sending)return;
  const c=s.composer;stopComposerTimer(c);composeDraft(document.getElementById('source_pipeline_task'));
  if(!s.pending&&s.composerDrafts)delete s.composerDrafts[c.position];
  delete c.focus;s.composer=null;if(!s.pending)s.submitError='';render();
  requestAnimationFrame(()=>{if(matches(s)&&!s.composer)[...document.querySelectorAll('.core-add-task')].find(button=>button.dataset.position===c.position)?.focus({preventScroll:true});});
 }
 const taskStartDelay=5000;
 function stopComposerTimer(c){if(!c)return;clearTimeout(c.startTimer);delete c.startTimer;delete c.autoStartAt;}
 function composerFocusin(event){
  const s=current(),c=s?.composer;if(!c||s.pendingComposer===c)return;
  if(event?.target&&!event.target.matches('input,textarea,select'))return;
  stopComposerTimer(c);c.editing=true;
  const status=document.querySelector('#source_pipeline_task [data-start-pending]');status?.remove();
 }
 function deferComposer(s,c){
  if(!sameScope(s)||!String(c.title||'').trim()||s.pendingComposer===c)return;
  stopComposerTimer(c);c.editing=false;c.autoStartAt=Date.now()+taskStartDelay;
  const fire=()=>{
   delete c.startTimer;
   if(!sameScope(s)||c.editing||!c.autoStartAt||!String(c.title||'').trim())return;
   if(c.error){stopComposerTimer(c);return;}
   if(c.loading||s.sending||s.pending&&s.pendingComposer!==c){c.startTimer=setTimeout(fire,200);return;}
   stopComposerTimer(c);void submit(s,c);
  };
  c.startTimer=setTimeout(fire,taskStartDelay);
 }
 function composerFocusout(event){
  const s=current(),c=s?.composer,root=event.currentTarget;
  if(!c||s.pendingComposer===c||root.contains(event.relatedTarget))return;
  composeDraft(root);
  queueMicrotask(()=>{
   if(!sameScope(s)||s.composer!==c||c.menuOpen||matches(s)&&document.getElementById('source_pipeline_task')!==root||root.contains(document.activeElement))return;
   if(!String(c.title||'').trim()){cancelCompose();return;}
   if(c.needsInput)try{c.parameters=readCoreTaskParameters(root);}catch(error){c.submitError={key:'taskNotSent',detail:error.message};render();return;}
   deferComposer(s,c);if(matches(s))render();
  });
 }
 function composerKeydown(event){
  if(event.isComposing)return;
  if(event.key==='ContextMenu'||event.key==='F10'&&event.shiftKey){draftMenu(event,event.currentTarget.dataset.position);return;}
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancelCompose();return;}
  if(event.target?.tagName==='TEXTAREA')return;
  if(event.key==='Enter'&&event.target?.tagName==='INPUT'){
   event.preventDefault();const s=current(),c=s?.composer;if(!c)return;
   composeDraft(document.getElementById('source_pipeline_task'));
   if(!String(c.title||'').trim()){cancelCompose();return;}
   if(c.needsInput)try{c.parameters=readCoreTaskParameters(document.getElementById('source_pipeline_task'));}catch(error){c.submitError={key:'taskNotSent',detail:error.message};render();return;}
   event.target.blur?.();deferComposer(s,c);render();
  }
 }
 function composeStatus(column,failed=false){
  const state=['done','dropped','pool'].includes(column.kind);
  const key=state?(failed?'createBlocked':'createPending'):(failed?'startBlocked':'startPending');
  const fallback=state?(failed?'未能创建，点击标题检查并修改':'5 秒后创建，点击标题继续修改'):(failed?'未能开始，点击标题检查并修改':'5 秒后开始，点击标题继续修改');
  return {key:'pipelineBoard.'+key,label:RunTeamsLocale.t('pipelineBoard.'+key,{},fallback)};
 }
 function queuedComposeCard(s,column,c){
  const {label}=composeStatus(column,!!(c.submitError||c.error));
  return `<div class="card title-only" oncontextmenu="RunTeamsSourcePipelines.draftMenu(event,this.dataset.position)" role="button" tabindex="0" data-position="${esc(c.position)}" onclick="RunTeamsSourcePipelines.compose(this.dataset.position)" onkeydown="if(event.target===this){if(event.key==='ContextMenu'||event.key==='F10'&&event.shiftKey)RunTeamsSourcePipelines.draftMenu(event,this.dataset.position);else if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}}"><div class="card-head"><div class="tt">${esc(c.title)}</div><span class="card-status ${c.submitError||c.error?'blocked':'queue'}" title="${esc(label)}" aria-label="${esc(label)}"><i class="d"></i></span></div></div>`;
 }
 async function compose(position,retry=false){
  const s=current();if(!s?.data||s.errorKey)return;
  if(requestDetailWorkspaceLeave(()=>compose(position,retry)))return;
  if(!RunTeamsSourcePipelinePanels.columns(s).some(column=>column.key===position))return;
  const old=s.composer;if(s.sending)return;if(old&&old.position!==position){composeDraft(document.getElementById('source_pipeline_task'));if(!s.pending){(s.composerDrafts??={})[old.position]=old;if(String(old.title||'').trim()&&!old.autoStartAt)deferComposer(s,old);}}
  resetDetailWorkspace();
  if(s.pending){s.composer=s.pendingComposer||s.composer||{title:s.pending.title,parameters:s.pending.payload?.parameters||{}};s.composer.position=position;s.pendingComposer=s.composer;render();focusComposer(s,s.composer,{initial:true});return;}
  const previous=old?.position===position?old:s.composerDrafts?.[position];
  if(previous&&(previous.contract||previous.loading)){stopComposerTimer(previous);previous.editing=true;s.composer=previous;render();focusComposer(s,previous,{initial:true});return;}
  const c={...previous,loading:true,position,error:'',title:previous?.title||'',parameters:previous?.parameters||{}};
  s.composer=c;s.submitError='';render();
  try{c.contract=await request('contract',{reference:s.reference,start_column_key:position});for(const [key,field] of Object.entries(c.contract.input_schema?.properties||{}))if(field.default!==undefined&&!Object.hasOwn(c.parameters,key))c.parameters[key]=structuredClone(field.default);}
  catch(error){c.error=error.message;}
  finally{c.loading=false;if(matches(s)&&s.composer===c){render();if(!c.autoStartAt)focusComposer(s,c,{initial:true});}}
 }
 function composeCard(s,column){
  const c=s.composer;if(!c||c.position!==column.key)return '';
  const pending=s.pendingComposer===c?s.pending:null,busy=!!(s.sending&&pending);
  const parameters=c.needsInput&&c.contract?coreWorkflowFrozenParameters(c.contract):[],disabled=!!(busy||pending);
  let body=c.needsInput?coreTaskParameterFields(parameters,c.parameters,'source_pipeline'):'';
  if(c.error)body=RunTeamsLoadFailure.markup({variant:'local',title:'无法读取任务输入',titleKey:'pipelineBoard.inputFailed',labelKey:'employeeHistory.retry',busyLabelKey:'pipelineBoard.inputLoading',error:c.error,retry:`RunTeamsSourcePipelines.compose(${JSON.stringify(c.position)},true)`});
  if(pending)body=`<p data-app-i18n="pipelineBoard.pendingHint">输入已保存。确认任务已创建后，它会显示在看板上。</p>`;
  const action=c.needsInput||pending?`<button class="btn sm" type="button" data-task-submit onclick="${pending&&s.canRetryAdmission?'RunTeamsSourcePipelines.retryAdmission()':'RunTeamsSourcePipelines.submit()'}" ${busy||c.loading||c.error||!pending&&s.data.runtime.status!=='running'?'disabled':''} data-app-i18n="pipelineBoard.${busy?(s.admissionUnknown?'checking':'submitting'):pending?(s.canRetryAdmission?'retryAdmission':'checkTask'):'createTask'}">${busy?(s.admissionUnknown?'正在核对…':'正在提交…'):pending?s.canRetryAdmission?'重试提交':'核对任务状态':'创建任务'}</button>`:'';
  const status=operationError(c.submitError||s.pendingComposer===c&&s.submitError),compact=!body&&!status&&!busy,queueStatus=composeStatus(column);
  return `<section id="source_pipeline_task" tabindex="-1" class="card ${compact?'title-only':''} source-pipeline-inline-task" data-position="${esc(c.position)}" aria-label="新建任务" data-app-i18n-aria-label="pipelineBoard.newTask" aria-busy="${!!(busy||c.loading)}" onpointerdown="event.stopPropagation()" onclick="event.stopPropagation()" oninput="RunTeamsSourcePipelines.composeDraft(this)" oncontextmenu="RunTeamsSourcePipelines.draftMenu(event,this.dataset.position)" onfocusin="RunTeamsSourcePipelines.composerFocusin(event)" onfocusout="RunTeamsSourcePipelines.composerFocusout(event)" onkeydown="RunTeamsSourcePipelines.composerKeydown(event)"><div class="card-head"><input id="source_pipeline_title" name="title" class="tt" aria-label="任务名称" data-app-i18n-aria-label="pipelineBoard.taskName" placeholder="新任务" data-app-i18n-placeholder="pipelineBoard.newTaskPlaceholder" value="${esc(pending?.title||c.title||'')}" autocomplete="off" maxlength="200" ${disabled?'disabled':''}>${c.autoStartAt?`<span class="card-status queue" data-start-pending title="${esc(queueStatus.label)}" aria-label="${esc(queueStatus.label)}" data-app-i18n-title="${queueStatus.key}" data-app-i18n-aria-label="${queueStatus.key}"><i class="d"></i></span>`:''}</div>${body}${action}${status}</section>`;
 }
 async function submit(s=current(),composer=s?.composer){
  if(!s||!sameScope(s)||s.errorKey||s.sending||s.pending&&s.pendingComposer&&s.pendingComposer!==composer)return;
  const form=matches(s)&&s.composer===composer?document.getElementById('source_pipeline_task'):null;
  const selection=S.sel,focused=form&&document.activeElement?.closest?.('.source-pipeline-inline-task');
  if(!s.pending){
   const c=composer;if(!c||c.loading||c.error||!c.contract)return;
   if(form)composeDraft(form);stopComposerTimer(c);const title=String(c.title||'').trim();
   if(!title){cancelCompose();return;}
   try{
   const parameters={...c.parameters,...(c.needsInput&&form?readCoreTaskParameters(form):{})};
   c.parameters=parameters;
   for(const key of c.contract.input_schema?.required||[]){const value=parameters[key];if(value==null||value===''||Array.isArray(value)&&!value.length){c.needsInput=true;throw Error(RunTeamsLocale.t('pipelineBoard.requiredInput',{field:taskSchemaFieldLabel(key,c.contract.input_schema.properties?.[key])},`请填写${taskSchemaFieldLabel(key,c.contract.input_schema.properties?.[key])}`));}}
   const command={operation_id:crypto.randomUUID(),reference:s.reference,start_column_key:c.position,title,payload:{schema:'runteams.task-input/v2',objective:title,context:{},parameters,inputs:[],module_bindings:{},asset_bindings:{}}};
   RunTeamsWorkState.setItem(pendingKey(s),JSON.stringify(command));s.pending=command;s.pendingComposer=composer;s.admissionUnknown=false;
   }catch(error){s.submitError={key:'taskNotSent',detail:error.message,detailKey:error.detailKey,detailVars:error.detailVars};composer.submitError=s.submitError;if(matches(s))render();return;}
  }
  s.sending=true;s.submitError='';composer.submitError='';if(matches(s))render();
  let completedTask;
  try{
   if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const reply=await request(s.admissionUnknown?'operation':'dispatch',s.pending);if(!sameScope(s))return;
   if(reply.status==='unknown'){s.canRetryAdmission=true;s.submitError={key:'taskRetryHint'};return;}
   RunTeamsWorkState.removeItem(pendingKey(s));s.pending=null;s.pendingComposer=null;s.admissionUnknown=false;if(s.composer===composer)s.composer=null;
   if(s.composerDrafts&&composer)delete s.composerDrafts[composer.position];
   completedTask=(reply.result||reply).workflow?.id;
   if(matches(s))await refresh({afterEdit:true});
  }catch(error){if(sameScope(s)){s.canRetryAdmission=false;s.admissionUnknown=error.code==='operation_unknown'||!error.confirmedReply;if(!s.admissionUnknown){RunTeamsWorkState.removeItem(pendingKey(s));s.pending=null;s.pendingComposer=null;}s.submitError={key:s.admissionUnknown?'taskCheckHint':'taskFailed',detail:error.message};composer.submitError=s.submitError;}}
  finally{
   s.sending=false;
   if(s.pending&&!matches(s))s.admissionUnknown=true;
   if(matches(s)){
    render();
    if(focused&&document.activeElement===document.body){
     if(completedTask&&S.sel===selection)document.querySelector(`.source-pipeline-workspace [data-workflow-id="${Number(completedTask)}"]`)?.focus();
     else if(S.sel===selection)document.querySelector('.source-pipeline-inline-task [data-task-submit]:not(:disabled)')?.focus({preventScroll:true});
    }
   }
  }
 }
 const workUpdateOwner=()=>JSON.stringify([workspaceAccountCacheToken(),workspaceDeviceStorageScope()]);
 const workUpdates=typeof BroadcastChannel==='function'?new BroadcastChannel('runteams.pipeline-work'):null;
 function workCommitted(workspace,workflowId){
  const notice={owner:workUpdateOwner(),reference:workspace.reference,workflowId:Number(workflowId)};
  try{workUpdates?.postMessage(notice);}catch{/* Polling still reads the confirmed ledger. */}
  void window.RunTeamsEmployeeDirectory?.refresh({localFirst:true,readPriority:'background'}).catch(()=>{});
 }
 async function receiveWorkUpdate(notice){
  if(!notice||notice.owner!==workUpdateOwner()||!referenceKey(notice.reference)||
   !Number.isSafeInteger(notice.workflowId)||notice.workflowId<=0||document.hidden)return;
  const workspace=taskWorkspace(),owner=S.sel;
  if(workspace&&referenceKey(workspace.reference)===referenceKey(notice.reference)){
   await refresh({silent:true});
   if(ownsTask(workspace)&&S.sel===owner&&owner?.type==='source-pipeline'&&owner.id==='work'&&
    Number(owner.workflowId)===notice.workflowId)await refreshOpenWork(workspace,owner,{force:true});
  }else if(owner?.type==='core-results'&&owner.data?.results?.some(row=>
   Number(row.workflow_id)===notice.workflowId&&referenceKey(row.pipeline_reference)===referenceKey(notice.reference))){
   await refreshContextResults(true);
  }
  void window.RunTeamsEmployeeDirectory?.refresh({localFirst:true,readPriority:'background'}).catch(()=>{});
 }
 if(workUpdates)workUpdates.onmessage=event=>{void receiveWorkUpdate(event.data).catch(()=>{});};
 let activityConnection;
 function activityTarget(){
  const workspace=taskWorkspace(),selection=S.sel;
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
  if(!taskWorkspace()||S.sel!==owner)return false;
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
   if(!ownsTask(s)||S.sel!==owner||owner.workflow!==previous)return;
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
 async function openWork(id,options={}){
  const s=options.workspace||taskWorkspace();if(!s)return;
  const previous=S.sel,back=options.returnToRecords||(s.embeddedTask&&Number(previous?.workflowId)===Number(id)?previous.returnToRecords:null);
  select('work',{workflowId:Number(id),loading:true,recordTitle:options.title||previous?.recordTitle,
   ...(s.embeddedTask?{employeeTaskWorkspace:s}:{}),...(back?{returnToRecords:back}:{}),
   ...(options.showDeliveries?{workSections:{deliveries:true}}:{})});const owner=S.sel;
  try{
   const [reply,data]=await Promise.all([request('work',{reference:s.reference,workflow_id:Number(id)}),
    s.data?Promise.resolve(s.data):request('workspace',{reference:s.reference})]);
   if(!ownsTask(s)||S.sel!==owner)return;
   s.data=data;s.loading=false;
   if(applyWorkReply(owner,reply))render();
  }catch(error){if(ownsTask(s)&&S.sel===owner){owner.loading=false;owner.error=error.message;render();}}
 }
 function openEmployeeTask(reference,id,options={}){
  if(!referenceKey(reference)||!Number.isSafeInteger(Number(id))||Number(id)<=0||!S.conversationPanel?.id)return;
  const workspace={scope:scope(),storageScope:durableScope(),reference,embeddedTask:true,
   employeePanelId:S.conversationPanel.id,view:'task',data:null,loading:true};
  return openWork(Number(id),{...options,workspace});
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
  const details=error.detail?`<p class="help" ${error.detailKey?`data-app-i18n="${esc(error.detailKey)}" data-app-i18n-vars="${esc(JSON.stringify(error.detailVars||{}))}"`:''}>${esc(error.detail)}</p>`:'';
  return `<p role="alert" data-app-i18n="pipelineBoard.${error.key}">${operationErrorFallback[error.key]}</p>${details}`;
 }
 function drawer(){
  const s=taskWorkspace(),selection=S.sel;if(!s||selection?.type!=='source-pipeline')return '';
  if(['settings','position'].includes(selection.id)&&window.RunTeamsSourcePipelinePanels)return RunTeamsSourcePipelinePanels.drawer();
  let title='',titleKey='',body='';
  if(selection.id==='work'){
   return RunTeamsSourcePipelinePanels.workDrawer(selection);
  }
  return '';
 }
 let creation=null;
 const creationKey=()=> 'runteams.pipeline-create:'+durableScope();
 const creationErrors={
  localSaveFailed:'无法在本机保存创建请求。智能体团队尚未创建。',
  unconfirmed:'暂时无法确认智能体团队是否已创建。请核对创建结果。',
  rejected:'无法创建智能体团队。请核对名称和首个岗位后重试。'
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
   title:'新建智能体团队',titleKey:'pipelineCreate.title',closeLabelKey:'employeeSettings.closeDialog',
   attrs:'role="dialog" aria-modal="true" aria-label="新建智能体团队" data-app-i18n-aria-label="pipelineCreate.title"',
   closeAction:'RunTeamsSourcePipelines.closeCreation()',
   body:'<div data-pipeline-create-fields></div><p role="alert" data-pipeline-create-error hidden></p>',
   footer:'<button class="btn" type="button" onclick="RunTeamsSourcePipelines.closeCreation()" data-app-i18n="pipelineCreate.close">关闭</button><button type="button" class="btn" data-app-i18n="materials.import" onclick="RunTeamsCreatorAuthor.choosePackage()">导入资产包</button><div class="grow"></div><button class="btn pri" type="button" data-pipeline-create-submit onclick="RunTeamsSourcePipelines.create()" disabled></button>'
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
    <label class="lbl" for="source_pipeline_create_name" data-app-i18n="pipelineCreate.name">智能体团队名称</label>
    <input class="input" style="width:100%" id="source_pipeline_create_name" name="name" required maxlength="80" value="${esc(c.name||'')}" oninput="RunTeamsSourcePipelines.creationName(this.value)">
    <label class="lbl" for="source_pipeline_first_role" data-app-i18n="pipelineCreate.firstRole">第一个岗位</label>
    <select class="input" style="width:100%" id="source_pipeline_first_role" name="choice" required><option value="" data-app-i18n="pipelineCreate.choose">选择员工和技能</option>${c.choices.map(creationChoiceLabel).join('')}</select>
   </form><p data-app-i18n="pipelineCreate.next">创建后，可以直接从岗位添加任务。</p>`:
   '<p data-app-i18n="pipelineCreate.empty">添加一名带有工作技能的员工后，即可创建智能体团队。</p>';
   const failed=RunTeamsLoadFailure.markup({variant:'local',title:'无法载入员工和技能',titleKey:'pipelineCreate.choicesFailedTitle',
    labelKey:'employeeHistory.retry',busyLabelKey:'pipelineCreate.choicesLoading',retry:'RunTeamsSourcePipelines.readCreationChoices()'});
   const partial=c.choiceErrors?.length?'<p role="status" data-app-i18n="pipelineCreate.partialChoices">部分员工或技能暂时无法载入。</p>':'';
   fields.innerHTML=c.pending?`<p><b>${esc(c.pending.name)}</b></p><p data-app-i18n="pipelineCreate.unconfirmed">无法确认智能体团队是否已创建。请核对创建结果。</p>`:
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
  submit.textContent=creationText(key,{},({checking:'正在核对…',creating:'正在创建…',check:'核对创建结果',create:'创建智能体团队'})[key]);
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
  try{if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const reply=await request('create',c.pending);if(c.scope!==scope()||creation!==c)return;const visible=revealTicket()&&c.modal?.isConnected&&document.getElementById('modalHost')?.firstChild===c.modal;RunTeamsWorkState.removeItem(creationKey());if(visible)closeModal();else c.modal?.remove();creation=null;const emptyModal=document.getElementById('modalHost')?.firstChild;await refreshCatalog();if(visible&&revealTicket()&&c.scope===scope()&&document.getElementById('modalHost')?.firstChild===emptyModal)await openReference(reply.reference);}
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
 function reset(){stopActivity();catalogSequence++;sequence++;rows=[];catalogScope='';catalogError='';catalogErrorScope='';reading=false;creation=null;}
 window.addEventListener('runteams:business-scope-will-change',reset);
 setInterval(()=>{
  const s=current();
  if(!document.hidden&&s?.data?.runtime?.status==='pausing'&&!s.sending)void refresh();
 },1000);
 async function pollWorkspace({detailOnly=false}={}){
  syncActivity();
  const s=taskWorkspace();
  if(document.hidden||!s?.data||s.sending||s.pollingWorkspace)return;
  if(detailOnly&&!(S.sel?.workflow?.state==='running'||S.sel?.attemptContext&&
   S.sel.data?.results?.some(result=>result.key===S.sel.resultKey&&result.state==='running')))return;
  s.pollingWorkspace=true;
  try{
   if(!detailOnly&&(s.view==='board'||s.embeddedTask)&&s.data.runtime.status!=='pausing')await refresh({silent:true});
   if(!ownsTask(s))return;
   if(S.sel?.type==='source-pipeline'&&S.sel.id==='work')await refreshOpenWork(s,S.sel,{force:!!s.embeddedTask&&!detailOnly});
   else await RunTeamsWorkRecords.refreshOpenAttempt();
  }finally{s.pollingWorkspace=false;}
 }
 setInterval(()=>void pollWorkspace(),8000);
 setInterval(()=>void pollWorkspace({detailOnly:true}),2000);
 window.addEventListener('pagehide',rememberComposerSize);
 window.addEventListener('focus',()=>void pollWorkspace());
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stopActivity();else void pollWorkspace();});
 window.RunTeamsSourcePipelines={pipelineIcon,cardFeedback,cardKeydown,cardMenu,cardCommand,editCard,draftMenu,restoreCard,taskWorkspace,openEmployeeTask,workCommitted,workContext,ensureWorkContext,request,select,operationError,current,sameScope,refreshCatalog,readCatalog,pageRoute,selectDockChat,catalogState,items:()=>catalogScope===scope()?rows.slice():[],sidebar,sidebarAvatar,sidebarMenu,openRoute,openFromLink,openVersion,refresh,retryRecovery,openReference,key,referenceKey,boot,header,editName,editIcon,board,workspace,conversation,dockPanel,messageToggle,toggleMessages,restoreMessageVisibility,animateComposer,retryBoard,control,compose,composeDraft,cancelCompose,composerKeydown,composerFocusin,composerFocusout,submit,openWork,refreshOpenWork,applyWorkReply,syncActivity,retainActivity,drawer,reset,newPipeline,closeCreation,readCreationChoices,create,retryControl,retryAdmission,creationName:value=>{if(creation)creation.name=value;}};
})();
