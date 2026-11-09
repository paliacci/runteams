/* Platform navigation for the employee's records. No author code or business writes. */
(()=>{
 'use strict';
 const saved=new Map(),openingOrigins=new WeakMap();
 function readResults(data){
  if(data?.error)throw Error(data.error);
  if(!Array.isArray(data?.results)||data.results.some(row=>typeof row?.key!=='string'||!row.key))throw Error('Invalid work history response');
  return data;
 }
 function listTime(value){
  const date=docParseTime(value);
  if(!date)return '';
  const locale=window.RunTeamsLocale;
  if(!locale)return docsTime(value);
  const english=locale.language==='en';
  const days=docDayDistance(value);
  if(days===0||days===1){
   const time=locale.formatDate(date,english?{hour:'numeric',minute:'2-digit'}:{hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
   return locale.t(days===0?'workRecords.todayTime':'workRecords.yesterdayTime',{time});
  }
  if(!english)return docsTime(value);
  return locale.formatDate(date,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
 }
 function groupedTime(value,previous){
  const date=docParseTime(value);
  if(!date)return '';
  const locale=window.RunTeamsLocale;
  const clock=locale.language==='en'?{hour:'numeric',minute:'2-digit'}:{hour:'2-digit',minute:'2-digit',hourCycle:'h23'};
  const day=docDayDistance(value);
  if(day===0||day===docDayDistance(previous))return locale.formatDate(date,clock);
  const year=date.getFullYear()!==new Date().getFullYear()?{year:'numeric'}:{};
  return locale.formatDate(date,{...year,month:'short',day:'numeric',...clock});
 }
 function timeLabel(value,updated,previous){
  const time=previous===undefined?listTime(value):groupedTime(value,previous);
  if(!time||!updated)return time;
  return window.RunTeamsLocale?.t('workRecordDetail.updatedTime',{time})??time+'更新';
 }
 function timeMarkup(value,updated=false,previous){
  if(!value)return '';
  const label=timeLabel(value,updated,previous);
  if(!label)return '';
  return `<time data-work-record-time="${esc(value)}"${updated?' data-work-record-updated':''}${previous===undefined?'':` data-work-record-previous-time="${esc(previous||'')}"`}>${esc(label)}</time>`;
 }
 const text=(key,fallback,vars={})=>window.RunTeamsLocale?.t('workRecords.'+key,vars,fallback)??fallback;
 function stateMarkup(state,returnTo){
  const labels={human_handled:'已人工处理',human_requested:'曾请求人工处理',returned:'已退回{name}'};
  const custom=Object.hasOwn(labels,state);
  const key='state.'+state,vars=state==='returned'?{name:returnTo}:{};
  const copy=custom?{key:'workRecords.'+key,label:text(key,labels[state].replace('{name}',returnTo||''),vars)}:workRecordStateCopy(state);
  const tone=custom?'neutral':coreWorkflowStateClass(state);
  return `<span class="work-record-state ${esc(tone)}" data-work-state="${esc(state)}" data-app-i18n="${copy.key}"${state==='returned'?` data-app-i18n-vars="${esc(JSON.stringify(vars))}"`:''}>${esc(copy.label)}</span>`;
 }
 function prose(value){return `<div class="doc-reader-prose work-record-report">${renderMarkdown(String(value||''))}</div>`;}
 function rowMarkup({key,title,summary,state,updated_at,created_at,report_document,icon,role,executionRole,returnTo,previousTime},action,attributes=''){
  const value=String(summary||''),plain=(report_document||role!==undefined?value:value.replace(/\[([^\]]+)\]\([^)]+\)/g,'$1').replace(/[*_`#]/g,'')).replace(/\s+/g,' ').trim();
  const name=title||text('untitled','未命名工作');
  const badge=role===undefined?stateMarkup(state,returnTo):'';
  const description=plain?`<span class="result-delivery-conclusion"${icon||role!==undefined||executionRole!==undefined?` title="${esc(plain)}"`:''}>${esc(plain)}</span>`:'';
  const titleMarkup=`<b title="${esc(name)}">${esc(name)}</b>`;
  const headingRole=executionRole??role;
  const heading=headingRole?`<span class="work-record-row-heading">${titleMarkup}<span class="work-record-state work-record-role" title="${esc(headingRole)}">${esc(headingRole)}</span></span>`:titleMarkup;
  return `<div class="result-delivery" role="listitem"><button class="result-delivery-summary rt-list-row" type="button" data-result-key="${esc(key)}" ${attributes} onclick="${action}"><span class="result-delivery-title">${heading}${timeMarkup(updated_at||created_at,false,previousTime)}${ICON('chev')}</span><span class="result-delivery-line">${icon?ICON(icon):''}${description}${badge}</span></button></div>`;
 }
 function taskRowMarkup(result){
  const pipeline=S.sel?.scope?.source_pipeline_reference&&!S.sel.scope.workflow_id;
  const output=result.outputs?.[0],run=result.contributions?.find(item=>Number(item.id)===Number(output?.run_id));
  const ref=output?.kind==='reference'?result.references?.find(item=>item.key===output.key):null;
  const document=output?.kind==='document'?run?.artifacts?.find(item=>Number(item.id)===Number(output.id)):null;
  return rowMarkup({...result,summary:result.summary||ref?.summary||document?.name||''},pipeline?'RunTeamsWorkRecords.openPipelineTask(this.dataset.resultKey)':'openResultDelivery(this.dataset.resultKey)');
 }
 const selectedResult=selection=>(selection?.data?.results||[]).find(row=>row.key===selection.resultKey);
 const workflowId=selection=>Number(selection?.workflow?.id||selectedResult(selection)?.workflow_id)||0;
 const referenceKey=reference=>reference?RunTeamsSourcePipelines.referenceKey(reference):'';
 const pipelineCurrent=reference=>!!referenceKey(reference)&&referenceKey(reference)===referenceKey(RunTeamsSourcePipelines.current()?.reference);
 function taskResults(workflows,reference){
  if(!Array.isArray(workflows))throw Error(text('tasksUnavailable','任务列表尚未载入，请重试。'));
  return {results:workflows.slice().reverse().map(work=>{
   if(!Number.isSafeInteger(Number(work.id))||work.pipeline_reference&&referenceKey(work.pipeline_reference)!==referenceKey(reference))throw Error(text('executionUnavailable','执行记录归属未能确认。'));
   return {key:'workflow-'+work.id,workflow_id:Number(work.id),title:work.title,state:work.state,summary:work.summary||'',updated_at:work.updated_at,created_at:work.created_at};
  })};
 }
 function updateTaskList(workspace){
  const selection=S.sel;
  if(selection?.type!=='core-results'||selection.sourceWorkspace!==workspace||selection.scope.workflow_id)return;
  selection.data=taskResults(workspace.data.workflows,workspace.reference);selection.status='ready';selection.error='';
 }
 function reportReference(report){return {id:Number(report.meta_json.revision_of||report.id),revision:Number(report.meta_json.revision||1),document_key:report.meta_json.document_key||'',name:report.name};}
 const artifactRoot=item=>Number(item.meta_json?.revision_of||item.id);
 function uniqueArtifacts(artifacts){
  const seen=new Set();
  return artifacts.slice().sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||''))||Number(b.id)-Number(a.id)).filter(item=>{
   const id=artifactRoot(item);
   if(!Number.isSafeInteger(id)||id<=0||seen.has(id))return false;
   seen.add(id);return true;
  });
 }
 function executionFields(run){
  const delivered=run.output_json?.output??run.output??{};
  return run.fields||(delivered&&typeof delivered==='object'&&!Array.isArray(delivered)?Object.entries(delivered).map(([key,value])=>({key,label:key,value,schema:{}})):[{key:'output',label:text('output','交付内容'),value:delivered,schema:{}}]);
 }
 function taskDeliveries(work){
  const runs=work.employee_runs||[],roles=new Map((work.snapshot_json?.pipeline_work?.asset?.pipeline?.positions||[]).map(role=>[role.key,role.name]));
  const roleName=run=>roles.get(run?.position_key)||run?.employee_name||'';
  const byId=new Map(runs.map(run=>[Number(run.id),run]));
  const artifacts=uniqueArtifacts(work.artifacts||runs.flatMap(run=>run.artifacts||[]));
  const files=artifacts.flatMap(item=>{
   if(item.meta_json?.source==='pipeline_task_report')return [];
   const binding=item.meta_json?.work_report;
   if(binding?.schema==='runteams.work-report/v1'&&Number(binding.workflow_id)!==Number(work.id))return [];
   return [{...item,role:roleName(byId.get(Number(binding?.employee_run_id||item.employee_run_id)))}];
  });
  return {files};
 }
 const hasFailureReason=value=>typeof value==='string'&&value.trim()&&value.trim()!=='请查看原工作对话。';
 function failureReason(run){
  const output=run?.output_json||{},issues=output.issues??run?.issues;
  return [run?.failure_reason,output.output?.reason??run?.output?.reason,...(Array.isArray(issues)?issues:[]),output.summary??run?.summary].find(hasFailureReason)||'';
 }
 const missingFailureReason=()=>window.RunTeamsLocale?.t('pipelineWork.failureUnrecorded',{},'未记录具体失败原因。')??'未记录具体失败原因。';
 function executionSummary(run){
  return run.state==='failed'?failureReason(run)||missingFailureReason():run.output_json?.summary??run.summary??'';
 }
 function currentExecutionOutsideHistory(work){
  const running=work.state==='running';
  if(!running&&!['blocked','needs_human','needs_approval'].includes(work.state))return null;
  const frozen=work.snapshot_json||{},wait=frozen.pipeline_waiting,runs=work.employee_runs||[];
  if(['blocked','needs_human'].includes(work.state)&&wait?.kind==='result'&&
   wait.state===work.state&&wait.position_key===work.cursor_key&&Number(wait.source_run_id)>0){
   // The task drawer already presents this result and links to the full execution from its heading.
   const source=runs.find(item=>Number(item.id)===Number(wait.source_run_id)&&item.position_key===work.cursor_key);
   if(source&&[work.state,'completed'].includes(source.state))return source;
  }
  const id=Number((running?frozen.employee_run_id:wait?.source_run_id??frozen.employee_run_id)||0);
  const run=id?runs.find(item=>Number(item.id)===id):runs[0];
  if(!run||run.state!==work.state||run.position_key!==(running?work.cursor_key:wait?.position_key||work.cursor_key))return null;
  if(running)return run;
  const waitingResult=Number(wait?.source_run_id)===Number(run.id)?wait.result:null;
  const results=[run.output_json,waitingResult].filter(Boolean);
  const hasResult=results.some(result=>
   [result.summary,result.reason,result.recovery,result.output?.reason,result.output?.recovery].some(hasFailureReason)||
   [result.issues,result.work_done].some(items=>Array.isArray(items)&&items.some(hasFailureReason))||
   result.report_references?.length||result.artifacts?.length||Object.keys(result.output||{}).length);
  return hasResult||failureReason(run)||executionFields(run).length||executionArtifacts(work,run).length||
   hasFailureReason(executionFeedback(work,run)?.summary)?null:run;
 }
 function executionState(work,run){
  const id=Number(run.id),events=work.events||[],frozen=work.snapshot_json||{};
  const wait=frozen.pipeline_waiting;
  const isWaiting=wait?.kind==='result'&&wait.state==='needs_human'&&Number(wait.source_run_id)===id;
  if(isWaiting)return {state:'needs_human'};
  const requested=run.state==='needs_human'||events.some(event=>event.type==='workflow.needs_human'&&Number(event.data_json?.employee_run_id)===id);
  if(requested||run.state==='blocked'){
   // Older response receipts have no run ID. Bind them through the next visit's exact feedback and time window.
   const next=(work.employee_runs||[]).findLast(candidate=>{
    const stage=candidate.input_json?.payload?.context?.pipeline_stage;
    return Number(candidate.id)>id&&candidate.position_key===run.position_key&&Number(stage?.feedback?.employee_run_id)===id;
   });
   const stage=next?.input_json?.payload?.context?.pipeline_stage;
   const queued=!next&&Number(frozen.pipeline_feedback?.employee_run_id)===id&&work.cursor_key===run.position_key;
   const until=Date.parse(next?.created_at||(queued?work.updated_at:null));
   const since=Date.parse(run.updated_at);
   const answered=events.some(event=>{
    const data=event.data_json||{};
    if(event.type!=='workflow.human_responded'||data.position_key!==run.position_key)return false;
    if(data.source_run_id!=null)return Number(data.source_run_id)===id;
    const at=Date.parse(event.created_at);
    return !!(stage?.human_response||queued&&frozen.pipeline_response)&&since<=at&&at<=until;
   });
   if(answered)return {state:'human_handled'};
   if(requested)return {state:'human_requested'};
  }
  if(run.state==='completed'){
   const positions=run.input_json?.pipeline_work?.asset?.pipeline?.positions||frozen.pipeline_work?.asset?.pipeline?.positions||[];
   const source=positions.findIndex(position=>position.key===run.position_key);
   const route=events.find(event=>event.type==='workflow.routed'&&Number(event.data_json?.employee_run_id)===id&&
    event.data_json.from===run.position_key&&event.data_json.when?.startsWith('outcome:'))?.data_json;
   const destination=positions.findIndex(position=>position.key===route?.to);
   if(destination>=0&&destination<source)return {state:'returned',returnTo:positions[destination].name};
  }
  return {state:run.state};
 }
 function executionPosition(run){
  const order=run.input_json;
  const positions=order?.pipeline_work?.asset?.pipeline?.positions||[];
  return order?.payload?.context?.pipeline_stage?.position_name||
   positions.find(position=>position.key===run.position_key)?.name||'';
 }
 function historicalOutcomeTitle(run){
  const result=run.output_json;
  if(result?.schema!=='runteams.work-result/v1')return '';
  const blocked=['blocked','needs_human','failed'].includes(run.state);
  const candidates=blocked?result.issues:
   run.state==='completed'?[result.summary,...(result.work_done||[])]:[];
  for(const value of candidates||[]){
   if(typeof value!=='string')continue;
   const sentence=value.split(/[。！？；;\n]|[.!?](?:\s|$)/u,1)[0];
   const phrase=sentence.split(blocked?/[，：]/u:/：/u,1)[0].trim();
   if(phrase.length>=8&&phrase.length<=48&&!/[<>`\[\]]|:\/\//u.test(phrase))return phrase;
  }
  return '';
 }
 function executionTitle(run,shownOutcome=''){
  const result=run.output_json;
  const systemFailure=run.failure_reason||(result?.transport_status==='failed'&&!result.schema?failureReason(run):'');
  if(run.state==='failed'&&/^(?:Codex )?执行达到 \d+ 分钟上限/u.test(systemFailure||''))return text('executionTimedOut','执行超时中断');
  if(run.state==='canceled')return text('executionCanceled','执行已取消');
  const title=result?.title,position=executionPosition(run);
  const workName=shownOutcome&&run.work_name===(position||run.employee_name)?'':run.work_name;
  return (title&&String(title).trim()!==shownOutcome&&title)||(!shownOutcome&&historicalOutcomeTitle(run))||
   workName||(!shownOutcome&&position)||text('executionDetail','执行详情');
 }
 function attemptsMarkup(work,attempts,start=0,end=attempts.length,label=text('executions','岗位执行记录'),shownOutcome=null){
  const rows=attempts.slice(start,end).map((run,index)=>{
   const previous=attempts[start+index-1];
   const shown=shownOutcome?.runId===run.id?shownOutcome.text:'';
   const title=executionTitle(run,shown);
   let summary=String(executionSummary(run)||'').trim();
   if(summary===shown||summary===title)summary='';
   else if(summary.startsWith(title)&&/^[：:。.!！]/u.test(summary.slice(title.length)))summary=summary.slice(title.length+1).trim();
   return rowMarkup({key:'attempt-'+run.id,title,
    summary,
    executionRole:executionPosition(run)||run.employee_name||'',...executionState(work,run),updated_at:run.updated_at,created_at:run.created_at,previousTime:previous?.updated_at||previous?.created_at||null},
    'RunTeamsWorkRecords.openAttempt(Number(this.dataset.attemptId))',`data-attempt-id="${Number(run.id)}"`);
  }).join('');
  return rows?`<div class="result-delivery-list work-record-list work-execution-list" role="list" aria-label="${esc(label)}">${rows}</div>`:`<p class="work-record-empty">${esc(text('noExecutions','尚无岗位执行记录。'))}</p>`;
 }
 function earlierExecutionsLabel(expanded,count){
  return expanded?text('hideEarlierExecutions','收起较早的执行'):text('showAllExecutions','查看全部 '+count+' 次执行',{count});
 }
 function earlierExecutionsMarkup(selection,id,work,attempts,limit,shownOutcome){
  const expanded=!!selection.showAllExecutions,region='work-executions-earlier-'+id;
  const body=`<div id="${region}" class="work-execution-earlier"${expanded?'':' hidden'}>${attemptsMarkup(work,attempts,limit,attempts.length,text('earlierExecutions','较早的执行'),shownOutcome)}</div>`;
  const footer=`<button type="button" class="settings-section-action settings-section-footer-action" aria-expanded="${expanded}" aria-controls="${region}" data-execution-count="${attempts.length}" onclick="RunTeamsWorkRecords.toggleEarlierExecutions(this)">${esc(earlierExecutionsLabel(expanded,attempts.length))}</button>`;
  return {body,footer};
 }
 function executionSectionMarkup(work,attempts,shownOutcome=null){
  const selection=S.sel,id=workflowId(selection),expanded=selection?.workSections?.history??selection?.executionExpanded??true;
  const label=text('executions','岗位执行记录'),limit=selection?.type==='source-pipeline'?3:attempts.length;
  const earlier=attempts.length>limit?earlierExecutionsMarkup(selection,id,work,attempts,limit,shownOutcome):null;
  return RunTeamsEmployeeDrawerHeader.section({id:'work-executions-'+id,stateKey:'executions',
   title:esc(label),
   body:attemptsMarkup(work,attempts,0,limit,label,shownOutcome)+(earlier?.body||''),footer:earlier?.footer,collapsedSections:new Set(expanded?[]:['executions']),
   action:'RunTeamsWorkRecords.toggleExecutionSection',className:'work-execution-section'});
 }
 function toggleEarlierExecutions(button){
  const selection=S.sel,region='work-executions-earlier-'+workflowId(selection);
  if(selection?.type!=='source-pipeline'||selection.id!=='work'||!button.isConnected||button.getAttribute('aria-controls')!==region)return;
  const earlier=document.getElementById(region);
  if(!earlier||earlier!==button.previousElementSibling)return;
  const expanded=selection.showAllExecutions=earlier.hidden;
  earlier.hidden=!expanded;
  button.setAttribute('aria-expanded',String(expanded));
  button.textContent=earlierExecutionsLabel(expanded,Number(button.dataset.executionCount));
 }
 function toggleExecutionSection(button){
  if(!button.isConnected||button.getAttribute('aria-controls')!=='work-executions-'+workflowId(S.sel))return;
  RunTeamsEmployeeDrawerHeader.toggleSection(button,S.sel.collapsedRecordSections||=new Set());
  const expanded=button.getAttribute('aria-expanded')==='true';
  if(S.sel.type==='source-pipeline')(S.sel.workSections??={}).history=expanded;else S.sel.executionExpanded=expanded;
 }
 function runtimeMarkup(run){
  const runtime=run?.input_json?.package?.runtime;
  if(!runtime?.model)return '';
  const {model,effort}=runtime;
  const label=text('runtimeModel','岗位模型')+' '+model;
  const levelKey=effort&&Object.hasOwn(EFFORT_LABELS,effort)?'runtimeSelector.level.'+effort:'';
  const depth=effort?` <span class="work-record-runtime-effort" title="思考强度" data-app-i18n-title="runtimeSelector.effort"${levelKey?` data-app-i18n="${levelKey}"`:''}>${esc(levelKey?EFFORT_LABELS[effort]:effort)}</span>`:'';
  return `<span class="work-record-runtime"><span class="work-record-runtime-model" title="${esc(label)}">${esc(model)}</span>${depth}</span>`;
 }
 function executionHandoff(work,run,fields){
  const route=(work.events||[]).find(event=>event.type==='workflow.routed'&&Number(event.data_json?.employee_run_id)===Number(run.id))?.data_json;
  if(!route)return null;
  const pipeline=run.input_json?.pipeline_work?.asset?.pipeline||work.snapshot_json?.pipeline_work?.asset?.pipeline;
  const next=work.employee_runs.findLast(candidate=>Number(candidate.id)>Number(run.id)&&candidate.position_key===route.to);
  const received=next?.input_json?.payload?.context?.pipeline_stage?.previous_handoffs||[];
  const matches=fields.filter(field=>received.some(entry=>entry.position_key===run.position_key&&Object.hasOwn(entry.values||{},field.key)&&
    JSON.stringify(entry.values[field.key])===JSON.stringify(field.value)));
  const target=[...(pipeline?.positions||[]),...(pipeline?.states||[])].find(stage=>stage.key===route.to);
  return {target:target?.name||'',fields:matches};
 }
 function executionArtifacts(work,run){
  const id=Number(run.id),workId=Number(work.id);
  return (run.artifacts||[]).filter(item=>{
   const binding=item.meta_json?.work_report;
   return binding?Number(binding.workflow_id)===workId&&Number(binding.employee_run_id)===id:Number(item.employee_run_id)===id;
  });
 }
 function executionReport(work,run){
  return uniqueArtifacts(executionArtifacts(work,run).filter(item=>item.meta_json?.work_report?.schema==='runteams.work-report/v1'))[0];
 }
 function isDraftReport(work,run){
  const output=run.output_json||{},submission=work.snapshot_json?.pipeline_submission;
  return (run.state==='running'||Array.isArray(output.report_references))&&
   !output.report_references?.length&&Number(submission?.receipt?.employee_run_id)!==Number(run.id);
 }
 function liveActivityMarkup(run,compact=false){
  const activity=run.live_activity||{};
  const lines=[];
  const questions=(activity.questions||[]).slice(compact?-1:-8);
  for(const question of questions)lines.push(question||text('liveQuestion','等待你回复'));
  if(activity.approval_pending)lines.push(text('liveApproval','工具操作等待确认'));
  const notes=(activity.notes||[]).slice(compact?-1:-8).reverse();
  lines.push(...notes);
  const stepLabels={command:['liveCommand','命令'],file:['liveFile','文件操作'],search:['liveSearch','搜索'],tool:['liveTool','工具操作']};
  const stepStates={running:['liveRunning','{step}进行中'],completed:['liveCompleted','{step}已完成'],failed:['liveFailed','{step}失败']};
  const steps=(activity.steps||[]).slice().reverse();
  if(compact)steps.sort((a,b)=>Number(b.status==='running')-Number(a.status==='running'));
  for(const step of steps.slice(0,compact?1:8)){
   if(!Object.hasOwn(stepLabels,step.kind)||!Object.hasOwn(stepStates,step.status))continue;
   lines.push(text(...stepStates[step.status],{step:text(...stepLabels[step.kind])}));
  }
  if(!lines.length&&run.state==='running')return `<p class="source-work-muted">${esc(text('liveAwaitingProgress','等待员工发出首条工作进展。'))}</p>`;
  const chat=Number(run.input_json?.chat_id);
  const conversation=!compact&&(questions.length||activity.approval_pending)&&Number.isSafeInteger(chat)&&chat>0?
   `<button type="button" class="btn sm" onclick="openConversationSession(${chat},'general',{device:true})">${esc(text('liveOpenConversation','查看工作对话'))}</button>`:'';
  return lines.map(line=>`<p>${esc(line)}</p>`).join('')+conversation;
 }
 function executionFeedback(work,run){
  const frozen=work.snapshot_json||{};
  const snapshots=[...(frozen.pipeline_history||[]).map(entry=>entry.snapshot),frozen];
  return snapshots.findLast(snapshot=>Number(snapshot?.pipeline_feedback?.employee_run_id)===Number(run.id))?.pipeline_feedback;
 }
 function attemptResult(work,run){
  const output=run.output_json||{},id=Number(run.id),workId=Number(work.id),artifacts=executionArtifacts(work,run);
  const report=executionReport(work,run);
  const pipeline=run.input_json?.pipeline_work?.asset?.pipeline||work.snapshot_json?.pipeline_work?.asset?.pipeline;
  const secret=new Set((pipeline?.parameters||[]).filter(field=>field.type==='secret').map(field=>field.key));
  const fields=executionFields(run).filter(field=>!secret.has(field.key));
  const issues=output.issues||run.issues||[];
  const contribution={...run,summary:executionSummary(run),output:output.output||run.output||{},issues:run.state==='failed'&&Array.isArray(issues)?issues.filter(hasFailureReason):issues,work_done:output.work_done||run.work_done||[],fields,artifacts,actions:[]};
  const feedback=executionFeedback(work,run);
  return {key:'attempt-'+id,workflow_id:workId,
   title:executionTitle(run),executionRole:executionPosition(run)||run.employee_name||'',
   ...executionState(work,run),summary:contribution.summary,created_at:run.created_at,updated_at:run.updated_at,
   attempts:[contribution],contributions:[contribution],outputs:fields.map(field=>({kind:'field',key:field.key,run_id:id})),references:[],
   handoff:executionHandoff(work,run,fields),feedback:feedback?.summary||'',
   liveActivity:liveActivityMarkup(run),
   ...(report?{report_document:reportReference(report),reportDraft:isDraftReport(work,run)}:{})};
 }
 function attemptCurrent(selection){return S.sel===selection&&workspaceAccountCacheToken()===selection.attemptContext.account&&pipelineCurrent(selection.scope.source_pipeline_reference);}
 async function readAttempt(selection,{silent=false}={}){
  if(!attemptCurrent(selection)||selection.readingAttempt)return;
  selection.readingAttempt=true;
  if(!silent){selection.status='loading';selection.error='';render();}
  try{
   const context=selection.attemptContext;
   const {workflow:work}=await RunTeamsSourcePipelines.request('work',{reference:selection.scope.source_pipeline_reference,workflow_id:context.workflowId});
   if(!attemptCurrent(selection))return;
   if(Number(work?.id)!==context.workflowId||referenceKey(work?.snapshot_json?.pipeline_work?.reference)!==referenceKey(selection.scope.source_pipeline_reference))throw Error(text('executionUnavailable','执行记录归属未能确认。'));
   const run=work.employee_runs?.find(row=>Number(row.id)===context.runId);
   if(!run)throw Error(text('executionUnavailable','执行记录归属未能确认。'));
   RunTeamsSourcePipelines.retainActivity?.(selection,run);
   const result=attemptResult(work,run);
   if(silent&&JSON.stringify(result)===JSON.stringify(selectedResult(selection)))return;
   selection.data={results:[result]};selection.resultKey=result.key;selection.status='ready';
   position(selection);render();restore(selection);
   if(result.report_document)await loadReport(selection);
  }catch(error){
   if(!silent&&attemptCurrent(selection)){selection.status='error';selection.error=error.message;render();}
  }finally{selection.readingAttempt=false;}
 }
 function refreshOpenAttempt(selection=S.sel){
  if(!selection?.attemptContext||selection.status!=='ready')return;
  if(['running','needs_human','blocked'].includes(selectedResult(selection)?.state))return readAttempt(selection,{silent:true});
 }
 function openAttempt(runId){
  const previous=S.sel,work=previous?.type==='source-pipeline'&&previous.id==='work'?previous.workflow:null;
  const record=previous?.type==='core-results'&&!previous.attemptContext?selectedResult(previous):null;
  const reference=work?.snapshot_json?.pipeline_work?.reference||previous?.scope?.source_pipeline_reference;
  const runs=work?.employee_runs||record?.attempts||record?.contributions||[];
  if(!Number.isSafeInteger(runId)||!runs.some(run=>Number(run.id)===runId)||!pipelineCurrent(reference))return;
  const selection={type:'core-results',id:'execution-detail',scope:{source_pipeline_reference:reference,workflow_id:Number(work?.id||record.workflow_id)},status:'loading',data:null,
   returnTo:previous,attemptContext:{runId,workflowId:Number(work?.id||record.workflow_id),account:workspaceAccountCacheToken(),url:location.pathname+location.search+location.hash}};
  selectDetailWorkspace(selection);return readAttempt(selection);
 }
 function retryAttempt(){if(S.sel?.attemptContext)return readAttempt(S.sel);}
 function attemptSection(selection,key,title,body){
  if(!body)return '';
  return RunTeamsEmployeeDrawerHeader.section({id:'work-attempt-'+selection.attemptContext.runId+'-'+key,stateKey:key,title,body,
   collapsedSections:selection.collapsedAttemptSections,action:'RunTeamsWorkRecords.toggleAttemptSection',className:'source-work-group work-record-detail-section'});
 }
 function toggleAttemptSection(button){
  const selection=S.sel;
  if(!selection?.attemptContext||!button.isConnected||!button.closest('.work-record-execution-drawer .work-record-detail-section')||
   button.getAttribute('aria-controls')!=='work-attempt-'+selection.attemptContext.runId+'-'+button.dataset.settingsSectionKey)return;
  RunTeamsEmployeeDrawerHeader.toggleSection(button,selection.collapsedAttemptSections||=new Set());
 }
 function settingsOwner(selection){
  const previous=selection.returnTo,owner=previous?.type==='source-pipeline'?previous:previous?.returnTo;
  return owner?.type==='source-pipeline'&&owner.id==='work'&&Number(owner.workflow?.id)===selection.attemptContext?.workflowId?owner:null;
 }
 function returnFromAttempt(){
  const selection=S.sel;if(!selection?.attemptContext||!attemptCurrent(selection))return;
  const parent=selection.returnTo,s=RunTeamsSourcePipelines.current();
  selectDetailWorkspace(parent);setAppUrl(selection.attemptContext.url,true);render();restore(parent);
  if(parent.type==='source-pipeline'&&parent.id==='work')void RunTeamsSourcePipelines.refreshOpenWork(s,parent,{force:true});
 }
 function openPipelineTask(key){
  const owner=S.sel,result=(owner?.data?.results||[]).find(row=>row.key===key),reference=owner?.scope?.source_pipeline_reference;
  if(owner?.type!=='core-results'||!result||!pipelineCurrent(reference))return;
  position(owner);
  const back={selection:owner,reference,account:workspaceAccountCacheToken(),url:location.pathname+location.search+location.hash};
  setAppUrl(RunTeamsSourcePipelines.route(reference),true);
  return RunTeamsSourcePipelines.openWork(Number(result.workflow_id),{returnToRecords:back});
 }
 function taskBackMarkup(selection){
  const back=selection.returnToRecords;
  if(!back||back.account!==workspaceAccountCacheToken()||!pipelineCurrent(back.reference))return '';
  const label=text('backToTasks','返回任务列表');
  return `<button type="button" class="run-back" aria-label="${esc(label)}" title="${esc(label)}" onclick="RunTeamsWorkRecords.returnToTasks()">${ICON('back')}</button>`;
 }
 function returnToTasks(){
  const back=S.sel?.returnToRecords;if(!back||back.account!==workspaceAccountCacheToken()||!pipelineCurrent(back.reference))return;
  selectDetailWorkspace(back.selection);setAppUrl(back.url,true);render();restore(back.selection);
 }
 function openCurrentTask(){
  const owner=S.sel,reference=owner?.scope?.source_pipeline_reference,id=Number(owner?.scope?.workflow_id||selectedResult(owner)?.workflow_id);
  if(owner?.type!=='core-results'||!id||!pipelineCurrent(reference)||owner.attemptContext&&!attemptCurrent(owner))return;
  setAppUrl(RunTeamsSourcePipelines.route(reference),true);
  return RunTeamsSourcePipelines.openWork(id,{returnToRecords:settingsOwner(owner)?.returnToRecords||owner.returnTo?.returnToRecords});
 }
 function scopeForPanel(panel=S.conversationPanel){
  const directory=RunTeamsEmployeeDirectory;
  if(!panel||panel.loading||panel.error||panel.debug_preview)return null;
  const entry=directory.forPanel(panel);
  // A verified authoring receipt can resolve records before the directory loads.
  const authoring=panel.kind==='employee_design'?(panel.authoringEmployeeReference||entry?.source?.reference):null;
  if(!authoring&&!directory.employeePanel(panel))return null;
  const reference=directory.panelReference(panel)||authoring;
  if(reference)return directory.referenceKey(reference)?{employee_reference:reference}:null;
  return entry?.record?.id?{employee_id:Number(entry.record.id)}:null;
 }
 function target(panel=S.conversationPanel){
  const scope=scopeForPanel(panel);if(!scope)return null;
  const identity=scope.employee_reference?RunTeamsEmployeeDirectory.referenceKey(scope.employee_reference):scope.employee_id;
  return {scope,key:JSON.stringify([workspaceAccountCacheToken(),Number(panel.id),identity])};
 }
 function matches(selection,t){
  if(selection?.type!=='core-results'||!t)return false;
  return t.scope.employee_reference?RunTeamsEmployeeDirectory.referenceKey(selection.scope?.employee_reference)===RunTeamsEmployeeDirectory.referenceKey(t.scope.employee_reference):Number(selection.scope?.employee_id)===t.scope.employee_id;
 }
 function capture(){
  const t=target(),selection=S.sel;if(!matches(selection,t)||!selection.data)return;
  const node=document.querySelector('#rgDrawer .context-results-drawer > .right-detail-scroll');
  selection.recordScrollTop=node?.scrollTop||0;
  saved.delete(t.key);saved.set(t.key,selection);
  while(saved.size>30)saved.delete(saved.keys().next().value);
 }
 function controls(panel){
  const t=target(panel);if(!t)return '';
  const on=matches(S.sel,t);
  return RunTeamsShell.headerAction({label:'工作记录',labelKey:'workRecords.title',icon:ICON('clipboard-clock'),action:'RunTeamsWorkRecords.toggle()',className:'employee-records-trigger',selected:on});
 }
 function refreshForPanel(panel){
  if(S.conversationPanel!==panel||!matches(S.sel,target(panel)))return;
  return refreshContextResults(true);
 }
 async function toggle(){
  const t=target();if(!t)return;
  if(matches(S.sel,t)){capture();closeContextResults();return;}
  const previous=saved.get(t.key);
  if(previous){
   selectDetailWorkspace(previous);
   const url=new URL(contextResultsRoute(previous.scope),location.href);
   if(previous.resultKey)url.searchParams.set('delivery',previous.resultKey);
   setAppUrl(url.pathname+url.search+url.hash,true);render();
   requestAnimationFrame(()=>{if(S.sel===previous){const node=document.querySelector('#rgDrawer .context-results-drawer > .right-detail-scroll');if(node)node.scrollTop=previous.recordScrollTop||0;}});
   return refreshContextResults(true);
  }
  return openContextResults(t.scope);
 }
 function position(selection){
  const node=document.querySelector('#rgDrawer .context-results-drawer > .right-detail-scroll');
  if(!node)return;
  const key=selection.resultKey||'list';selection.recordPositions||={};selection.recordPositions[key]=node.scrollTop;
 }
 function restore(selection,focusKey=''){
  requestAnimationFrame(()=>{
   if(S.sel!==selection)return;
   const node=document.querySelector('#rgDrawer .context-results-drawer > .right-detail-scroll');
   if(!node)return;
   node.scrollTop=selection.recordPositions?.[selection.resultKey||'list']||0;
   if(focusKey&&!selection.resultKey&&document.activeElement===document.body){
    const card=Array.from(node.querySelectorAll('button[data-result-key]')).find(button=>button.dataset.resultKey===focusKey);
    card?.focus({preventScroll:true});
   }
  });
 }
 function reportState(selection,ref){
  const state=selection.reportDocuments?.[ref.id];
  return state?.documentKey===(ref.document_key||'')?state:null;
 }
 async function loadReport(selection=S.sel,force=false){
  const result=selection?.data?.results?.find(item=>item.key===selection.resultKey),ref=result?.report_document;
  if(S.sel!==selection||selection?.type!=='core-results'||!ref)return;
  const account=workspaceAccountCacheToken(),reportId=ref.id;selection.reportDocuments||={};
  const saved=reportState(selection,ref);
  if(saved?.status==='loading'&&saved.refRevision>=ref.revision||!force&&saved?.status==='ready'&&saved.doc?.revision>=ref.revision)return;
  const state={status:'loading',documentKey:ref.document_key||'',refRevision:ref.revision,doc:saved?.doc||null,error:''};selection.reportDocuments[reportId]=state;
  const current=()=>{
   if(S.sel!==selection||selection.resultKey!==result.key||workspaceAccountCacheToken()!==account||selection.reportDocuments[reportId]!==state)return false;
   const latest=selection.data?.results?.find(item=>item.key===result.key)?.report_document;
   return latest?.id===reportId&&(latest.document_key||'')===state.documentKey&&latest.revision===state.refRevision;
  };
  render();
  try{
   const doc=await api('/api/core/documents/'+Number(reportId));
   if(!current()){if(selection.reportDocuments[reportId]===state)state.status='idle';return;}
   if(doc?.error)throw Error(doc.error);
   if(!doc||typeof doc.content!=='string'||state.documentKey&&doc.document_key!==state.documentKey)throw Error('汇报文档归属未能确认');
   const minimumRevision=Math.max(Number(state.refRevision)||0,Number(state.doc?.revision)||0);
   if(minimumRevision&&(!Number.isSafeInteger(doc.revision)||doc.revision<minimumRevision))throw Error('最新汇报版本尚不可用');
   state.doc=doc;state.status='ready';
  }catch(error){if(current()){state.status='error';state.error=error.message||'汇报暂时无法读取';}else if(selection.reportDocuments[reportId]===state)state.status='idle';}
  if(current())render();
 }
 function reportMarkup(result,selection){
  const state=reportState(selection,result.report_document);
  if(!state?.doc&&state?.status!=='error')return documentReaderSkeletonMarkup(true,false,'workRecordDetail.reportLoading');
  const body=state?.doc?(typeof RunTeamsRichDocuments!=='undefined'&&RunTeamsRichDocuments.supported(state.doc)?RunTeamsRichDocuments.reportMarkup(state.doc,result.report_document.id):renderMarkdown(state.doc.content,{imageUrls:state.doc.native?.image_urls})):result.summary?`<section><h3 data-app-i18n="workRecordDetail.reportSummary">工作摘要</h3><p>${esc(result.summary)}</p></section>`:'';
  const retry='RunTeamsWorkRecords.loadReport(S.sel,true)';
  const [busyLabelKey,busyLabel]=state?.doc?
   ['workRecordDetail.reportRefreshing','正在更新汇报…']:['workRecordDetail.reportLoading','正在读取汇报…'];
  let notice='';
  if(state?.status==='error'){
   const title=state.doc?'无法读取最新汇报':'无法读取汇报';
   const titleKey=state.doc?'workRecordDetail.reportRefreshFailed':'workRecordDetail.reportFailed';
   notice=RunTeamsLoadFailure.markup({variant:'local',title,titleKey,note:state.doc?'这里显示的是上次载入的汇报。':'',noteKey:state.doc?'workRecordDetail.cachedReport':undefined,labelKey:'employeeHistory.retry',busyLabelKey,retry,focusFallback:'.context-results-drawer .work-record-report-open'});
  }else if(state.status==='loading'){
   notice=`<span class="sr-only" role="status" data-app-i18n="${busyLabelKey}">${busyLabel}</span>`;
  }
  return notice+body;
 }
 function reportActionMarkup(result,selection){
  const ref=result?.report_document;
  if(!ref||!reportState(selection,ref)?.doc)return '';
  return `<button type="button" class="work-record-report-open" data-record-report="${esc(result.key)}" onclick="RunTeamsWorkRecords.openReport(this.dataset.recordReport)" data-app-i18n="workRecordDetail.openReport">在文档中打开</button>`;
 }
 async function openReport(key){
  const owner=S.sel,result=owner?.data?.results?.find(item=>item.key===key),ref=result?.report_document;
  if(owner?.type!=='core-results'||owner.resultKey!==key||!ref||!reportState(owner,ref)?.doc)return;
  capture();
  return openDocumentReaderById(Number(ref.id));
 }
 function originTaskPending(selection,key){return openingOrigins.get(selection)?.has(key)===true;}
 function showOriginTaskProgress(button,pending){
  button.dataset.appI18n=pending?'workRecordDetail.openingTask':'workRecordDetail.openTask';
  button.textContent=pending?'正在打开原任务…':'前往原任务';
  button.setAttribute('aria-disabled',String(pending));
  button.setAttribute('aria-busy',String(pending));
  window.RunTeamsLocale?.apply(button);
 }
 async function openOrigin(key){
  const owner=S.sel,scope=workspaceAccountCacheToken(),result=owner?.data?.results?.find(r=>r.key===key);
  if(owner?.type!=='core-results'||!result||originTaskPending(owner,key))return;
  capture();
  if(owner.scope?.source_pipeline_reference)return openCurrentTask();
  if(result.origin?.kind==='employee_chat'&&Number(result.origin.chat_id)>0)return openConversationSession(Number(result.origin.chat_id),'general');
  const recordKey=owner.resultKey;
  const current=()=>S.sel===owner&&owner.resultKey===recordKey&&workspaceAccountCacheToken()===scope;
  const buttons=()=>[...document.querySelectorAll('[data-record-origin]')].filter(button=>button.dataset.recordOrigin===key);
  const notify=(key,fallback)=>toast(fallback,'err','workRecordDetail.'+key);
  const pending=openingOrigins.get(owner)||new Set();
  openingOrigins.set(owner,pending);pending.add(key);
  buttons().forEach(button=>showOriginTaskProgress(button,true));
  let workflow;
  try{workflow=await api(`/api/core/workflows/${Number(result.workflow_id)}`);}
  catch{if(current())notify('originalTaskFailed','无法打开原任务。请稍后重试。');return;}
  finally{pending.delete(key);if(current())buttons().forEach(button=>showOriginTaskProgress(button,false));}
  if(!current())return;
  if(!workflow||workflow.error)return notify('originalTaskFailed','无法打开原任务。请稍后重试。');
  if(Number(workflow.id)!==Number(result.workflow_id))return notify('originalTaskUnverified','无法确认原任务。请刷新工作记录后重试。');
  selectDetailWorkspace({type:'core-workflow',id:Number(result.workflow_id),workflow,returnTo:owner});render();
 }
 function returnFromOrigin(){
  const selection=S.sel?.returnTo;if(selection?.type!=='core-results')return;
  selectDetailWorkspace(selection);
  const url=new URL(contextResultsRoute(selection.scope),location.href);
  if(selection.resultKey)url.searchParams.set('delivery',selection.resultKey);
  setAppUrl(url.pathname+url.search+url.hash,true);render();restore(selection);
 }
 window.RunTeamsWorkRecords=Object.freeze({readResults,listTime,timeMarkup,stateMarkup,prose,rowMarkup,taskRowMarkup,taskResults,updateTaskList,taskDeliveries,attemptsMarkup,executionSummary,currentExecutionOutsideHistory,hasFailureReason,missingFailureReason,executionSectionMarkup,toggleExecutionSection,toggleEarlierExecutions,runtimeMarkup,openAttempt,retryAttempt,refreshOpenAttempt,attemptSection,toggleAttemptSection,returnFromAttempt,openPipelineTask,taskBackMarkup,returnToTasks,openCurrentTask,scopeForPanel,controls,toggle,refreshForPanel,capture,position,restore,loadReport,reportMarkup,reportActionMarkup,openReport,openOrigin,originTaskPending,returnFromOrigin,liveActivityMarkup});
 window.addEventListener('runteams:business-scope-will-change',()=>saved.clear());
 window.addEventListener('runteams:languagechange',()=>{
  for(const time of document.querySelectorAll('time[data-work-record-time]')){
   time.textContent=timeLabel(time.dataset.workRecordTime,time.hasAttribute('data-work-record-updated'),time.dataset.workRecordPreviousTime);
  }
 });
 window.addEventListener('pagehide',()=>saved.clear());
})();
