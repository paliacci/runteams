/* The only mutable employee catalog. Views below are computed projections. */
(()=>{
 'use strict';
 let items=[],scope='',pending=null,cloudPending=null,cloudNextAt=0,sequence=0,activationSequence=0;
 let activity=null,activityReadAt=0;
 let localError='',cloudError='';
 const token=()=>`${_workspaceBusinessGeneration}:${workspaceAccountCacheToken()}`;
 const current=()=>scope===token()?items:[];
 const isLoading=()=>pending?.scope===token()||cloudPending?.scope===token();
 function reset(){items=[];scope='';pending=null;cloudPending=null;cloudNextAt=0;activity=null;activityReadAt=0;localError='';cloudError='';sequence++;activationSequence++;}
 const showErrors=()=>{S.coreTeamError=[localError,cloudError].filter(Boolean).join('；');};
 function install(rows,expected){
  if(expected!==token())return false;
  if(!Array.isArray(rows)||rows.some(row=>typeof row.key!=='string'||!row.record?.name||!row.open))throw Error('员工目录回执无效');
  if(new Set(rows.map(row=>row.key)).size!==rows.length)throw Error('员工目录身份重复');
  items=rows;scope=expected;
  for(const row of rows)if(row.asset?.reference)RunTeamsHost.assets.remember(row.asset.reference);
  return true;
 }
 function readDirectory(expected,options,local){
  const flight=local?pending:cloudPending;
  if(flight?.scope===expected&&flight.sequence===sequence)return flight.promise;
  const own=sequence,started=Date.now();
  const promise=(async()=>{
   const reply=await api(local?'/api/employee-directory?view=local':'/api/employee-directory',undefined,undefined,
    {readCurrent:true,readPriority:options.readPriority});
   if(expected!==token()||own!==sequence)return;
   if(reply.error||reply.schema!=='runteams.employee-directory/v1')throw Error(reply.error||'员工目录没有载入');
   if(local){
    if(!Array.isArray(reply.activity?.chats)||reply.activity.workflows!==null&&!Array.isArray(reply.activity.workflows))throw Error('员工状态回执无效');
    deviceChatRemember(reply);
    activity=reply.activity;activityReadAt=started;
    localError=[reply.errors?.sources?.error,reply.errors?.downloads?.error].filter(Boolean).join('；');
   }else{
    cloudError=RunTeamsHost.session.workspace(S)
     ? Object.values(reply.errors||{}).map(value=>value.error).filter(Boolean).join('；')
     : reply.errors?.assets?.error||'';
   }
   // An independent local refresh must not discard already displayed cloud rows.
   if(!local||!current().some(row=>row.asset)){
    install(reply.items,expected);
   }
   showErrors();
   if(!local||S.localLibrary||current().length)S.coreTeamLoaded=true;
   S.deviceSessionActor=String(S.localLibrary?.library_id||RunTeamsHost.session.actor(S)||'');
   return {employees:assets(),items:current(),errors:reply.errors};
  })().finally(()=>{
   if(local&&pending?.promise===promise)pending=null;
   if(!local&&cloudPending?.promise===promise)cloudPending=null;
   if(expected===token()){
    S.coreTeamLoading=isLoading();
    if(!local&&!S.booting)refreshBotList();
   }
  });
  const next={scope:expected,sequence:own,promise};
  if(local)pending=next;else cloudPending=next;
  return promise;
 }
 async function refresh(options={}){
  const expected=token();
  if(RunTeamsHost.session.workspace(S))return readDirectory(expected,options,false);
  const local=await readDirectory(expected,options,true);
  if(expected!==token()||!local||S.localLibrary)return local;
  if(!options.localFirst&&options.readPriority!=='background'){
   cloudNextAt=Date.now()+60000;
   if(!S.booting)refreshBotList();
   return readDirectory(expected,options,false);
  }
  if(Date.now()>=cloudNextAt){
   cloudNextAt=Date.now()+60000;
   const own=sequence;
   void readDirectory(expected,{...options,readPriority:'background'},false).catch(error=>{
    if(expected!==token()||own!==sequence)return;
    cloudError=error.message;showErrors();
    if(!S.booting)refreshBotList();
   });
  }
  return local;
 }
 function accept(entry){
  if(!entry||(!S.localLibrary&&!RunTeamsHost.session.ready(S))||RunTeamsHost.session.workspace(S))return;
  // A confirmed creation carries the backend's exact directory projection.
  // It does not derive employee identity from a conversation title or chat ID.
  const rows=current(),same=(a,b)=>{const identity=referenceKey(a);return !!identity&&identity===referenceKey(b);},prior=rows.find(row=>row.key===entry.key||same(row.reference,entry.reference));sequence++;
  const next=prior?{...prior,key:entry.key,source:entry.source,record:{...prior.record,name:entry.record.name,avatar:entry.record.avatar,avatar_src:entry.record.avatar_src||null}}:entry;
  const updated=prior?rows.filter(row=>row===prior||row.key!==entry.key).map(row=>row===prior?next:row):[next,...rows];
  install(updated,token());
 }
 const downloaded=()=>current().map(row=>row.work).filter(row=>row&&!row.history_only);
 const assets=()=>current().filter(row=>row.asset||row.work).map(row=>row.record);
 function assetIdentity(id){
  id=Number(id);const entry=current().find(row=>Number(row.work?.id)===id||Number(row.asset?.id)===id);
  return entry?(Number(entry.work?.id)===id?entry.work:{...entry.record,...(entry.work?{work_employee_id:entry.work.id}:{})}):null;
 }
 function upsertAsset(asset){
  const rows=current(),index=rows.findIndex(row=>Number(row.asset?.id)===Number(asset.id));
  if(index<0)throw Error('员工不在当前目录中，请重新读取');
  sequence++;
  install(rows.map((row,n)=>n===index?{...row,asset,record:{...asset,...(row.source?{name:row.record.name,avatar:row.record.avatar,avatar_src:row.record.avatar_src||null}:{})}}:row),token());
 }
 const openings=new Map();
 function workConversation(entry){
  if(!entry)return null;
  const rows=(S.chats||[]).filter(row=>row.storage_scope==='device'&&row.kind==='general'&&
   !row.context?.pipeline_work&&!row.context?.source_pipeline_workspace&&matches(entry,row));
  const saved=entry.conversation;
  if(saved&&!rows.some(row=>String(row.id)===String(saved.id)))rows.push(saved);
  return rows.sort((a,b)=>Number(!!b.last_message_id)-Number(!!a.last_message_id)||
   String(b.updated_at||'').localeCompare(String(a.updated_at||''))||Number(b.id)-Number(a.id))[0]||null;
 }
 function forgetConversation(id){
  for(const row of current())if(String(row.conversation?.id)===String(id))delete row.conversation;
 }
 async function activate(key,{newSession=false}={}){
  const entry=current().find(row=>row.key===key);if(!entry)throw Error('员工目录已变化，请重新打开');
  if(!entry.source&&!newSession&&typeof workspaceEmployeeWindowIdentity==='function'){
   const identities=references(entry).map(referenceKey),existing=(S.workspaceWindows||[]).find(row=>identities.includes(workspaceEmployeeWindowIdentity(row.key)?.key));
   if(existing){activationSequence++;activateWorkspaceWindow(existing.key);return;}
  }
  const expected=token(),requestKey=expected+':'+key+(newSession?':new-session':':work');
  const existing=openings.get(requestKey);
  if(existing?.sequence===activationSequence&&S.workspaceSwitchPending===existing.pending)return existing.task;
  const recent=newSession||entry.source?null:workConversation(entry);
  const history=recent?.last_message_id||(!newSession&&entry.source&&(S.chats||[]).some(row=>
   row.storage_scope==='device'&&row.last_message_id&&String(row.id)===String(entry.source.chat_id)));
  const layout=history?'history':'employee';
  const pending=workspaceBeginEmployeeOpen(key,layout);
  const sequence=++activationSequence,drawerSequence=_detailOpenSequence;
  const ownsOpen=()=>expected===token()&&sequence===activationSequence&&S.workspaceSwitchPending===pending&&
   S.conversationPanel===pending.employeeOpen.panel&&S.surface===pending.employeeOpen.surface&&
   _routeSequence===pending.employeeOpen.routeSequence&&_detailOpenSequence===drawerSequence;
  const task=(async()=>{
   if(!entry.source)return openBotConversation(entry.open.employee_id,{forceNew:newSession,workspaceSwitchToken:pending.token,openCurrent:ownsOpen,employeeKey:key});
   const receiptScope=S.localLibrary?workspaceAccountCacheToken():RunTeamsHost.session.deviceScope(S);
   if(newSession&&!receiptScope)throw Error('员工所在工作区未就绪，请重新打开');
   const receiptKey='runteams.employee-session-open:'+receiptScope+':'+key;
   let operation;
   if(newSession){operation=localStorage.getItem(receiptKey)||crypto.randomUUID();localStorage.setItem(receiptKey,operation);}
   const config=defaultChatConfig(null),runtime={channel_id:config.channel_id,model:config.model,reasoning_effort:config.reasoning_effort};
   const reply=await api('/api/employee-directory/open','POST',{key,runtime,...(newSession?{operation_id:operation}:{})});
   if(!ownsOpen())return;
   if(reply.error||!reply.session)throw Error(reply.error||'员工暂时无法打开');
   const session=reply.session;
   if(session.kind!=='employee_design'||session.storage_scope!=='device'||
      session.context?.creator_local_source_id!==entry.source.id||session.context?.creator_employee_source!==entry.source.path)throw Error('员工对话入口未能核对');
   if(newSession)localStorage.removeItem(receiptKey);
   const {messages,...summary}=session,existing=(S.chats||[]).find(row=>String(row.id)===String(session.id));
   const last=messages?.[messages.length-1],lastBot=messages?.slice().reverse().find(row=>row.role==='bot');
   if(Array.isArray(messages))summary.last_message_id=last?.id??null;
   if(last)Object.assign(summary,{last_message_text:last.text,last_message_at:last.ts});
   if(lastBot)Object.assign(summary,{last_bot_message_text:lastBot.text,last_bot_message_at:lastBot.ts});
   S.chats=[{...existing,...summary},...(S.chats||[]).filter(row=>String(row.id)!==String(session.id))];
   deviceChatRemember(session);
   RunTeamsStaticPages.rememberLocalSessionLayout(session);
   accept(session.employee);await openRailConversationSession(session.id,{device:true,employeeKey:key});
   if(expected!==token()||String(S.conversationPanel?.id)!==String(session.id))return;
   // The chat loader restores this conversation's own drawer. A new session starts closed.
  })();openings.set(requestKey,{sequence,pending,task});
  try{return await task;}catch(error){if(ownsOpen())throw error;}
  finally{
   if(openings.get(requestKey)?.task===task)openings.delete(requestKey);
   if(S.workspaceSwitchPending===pending){workspaceFinishSwitchPending();render();}
  }
 }
 const referenceKey=ref=>{
  if(!ref||typeof ref!=='object')return '';
  const fields=ref.schema==='runteams.local-employee-reference/1'?(ref.storage_kind==='local'?['schema','source_id','employee_source','storage_kind','library_id']:['schema','source_id','employee_source','account_id','deployment_id','storage_namespace']):['runteams.acquired-employee-reference/1','runteams.rented-employee-reference/1'].includes(ref.schema)?['schema','source_id','employee_source','account_id','deployment_id','storage_namespace']:ref.schema==='runteams.business-reference/v1'?['schema','deployment_id','workspace_id','data_epoch','resource','id']:null;
  return fields&&fields.every(field=>ref[field]!==undefined)?JSON.stringify(fields.map(field=>ref[field])):'';
 };
 const references=entry=>[entry?.reference,entry?.source?.reference,entry?.work?.native_asset?.employee_reference].filter(ref=>referenceKey(ref));
 const entryFor=value=>typeof value==='string'?current().find(row=>row.key===value)||null:current().find(row=>references(row).some(ref=>referenceKey(ref)===referenceKey(value)))||null;
 const assetEntry=id=>current().find(row=>Number(row.asset?.id)===Number(id)||Number(row.work?.id)===Number(id))||null;
 const panelReference=panel=>panel?.employee_binding?.reference||panel?.context?.source_employee||panel?.context?.employee_reference||panel?.work_employee?.reference||null;
 function forPanel(panel=S.conversationPanel){
  if(!panel)return null;
  const ref=panelReference(panel);if(ref)return entryFor(ref);
  const c=panel.context||{};
  if(c.creator_local_source_id){const rows=current().filter(row=>row.source?.id===c.creator_local_source_id);return rows.find(row=>row.source.path===c.creator_employee_source)||(!c.creator_employee_source&&rows.length===1?rows[0]:null);}
  // Numeric IDs are restricted to the acquired-asset adapter, never source identity.
  return panel.kind==='general'&&c.context_type==='worker'?assetEntry(panel.employee_id||c.target_employee_id):null;
 }
 function matches(entry,panel){
  const found=forPanel(panel);return !!entry&&!!found&&found.key===entry.key;
 }
 function employeePanel(panel=S.conversationPanel){return !!forPanel(panel)||!!panelReference(panel)&&panel?.kind==='general'&&panel.context?.context_type==='worker';}
 function sessions(panel=S.conversationPanel){
  const entry=forPanel(panel),ref=panelReference(panel),identity=referenceKey(ref);if(!entry&&!identity)return [];
  const rows=[...(S.chats||[])];if(panel.id&&!rows.some(row=>String(row.id)===String(panel.id)))rows.unshift(panel);
  return rows.filter(row=>row.storage_scope==='device'&&['general','employee_design'].includes(row.kind)&&(entry?matches(entry,row):referenceKey(panelReference(row))===identity))
   .sort((a,b)=>String(b.updated_at||'').localeCompare(String(a.updated_at||''))||String(b.id).localeCompare(String(a.id),undefined,{numeric:true}));
 }
 // Display-only projection of existing execution facts; never an execution permission.
 const workLabel=value=>String(value||'').replace(/\s+/g,' ').trim().slice(0,100);
 const statusCopy=(phase,taskTitle,key)=>{
  const task=taskTitle?` · ${taskTitle}`:'';
  return {text:phase+task,...(key?{textKey:`employeeChat.${key}`,textVars:{task}}:{})};
 };
 function status(entry){return statuses(entry)[0];}
 function statuses(entry){
  if(!entry||!entryFor(entry.key))return [{kind:'unknown',text:'状态暂不可用',textKey:'employeeChat.statusUnavailable'}];
  const panels=[...new Set([S.conversationPanel,...Object.values(S.conversationPanelsByChat||{})].filter(panel=>panel&&matches(entry,panel)))];
  const liveStatuses=panels.filter(panel=>panel.busy).map(live=>{
   const message=[...(live.messages||[])].reverse().find(item=>item.streaming),trace=message?.trace||{};
   const taskTitle=workLabel([...(live.messages||[])].reverse().find(item=>item.role==='user')?.text||live.title);
   const waiting=!live.stopping&&!live.stopRequested&&!trace.runtimeStatus&&(trace.requests||[]).some(item=>item.status==='pending');
   const current=workLabel(trace.current);
   const [phase,key]=live.stopping||live.stopRequested?['正在停止','statusStopping']:waiting?['需要处理','statusAttention']:
    trace.runtimeStatus?.phase==='compacting'?['正在整理对话','statusCompacting']:trace.runtimeStatus?.phase==='thinking'?['正在思考','statusThinking']:
    current?[current,null]:['正在处理','statusWorking'];
   return {kind:waiting?'waiting':'talking',...statusCopy(phase,taskTitle,key),taskTitle,chatId:live.id,state:waiting?'needs_human':'running'};
  });
  // Directory facts also cover work started in another session or client.
  const active=(activity?.chats||S.chats||[]).filter(row=>{
   if(!matches(entry,row)||row.awaiting_reply!==true)return false;
   const local=panels.find(panel=>String(panel.id)===String(row.id));
   const reply=[...(local?.messages||[])].reverse().find(item=>['bot','assistant'].includes(item.role)&&!item.streaming);
   return !local?.busy&&!(reply?.id&&Number(reply.id)>=Number(row.last_message_id));
  });
  const chats=active.map(row=>{
   const taskTitle=workLabel(row.title),waiting=row.awaiting_user_input===true;
   return {kind:waiting?'waiting':'talking',...statusCopy(waiting?'需要处理':'正在处理',taskTitle,waiting?'statusAttention':'statusWorking'),taskTitle,chatId:row.id,state:waiting?'needs_human':'running'};
  });
  if(liveStatuses.length||chats.length)return [...liveStatuses,...chats];
  const panelWork=panels.flatMap(panel=>(panel.work||[]).map(work=>({...work,id:work.workflow_id,employee_reference:work.employee_reference||panelReference(panel)})));
  let workflows;
  if(activity?.workflows){
   const latest=new Map(activity.workflows.map(row=>[String(row.id),row]));
   for(const row of panelWork){
    const key=String(row.id),updated=Date.parse(row.updated_at);
    if(updated>=activityReadAt&&updated>=(Date.parse(latest.get(key)?.updated_at)||0))latest.set(key,row);
   }
   workflows=[...latest.values()];
  }else workflows=[...(S.deviceWorkflows||[]),...(S.coreWorkflows||[]),...panelWork];
  const related=workflows.filter(row=>{
   if(row.trashed_at)return false;
   const ref=row.employee_reference||row.snapshot_json?.employee_reference;
   if(ref)return references(entry).some(value=>referenceKey(value)===referenceKey(ref));
   return entry.work&&typeof workflowOccupyingEmployeeId==='function'&&workflowOccupyingEmployeeId(row)===Number(entry.work.id);
  });
  const working=related.filter(row=>['ready','running','waiting_retry'].includes(row.state));
  const work=working.length?working:related.filter(row=>['needs_human','needs_approval','interrupted'].includes(row.state));
  if(work.length){
   const unique=new Map();
   for(const row of work){
    if(unique.has(String(row.id)))continue;
    const taskTitle=workLabel(row.task?.title||row.snapshot_json?.task?.title||row.task_title||row.title);
    const [phase,key]=row.state==='waiting_retry'?['等待重试','statusRetry']:row.state==='ready'?['等待开始','statusQueued']:
     working.length?['正在处理','statusWorking']:['需要处理','statusAttention'];
    unique.set(String(row.id),{kind:working.length?'working':'waiting',...statusCopy(phase,taskTitle,key),taskTitle,workflowId:row.link_ready===false?null:row.id,state:row.state});
   }
   return [...unique.values()];
  }
  if(activity?.workflows===null||!activity&&(S.chatDirectoryError||panels.some(panel=>panel.workError)))return [{kind:'unknown',text:'状态暂不可用',textKey:'employeeChat.statusUnavailable'}];
  if(!activity&&S.chatDirectoryLoaded===false)return [{kind:'unknown',text:'正在读取状态…',textKey:'employeeChat.statusLoading'}];
  return [{kind:'idle',text:'空闲',textKey:'employeeChat.statusIdle'}];
 }
 function paintStatus(){
  const entry=forPanel();if(!entry||typeof employeeDeskNowMarkup!=='function')return;
  for(const node of document.querySelectorAll('[data-employee-work-status]')){
   if(node.dataset.employeeWorkStatus!==entry.key)continue;
   const html=employeeDeskNowMarkup(entry.key,node);
   if(html)node.outerHTML=html;
  }
  RunTeamsHeaderStatus.sync();
 }
 const pinStorageKey='runteams_sidebar_pinned_employees_v1';
 function pinnedKeys(){
  try{
   const value=JSON.parse(RunTeamsBusinessStorage.getItem(pinStorageKey)||'[]');
   return new Set(Array.isArray(value)?value.filter(key=>typeof key==='string'):[]);
  }catch{return new Set();}
 }
 function togglePin(key,expected){
  const entry=entryFor(key);
  if(expected!==token()||!entry||entry.pipeline_groups?.length)return;
  const pinned=pinnedKeys();
  const next=pinned.delete(key)?[...pinned]:[key,...pinned];
  try{
   if(!RunTeamsBusinessStorage.key(pinStorageKey))throw Error('Employee pin scope is unavailable');
   RunTeamsBusinessStorage.setItem(pinStorageKey,JSON.stringify(next));
  }catch{
   toast('无法保存员工置顶，请重试。','err','employeeSettings.pinFailed');
   return;
  }
  refreshBotList();
 }
 function rowMenu(event,key){
  event.preventDefault();event.stopPropagation();const entry=entryFor(key);if(!entry||entry.pipeline_groups?.length)return;
  const pinned=pinnedKeys().has(key),expected=token();
  const canManage=()=>{
   const current=entryFor(key);
   return expected===token()&&current&&!current.pipeline_groups?.length;
  };
  const items=[{label:pinned?'取消置顶':'置顶',labelKey:pinned?'conversationDetail.unpin':'conversationDetail.pin',icon:pinned?'pin-off':'pin',fn:()=>togglePin(key,expected)}];
  const uninstall=RunTeamsHost.assets.uninstallAction?.('employee',entry);
  if(uninstall)items.push({...uninstall,fn:()=>{if(canManage())uninstall.fn();}});
  else if(entry.asset?.editable&&RunTeamsHost.assets.canTrashEmployee?.(entry.asset)){
   items.push({label:'移到垃圾箱',labelKey:'employeeSettings.trash',icon:'trash',fn:()=>{
    if(canManage())trashCoreEmployee(entry.asset.id);
   }});
  }
  openMenu(event.currentTarget,items,{variant:'workerAction',dismissOnScroll:'#rgRail .bot-list-scroll',...(event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY}}:{})});
 }
 function sessionTitle(row,panel=S.conversationPanel){
  const clean=value=>String(value||'').replace(/\[\[capability:[A-Za-z0-9_-]+\]\]/g,'').replace(/\s+/g,' ').trim();
  const title=clean(row.title),employeeNames=[forPanel(panel)?.record?.name,row.employee_binding?.name,row.context?.worker_name].map(clean).filter(Boolean);
  if(title&&(row.title_source==='manual'||!employeeNames.includes(title)&&!['新对话','未命名会话','正在准备'].includes(title)))return title;
  const cached=String(row.id)===String(panel?.id)?panel:S.conversationPanelsByChat?.[String(row.id)];
  const first=row.first_user_message_text??(String(cached?.id)===String(row.id)?cached.messages?.find(message=>message.role==='user')?.text:null);
  return clean(first);
 }
 function sessionMenu(event){
  const panel=S.conversationPanel;if(!employeePanel(panel))return;
  const expected=token(),stillCurrent=()=>token()===expected&&S.conversationPanel===panel;
  const entry=forPanel(panel);
  const rows=sessions(panel).slice(0,20),items=[{head:true,label:'历史对话',labelKey:'employeeChat.history',...(entry?{action:{label:'新对话',labelKey:'shell.newChat',icon:'message-circle-plus',fn:()=>{if(stillCurrent())void newSession(entry.key).catch(()=>{if(stillCurrent())toast('无法打开新对话。请重试。','err','employeeChat.newConversationFailed');});}}}:{})}];
  for(const row of rows){
   const selected=String(row.id)===String(panel.id),title=sessionTitle(row,panel);
   items.push({label:title||'未命名对话',labelKey:title?undefined:'globalSearch.untitledChat',selected,fn:()=>{if(stillCurrent()&&!selected&&sessions(panel).some(item=>String(item.id)===String(row.id)))void openRailConversationSession(row.id,{device:true,employeeKey:entry?.key});}});
  }
  if(!rows.length)items.push({empty:true,label:'还没有其他对话',labelKey:'employeeChat.noHistory'});
  const keyboardReturn=()=>stillCurrent()?document.querySelector('.conversation-session-switcher'):null;
  openMenu(event.currentTarget,items,{variant:'conversationSessions',align:'left',boundary:'workspace',keyboardReturn});
 }
 const newSession=key=>activate(key,{newSession:true});
 const open=key=>activate(key);
 function settings(key){
  const entry=entryFor(key);if(!entry)throw Error('员工目录已变化，请重新打开。');
  activationSequence++;
  if(activeRailMode()==='assistant'&&matches(entry,S.conversationPanel)){
   return RunTeamsEmployeeConfiguration.openConversation(entry);
  }
  return RunTeamsEmployeeConfiguration.open(entry);
 }
 async function finishCreation(panel,session){
  if(S.conversationPanel!==panel||String(panel.id)!==String(session?.id)||!session?.employee)return;
  // Creation changes the object of this conversation, never its navigation.
  accept(session.employee);
 }
 const sourceFor=value=>(entryFor(value)||assetEntry(value))?.source||null;
 window.RunTeamsEmployeeDirectory=Object.freeze({entryFor,assetEntry,forPanel,panelReference,referenceKey,references,matches,employeePanel,status,statuses,paintStatus,rowMenu,pinnedKeys,sourceFor,refresh,isLoading,accept,current,assets,downloaded,assetIdentity,upsertAsset,open,settings,finishCreation,sessions,sessionMenu,newSession,workConversation,forgetConversation,reset});
 window.addEventListener('runteams:business-scope-changed',reset);
})();
