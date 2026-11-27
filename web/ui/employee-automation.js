/* Employee schedules use the current directory and device work execution. */
(()=>{
 'use strict';
 let state=null,form=null;
 const base='/api/device/employee-schedules';
 const templateEndpoint='/api/device/asset-automation-templates';
 const pipelineOwner=()=>S.surface==='source-pipeline'?window.RunTeamsSourcePipelines?.current():null;
 const endpoint=s=>s?.pipeline?'/api/device/pipeline-schedules':base;
 const refKey=ref=>ref?.pipeline_source?RunTeamsSourcePipelines.referenceKey(ref):RunTeamsEmployeeDirectory.referenceKey(ref);
 const scope=()=>`${_workspaceBusinessGeneration}:${workspaceAccountCacheToken()}`;
 const operationKey=target=>'runteams.employee-schedule-operation:'+workspaceDeviceStorageScope()+':'+target.key;
 function panelReference(panel){
  const bound=window.RunTeamsEmployeeDirectory?.panelReference(panel);
  if(bound||panel?.kind!=='employee_design'||panel.storage_scope!=='device')return bound;
  const ref=panel.authoringEmployeeReference,context=panel.context;
  const deviceScope=S.localLibrary?.cache_scope||RunTeamsHost.session.deviceScope(S);
  if(ref?.schema==='runteams.local-employee-reference/1'&&deviceScope&&context?.creator_local_scope===deviceScope&&
     ref.source_id===context.creator_local_source_id&&ref.employee_source===context.creator_employee_source)return ref;
  return null;
 }
 function eligible(panel=S.conversationPanel){
  if(pipelineOwner()?.data&&!RunTeamsHost.session.workspace(S)&&(S.localLibrary||RunTeamsHost.session.ready(S)))return true;
  const reference=panelReference(panel);
  if(S.localLibrary&&reference&&(reference.schema!=='runteams.local-employee-reference/1'||reference.storage_kind!=='local'||reference.library_id!==S.localLibrary.library_id))return false;
  return !!panel&&!RunTeamsHost.session.workspace(S)&&!panel.loading&&!panel.error&&!panel.debug_preview&&!!(S.localLibrary||RunTeamsHost.session.ready(S))&&!!window.RunTeamsEmployeeDirectory&&(RunTeamsEmployeeDirectory.employeePanel(panel)||panel.kind==='employee_design'&&!!panel.context?.creator_local_source_id);
 }
 function identity(panel=S.conversationPanel){const owner=pipelineOwner();if(owner)return JSON.stringify(['pipeline',owner.reference]);const c=panel?.context||{};return JSON.stringify([panel?.id,panel?.kind,RunTeamsEmployeeDirectory.referenceKey(panelReference(panel)),c.creator_local_source_id,c.creator_employee_source]);}
 function target(panel=S.conversationPanel){
  const owner=pipelineOwner();if(owner?.data&&eligible(panel))return {pipeline:true,owner,key:'pipeline:'+RunTeamsSourcePipelines.key(owner.reference),reference:owner.reference,source:null,chat:null};
  if(!eligible(panel))return null;
  const directory=RunTeamsEmployeeDirectory,row=directory.forPanel(panel);
  if(row)return row.work?.history_only?null:{key:row.key,reference:row.source?.reference||row.reference,source:row.source||null,chat:panel.id};
  const reference=panelReference(panel);
  // A verified local binding already carries the original source identity.
  // This key is the existing receipt namespace, never execution authority.
  if(reference?.schema==='runteams.local-employee-reference/1'&&directory.referenceKey(reference))return {key:'source:'+reference.source_id+':'+reference.employee_source,reference,source:null,chat:panel.id};
  return null;
 }
 function ownsTarget(s){
  if(!s||s.scope!==scope())return false;
  const owner=pipelineOwner(),panel=S.conversationPanel;
  if(s.pipeline)return !!owner&&owner===s.owner;
  return !owner&&!!panel&&s.chat===panel.id&&s.identity===identity(panel);
 }
 function current(){
  return ownsTarget(state)&&eligible()&&RunTeamsAssetOverview.active()?state:null;
 }
 const valid=s=>state===s&&ownsTarget(s)&&eligible();
 const drawerSelector='.asset-overview';
 const scheduleMenuOpen=()=>!!document.querySelector(drawerSelector+' [data-schedule-control="menu"][aria-expanded="true"]');
 function paint(){
  const active=document.activeElement;
  const row=active?.closest?.(drawerSelector+' [data-schedule-id]');
  const control=active?.dataset?.scheduleControl,template=active?.dataset?.templateReview;
  const owner=current();
  render();
  if(!owner||active?.isConnected||current()!==owner||document.activeElement!==document.body)return;
  if(template!==undefined){templateButton(template)?.focus({preventScroll:true});return;}
  if(!row||!control)return;
  const drawer=document.querySelector(drawerSelector);
  const replacement=drawer?.querySelector(`[data-schedule-id="${row.dataset.scheduleId}"]`);
  const target=replacement?.querySelector(`[data-schedule-control="${control}"]:not(:disabled)`)
   ||replacement?.querySelector('.employee-automation-open')
   ||document.querySelector('.asset-overview-trigger');
  target?.focus({preventScroll:true});
 }
 const pendingKey=s=>s.storageKey;
 function pending(s){if(!s.storageKey)return null;try{return JSON.parse(RunTeamsWorkState.getItem(pendingKey(s))||'null');}catch(_){return null;}}
 function clearPending(s,id){if(pending(s)?.operation_id===id)RunTeamsWorkState.removeItem(pendingKey(s));}
 function prepare(panel=S.conversationPanel){
  const t=target(),owner=identity(panel);
  if(!state||state.scope!==scope()||state.identity!==owner||t?.pipeline&&state.owner!==t.owner)state={...(t||{key:'employee-automation:'+panel.id,reference:null,source:null,chat:panel.id}),identity:owner,scope:scope(),storageKey:t?operationKey(t):null,items:[],skills:[],loading:false,error:'',busy:false,hasRead:false};
  return state;
 }
 function overviewSection(){
  if(!eligible())return '';
  const s=prepare(),selection=S.sel;
  if(s.overviewSelection!==selection){s.overviewSelection=selection;queueMicrotask(()=>{if(current()===s&&S.sel===selection)void refresh({silent:s.hasRead});});}
  if(!s.hasRead&&!s.error&&!s.unavailable)return RunTeamsAssetOverview.loadingSection('overview-automation');
  const disabled=!s.hasRead||s.loading||s.busy||s.unavailable||s.error||!!pending(s);
  const add=RunTeamsAssetOverview.sectionAction(RunTeamsAssetOverview.labels('new','新建'),'RunTeamsEmployeeAutomation.edit()',disabled);
  return RunTeamsAssetOverview.section(copy('pipelineBoard.automation','自动化'),add,automationContent(s)+templateContent(s));
 }
 function refresh(options={}){
  const s=current();if(!s)return;
  if(s.readRequest){
   if(options.silent)return s.readRequest;
   return s.readRequest.then(()=>{if(current()===s)return refresh(options);});
  }
  s.readRequest=readSchedules(s,options).finally(()=>{s.readRequest=null;});
  return s.readRequest;
 }
 async function readSchedules(s,options){
  const defer=()=>options.background&&scheduleMenuOpen();
  if(!options.silent){s.loading=true;paint();}
  try{
   if(!RunTeamsWorkState.ready)await RunTeamsWorkState.connect();if(!valid(s))return;
   let t=target();
   if(!s.pipeline&&!t&&!RunTeamsEmployeeDirectory.forPanel(S.conversationPanel)){await RunTeamsEmployeeDirectory.refresh();if(current()!==s)return;t=target();}
   if(!t?.reference){s.error='';s.unavailable=true;return;}
   if(s.reference&&refKey(s.reference)!==refKey(t.reference))throw Error('员工来源已变化，请关闭面板后重新打开。');
   s.reference=t.reference;s.source=t.source;s.storageKey||=operationKey(t);s.unavailable='';
   const out=await api(endpoint(s)+'?reference='+encodeURIComponent(JSON.stringify(s.reference)),undefined,undefined,{readCurrent:true});if(!valid(s)||defer())return;if(out.error)throw Error(out.error);if(!Array.isArray(out.items)||!Array.isArray(out.skills)||refKey(out.reference)!==refKey(s.reference))throw Error('自动化读取结果无效。');s.items=out.items;s.skills=out.skills;s.followupTargets=out.followup_targets||[];if(s.pipeline){s.positions=out.positions||[];s.startColumn=out.start_column_key;s.pipelineStatus=out.pipeline_status;}s.reference=out.reference;s.error='';s.unavailable=!!out.unavailable;s.hasRead=true;
   if(!S.localLibrary&&!s.unavailable&&(!options.background||!s.templates))await readTemplates(s);
  }
  catch(e){if(valid(s)&&!defer()){s.error=e.message||'自动化暂时无法读取。';}}
  finally{s.loading=false;if(current()===s&&!defer())paint();}
 }

 async function readTemplates(s){
  try{
   const out=await api(templateEndpoint+'?reference='+encodeURIComponent(JSON.stringify(s.reference)),undefined,undefined,{readCurrent:true});
   if(!valid(s))return;
   if(out.error||!Array.isArray(out.templates)||!Array.isArray(out.imported_ids)||refKey(out.reference)!==refKey(s.reference))throw Error();
   s.templates=out.templates;s.templateRevision=out.revision;s.importedTemplates=new Set(out.imported_ids);s.canImportTemplates=out.can_import!==false;s.templateReadError=false;
  }catch(_){
   if(valid(s))s.templateReadError=true;
  }
 }
 const templateButton=index=>document.querySelector(`${drawerSelector} [data-template-review="${Number(index)}"]`);
 function templateContent(s){
  if(!s.templates?.length&&!s.templateReadError)return '';
  const disabled=s.templateReadError||s.loading||s.busy||s.error||s.unavailable||!!pending(s);
  const failure=s.templateReadError?RunTeamsLoadFailure.markup({variant:'local',title:'无法载入资产模板',
   titleKey:'scheduledAutomation.templatesFailed',labelKey:'employeeHistory.retry',retry:'RunTeamsEmployeeAutomation.refresh()'}):'';
  return `<div class="employee-automation-templates"><h4>${copy('scheduledAutomation.assetTemplates','资产模板')}</h4>
   ${failure}<div class="employee-automation-list">${(s.templates||[]).map((item,index)=>`<div class="employee-automation-template">
    <span class="employee-automation-copy"><b title="${esc(item.name)}">${esc(item.name)}</b><small>${esc(automationListSchedule(item))}</small></span>
    ${s.importedTemplates.has(item.id)?`<small class="employee-automation-template-added">${copy('scheduledAutomation.templateAdded','已添加')}</small>`:
     `<button type="button" class="btn ghost" data-template-review="${index}" onclick="RunTeamsEmployeeAutomation.reviewTemplate(${index})" ${disabled?'disabled':''}>${copy('scheduledAutomation.reviewTemplate','查看')}</button>`}
   </div>`).join('')}</div></div>`;
 }
 async function reviewTemplate(index){
  const s=current(),item=s?.templates?.[index];
  if(!item||s.templateReadError||s.loading||s.busy||s.error||s.unavailable||pending(s)||s.importedTemplates.has(item.id))return;
  const revision=s.templateRevision,canImport=s.canImportTemplates;
  const title=canImport?'添加自动化模板':'自动化模板',titleKey=canImport?'scheduledAutomation.addTemplateTitle':'scheduledAutomation.templateTitle';
  const hasInputs=canImport&&(s.pipeline||!!item.skill_key);
  const dialog=openDialog({
   className:'automation-editor employee-schedule-editor',title,titleKey,closeLabelKey:'employeeConsent.close',
   attrs:`role="dialog" aria-modal="true" aria-label="${title}" data-app-i18n-aria-label="${titleKey}"`,
   closeAction:`RunTeamsEmployeeAutomation.closeTemplate(${index})`,
   body:`<div class="employee-schedule-content employee-automation-template-review">
    <h4>${esc(item.name)}</h4><p class="help">${esc(automationListSchedule(item))}</p>
    <p class="employee-automation-template-objective">${esc(item.objective)}</p>
    <p class="help">${canImport?copy('scheduledAutomation.templatePaused','添加后保持暂停。核对设置后可启用。'):copy('scheduledAutomation.templateReadOnly','此资产的模板仅供查看。')}</p>
    <div data-automation-template-inputs>${hasInputs?RunTeamsSkeletons.region('parameters',undefined,'scheduledAutomation.loadingInputs'):''}</div>
    <p class="account-team-error" data-automation-template-error role="alert" hidden></p>
   </div>`,
   footer:`<button type="button" class="btn ghost" onclick="RunTeamsEmployeeAutomation.closeTemplate(${index})">${canImport?copy('scheduledAutomation.cancel','取消'):copy('employeeConsent.close','关闭')}</button>
    ${canImport?`<button type="button" class="btn pri" data-automation-template-add ${hasInputs?'disabled':''}>${copy('scheduledAutomation.addTemplate','添加')}</button>`:''}`
  });
  const ownsDialog=()=>current()===s&&document.getElementById('modalHost')===dialog;
  const inputs=dialog.querySelector('[data-automation-template-inputs]');
  const error=dialog.querySelector('[data-automation-template-error]');
  const add=dialog.querySelector('[data-automation-template-add]');
  dialog.querySelector('.modal-x')?.focus();
  if(!canImport)return;
  if(hasInputs){
   try{
    const contract=s.pipeline?await RunTeamsSourcePipelines.request('contract',{reference:s.reference,start_column_key:item.start_column_key}):
     s.skills.find(skill=>skill.key===item.skill_key);
    if(!ownsDialog())return;
    if(!contract?.input_schema)throw Error();
    inputs.innerHTML=coreTaskParameterFields(coreWorkflowFrozenParameters(contract),{},'automation_template');
    RunTeamsLocale.apply(inputs);add.disabled=false;
   }catch(_){
    if(ownsDialog()){
     inputs.replaceChildren();
     applyCopy(error,'无法读取任务信息。请重新打开模板后再试。','scheduledAutomation.templateInputsFailed');
     error.hidden=false;
    }
    return;
   }
  }
  add.onclick=async()=>{
   if(!ownsDialog()||s.busy)return;
   error.hidden=true;
   let parameters;
   try{if(hasInputs)parameters={[item.id]:readCoreTaskParameters(inputs)};}
   catch(e){applyCopy(error,e.message,e.detailKey,e.detailVars);error.hidden=false;return;}
   s.busy=true;add.disabled=true;add.setAttribute('aria-busy','true');
   try{
    const out=await api(templateEndpoint,'POST',{reference:s.reference,revision,template_ids:[item.id],...(parameters?{parameters}:{})});
    if(out.error||!Array.isArray(out.results)||!out.results.some(row=>row.template_id===item.id))throw Error(out.error||'');
    if(valid(s)){
     s.importedTemplates.add(item.id);s.busy=false;
     if(ownsDialog())closeModal();
     await refresh();
     if(current()===s&&document.activeElement===document.body)document.querySelector(`${drawerSelector} [data-schedule-id="${Number(out.results[0].id)}"] .employee-automation-open`)?.focus({preventScroll:true});
    }
   }catch(e){
    if(ownsDialog()){
     applyCopy(error,'无法添加自动化模板。请检查任务信息后重试。','scheduledAutomation.addTemplateFailed');
     error.hidden=false;
    }
   }finally{s.busy=false;add.disabled=false;add.removeAttribute('aria-busy');}
  };
 }

 function closeTemplate(index){closeModal();templateButton(index)?.focus({preventScroll:true});}

 const runStates={
  queued:['automationList.queued','等待执行'],running:['automationList.running','正在执行'],
  completed:['automationList.completed','已完成'],failed:['automationList.failed','运行失败'],
  blocked:['scheduledAutomation.needsAttention','需要处理'],interrupted:['scheduledAutomation.needsReview','需要核对'],
  skipped:['automationList.skipped','已跳过'],canceled:['workRecords.state.canceled','已停止']
 };
 function runState({status,workflow_state}){
  if(status==='blocked'){
   if(workflow_state==='needs_approval')return ['workRecords.state.needs_approval','等待审批'];
   if(workflow_state==='needs_human')return ['workRecords.state.needs_human','待人工处理'];
  }
  const key=status==='waiting'?'running':status==='cancelled'?'canceled':status;
  return Object.hasOwn(runStates,key)?runStates[key]:['workRecords.state.unknown','状态未知'];
 }
 const copy=(key,fallback)=>`<span data-app-i18n="${key}">${fallback}</span>`;
 const localError=(detailKey,message)=>Object.assign(new Error(message),{detailKey});
 function applyCopy(node,text,key,parameters){
  if(key)node.setAttribute('data-app-i18n',key);else node.removeAttribute('data-app-i18n');
  if(parameters)node.setAttribute('data-app-i18n-vars',JSON.stringify(parameters));else node.removeAttribute('data-app-i18n-vars');
  node.textContent=text;
  if(key)window.RunTeamsLocale?.apply(node);
 }
 const vars=name=>`data-app-i18n-vars="${esc(JSON.stringify({name}))}"`;
 function row(item,s){
  const id=Number(item.id),paused=!item.enabled,latest=item.runs?.[0],disabled=s.loading||s.busy||s.error||s.unavailable||!!pending(s);
  const enabled=paused?copy('automationList.paused','已暂停'):copy('automationList.enabled','已启用');
  const statusId='employee-schedule-status-'+id,timeId='employee-schedule-time-'+id,description=`aria-describedby="${statusId}"`;
  const actionKey=paused?'scheduledAutomation.enableFor':'scheduledAutomation.pauseFor';
  return `<div class="employee-automation-row rt-list-row" data-schedule-id="${id}" onclick="RunTeamsEmployeeAutomation.records(${id})">
   <span hidden id="${statusId}">${enabled}${latest?` · ${copy('scheduledAutomation.latestRun','最近运行')} ${copy(...runState(latest))}`:''}</span>
   <button type="button" class="employee-automation-icon-action employee-automation-toggle" data-schedule-control="toggle" title="${paused?'启用自动化':'暂停自动化'}" data-app-i18n-title="${paused?'automationList.enable':'automationList.pause'}" aria-label="${esc((paused?'启用':'暂停')+item.name)}" data-app-i18n-aria-label="${actionKey}" ${vars(item.name)} ${description} onclick="event.stopPropagation();RunTeamsEmployeeAutomation.action(${id},'${paused?'resume':'pause'}')" ${disabled?'disabled':''}>${ICON(paused?'play':'pause')}</button>
   <button type="button" class="employee-automation-open" data-schedule-control="history" aria-label="${esc(item.name)}的运行记录" data-app-i18n-aria-label="scheduledAutomation.historyFor" ${vars(item.name)} aria-describedby="${statusId} ${timeId}"><span class="employee-automation-copy"><b title="${esc(item.name)}">${esc(item.name)}</b><small id="${timeId}" data-employee-schedule-time>${esc(automationListSchedule(item))}</small></span></button>
   <button type="button" class="employee-automation-icon-action" data-schedule-control="menu" aria-label="${esc(item.name)}的更多操作" data-app-i18n-aria-label="automationList.moreFor" ${vars(item.name)} aria-haspopup="menu" onclick="event.stopPropagation();RunTeamsEmployeeAutomation.menu(event,${id})" ${disabled?'disabled':''}>${ICON('more')}</button>
  </div>`;
 }
 window.addEventListener('runteams:languagechange',()=>{
  if(formCurrent())scheduleSummary(form);
  const s=current();if(!s)return;
  const items=new Map(s.items.map(item=>[String(item.id),item]));
  document.querySelectorAll(drawerSelector+' [data-schedule-id]').forEach(row=>{
   const item=items.get(row.dataset.scheduleId),label=row.querySelector('[data-employee-schedule-time]');
   if(item&&label)label.textContent=automationListSchedule(item);
  });
 });

 function automationContent(s){
  const list=s.items.length?`<div class="employee-automation-list" aria-busy="${s.busy}">${s.items.map(item=>row(item,s)).join('')}</div>`:'';
  let content=list;
  if(s.error&&!s.loading){
   const noteKey=s.hasRead?(list?'scheduledAutomation.cached':'scheduledAutomation.cachedEmpty'):undefined;
   content=RunTeamsLoadFailure.markup({variant:'local',title:'无法载入自动化',titleKey:'automationList.readFailed',note:noteKey?(list?'正在显示上次载入的计划。':'上次载入时还没有计划。'):'',noteKey,labelKey:'employeeHistory.retry',busyLabelKey:'automationList.loading',retry:'RunTeamsEmployeeAutomation.refresh()'})+list;
  }else if(s.unavailable)content=RunTeamsEmptyStates.markup('automations',{
   title:'暂时无法设置自动化',titleKey:'scheduledAutomation.unavailable'
  })+list;
  else if(!list&&!s.templates?.length&&!s.templateReadError)content=RunTeamsEmptyStates.markup('automations',{titleKey:'automationList.empty'});
  const recovery=pending(s)&&!s.submitting?`<div class="employee-automation-recovery" role="status">
   ${copy('scheduledAutomation.operationPending','上次操作结果待确认。')}
   <button type="button" class="btn" onclick="RunTeamsEmployeeAutomation.recover()" ${s.busy?'disabled':''}>${copy('scheduledAutomation.checkOperation','核对操作')}</button>
   <button type="button" class="btn ghost" onclick="RunTeamsEmployeeAutomation.cancelPending()" ${s.busy?'disabled':''}>${copy('scheduledAutomation.cancelOperation','取消操作')}</button>
  </div>`:'';
  const paused=s.pipeline&&s.hasRead&&s.pipelineStatus!=='running'?`<p class="help" data-app-i18n="scheduledAutomation.pipelinePaused">智能体团队已暂停，自动化暂时不会开始新工作。</p>`:'';
  return recovery+paused+content;
 }
 function commandFailure(message,action){
  if(message==='润色失败，尚未创建。请重试或勾选原文。'||message==='润色结果无效。')return localError('scheduledAutomation.polishFailed','无法润色任务说明。请重试，或选择使用原文。');
  if(message==='自动化已变化，请重新读取。')return localError('scheduledAutomation.changed','这项自动化已有更新。请重新打开自动化后再试。');
  if(message==='请重新打开运行记录，核对要处理的那一次运行。')return localError('scheduledAutomation.reviewRunAgain',message);
  if(message==='这项自动化还有未完成或需要核对的运行。')return localError('scheduledAutomation.unfinishedRun','请先在运行记录中处理上次运行。');
  return action==='save'?localError('automationEditor.saveFailed','无法保存自动化。请稍后再试。'):localError('scheduledAutomation.operationFailed','无法完成操作。请稍后再试。');
 }
 function notify(error,kind='err'){toast(error.message,kind,error.detailKey);}
 async function command(action,item=null,value=null){
  const s=current(),t=target();if(!s||!s.reference||!s.storageKey||!t?.reference||refKey(t.reference)!==refKey(s.reference)||s.busy||pending(s))return false;
  const request={operation_id:crypto.randomUUID(),action,reference:s.reference,id:item?.id??null,expected_revision:item?.revision??null,value};
  try{RunTeamsWorkState.setItem(pendingKey(s),JSON.stringify({operation_id:request.operation_id}));}catch(_){
   const error=localError('scheduledAutomation.receiptFailed','无法在本机保存操作记录。请检查储存空间后重试。');
   if(action==='save')throw error;
   notify(error);return false;
  }
  s.busy=true;s.submitting=true;s.commandError='';paint();
  try{if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();const out=await api(endpoint(s),'POST',request);if(out.error){if(out.state!=='unknown')clearPending(s,request.operation_id);throw Error(out.error);}if(out.operation_id!==request.operation_id)throw Error('操作回执需要核对。');clearPending(s,request.operation_id);if(valid(s)){s.busy=false;await refresh();}return true;}
  catch(e){
   if(e.status===400&&e.code==='schedule_command_rejected')clearPending(s,request.operation_id);
   if(valid(s)){s.commandError=e.message;if(!(form?.owner===s&&document.getElementById('employee_schedule_error')))notify(pending(s)?localError('scheduledAutomation.operationUnconfirmed','无法确认操作结果。请先核对上次操作。'):commandFailure(e.message,action));}
   return false;
  }
  finally{s.submitting=false;s.busy=false;if(valid(s))paint();}
 }
 async function recover(){
  const s=current(),p=s&&pending(s);if(!p||s.busy)return;
  s.busy=true;paint();
  try{
   const out=await api(endpoint(s)+'/operations/'+encodeURIComponent(p.operation_id),undefined,undefined,{readCurrent:true});if(!valid(s))return;
   if(out.state==='failed'){
    clearPending(s,p.operation_id);
    notify(commandFailure(out.error));
   }else if(out.error)throw Error(out.error);
   else if(['committed','abandoned'].includes(out.state)){clearPending(s,p.operation_id);s.busy=false;await refresh();}
   else notify(localError('scheduledAutomation.stillPending','操作仍待确认。请稍后再核对。'),'info');
  }catch(e){if(valid(s))notify(localError('scheduledAutomation.checkFailed','无法读取操作结果。请稍后再核对。'));}
  finally{if(valid(s)){s.busy=false;paint();}}
 }
 async function cancelPending(){
  const s=current(),p=s&&pending(s);if(!p||s.busy)return;
  return confirmModal('取消上次操作？','尚未完成的操作将取消。已保存的更改会保留。',async()=>{
   if(!valid(s))return;s.busy=true;paint();
   try{
    const out=await api(endpoint(s)+'/operations/'+encodeURIComponent(p.operation_id)+'/abandon','POST',{});
    if(out.error)throw Error(out.error);
    if(['committed','abandoned'].includes(out.state))clearPending(s,p.operation_id);
    if(valid(s)){s.busy=false;await refresh();}
   }catch(e){if(valid(s))notify(localError('scheduledAutomation.cancelFailed','无法取消操作。请先核对操作结果。'));}
   finally{if(valid(s)){s.busy=false;paint();}}
  },false,{titleKey:'scheduledAutomation.cancelOperationTitle',messageKey:'scheduledAutomation.cancelOperationMessage',
   cancel:'保留操作',cancelKey:'scheduledAutomation.keepOperation',action:'取消操作',actionKey:'scheduledAutomation.cancelOperation',closeKey:'employeeConsent.close'});
 }
 const find=id=>current()?.items.find(r=>r.id===Number(id));
 async function action(id,action){const item=find(id);if(item)await command(action,item);}
 function menu(event,id){
  const owner=current(),item=find(id);if(!item)return;
  const own=fn=>()=>current()===owner&&fn();
  openMenu(event.currentTarget,[
   {label:'编辑',labelKey:'automationList.edit',icon:'edit',fn:own(()=>edit(id))},
   {label:'立即运行',labelKey:'automationList.runNow',icon:'play',disabled:!!owner.pipeline&&owner.pipelineStatus!=='running',fn:own(()=>{if(!owner.pipeline||owner.pipelineStatus==='running')action(id,'run');})},
   {label:'运行记录',labelKey:'scheduledAutomation.history',icon:'history',fn:own(()=>records(id))},
   {label:'删除自动化',labelKey:'scheduledAutomation.delete',icon:'trash',danger:true,fn:own(()=>confirmModal(
    '删除这项自动化？','之后不会再按此计划创建工作。正在进行的工作和已有记录会保留。',
    ()=>current()===owner&&action(id,'delete'),true,{
     titleKey:'scheduledAutomation.deleteTitle',messageKey:'scheduledAutomation.deleteMessage',
     cancelKey:'scheduledAutomation.cancel',action:'删除自动化',actionKey:'scheduledAutomation.delete',closeKey:'employeeConsent.close'
    }))}
  ],{variant:'workerAction'});
 }
 async function records(id){
  const owner=current(),dialogBefore=document.getElementById('modalHost');if(!owner)return;
  await refresh({silent:true});
  if(current()!==owner||document.getElementById('modalHost')!==dialogBefore)return;
  const item=find(id);if(!item)return;
  const runs=item.runs||[];
  const workflows=owner.pipeline?owner.owner.data?.workflows:[];
  const completedWork=new Set((workflows||[]).filter(work=>work.state==='completed').map(work=>work.id));
  const notice=owner.error?`<p role="status">${runs.length?copy('scheduledAutomation.cachedHistory','无法载入最新记录。正在显示上次载入的记录。'):copy('scheduledAutomation.historyFailed','无法载入运行记录。关闭后可重新打开。')}</p>`:'';
  const list=runs.length?`<div class="employee-automation-records">${runs.map(r=>`<div>
   <b>${copy(...runState(r))}</b>
   <span>${r.scheduled_for?.startsWith('manual:')?copy('scheduledAutomation.manual','手动运行'):automationRunTimeMarkup(r.scheduled_for)}</span>
   ${r.reason?`<p>${r.status==='skipped'&&r.reason==='用户已跳过这一次定时。'
    ?copy('scheduledAutomation.skippedByUser','用户已跳过这一次定时。'):esc(r.reason)}</p>`:''}
   ${r.status==='failed'&&completedWork.has(r.workflow_id)?`<p>${copy('scheduledAutomation.linkedTaskCompleted','关联任务现已完成。')}</p>`:''}
   ${r.workflow_id?`<button class="btn" onclick="closeModal();${owner.pipeline?`RunTeamsSourcePipelines.openWork(${Number(r.workflow_id)})`:`openCoreWorkflow(${Number(r.workflow_id)},{storageScope:'device'})`}">${copy('scheduledAutomation.openWork','查看工作记录')}</button>`:''}
   ${r.chat_id&&!owner.pipeline?`<button class="btn" onclick="closeModal();openConversationSession(${Number(r.chat_id)},'general',{readCurrent:true})">${copy('workRecordDetail.openConversation','打开对话')}</button>`:''}
   ${r.status==='interrupted'?`<button class="btn" onclick="closeModal();RunTeamsEmployeeAutomation.resolve(${Number(item.id)},${Number(r.id)})">${copy('scheduledAutomation.markIncomplete','标记为未完成')}</button>`:''}
  </div>`).join('')}</div>`:owner.error?'':`<p>${copy('automationEditor.historyEmpty','还没有运行记录')}</p>`;
  const dialog=openDialog({
   title:item.name+'的运行记录',titleKey:'scheduledAutomation.historyFor',titleVars:{name:item.name},
   closeLabelKey:'employeeConsent.close',attrs:`role="dialog" aria-modal="true" aria-label="${esc(item.name)}的运行记录" data-app-i18n-aria-label="scheduledAutomation.historyFor" ${vars(item.name)}`,
   closeAction:`RunTeamsEmployeeAutomation.closeRecords(${Number(item.id)})`,
   body:notice+list,footer:`<button class="btn" onclick="RunTeamsEmployeeAutomation.closeRecords(${Number(item.id)})">${copy('employeeConsent.close','关闭')}</button>`
  });
  dialog.querySelector('.modal-x')?.focus();
 }
 function closeRecords(id){
  closeModal();
  document.querySelector(`${drawerSelector} [data-schedule-id="${Number(id)}"] .employee-automation-open`)?.focus();
 }
 function resolve(id,runId){
  const owner=current(),item=find(id);if(!item||!Number.isSafeInteger(runId)||runId<1)return;
  confirmModal('将这次运行标记为未完成？','请先检查已有工作和外部操作的结果。标记后，后续计划可以继续运行。',
   ()=>current()===owner&&command('resolve',item,{run_id:runId}),false,{titleKey:'scheduledAutomation.markTitle',messageKey:'scheduledAutomation.markMessage',cancelKey:'scheduledAutomation.cancel',action:'标记为未完成',actionKey:'scheduledAutomation.markIncomplete',closeKey:'employeeConsent.close'});
 }
 function field(name){return document.getElementById('employee_schedule_'+name);}
 function formCurrent(f=form){return !!f&&form===f&&valid(f.owner)&&document.getElementById('modalHost')===f.element;}
 function edit(id=0){
  const s=current(),item=id?find(id):null;if(!s||!s.hasRead||s.loading||s.busy||s.error||s.unavailable||pending(s)||!s.reference||id&&!item)return;
  const schedule=item?.schedule||{},kind=item?.schedule_kind||'daily',payload=item?.payload||{};
  const objective=payload.original_objective??payload.objective??'';
  const targets=[...(s.followupTargets||[])],saved=payload.parameters||{};
  let selected=-1;
  if(!s.pipeline&&saved.followup_pipeline&&saved.followup_state){
   selected=targets.findIndex(t=>t.pipeline===saved.followup_pipeline&&t.state===saved.followup_state&&t.skill_key===payload.skill_key);
   if(selected<0)selected=targets.push({name:saved.followup_pipeline+' · '+saved.followup_state,pipeline:saved.followup_pipeline,state:saved.followup_state,skill_key:payload.skill_key})-1;
  }
  const showTargets=!s.pipeline&&targets.length&&(selected>=0||!item||payload.schema!=='runteams.task-input/v2');
  const fixedSkill=!s.pipeline&&selected<0&&payload.skill_key?s.skills.find(skill=>skill.key===payload.skill_key):null;
  const timezone=schedule.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone;
  const f={owner:s,item,targets,fixedSkill,timezone,scheduleSelected:!!item,scheduleExpanded:false,hasSchedule:!!item,enabled:item?item.enabled:true,saving:false,position:payload.start_column_key||s.startColumn,parameterDrafts:{[payload.start_column_key||s.startColumn]:payload.parameters||{}}};form=f;
  const title=item?'编辑自动化':'新建自动化',titleKey=item?'scheduledAutomation.editTitle':'scheduledAutomation.new';
  const promptKey=s.pipeline?'scheduledAutomation.pipelinePrompt':'scheduledAutomation.employeePrompt';
  const dialog=openDialog({
   className:'automation-editor employee-schedule-editor',title,titleKey,closeLabelKey:'employeeConsent.close',
   attrs:`role="dialog" aria-modal="true" aria-label="${title}" data-app-i18n-aria-label="${titleKey}"`,
   headerActions:item&&!item.enabled?`<button type="button" class="x" aria-label="计划选项" data-app-i18n-aria-label="scheduledAutomation.options" onclick="RunTeamsEmployeeAutomation.editOptions(event)">${ICON('more')}</button>`:'',
   body:`<div class="employee-schedule-content">
    <div class="employee-schedule-task">
     <textarea class="ta" id="employee_schedule_objective" maxlength="20000" aria-label="任务说明" data-app-i18n-aria-label="automationEditor.instructions" placeholder="描述每次运行要完成的工作" data-app-i18n-placeholder="${promptKey}" oninput="RunTeamsEmployeeAutomation.taskChanged()">${esc(objective)}</textarea>
     ${s.pipeline||fixedSkill?'':`<label class="employee-schedule-original" id="employee_schedule_original_field" title="关闭此选项时，应用会先润色任务说明。" data-app-i18n-title="scheduledAutomation.originalHint"><input type="checkbox" id="employee_schedule_original" ${item&&payload.use_original!==false?'checked':''}>${copy('scheduledAutomation.original','使用原文')}</label>`}
    </div>
    ${s.pipeline?`<div class="field"><label for="employee_schedule_position" data-app-i18n="scheduledAutomation.startPosition">起始岗位</label><select class="inp" id="employee_schedule_position" onchange="RunTeamsEmployeeAutomation.startChanged()">${s.positions.map(p=>`<option value="${esc(p.key)}" ${p.key===f.position?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div><div id="employee_schedule_inputs"></div>`:''}
    ${fixedSkill?coreTaskParameterFields(coreWorkflowFrozenParameters(fixedSkill),saved,'employee_schedule_work'):''}
    ${showTargets?`<div class="field"><label for="employee_schedule_target">${copy('scheduledAutomation.followupTarget','跟进对象')}</label><select class="inp" id="employee_schedule_target" onchange="RunTeamsEmployeeAutomation.taskChanged()"><option value="-1" data-app-i18n="scheduledAutomation.standalone">独立任务</option>${targets.map((target,index)=>`<option value="${index}" ${index===selected?'selected':''}>${esc(target.name)}</option>`).join('')}</select></div>`:''}
    <div class="employee-schedule-timing">
     <button type="button" class="employee-schedule-summary" id="employee_schedule_summary" aria-expanded="false" aria-controls="employee_schedule_details" onclick="RunTeamsEmployeeAutomation.toggleSchedule()">${ICON('clock')}<span id="employee_schedule_label" data-app-i18n="scheduledAutomation.chooseSchedule">设置运行时间</span><small>${copy('scheduledAutomation.keepOnline','运行时电脑需在线')}</small>${ICON('chev')}</button>
     <div id="employee_schedule_details" class="employee-schedule-details" hidden inert aria-hidden="true"><div class="employee-schedule-details-inner">
      <div class="employee-schedule-fields">
       <label class="field"><span id="employee_schedule_repeat" data-app-i18n="automationEditor.repeat">重复</span>${csel('employee_schedule_kind',[
        {value:'daily',label:'每天',labelKey:'automationEditor.daily'},
        {value:'weekly',label:'每周',labelKey:'automationEditor.weekly'},
        {value:'interval',label:'按间隔',labelKey:'automationEditor.interval'}
       ],kind,()=>{if(formCurrent(f)&&!f.saving)scheduleChanged();},{menuVariant:'settingsSelect'})}</label>
       <label class="field" id="employee_schedule_time_field">${copy('automationEditor.time','时间')}<input class="inp" id="employee_schedule_time" type="text" placeholder="HH:mm" maxlength="5" autocomplete="off" spellcheck="false" value="${esc(schedule.time||'09:00')}" oninput="RunTeamsEmployeeAutomation.scheduleChanged()"></label>
       <label class="field" id="employee_schedule_interval_field">${copy('scheduledAutomation.intervalMinutes','间隔（分钟）')}<input class="inp" id="employee_schedule_interval" type="number" min="1" max="43200" value="${Math.max(1,(item?.interval_sec||3600)/60)}" oninput="RunTeamsEmployeeAutomation.scheduleChanged()"></label>
      </div>
      <div id="employee_schedule_days" class="employee-schedule-days" hidden><span data-app-i18n="automationEditor.weekdays">星期</span><div>${['一','二','三','四','五','六','日'].map((label,day)=>`<label><input type="checkbox" value="${day}" ${(schedule.weekdays||[]).includes(day)?'checked':''} onchange="RunTeamsEmployeeAutomation.scheduleChanged()">${copy('automationEditor.day'+day,label)}</label>`).join('')}</div></div>
     </div></div>
    </div>
    <label class="employee-schedule-name">${ICON('tag')}<input class="inp employee-schedule-name-input" type="text" id="employee_schedule_name" aria-label="名称" data-app-i18n-aria-label="automationEditor.name" maxlength="120" value="${esc(item?.name||'')}" placeholder="自动生成名称" data-app-i18n-placeholder="scheduledAutomation.automaticName" autocomplete="off"></label>
    <p id="employee_schedule_error" role="alert" class="account-team-error" hidden></p>
   </div>`,
   footer:`<span class="employee-schedule-paused" id="employee_schedule_paused" data-app-i18n="automationList.paused" ${item&&!item.enabled?'':'hidden'}>已暂停</span><div class="grow"></div><button class="btn ghost" id="employee_schedule_close" data-app-i18n="scheduledAutomation.cancel" onclick="closeModal()">取消</button><button class="btn pri" id="employee_schedule_save" data-app-i18n="${item?'automationEditor.save':'scheduledAutomation.create'}" onclick="RunTeamsEmployeeAutomation.save()">${item?'保存':'创建'}</button>`
  });
  f.element=dialog;scheduleChanged();taskChanged();if(s.pipeline)void startChanged(true);
  field('objective')?.focus({preventScroll:true});
 }
 function errorText(error){
  const node=field('error');if(!node)return;
  applyCopy(node,error?.message||'',error?.detailKey,error?.detailVars);
  node.hidden=!error;
 }
 function automaticName(objective){return [...String(objective||'').trim().split(/[\r\n，。！？；,:!?;]/)[0]].slice(0,18).join('');}
 function taskChanged(){const f=form;if(!f||f.saving)return;const original=field('original_field');if(original)original.hidden=Number(field('target')?.value??-1)>=0;const objective=field('objective')?.value||'';if(field('save'))field('save').disabled=!objective.trim()||!f.hasSchedule||f.owner.pipeline&&!f.inputContract;errorText(f.scheduleError);}
 function scheduleKind(){return field('kind')?.dataset.value;}
 function scheduleSummary(f){
  const label=field('label');
  if(f.scheduleSelected&&f.hasSchedule){
   const value=scheduleValue();
   label.textContent=automationListSchedule(value);
   label.removeAttribute('data-app-i18n');
  }else applyCopy(label,'设置运行时间','scheduledAutomation.chooseSchedule');
 }
 function scheduleChanged(){
  const f=form,kind=scheduleKind();if(!f||f.saving)return;
  field('time_field').hidden=kind==='interval';field('interval_field').hidden=kind!=='interval';field('days').hidden=kind!=='weekly';
  if(f.scheduleSelected){
   try{scheduleValue();f.hasSchedule=true;f.scheduleError=null;}
   catch(e){f.hasSchedule=false;f.scheduleError=e;}
   errorText(f.scheduleError);
   scheduleSummary(f);
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
  const kind=scheduleKind(),item=form?.item,saved=item?.schedule;
  const schedule={time:saved?.time||'09:00',weekdays:saved?.weekdays||[],timezone:form.timezone};
  let intervalSec=item?.interval_sec||3600;
  if(kind==='weekly'){
   schedule.weekdays=[...document.querySelectorAll('#employee_schedule_days input:checked')].map(node=>Number(node.value));
   if(!schedule.weekdays.length)throw localError('scheduledAutomation.chooseDay','请至少选择一天。');
  }
  if(kind==='interval'){
   const minutes=Number(field('interval').value);
   if(!Number.isInteger(minutes)||minutes<1||minutes>43200)throw localError('scheduledAutomation.invalidInterval','请输入 1 到 43200 之间的整数分钟数。');
   intervalSec=minutes*60;
  }else{
   schedule.time=field('time').value;
   if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(schedule.time))throw localError('scheduledAutomation.invalidTime','请用 24 小时制输入时间，例如 09:00。');
  }
  return {schedule_kind:kind,interval_sec:intervalSec,schedule};
 }
 function editOptions(event){const f=form;if(!formCurrent(f)||f.saving||f.enabled)return;openMenu(event.currentTarget,[{label:'启用自动化',labelKey:'automationList.enable',icon:'play',fn:()=>{if(formCurrent(f)&&!f.saving){f.enabled=true;field('paused').hidden=true;}}}]);}
 function freezeForm(f,busy,progress){
  if(!formCurrent(f))return;
  f.element.querySelectorAll('.employee-schedule-content input,.employee-schedule-content textarea,.employee-schedule-content select,.employee-schedule-content button').forEach(node=>node.disabled=busy);
  const button=field('save');
  button.disabled=busy||!!pending(f.owner)||!f.hasSchedule||!field('objective').value.trim()||f.owner.pipeline&&!f.inputContract;
  button.setAttribute('aria-busy',String(busy));
  applyCopy(button,...(busy?progress:f.item?['保存','automationEditor.save']:['创建','scheduledAutomation.create']));
  applyCopy(field('close'),busy?'关闭':'取消',busy?'employeeConsent.close':'scheduledAutomation.cancel');
 }
 async function save(){
  const f=form;if(!formCurrent(f)||f.saving||f.owner.busy||pending(f.owner))return;
  try{
   const objective=field('objective').value,name=field('name').value.trim()||automaticName(objective);
   if(!objective.trim())throw localError('scheduledAutomation.missingInstructions','请描述要完成的工作。');if(!f.scheduleSelected)throw localError('scheduledAutomation.chooseSchedule','设置运行时间');
   const target=f.targets[Number(field('target')?.value??-1)];
   const employeeTask=target?{skill_key:target.skill_key,parameters:{...(f.item?.payload?.skill_key===target.skill_key?f.item.payload.parameters:{}),followup_pipeline:target.pipeline,followup_state:target.state}}:
    f.fixedSkill?{skill_key:f.fixedSkill.key,parameters:readCoreTaskParameters(f.element.querySelector('.employee-schedule-content'))}:null;
   const task=f.owner.pipeline?{start_column_key:f.position,parameters:readCoreTaskParameters(field('inputs'))}:employeeTask||{use_original:field('original').checked};
   const value={name,objective,enabled:f.enabled,...scheduleValue(),...task};
   if(f.owner.pipeline&&!f.inputContract)throw localError('scheduledAutomation.checkInputs','请先检查起始岗位的任务信息。');
   f.saving=true;errorText('');freezeForm(f,true,value.use_original===false?['正在润色任务说明…','scheduledAutomation.polishing']:f.item?['正在保存…','automationEditor.saving']:['正在创建…','scheduledAutomation.creating']);
   if(await command('save',f.item,value)){if(formCurrent(f)){form=null;closeModal();}}
   else if(formCurrent(f))errorText(pending(f.owner)?localError('scheduledAutomation.saveUnconfirmed','无法确认是否已保存。关闭此窗口，在自动化中核对上次操作。'):commandFailure(f.owner.commandError,'save'));
  }catch(e){if(formCurrent(f))errorText(e);}
  finally{f.saving=false;freezeForm(f,false);}
 }

 function pipelineInputs(f){
  if(f.inputLoading)return RunTeamsSkeletons.region('parameters',undefined,'scheduledAutomation.loadingInputs');
  if(f.inputError)return RunTeamsLoadFailure.markup({variant:'local',title:'无法读取任务信息',titleKey:'scheduledAutomation.inputsFailed',labelKey:'employeeHistory.retry',busyLabelKey:'scheduledAutomation.loadingInputs',retry:'RunTeamsEmployeeAutomation.startChanged(true,true)'});
  return coreTaskParameterFields(coreWorkflowFrozenParameters(f.inputContract),f.parameterDrafts[f.position]||{},'pipeline_schedule')||`<p class="help">${copy('scheduledAutomation.noInputs','这项工作无需其他任务信息。')}</p>`;
 }
 async function startChanged(initial=false,focusAfterRead=false){
  const f=form;if(!formCurrent(f)||!f.owner.pipeline||f.saving)return;
  const position=field('position').value;
  if(!initial&&f.inputContract){try{f.parameterDrafts[f.position]=readCoreTaskParameters(field('inputs'));}catch(e){field('position').value=f.position;errorText(e);return;}}
  f.position=position;f.inputContract=null;f.inputLoading=true;f.inputError='';const ticket=(f.contractRead||0)+1;f.contractRead=ticket;taskChanged();
  field('inputs').innerHTML=pipelineInputs(f);
  try{const result=await RunTeamsSourcePipelines.request('contract',{reference:f.owner.reference,start_column_key:position});
   if(!formCurrent(f)||f.contractRead!==ticket)return;
   f.inputLoading=false;f.inputContract=result;
   const inputs=field('inputs');
   inputs.innerHTML=pipelineInputs(f);taskChanged();
   if(focusAfterRead&&document.activeElement===document.body){
    const next=inputs.querySelector('input:not(:disabled),textarea:not(:disabled),select:not(:disabled)')||field('position');
    next.focus({preventScroll:true});
   }
  }catch(e){if(formCurrent(f)&&f.contractRead===ticket){f.inputLoading=false;f.inputError=true;field('inputs').innerHTML=pipelineInputs(f);}}
 }

 function settingsOpen(panel=S.conversationPanel){
  const configuration=window.RunTeamsEmployeeConfiguration?.current();
  if(configuration&&S.sel?.type!=='employee-overview'&&configuration.entry.key===(window.RunTeamsEmployeeConfiguration?.workTarget?.(panel)||target(panel))?.key)return true;
  const t=target(panel),s=typeof RunTeamsCreatorAuthor==='undefined'?null:RunTeamsCreatorAuthor.current();
  return !!s&&!!t?.source&&(s.session===panel.id||(s.sourceId===t.source.id||s.localDraft?.id===t.source.id)&&(!s.employeeSource||s.employeeSource===t.source.path));
 }
 async function sourceSettings(){
  const panel=S.conversationPanel;if(panel?.context?.pipeline_work){toast('请在智能体团队设置中配置对应岗位。','info',"employeeSettings.configurePipeline");return;}
  const work=window.RunTeamsEmployeeConfiguration?.workTarget?.(panel),t=target();if(!t&&!work){toast('员工暂不可用。','info',"employeeSettings.missingEmployee");return;}
  if(settingsOpen(panel))return window.RunTeamsEmployeeConfiguration?.current()?RunTeamsEmployeeConfiguration.close():RunTeamsCreatorAuthor.close();

  return work?RunTeamsEmployeeConfiguration.openConversation(work,RunTeamsEmployeeDirectory.forPanel(panel)):RunTeamsEmployeeDirectory.settings(t.key);
 }
 window.RunTeamsEmployeeAutomation=Object.freeze({overviewSection,sourceSettings,current,refresh,reviewTemplate,closeTemplate,edit,startChanged,scheduleChanged,taskChanged,toggleSchedule,editOptions,save,action,menu,records,closeRecords,recover,resolve,cancelPending});
 if(typeof setInterval==='function')setInterval(()=>{const s=current();if(s&&!s.unavailable&&!s.busy&&!pending(s)&&!document.querySelector('#modalHost')&&!scheduleMenuOpen())void refresh({silent:true,background:true});},10000);
 window.addEventListener('runteams:business-scope-changed',()=>{state=null;form=null;});
})();
