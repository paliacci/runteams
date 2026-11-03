/* The only mutable employee catalog. Views below are computed projections. */
(()=>{
 'use strict';
 let items=[],scope='',pending=null,sequence=0,activationSequence=0,error='';
 const token=()=>`${_workspaceBusinessGeneration}:${workspaceAccountCacheToken()}`;
 const current=()=>scope===token()?items:[];
 const isLoading=()=>pending?.scope===token()||false;
 function reset(){items=[];scope='';pending=null;sequence++;activationSequence++;error='';}
 function install(rows,expected){
  if(expected!==token())return false;
  if(!Array.isArray(rows)||rows.some(row=>typeof row.key!=='string'||!row.record?.name||!row.open))throw Error('员工目录回执无效');
  if(new Set(rows.map(row=>row.key)).size!==rows.length)throw Error('员工目录身份重复');
  items=rows;scope=expected;
  for(const row of rows)if(row.asset?.reference)RunTeamsHost.assets.remember(row.asset.reference);
  return true;
 }
 async function refresh(options={}){
  const expected=token();if(pending?.scope===expected)return pending.promise;
  const own=++sequence;
  const promise=(async()=>{
   const reply=await api('/api/employee-directory',undefined,undefined,{readCurrent:true,readPriority:options.readPriority});
   if(expected!==token()||own!==sequence)return;
   if(reply.error||reply.schema!=='runteams.employee-directory/v1')throw Error(reply.error||'员工目录没有载入');
   install(reply.items,expected);error=Object.values(reply.errors||{}).map(value=>value.error).filter(Boolean).join('；');
   S.coreTeamLoaded=true;S.coreTeamError=error;S.deviceSessionActor=String(S.localLibrary?.library_id||RunTeamsHost.session.actor(S)||'');
   return {employees:assets(),items:current(),errors:reply.errors};
  })();pending={scope:expected,promise};
  try{return await promise;}finally{if(pending?.promise===promise)pending=null;}
 }
 function accept(entry){
  if(!entry||(!S.localLibrary&&!RunTeamsHost.session.ready(S))||RunTeamsHost.session.workspace(S))return;
  // A confirmed creation carries the backend's exact directory projection.
  // It does not derive employee identity from a conversation title or chat ID.
  const rows=current(),same=(a,b)=>{const identity=referenceKey(a);return !!identity&&identity===referenceKey(b);},prior=rows.find(row=>row.key===entry.key||same(row.reference,entry.reference));sequence++;
  const next=prior?{...prior,key:entry.key,source:entry.source,record:{...prior.record,name:entry.record.name,avatar:entry.record.avatar,avatar_src:entry.record.avatar_src||null}}:entry;
  install([next,...rows.filter(row=>row!==prior&&row.key!==entry.key)],token());
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
  install(rows.map((row,n)=>n===index?{...row,asset,record:{...asset,...(row.source?{name:row.record.name,avatar:row.record.avatar,avatar_src:row.record.avatar_src||null}:{})}}:row),token());
 }
 const openings=new Map();
 async function activate(key,{newSession=false}={}){
  const entry=current().find(row=>row.key===key);if(!entry)throw Error('员工目录已变化，请重新打开');
  if(!newSession&&typeof workspaceEmployeeWindowIdentity==='function'){
   const identities=references(entry).map(referenceKey),existing=(S.workspaceWindows||[]).find(row=>identities.includes(workspaceEmployeeWindowIdentity(row.key)?.key));
   if(existing){activationSequence++;activateWorkspaceWindow(existing.key);return;}
  }
  if(!entry.source)return openBotConversation(entry.open.employee_id,{forceNew:newSession});
  const expected=token(),previous=S.conversationPanel,requestKey=expected+':'+key+(newSession?':new-session':':work');
  if(openings.has(requestKey))return openings.get(requestKey);
  const own=++activationSequence,drawerSequence=typeof _detailOpenSequence==='undefined'?null:_detailOpenSequence;
  const task=(async()=>{
   const receiptScope=S.localLibrary?workspaceAccountCacheToken():RunTeamsHost.session.deviceScope(S);
   if(newSession&&!receiptScope)throw Error('员工所在工作区未就绪，请重新打开');
   const receiptKey='runteams.employee-session-open:'+receiptScope+':'+key;
   let operation;
   if(newSession){operation=localStorage.getItem(receiptKey)||crypto.randomUUID();localStorage.setItem(receiptKey,operation);}
   const config=defaultChatConfig(null),runtime={channel_id:config.channel_id,model:config.model,reasoning_effort:config.reasoning_effort};
   const reply=await api('/api/employee-directory/open','POST',{key,runtime,purpose:'work',...(newSession?{operation_id:operation}:{})});
   if(expected!==token()||own!==activationSequence||S.conversationPanel!==previous)return;
   if(drawerSequence!==null&&drawerSequence!==_detailOpenSequence)return;
   if(reply.error||!reply.session)throw Error(reply.error||'员工暂时无法打开');
   const session=reply.session;
   if(session.kind!=='general'||!session.context?.local_employee_package)throw Error('员工工作入口未能核对');
   if(newSession)localStorage.removeItem(receiptKey);
   const {messages,...summary}=session,existing=(S.chats||[]).find(row=>String(row.id)===String(session.id));
   const last=messages?.[messages.length-1],lastBot=messages?.slice().reverse().find(row=>row.role==='bot');
   if(last)Object.assign(summary,{last_message_text:last.text,last_message_at:last.ts});
   if(lastBot)Object.assign(summary,{last_bot_message_text:lastBot.text,last_bot_message_at:lastBot.ts});
   S.chats=[{...existing,...summary},...(S.chats||[]).filter(row=>String(row.id)!==String(session.id))];
   accept(session.employee);await openConversationSession(session.id,session.kind);
   if(expected!==token()||String(S.conversationPanel?.id)!==String(session.id))return;
   // The chat loader restores this conversation's own drawer. A new session starts closed.
  })();openings.set(requestKey,task);if(typeof render==='function')render();
  try{return await task;}finally{if(openings.get(requestKey)===task)openings.delete(requestKey);if(expected===token()&&typeof render==='function')render();}
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
  return rows.filter(row=>row.storage_scope==='device'&&row.kind==='general'&&(entry?matches(entry,row):referenceKey(panelReference(row))===identity))
   .sort((a,b)=>String(b.updated_at||'').localeCompare(String(a.updated_at||''))||String(b.id).localeCompare(String(a.id),undefined,{numeric:true}));
 }
 // Display-only projection of existing execution facts; never an execution permission.
 const workLabel=value=>String(value||'').replace(/\s+/g,' ').trim().slice(0,100);
 function status(entry){
  if(!entry||!entryFor(entry.key))return {kind:'unknown',text:'状态暂不可用'};
  const panels=[...new Set([S.conversationPanel,...Object.values(S.conversationPanelsByChat||{})].filter(panel=>panel&&matches(entry,panel)))];
  const live=panels.find(panel=>panel.busy);
  if(live){
   const message=[...(live.messages||[])].reverse().find(item=>item.streaming),trace=message?.trace||{};
   const taskTitle=workLabel([...(live.messages||[])].reverse().find(item=>item.role==='user')?.text||live.title);
   const waiting=!live.stopping&&!live.stopRequested&&!trace.runtimeStatus&&(trace.requests||[]).some(item=>item.status==='pending');
   const phase=live.stopping||live.stopRequested?'正在停止':waiting?'需要处理':trace.runtimeStatus?.phase==='compacting'?'正在优化会话':trace.runtimeStatus?.phase==='thinking'?'正在思考':workLabel(trace.current)||'正在处理';
   return {kind:waiting?'waiting':'talking',text:taskTitle?`${phase}：${taskTitle}`:phase,taskTitle,chatId:live.id};
  }
  // Directory facts also cover work started in another session or client.
  const active=(S.chats||[]).find(row=>{
   if(!matches(entry,row)||row.awaiting_reply!==true)return false;
   const local=panels.find(panel=>String(panel.id)===String(row.id));
   const reply=[...(local?.messages||[])].reverse().find(item=>['bot','assistant'].includes(item.role)&&!item.streaming);
   return !(reply?.id&&Number(reply.id)>=Number(row.last_message_id)&&local&&!local.busy);
  });
  if(active){const taskTitle=workLabel(active.title),waiting=active.awaiting_user_input===true;return {kind:waiting?'waiting':'talking',text:[waiting?'需要处理':'正在处理',taskTitle].filter(Boolean).join('：'),taskTitle,chatId:active.id};}
  const workflows=[...(S.deviceWorkflows||[]),...(S.coreWorkflows||[]),...panels.flatMap(panel=>(panel.work||[]).map(work=>({...work,id:work.workflow_id,employee_reference:work.employee_reference||panelReference(panel)})))];
  const related=workflows.filter(row=>{
   if(row.trashed_at)return false;
   const ref=row.employee_reference||row.snapshot_json?.employee_reference;
   if(ref)return references(entry).some(value=>referenceKey(value)===referenceKey(ref));
   return entry.work&&typeof workflowOccupyingEmployeeId==='function'&&workflowOccupyingEmployeeId(row)===Number(entry.work.id);
  });
  const working=related.find(row=>['ready','running','waiting_retry'].includes(row.state));
  const waiting=related.find(row=>['needs_human','needs_approval','interrupted'].includes(row.state));
  const work=working||waiting;
  if(work){const taskTitle=workLabel(work.task?.title||work.snapshot_json?.task?.title||work.task_title||work.title),phase=working?(work.state==='waiting_retry'?'等待重试':work.state==='ready'?'等待开始':'正在处理'):'需要处理';return {kind:working?'working':'waiting',text:[phase,taskTitle].filter(Boolean).join('：'),taskTitle,workflowId:work.id};}
  if(S.chatDirectoryError||panels.some(panel=>panel.workError))return {kind:'unknown',text:'状态暂不可用'};
  if(S.chatDirectoryLoaded===false)return {kind:'unknown',text:'正在读取状态…'};
  return {kind:'idle',text:'空闲'};
 }
 function paintStatus(){
  const entry=forPanel();if(!entry||typeof employeeDeskNowMarkup!=='function')return;
  for(const node of document.querySelectorAll('[data-employee-work-status]')){
   if(node.dataset.employeeWorkStatus!==entry.key)continue;
   const html=employeeDeskNowMarkup(entry.key);
   if(node.outerHTML!==html)node.outerHTML=html;
  }
 }
 function rowMenu(event,key){
  event.preventDefault();event.stopPropagation();const entry=entryFor(key);if(!entry)return;
  const items=[{label:'员工设置',icon:'settings',fn:()=>settings(key)},{label:'工作记录',icon:'clock',fn:()=>openContextResults({employee_reference:entry.source?.reference||entry.reference})}];
  if(entry.asset?.editable)items.push({divider:true},{label:'移到垃圾箱',icon:'trash',fn:()=>trashCoreEmployee(entry.asset.id)});
  openMenu(event.currentTarget,items,{variant:'workerAction',...(event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY}}:{})});
 }
 function sessionTitle(row,panel=S.conversationPanel){
  const clean=value=>String(value||'').replace(/\[\[capability:[A-Za-z0-9_-]+\]\]/g,'').replace(/\s+/g,' ').trim();
  const title=clean(row.title),employeeNames=[forPanel(panel)?.record?.name,row.employee_binding?.name,row.context?.worker_name].map(clean).filter(Boolean);
  if(title&&(row.title_source==='manual'||!employeeNames.includes(title)&&!['新对话','未命名会话','正在准备'].includes(title)))return title;
  const cached=String(row.id)===String(panel?.id)?panel:S.conversationPanelsByChat?.[String(row.id)];
  const first=row.first_user_message_text??(String(cached?.id)===String(row.id)?cached.messages?.find(message=>message.role==='user')?.text:null);
  return clean(first)||'未命名会话';
 }
 function sessionMenu(event){
  const panel=S.conversationPanel;if(!employeePanel(panel))return;
  const expected=token(),stillCurrent=()=>token()===expected&&S.conversationPanel===panel;
  const entry=forPanel(panel);
  const rows=sessions(panel).slice(0,20),items=[{head:true,label:'历史会话',...(entry?{action:{label:'新会话',icon:'message-circle-plus',fn:()=>{if(stillCurrent())void newSession(entry.key).catch(error=>toast(error.message,'err'));}}}:{})}];
  for(const row of rows){const selected=String(row.id)===String(panel.id);items.push({label:sessionTitle(row,panel),selected,fn:()=>{if(stillCurrent()&&!selected&&sessions(panel).some(item=>String(item.id)===String(row.id)))void openConversationSession(row.id,'general');}});}
  if(!rows.length)items.push({empty:true,label:'还没有其他对话'});
  openMenu(event.currentTarget,items,{variant:'conversationSessions',align:'left',boundary:'workspace'});
 }
 const newSession=key=>activate(key,{newSession:true});
 const isOpening=key=>[...openings.keys()].some(value=>value.startsWith(token()+':'+key+':'));
 const open=key=>activate(key);
 function settings(key){const entry=entryFor(key);if(!entry)throw Error('员工目录已变化，请重新打开。');activationSequence++;return RunTeamsEmployeeConfiguration.open(entry);}
 async function finishCreation(panel,session){
  if(S.conversationPanel!==panel||String(panel.id)!==String(session?.id)||!session?.employee)return;
  // Creation changes the object of this conversation, never its navigation.
  accept(session.employee);
 }
 const sourceFor=value=>(entryFor(value)||assetEntry(value))?.source||null;
 window.RunTeamsEmployeeDirectory=Object.freeze({entryFor,assetEntry,forPanel,panelReference,referenceKey,references,matches,employeePanel,status,paintStatus,rowMenu,sourceFor,refresh,isLoading,accept,current,assets,downloaded,assetIdentity,upsertAsset,open,settings,isOpening,finishCreation,sessions,sessionMenu,newSession,reset});
 window.addEventListener('runteams:business-scope-changed',reset);
})();
