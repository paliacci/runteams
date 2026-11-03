/* Employee schedules use the current directory and device work execution. */
(()=>{
 'use strict';
 let state=null,form=null;
 const base='/api/device/employee-schedules';
 const pipelineOwner=()=>S.surface==='source-pipeline'?window.RunTeamsSourcePipelines?.current():null;
 const endpoint=s=>s?.pipeline?'/api/device/pipeline-schedules':base;
 const refKey=ref=>ref?.pipeline_source?RunTeamsSourcePipelines.referenceKey(ref):RunTeamsEmployeeDirectory.referenceKey(ref);
 const scope=()=>`${_workspaceBusinessGeneration}:${workspaceAccountCacheToken()}`;
 const operationKey=target=>'runteams.employee-schedule-operation:'+workspaceDeviceStorageScope()+':'+target.key;
 function eligible(panel=S.conversationPanel){
  if(pipelineOwner()?.data&&!RunTeamsHost.session.workspace(S)&&(S.localLibrary||RunTeamsHost.session.ready(S)))return true;
  const reference=window.RunTeamsEmployeeDirectory?.panelReference(panel);
  if(S.localLibrary&&reference&&(reference.schema!=='runteams.local-employee-reference/1'||reference.storage_kind!=='local'||reference.library_id!==S.localLibrary.library_id))return false;
  return !!panel&&!RunTeamsHost.session.workspace(S)&&!panel.loading&&!panel.error&&!panel.debug_preview&&!!(S.localLibrary||RunTeamsHost.session.ready(S))&&!!window.RunTeamsEmployeeDirectory&&(RunTeamsEmployeeDirectory.employeePanel(panel)||panel.kind==='employee_design'&&!!panel.context?.creator_local_source_id);
 }
 function identity(panel=S.conversationPanel){const owner=pipelineOwner();if(owner)return JSON.stringify(['pipeline',owner.reference]);const c=panel?.context||{};return JSON.stringify([panel?.id,panel?.kind,RunTeamsEmployeeDirectory.referenceKey(RunTeamsEmployeeDirectory.panelReference(panel)),c.creator_local_source_id,c.creator_employee_source]);}
 function target(panel=S.conversationPanel){
  const owner=pipelineOwner();if(owner?.data&&eligible(panel))return {pipeline:true,owner,key:'pipeline:'+RunTeamsSourcePipelines.key(owner.reference),reference:owner.reference,source:null,chat:null};
  if(!eligible(panel))return null;
  const directory=RunTeamsEmployeeDirectory,row=directory.forPanel(panel);
  if(row)return row.work?.history_only?null:{key:row.key,reference:row.source?.reference||row.reference,source:row.source||null,chat:panel.id};
  const reference=directory.panelReference(panel);
  // A verified local binding already carries the original source identity.
  // This key is the existing receipt namespace, never execution authority.
  if(reference?.schema==='runteams.local-employee-reference/1'&&directory.referenceKey(reference))return {key:'source:'+reference.source_id+':'+reference.employee_source,reference,source:null,chat:panel.id};
  return null;
 }
 function current(){const panel=S.conversationPanel;if(state?.pipeline)return state.scope===scope()&&pipelineOwner()===state.owner&&S.sel?.type==='source-pipeline'&&S.sel.id==='automation'?state:null;return state&&eligible(panel)&&state.scope===scope()&&state.chat===panel.id&&state.identity===identity(panel)&&S.sel?.type==='employee-automation'&&S.sel.id===state.key?state:null;}
 function controls(panel){if(!eligible(panel))return '';return `<button type="button" class="conversation-header-action creator-work-trigger employee-automation-trigger${current()?' on':''}" aria-label="自动化" aria-expanded="${!!current()}" aria-pressed="${!!current()}" onclick="RunTeamsEmployeeAutomation.toggle()">${ICON('repeat')}<span>自动化</span></button>`;}
 const valid=s=>state===s&&eligible()&&s.scope===scope()&&(s.pipeline?pipelineOwner()===s.owner:s.chat===S.conversationPanel.id&&s.identity===identity());
 const paint=()=>render();
 const pendingKey=s=>s.storageKey;
 function pending(s){if(!s.storageKey)return null;try{return JSON.parse(RunTeamsWorkState.getItem(pendingKey(s))||'null');}catch(_){return null;}}
 function clearPending(s,id){if(pending(s)?.operation_id===id)RunTeamsWorkState.removeItem(pendingKey(s));}
 async function toggle(){
  const panel=S.conversationPanel;if(!eligible(panel))return;
  if(current()){closeDetailWorkspace();return;}
  const t=target(),owner=identity(panel);
  if(!state||state.scope!==scope()||state.identity!==owner||t?.pipeline&&state.owner!==t.owner)state={...(t||{key:'employee-automation:'+panel.id,reference:null,source:null,chat:panel.id}),identity:owner,scope:scope(),storageKey:t?operationKey(t):null,items:[],skills:[],loading:false,error:'',busy:false,hasRead:false,createAvailable:false};
  selectDetailWorkspace(state.pipeline?{type:'source-pipeline',id:'automation'}:{type:'employee-automation',id:state.key});await refresh();
 }
 async function refresh(options={}){
  const s=current();if(!s||s.loading||s.refreshing)return;
  s.refreshing=true;if(!options.silent){s.loading=true;s.error='';}paint();
  try{
   if(!RunTeamsWorkState.ready)await RunTeamsWorkState.connect();if(!valid(s))return;
   let t=target();
   if(!s.pipeline&&!t&&!RunTeamsEmployeeDirectory.forPanel(S.conversationPanel)){await RunTeamsEmployeeDirectory.refresh();if(current()!==s)return;t=target();}
   if(!t?.reference){s.unavailable='这名员工尚未准备就绪，请核对员工资源。';s.createAvailable=false;return;}
   if(s.reference&&refKey(s.reference)!==refKey(t.reference))throw Error('员工来源已变化，请关闭面板后重新打开。');
   s.reference=t.reference;s.source=t.source;s.storageKey||=operationKey(t);s.unavailable='';
   const out=await api(endpoint(s)+'?reference='+encodeURIComponent(JSON.stringify(s.reference)),undefined,undefined,{readCurrent:true});if(!valid(s))return;if(out.error)throw Error(out.error);if(!Array.isArray(out.items)||!Array.isArray(out.skills)||refKey(out.reference)!==refKey(s.reference))throw Error('自动化读取结果无效。');s.items=out.items;s.skills=out.skills;if(s.pipeline){s.positions=out.positions||[];s.startColumn=out.start_column_key;s.pipelineStatus=out.pipeline_status;}s.reference=out.reference;s.unavailable=out.unavailable||'';s.hasRead=true;s.createAvailable=!s.unavailable;
  }
  catch(e){if(valid(s)){s.error=e.message||'自动化暂时无法读取。';s.createAvailable=false;}}
  finally{s.loading=false;s.refreshing=false;if(valid(s))paint();}
 }

 function row(item,s){
  const paused=!item.enabled,latest=item.runs?.[0],disabled=s.busy||!!pending(s);
  const runStatus={queued:'等待执行',running:'正在执行',waiting:'正在执行',completed:'已完成',failed:'运行失败',blocked:'需要处理',canceled:'已停止',cancelled:'已停止',interrupted:'需要核对',skipped:'已跳过'}[latest?.status];
  const status=(paused?'已暂停':'已启用')+(runStatus?'，最近运行：'+runStatus:'');
  const tone=paused?'paused':({running:'running',waiting:'running',blocked:'attention',interrupted:'attention',failed:'failed'}[latest?.status]||'enabled');
  return `<div class="employee-automation-row" data-schedule-state="${tone}" data-schedule-id="${Number(item.id)}" onclick="RunTeamsEmployeeAutomation.records(${Number(item.id)})"><button type="button" class="employee-automation-icon-action employee-automation-toggle" title="${paused?'启用计划':'暂停计划'}；${esc(status)}" aria-label="${esc((paused?'启用':'暂停')+item.name)}，${esc(status)}" onclick="event.stopPropagation();RunTeamsEmployeeAutomation.action(${Number(item.id)},'${paused?'resume':'pause'}')" ${disabled?'disabled':''}>${ICON(paused?'play':'pause')}</button><button type="button" class="employee-automation-open" aria-label="${esc(item.name)}的运行记录，${esc(status)}" title="${esc(status)}"><span class="employee-automation-copy"><b title="${esc(item.name)}">${esc(item.name)}</b><small>${esc(automationScheduleLabel(item))}</small></span></button><button type="button" class="employee-automation-icon-action" aria-label="${esc(item.name)}的更多操作" aria-haspopup="menu" onclick="event.stopPropagation();RunTeamsEmployeeAutomation.menu(event,${Number(item.id)})" ${disabled?'disabled':''}>${ICON('more')}</button></div>`;
 }

 function drawer(){
  const s=current();if(!s)return '';
  const heading={toolbar:RunTeamsEmployeeDrawerHeader.markup('automation'),intro:`<section class="workspace-detail-head detail-drawer-intro">${detailDrawerHeading('自动化',s.pipeline?'按计划创建流水线工作。':'让员工按计划处理工作。')}</section>`};
  const content=s.loading&&!s.hasRead?RunTeamsSkeletons.region('employee-automations',3):s.error?RunTeamsLoadFailure.markup({variant:'local',title:'自动化暂时无法读取',error:s.error,retry:'RunTeamsEmployeeAutomation.refresh()'})+(s.items.length?`<div class="employee-automation-list">${s.items.map(item=>row(item,s)).join('')}</div>`:''):s.unavailable?RunTeamsEmptyStates.markup('automations',{title:'自动化尚未就绪',description:s.unavailable}):s.items.length?`<div class="employee-automation-list" aria-busy="${s.busy}">${s.items.map(item=>row(item,s)).join('')}</div>`:RunTeamsEmptyStates.markup('automations');
  const recovery=pending(s)&&!s.submitting?'<div class="employee-automation-recovery" role="status">上次操作结果待核对。<button type="button" class="btn" onclick="RunTeamsEmployeeAutomation.recover()">核对原操作</button><button type="button" class="btn ghost" onclick="RunTeamsEmployeeAutomation.cancelPending()">取消这次操作</button></div>':'';
  return detailDrawerShell({className:'employee-automation-drawer',header:heading,fixedIntroClass:'detail-drawer-summary',body:recovery+(s.pipeline&&s.hasRead&&s.pipelineStatus!=='running'?'<p class="help">流水线已暂停，自动化不会开始新工作。</p>':'')+content,bodyClass:'employee-automation-body',attrs:s.pipeline?'aria-label="流水线自动化"':'aria-label="员工自动化"'});
 }
 function decorateHeader(){
  const s=current();if(!s)return;
  const reading=!!(s.loading||s.refreshing),blocked=!!(s.busy||s.error||s.unavailable||!s.reference||pending(s)),disabled=reading||blocked;
  const readPending=reading&&s.createAvailable===true&&!blocked;
  RunTeamsEmployeeDrawerHeader.mount('automation',s,{onCollapse:closeDetailWorkspace,extras:{text:'',actions:s.hasRead?[{id:'new',label:'新建',icon:'plus',platformId:'employee_automation_add',readPending,disabled,onPress:()=>{if(current()===s)edit();}}]:[]}});
 }
 async function command(action,item=null,value=null){
  const s=current(),t=target();if(!s||!s.reference||!s.storageKey||!t?.reference||refKey(t.reference)!==refKey(s.reference)||s.busy||pending(s))return false;
  const request={operation_id:crypto.randomUUID(),action,reference:s.reference,id:item?.id??null,expected_revision:item?.revision??null,value};
  try{RunTeamsWorkState.setItem(pendingKey(s),JSON.stringify({operation_id:request.operation_id}));}catch(_){throw Error('无法保存操作回执，请检查本机存储后重试。');}
  s.busy=true;s.submitting=true;s.commandError='';paint();
  try{if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const out=await api(endpoint(s),'POST',request);if(out.error){if(out.state!=='unknown')clearPending(s,request.operation_id);throw Error(out.error);}if(out.operation_id!==request.operation_id)throw Error('操作回执需要核对。');clearPending(s,request.operation_id);if(valid(s)){s.busy=false;await refresh();}return true;}
  catch(e){if(valid(s)){s.commandError=e.message;if(!(form?.owner===s&&document.getElementById('employee_schedule_error')))toast(pending(s)?'操作结果待核对，请勿重复提交。':e.message,'err');}return false;}
  finally{s.submitting=false;s.busy=false;if(valid(s))paint();}
 }
 async function recover(){const s=current(),p=s&&pending(s);if(!p||s.busy)return;s.busy=true;paint();try{const out=await api(endpoint(s)+'/operations/'+encodeURIComponent(p.operation_id),undefined,undefined,{readCurrent:true});if(!valid(s))return;if(out.state==='failed')clearPending(s,p.operation_id);if(out.error)throw Error(out.error);if(['committed','abandoned'].includes(out.state)){clearPending(s,p.operation_id);s.busy=false;await refresh();}else toast('原操作尚未确认，请稍后再次核对。','info');}catch(e){if(valid(s))toast(e.message,'err');}finally{if(valid(s)){s.busy=false;paint();}}}
 async function cancelPending(){const s=current(),p=s&&pending(s);if(!p||s.busy)return;return confirmModal('取消这次操作？','只取消尚未完成的设置，已保存的结果会保留。',async()=>{if(!valid(s))return;s.busy=true;paint();try{const out=await api(endpoint(s)+'/operations/'+encodeURIComponent(p.operation_id)+'/abandon','POST',{});if(out.error)throw Error(out.error);if(['committed','abandoned'].includes(out.state))clearPending(s,p.operation_id);if(valid(s)){s.busy=false;await refresh();}}catch(e){if(valid(s))toast(e.message,'err');}finally{if(valid(s)){s.busy=false;paint();}}});}
 const find=id=>current()?.items.find(r=>r.id===Number(id));
 async function action(id,action){const item=find(id);if(item)await command(action,item);}
 function menu(event,id){const owner=current(),item=find(id);if(!item)return;const own=fn=>()=>current()===owner&&fn();openMenu(event.currentTarget,[{label:'编辑',icon:'edit',fn:own(()=>edit(id))},{label:'立即运行一次',icon:'play',disabled:!!owner.pipeline&&owner.pipelineStatus!=='running',fn:own(()=>{if(!owner.pipeline||owner.pipelineStatus==='running')action(id,'run');})},{label:'运行记录',icon:'history',fn:own(()=>records(id))},{label:'删除自动化',icon:'trash',danger:true,fn:own(()=>confirmModal('删除这项自动化？','之后不会再按此计划创建工作，正在进行的工作与已有记录会保留。',()=>current()===owner&&action(id,'delete'),true))}],{variant:'workerAction'});}
 async function records(id){const owner=current(),dialogBefore=document.getElementById('modalHost');await refresh({silent:true});if(current()!==owner||document.getElementById('modalHost')!==dialogBefore)return;const item=find(id);if(!item)return;openDialog({title:item.name+'的运行记录',body:item.runs?.length?`<div class="employee-automation-records">${item.runs.map(r=>`<div><b>${esc(({queued:'等待执行',running:'正在执行',waiting:'正在执行',completed:'已完成',failed:'失败',blocked:'需要处理',interrupted:'需要核对',skipped:'已跳过',canceled:'已停止',cancelled:'已停止'})[r.status]||r.status)}</b><span>${esc(r.scheduled_for.startsWith('manual:')?'手动运行':automationTime(r.scheduled_for))}</span>${r.reason?`<p>${esc(r.reason)}</p>`:''}${r.workflow_id?`<button class="btn" onclick="closeModal();${owner.pipeline?`RunTeamsSourcePipelines.openWork(${Number(r.workflow_id)})`:`openCoreWorkflow(${Number(r.workflow_id)},{storageScope:'device'})`}">查看工作记录</button>`:''}${r.chat_id&&!owner.pipeline?`<button class="btn" onclick="closeModal();openConversationSession(${Number(r.chat_id)},'general')">查看工作对话</button>`:''}${r.status==='interrupted'?`<button class="btn" onclick="closeModal();RunTeamsEmployeeAutomation.resolve(${Number(item.id)})">按未完成结束本次记录</button>`:''}</div>`).join('')}</div>`:'<p>还没有运行记录。</p>',footer:'<button class="btn" onclick="closeModal()">关闭</button>'});}
 function resolve(id){const owner=current();if(!owner)return;confirmModal('已核对原工作？','结束这次记录后，后续计划可以继续运行。原工作不会重做或撤销，请先确认原工作与外部操作结果。',()=>current()===owner&&action(id,'resolve'));}
 function field(name){return document.getElementById('employee_schedule_'+name);}
 function formCurrent(f=form){return !!f&&form===f&&valid(f.owner)&&document.getElementById('modalHost')===f.element;}
 function edit(id=0){
  const s=current(),item=id?find(id):null;if(!s||!s.hasRead||s.loading||s.refreshing||s.busy||s.error||s.unavailable||pending(s)||!s.reference||id&&!item)return;
  const schedule=item?.schedule||{},kind=item?.schedule_kind||'daily',payload=item?.payload||{};
  const objective=payload.original_objective??payload.objective??'';
  const parameters=!s.pipeline&&payload.schema==='runteams.task-input/v2'&&Object.keys(payload.parameters||{}).length?'\n\n任务资料：\n'+JSON.stringify(payload.parameters,null,2):'';
  const f={owner:s,item,scheduleSelected:!!item,scheduleExpanded:false,hasSchedule:!!item,enabled:item?item.enabled:true,saving:false,position:payload.start_column_key||s.startColumn,parameterDrafts:{[payload.start_column_key||s.startColumn]:payload.parameters||{}}};form=f;
  const dialog=openDialog({className:'automation-editor employee-schedule-editor',title:item?'编辑自动化':'新建自动化',
   headerActions:item&&!item.enabled?'<button type="button" class="x" aria-label="计划选项" onclick="RunTeamsEmployeeAutomation.editOptions(event)">'+ICON('more')+'</button>':'',
   body:`<div class="employee-schedule-content"><div class="employee-schedule-task"><textarea class="ta" id="employee_schedule_objective" maxlength="20000" aria-label="任务说明" placeholder="${s.pipeline?'想让流水线定期完成什么工作？':'想让员工定期做什么？&#10;例如：每周五整理项目进展，生成一份工作回顾。'}" oninput="RunTeamsEmployeeAutomation.taskChanged()">${esc(objective+parameters)}</textarea>${s.pipeline?'':`<label class="employee-schedule-original" title="勾选后按原文创建；未勾选时，点击创建会自动润色。"><input type="checkbox" id="employee_schedule_original" ${item&&payload.use_original!==false?'checked':''}><span>原文</span></label>`}</div>${s.pipeline?`<div class="field"><label for="employee_schedule_position">开始岗位</label><select class="inp" id="employee_schedule_position" onchange="RunTeamsEmployeeAutomation.startChanged()">${s.positions.map(p=>`<option value="${esc(p.key)}" ${p.key===f.position?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div><div id="employee_schedule_inputs"></div>`:''}
   <div class="employee-schedule-timing"><button type="button" class="employee-schedule-summary" id="employee_schedule_summary" aria-expanded="false" aria-controls="employee_schedule_details" onclick="RunTeamsEmployeeAutomation.toggleSchedule()">${ICON('clock')}<span id="employee_schedule_label">选择执行时间</span><small><span>电脑需保持在线</span></small>${ICON('chev')}</button>
   <div id="employee_schedule_details" class="employee-schedule-details" hidden inert aria-hidden="true"><div class="employee-schedule-details-inner"><div class="employee-schedule-fields"><label class="field"><span>重复</span>${csel('employee_schedule_kind',[{value:'daily',label:'每天'},{value:'weekly',label:'每周'},{value:'interval',label:'按周期'}],kind,()=>{if(formCurrent(f)&&!f.saving)scheduleChanged();},{menuVariant:'settingsSelect'})}</label><label class="field" id="employee_schedule_time_field"><span>时间</span><input class="inp" id="employee_schedule_time" type="text" placeholder="HH:mm" maxlength="5" autocomplete="off" spellcheck="false" value="${esc(schedule.time||'09:00')}" oninput="RunTeamsEmployeeAutomation.scheduleChanged()"></label><label class="field" id="employee_schedule_interval_field"><span>间隔（分钟）</span><input class="inp" id="employee_schedule_interval" type="number" min="1" max="43200" value="${Math.max(1,(item?.interval_sec||3600)/60)}" oninput="RunTeamsEmployeeAutomation.scheduleChanged()"></label></div>
   <div id="employee_schedule_days" class="employee-schedule-days" hidden><span>星期</span><div>${['一','二','三','四','五','六','日'].map((label,day)=>`<label><input type="checkbox" value="${day}" ${(schedule.weekdays||[]).includes(day)?'checked':''} onchange="RunTeamsEmployeeAutomation.scheduleChanged()"><span>${label}</span></label>`).join('')}</div></div></div></div></div>
   <label class="employee-schedule-name">${ICON('tag')}<input class="inp employee-schedule-name-input" type="text" id="employee_schedule_name" aria-label="名称" maxlength="120" value="${esc(item?.name||'')}" placeholder="自动生成" autocomplete="off"></label><p id="employee_schedule_error" role="alert" class="account-team-error" hidden></p></div>`,
   footer:`<span class="employee-schedule-paused" id="employee_schedule_paused">${item&&!item.enabled?'已暂停':''}</span><div class="grow"></div><button class="btn ghost" id="employee_schedule_close" onclick="closeModal()">取消</button><button class="btn pri" id="employee_schedule_save" onclick="RunTeamsEmployeeAutomation.save()">${item?'保存':'创建'}</button>`});
  f.element=dialog;scheduleChanged();taskChanged();if(s.pipeline)void startChanged(true);
 }
 function errorText(message){const node=field('error');if(node){node.textContent=message;node.hidden=!message;}}
 function automaticName(objective){return [...String(objective||'').trim().split(/[\r\n，。！？；,:!?;]/)[0]].slice(0,18).join('');}
 function taskChanged(){const f=form;if(!f||f.saving)return;const objective=field('objective')?.value||'';if(field('save'))field('save').disabled=!objective.trim()||!f.hasSchedule||f.owner.pipeline&&!f.inputContract;errorText('');}
 function scheduleKind(){return field('kind')?.dataset.value;}
 function scheduleChanged(){
  const f=form,kind=scheduleKind();if(!f||f.saving)return;
  field('time_field').hidden=kind==='interval';field('interval_field').hidden=kind!=='interval';field('days').hidden=kind!=='weekly';
  if(f.scheduleSelected){
   try{scheduleValue();f.hasSchedule=true;errorText('');const days=[...document.querySelectorAll('#employee_schedule_days input:checked')].map(n=>'一二三四五六日'[Number(n.value)]);field('label').textContent=kind==='interval'?`每隔 ${field('interval').value} 分钟`:kind==='weekly'?`每周${days.join('、')} ${field('time').value}`:`每天 ${field('time').value}`;}
   catch(e){f.hasSchedule=false;field('label').textContent='设置执行时间';}
   if(field('save'))field('save').disabled=!f.hasSchedule||!field('objective').value.trim()||f.owner.pipeline&&!f.inputContract;
  }
 }
 function toggleSchedule(){
  const f=form;if(!formCurrent(f)||f.saving)return;
  const node=field('details'),expanded=!f.scheduleExpanded,start=node.hidden?0:node.getBoundingClientRect?.().height||0;
  f.detailsAnimation?.cancel();f.scheduleExpanded=expanded;f.scheduleSelected=true;
  field('summary').setAttribute('aria-expanded',String(expanded));node.setAttribute('aria-hidden',String(!expanded));node.inert=!expanded;node.hidden=false;
  scheduleChanged();
  const finish=()=>{if(formCurrent(f)&&f.scheduleExpanded===expanded)node.hidden=!expanded;};
  if(!node.animate||window.matchMedia?.('(prefers-reduced-motion: reduce)').matches){finish();return;}
  const style=getComputedStyle(node),duration=style.getPropertyValue('--dur-2').trim(),ms=duration.endsWith('ms')?parseFloat(duration):parseFloat(duration)*1000;
  const animation=node.animate([{height:start+'px',opacity:expanded?0:1},{height:(expanded?node.scrollHeight:0)+'px',opacity:expanded?1:0}],{duration:Number.isFinite(ms)?ms:180,easing:style.getPropertyValue('--ease').trim()||'ease',fill:'none'});
  f.detailsAnimation=animation;animation.onfinish=()=>{if(f.detailsAnimation===animation){f.detailsAnimation=null;finish();}};
 }
 function scheduleValue(){
  const kind=scheduleKind(),days=[...document.querySelectorAll('#employee_schedule_days input:checked')].map(n=>Number(n.value)),minutes=Number(field('interval').value),time=field('time').value;
  if(kind==='weekly'&&!days.length)throw Error('请选择至少一天。');
  if(kind!=='interval'&&!/^([01]\d|2[0-3]):[0-5]\d$/.test(time))throw Error('请输入有效时间，例如 09:00。');
  if(!Number.isInteger(minutes)||minutes<1||minutes>43200)throw Error('请填写有效的分钟间隔。');
  return {schedule_kind:kind,interval_sec:minutes*60,schedule:{time,weekdays:days,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone}};
 }
 function editOptions(event){const f=form;if(!formCurrent(f)||f.saving||f.enabled)return;openMenu(event.currentTarget,[{label:'启用计划',icon:'play',fn:()=>{if(formCurrent(f)&&!f.saving){f.enabled=true;field('paused').textContent='';}}}]);}
 function freezeForm(f,busy,label){if(!formCurrent(f))return;f.element.querySelectorAll('.employee-schedule-content input,.employee-schedule-content textarea,.employee-schedule-content select,.employee-schedule-content button').forEach(n=>n.disabled=busy);field('save').disabled=busy||!!pending(f.owner)||!f.hasSchedule||!field('objective').value.trim()||f.owner.pipeline&&!f.inputContract;field('save').textContent=busy?label:f.item?'保存':'创建';field('close').textContent=busy?'关闭':'取消';}
 async function save(){
  const f=form;if(!formCurrent(f)||f.saving||f.owner.busy||pending(f.owner))return;
  try{
   const objective=field('objective').value,name=field('name').value.trim()||automaticName(objective);
   if(!objective.trim())throw Error('先写下要完成的工作。');if(!f.scheduleSelected)throw Error('请选择执行时间。');
   const value={name,objective,enabled:f.enabled,...scheduleValue(),...(f.owner.pipeline?{start_column_key:f.position,parameters:readCoreTaskParameters(field('inputs'))}:{use_original:field('original').checked})};
   if(f.owner.pipeline&&!f.inputContract)throw Error('请先核对开始岗位的任务输入。');
   f.saving=true;errorText('');freezeForm(f,true,f.owner.pipeline?'保存中…':value.use_original?'创建中…':'润色中…');
   if(await command('save',f.item,value)){if(formCurrent(f)){form=null;closeModal();}}
   else if(formCurrent(f))errorText(pending(f.owner)?'创建结果待核对。关闭后可核对原操作，请勿重复提交。':f.owner.commandError||'未能保存，请检查设置后重试。');
  }catch(e){if(formCurrent(f))errorText(e.message);}
  finally{f.saving=false;freezeForm(f,false);}
 }

 function pipelineInputs(f){
  if(f.inputLoading)return RunTeamsSkeletons.region('parameters');
  if(f.inputError)return RunTeamsLoadFailure.markup({variant:'local',title:'任务输入暂时无法读取',error:f.inputError,retry:'RunTeamsEmployeeAutomation.startChanged(true)'});
  return coreTaskParameterFields(coreWorkflowFrozenParameters(f.inputContract),f.parameterDrafts[f.position]||{},'pipeline_schedule')||'<p class="help">这项工作不需要额外任务资料。</p>';
 }
 async function startChanged(initial=false){
  const f=form;if(!formCurrent(f)||!f.owner.pipeline||f.saving)return;
  const position=field('position').value;
  if(!initial&&f.inputContract){try{f.parameterDrafts[f.position]=readCoreTaskParameters(field('inputs'));}catch(e){field('position').value=f.position;errorText(e.message);return;}}
  f.position=position;f.inputContract=null;f.inputLoading=true;f.inputError='';const ticket=(f.contractRead||0)+1;f.contractRead=ticket;taskChanged();
  field('inputs').innerHTML=pipelineInputs(f);
  try{const result=await RunTeamsSourcePipelines.request('contract',{reference:f.owner.reference,start_column_key:position});
   if(!formCurrent(f)||f.contractRead!==ticket)return;
   f.inputLoading=false;f.inputContract=result;field('inputs').innerHTML=pipelineInputs(f);errorText('');taskChanged();
  }catch(e){if(formCurrent(f)&&f.contractRead===ticket){f.inputLoading=false;f.inputError=e.message;field('inputs').innerHTML=pipelineInputs(f);errorText(e.message);}}
 }

 function settingsOpen(panel=S.conversationPanel){
  const configuration=window.RunTeamsEmployeeConfiguration?.current();
  if(configuration&&configuration.entry.key===(window.RunTeamsEmployeeConfiguration?.workTarget?.(panel)||target(panel))?.key)return true;
  const t=target(panel),s=typeof RunTeamsCreatorAuthor==='undefined'?null:RunTeamsCreatorAuthor.current();
  return !!s&&!!t?.source&&(s.session===panel.id||(s.sourceId===t.source.id||s.localDraft?.id===t.source.id)&&(!s.employeeSource||s.employeeSource===t.source.path));
 }
 function settingsControl(panel=S.conversationPanel){const selected=settingsOpen(panel);return `<button type="button" class="conversation-header-action creator-work-trigger employee-settings-trigger${selected?' on':''}" aria-label="设置" aria-expanded="${selected}" aria-pressed="${selected}" onclick="RunTeamsEmployeeAutomation.sourceSettings()">${ICON('settings')}<span>设置</span></button>`;}
 async function sourceSettings(){
  const panel=S.conversationPanel;if(panel?.context?.pipeline_work){toast('请在流水线设置中配置对应岗位。','info');return;}
  const work=window.RunTeamsEmployeeConfiguration?.workTarget?.(panel),t=target();if(!t&&!work){toast('员工暂不可用。','info');return;}
  if(settingsOpen(panel))return window.RunTeamsEmployeeConfiguration?.current()?RunTeamsEmployeeConfiguration.close():RunTeamsCreatorAuthor.close();

  return work?RunTeamsEmployeeConfiguration.open(work):RunTeamsEmployeeDirectory.settings(t.key);
 }
 window.RunTeamsEmployeeAutomation=Object.freeze({decorateHeader,settingsOpen,settingsControl,sourceSettings,current,controls,toggle,refresh,drawer,edit,startChanged,scheduleChanged,taskChanged,toggleSchedule,editOptions,save,action,menu,records,recover,resolve,cancelPending});
 if(typeof setInterval==='function')setInterval(()=>{const s=current();if(s&&!s.unavailable&&!s.busy&&!pending(s)&&!document.querySelector('#modalHost'))void refresh({silent:true});},10000);
 window.addEventListener('runteams:business-scope-changed',()=>{state=null;form=null;});
})();
