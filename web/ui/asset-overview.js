/* Device checks use the same declarations on employee and pipeline overviews. */
const RunTeamsEnvironment = (() => {
 'use strict';
 const t=(key,vars={})=>RunTeamsLocale.t('environmentCheck.'+key,vars);
 const allowed = ['ffmpeg','ffprobe'];
 let state, timer;
 const device = () => JSON.stringify([workspaceAccountCacheToken(), workspaceDeviceStorageScope()]);
 function current(){
  const scope = device();
  if(state?.scope !== scope){
   clearTimeout(timer);
   state = {scope, checks:{}, read:null, tools:[], checked:0, phase:'', error:'', repairError:'', chat:null};
   restoreChat(state);
  }
  return state;
 }
 function restoreChat(s){
  try{
   const saved=JSON.parse(localStorage.getItem('runteams.media-repair.'+s.scope));
   s.chat=saved?.id||null;s.repairTools=saved?.tools||[];
  }catch{}
 }
 function remember(s,id,tools=[]){
  s.chat=id;s.repairTools=tools;
  try{
   const key='runteams.media-repair.'+s.scope;
   if(id)localStorage.setItem(key,JSON.stringify({id,tools}));
   else localStorage.removeItem(key);
  }catch{}
 }
 function visible(s){
  return state===s && device()===s.scope && !!window.RunTeamsAssetOverview?.active();
 }
 async function check(s, tools){
  if(s.read)return s.read;
  s.read=(async()=>{
   try{
    const reply=await RunTeamsSourcePipelines.request('environment-check',{tools});
    if(tools.some(tool=>!['ready','missing','failed'].includes(reply.checks?.[tool])))throw Error();
    s.checks=reply.checks;s.error='';
    if(!s.repairing && tools.every(tool=>s.checks[tool]==='ready')){
     if(s.chat&&s.repairTools?.every(tool=>s.checks[tool]==='ready'))remember(s,null);
     s.repairError='';
    }
   }catch{s.error=t('readError');s.checks={};}
   finally{s.read=null;s.checked=String(s.tools)===String(tools)?Date.now():0;if(visible(s))render();}
  })();
  return s.read;
 }
 function schedule(s, tools){
  const different=String(s.tools)!==String(tools);
  s.tools=tools;
  if(different)s.checked=0;
  clearTimeout(timer);
  const delay=Math.max(0,s.checked+30000-Date.now());
  timer=setTimeout(()=>{
   if(!visible(s)||!document.querySelector('.asset-overview .overview-body')||document.hidden)return;
   if(!s.read && !s.repairing)void check(s,s.tools);
  },delay);
  if(!s.listening){
   s.listening=true;
   document.addEventListener('visibilitychange',function wake(){
    if(state!==s){document.removeEventListener('visibilitychange',wake);return;}
    if(!document.hidden && visible(s) && s.tools.length && !s.repairing)void check(s,s.tools);
   });
  }
 }
 function pipelineRows(data){
  const members=new Map((data?.employees||[]).map(member=>[member.member_ref,member]));
  return (data?.asset?.pipeline?.positions||[]).map(position=>({
   name:position.name,tools:members.get(position.employee_ref)?.skills?.find(skill=>skill.key===position.skill_key)?.environment_tools||[]
  }));
 }
 function markup(rows){
  const tools=allowed.filter(tool=>rows.some(row=>row.tools?.includes(tool)));
  if(!tools.length){if(timer)clearTimeout(timer);return '';}
  const s=current();schedule(s,tools);
  const issues=tools.filter(tool=>['missing','failed'].includes(s.checks[tool]));
  if(!issues.length&&!s.error)return '';
  const checking=s.phase==='verify', repairing=s.repairing;
  const status=checking?t('checking'):s.phase==='approval'?t('approval'):repairing?t('repairing'):s.error?t('failed'):t('count',{count:issues.length});
  const items=issues.map(tool=>{
   const names=[...new Set(rows.filter(row=>row.tools?.includes(tool)).map(row=>row.name).filter(Boolean))];
   const title=s.checks[tool]==='missing'?t('missing',{tool}):(tool==='ffmpeg'?t('decode'):t('duration'));
   return '<div class="environment-issue"><strong>'+esc(title)+'</strong><p>'+esc(t('impacts',{names:names.join('、')}))+'</p></div>';
  }).join('');
  const retry='<button type="button" class="btn sm" onclick="RunTeamsEnvironment.retry()">'+esc(t('retry'))+'</button>';
  const button=repairing||checking?'':s.error?retry:
   '<button type="button" class="btn pri sm" onclick="RunTeamsEnvironment.repair()">'+esc(t('repair'))+'</button>'+retry;
  const chat=s.chat?'<button type="button" class="btn sm" onclick="RunTeamsEnvironment.openChat()">'+esc(t('chat'))+'</button>':'';
  return '<section class="overview-environment" data-busy="'+(repairing||checking)+'" aria-label="'+esc(t('title'))+'"><header><h3>'+esc(t('title'))+'</h3><span role="status">'+status+'</span></header><div class="environment-details">'+items+
   (s.error||s.repairError?'<p role="status">'+esc(s.error||s.repairError)+'</p>':'')+'<div class="environment-actions">'+button+chat+'</div></div></section>';
 }
 async function retry(){const s=current();if(!s.tools.length||s.repairing)return;s.phase='verify';render();await check(s,s.tools);s.phase='';if(visible(s))render();}
 function openChat(){const s=current();if(s.chat)openConversationSession(s.chat,'general');}
 async function repair(){
  const s=current();
  if(s.repairing)return;
  if(!navigator.locks)return runRepair(s);
  await navigator.locks.request('runteams.media-repair.'+s.scope,{ifAvailable:true},async lock=>{
   if(!visible(s))return;
   restoreChat(s);
   if(lock)return runRepair(s);
   s.repairError=t('confirm');render();
  });
 }
 async function runRepair(s){
  if(s.repairing||s.read||s.error)return;
  const tools=s.tools.filter(tool=>['missing','failed'].includes(s.checks[tool]));
  if(!tools.length)return;
  s.repairing=true;s.phase='repair';s.repairError='';render();
  try{
   const config=defaultChatConfig();
   if(!config.channel_id||!config.model)throw Error(t('channel'));
   // Use a separate native conversation so work drafts and production cards stay intact.
   if(s.chat){
    const interaction=await api('/api/chat/'+encodeURIComponent(s.chat)+'/interaction');
    if(interaction?.error||interaction?.active!==false)throw Error(t('confirm'));
   }else{
    const reply=await api('/api/conversations','POST',{kind:'general',...config,context:{context_type:'general',intent:'general',ambient_disabled:true}});
    if(device()!==s.scope)return;
    if(!reply?.session?.id)throw Error(reply?.error||t('createFailed'));
    remember(s,reply.session.id,tools);
   }
   if(device()!==s.scope)return;
   if(visible(s))render();
   const message='请修复本机媒体运行环境。RunTeams 实测发现：'+tools.map(tool=>tool+(s.checks[tool]==='missing'?' 未找到':' 功能检查失败')).join('、')+
    '。先查找本机已有可执行程序并诊断原因。涉及安装、重装、提权或更改系统设置，先在本对话列出具体变更并向用户请求确认，收到确认后再执行。不要改动员工、智能体团队、现有任务或素材。完成后 RunTeams 会用短音频独立复检。';
   let terminal=false;
   await streamApi('/api/chat/'+encodeURIComponent(s.chat)+'/stream',{message,attachments:[],capabilities:[]},event=>{
    if(event.type==='agent_event' && ['user_input','user_input_resolved','user_input_expired'].includes(event.event?.kind)){
     s.phase=event.event.kind==='user_input'?'approval':'repair';
     if(visible(s))render();
    }
    if(event.type==='error')throw Error(event.message||t('runFailed'));
    if(event.type==='result'||event.type==='cancelled')terminal=true;
   });
   s.repairError=terminal?t('remaining'):t('disconnected');
  }catch(error){s.repairError=error.message||t('startFailed');}
  finally{
   if(device()===s.scope){
    s.phase='verify';if(visible(s))render();await check(s,s.tools);s.phase='';
    if(!s.error&&s.repairTools?.every(name=>s.checks[name]==='ready')){remember(s,null);s.repairError='';}
   }
   s.repairing=false;if(visible(s))render();
  }
 }
 return {markup,pipelineRows,repair,retry,openChat};
})();
/* Shared employee and pipeline drawer. The selected asset owns its reads and controls. */
(()=>{
 'use strict';
 const esc=value=>String(value??'').replace(/[&<>"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));
 const labels=(key,fallback)=>`<span data-app-i18n="assetOverview.${key}">${esc(fallback)}</span>`;
 const employee=()=>S.sel?.type==='employee-overview';
 const pipeline=()=>S.sel?.type==='source-pipeline'&&S.sel.id==='settings';
 const active=()=>employee()||pipeline();
 const section=(title,action,body,className='')=>`<section class="overview-section${className?' '+className:''}"><div class="settings-section-bar"><h3 class="settings-section-title">${title}</h3>${action}</div>${body}</section>`;
 const textButton=(label,action,disabled=false,style='btn pri sm')=>`<button type="button" class="${style}" onclick="${action}" ${disabled?'disabled':''}>${label}</button>`;

 const sectionAction=(label,action,disabled=false)=>textButton(label,action,disabled,'settings-section-action');

 // Device layout preferences are independent for employee and pipeline workspaces.
 const choices=new Map();
 const employeeHint='runteams.overview.employee-route';
 let lastContext='',manualMotion=false;
 function preferred(kind){
  let value=choices.get(kind);
  try{value=localStorage.getItem('runteams.overview.open.'+kind)??value;}catch{}
  return value==null?window.innerWidth>=1100:value==='open';
 }
 function remember(kind,open){
  const value=open?'open':'closed';
  choices.set(kind,value);
  try{localStorage.setItem('runteams.overview.open.'+kind,value);}catch{}
 }
 function employeeEligible(panel){
  return !!panel&&!panel.debug_preview&&(RunTeamsEmployeeDirectory.employeePanel(panel)||panel.kind==='employee_design'&&!!panel.context?.creator_local_source_id);
 }
 function routeKey(url){return url.pathname+'?chat='+String(url.searchParams.get('chat')||'');}
 function detailLink(url){return ['results','workflow'].some(key=>url.searchParams.has(key));}
 function pendingKind(value=location.href,layout=''){
  const url=new URL(value,location.origin),route=RunTeamsRoutes.preview(url.href);
  if(detailLink(url))return '';
  if(route.kind==='source-pipeline')return 'pipeline';
  if(route.kind==='employee-work'||route.kind==='bot'&&!route.settings)return 'employee';
  if(!['chat','chat-new'].includes(route.kind))return '';
  if(route.ownerPath?.startsWith('/employees/'))return 'employee';
  if(route.ownerPath?.startsWith('/pipelines/'))return RunTeamsStaticPages.pipelineChatView(url.href)==='board'?'pipeline':'';
  if(layout==='employee'||RunTeamsStaticPages.localConversationLayout(url.href)==='employee')return 'employee';
  try{if(sessionStorage.getItem(employeeHint)===routeKey(url))return 'employee';}catch{}
  return window.RunTeamsBoot?.savedWorkspaceWindows().some(row=>row.employeeReference&&routeKey(new URL(row.route,location.origin))===routeKey(url))?'employee':'';
 }
 function loadingSection(kind){
  return `<section class="overview-section"><div class="skeleton-block overview-loading-bar" aria-hidden="true"></div>${RunTeamsSkeletons.region(kind)}</section>`;
 }
 function loadingIntro(kind){
  const loadingKey=kind==='employee'?'employeeChat.guidanceLoading':'pipelineSettings.loading';
  const head=identity({avatar:`<span class="overview-avatar">${placeholder('avatar',loadingKey)}</span>`,
   namePlaceholder:placeholder('name',loadingKey),runtime:kind==='employee'?placeholder('runtime',loadingKey):'',descriptionControl:placeholder('description',loadingKey)});
  const examples=kind==='employee'?placeholder('examples',loadingKey):'';
  return head+examples;
 }
 function loadingDrawer(kind){
  const sections=loadingSection('overview-deliveries')+loadingSection('overview-activity')+loadingSection('overview-automation')+
   RunTeamsSkeletons.region('overview-configuration',1,kind==='employee'?'employeeSettings.loading':'pipelineSettings.loading');
  return `<aside class="drawer right-detail-drawer asset-overview overview-pending-drawer" ${RunTeamsSkeletons.statusAttrs('skeleton.loading')}><div class="overview-body" aria-hidden="true" inert>${loadingIntro(kind)}${sections}</div></aside>`;
 }
 function pendingPage(content,options){
  const kind=!options.error&&pendingKind(options.route||location.href,options.conversationLayout);
  if(!kind||!preferred(kind))return content;
  const width=typeof activeRightDetailWidth==='function'?activeRightDetailWidth():loadRightDetailWidth();
  return `<div class="overview-pending-workspace" style="--overview-pending-width:${width}px">${content}${loadingDrawer(kind)}</div>`;
 }
 function prepare(pipelinePage,employeePage){
  const s=pipelinePage&&RunTeamsSourcePipelines.current(),panel=employeePage&&S.conversationPanel;
  const kind=s?'pipeline':employeeEligible(panel)?'employee':'';
  const ready=s?!!s.data&&!s.loading&&!s.errorKey:!!panel&&!panel.loading&&!panel.error;
  if(!kind||!ready){
   lastContext='';
   const startup=S.workspaceStartup;
   const restoringPanel=startup?.deferChrome&&!startup.chromeReady&&!startup.navigationDetached&&startup.panel===panel;
   const hydratingRoute=!S.pageTransition&&S.surface==='team'&&!panel?.error&&(!panel||panel.loading||restoringPanel);
   const pending=pipelinePage&&!s?.errorKey?'pipeline':hydratingRoute?pendingKind():'';
   return pending&&!S.sel&&!detailLink(new URL(location.href))&&preferred(pending)?{key:'overview-pending:'+pending,content:()=>loadingDrawer(pending)}:null;
  }
  const context=detailWorkspaceContext();
  if(context===lastContext)return null;
  lastContext=context;
  if(kind==='employee'){try{sessionStorage.setItem(employeeHint,routeKey(new URL(location.href)));}catch{}}
  if(S.sel||detailLink(appRouteLocation()))return null;
  const open=preferred(kind);remember(kind,open);
  if(!open)return null;
  if(s){
   const selection=selectDetailWorkspace({type:'source-pipeline',id:'settings'});
   queueMicrotask(()=>{if(S.sel===selection&&RunTeamsSourcePipelines.current()===s)void RunTeamsSourcePipelinePanels.loadSettingsData(s);});
  }else selectDetailWorkspace({type:'employee-overview',id:panel.id});
  return null;
 }
 function trigger(disabled=false){
  return RunTeamsShell.headerAction({label:'概览',labelKey:'assetOverview.title',icon:ICON('panel-right-open'),action:'RunTeamsAssetOverview.toggle()',className:'asset-overview-trigger',selected:!!S._selKey,disabled});
 }
 function closed(){
  if(!active())return;
  remember(pipeline()?'pipeline':'employee',false);manualMotion=true;
 }
 function takeManualMotion(){const motion=manualMotion;manualMotion=false;return motion;}
 function toggle(){
  if(requestDetailWorkspaceLeave(toggle))return;
  const workspace=RunTeamsSourcePipelines.current(),panel=S.conversationPanel;
  if(!workspace&&(!panel||panel.loading||panel.error))return;
  const expanded=!!S._selKey;
  remember(workspace?'pipeline':'employee',!expanded);manualMotion=true;
  if(expanded){
   selectDetailWorkspace(null);render();return;
  }
  if(workspace)return RunTeamsSourcePipelinePanels.settings();
  selectDetailWorkspace({type:'employee-overview',id:panel.id});render();
 }
 function scopeUrl(scope){
  if(scope.employee_reference)return '/api/device/work/results?employee_reference='+encodeURIComponent(JSON.stringify(scope.employee_reference));
  return '/api/core/results?employee_id='+encodeURIComponent(scope.employee_id);
 }
 async function load(selection=S.sel){
  if(!active()||S.sel!==selection||selection.overviewLoading)return;
  const workspace=RunTeamsSourcePipelines.current(),scope=workspace?null:RunTeamsWorkRecords.scopeForPanel();
  const revision=selection.overviewWorkRevision;
  selection.overviewLoading=true;selection.overviewError=false;
  try{
   const data=workspace?await RunTeamsSourcePipelines.request('records',{reference:workspace.reference,overview:true}):scope?await api(scopeUrl(scope),undefined,undefined,{readCurrent:true}):{results:[]};
   if(S.sel===selection&&selection.overviewWorkRevision===revision)selection.overviewRecords=RunTeamsWorkRecords.readResults(data).results;
  }catch{if(S.sel===selection&&selection.overviewWorkRevision===revision)selection.overviewError=true;}
  finally{selection.overviewLoading=false;if(S.sel===selection)render();}
 }
 function rememberOrigin(key){
  S.sel.overviewOrigin={key,url:location.pathname+location.search+location.hash,top:document.querySelector('.overview-scroll')?.scrollTop||0};
 }
 function origin(selection){
  if(selection?.overviewReturn)return selection.overviewReturn;
  const records=selection?.returnToRecords?.selection||selection?.returnTo;
  return records?.type==='core-results'&&records.overviewReturn?.overviewOrigin?.key?records.overviewReturn:null;
 }
 function backMarkup(selection){
  if(!origin(selection))return '';
  return `<button type="button" class="run-back" title="返回概览" aria-label="返回概览" data-app-i18n-title="assetOverview.back" data-app-i18n-aria-label="assetOverview.back" onclick="RunTeamsAssetOverview.back()">${ICON('back')}</button>`;
 }
 function back(){
  const owner=origin(S.sel);if(!owner)return;
  const entry=owner.overviewOrigin;
  selectDetailWorkspace(owner);if(entry)setAppUrl(entry.url,true);render();
  requestAnimationFrame(()=>{
   if(S.sel!==owner||!entry)return;
   const node=document.querySelector('.overview-scroll');if(!node)return;
   node.scrollTop=entry.top;
   (entry.key?node.querySelector('[data-result-key="'+CSS.escape(entry.key)+'"]'):node.querySelector('.overview-activity .settings-section-action'))?.focus({preventScroll:true});
  });
 }
 function toggleActivity(){
  if(!active())return;
  S.sel.activityExpanded=!S.sel.activityExpanded;
  render();
  document.querySelector('.overview-activity .settings-section-action')?.focus({preventScroll:true});
 }
 function openEmployeeActivity(){
  selectDetailWorkspace({type:'employee-overview',id:S.conversationPanel.id,activityExpanded:true});
  const url=appRouteLocation();url.searchParams.delete('results');
  setAppUrl(url.pathname+url.search+url.hash,true);render();
 }
 function openRow(key){
  if(!active())return;
  rememberOrigin(key);
  if(pipeline()){
   const id=Number(key.replace(/^workflow-/,''))||S.sel.overviewRecords?.find(row=>row.key===key)?.workflow_id;
   if(id)return RunTeamsSourcePipelines.openWork(id);
  }else{
   const scope=RunTeamsWorkRecords.scopeForPanel();if(scope)return openContextResults(scope,{delivery:key});
  }
 }
 const previewLimit=2;
 function listToggle(expanded,controls,action,disabled=false){
  const label=expanded?esc(RunTeamsLocale.t('replyContent.collapse')):labels('all','全部');
  return `<button type="button" class="settings-section-action" aria-expanded="${!!expanded}" aria-controls="${controls}" ${disabled?'disabled':''} onclick="${action}">${label}</button>`;
 }
 function activity(records){
  if(!pipeline()&&!S.sel.overviewRecords&&!S.sel.overviewError)return loadingSection('overview-activity');
  const expanded=S.sel.activityExpanded;
  const reports=new Map((S.sel.overviewRecords||[]).map(row=>[row.key,row]));
  const recent=(expanded?records:records.slice(0,previewLimit)).map(row=>{
   const report=reports.get(row.key);
   const summary=report?.state===row.state&&report.summary||row.summary||row.objective;
   return {...row,summary};
  });
  if(expanded&&pipeline())RunTeamsWorkRecords.activityPreviews(S.sel,RunTeamsSourcePipelines.current(),recent);
  const list=recent.map(record=>RunTeamsWorkRecords.rowMarkup(record,'RunTeamsAssetOverview.openRow(this.dataset.resultKey)')).join('');
  const content=list?`<div class="work-record-list overview-records overview-activity-rows" id="overview-activity-records" role="list">${list}</div>`:!pipeline()&&S.sel.overviewError?sectionAction(labels('retry','重新载入'),'RunTeamsAssetOverview.load()'):RunTeamsEmptyStates.markup('records',{titleKey:'assetOverview.noActivity'});
  const toggle=records.length>previewLimit?listToggle(expanded,'overview-activity-records','RunTeamsAssetOverview.toggleActivity()'):'';
  return section(labels('activity','工作动态'),toggle,content,'overview-activity');
 }
 function deliveryItems(){
  const items=new Map();
  function add(file,document){
   const id=Number(document?file?.meta_json?.revision_of||file?.id:file?.id);
   if(!Number.isSafeInteger(id)||id<=0||!file.name)return;
   const key=(document?'doc-':'file-')+id;
   if(!items.has(key))items.set(key,{key,id,file,document});
  }
  for(const record of S.sel.overviewRecords||[]){
   if(!['completed','recorded'].includes(record.state))continue;
   if(Object.hasOwn(record,'delivery_document')){
    if(record.delivery_document)add({...record.delivery_document,purpose:'document'},true);
    continue;
   }
   if(record.report_document)add({...record.report_document,purpose:'document'},true);
   const outputs=new Set((record.outputs||[]).filter(o=>o.kind==='document').map(o=>Number(o.id)));
   for(const run of record.contributions||[]){
    for(const file of run.artifacts||[]){
     if(file.purpose==='document'){
      if(outputs.has(Number(file.id))&&!file.meta_json?.work_report)add(file,true);
     }else if(file.purpose!=='evidence' && file.meta_json?.source!=='pipeline_task_report')add(file,false);
    }
   }
  }
  return items;
 }
 function openDelivery(key){
  if(!active())return;
  const item=deliveryItems().get(key);
  if(!item)return;
  if(item.document)return openDocumentReaderById(item.id);
  return openResultEvidenceFile(item.id,[item.file]);
 }
 function toggleDeliveries(){
  if(!active())return;
  S.sel.deliveriesExpanded=!S.sel.deliveriesExpanded;
  render();
  document.querySelector('.overview-delivery-section .settings-section-action')?.focus({preventScroll:true});
 }
 function deliveryRows(items){
  const rows=items.map(({key,file,id,document})=>RunTeamsWorkRecords.deliveryRowMarkup(file,{
   key,actionOnly:true,downloadId:document?id:null,action:'RunTeamsAssetOverview.openDelivery(this.dataset.resultKey)'
  })).join('');
  return `<div class="work-deliverable-list" id="overview-delivery-files" role="list">${rows}</div>`;
 }
 const knowledgePreviewLimit=3;
 const knowledgeText=(key,vars={})=>RunTeamsLocale.t('assetKnowledge.'+key,vars);
 function knowledgeState(){
  const sel=S.sel;
  if(!active()||RunTeamsHost.session.workspace(S))return null;
  const owner=pipeline()?{reference:RunTeamsSourcePipelines.current()?.reference}:{chat:Number(S.conversationPanel?.id)};
  if(!owner.reference&&!owner.chat)return null;
  const key=JSON.stringify([workspaceAccountCacheToken(),workspaceDeviceStorageScope(),owner]);
  if(sel.knowledge?.key!==key)sel.knowledge={key,owner,total:null,items:[],request:0,error:''};
  return sel.knowledge;
 }
 function knowledgeRow(item){
  const name=item.name.split('/').pop();
  return `<button type="button" class="work-deliverable" data-source="${esc(JSON.stringify(item.id))}" onclick="RunTeamsAssetOverview.openKnowledge(JSON.parse(this.dataset.source))"><span class="work-deliverable-icon" aria-hidden="true">${ICON('doc')}</span><b class="work-deliverable-title" title="${esc(item.name)}">${esc(name)}</b><span class="work-deliverable-action">${esc(knowledgeText('open'))}</span></button>`;
 }
 async function readKnowledge(s){
  const request=++s.request;
  s.busy=true;s.error='';
  try{
   const query=s.expanded?{expanded:true}:{};
   const result=await RunTeamsSourcePipelines.request('asset-knowledge',{...s.owner,...query});
   if(knowledgeState()!==s||request!==s.request)return;
   s.items=result.sources;s.total=result.total;
  }catch(error){if(knowledgeState()===s&&request===s.request)s.error=error.message;}
  finally{if(knowledgeState()===s&&request===s.request){s.busy=false;render();}}
 }
 function appendKnowledgeRow(parent,cells,tag,label){
  const row=parent.insertRow(),marker=document.createElement('th');
  marker.scope=tag==='th'?'col':'row';marker.className='knowledge-row-number';
  marker.textContent=label;row.append(marker);
  for(const value of cells){
   const cell=document.createElement(tag);
   if(tag==='th')cell.scope='col';
   cell.textContent=value;row.append(cell);
  }
 }
 function showKnowledgeCsv(content,file,text){
  if(!text){content.className='mb result-evidence-preview-content is-empty';content.replaceChildren(resultEvidenceCopyNode('p','emptyFile','文件没有内容'));return;}
  // One field and its separator. A quoted field may contain entire physical lines.
  const field=/(?:"((?:[^"]|"")*)"|([^,\r\n]*))(,|\r\n|\n|\r|$)/gy;
  function readRow(start){
   field.lastIndex=start;
   const cells=[];
   let match;
   do{
    match=field.exec(text);
    if(!match||cells.length>=2048)return null;
    cells.push(match[1]===undefined?match[2]:match[1].replace(/""/g,'"'));
   }while(match[3]===',');
   return cells;
  }
  const headers=readRow(text.charCodeAt(0)===0xfeff?1:0),starts=[{offset:field.lastIndex,firstRow:1}];
  const viewport=document.createElement('div');
  viewport.className='knowledge-csv-scroll';viewport.tabIndex=0;
  const pager=document.createElement('nav'),number=document.createElement('span');
  pager.className='knowledge-csv-pager';number.setAttribute('aria-live','polite');
  let page=0;
  function pageButton(key,delta){
   const button=document.createElement('button');
   button.type='button';button.className='btn sm';button.textContent=knowledgeText(key);
   button.onclick=()=>draw(page+delta);return button;
  }
  const prev=pageButton('previousPage',-1),next=pageButton('nextPage',1);
  pager.append(prev,number,next);
  content.className='mb result-evidence-preview-content is-csv';
  content.replaceChildren(viewport,pager);
  function draw(index){
   const table=document.createElement('table');
   table.setAttribute('aria-label',file.name);
   function showOriginalText(){
    content.className='mb result-evidence-preview-content is-text';
    content.replaceChildren();showResultEvidenceText(content,file.name,text);
   }
   if(!headers){showOriginalText();return;}
   appendKnowledgeRow(table.createTHead(),headers,'th',knowledgeText('rowNumber'));
   const body=table.createTBody();
   let {offset,firstRow}=starts[index],cellsRendered=0;
   while(offset<text.length&&body.rows.length<100&&cellsRendered<10000){
    const row=readRow(offset);
    if(!row){showOriginalText();return;}
    appendKnowledgeRow(body,row,'td',firstRow+body.rows.length);cellsRendered+=row.length;
    offset=field.lastIndex;
   }
   page=index;starts[page+1]={offset,firstRow:firstRow+body.rows.length};
   prev.disabled=page===0;next.disabled=offset>=text.length;
   pager.hidden=prev.disabled&&next.disabled;
   number.textContent=String(page+1);
   viewport.replaceChildren(table);viewport.scrollTop=0;
  }
  draw(0);
 }
 function showWorkbook(content,file,sheets){
  const select=document.createElement('select');
  select.className='btn sm knowledge-sheet-select';
  select.setAttribute('aria-label',knowledgeText('worksheet'));
  sheets.forEach(({name},index)=>select.add(new Option(name,String(index))));
  const viewport=document.createElement('div');
  viewport.className='knowledge-csv-scroll';viewport.tabIndex=0;
  const controls=document.createElement('nav');
  controls.className='knowledge-csv-pager';
  const prev=document.createElement('button'),next=document.createElement('button'),number=document.createElement('span');
  number.setAttribute('aria-live','polite');
  for(const [button,key,delta] of [[prev,'previousPage',-1],[next,'nextPage',1]]){
   button.type='button';button.className='btn sm';button.textContent=knowledgeText(key);
   button.onclick=()=>draw(page+delta);
  }
  controls.append(prev,number,next);
  content.className='mb result-evidence-preview-content is-csv';
  content.replaceChildren(select,viewport,controls);
  let page=0;
  function draw(index){
   page=index;
   const sheet=sheets[select.selectedIndex],rows=sheet?.rows||[];
   const shown=rows.slice(page*100,(page+1)*100);
   if(shown.length){
    const table=document.createElement('table'),columns=Math.max(...shown.map(row=>row[1].length));
    table.setAttribute('aria-label',file.name+' · '+sheet.name);
    const labels=Array.from({length:columns},(_,i)=>{
     let label='';
     for(let n=i+1;n;n=Math.floor((n-1)/26))label=String.fromCharCode(65+(n-1)%26)+label;
     return label;
    });
    appendKnowledgeRow(table.createTHead(),labels,'th',knowledgeText('rowNumber'));
    const body=table.createTBody();
    for(const [row,values] of shown)appendKnowledgeRow(body,values,'td',row);
    viewport.replaceChildren(table);
   }else viewport.replaceChildren(resultEvidenceCopyNode('p','emptyFile','文件没有内容'));
   prev.disabled=page===0;next.disabled=(page+1)*100>=rows.length;
   controls.hidden=prev.disabled&&next.disabled;number.textContent=String(page+1);
   select.hidden=!sheets.length;viewport.scrollTop=0;viewport.scrollLeft=0;
  }
  select.onchange=()=>draw(0);
  draw(0);
 }
 async function openKnowledge(source){
  const s=knowledgeState(),file=s?.items.find(item=>item.id===source);
  if(!file)return;
  const host=openChildDialog({title:file.name.split('/').pop(),subtitle:knowledgeText('source',{origin:file.employee_name||knowledgeText('imported')}),
   className:'result-evidence-modal knowledge-file-modal',bodyClass:'mb result-evidence-preview-content is-loading',
   body:`<span class="env-spinner" aria-hidden="true"></span><span role="status">${esc(knowledgeText('loading'))}</span>`,
   headerActions:`<button type="button" class="doc-reader-download knowledge-download" title="${esc(knowledgeText('saveOriginal'))}" aria-label="${esc(knowledgeText('saveOriginal'))}" data-app-i18n-title="assetKnowledge.saveOriginal" data-app-i18n-aria-label="assetKnowledge.saveOriginal" onclick="RunTeamsAssetOverview.exportKnowledge(${esc(JSON.stringify(source))},this)">${ICON('download')}</button>`,
   footer:'',footerClass:'knowledge-export-feedback',footerAttrs:'role="alert" hidden',
   closeLabelKey:'workRecordDetail.closePreview',manageFocus:true});
  const content=host.querySelector('.result-evidence-preview-content');
  const current=()=>host.isConnected&&knowledgeState()===s;
  function failed(message){
   if(!current())return;
   content.className='mb result-evidence-preview-content is-empty';
   content.textContent=message;content.setAttribute('role','alert');
  }
  try{
   const fileData=await RunTeamsSourcePipelines.request('asset-knowledge',{...s.owner,source,open:true},{retryOnDisconnect:false});
   if(!current())return;
   if(fileData.kind==='opened'){closeChildDialog();return;}
   content.replaceChildren();
   if(fileData.kind==='image'){
    const image=new Image();image.alt=file.name;
    image.onerror=()=>failed(RunTeamsLocale.t('workRecordDetail.fileFailed'));
    content.className='mb result-evidence-preview-content is-image';
    content.append(image);image.src=fileData.url;
   }else if(fileData.kind==='workbook'){
    showWorkbook(content,file,fileData.sheets);
   }else if(/\.csv$/i.test(file.name)){
    showKnowledgeCsv(content,file,fileData.text);
   }else{
    content.className='mb result-evidence-preview-content is-text';
    showResultEvidenceText(content,file.name,fileData.text);
   }
  }catch(error){failed(error.code==='knowledge_office_unreadable'?knowledgeText('unreadableOffice'):error.message);}
 }
 function toggleKnowledge(){
  const s=knowledgeState();if(!s||s.uploading)return;
  s.expanded=!s.expanded;s.error='';
  if(s.expanded&&s.items.length<s.total)void readKnowledge(s);
  else{s.request++;s.busy=false;}
  render();
 }
 function retryKnowledge(){
  const s=knowledgeState();if(!s||s.busy)return;
  void readKnowledge(s);
  render();
 }
 function refreshKnowledgeAfterTurn(panel){
  if(S.conversationPanel!==panel||!(pipeline()?panel.context?.source_pipeline_workspace:employee()&&panel.kind==='general'))return;
  const s=knowledgeState();
  if(s&&!s.uploading)void readKnowledge(s);
 }
 function knowledgeAddAction(s){
  return sectionAction(esc(knowledgeText('import')),'this.nextElementSibling.click()',s.busy)+
   '<input type="file" hidden accept=".png,.jpg,.jpeg,.webp,.gif,.mp4,.mov,.wav,.mp3,.m4a,.ogg,.flac,.txt,.md,.markdown,.csv,.json,.srt,.vtt,.pdf,.doc,.docx,.xls,.xlsx" onchange="RunTeamsAssetOverview.uploadKnowledge(this.files[0])">';
 }
 function knowledgeEmpty(){
  return RunTeamsEmptyStates.markup('documents',{title:knowledgeText('empty'),titleKey:'assetKnowledge.empty'});
 }
 function knowledgeSection(s){
  if(!s)return '';
  if(!s.request){s.request++;queueMicrotask(()=>{if(knowledgeState()===s&&!s.busy)void readKnowledge(s);});}
  const toggle=s.total>knowledgePreviewLimit?listToggle(s.expanded,'overview-knowledge-files','RunTeamsAssetOverview.toggleKnowledge()',s.uploading):'';
  const rows=s.expanded?s.items:s.items.slice(0,knowledgePreviewLimit);
  const pending=s.total===null?knowledgePreviewLimit:s.busy&&s.expanded?Math.min(knowledgePreviewLimit,s.total-rows.length):0;
  const skeleton=!s.error&&pending>0?RunTeamsSkeletons.region('overview-knowledge',pending):'';
  let body=`<div class="work-deliverable-list" id="overview-knowledge-files">${rows.map(knowledgeRow).join('')}${skeleton}</div>`;
  if(!s.error&&s.total===0)body=knowledgeEmpty();
  if(s.error)body+=`<p role="alert">${esc(s.error)}</p>`+sectionAction(esc(knowledgeText('reload')),'RunTeamsAssetOverview.retryKnowledge()');
  return section(esc(knowledgeText('title')),'<div class="overview-knowledge-actions">'+knowledgeAddAction(s)+toggle+'</div>',body,'overview-knowledge');
 }
 async function exportKnowledge(source,button){
  const s=knowledgeState();if(!s||s.busy||!s.items.some(item=>item.id===source))return;
  const feedback=button.closest('.knowledge-file-modal').querySelector('.knowledge-export-feedback');
  feedback.hidden=true;feedback.textContent='';button.disabled=true;
  s.busy=true;s.error='';render();
  try{
   const result=await RunTeamsSourcePipelines.request('asset-knowledge',{...s.owner,source,export:true});
   if(result.saved&&knowledgeState()===s)toast(knowledgeText('saved'),'ok');
  }catch(error){
   if(knowledgeState()!==s)return;
   const message=error.code==='knowledge_name_conflict'?knowledgeText('nameConflict'):error.message;
   if(feedback.isConnected){feedback.hidden=false;feedback.textContent=message;}
   else s.error=message;
  }finally{button.disabled=false;if(knowledgeState()===s){s.busy=false;render();}}
 }
 async function uploadKnowledge(file){
  const s=knowledgeState();if(!s||s.busy||!file)return;
  s.uploading=true;s.busy=true;s.error='';render();
  try{
   const request=data=>RunTeamsSourcePipelines.request('asset-knowledge',{...s.owner,...data});
   const {upload}=await request({upload:'begin',name:file.name,size:file.size});
   let saved=false;
   try{
    const block=2*1024*1024;
    for(let offset=0;offset<file.size;offset+=block){
     if(knowledgeState()!==s)return;
     const {data}=await readChatFile({file:file.slice(offset,offset+block),name:file.name});
     await request({upload,offset,chunk:data});
    }
    if(knowledgeState()!==s)return;
    let result=await request({upload,replace:false});
    if(result.duplicate&&knowledgeState()===s&&window.confirm(knowledgeText('replace',{name:file.name}))){
     result=await request({upload,replace:true});
    }
    saved=result.saved;
   }finally{
    if(!saved)await request({upload,cancel:true}).catch(()=>{});
   }
   if(knowledgeState()===s)await readKnowledge(s);
  }catch(error){if(knowledgeState()===s)s.error=error.message;}
  finally{if(knowledgeState()===s){s.uploading=false;s.busy=false;render();}}
 }
 function deliverySection(){
  if(!S.sel.overviewRecords&&!S.sel.overviewError)return loadingSection('overview-deliveries');
  const items=[...deliveryItems().values()];
  if(!items.length)return '';
  const expanded=S.sel.deliveriesExpanded;
  const all=items.length>previewLimit?listToggle(expanded,'overview-delivery-files','RunTeamsAssetOverview.toggleDeliveries()'):'';
  return section(labels('deliveries','交付成果'),all,deliveryRows(expanded?items:items.slice(0,previewLimit)),'overview-delivery-section');
 }
 function placeholder(part,labelKey){
  return `<span class="skeleton-block overview-placeholder" data-skeleton-region="overview-${part}" ${RunTeamsSkeletons.statusAttrs(labelKey)}></span>`;
 }
 function versionToolbar({version,modeControl,publication,loading}){
  if(!loading&&!modeControl&&!version&&!publication)return '';
  if(publication?.initialRead||(!publication&&loading)){
   return '<footer class="overview-footer"><div class="overview-version-actions">'+placeholder('version','skeleton.loading')+
    placeholder('version-action','skeleton.loading')+'</div></footer>';
  }
  version=publication?.version||version;
  const number=version?esc(/^\d/.test(version)?'v'+version:version):'';
  const versionLabel=publication?.versionPending?placeholder('version','skeleton.loading'):number?`<span class="overview-version-number">${number}</span>`:loading?placeholder('version','skeleton.loading'):'';
  let button='';
  if(publication){
   const {labelKey,label,vars,action,id,disabled,popup,expanded,passive}=publication;
   const caption=`<span data-app-i18n="${esc(labelKey)}"${vars?' data-app-i18n-vars="'+esc(JSON.stringify(vars))+'"':''}>${esc(label)}</span>`;
   button=publication.checking||loading&&!number?placeholder('version-action',publication.checking?labelKey:'skeleton.loading'):
    passive?`<span class="overview-version-status" role="status">${caption}</span>`:
    `<button type="button"${id?' id="'+esc(id)+'"':''} class="btn pri sm" onclick="${esc(action)}"${disabled?' disabled':''}${popup?' aria-haspopup="'+esc(popup)+'" aria-expanded="'+!!expanded+'"':''}>${caption}</button>`;
  }
  return `<footer class="overview-footer">${modeControl}<div class="overview-version-actions">${versionLabel}${button}</div></footer>`;
 }
 function identity({title='',avatar,description='',descriptionControl='',runtime='',descriptionDetails='',namePlaceholder=''}){
  return `<header class="overview-identity">${avatar}
   <h2 title="${esc(title||'')}">${title?esc(title):namePlaceholder}</h2><div class="overview-head-action">${runtime}</div>
   ${description||descriptionControl?`<div class="overview-description" title="${esc(description||'')}">${descriptionControl||`<span>${esc(description)}</span>`}</div>`:''}${descriptionDetails}</header>`;
 }
 // Comment boundaries keep optional, multi-element sections in the same layout.
 const part=(name,html)=>`<!--overview:${name}-->${html}<!--/overview:${name}-->`;
 function splitDrawer(html){
  const parts=new Map();
  const frame=html.replace(/<!--overview:([a-z-]+)-->([\s\S]*?)<!--\/overview:\1-->/g,(_,name,body)=>{
   parts.set(name,body);return part(name,'');
  });
  return {parts,frame};
 }
 function patchDrawer(root,before,after){
  if(!before||!root.querySelector('.asset-overview .overview-scroll'))return false;
  const previous=splitDrawer(before),next=splitDrawer(after);
  if(!previous.parts.size||previous.frame!==next.frame)return false;
  const changed=new Map([...next.parts].filter(([name,body])=>body!==previous.parts.get(name)));
  const comments=document.createTreeWalker(root,NodeFilter.SHOW_COMMENT),ranges=new Map();
  // Validate all boundaries before mutating any section. A drawer rebuilt by
  // another view must go through the normal full render.
  for(let node=comments.nextNode();node;node=comments.nextNode()){
   if(!node.data.startsWith('overview:'))continue;
   const name=node.data.slice('overview:'.length);
   if(!changed.has(name))continue;
   let end=node.nextSibling;
   while(end&&!(end.nodeType===Node.COMMENT_NODE&&end.data==='/overview:'+name))end=end.nextSibling;
   if(!end||ranges.has(name))return false;
   const range=document.createRange();
   range.setStartAfter(node);range.setEndBefore(end);ranges.set(name,range);
  }
  if(ranges.size!==changed.size)return false;
  for(const [name,range] of ranges){
   const template=document.createElement('template');
   template.innerHTML=changed.get(name);
   range.deleteContents();range.insertNode(template.content);
  }
  return true;
 }
 function shell({title,avatar,description,descriptionControl='',descriptionDetails='',runtime='',examples='',pending='',environment=[],configuration='',version='',modeControl='',publication=null,extras='',records,identityLoading=false,versionLoading=false}){
  const sel=S.sel;
  if(records){
   const revision=JSON.stringify(records.map(row=>[row.key,row.state,row.updated_at]));
   if(sel.overviewWorkRevision!==revision){
    sel.overviewWorkRevision=revision;
    sel.overviewRecords=records.length?undefined:[];
    sel.overviewError=false;
   }
  }
  if(!sel.overviewRecords&&!sel.overviewLoading&&!sel.overviewError)queueMicrotask(()=>{if(S.sel===sel&&!sel.overviewRecords)void load(sel);});
  const intro=identityLoading?loadingIntro(pipeline()?'pipeline':'employee'):identity({title,avatar,description,descriptionControl,descriptionDetails,runtime})+examples;
  const knowledge=knowledgeState();
  const body=part('identity',intro)+part('environment',RunTeamsEnvironment.markup(environment))+
   part('pending',pending)+part('deliveries',deliverySection())+
   (employee()?part('knowledge',knowledgeSection(knowledge)):'')+
   part('activity',activity(records||sel.overviewRecords||[]))+part('automation',RunTeamsEmployeeAutomation.overviewSection())+
   (pipeline()?part('knowledge',knowledgeSection(knowledge)):'')+
   part('configuration',configuration)+part('extras',extras);
  return `<aside class="drawer right-detail-drawer asset-overview employee-configuration-drawer ${pipeline()?'source-pipeline-settings-drawer':''}"><div class="right-detail-scroll overview-scroll"><div class="right-detail-body overview-body">${body}</div></div>${part('version',versionToolbar({version,modeControl,publication,loading:versionLoading}))}</aside>`;
 }
 function employeeConfiguration(panel,entry){
  if(!entry||entry.work?.history_only||panel.loading||panel.error||panel.employee_error||panel.context?.pipeline_work||panel.context?.source_pipeline_workspace)return '';
  const selection=S.sel,settings=RunTeamsEmployeeConfiguration;
  const target=settings.workTarget(panel)||entry;
  requestAnimationFrame(()=>{
   if(S.sel===selection&&S.conversationPanel===panel)void settings.mountInline(target,selection);
  });
  const parts=settings.inlineParts(target.key);
  return parts?'<div class="settings-section-stack">'+parts.body+'</div>':'';
 }
 function employeeDrawer(){
  const panel=S.conversationPanel,entry=RunTeamsEmployeeDirectory.overviewEntry(panel),record=entry?.record||{},binding=panel.employee_binding||{};
  const examples=conversationEmployeeExamples(panel);
  const chips=examples.map(item=>`<button type="button" onclick="conversationPanelWorkExample(this)"${conversationWorkExampleAttribute(item)}><span class="overview-example-icon" aria-hidden="true">${ICON(conversationExampleIcon(item.icon))}</span><span data-work-example-label>${esc(conversationWorkExampleText(item).title)}</span></button>`).join('');
  const version=entry?.source?.version||entry?.work?.origin?.listing_version||record.active_release?.version||entry?.asset?.version||'';
  const publication=RunTeamsHost.assets.employeePublicationAction?.(panel,entry);
  const directoryLoading=!entry&&RunTeamsEmployeeDirectory.isLoading();
  const name=record.name||binding.name;
  const identityLoading=!name&&!panel.error&&(panel.loading||panel.guidanceReading||directoryLoading);
  const description=binding.description||entry?.source?.description||record.description||entry?.source?.capabilities?.[0]?.summary;
  const runtime=identityLoading?'':conversationRuntimeControl('overview',!!panel.busy,placeholder('runtime','composer.runtimeLoading'));
  return shell({title:name||conversationSessionTitle(panel),identityLoading,
   environment:[{name:name||'当前员工',tools:binding.environment_tools??entry?.source?.environment_tools}],
   avatar:`<span class="overview-avatar">${workerAvatarMarkup({...record,...binding})}</span>`,description,runtime,
   examples:chips?`<div class="overview-examples">${chips}</div>`:'',versionLoading:directoryLoading,
   configuration:employeeConfiguration(panel,entry),pending:conversationQuestionDock('panel'),version,publication,
   modeControl:RunTeamsHost.assets.employeeVersionControl?.(panel,entry)||''});
 }
 window.RunTeamsAssetOverview={patchDrawer,active,employee,pipeline,employeeEligible,pendingPage,prepare,closed,takeManualMotion,trigger,toggle,section,sectionAction,loadingSection,textButton,labels,shell,employeeDrawer,back,backMarkup,openKnowledge,toggleKnowledge,retryKnowledge,refreshKnowledgeAfterTurn,uploadKnowledge,exportKnowledge,openDelivery,openRow,toggleActivity,openEmployeeActivity,toggleDeliveries,load};
})();
