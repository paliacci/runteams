/* RunTeams conversation module. Own business UI here; shared shell and routes stay in index.html.
 * Classic script: functions retain their existing names and access the host's S/helpers at call time.
 * Do not run initialization here; do not redeclare S, api, ICON, esc, render or shared controls. */

/* module-function:conversationPanelWorkExample */
function conversationPanelWorkExample(value){
  let example;try{example=JSON.parse(value);}catch(error){return;}
  conversationPanelStarter(example.prompt,{skill_key:example.skill_key,requirements:example.requirements||[],bindings:{}});
}

/* module-function:conversationExampleMaterialRows */
function conversationExampleMaterialRows(panel=S.conversationPanel){
  const example=panel?.example_materials;if(!example)return [];
  const refs=(panel.attachments||[]).filter(item=>item.kind==='local_asset'),bindings=example.bindings||(example.bindings={}),requirements=example.requirements||[];
  const rows=requirements.map((item,index)=>({ ...item,index,candidates:refs.filter(ref=>ref.local_kind===item.type),selected:refs.find(ref=>ref.grant_id===Number(bindings[item.name])&&ref.local_kind===item.type)}));
  for(const type of ['file','folder']){
    const missing=rows.filter(row=>row.type===type&&!row.selected),used=new Set(rows.filter(row=>row.selected).map(row=>row.selected.grant_id)),available=refs.filter(ref=>ref.local_kind===type&&!used.has(ref.grant_id));
    if(missing.length===1&&available.length===1){missing[0].selected=available[0];bindings[missing[0].name]=available[0].grant_id;}
  }
  return rows;
}

/* module-function:conversationMaterialHint */
function conversationMaterialHint(item,kind){
  return String(item.hint||`选择${kind}，也可以拖入或粘贴。`).trim().replace(/^请(?:先)?选择/u,'选择').replace(/项目根目录/gu,'项目文件夹').replace(/也可(?!以)/gu,'也可以');
}

/* module-function:conversationExampleMaterialMenuItems */
function conversationExampleMaterialMenuItems(panel){
  const items=[];
  for(const row of conversationExampleMaterialRows(panel)){
    const folder=row.type==='folder',label=row.label||row.name;
    const optional=globalThis.RunTeamsLocale?.t('employeeMaterial.optional',{},'可选')||'可选';
    items.push({head:true,label:row.required?label:`${label} · ${optional}`});
    const choose=folder?'chooseFolder':'chooseFile';
    items.push({
      label:row.selected?'更换':folder?'选择文件夹':'选择文件',
      labelKey:'employeeMaterial.'+(row.selected?'replace':choose),
      icon:folder?'folder':'paperclip',disabled:panel.busy||panel.example_materials_picking,
      description:row.selected?.name||(row.hint?conversationMaterialHint(row,folder?'文件夹':'文件'):''),
      fn:()=>pickConversationExampleMaterial(row.index)
    });
    if(!row.selected)for(const ref of row.candidates){
      items.push({label:ref.name,description:'使用已添加的资料',descriptionKey:'employeeMaterial.useExisting',
        icon:folder?'folder':'paperclip',disabled:panel.busy,fn:()=>assignConversationExampleMaterial(row.index,ref.grant_id)});
    }
  }
  if(items.length)items.push({label:'取消资料选择',labelKey:'employeeMaterial.cancel',icon:'x',disabled:panel.busy,fn:clearConversationExampleMaterials});
  return items;
}

/* module-function:conversationExampleBindings */
function conversationExampleBindings(panel=S.conversationPanel){return Object.fromEntries(conversationExampleMaterialRows(panel).filter(row=>row.selected).map(row=>[row.name,row.selected.grant_id]));}

/* module-function:conversationEmployeeGuidance */
function conversationEmployeeGuidance(panel){
 if(!RunTeamsEmployeeDirectory.employeePanel(panel)||panel.kind!=='general')return null;
 const entry=RunTeamsEmployeeDirectory.forPanel(panel),employee=panel.employee_binding||entry?.record;
 if(panel.guidanceError||panel.guidanceReading)return {loading:true,error:panel.guidanceError,unconfirmed:true};
 if(!employee)return null;
 return {employee,unconfirmed:false};
}

function conversationEmployeeExamples(panel,guidance=conversationEmployeeGuidance(panel)){
 const entry=RunTeamsEmployeeDirectory.forPanel(panel);
 const works=guidance?.employee?.skills??entry?.source?.capabilities??panel.authoringCapabilities??[];
 return guidance?.loading?[]:workExampleItems(works).slice(0,3);
}

function conversationExampleIcon(icon){
  if(typeof icon==='string'&&/^[a-z][a-z0-9-]{0,47}$/.test(icon)&&document.getElementById('i-'+icon)?.localName==='symbol')return icon;
  return 'spark';
}

/* module-function:conversationNewAction */
function conversationNewAction(label,action,icon,description,id,copy={}){
  const tooltipId=description?`conversation_starter_${id}`:'';
  const heading=`<span class="conversation-new-action-heading"><span class="conversation-new-action-icon" aria-hidden="true">${ICON(icon)}</span><b${copy.title?` data-app-i18n="${esc(copy.title)}"`:''}>${esc(label)}</b></span>`;
  const tooltip=description?`<span class="conversation-new-action-description" id="${tooltipId}" role="tooltip"${copy.detail?` data-app-i18n="${esc(copy.detail)}"`:''}>${esc(description)}</span>`:'';
  return `<button type="button" class="conversation-new-action" onclick="${esc(action)}"${tooltipId?` aria-describedby="${tooltipId}"`:''}>${heading}${tooltip}</button>`;
}

/* module-function:conversationNewEmpty */
function conversationNewEmpty({actions='',notice='',noticeKey='',extra='',composer='',title='你想完成什么？',titleKey=''}={}){
  const options=actions?`<div class="conversation-new-actions" aria-label="建议操作" data-app-i18n-aria-label="employeeCreate.suggestions">${actions}</div>`:'';
  return `<div class="conversation-empty-state conversation-employee-guidance conversation-new-state" role="region" aria-labelledby="conversation_empty_title"><strong id="conversation_empty_title"${titleKey?` data-app-i18n="${esc(titleKey)}"`:''}>${esc(title)}</strong>${notice?`<p class="conversation-new-notice"${noticeKey?` data-app-i18n="${esc(noticeKey)}"`:''}>${esc(notice)}</p>`:''}${options}${extra}${composer?`<div class="rail-assistant-input conversation-home-composer">${composer}</div>`:''}</div>`;
}

/* module-function:conversationEmployeeEmpty */
function conversationEmployeeEmpty(panel,guidance,composer){
  if(guidance?.loading){
    const retry='ensureConversationEmployeeGuidance(true)';
    const feedback=RunTeamsLoadFailure.pending(retry)||(guidance.error?RunTeamsLoadFailure.markup({
      variant:'local',compact:true,title:'无法读取员工信息',titleKey:'employeeChat.guidanceFailed',
      label:'重试',labelKey:'conversationDetail.retry',busyLabelKey:'employeeChat.guidanceLoading',error:guidance.error,retry
    }):'');
    const extra=feedback?`<div class="conversation-new-actions">${feedback}</div>`:RunTeamsStaticPages.conversationWelcomeOptions('employee');
    return conversationNewEmpty({title:'想交办什么工作？',titleKey:'employeeChat.emptyTitle',extra,composer});
  }
  if(panel.kind==='employee_design'&&panel.context?.creator_local_source_id&&!panel.authoringCapabilities&&
     !RunTeamsEmployeeDirectory.forPanel(panel)&&RunTeamsEmployeeDirectory.isLoading()){
    return conversationNewEmpty({title:'想交办什么工作？',titleKey:'employeeChat.emptyTitle',extra:RunTeamsStaticPages.conversationWelcomeOptions('employee'),composer});
  }
  const examples=conversationEmployeeExamples(panel,guidance);
  const row=(example,index)=>conversationNewAction(example.title,`conversationPanelWorkExample(decodeURIComponent('${encodeURIComponent(JSON.stringify(example)).replace(/'/g,'%27')}'))`,conversationExampleIcon(example.icon),workExamplePreview(example.prompt),index);
  return conversationNewEmpty({title:'想交办什么工作？',titleKey:'employeeChat.emptyTitle',actions:examples.map(row).join(''),composer});
}

/* module-function:conversationDisplayMessages */
function conversationDisplayMessages(panel){
  const source=panel.messages||[],messages=[];
  const time=value=>{const date=docParseTime(value);return date?date.getTime():Infinity;};
  for(const [index,message] of source.entries()){
    const item={...message,originalIndex:index},events=message.metadata?.trace?.events||[];let start=0;
    if(message.metadata?.question_segment&&source[index-1]?.role==='user'){
      // Client send times retain milliseconds; persisted segment times may
      // only have seconds. The response still follows its originating input.
      const origin=messages.find(row=>row.originalIndex===index-1&&!row.transientQuestionSegment),sent=time(source[index-1].ts),segment=time(message.ts);
      if(Number.isFinite(sent)&&(!Number.isFinite(segment)||segment<sent))item.timelineTime=sent;
      else if(origin&&!Number.isFinite(sent)&&Number.isFinite(segment))origin.timelineTime=segment;
    }
    // Old receipts saved the whole assistant turn after its answers. Project
    // the recorded pre-answer process before each answer without rewriting it.
    if(!message.streaming&&!message.metadata?.question_segment){
      for(let position=0;position<events.length;position++){
        const event=events[position]?.event;if(event?.kind!=='user_input_resolved'||!event.id||!event.message?.id)continue;
        const answerIndex=source.findIndex(row=>row.role==='user'&&String(row.id)===String(event.message.id)&&row.metadata?.question_request_id===event.id&&!row.metadata?.question_prefix_id);
        if(answerIndex<0)continue;
        const trace=restoredAgentTrace({trace:{events:events.slice(start,position),complete:false}});
        if(trace)messages.push({role:'bot',text:'',ts:source[answerIndex].ts,trace,originalIndex:index,timelinePosition:answerIndex-.5,transientQuestionSegment:true});
        start=position+1;
      }
      if(start)item.trace=restoredAgentTrace({trace:{...message.metadata.trace,events:events.slice(start),duration_sec:undefined}});
    }
    messages.push(item);
  }
  for(const work of panel.work||[]){
    if(!work.trashed_at&&Number(work.workflow_id)>0)messages.push({role:'bot',text:work.state==='completed'?String(work.summary||''):'',ts:work.updated_at||work.created_at,
      workReference:Number(work.workflow_id),workTitle:work.title||'查看工作'});
  }
  return messages.sort((a,b)=>(a.timelineTime??time(a.ts))-(b.timelineTime??time(b.ts))||(a.timelinePosition??a.originalIndex??Infinity)-(b.timelinePosition??b.originalIndex??Infinity));
}

/* module-function:newLiveAgentMessage */
function newLiveAgentMessage(prefix="live"){return {role:"bot",text:"",ts:new Date().toISOString(),streaming:true,localId:prefix+Date.now()+Math.random().toString(16).slice(2),trace:newAgentTrace(),applied:[]};}

/* module-function:storedConversationMessage */
function storedConversationMessage(message){const m=message||{},metadata=m.metadata||{},systemNotice=metadata.system_notice||null;return {id:m.id,role:m.role,text:m.text,ts:m.ts||m.created_at||"",applied:m.applied||[],attachments:m.attachments||[],capabilities:m.capabilities||[],metadata,systemNotice,runCards:metadata.run_cards||[],contextRefs:Array.isArray(metadata.context_refs)?metadata.context_refs:[],trace:restoredAgentTrace(metadata)||(systemNotice?.kind==='stopped'?{complete:true,cancelled:true,steps:[]}:null),stopped:!!metadata.stopped||systemNotice?.kind==='stopped',ephemeral:!!metadata.failed};}

/* module-function:agentWorkStepDescription */
function agentWorkStepDescription(step){
  const kind=step.stepKind||'',meta=step.meta||{},raw=String(step.label||'');
  const nativeTool=String(meta.arguments?.tool_id||meta.tool||'').split(/__|\//).at(-1).match(/^runteams_[a-z0-9_]+$/)?.[0],args=meta.arguments?.tool_id&&meta.arguments.arguments&&typeof meta.arguments.arguments==='object'?meta.arguments.arguments:meta.arguments||{};
  if(kind==='image'||['imageView','image_view','view_image'].includes(raw)||['view_image','image_view'].includes(meta.tool))return {label:'查看图像',icon:'image',group:'image',category:'image'};
  if(nativeTool==='runteams_creator_source'){
    if(['schema','reference'].includes(args.action))return {label:'查看资料',icon:'search',group:'explore',category:'inspect'};
    if(args.action==='import')return {label:'导入资料',icon:'folder',group:'import',category:'import'};
    return {label:'处理资源',icon:'edit',group:'resource',category:'resource'};
  }
  if(['runteams_get_context','runteams_get_environment','runteams_get_employee','runteams_get_task'].includes(nativeTool))return {label:'查看资料',icon:'search',group:'explore',category:'inspect'};
  const native=String(meta.tool||raw),known={Read:['读取文件','search','read'],Glob:['查看文件','folder','list'],Grep:['搜索资料','search','search'],Bash:['运行命令','term','command'],Edit:['更新文件','edit','edit'],Write:['更新文件','edit','edit'],MultiEdit:['更新文件','edit','edit'],WebSearch:['搜索资料','search','search'],WebFetch:['浏览网页','globe','browse']};
  if(kind==='tool'&&known[native]){const [label,icon,category]=known[native];return {label,icon,group:'explore',category};}
  if(kind==='command'){
    const actions=Array.isArray(meta.commandActions)?meta.commandActions:[],type=actions[0]?.type;
    if(actions.length&&actions.every(action=>action?.type===type)){
      if(type==='read')return {label:'读取文件',icon:'search',group:'explore',category:'read'};
      if(type==='listFiles')return {label:'查看文件',icon:'folder',group:'explore',category:'list'};
      if(type==='search')return {label:'搜索资料',icon:'search',group:'search',category:'search'};
    }
    return {label:'运行命令',icon:'term',group:'explore',category:'command'};
  }
  if(kind==='file')return {label:'更新文件',icon:'edit',group:'file-change',category:'edit'};
  if(kind==='search')return {label:'搜索资料',icon:'search',group:'search',category:'search'};
  return {label:'执行操作',icon:'wrench',category:'operation'};
}

/* module-function:agentWorkStepIcon */
function agentWorkStepIcon(step){return ICON(agentWorkStepDescription(step).icon);}

/* module-function:agentWorkStepLabel */
function agentWorkStepLabel(step){const info=agentWorkStepDescription(step);return info.category==='image'?'查看 1 张图像':info.label;}

/* module-function:agentWorkActionContext */
function agentWorkActionContext(step){
  const meta=step.meta||{},wrapped=meta.arguments||{},args=wrapped.tool_id&&wrapped.arguments&&typeof wrapped.arguments==='object'?wrapped.arguments:wrapped;
  const tool=String(wrapped.tool_id||meta.tool||''),native=tool.split(/__|\//).at(-1).match(/^runteams_[a-z0-9_]+$/)?.[0],info=agentWorkStepDescription(step);
  const text=value=>{
    if(typeof value!=='string')return '';
    const clean=value.replace(/[\u0000-\u001f\u007f]+/g,' ').replace(/\s+/g,' ').trim();
    if(/(?:api[_-]?key|access[_-]?token|authorization|password|secret)\s*[:=]|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{12,}/i.test(clean))return '';
    return clean.length>140?clean.slice(0,139)+'…':clean;
  };
  const target=(key,text)=>({key,text});
  const currentFolder=target('currentFolder','当前文件夹');
  const basename=value=>{if(typeof value!=='string')return '';if(value==='.')return currentFolder;return text(value.replace(/[\\/]+$/,'').split(/[\\/]/).at(-1));};
  const host=value=>{try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?text(url.hostname):'';}catch(error){return '';}};
  const title=value=>text(value).replace(/https?:\/\/[^\s]+/g,url=>host(url)).replace(/(^|\s)((?:[A-Za-z]:)?[\\/][^\s"'<>]+)/g,(_,space,path)=>space+basename(path));
  const join=values=>{const items=[...new Set(values.filter(Boolean))];return items.length?{items:items.slice(0,2),count:items.length}:'';};
  const result={label:agentWorkStepLabel(step),target:''};
  if(native==='runteams_creator_source'){
    const schemas={employee:target('employeeSchema','员工规范'),skill:target('skillSchema','技能规范'),pipeline:target('pipelineSchema','智能体团队规范'),project:target('projectSchema','项目规范')},references={project:target('projectStructure','项目结构'),dependencies:target('dependencies','依赖约定'),authoring:target('authoring','创作指南')};
    if(args.action==='schema')result.target=Object.hasOwn(schemas,args.kind)?schemas[args.kind]:'';
    else if(args.action==='reference')result.target=Object.hasOwn(references,args.kind)?references[args.kind]:'';
    else if(args.action==='submit'){
      result.label='提交';result.target=Object.keys(args.files||{}).some(path=>/(?:^|\/)employee\.json$/.test(path))?target('employeeSource','员工源码'):target('assetSource','作品源码');
    }else if(args.action==='import')result.target=basename(args.path);
    return result;
  }
  const subjects={runteams_get_context:target('workContext','当前工作上下文'),runteams_get_environment:target('workEnvironment','工作环境'),runteams_get_employee:target('employeeInfo','员工资料'),runteams_get_task:target('taskInfo','任务资料'),runteams_get_pipeline:target('pipelineInfo','智能体团队资料'),runteams_list_pipelines:target('pipelineList','智能体团队目录')};
  if(subjects[native]){result.label='查看资料';result.target=subjects[native];return result;}
  const actions=Array.isArray(meta.commandActions)?meta.commandActions:[];
  if(info.category==='read'){
    const paths=actions.filter(action=>action?.type==='read').map(action=>action.path||action.name);
    if(tool==='Read')paths.push(args.file_path);
    const skills=paths.filter(path=>typeof path==='string'&&/(?:^|[\\/])(?:agent_skills|skills)[\\/].*[\\/]SKILL\.md$/i.test(path));
    if(skills.length&&skills.length===paths.length){result.label='读取技能';result.target=join(skills.map(path=>basename(path.replace(/[\\/]SKILL\.md$/i,''))));}
    else result.target=join(paths.map(basename));
  }else if(info.category==='list'){
    result.target=tool==='Glob'?text(args.pattern):join(actions.filter(action=>action?.type==='listFiles').map(action=>basename(action.path)));
  }else if(info.category==='search'){
    const action=actions.find(action=>action?.type==='search'),query=text(action?.query||args.pattern||args.query||meta.query||(step.stepKind==='search'&&String(step.label||'').startsWith('搜索 ')?String(step.label).slice(3):'')),where=basename(action?.path||args.path);
    result.target=query?{where,query}:where;
  }else if(info.category==='edit'){
    const changes=Array.isArray(meta.changes)?meta.changes:[];
    result.target=join([...changes.map(change=>basename(change?.path)),basename(args.file_path)]);
  }else if(info.category==='browse')result.target=host(args.url);
  else if(info.category==='image')result.target=basename(meta.path||args.path);
  else if(tool==='Bash')result.target=title(args.description);
  // A tool-supplied action title is an input, unlike output/error/status.
  if(!result.target&&info.category==='operation')result.target=title(args.title);
  return result;
}

/* module-function:agentWorkStepVisible */
function agentWorkStepVisible(step){const key=String(step?.label||"").replace(/[\s_-]+/g,"").toLowerCase();return !["usermessage","agentmessage","reasoning","plan"].includes(key);}

/* module-function:agentTraceActivity */
function agentTraceActivity(trace){const steps=(trace.steps||[]).filter(agentWorkStepVisible),byId=new Map(steps.map(step=>[String(step.id),step])),activity=(trace.activity||[]).map(item=>item.type==="step"?{...item,step:byId.get(String(item.id))}:item).filter(item=>item.type==="text"?String(item.text||"").trim():item.step);if(activity.length)return activity;return steps.map(step=>({type:"step",id:step.id,step}));}

/* module-function:agentTraceGroups */
function agentTraceGroups(trace){
  const items=[];
  for(const item of agentTraceActivity(trace)){
    if(item.type==='text'){items.push(item);continue;}
    const status=item.step.status||'running',last=items.at(-1),group=status==='cancelled'?'stopped':agentWorkStepDescription(item.step).category==='image'?'image':'activity';
    if(group!=='stopped'&&last?.type==='steps'&&last.group===group)last.steps.push(item.step);
    else items.push({type:'steps',group,steps:[item.step]});
  }
  return items;
}

const agentWorkVerbKeys=new Map([
  ["查看图像", "image"],
  ["查看资料", "inspect"],
  ["导入资料", "import"],
  ["处理资源", "resource"],
  ["读取文件", "read"],
  ["查看文件", "list"],
  ["浏览文件", "browseFiles"],
  ["搜索资料", "search"],
  ["运行命令", "command"],
  ["更新文件", "edit"],
  ["浏览网页", "browse"],
  ["执行操作", "operation"],
  ["提交", "submit"],
  ["读取技能", "readSkill"],
]);
function agentWorkSummaryLabel(summary){
  const locale=globalThis.RunTeamsLocale;
  if(!locale)return summary.label;
  if(summary.images){
    const action=locale.t(summary.images===1?'conversationTrace.oneImage':'conversationTrace.images',{count:summary.images});
    return summary.running?locale.t('conversationTrace.running',{action}):action;
  }
  const actions=(summary.verbs||[]).map(label=>locale.t('conversationTrace.'+agentWorkVerbKeys.get(label),{},label));
  if(!actions.length)return summary.label;
  if(summary.running)return locale.t('conversationTrace.running',{action:actions[0]});
  const list=new Intl.ListFormat(locale.language,{type:'conjunction',style:'short'}).format(actions);
  return summary.count?locale.t('conversationTrace.many',{actions:list,count:summary.count}):list;
}
/* module-function:agentWorkGroupSummary */
function agentWorkGroupSummary(item,active){
  const running=item.steps.findLast(step=>(step.status||'running')==='running');
  if(running&&active){
    const {label,icon,category}=agentWorkStepDescription(running);
    return {label:`正在${agentWorkStepLabel(running)}`,icon,running:true,verbs:[label],images:category==='image'?1:0};
  }
  if(item.group==='stopped')return {label:agentWorkStepLabel(item.steps[0]),icon:agentWorkStepDescription(item.steps[0]).icon,verbs:[agentWorkStepDescription(item.steps[0]).label]};
  if(item.group==='image')return {label:`查看 ${item.steps.length} 张图像`,icon:'image',images:item.steps.length};
  // This describes attempted actions, not the success of a command or the turn.
  let labels=[...new Set(item.steps.map(step=>agentWorkStepDescription(step).label))];
  if(labels.includes('读取文件')&&labels.includes('查看文件'))labels=labels.filter(label=>label!=='查看文件').map(label=>label==='读取文件'?'浏览文件':label);
  return {label:labels.length<=3?labels.join('、'):`${labels.slice(0,2).join('、')}等 ${item.steps.length} 项操作`,icon:agentWorkStepDescription(item.steps[0]).icon,verbs:labels.length<=3?labels:labels.slice(0,2),count:labels.length>3?item.steps.length:0};
}

function agentWorkTargetLabel(target){
  if(typeof target==='string')return target;
  const locale=globalThis.RunTeamsLocale;
  if(target.key)return locale?.t('conversationTrace.'+target.key,{},target.text)??target.text;
  if(target.items){
    const values=target.items.map(agentWorkTargetLabel);
    const items=locale?new Intl.ListFormat(locale.language,{type:'conjunction',style:'short'}).format(values):values.join('、');
    const count=target.count;
    return count>2?(locale?.t('conversationTrace.moreTargets',{items,count})??`${items}等 ${count} 项`):items;
  }
  const where=agentWorkTargetLabel(target.where);
  return where?`${where} · “${target.query}”`:`“${target.query}”`;
}

/* module-function:agentWorkStepMarkup */
function agentWorkStepMarkup(step){
  const action=agentWorkActionContext(step),verbKey=agentWorkVerbKeys.get(action.label);
  return `<div class="agent-work-step"><span class="agent-work-icon">${agentWorkStepIcon(step)}</span><span class="agent-work-label"><span class="agent-work-verb"${verbKey?` data-app-i18n="conversationTrace.${verbKey}"`:action.label==='查看 1 张图像'?` data-app-i18n="conversationTrace.oneImage" data-app-i18n-vars="${esc(JSON.stringify({count:1}))}"`:""}>${esc(action.label)}</span>${action.target?` <span class="agent-work-target"${typeof action.target==='object'?` data-agent-work-target="${esc(JSON.stringify(action.target))}"`:""}>${esc(agentWorkTargetLabel(action.target))}</span>`:''}</span></div>`;
}

/* module-function:agentTraceActivityMarkup */
function agentTraceActivityMarkup(trace,active=true){
  return agentTraceGroups(trace).map(item=>{
    if(item.type==='text')return `<div class="agent-work-text">${conversationMarkdown(item.text||'')}</div>`;
    const summary=agentWorkGroupSummary(item,active),status=summary.running?'running':'ended',label=agentWorkSummaryLabel(summary);
    return `<details class="agent-work-group" data-agent-disclosure="group:${esc(item.steps[0].id)}" ontoggle="conversationSyncActionLists(this)"><summary class="agent-work-action ${status}" data-agent-work-summary="${esc(JSON.stringify(summary))}" aria-label="${esc(label+'，展开或收起动作')}" data-app-i18n-aria-label="conversationDetail.toggleActions" data-app-i18n-vars="${esc(JSON.stringify({label}))}"><span class="agent-work-icon">${ICON(summary.icon)}</span><span class="agent-work-label">${summary.running?conversationProgressLabel(label):esc(label)}</span>${ICON('chev')}</summary><div class="agent-work-group-body" role="region" aria-label="动作列表" data-app-i18n-aria-label="conversationDetail.actionList" tabindex="-1" onscroll="conversationSyncActionList(this)">${item.steps.map(step=>agentWorkStepMarkup(step)).join('')}</div></details>`;
  }).join('');
}

/* module-function:conversationSyncActionList */
function conversationSyncActionList(list){
  if(!list||!list.closest('.agent-work-group')?.open||list.clientHeight<1)return;
  if(Number.isFinite(list.__agentRestoreScrollTop)){const top=list.__agentRestoreScrollTop;delete list.__agentRestoreScrollTop;list.scrollTop=top;}
  const overflow=list.scrollHeight>list.clientHeight+1;
  list.dataset.scrollable=String(overflow);
  list.style.setProperty('--agent-fade-top',overflow&&list.scrollTop>1?'12px':'0px');
  list.style.setProperty('--agent-fade-bottom',overflow&&list.scrollTop+list.clientHeight<list.scrollHeight-1?'12px':'0px');
  list.tabIndex=overflow?0:-1;
}

/* module-function:conversationSyncActionLists */
function conversationSyncActionLists(root){
  if(!root)return;
  requestAnimationFrame(()=>{if(root.isConnected===false)return;root.querySelectorAll('.agent-work-group-body').forEach(conversationSyncActionList);});
}

/* module-function:conversationCaptureProcessState */
function conversationCaptureProcessState(root){
  if(!root)return null;
  const nodes=[...root.querySelectorAll('[data-agent-disclosure]')],active=document.activeElement;
  return {known:nodes.map(node=>node.dataset.agentDisclosure),opened:nodes.filter(node=>node.open).map(node=>node.dataset.agentDisclosure),
    focus:nodes.find(node=>node.querySelector(':scope > summary')===active)?.dataset.agentDisclosure,
    listFocus:nodes.find(node=>node.querySelector(':scope > .agent-work-group-body')===active)?.dataset.agentDisclosure,
    scrolls:nodes.flatMap(node=>{const list=node.querySelector(':scope > .agent-work-group-body');return list?[[node.dataset.agentDisclosure,Number.isFinite(list.__agentRestoreScrollTop)?list.__agentRestoreScrollTop:list.scrollTop]]:[];})};
}

/* module-function:conversationRestoreProcessState */
function conversationRestoreProcessState(root,state){
  if(!root||!state)return;
  const nodes=new Map([...root.querySelectorAll('[data-agent-disclosure]')].map(node=>[node.dataset.agentDisclosure,node]));
  for(const key of state.opened)if(nodes.has(key))nodes.get(key).open=true;
  // Preserve an inspected action list when completion adds an outer history.
  // A history the user explicitly collapsed must stay closed.
  for(const key of state.opened){const history=nodes.get(key)?.closest('.agent-work-history');if(history&&!(state.known||[]).includes(history.dataset.agentDisclosure))history.open=true;}
  for(const [key,top] of state.scrolls||[]){const list=nodes.get(key)?.querySelector(':scope > .agent-work-group-body');if(list){list.__agentRestoreScrollTop=top;conversationSyncActionList(list);}}
  conversationSyncActionLists(root);
  if(state.focus)nodes.get(state.focus)?.querySelector(':scope > summary')?.focus({preventScroll:true});
  else if(state.listFocus)nodes.get(state.listFocus)?.querySelector(':scope > .agent-work-group-body')?.focus({preventScroll:true});
}

/* module-function:agentTraceDuration */
function agentTraceSeconds(trace){
  const raw=trace?.durationSec;let seconds=raw!==undefined&&raw!==null&&raw!==''?Number(raw):NaN;
  if(!Number.isFinite(seconds)){const started=Number(trace?.startedAt),finished=Number(trace?.finishedAt);seconds=started>0&&finished>=started?(finished-started)/1000:NaN;}
  return Number.isFinite(seconds)&&seconds>=0?Math.floor(seconds):null;
}
function agentTraceDuration(trace){
  const seconds=agentTraceSeconds(trace);if(seconds===null)return '';
  const hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60),rest=seconds%60,parts=[];
  if(hours)parts.push(`${hours}小时`);if(minutes)parts.push(`${minutes}分钟`);if(rest||!parts.length)parts.push(`${rest}秒`);return parts.join(' ');
}

function agentTraceLocalizedDuration(seconds){
  const locale=globalThis.RunTeamsLocale?.language||'zh-CN';
  const units=[['hour',Math.floor(seconds/3600)],['minute',Math.floor(seconds%3600/60)],['second',seconds%60]];
  const parts=units.filter(([,value])=>value>0);
  if(!parts.length)parts.push(['second',0]);
  return parts.map(([unit,value])=>new Intl.NumberFormat(locale,{style:'unit',unit,unitDisplay:'short'}).format(value)).join(' ');
}
globalThis.RunTeamsLocale?.onChange(()=>{
  for(const node of document.querySelectorAll('[data-agent-work-target]')){
    node.textContent=agentWorkTargetLabel(JSON.parse(node.dataset.agentWorkTarget));
  }
  for(const node of document.querySelectorAll('[data-agent-work-summary]')){
    const label=agentWorkSummaryLabel(JSON.parse(node.dataset.agentWorkSummary));
    const text=node.querySelector('.conversation-progress-label')||node.querySelector('.agent-work-label');
    if(text)text.textContent=label;
    node.dataset.appI18nVars=JSON.stringify({label});
    globalThis.RunTeamsLocale.apply(node);
  }
  for(const node of document.querySelectorAll('[data-agent-elapsed]')){
    node.dataset.appI18nVars=JSON.stringify({duration:agentTraceLocalizedDuration(Number(node.dataset.agentElapsed))});
    globalThis.RunTeamsLocale.apply(node);
  }
});

/* module-function:agentTraceMarkup */
function agentTraceMarkup(trace,streaming,surface=null,stopping=false,hasReply=false,messageKey=''){
  if(!trace)return streaming?conversationWaitingMarkup(''):'';
  const rows=agentTraceActivityMarkup(trace,!!streaming&&!trace.complete&&!trace.failed&&!trace.cancelled),seconds=agentTraceSeconds(trace),waiting=(trace.requests||[]).some(request=>request.status==='pending')&&!trace.runtimeStatus;
  if(streaming){
    const phase=trace.runtimeStatus?.phase;
    const [status,statusKey]=stopping?['正在停止','conversationDetail.stopping']:phase==='compacting'?['正在整理对话上下文','conversationDetail.compacting']:phase==='thinking'?['正在思考','conversationDetail.thinking']:[String(trace.current||''),''];
    const hasRunning=(trace.steps||[]).some(step=>(step.status||'running')==='running');
    return `<div class="agent-work-stream" aria-label="工作过程" data-app-i18n-aria-label="conversationDetail.workStream">${rows}${!waiting&&(!hasRunning||stopping||trace.runtimeStatus?.phase==='compacting')&&(!hasReply||stopping||trace.runtimeStatus?.phase==='compacting')?conversationWaitingMarkup(status,trace.startedAt,statusKey):''}</div>`;
  }
  const answered=(trace.requests||[]).map(request=>`<div class="agent-question-record">${request.questions.map(q=>`<p><b>${esc(conversationQuestionText(q))}</b><span>${esc((request.answers?.[q.id]?.answers||[]).join('、'))}</span></p>`).join('')}</div>`).join('');
  if(!rows&&!answered)return '';
  if(trace.cancelled||trace.failed||trace.complete!==true)return `<div class="agent-work-stream">${rows}${answered}</div>`;
  const duration=seconds===null?'':agentTraceLocalizedDuration(seconds);
  const summary=duration?`<span data-agent-elapsed="${seconds}" data-app-i18n="conversationDetail.workElapsed" data-app-i18n-vars="${esc(JSON.stringify({duration}))}">用时 ${esc(duration)}</span>`:'<span data-app-i18n="conversationDetail.workHistory">工作过程</span>';
  return `<details class="agent-work-history" data-agent-history="complete" data-agent-disclosure="history:${esc(trace.steps?.[0]?.id||messageKey||trace.startedAt||'complete')}" ontoggle="conversationSyncActionLists(this)"><summary>${summary}${ICON('chev')}</summary><div class="agent-work-history-body">${rows}${answered}${trace.truncated?'<p class="agent-trace-note" aria-label="系统提示" data-app-i18n-aria-label="conversationDetail.systemNotice" data-app-i18n="conversationDetail.traceIncomplete">此处保存的过程记录不完整。</p>':''}</div></details>`;
}

/* module-function:conversationApplyInteractionEvent */
function conversationApplyInteractionEvent(message,event){
  const trace=message.trace||(message.trace=newAgentTrace());
  if(event.kind==='runtime_status'){
    if(event.active)trace.runtimeStatus={phase:event.phase,id:event.id};
    else if(trace.runtimeStatus?.id===event.id){trace.runtimeStatus=null;trace.current='';}
    return true;
  }
  if(event.kind==='employee_app_authorization'){
    try{
      const url=new URL(event.url);
      if(['https://connect.composio.dev','https://app.composio.dev'].includes(url.origin)&&
         url.pathname.startsWith('/link/')&&!url.username&&!url.password&&typeof event.app==='string')
        trace.employeeAppAuthorization={id:event.id,app:event.app,url:url.href,state:'waiting',opened:event.opened===true};
    }catch{}
    return true;
  }
  if(event.kind==='employee_app_authorization_closed'){
    if(['connected','expired','interrupted'].includes(event.state)&&typeof event.app==='string')
      trace.employeeAppAuthorization={id:event.id,app:event.app,state:event.state};
    else if(trace.employeeAppAuthorization?.id===event.id)trace.employeeAppAuthorization=null;
    return true;
  }
  if(event.kind==='provider_error'){trace.providerError={code:event.code,willRetry:event.will_retry===true};return true;}
  if(event.kind==='rate_limits'){trace.rateLimits=event.windows||[];return true;}
  if(event.kind==='provider_error_cleared'){trace.providerError=null;return true;}
  if(event.kind==='reasoning_delta'&&!trace.runtimeStatus)trace.runtimeStatus={phase:'thinking',id:'reasoning-delta'};
  if(['reply_delta','work_delta','step'].includes(event.kind)&&trace.runtimeStatus?.phase!=='compacting')trace.runtimeStatus=null;
  if(!['user_input','user_input_resolved','user_input_expired','reply_reset'].includes(event.kind))return false;
  if(event.kind==='reply_reset'){message.text=String(event.text||'');return true;}
  trace.requests=trace.requests||[];
  if(event.kind==='user_input'){
    const request=event.request;if(!request?.id||!Array.isArray(request.questions))return true;
    if(!trace.requests.some(item=>item.id===request.id))trace.requests.push({...request});
    if(request.isBlocking!==false)trace.current='等待你的回答';
  }else{
    const request=trace.requests.find(item=>item.id===event.id);
    if(request){request.status=event.kind==='user_input_expired'?'expired':'answered';request.answers=event.answers||{};}
    if(event.kind!=='user_input_expired')trace.current='正在继续处理';
  }
  return true;
}

/* module-function:conversationQuestionState */
function conversationQuestionState(message,request){
  message.questionDrafts=message.questionDrafts||{};
  message.questionDraft=message.questionDrafts[request.id]||(message.questionDrafts[request.id]={id:request.id,page:0,selected:Object.fromEntries(request.questions.filter(q=>request.isBlocking===false&&(q.options||[]).length&&!q.multiSelect).map(q=>[q.id,[0]])),custom:{},error:'',sending:false,collapsed:false});
  return message.questionDraft;
}

/* module-function:conversationQuestionText */
function conversationQuestionText(q){
  if(q.id!=='external-app-action')return q.question;
  const raw=String(q.question||''),heading=raw.split(/\r?\n/,1)[0];
  const separator=heading.indexOf(' · ');
  const app=separator>0?heading.slice(0,separator).trim().slice(0,120):'';
  const action=separator>0?heading.slice(separator+3).trim():'';
  const label=(key,vars,fallback)=>globalThis.RunTeamsLocale?.t('conversationQuestion.'+key,vars,fallback)??fallback;
  if(app&&action==='List repositories for the authenticated user'){
    let args;
    try{args=JSON.parse(raw.slice(heading.length).trim());}catch{}
    const count=args?.per_page;
    if(Number.isInteger(count)&&count>0&&count<=100&&args.sort==='updated'&&args.direction==='desc'&&args.type==='all')
      return label('appListRecentRepositories',{app,count},`查看 ${app} 可访问的仓库，按最近更新时间取前 ${count} 个`);
    return label('appListRepositories',{app},`查看 ${app} 可访问的仓库`);
  }
  return app?label('appOperation',{app},`使用 ${app} 执行操作`):label('appOperationGeneric',{},'执行应用操作');
}

/* module-function:conversationQuestionPrompt */
function conversationQuestionPrompt(q){
  return q.id==='external-app-action'?esc(conversationQuestionText(q)):renderMarkdown(q.question);
}

/* module-function:conversationQuestionCard */
function conversationQuestionCard(message,index,surface){
  return (message.trace?.requests||[]).map(request=>{
    if(request.status!=='pending'||!message.streaming)return '';
    return `<div class="agent-question-entry"><div class="agent-question-prompt">${request.questions.map(conversationQuestionPrompt).join('')}</div><button type="button" class="agent-question-reopen" onclick="conversationQuestionOpen('${surface}',${index},'${esc(request.id)}')">${ICON('question')}<span data-app-i18n="conversationQuestion.answer">回答问题</span></button></div>`;
  }).join('');
}

/* module-function:conversationHasLiveQuestion */
function conversationHasLiveQuestion(surface){return (surface==='panel'?(S.conversationPanel?.messages||[]):(S.chatMsgs||[])).some(message=>message.streaming&&!message.stopping&&(message.trace?.requests||[]).some(request=>request.status==='pending'&&!message.questionDrafts?.[request.id]?.collapsed));}

/* module-function:conversationQuestionDock */
function conversationQuestionDock(surface){
  const messages=surface==='panel'?(S.conversationPanel?.messages||[]):(S.chatMsgs||[]);
  for(let index=messages.length-1;index>=0;index--){
    const message=messages[index];if(!message.streaming||message.stopping)continue;
    for(const request of message.trace?.requests||[]){
      if(request.status!=='pending'||message.questionDrafts?.[request.id]?.collapsed)continue;
      return `<div class="agent-question-dock" data-question-surface="${surface}">${conversationDockCard(message,index,surface,request)}</div>`;
    }
  }
  return `<div class="agent-question-dock" data-question-surface="${surface}" hidden></div>`;
}

/* module-function:conversationDockCard */
function conversationDockCard(message,index,surface,request){
  const state=conversationQuestionState(message,request),page=Math.min(state.page,request.questions.length-1),q=request.questions[page],options=q.options||[],selected=state.selected[q.id]||[],locked=state.sending,count=request.questions.length,valid=!!(selected.length||String(state.custom[q.id]||'').trim());
  const overview=surface==='panel'&&window.RunTeamsAssetOverview?.employee();
  const optionRows=(q,page)=>{
    const options=q.options||[],selected=state.selected[q.id]||[];
    return options.map((option,oi)=>`<button type="button" class="agent-question-option${selected.includes(oi)?' selected':''}" role="${q.multiSelect?'checkbox':'radio'}" aria-checked="${selected.includes(oi)}" ${locked?'disabled':''} onclick="conversationQuestionSelect('${surface}',${index},${oi},${page})"><span class="agent-question-number" aria-hidden="true">${oi+1}</span><span class="agent-question-option-copy"><b>${esc(option.label)}</b>${option.description?`<small>${esc(option.description)}</small>`:''}</span><span class="agent-question-check" aria-hidden="true">${selected.includes(oi)?ICON(q.multiSelect?'check':'arrow'):''}</span></button>`).join('');
  };
  const rows=optionRows(q,page);
  const errorKey=state.error==="请先选择或填写答案"?"required":state.error==="请回答这个问题"?"missing":state.error==="暂时无法确认答案是否已提交，可原样重试。"?"unknown":"";
  if(overview){
    const groups=request.questions.map((question,i)=>{
      const options=optionRows(question,i);
      const field=conversationQuestionInput(question,state.custom[question.id]||'',surface,index,locked,i);
      return `<div class="overview-question" data-answer-index="${i}"><div class="agent-question-title">${conversationQuestionPrompt(question)}</div>${options?`<div class="agent-question-options" role="${question.multiSelect?'group':'radiogroup'}" aria-label="${esc(conversationQuestionText(question))}">${options}</div>`:''}<label class="agent-question-custom${options?' is-inline':''}">${field}</label></div>`;
    }).join('');
    const complete=request.questions.every(item=>state.selected[item.id]?.length||String(state.custom[item.id]||'').trim());
    return `<section class="agent-question-card agent-question-docked" data-question-id="${esc(request.id)}">${groups}${state.error?`<p class="agent-question-error" role="alert">${esc(state.error)}</p>`:''}<footer class="agent-question-foot"><button type="button" class="agent-question-submit" ${locked||!complete?'disabled':''} aria-busy="${locked}" onclick="conversationQuestionSubmit('${surface}',${index})">${locked?conversationProgressLabel('发送中',false,'conversationQuestion.sending'):'<span data-app-i18n="assetOverview.submit">提交此项</span>'}</button></footer></section>`;
  }
  return `<section class="agent-question-card agent-question-docked ${options.length?'has-options':'is-free-input'}" data-question-id="${esc(request.id)}" data-question-page="${page}" aria-label="问题" data-app-i18n-aria-label="conversationQuestion.title" onkeydown="conversationQuestionKeydown(event,'${surface}',${index})"><header class="agent-question-head">${ICON('question')}<span><span data-app-i18n="conversationQuestion.title">问题</span>${count>1?` ${page+1} / ${count}`:''}</span><button type="button" class="agent-question-dismiss" aria-label="收起问题" data-app-i18n-aria-label="conversationQuestion.dismiss" ${locked?'disabled':''} onclick="conversationQuestionCollapse('${surface}',${index})">${ICON('x')}</button></header><div class="agent-question-scroll"><div class="agent-question-title">${conversationQuestionPrompt(q)}</div>${rows?`<div class="agent-question-options" role="${q.multiSelect?'group':'radiogroup'}" aria-label="${esc(conversationQuestionText(q))}">${rows}</div>`:''}${!options.length?`<label class="agent-question-custom">${conversationQuestionInput(q,state.custom[q.id]||'',surface,index,locked)}</label>`:''}</div>${state.error?`<p class="agent-question-error" role="alert"${errorKey?` data-app-i18n="conversationQuestion.${errorKey}"`:""}>${esc(state.error)}</p>`:''}<footer class="agent-question-foot">${options.length?`<label class="agent-question-custom is-inline">${ICON('edit')}${conversationQuestionInput(q,state.custom[q.id]||'',surface,index,locked)}</label>`:'<span></span>'}<div>${page>0?`<button type="button" class="agent-question-back" ${locked?'disabled':''} onclick="conversationQuestionPage('${surface}',${index},${page-1})" data-app-i18n="conversationQuestion.back">上一步</button>`:''}<button type="button" class="agent-question-back" ${locked?'disabled':''} onclick="conversationQuestionCollapse('${surface}',${index})" data-app-i18n="conversationQuestion.skip">跳过</button><button type="button" class="agent-question-submit" ${locked||!valid?'disabled':''} aria-busy="${locked}" onclick="conversationQuestionSubmit('${surface}',${index})">${locked?conversationProgressLabel('发送中',false,'conversationQuestion.sending'):`<span data-app-i18n="conversationQuestion.${page<count-1?'next':'send'}">${page<count-1?'下一步':'发送'}</span>`}</button></div></footer></section>`;
}

/* module-function:conversationQuestionOpen */
function conversationQuestionOpen(surface,index,id){
  const message=_conversationMsg(surface,index),request=message?.trace?.requests?.find(item=>item.id===id&&item.status==='pending');if(!request||!message.streaming)return;
  for(const other of (surface==='panel'?S.conversationPanel.messages:S.chatMsgs))for(const pending of other.trace?.requests||[])if(pending.status==='pending')conversationQuestionState(other,pending).collapsed=true;
  const active=document.activeElement;conversationQuestionState(message,request).collapsed=false;conversationQuestionRefresh(message,surface);
  requestAnimationFrame(()=>{if(_conversationMsg(surface,index)!==message||conversationQuestionState(message,request).collapsed||document.activeElement!==active&&document.activeElement!==document.body)return;document.querySelector(`[data-question-surface="${surface}"] textarea,[data-question-surface="${surface}"] input`)?.focus({preventScroll:true});});
}

/* module-function:conversationQuestionCollapse */
function conversationQuestionCollapse(surface,index){const message=_conversationMsg(surface,index),request=message&&conversationQuestionRequest(message,index);if(!request)return;const state=conversationQuestionState(message,request);if(state.sending)return;const active=document.activeElement;state.collapsed=true;conversationQuestionRefresh(message,surface);requestAnimationFrame(()=>{if(_conversationMsg(surface,index)===message&&state.collapsed&&(document.activeElement===active||document.activeElement===document.body))conversationInputElement(surface)?.focus({preventScroll:true});});}

/* Keep the active answer's ancestor chain mounted. Restoring focus after a
 * replacement still cancels IME composition, so only siblings may be replaced. */
function conversationPatchQuestionFocus(root,html){
 const field=document.activeElement,card=field?.closest?.('.agent-question-card'),dock=card?.closest('.agent-question-dock');
 if(!root?.contains(field)||!dock||!['INPUT','TEXTAREA'].includes(field.tagName))return false;
 const template=document.createElement('template');template.innerHTML=html;const next=template.content.firstElementChild;
 const nextDock=next?.matches('.agent-question-dock')?next:[...next?.querySelectorAll('.agent-question-dock')||[]].find(node=>node.dataset.questionSurface===dock.dataset.questionSurface);
 const nextCard=nextDock?.querySelector('.agent-question-card'),replacement=nextCard?.querySelectorAll('textarea,input')[[...card.querySelectorAll('textarea,input')].indexOf(field)];
 if(!replacement||dock.dataset.questionSurface!==nextDock.dataset.questionSurface||card.dataset.questionId!==nextCard.dataset.questionId||card.dataset.questionPage!==nextCard.dataset.questionPage||field.tagName!==replacement.tagName||field.type!==replacement.type)return false;
 const path=(node,end)=>{const nodes=[];for(;node;node=node.parentElement){nodes.unshift(node);if(node===end)return nodes;}return [];},before=path(field,root),after=path(replacement,next);
 if(!before.length||before.length!==after.length||before.some((node,i)=>node.tagName!==after[i].tagName||node.id!==after[i].id))return false;
 const attributes=(node,target)=>{for(const attr of [...node.attributes])if(!target.hasAttribute(attr.name))node.removeAttribute(attr.name);for(const attr of target.attributes)if(node.getAttribute(attr.name)!==attr.value)node.setAttribute(attr.name,attr.value);};
 for(let i=0;i<before.length-1;i++){
  const node=before[i],target=after[i],keep=before[i+1],nextKeep=after[i+1];attributes(node,target);
  const siblings=(parent,child,leading)=>{const nodes=[...parent.childNodes],index=nodes.indexOf(child);return leading?nodes.slice(0,index):nodes.slice(index+1);};
  for(const leading of [true,false]){const old=siblings(node,keep,leading),fresh=siblings(target,nextKeep,leading);if(old.length===fresh.length&&old.every((item,j)=>item.isEqualNode(fresh[j])))continue;old.forEach(item=>item.remove());fresh.forEach(item=>node.insertBefore(item.cloneNode(true),leading?keep:null));}
 }
 // Preserve the live value, selection, scroll and native composition state.
 for(const name of ['disabled','readonly','aria-label','placeholder','maxlength']){if(replacement.hasAttribute(name))field.setAttribute(name,replacement.getAttribute(name));else field.removeAttribute(name);}
 return true;
}

/* module-function:conversationRefreshQuestionDock */
function conversationRefreshQuestionDock(surface){
  const dock=document.querySelector?.(`[data-question-surface="${surface}"]`);if(!dock)return;
  const html=conversationQuestionDock(surface);if(dock.__questionMarkup===html)return;if(conversationPatchQuestionFocus(dock,html)){dock.__questionMarkup=html;return;}
  const active=document.activeElement,same=dock.contains(active),id=dock.querySelector('[data-question-id]')?.dataset.questionId,fields=[...dock.querySelectorAll('button,textarea,input')],focusIndex=same?fields.indexOf(active):-1,selection=same&&['INPUT','TEXTAREA'].includes(active.tagName)?[active.selectionStart,active.selectionEnd]:null;
  const template=document.createElement('template');template.innerHTML=html;const next=template.content.firstElementChild;next.__questionMarkup=html;dock.replaceWith(next);next.querySelectorAll('textarea').forEach(conversationQuestionResize);
  if(same&&id===next.querySelector('[data-question-id]')?.dataset.questionId){const control=next.querySelectorAll('button,textarea,input')[focusIndex];control?.focus({preventScroll:true});if(selection)control?.setSelectionRange?.(...selection);}
}

/* module-function:conversationQuestionAnswerMessage */
function conversationQuestionAnswerMessage(surface,saved,panel=null,prefix=null){
  if(!saved?.id)return;const messages=surface==='panel'?(panel||S.conversationPanel)?.messages:S.chatMsgs;if(!messages||messages.some(m=>String(m.id)===String(saved.id)))return;
  const live=messages.find(m=>m.streaming),index=live?messages.indexOf(live):messages.length;
  if(prefix?.id){
    const pending=(live?.trace?.requests||[]).filter(request=>request.status==='pending'&&request.id!==saved.metadata?.question_request_id);
    const before=messages.some(message=>String(message.id)===String(prefix.id))?[]:[storedConversationMessage(prefix)];
    messages.splice(index,0,...before,storedConversationMessage(saved));
    if(live){live.text='';live.trace={...newAgentTrace(),requests:pending,current:'正在继续处理'};live.ts=new Date(Math.max(Date.now(),new Date(saved.ts||saved.created_at||0).getTime()+1)).toISOString();delete live.questionDraft;delete live.questionDrafts;}
  }else messages.splice(live?index+1:index,0,storedConversationMessage(saved));
  if(surface!=='panel'||!panel||S.conversationPanel===panel)render();
}

/* module-function:conversationQuestionInput */
function conversationQuestionInput(question,value,surface,index,locked,page){
  const options=question.options||[],attrs=`${locked?'disabled':''} aria-label="${options.length?'其他答案':'你的回答'}" data-app-i18n-aria-label="conversationQuestion.${options.length?'other':'your'}" placeholder="${options.length?'或输入自己的答案':'输入答案…'}" data-app-i18n-placeholder="conversationQuestion.${options.length?'otherPrompt':'prompt'}" maxlength="8000" onfocus="conversationQuestionBindComposition(this)" oncompositionstart="this.dataset.composing='true'" oncompositionend="this.dataset.composing='false'" oninput="conversationQuestionResize(this);conversationQuestionCustom('${surface}',${index},this.value${page===undefined?'':','+page})"`;
  return question.isSecret?`<input type="password" autocomplete="off" ${attrs} value="${esc(value)}">`:`<textarea ${attrs} rows="1">${esc(value)}</textarea>`;
}

function conversationQuestionBindComposition(field){
 if(field.__questionCompositionBound)return;field.__questionCompositionBound=true;
 field.addEventListener('compositionstart',()=>{field.dataset.composing='true';});
 field.addEventListener('compositionend',()=>{field.dataset.composing='false';});
}

/* module-function:conversationQuestionResize */
function conversationQuestionResize(field){if(field?.tagName!=='TEXTAREA')return;field.style.height='auto';field.style.height=Math.min(148,Math.max(field.closest?.('.is-inline')?32:44,field.scrollHeight+2))+'px';}

/* module-function:conversationQuestionRequest */
function conversationQuestionRequest(message,index){return (message.trace?.requests||[]).find(item=>item.status==='pending'&&item.id===message.questionDraft?.id)||(message.trace?.requests||[]).find(item=>item.status==='pending');}

/* module-function:conversationQuestionSelect */
function conversationQuestionSelect(surface,index,option,page){
  const message=_conversationMsg(surface,index),request=message&&conversationQuestionRequest(message,index);if(!request)return;
  const state=conversationQuestionState(message,request),q=request.questions[page??state.page];if(!q||state.sending||message.stopping)return;
  const previous=state.selected[q.id]||[];state.selected[q.id]=q.multiSelect?(previous.includes(option)?previous.filter(value=>value!==option):[...previous,option]):[option];if(!q.multiSelect)state.custom[q.id]='';state.error='';
  conversationQuestionRefresh(message,surface);
}

/* module-function:conversationQuestionCustom */
function conversationQuestionCustom(surface,index,value,page){const message=_conversationMsg(surface,index),request=message&&conversationQuestionRequest(message,index);if(!request)return;const state=conversationQuestionState(message,request);if(state.sending||message.stopping)return;const q=request.questions[page??state.page];if(!q)return;state.custom[q.id]=value;if(value.trim()&&!q.multiSelect)state.selected[q.id]=[];state.error='';const dock=document.querySelector?.(`[data-question-surface="${surface}"]`);if(dock)dock.__questionMarkup=conversationQuestionDock(surface);const mounted=document.querySelector?.(`[data-question-id="${request.id}"]`);const send=mounted?.querySelector('.agent-question-submit');if(send)send.disabled=!(page===undefined?((state.selected[q.id]||[]).length||value.trim()):request.questions.every(item=>state.selected[item.id]?.length||String(state.custom[item.id]||'').trim()));mounted?.querySelector('.agent-question-error')?.remove();if(q.multiSelect)return;const card=document.querySelector(`[data-question-id="${request.id}"]`);(page===undefined?card:card?.querySelector(`[data-answer-index="${page}"]`))?.querySelectorAll('.agent-question-option').forEach(option=>{option.classList.remove('selected');option.setAttribute('aria-checked','false');option.querySelector('.agent-question-check').innerHTML='';});}

/* module-function:conversationQuestionRefresh */
function conversationQuestionRefresh(message,surface,panel=null){if(surface==='panel'&&panel&&S.conversationPanel!==panel)return;if(message.streaming)refreshLiveAgentMessage(message,surface,surface==='panel'?(panel||S.conversationPanel):null);else render();}

/* module-function:conversationQuestionPage */
function conversationQuestionPage(surface,index,page){const message=_conversationMsg(surface,index),request=message&&conversationQuestionRequest(message,index);if(!request)return;const state=conversationQuestionState(message,request);if(state.sending)return;state.page=Math.max(0,Math.min(request.questions.length-1,page));state.error='';conversationQuestionRefresh(message,surface);}

/* module-function:conversationQuestionSubmit */
async function conversationQuestionSubmit(surface,index){
  const panel=surface==='panel'?S.conversationPanel:null,message=_conversationMsg(surface,index),request=message&&conversationQuestionRequest(message,index);if(!request)return;
  const state=conversationQuestionState(message,request);if(state.sending||message.stopping)return;
  const values=q=>{const custom=String(state.custom[q.id]||'').trim(),selected=(state.selected[q.id]||[]).map(oi=>q.options[oi]?.label).filter(Boolean);return custom?(q.multiSelect?[...selected,custom]:[custom]):selected;};
  if(!values(request.questions[state.page]).length){state.error='请先选择或填写答案';conversationQuestionRefresh(message,surface);return;}
  if(!(surface==='panel'&&window.RunTeamsAssetOverview?.employee())&&state.page<request.questions.length-1){conversationQuestionPage(surface,index,state.page+1);return;}
  const missing=request.questions.findIndex(q=>!values(q).length);if(missing>=0){state.page=missing;state.error='请回答这个问题';conversationQuestionRefresh(message,surface);return;}
  const chatId=surface==='panel'?panel?.id:S.chatId,answers=Object.fromEntries(request.questions.map(q=>[q.id,{answers:values(q)}]));state.sending=true;state.error='';conversationQuestionRefresh(message,surface);
  try{let result=await api(`/api/chat/${chatId}/interaction`,'POST',{request_id:request.id,answers});for(let attempt=0;result.pending&&attempt<12;attempt++){if(request.status==='answered'){state.sending=false;return;}await new Promise(resolve=>setTimeout(resolve,500));result=await api(`/api/chat/${chatId}/interaction`,'POST',{request_id:request.id,answers});}if(result.error)throw Error(result.error);if(!result.accepted)throw Error('暂时无法确认答案是否已提交，可原样重试。');request.status='answered';request.answers=Object.fromEntries(request.questions.map(q=>[q.id,{answers:q.isSecret?['已填写']:values(q)}]));state.sending=false;message.trace.current='正在继续处理';if(surface==='panel'||S.chatId===chatId)conversationQuestionAnswerMessage(surface,result.message,panel,result.prefix_message);if(surface==='panel'||S.chatId===chatId)conversationQuestionRefresh(message,surface,panel);}
  catch(error){state.sending=false;state.error=error.message||'暂时无法确认答案是否已提交，可原样重试。';if(surface==='panel'||S.chatId===chatId)conversationQuestionRefresh(message,surface,panel);}
}

/* module-function:conversationQuestionKeydown */
function conversationQuestionKeydown(event,surface,index){
  if(event.isComposing||event.keyCode===229||event.target?.dataset?.composing==='true'||event.repeat)return;
  const editing=['TEXTAREA','INPUT'].includes(event.target?.tagName);
  if(editing){
    if(event.key!=='Enter'||event.shiftKey)return;
    if(typeof accountSettingsPrefs==='function'&&accountSettingsPrefs().send_mode==='meta-enter'&&!event.metaKey&&!event.ctrlKey)return;
    event.preventDefault();event.stopPropagation?.();conversationQuestionSubmit(surface,index);return;
  }
  const message=_conversationMsg(surface,index),request=message&&conversationQuestionRequest(message,index);if(!request)return;const state=conversationQuestionState(message,request),q=request.questions[state.page],count=(q.options||[]).length;
  if(/^[1-9]$/.test(event.key)&&Number(event.key)<=count){event.preventDefault();conversationQuestionSelect(surface,index,Number(event.key)-1);}
  else if(['ArrowDown','ArrowUp'].includes(event.key)&&count){event.preventDefault();const previous=(state.selected[q.id]||[])[0]??(event.key==='ArrowDown'?-1:0),next=(previous+(event.key==='ArrowDown'?1:-1)+count)%count;conversationQuestionSelect(surface,index,next);}
  else if(event.key==='Enter'){event.preventDefault();conversationQuestionSubmit(surface,index);}
}

/* module-function:conversationRestoreLiveInteraction */
function conversationRestoreLiveInteraction(message,state){
  const holder={text:'',trace:newAgentTrace()};for(const item of state.events||[])if(item.type==='agent_event')applyAgentStreamEvent(holder,item.event);
  for(const request of state.requests||[])conversationApplyInteractionEvent(holder,{kind:'user_input',request});
  message.trace=holder.trace;message.text=state.reply||'';
}

/* module-function:conversationWatchDetachedInteraction */
async function conversationWatchDetachedInteraction(panel,message){
  const account=typeof workspaceAccountCacheToken==='function'?workspaceAccountCacheToken():'';
  while(panel.interactionDetached){
    if(typeof workspaceAccountCacheToken==='function'&&account!==workspaceAccountCacheToken())return;
    try{
      const state=await api(`/api/chat/${panel.id}/interaction`);if(state.error)throw Error(state.error);
      if(typeof workspaceAccountCacheToken==='function'&&account!==workspaceAccountCacheToken())return;
      if(!state.active){const saved=await api(`/api/chat/${panel.id}`);if(saved.error)throw Error(saved.error);panel.messages=(saved.messages||[]).map(storedConversationMessage);panel.busy=false;panel.interactionDetached=false;if(S.conversationPanel===panel)render();return;}
      for(const receipt of state.answers||[])conversationQuestionAnswerMessage('panel',receipt.message,panel,receipt.prefix_message);
      conversationRestoreLiveInteraction(message,state);refreshLiveAgentMessage(message,'panel',panel);
    }catch(error){message.interactionReadError=error.message;}
    await new Promise(resolve=>setTimeout(resolve,1200));
  }
}

/* module-function:agentTraceHasDetails */
function agentTraceHasDetails(trace){return !!(trace&&agentTraceActivity(trace).length);}

/* module-function:conversationMessageFailure */
function conversationMessageFailure(message,index,surface,chatId=null){
  const notice=message?.systemNotice,kind=notice?.kind;
  if(message?.streaming)return '';
  const provider=conversationProviderError(message);
  if(provider){
    const messages=surface==='panel'?S.conversationPanel?.messages:S.chatMsgs;
    if(provider.code==='usageLimitExceeded'&&messages?.[messages.length-1]===message)return '';
    return conversationProviderNotice(message);
  }
  if(['plan_cancelled','work_state','action_result'].includes(kind))return '';
  if(!message?.ephemeral&&!notice?.text)return '';
  const text=notice?.text||(message.ephemeral?message.text:'');
  const key=message?.errorLocaleKey;
  return text?`<div class="conversation-system-error" role="status" aria-label="系统提示" data-app-i18n-aria-label="conversationDetail.systemNotice">${ICON('info')}<span${key?` data-app-i18n="${esc(key)}"`:""}>${esc(text)}</span></div>`:'';
}

function conversationAppAuthorization(message,surface){
  const auth=message.trace?.employeeAppAuthorization;
  if(!auth||auth.state==='interrupted'||message.stopping||message.stopped||auth.state==='waiting'&&!message.streaming)return '';
  const {state,app,opened,url}=auth;
  const [label,detail]=state==='connected'?['已连接','']:
    state==='expired'?['授权超时','可重新发起授权，再继续刚才的任务。']:
    opened?['等待授权','已打开授权页，请在浏览器中确认。']:
    ['等待授权','请打开授权页，在浏览器中确认。'];
  const detailKey=state==='expired'?'expiredHint':opened?'openedHint':'waitingHint';
  const action=state==='waiting'?
    `<a class="agent-question-reopen" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${ICON('link')}<span data-app-i18n="conversationApp.${opened?'reopen':'open'}">${opened?'重新打开':'打开授权页'}</span></a>`:
    state==='expired'&&surface!=='mock'?
    `<button type="button" class="agent-question-reopen" data-authorization-app="${esc(app)}" onclick="conversationRetryAppAuthorization('${surface}',this)" data-app-i18n="conversationApp.retry">重新授权</button>`:'';
  return `<section class="agent-question-entry conversation-app-auth">
    <div class="conversation-app-auth-copy" role="status"><div class="conversation-app-auth-heading">${ICON(state==='connected'?'check':'link')}<strong>${esc(app)}</strong><span data-app-i18n="conversationApp.${state}">${label}</span></div>
    ${detail?`<p data-app-i18n="conversationApp.${detailKey}">${detail}</p>`:''}</div>${action}</section>`;
}

function conversationRetryAppAuthorization(surface,button){
  const app=button.dataset.authorizationApp;
  const input=conversationInputElement(surface);
  if(!app||!input)return;
  if(surface==='panel'?S.conversationPanel?.busy:S.chatBusy)
    return toast('请等员工完成当前工作后再试。','info','conversationDetail.retryBusy');
  if(conversationInputValue(input).trim()){
    input.focus();
    return toast('请先发送或清空当前草稿。','info','conversationApp.draft');
  }
  const fallback=`请重新连接 ${app}，授权后继续刚才的任务。`;
  _sendConversationText(surface,globalThis.RunTeamsLocale?.t('conversationApp.retryRequest',{app},fallback)||fallback);
}

/* module-function:botConversationBody */
function botConversationBody(m,index,surface,chatId=null){
  const appCard=conversationAppAuthorization(m,surface);
  const waitingForAuthorization=appCard&&m.trace.employeeAppAuthorization.state==='waiting';
  const trace=waitingForAuthorization?'':agentTraceMarkup(m.trace,!!m.streaming,surface,!!m.stopping,!!m.text,m.id||m.localId||`${surface}:${index}`);
  const answer=m.text?(typeof RunTeamsReplyContent!=='undefined'?RunTeamsReplyContent.markup(m.text,{key:[typeof workspaceAccountCacheToken==='function'?workspaceAccountCacheToken():'preview',chatId||conversationChatId(surface)||surface,m.id||m.localId||index].join(':'),streaming:!!m.streaming},conversationMarkdown):`<div class="cmessage-markdown">${conversationMarkdown(m.text)}</div>`):'';
  const work=Number(m.workReference)||0,link=work?`<p class="cmessage-markdown"><a href="#" onclick="event.preventDefault();workItemOpenTask(${work})">${esc(m.workTitle||'查看工作')}</a></p>`:'';
  return `${conversationMessageFailure(m,index,surface,chatId)}${trace}${answer}${link}${appCard}${conversationQuestionCard(m,index,surface)}`;
}

/* module-function:copyConversationMessage */
async function copyConversationMessage(surface,index,button){const message=_conversationMsg(surface,index),text=String(message?.text||'');if(!text)return;try{await navigator.clipboard.writeText(message.role==='bot'&&typeof RunTeamsReplyContent!=='undefined'?RunTeamsReplyContent.plainText(text):text);conversationCopied(button);}catch(error){toast('无法复制。请手动选择要复制的文字。','err','conversationDetail.copyFailed');}}

/* module-function:editConversationMessage */
function editConversationMessage(surface,index){const message=_conversationMsg(surface,index);if(!message)return;const panel=surface==="panel"?S.conversationPanel:null;if(surface==="chat"?S.chatBusy:panel?.busy)return toast("请等助手完成当前工作后再编辑。","info","conversationDetail.editBusy");if(!message.id)return toast("这条消息尚未保存，暂时无法从这里重新开始。","info","conversationDetail.editUnsaved");confirmModal("从这条消息重新开始？","重新发送时，这条消息及后续对话会被替换。已执行的任务和智能体团队，以及文件改动都会保留。",()=>{const capabilities=(message.capabilities||[]).map(item=>({...item})),draft=conversationDraftFromMessage(message.text||"",capabilities),attachments=(message.attachments||[]).map(item=>({...item,localId:`rewind-${surface}-${item.id}`,reuseId:item.id}));clearConversationAttachments(surface);setConversationAttachments(surface,attachments);setConversationCapabilities(surface,capabilities);setConversationDraftValue(surface,draft);if(surface==="panel"){panel.messages=panel.messages.slice(0,index);panel.editRewind={messageId:message.id};}else{S.chatMsgs=S.chatMsgs.slice(0,index);S.chatRewind={messageId:message.id};}render();toast("修改消息，然后重新发送。","info","conversationDetail.editReady");requestAnimationFrame(()=>{const box=conversationInputElement(surface);if(box){setConversationInputValue(box,draft,capabilities);box.focus();restoreConversationSelection(surface,draft.length);}});},false,{
  titleKey:"conversationDetail.rewindTitle",messageKey:"conversationDetail.rewindMessage",
  action:"编辑消息",actionKey:"conversationDetail.editMessage",cancelKey:"trash.cancel",closeKey:"conversationDetail.close"
});}


const conversationFeedbackWrites=new Set();
function conversationFeedbackLabelKey(rating,pending){return 'conversationDetail.'+(rating==='up'?'removeUp':rating==='down'?'removeDown':'rate')+(pending?'Pending':'');}
function conversationFeedbackValue(message){return ['up','down'].includes(message?.metadata?.response_feedback)?message.metadata.response_feedback:null;}
function conversationReplyFeedback(event,surface,index,messageId){
  event.stopPropagation();
  const message=_conversationMsg(surface,index),chatId=conversationChatId(surface);
  if(!message||Number(message.id)!==Number(messageId)||message.role!=='bot'||message.streaming||!deviceChatKnown(chatId))return;
  const scope=workspaceAccountCacheToken(),key=scope+':'+chatId+':'+message.id;
  if(conversationFeedbackWrites.has(key))return;
  const anchor=event.currentTarget,selected=conversationFeedbackValue(message);
  const save=rating=>saveConversationReplyFeedback(surface,chatId,message,rating,scope,anchor);
  if(selected)return save(null);
  openMenu(anchor,[{label:'回复优秀',labelKey:'conversationDetail.helpful',icon:'response-thumb-up',fn:()=>save('up')},
    {label:'回复不佳',labelKey:'conversationDetail.unhelpful',icon:'response-thumb-down',fn:()=>save('down')}],{variant:'railItem',placement:'above'});
}
async function saveConversationReplyFeedback(surface,chatId,message,rating,scope,anchor){
  const current=()=>scope===workspaceAccountCacheToken(),visible=()=>current()&&String(conversationChatId(surface))===String(chatId);
  if(!visible())return;
  const key=scope+':'+chatId+':'+message.id;if(conversationFeedbackWrites.has(key))return;
  const buttons=()=>[...new Set([anchor,...(visible()?Array.from(document.querySelectorAll?.('[data-response-feedback-message]')||[]).filter(button=>String(button.dataset.responseFeedbackMessage)===String(message.id)&&String(button.dataset.responseFeedbackChat)===String(chatId)):[])])];
  conversationFeedbackWrites.add(key);anchor.disabled=true;anchor.setAttribute('aria-busy','true');
  try{
    const result=await api(`/api/chat/${chatId}/message-feedback`,'POST',{message_id:Number(message.id),rating});
    if(!current())return;
    if(result.error)throw Object.assign(Error(result.error),{feedbackRejected:true});
    if(Number(result.message_id)!==Number(message.id)||result.rating!==rating)throw Error('回复评价尚未确认');
    const apply=target=>{target.metadata={...(target.metadata||{})};if(rating)target.metadata.response_feedback=rating;else delete target.metadata.response_feedback;if(result.case?.case_id)target.metadata.response_feedback_case=result.case;};
    apply(message);
    if(visible()){
      const messages=surface==='panel'?S.conversationPanel?.messages:S.chatMsgs;
      const latest=messages?.find(row=>String(row.id)===String(message.id));if(latest)apply(latest);
      const label=(rating==='up'?'取消回复优秀评价':rating==='down'?'取消回复不佳评价':'评价回复')+(result.case?.sync_status==='pending'?'，案例待上传':'');
      const labelKey=conversationFeedbackLabelKey(rating,result.case?.sync_status==='pending');
      for(const button of buttons()){
        button.dataset.appI18nTitle=labelKey;button.dataset.appI18nAriaLabel=labelKey;
        button.innerHTML=ICON('response-thumb-'+(rating||'mixed'));button.title=label;button.setAttribute('aria-label',label);button.setAttribute('aria-pressed',String(!!rating));
        if(rating)button.removeAttribute('aria-haspopup');else button.setAttribute('aria-haspopup','menu');
        window.RunTeamsLocale?.apply(button);
      }
    }
  }catch(error){if(visible())toast(error.feedbackRejected?'无法保存评价。请重试。':'无法确认评价是否已保存。请刷新对话后查看。','err',error.feedbackRejected?'conversationDetail.feedbackFailed':'conversationDetail.feedbackUnconfirmed');}
  finally{conversationFeedbackWrites.delete(key);for(const button of buttons())if(button.isConnected){button.disabled=false;button.removeAttribute('aria-busy');}}
}

const conversationMessageTimeFormats={
  timeZh:new Intl.DateTimeFormat('zh-CN',{timeStyle:'short'}),
  timeEn:new Intl.DateTimeFormat('en',{timeStyle:'short'}),
  dateZh:new Intl.DateTimeFormat('zh-CN',{dateStyle:'long',timeStyle:'short'}),
  dateEn:new Intl.DateTimeFormat('en',{dateStyle:'long',timeStyle:'short'})
};

/* module-function:conversationMessageActions */
function conversationMessageActions(message,index,surface,options={}){
  if(message.workNotice||message.streaming||message.state==="sending")return "";
  const copy=message.text?`<button type="button" title="复制" data-app-i18n-title="conversationDetail.copy" aria-label="复制消息" data-app-i18n-aria-label="conversationDetail.copyMessage" onclick="copyConversationMessage('${surface}',${index},this)">${ICON("message-copy")}</button>`:"",
    edit=options.user?`<button type="button" title="编辑并重新发送" data-app-i18n-title="conversationDetail.editResend" aria-label="编辑并重新发送" data-app-i18n-aria-label="conversationDetail.editResend" onclick="editConversationMessage('${surface}',${index})">${ICON("message-edit")}</button>`:"";
  const date=docParseTime(message.ts);
  let time="";
  if(date){
    const vars=Object.fromEntries(Object.entries(conversationMessageTimeFormats).map(([key,formatter])=>[key,formatter.format(date)]));
    time=`<time class="cmessage-time" datetime="${esc(date.toISOString())}" title="${esc(vars.dateZh)}" aria-label="${esc('发送于 '+vars.dateZh)}" data-app-i18n="conversationDetail.messageClock" data-app-i18n-title="conversationDetail.messageDate" data-app-i18n-aria-label="conversationDetail.messageTime" data-app-i18n-vars="${esc(JSON.stringify(vars))}">${esc(vars.timeZh)}</time>`;
  }
  const rating=conversationFeedbackValue(message),chatId=conversationChatId(surface),
    rateable=!options.user&&message.role==='bot'&&message.id&&message.text&&!message.ephemeral&&!message.systemNotice&&typeof deviceChatKnown==='function'&&deviceChatKnown(chatId),
    label=(rating==='up'?'取消回复优秀评价':rating==='down'?'取消回复不佳评价':'评价回复')+(message.metadata?.response_feedback_case?.sync_status==='pending'?'，案例待上传':''),
    labelKey=conversationFeedbackLabelKey(rating,message.metadata?.response_feedback_case?.sync_status==='pending'),
    busy=rateable&&conversationFeedbackWrites.has(workspaceAccountCacheToken()+':'+chatId+':'+message.id),
    feedback=rateable?`<button type="button" data-response-feedback-message="${Number(message.id)}" data-response-feedback-chat="${esc(chatId)}" title="${label}" aria-label="${label}" data-app-i18n-title="${labelKey}" data-app-i18n-aria-label="${labelKey}" aria-pressed="${!!rating}" ${rating?'':'aria-haspopup="menu"'} ${busy?'disabled aria-busy="true"':''} onclick="conversationReplyFeedback(event,'${surface}',${index},${Number(message.id)})">${ICON('response-thumb-'+(rating||'mixed'))}</button>`:"";
  return copy||edit||time?`<div class="cmessage-actions" role="toolbar" aria-label="消息操作" data-app-i18n-aria-label="conversationDetail.actions">${options.user?time:""}${copy}${edit}${feedback}${options.user?"":time}</div>`:"";
}

/* module-function:conversationFailureCopy */
function conversationFailureCopy(text,copyOverride=''){
  const raw=String(text||"").trim();
  let copy="这次没有完成，请重试。";
  if(copyOverride)copy=copyOverride;else if(/本地服务(?:没有返回结果|没有响应)|connection refused|ECONNREFUSED/i.test(raw))copy="暂时无法连接服务，请稍后重试。";
  else if(/用量已达上限|rate.?limit|quota|429/i.test(raw))copy="当前模型暂时无法继续，请稍后重试或换个模型。";
  else if(/响应超时|timed?\s*out|timeout/i.test(raw))copy="等待时间过长，请重试。";
  else if(/连接暂时中断|network|fetch failed/i.test(raw))copy="连接已中断，回复未生成完整。";
  else if(/未登录|需要登录|认证失败|unauthori[sz]ed|invalid.api.key/i.test(raw))copy="模型连接需要重新登录，请检查设置。";
  else if(raw&&raw.length<=80&&!/[\n{}\[\]\/\\]|(?:Error|Exception|Traceback|http|api|cli|token|model_id)/i.test(raw))copy=raw;
  return `${esc(copy)}${raw&&raw!==copy?`<details class="cerror-details"><summary>查看错误详情</summary><code>${esc(raw)}</code></details>`:""}`;
}

/* module-function:conversationHasConfirmedReply */
function conversationHasConfirmedReply(messages,userMessageId){const index=(messages||[]).findIndex(message=>message.role==='user'&&userMessageId!=null&&String(message.id)===String(userMessageId));if(index<0)return false;for(const message of messages.slice(index+1)){if(message.role==='user'){if(message.metadata?.question_request_id)continue;break;}if(message.id&&(message.metadata?.trace?.complete===true||message.trace?.complete===true))return true;}return false;}

/* module-function:retryFailedConversationMessage */
function retryFailedConversationMessage(surface,index){
  const panel=surface==="panel"?S.conversationPanel:null,messages=surface==="panel"?(panel?.messages||[]):S.chatMsgs;
  if(surface==="panel"?panel?.busy:S.chatBusy)return toast("助手完成当前工作后再试","info","conversationDetail.retryBusy");
  const failed=messages[index];if(!failed||!failed.ephemeral)return toast("这条失败记录已经更新","info","conversationDetail.retryStale");
  if(failed.retryDraft){const retry=failed.retryDraft;clearConversationAttachments(surface);setConversationAttachments(surface,(retry.attachments||[]).slice());setConversationCapabilities(surface,(retry.capabilities||[]).map(item=>({...item})));setConversationDraftValue(surface,retry.text||"");messages.splice(index,1);render();requestAnimationFrame(()=>conversationSubmit(surface,()=>(surface==="panel"?sendConversationPanel():sendChat())));return;}
  // A rejected preflight has no persisted user message; preserve the restored draft.
  if(!failed.retryAccepted&&!failed.ts&&(surface==="panel"?panel?.input:S.chatDraft)){messages.splice(index,1);render();requestAnimationFrame(()=>conversationSubmit(surface,()=>(surface==="panel"?sendConversationPanel():sendChat())));return;}
  let userIndex=index-1;while(userIndex>=0&&messages[userIndex]?.role!=="user")userIndex--;
  if(userIndex<0){messages.splice(index,1);render();requestAnimationFrame(()=>conversationSubmit(surface,()=>(surface==="panel"?sendConversationPanel():sendChat())));return;}
  const message=messages[userIndex],capabilities=(message.capabilities||[]).map(item=>({...item})),draft=conversationDraftFromMessage(message.text||"",capabilities),attachments=(message.attachments||[]).map(item=>({...item,localId:`retry-${surface}-${item.id||userIndex}`,reuseId:item.id}));
  clearConversationAttachments(surface);setConversationAttachments(surface,attachments);setConversationCapabilities(surface,capabilities);setConversationDraftValue(surface,draft);
  if(surface==="panel"){panel.messages=panel.messages.slice(0,userIndex);panel.editRewind=message.id?{messageId:message.id}:null;panel.input=draft;}
  else{S.chatMsgs=S.chatMsgs.slice(0,userIndex);S.chatRewind=message.id?{messageId:message.id}:null;S.chatDraft=draft;}
  render();requestAnimationFrame(()=>conversationSubmit(surface,()=>(surface==="panel"?sendConversationPanel():sendChat())));
}

/* module-function:conversationMessages */
function conversationMessages(messages,options={}){
  const chatId=options.chatId,surface=options.surface||"chat",showActions=options.showActions!==false;
  let previous=null,hasUser=false;
  return (messages||[]).map((m,displayIndex)=>{
    const index=m.originalIndex??displayIndex,failure=m.role==='user'?'':conversationMessageFailure(m,index,surface,chatId);
    if(m.role==='bot'&&!m.text&&!m.streaming&&!m.ephemeral&&!m.workReference&&!failure&&!agentTraceHasDetails(m.trace)&&!m.trace?.employeeAppAuthorization&&!(m.trace?.requests||[]).length&&!m.stopped&&!m.trace?.cancelled)return '';
    const date=conversationMessageDate(m,hasUser?previous:null);if(m.role==="user")hasUser=true;if(!m.transientQuestionSegment&&!['debug','debug-draft'].includes(m.role))previous=m;
    if(m.role==="debug")return `<div class="conversation-debug-state-label" role="separator"><span>${esc(m.text)}</span></div>`;
    if(m.role==="user"){
      const capabilities=m.capabilities||[],files=chatMessageAttachments(m.attachments||[],chatId);
      const extensions=chatMessageCapabilities(capabilities),summary=m.metadata?.question_summary;
      const content=[
        summary?`<div class="cmessage-question-summary" title="${esc(summary)}">${esc(summary)}</div>`:"",
        m.text?`<div class="cmessage-text">${chatMessageText(m.text,capabilities)}</div>`:"",
        extensions?`<div class="cmessage-context">${extensions}</div>`:""
      ].join("");
      const bubble=content?`<div class="cbubble ${extensions?"has-context":"text-only"}">${content}</div>`:"";
      return `${date}<div class="cmsg user ${esc(m.state||'')}" role="article" aria-label="你的消息" data-app-i18n-aria-label="conversationDetail.userMessage" ${m.localId?`data-local-message="${esc(m.localId)}"`:""}><div class="cmessage-stack">${files}${bubble}${showActions?conversationMessageActions(m,index,surface,{user:true}):""}</div></div>`;
    }
    const waiting=!!m.streaming&&!m.text&&!agentTraceHasDetails(m.trace)&&!(m.trace?.requests||[]).some(item=>item.status==='pending'),identity=conversationMessageIdentity(surface,{waiting});
    if(m.ephemeral){const unconfirmed=typeof m.retryAccepted==='boolean';return `<div class="cmsg bot" ${unconfirmed?'data-reply-unknown="true"':''} role="article" aria-label="${unconfirmed?'回复结果待确认':'回复失败'}" data-app-i18n-aria-label="conversationDetail.${unconfirmed?'replyUnknown':'replyFailed'}">${identity}<div class="cmessage-stack"><div class="cbubble">${m.systemNotice&&m.text?`<div class="cmessage-markdown">${conversationMarkdown(m.text)}</div>`:''}${failure}${agentTraceMarkup(m.trace,false)}</div></div></div>`;}
    return `<div class="cmsg bot${m.streaming?' streaming':''}${waiting?' is-waiting':''}" role="article" aria-label="${m.systemNotice&&!m.text?'系统提示':'助手消息'}" data-app-i18n-aria-label="conversationDetail.${m.systemNotice&&!m.text?'systemNotice':'assistantMessage'}" ${m.localId?`data-live-agent="${esc(m.localId)}"`:''}>${identity}<div class="cmessage-stack"><div class="cbubble">${botConversationBody(m,index,surface,chatId)}</div>${showActions?conversationMessageActions(m,index,surface):''}</div></div>`;
  }).join("");
}

/* module-function:conversationThinkingElapsed */
function conversationThinkingElapsed(startedAt){const started=Number(startedAt)||Date.now(),seconds=Math.max(0,Math.floor((Date.now()-started)/1000));return {seconds,label:`正在处理 ${agentTraceDuration({durationSec:seconds})}`};}

/* module-function:conversationThinking */
function conversationThinking(label="",startedAt=Date.now()){
  const surface=S.conversationPanel?"panel":"chat";
  return `<div class="cmsg bot thinking is-waiting">${conversationMessageIdentity(surface,{waiting:true})}<div class="cmessage-stack"><div class="cbubble">${conversationWaitingMarkup(label,startedAt)}</div></div></div>`;
}

/* module-function:liveAgentMessageRenderKey */
function liveAgentMessageRenderKey(message){const trace=message.trace||{};return JSON.stringify([message.text||"",message.systemNotice||null,!!message.streaming,!!message.stopped,!!message.stopping,trace.current||"",trace.runtimeStatus||null,trace.providerError||null,trace.rateLimits||[],!!trace.complete,!!trace.cancelled,trace.reasoning||"",trace.plan||"",trace.steps||[],trace.activity||[],trace.requests||[],trace.employeeAppAuthorization||null,message.questionDraft||null,message.applied||[]]);}

/* module-function:refreshLiveAgentMessage */
function refreshLiveAgentMessage(message,surface,panel=null){
  if(typeof refreshRailChatActivity==='function')refreshRailChatActivity();
  const key=message.localId;if(_liveAgentRenderPending.has(key))return;_liveAgentRenderPending.add(key);
  requestAnimationFrame(()=>{
    if(typeof RunTeamsEmployeeDirectory!=='undefined')RunTeamsEmployeeDirectory.paintStatus?.();
    _liveAgentRenderPending.delete(key);const visible=surface!=="panel"||!panel||S.conversationPanel===panel,scroll=visible&&surface==="panel"?document.getElementById("conversation_scroll"):null,followLatest=conversationScrollNearBottom(scroll),row=visible?document.querySelector(`[data-live-agent="${key}"] .cbubble`):null,renderKey=liveAgentMessageRenderKey(message),messages=panel?(panel.messages||[]):(S.chatMsgs||[]),messageIndex=messages.indexOf(message);
    if(row&&row.__liveAgentRenderKey!==renderKey){
      const processState=conversationCaptureProcessState(row);
      const active=document.activeElement,card=row.querySelector('.agent-question-card'),sameFocus=card?.contains(active),controls=card?[...card.querySelectorAll('button,textarea')]:[],focusIndex=sameFocus?controls.indexOf(active):-1,selection=sameFocus&&['TEXTAREA','INPUT'].includes(active.tagName)?[active.selectionStart,active.selectionEnd]:null,oldQuestion=card?.dataset.questionId,oldPage=card?.dataset.questionPage;
      row.innerHTML=botConversationBody(message,messageIndex,surface);
      conversationRestoreProcessState(row,processState);
      const waiting=!!message.streaming&&!message.text&&!agentTraceHasDetails(message.trace)&&!(message.trace?.requests||[]).some(item=>item.status==='pending'),article=row.closest('.cmsg');article?.classList.toggle('is-waiting',waiting);article?.classList.toggle('streaming',!!message.streaming);
      const nextCard=row.querySelector('.agent-question-card');
      if(nextCard&&sameFocus&&oldQuestion===nextCard.dataset.questionId&&oldPage===nextCard.dataset.questionPage){const control=nextCard.querySelectorAll('button,textarea')[focusIndex];control?.focus({preventScroll:true});if(selection&&['TEXTAREA','INPUT'].includes(control?.tagName))control.setSelectionRange(...selection);}
      else if(nextCard&&(sameFocus||!oldQuestion&&(!active||active===document.body||active.id==='conversation_box'||active.id==='cbox')))nextCard.querySelector('[role="radio"],[role="checkbox"],textarea,input')?.focus({preventScroll:true});
      row.__liveAgentRenderKey=renderKey;
    }else if(!row&&visible)render();
    if(visible)conversationRefreshQuestionDock(surface);
    if(surface==="panel"){if(!visible)return;if(followLatest)scrollConversationPanel();else syncConversationScrollState(scroll);}else scrollChat();
  });
}

/* module-function:finalizeStoppedAgentMessage */
function finalizeStoppedAgentMessage(message){if(!message)return;const trace=message.trace||(message.trace=newAgentTrace());message.text=message.text||"";message.systemNotice={kind:"stopped",text:"已停止。"};message.streaming=false;message.stopped=true;message.stopping=false;trace.complete=true;trace.cancelled=true;trace.current="已停止";trace.finishedAt=Date.now();(trace.steps||[]).forEach(step=>{if(step.status==="running")step.status="cancelled";});}

/* module-function:stopLiveAgentMessageImmediately */
function stopLiveAgentMessageImmediately(messages){const message=[...(messages||[])].reverse().find(item=>item&&item.role!=="user"&&item.streaming);if(!message)return null;const snapshot={message,text:message.text,streaming:message.streaming,stopped:message.stopped,stopping:message.stopping,trace:JSON.parse(JSON.stringify(message.trace||newAgentTrace()))};message.stopping=true;message.trace.current="正在停止";return snapshot;}

/* module-function:restoreOptimisticallyStoppedMessage */
function restoreOptimisticallyStoppedMessage(snapshot){if(!snapshot?.message)return;const message=snapshot.message;message.text=snapshot.text;message.streaming=snapshot.streaming;message.stopped=snapshot.stopped;message.stopping=snapshot.stopping;message.trace=snapshot.trace;}

/* module-function:_sendConversationText */
function _sendConversationText(surface,text){
  if(surface==="mock")return;
  ;
  if(surface==="chat"){S.chatDraft=text;const box=document.getElementById("cbox");if(box)setConversationInputValue(box,text,S.chatCapabilities);conversationSubmit(surface,()=>sendChat());return;}
  const panel=S.conversationPanel;if(!panel||panel.busy)return;panel.input=text;const box=document.getElementById("conversation_box");if(box)setConversationInputValue(box,text,panel.capabilities||[]);conversationSubmit(surface,()=>sendConversationPanel());
}

/* module-function:_conversationMsg */
function _conversationMsg(surface,index){const msgs=(surface==="chat"?S.chatMsgs:(S.conversationPanel&&S.conversationPanel.messages));return msgs&&msgs[index];}

/* module-function:chatModelItems */
function chatModelItems(cfg){
  cfg=cfg||S.chatCfg;
  const items=[];
  S.channels.filter(c=>modelChannelAvailable(c)&&(channelCatalog(c).models||[]).length).forEach(c=>{
    const current=c.id===cfg.channel_id?effectiveModelValue(c,cfg.model):effectiveModelValue(c,"");
    items.push({head:true,label:c.provider_label||c.name,provider:c.provider});
    modelItems(c,current).forEach(model=>items.push({value:String(c.id)+"::"+model.value,label:model.label}));
  });
  return items;
}

/* module-function:chatRouteValue */
function chatRouteValue(cfg){ const c=cfg&&S.channels.find(x=>String(x.id)===String(cfg.channel_id));return cfg&&cfg.channel_id!=null&&cfg.model?String(cfg.channel_id)+"::"+effectiveModelValue(c,cfg.model):""; }

/* module-function:chatAttachmentUrl */
function chatAttachmentUrl(item,chatId=S.chatId){ if(item.kind==="local_asset")return "";return item.preview||((chatId&&chatId!=="new"&&item.id)?`/api/chat/${chatId}/attachment/${item.id}`:""); }

function conversationAttachmentFolderCopy(item){
  const count=Number(item.file_count)||0,size=formatFileSize(item.size);
  return {key:count===1?"conversationAttachment.folderFile":"conversationAttachment.folderFiles",vars:{count,size},text:`${count} 个文件 ${size}`};
}

/* module-function:chatMessageAttachments */
function chatMessageAttachments(items,chatId=S.chatId){
  if(!items.length)return "";
  const markup=items.map(item=>{
    if(item.kind==="local_asset"){
      const folder=item.local_kind==="folder";
      return `<span class="cmessage-file local-reference">${ICON(folder?"folder":"doc")}<span><b lang="${/[\u3400-\u9fff]/.test(item.name)?"zh":"en"}">${esc(item.name)}</b><small data-app-i18n="localReference.${folder?"folderDetail":"fileDetail"}">${folder?"文件夹":"文件"} · 仅在这台电脑使用</small></span></span>`;
    }
    const url=chatAttachmentUrl(item,chatId);
    if(item.kind==="image"&&url)return `<a class="cmessage-image" href="${url}" target="_blank" rel="noopener noreferrer"><img src="${url}" alt="${esc(item.name)}"></a>`;
    const folder=item.kind==="folder",copy=folder?conversationAttachmentFolderCopy(item):null;
    const detail=copy?`<small data-app-i18n="${copy.key}" data-app-i18n-vars="${esc(JSON.stringify(copy.vars))}">${esc(copy.text)}</small>`:url?`<small>${esc(formatFileSize(item.size))}</small>` :`<small data-app-i18n="conversationAttachment.unavailable" data-app-i18n-vars="${esc(JSON.stringify({size:formatFileSize(item.size)}))}">附件不可用 · ${esc(formatFileSize(item.size))}</small>`;
    const body=`${ICON(folder?"folder":"doc")}<span><b>${esc(item.name)}</b>${detail}</span>`;
    return folder||!url?`<span class="cmessage-file ${folder?"folder":"unavailable"}">${body}</span>`:`<a class="cmessage-file" href="${url}" target="_blank" rel="noopener noreferrer">${body}</a>`;
  }).join("");
  return `<div class="cmessage-files">${markup}</div>`;
}

/* module-function:chatMessageCapabilities */
function chatMessageCapabilities(items){const global=(items||[]).filter(item=>!item.mention_token&&!item.mention_id);if(!global.length)return "";return `<div class="cmessage-capabilities">${global.map(item=>`<span>${conversationCapabilityIcon(item)}<b>${esc(item.label||item.id)}</b></span>`).join("")}</div>`;}

/* module-function:chatMessageText */
function chatMessageText(text,items){let html=esc(text||"");(items||[]).filter(item=>item.mention_token).forEach(item=>{const token=esc(item.mention_token),chip=`<span class="cmessage-capability-ref">${conversationCapabilityIcon(item)}<b lang="${/[\u3400-\u9fff]/.test(item.label||item.id)?"zh":"en"}">${esc(item.label||item.id)}</b></span>`;html=html.split(token).join(chip);});return html;}

/* module-function:acceptedChatFile */
function acceptedChatFile(file){ const ext=(file.name.match(/\.[^.]+$/)||[""])[0].toLowerCase();return CHAT_FILE_EXTENSIONS.includes(ext); }

/* module-function:conversationAttachments */
function conversationAttachments(surface){return (surface==="panel"?((S.conversationPanel&&S.conversationPanel.attachments)||[]):S.chatAttachments);}

/* module-function:conversationCapabilities */
function conversationCapabilities(surface){return (surface==="panel"?((S.conversationPanel&&S.conversationPanel.capabilities)||[]):S.chatCapabilities);}

/* module-function:conversationDraftValue */
function conversationDraftValue(surface){return (surface==="panel"?((S.conversationPanel&&S.conversationPanel.input)||""):(S.chatDraft||""));}

/* module-function:conversationChatId */
function conversationChatId(surface){return (surface==="panel"?(S.conversationPanel&&S.conversationPanel.id):S.chatId);}

/* module-function:conversationChannelId */
function conversationChannelId(surface){return (surface==="panel"?(S.conversationPanel&&S.conversationPanel.channel_id):(S.chatCfg&&S.chatCfg.channel_id));}

/* module-function:conversationCapabilityKey */
function conversationCapabilityKey(item){return `${item.kind}:${item.id}`;}

/* module-function:conversationCapabilityIcon */
function conversationCapabilityIcon(item){return item.icon_url?`<img src="${esc(item.icon_url)}" alt="">`:ICON(item.kind==="mcp"?"flow":"package");}

/* module-function:conversationMentionId */
function conversationMentionId(){return `m${Date.now().toString(36)}${(++_conversationMentionSeq).toString(36)}`;}

/* module-function:conversationCapabilityMarker */
function conversationCapabilityMarker(id){return CAPABILITY_MARKER_OPEN+id+CAPABILITY_MARKER_CLOSE;}

/* module-function:conversationCanonicalFromNode */
function conversationCanonicalFromNode(root){
  const walk=node=>{if(node.nodeType===Node.TEXT_NODE)return node.nodeValue||"";if(node.nodeType!==Node.ELEMENT_NODE&&node.nodeType!==Node.DOCUMENT_FRAGMENT_NODE)return "";if(node.nodeType===Node.ELEMENT_NODE&&node.dataset&&node.dataset.capabilityMention)return conversationCapabilityMarker(node.dataset.capabilityMention);if(node.nodeType===Node.ELEMENT_NODE&&node.tagName==="BR")return "\n";let value="";const block=node.nodeType===Node.ELEMENT_NODE&&/^(DIV|P)$/.test(node.tagName);for(const child of node.childNodes){const childBlock=child.nodeType===Node.ELEMENT_NODE&&/^(DIV|P)$/.test(child.tagName);if(childBlock&&value&&!value.endsWith("\n"))value+="\n";value+=walk(child);if(childBlock&&child.nextSibling&&!value.endsWith("\n"))value+="\n";}return value+(block&&node.nextSibling&&!value.endsWith("\n")?"\n":"");};
  return walk(root).replace(/\u00a0/g," ");
}

/* module-function:conversationInputValue */
function conversationInputValue(box){
  return box&&box.classList?.contains("ccomposer-editor")?conversationCanonicalFromNode(box):String((box&&box.value)||"");
}

/* module-function:conversationCapabilityMentionHtml */
function conversationCapabilityMentionHtml(item){const label=String(item.label||item.id);return `<span class="cinline-capability" contenteditable="false" data-capability-mention="${esc(item.mention_id)}" title="${esc(item.description||label)}">${conversationCapabilityIcon(item)}<b lang="${/[\u3400-\u9fff]/.test(label)?"zh":"en"}">${esc(label.startsWith("$")?label:"$"+label)}</b></span>`;}

/* module-function:conversationEditorHtml */
function conversationEditorHtml(value,items){const byId=new Map((items||[]).filter(item=>item.mention_id).map(item=>[item.mention_id,item]));let at=0,out="";String(value||"").replace(CAPABILITY_MARKER_RE,(match,id,index)=>{out+=esc(String(value).slice(at,index)).replace(/\n/g,"<br>");const item=byId.get(id);if(item)out+=conversationCapabilityMentionHtml(item);at=index+match.length;return match;});out+=esc(String(value||"").slice(at)).replace(/\n/g,"<br>");return out;}

/* module-function:conversationSelectionOffsets */
function conversationSelectionOffsets(box){
  const selection=window.getSelection();if(!box||!selection||!selection.rangeCount||!box.contains(selection.anchorNode)||!box.contains(selection.focusNode))return null;const range=selection.getRangeAt(0);
  const boundary=(target,targetOffset)=>{let total=0,done=false;const measure=node=>{if(node.nodeType===Node.TEXT_NODE)return (node.nodeValue||"").length;if(node.nodeType!==Node.ELEMENT_NODE)return 0;if(node.dataset&&node.dataset.capabilityMention)return conversationCapabilityMarker(node.dataset.capabilityMention).length;if(node.tagName==="BR")return 1;return [...node.childNodes].reduce((sum,child)=>sum+measure(child),0);};const visit=node=>{if(done)return;if(node===target){if(node.nodeType===Node.TEXT_NODE)total+=Math.min(targetOffset,(node.nodeValue||"").length);else for(let i=0;i<Math.min(targetOffset,node.childNodes.length);i++)total+=measure(node.childNodes[i]);done=true;return;}if(node.nodeType===Node.TEXT_NODE){total+=(node.nodeValue||"").length;return;}if(node.nodeType!==Node.ELEMENT_NODE)return;if(node.dataset&&node.dataset.capabilityMention){total+=conversationCapabilityMarker(node.dataset.capabilityMention).length;return;}if(node.tagName==="BR"){total+=1;return;}for(const child of node.childNodes)visit(child);};visit(box);return total;};
  return {start:boundary(range.startContainer,range.startOffset),end:boundary(range.endContainer,range.endOffset)};
}

/* module-function:conversationDomPoint */
function conversationDomPoint(box,target){let remaining=Math.max(0,target),found=null;const visit=parent=>{for(let index=0;index<parent.childNodes.length&&!found;index++){const node=parent.childNodes[index];if(node.nodeType===Node.TEXT_NODE){const length=(node.nodeValue||"").length;if(remaining<=length){found={node,offset:remaining};return;}remaining-=length;continue;}if(node.nodeType!==Node.ELEMENT_NODE)continue;if(node.dataset&&node.dataset.capabilityMention){const length=conversationCapabilityMarker(node.dataset.capabilityMention).length;if(remaining===0){found={node:parent,offset:index};return;}if(remaining<=length){found={node:parent,offset:index+1};return;}remaining-=length;continue;}if(node.tagName==="BR"){if(remaining===0){found={node:parent,offset:index};return;}if(remaining===1){found={node:parent,offset:index+1};return;}remaining-=1;continue;}visit(node);}};visit(box);return found||{node:box,offset:box.childNodes.length};}

/* module-function:conversationMessageFromDraft */
function conversationMessageFromDraft(value,items){let text=String(value||"");(items||[]).filter(item=>item.mention_id).forEach(item=>{text=text.split(conversationCapabilityMarker(item.mention_id)).join(`[[capability:${item.mention_id}]]`);});return text;}

/* module-function:conversationDraftFromMessage */
function conversationDraftFromMessage(text,items){let value=String(text||"");(items||[]).filter(item=>item.mention_id).forEach(item=>{const token=item.mention_token||`[[capability:${item.mention_id}]]`;value=value.split(token).join(conversationCapabilityMarker(item.mention_id));});return value;}

/* module-function:conversationCapabilitiesForSend */
function conversationCapabilitiesForSend(surface,value){return conversationCapabilities(surface).filter(item=>!item.mention_id||String(value).includes(conversationCapabilityMarker(item.mention_id))).map(item=>item.mention_id?{...item,mention_token:`[[capability:${item.mention_id}]]`}:item);}

/* module-function:conversationDraftAttachment */
function conversationDraftAttachment(surface,item){
  const url=chatAttachmentUrl(item,conversationChatId(surface)),local=item.kind==="local_asset",folder=item.local_kind==="folder";
  const thumb=item.kind==="image"&&url?`<img src="${url}" alt="">`:ICON(item.kind==="folder"||folder?"folder":"doc");
  const copy=item.kind==="folder"?conversationAttachmentFolderCopy(item):null;
  const detail=local?`${folder?"文件夹":"文件"} · 仅在这台电脑使用`:copy?.text||formatFileSize(item.size);
  const path=item.path||item.name||"",title=[path,detail].filter(Boolean).join(" ");
  const titleMarkers=local?` data-app-i18n-title="localReference.${folder?"folderTitle":"fileTitle"}" data-app-i18n-vars="${esc(JSON.stringify({path}))}"`:copy?` data-app-i18n-title="${copy.key}Title" data-app-i18n-vars="${esc(JSON.stringify({...copy.vars,path}))}"`:"";
  return `<div class="cattachment draft" title="${esc(title)}"${titleMarkers}>${thumb}<span><b lang="${/[\u3400-\u9fff]/.test(item.name||"")?"zh":"en"}">${esc(item.name)}</b><small${local?` data-app-i18n="localReference.${folder?"folderDetail":"fileDetail"}"`:copy?` data-app-i18n="${copy.key}" data-app-i18n-vars="${esc(JSON.stringify(copy.vars))}"`:""}>${esc(detail)}</small></span><button title="移除" aria-label="移除 ${esc(item.name)}" data-app-i18n-title="localReference.remove" data-app-i18n-aria-label="localReference.removeNamed" data-app-i18n-vars="${esc(JSON.stringify({name:item.name||""}))}" onclick="removeConversationAttachment('${surface}','${item.localId}');conversationSyncSendState('${surface}')">${ICON("x")}</button></div>`;
}

/* module-function:conversationDraftItemsHtml */
function conversationDraftItemsHtml(surface){return conversationAttachments(surface).map(item=>conversationDraftAttachment(surface,item)).join("");}

/* One shared runtime entry reads live state while retaining the originating draft. */
function conversationRuntimeControl(surface,disabled=false,pendingMarkup){
  const startup=S.workspaceStartup,origin=S.conversationPanel;
  if(origin?.runtimeUnconfirmed)return `<button type="button" class="conversation-runtime-retry" id="conversation_runtime_recheck" data-app-i18n="runtimeSelector.checkSaved" aria-describedby="conversation_runtime_unconfirmed" onclick="checkSavedConversationRuntime()">核对已保存设置</button><span id="conversation_runtime_unconfirmed" class="sr-only" data-app-i18n="runtimeSelector.unconfirmed">暂时无法确认设置是否已保存。核对后即可继续。</span>`;
  if(origin&&!origin.model&&!origin.busy&&!origin.loading&&S.modelCatalogReady&&S.settingsPreferencesState==='ready'&&!startup?.channelsPending)normalizeConversationModelConfig(origin);
  const state=()=>{
    const current=S.conversationPanel,cfg=origin||{},view=RunTeamsModelChannels.composer(S,cfg),channel=S.channels.find(c=>String(c.id)===String(cfg.channel_id));
    const efforts=view.status==='ready'?effortItems(channel,cfg.model,cfg.reasoning_effort,true):[],effort=view.status==='ready'?normalizedEffort(channel,cfg.model,cfg.reasoning_effort):cfg.reasoning_effort||view.effort||'';
    return {models:chatModelItems(cfg),value:chatRouteValue(cfg),modelLabel:view.label,modelLabelKey:!view.label&&S.settingsPreferencesState==='error'?'runtimeSelector.modelSettingsFailed':'',preview:view.selected,loading:!view.selected&&view.loading,saving:!!cfg.runtimeSaving,effort,efforts,effortLabel:EFFORT_LABELS[effort]||'模型默认',defaultEffort:defaultEffort(channel,cfg.model),disabled:disabled||!origin||current!==origin||!!(cfg.busy||cfg.loading||cfg.saving)||view.displayOnly&&!RunTeamsModelChannels.hasSelectableModels(S),failed:view.failed||!!startup?.channelsError,status:view.status};
  };
  const view=state();
  if(startup?.channelsPending&&!view.preview)return pendingMarkup??RunTeamsStaticPages.runtimePending();
  if(startup?.channelsError&&!view.preview)return RunTeamsLoadFailure.button({variant:'local',compact:true,label:'无法读取模型渠道，输入已保留。重试',labelKey:'runtimeSelector.channelRetry',busyLabelKey:'composer.runtimeLoading',retry:'conversationRefreshRuntime()',buttonClassName:'csel runtime-csel'});
  const control=runtimeCsel(surface==='overview'?'overview_runtime':'conversation_runtime',{
    getState:state,disabled:view.disabled,pendingMarkup,
    onModel:value=>{if(state().disabled)return;return conversationPanelRouteChanged(value);},
    onEffort:value=>{if(state().disabled||state().status!=='ready')return;return conversationPanelEffortChanged(value);}
  });
  return view.failed?`<span class="conversation-runtime-control">${control}<button type="button" class="conversation-runtime-retry" data-app-i18n="runtimeSelector.refreshRetry" onclick="conversationRefreshRuntime()">无法更新模型状态。重试</button></span>`:control;
}

/* module-function:conversationRefreshRuntime */
async function conversationRefreshRuntime(){
  const token=workspaceAccountCacheToken(),panel=S.conversationPanel;
  const paint=()=>{
    if(token!==workspaceAccountCacheToken()||panel!==S.conversationPanel)return;
    const wanted=panel?.channel_id||String(S.settingsPreferences?.default_model||'').split('::')[0];
    if(!panel?.model&&S.settingsPreferencesState==='ready'&&(!wanted||channelCatalog(S.channels.find(c=>String(c.id)===String(wanted))).status==='ready'))initializeNewConversationModel(panel);
    if(S.workspaceStartup){S.workspaceStartup.channelsError=S.settingsPreferencesState==='error'&&!panel?.model?'对话偏好暂时无法读取，请重试。':'';S.workspaceStartup.channelsPending=false;S.workspaceStartup.pending=false;}
    if(S.settingsPreferencesState==='ready')saveModelCatalogSnapshot(S.modelCatalog);render();
  };
  try{
    await Promise.all([S.settingsPreferencesState==='error'?accountSettingsReadPreferences(true):Promise.resolve(),modelChannelData().configuration(true,{progressive:true,force:true,onCatalog:paint})]);
    paint();
  }catch(error){if(token===workspaceAccountCacheToken()){S.modelCatalogReadState='error';render();}}
}

function conversationSendLabel(surface,busy){
  if(busy){
    if(conversationQueueEnabled())return ["composer.queue","加入队列（仅文字）"];
    if(conversationCanSteer(surface))return ["composer.steer","补充要求（仅文字）"];
    return ["composer.wait","回复完成后可发送"];
  }
  if(surface==="panel"){
    const panel=S.conversationPanel;
    if(conversationEmployeeGuidance(panel)?.unconfirmed)return ["employeeChat.sendWaitForEmployee","员工信息待核对，暂时无法发送"];
    if(typeof conversationEmployeeAssetMissing==="function"&&conversationEmployeeAssetMissing(panel))return ["employeeChat.sendRestoreEmployee","请先恢复这名员工，再发送消息"];
  }
  if(conversationQueueState(surface)?.items.some(item=>item.uncertain))return ["composer.queue","加入队列（仅文字）"];
  return ["composer.send","发送"];
}

/* module-function:conversationComposer */
function conversationComposer(options){
  const connecting=!!S.workspaceStartup?.pending;
  const surface=options.surface,draftItems=conversationDraftItemsHtml(surface),docked=(surface==="panel"),value=conversationDraftValue(surface);
  if(!options.busy&&!connecting&&conversationChannelId(surface)){
    modelChannelData().warmCapabilityPage(conversationChannelId(surface),conversationChatId(surface));
  }
  const keydown=(docked?"conversationPanelKeydown":"chatKeydown"),stopAction=docked?"stopConversationPanel":"stopChat",stopping=!!options.stopping,action=options.sendAction;
  const [sendKey,title]=conversationSendLabel(surface,!!options.busy);
  const placeholder=options.placeholder||"说说你想做什么…";
  const promptKey=options.placeholderCopy?.key||(placeholder==="说说你想做什么…"?"composer.prompt":placeholder==="描述员工要负责的工作…"?"employeeCreate.prompt":"");
  const promptMarkers=promptKey?` data-app-i18n-aria-label="${promptKey}" data-app-i18n-data-placeholder="${promptKey}"${options.placeholderCopy?.vars?` data-app-i18n-vars="${esc(JSON.stringify(options.placeholderCopy.vars))}"`:""}`:"";
  const runtimeControls=options.runtimeControl!=null?`<div class="copt runtime" ${options.busy?'inert aria-disabled="true"':''}>${options.runtimeControl}</div>`:`<div class="copt route" ${options.busy?'inert aria-disabled="true"':''}>${options.modelControl}</div><div class="copt effort" ${options.busy?'inert aria-disabled="true"':''}><span class="copt-label" data-app-i18n="composer.thinking">思考</span>${options.effortControl}</div>`;
  const content=`${options.scopeControl||""}${options.contextControl||""}<div class="ccomposer-editor" id="${options.inputId}" role="textbox" aria-multiline="true" aria-label="${esc(placeholder)}" data-placeholder="${esc(placeholder)}" ${promptMarkers} data-empty="${String(!String(value).trim())}" contenteditable="true" oninput="conversationInputChanged(this,'${surface}')" onbeforeinput="conversationBeforeInput(event)" onpaste="conversationPaste(event,'${surface}')" onkeydown="${keydown}(event)" onkeyup="conversationComposerSelectionChanged('${surface}')" onmouseup="conversationComposerSelectionChanged('${surface}')" onfocus="conversationComposerFocused(this,'${surface}')">${conversationEditorHtml(value,conversationCapabilities(surface))}</div><div class="cfoot"><div class="cfoot-left"><input id="${options.fileInputId}" class="cfile-input" type="file" multiple accept="${CHAT_FILE_ACCEPT}" onchange="conversationFilesPicked('${surface}',this.files);this.value=''"><button class="cattach-btn" type="button" data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="false" title="添加内容" aria-label="添加内容" data-app-i18n-title="composer.add" data-app-i18n-aria-label="composer.add" onpointerdown="event.preventDefault();captureConversationSelection('${surface}')" onclick="conversationAddMenu(event,'${surface}')" ${options.busy||connecting?"disabled":""}>${ICON("plus")}</button>${typeof RunTeamsWorkFolders!=="undefined"?RunTeamsWorkFolders.markup(surface,!!options.busy):""}${draftItems?`<div class="cattachments" aria-label="已添加资料" data-app-i18n-aria-label="composer.attachments">${draftItems}</div>`:""}${runtimeControls}</div><div class="cfoot-right">${options.busy?`<button type="button" class="conversation-composer-stop" aria-label="${stopping?'正在停止…':'停止回复'}" data-app-i18n-aria-label="composer.${stopping?'stopping':'stop'}" ${stopping?'disabled':''} onclick="${stopAction}()">${ICON('stop')}</button>`:''}<button class="sendbtn" title="${esc(title)}" aria-label="${esc(title)}" data-app-i18n-title="${sendKey}" data-app-i18n-aria-label="${sendKey}" ${connecting&&S.workspaceStartup?.profilePending?'aria-busy="true"':""} onclick="conversationSubmit('${surface}',()=>${action}())" ${conversationSendDisabled(surface,!!options.busy,value)?"disabled":""}>${ICON("arrow")}</button></div></div>${connecting?workspaceStartupNotice():""}`;
  return `${conversationProviderBanner(surface)}<div data-conversation-queue="${surface}">${conversationQueueMarkup(surface)}</div>${surface==='panel'&&window.RunTeamsAssetOverview?.employee()?'':conversationQuestionDock(surface)}${RunTeamsStaticPages.composer(content,{surface,busy:options.busy,attributes:`data-local-references="${conversationSupportsLocalReferences(surface)}" ondragover="conversationDragOver(event)" ondragleave="this.classList.remove('dragging')" ondrop="conversationDrop(event,'${surface}')"`})}`;
}

/* module-function:conversationComposerKeydown */
function conversationComposerKeydown(event,surface){if(event.key!=="Enter")return;const capabilityMenu=document.getElementById("popmenu")?.classList.contains("chat-add-menu");if(event.isComposing||event.keyCode===229||event.currentTarget?.dataset?.composing==="true"){if(capabilityMenu)event.stopPropagation();return;}if(event.shiftKey)return;if(capabilityMenu)return;if(typeof accountSettingsPrefs==='function'&&accountSettingsPrefs().send_mode==='meta-enter'&&!event.metaKey&&!event.ctrlKey)return;event.preventDefault();event.stopPropagation();if(event.repeat)return;conversationSubmit(surface,()=>(surface==="panel"?sendConversationPanel():sendChat()));}

/* module-function:chatKeydown */
function chatKeydown(event){conversationComposerKeydown(event,"chat");}

/* module-function:conversationPanelKeydown */
function conversationPanelKeydown(event){conversationComposerKeydown(event,"panel");}

/* module-function:conversationBeforeInput */
function conversationBeforeInput(event){if(event.inputType==="insertParagraph"){event.preventDefault();document.execCommand("insertLineBreak",false,null);}}

/* module-function:conversationInputChanged */
function conversationInputChanged(box,surface){const value=conversationInputValue(box),visibleValue=value.replace(CAPABILITY_MARKER_RE,"");box.dataset.empty=String(!value.trim());autoSizeChatInput(box);conversationSyncSendState(surface);captureConversationSelection(surface);const filtering=updateConversationCapabilitySearch(box,surface);if(filtering)return;setConversationDraftValue(surface,value);if(surface==="panel"&&!visibleValue.trim())clearConversationExampleMaterials();refreshConversationDraftItems(surface);if(surface==="chat")syncChatEmptyState(box);conversationOpenMentionSearch(box,surface);}

/* module-function:conversationMentionQuery */
function conversationMentionQuery(value,selection){
  if(!selection||selection.start!==selection.end)return null;
  const before=String(value).slice(0,selection.start),match=/(?:^|[ \n])@([^\s@\uE000\uE001]*)$/.exec(before);
  if(!match)return null;
  const tail=String(value).slice(selection.start).match(/^[^\s@\uE000\uE001]*/)[0],query=match[1]+tail;
  if(query.length>240)return null;
  return {start:before.lastIndexOf('@'),end:selection.start+tail.length,query};
}

/* module-function:conversationOpenMentionSearch */
function conversationOpenMentionSearch(box,surface){
  if(box.dataset.composing==='true'||S.workspaceStartup?.pending||(surface==='panel'?S.conversationPanel?.busy:S.chatBusy))return;
  const value=conversationInputValue(box);if(!value.includes('@')||document.getElementById('popmenu'))return;const mention=conversationMentionQuery(value,conversationSelectionOffsets(box));if(!mention)return;
  showConversationCapabilityMenu(box,surface,{surface,trigger:'mention',baseValue:value,...mention});
}

/* module-function:conversationComposerSelectionChanged */
function conversationComposerSelectionChanged(surface){
  captureConversationSelection(surface);
  if(_conversationCapabilitySearch?.surface===surface&&_conversationCapabilitySearch.trigger==='mention'){
    const box=conversationInputElement(surface);if(box)updateConversationCapabilitySearch(box,surface);
  }
}

/* module-function:conversationFilesPicked */
function conversationFilesPicked(surface,files){if(S.workspaceStartup?.pending)return Promise.resolve();const result=addConversationFiles(surface,files);conversationSyncSendState(surface);return Promise.resolve(result).then(()=>conversationSyncSendState(surface));}

/* module-function:conversationDragOver */
function conversationDragOver(event){event.preventDefault();event.currentTarget.classList.add("dragging");}

/* module-function:conversationSupportsLocalReferences */
function conversationSupportsLocalReferences(surface){return surface==="panel"&&conversationContextType(S.conversationPanel)==="worker"&&["chat","work"].includes(conversationIntent(S.conversationPanel));}

/* module-function:conversationDrop */
async function conversationDrop(event,surface){
  event.preventDefault();event.currentTarget.classList.remove("dragging");
  if(S.workspaceStartup?.pending)return;
  if(conversationSupportsLocalReferences(surface)){
    if(event.isTrusted)await readConversationLocalReferenceEvent(surface,"drop");
    return;
  }
  addConversationFiles(surface,event.dataTransfer&&event.dataTransfer.files);
}

/* module-function:conversationNativeLocalDrop */
async function conversationNativeLocalDrop(paths,x,y){
  const composer=document.elementFromPoint(x,y)?.closest('.ccomposer[data-local-references="true"]');if(!composer)return;
  const surface=composer.dataset.conversationSurface,panel=S.conversationPanel;if(panel?.busy)return;
  try{await prepareConversationLocalReferences(surface,await api("/api/local-references/prepare","POST",{paths}),panel);}catch(error){toast(error.message||"无法添加本地引用。请重试。","err",error.message?undefined:"localReference.addFailed");}
}

/* module-function:conversationPaste */
async function conversationPaste(event,surface){
  const box=event.currentTarget,files=Array.from(event.clipboardData?.files||[]),text=event.clipboardData?.getData("text/plain")||"";
  const types=Array.from(event.clipboardData?.types||[]),hasLocalFiles=types.includes("public.file-url")||(!files.length&&types.includes("Files"))||/^file:\/\//i.test(event.clipboardData?.getData("text/uri-list")||"");
  const local=conversationSupportsLocalReferences(surface),panel=S.conversationPanel;
  if(local&&panel?.busy){event.preventDefault();return;}
  const native=local&&event.isTrusted&&window.webkit?.messageHandlers?.runteamsLocalReferencePaste;
  if(native){
    event.preventDefault();
    const selected=conversationSelectionOffsets(box),draft=conversationInputValue(box);
    try{
      const paths=await native.postMessage({});
      if(S.conversationPanel!==panel||panel?.busy)return;
      if(paths.length){await prepareConversationLocalReferences(surface,await api("/api/local-references/prepare","POST",{paths}),panel);return;}
      // Keep the captured selection for normal paste, but never overwrite edits
      // or steal focus if the user moved on while the native bridge replied.
      if(!box.isConnected||document.activeElement!==box||conversationInputValue(box)!==draft)return;
      if(selected)restoreConversationSelection(surface,selected.start,selected.end);
      applyConversationPaste(surface,box,files,text);
    }catch(error){if(S.conversationPanel===panel)toast("无法粘贴。请重试，或点按加号添加本地引用。","err","localReference.pasteFailed");}
    return;
  }
  if(local&&(hasLocalFiles||files.length)){
    event.preventDefault();if(event.isTrusted)await readConversationLocalReferenceEvent(surface,"paste",{box,files,text});return;
  }
  if(files.length||box?.isContentEditable){event.preventDefault();applyConversationPaste(surface,box,files,text);}
}

/* module-function:readChatFile */
function readChatFile(item){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve({name:item.name,mime_type:item.mime_type,size:item.size,data:String(r.result||"").split(",",2)[1]||""});r.onerror=()=>reject(Object.assign(new Error("无法读取「"+item.name+"」。请重新添加。"),{messageKey:"composer.fileRead",messageVars:{name:item.name}}));r.readAsDataURL(item.file);});}

/* module-function:autoSizeChatInput */
function autoSizeChatInput(box){
  if(!box)return;
  box.style.height="auto";
  const compact=!!box.closest?.(".conversation-main");
  const minHeight=compact?82:72;
  const maxHeight=compact?180:190;
  box.style.height=Math.min(maxHeight,Math.max(minHeight,box.scrollHeight))+"px";
}

/* module-function:scrollChat */
function scrollChat(){ const s=document.getElementById("cscroll"); if(s) s.scrollTop=s.scrollHeight; }

/* module-function:rerenderChatKeepingDraft */
function rerenderChatKeepingDraft(){ const old=document.getElementById("cbox"),draft=old?conversationInputValue(old):S.chatDraft,selection=old?conversationSelectionOffsets(old):null;S.chatDraft=draft;render();const box=document.getElementById("cbox");if(box){syncChatEmptyState(box);box.focus();if(selection)restoreConversationSelection("chat",selection.start,selection.end);} }

/* module-function:persistChatConfig */
async function persistChatConfig(){if(S.chatId==="new"||S.chatId==null)return;const result=await api("/api/chat/"+S.chatId+"/config","POST",S.chatCfg);if(result.error&&!handleAgentChannelError(result.error,{channelId:S.chatCfg.channel_id,model:S.chatCfg.model}))toast(result.error,"err");}

/* module-function:ensureChatEnvironment */
async function ensureChatEnvironment(){if(RunTeamsModelChannels.extensionsReady(S,S.environment))return true;try{const result=await modelChannelData().extensions(false);if(!result)return false;if(result.error)throw new Error(result.error);S.environment=result;saveEnvironmentSnapshot(result);return true;}catch(e){toast("模型能力没有载入。请确认 Agent CLI 已连接","err");return false;}}

/* module-function:conversationCapabilityMenuItems */
function conversationCapabilityMenuItems(surface,staticOnly=false){const items=staticOnly?[{head:true,label:"添加",labelKey:"composer.addHeading"},{label:"文件和文件夹",labelKey:"composer.files",icon:"paperclip",fn:()=>openConversationAttachmentPicker(surface)},{head:true,label:"技能",labelKey:"composer.skills"}]:capabilityMenuItemsFor(conversationChannelId(surface),()=>openConversationAttachmentPicker(surface),item=>addConversationCapability(surface,item),(plugin,row,add)=>installConversationCapability(surface,plugin,row,add));if(conversationSupportsLocalReferences(surface)){items.splice(1,1,{label:"本地文件和文件夹",labelKey:"composer.localFiles",icon:"folder",fn:()=>openConversationLocalReferencePicker(surface)});items.splice(2,0,{label:"上传附件",labelKey:"composer.upload",icon:"paperclip",fn:()=>openConversationAttachmentPicker(surface)});}if(surface==="panel"&&S.conversationPanel&&!conversationFixedContext(S.conversationPanel)&&conversationContext(S.conversationPanel).ambient_disabled&&currentPageContext()?.surface!=="chat")items.splice(2,0,{label:"参考当前页面",labelKey:"composer.referencePage",description:currentPageContext().label||"将当前页面添加为参考",descriptionKey:currentPageContext().label?undefined:"composer.pageHint",icon:"panel-right-open",fn:restoreConversationAmbientContext});const panel=surface==="panel"?S.conversationPanel:null;
  if(panel?.example_materials)items.unshift(...conversationExampleMaterialMenuItems(panel));
  if(panel?.storage_scope==="device"&&panel.kind==="general"&&(panel.context?.source_pipeline_workspace||
    (panel.subject_type==="employee"&&conversationIntent(panel)==="chat"&&!panel.context?.pipeline_work&&!panel.context?.employee_work))){
    const upload=items.find(item=>item.labelKey==="composer.upload"||item.labelKey==="composer.files");
    if(upload){upload.description="新会话可引用文本 PDF、MD、TXT";upload.descriptionKey="composer.assetSourcesHint";}
  }
  return items;}

/* module-function:conversationInputElement */
function conversationInputElement(surface){return document.getElementById((surface==="panel"?"conversation_box":"cbox"));}

/* module-function:installConversationCapability */
async function installConversationCapability(surface,plugin,row,addCapability){
  if(!row||row.dataset.installing==="1")return;row.dataset.installing="1";row.classList.remove("install-error");row.classList.add("installing");row.setAttribute("aria-busy","true");setCapabilityInstallDetail(row,"正在安装…","installing","composer.installing");
  let completed=false;modelChannelData().invalidate();
  try{
    const result=await api("/api/environment/plugin/install","POST",{channel_id:plugin.channel_id||conversationChannelId(surface),plugin_id:plugin.id||plugin.name});if(result.error)throw Object.assign(new Error(result.error),{code:result.code});
    completed=true;const environment=await modelChannelData().extensions(true);
    if(!environment||environment.error)throw Error('安装结果尚未确认。');
    const found=environment.plugins.find(item=>String(item.channel_id)===String(plugin.channel_id||conversationChannelId(surface))&&pluginIdentity(item)===pluginIdentity(plugin));
    if(!found||found.enabled!==true)throw Error('安装或启用状态尚未确认。');
    S.environment=environment;saveEnvironmentSnapshot(environment);
    row.classList.remove("installing");row.classList.add("install-success");row.removeAttribute("aria-busy");setCapabilityInstallDetail(row,"安装完成","success","composer.installed");toast(`已安装并启用「${capabilityFromPlugin(plugin).label}」`,"info","composer.installedEnabled",{name:capabilityFromPlugin(plugin).label});await new Promise(resolve=>setTimeout(resolve,320));closePop();addCapability(capabilityFromPlugin(found));
  }catch(error){if(completed||error.code==='mutation_outcome_unknown'){row.dataset.installing='1';row.classList.remove('installing');row.removeAttribute('aria-busy');setCapabilityInstallDetail(row,'安装结果待核对','','composer.installUnknown');toast('暂时无法确认安装结果。请刷新技能与工具列表后再试。','info','composer.installCheck');return;}row.dataset.installing="";row.classList.remove("installing");row.classList.add("install-error");row.removeAttribute("aria-busy");row.title=error.message||"安装失败";if(error.message)delete row.dataset.appI18nTitle;else{row.dataset.appI18nTitle="composer.installFailed";window.RunTeamsLocale?.apply(row);}setCapabilityInstallDetail(row,"安装失败，点按重试","error","composer.installRetry");toast(error.message||"无法安装技能。","err",error.message?undefined:"composer.skillInstallFailed");}
}

/* module-function:showConversationCapabilityMenu */
function showConversationCapabilityMenu(anchor,surface,session=null){
 openMenu(anchor,conversationCapabilityMenuItems(surface,true),{variant:"chatAdd",positionAnchor:anchor.closest(".ccomposer")||anchor,placement:"above",
  onClose:()=>window.removeEventListener('resize',alignConversationCapabilityMenu)});
 if(_popAnchor!==anchor)return;
 const menu=document.getElementById("popmenu");if(!menu)return;
 window.addEventListener('resize',alignConversationCapabilityMenu);
 const state={anchor,surface,menu,channel:conversationChannelId(surface),scope:workspaceAccountCacheToken(),owner:surface==="panel"?S.conversationPanel:S.chatId,query:"",version:0,items:[],seen:new Set(),next:null,pending:false,error:"",closed:false};
 state.configuration=conversationCapabilityConfiguration(state.channel);menu._capabilityPage=state;menu.dataset.capabilityPaged="true";
 const list=document.createElement('div'),footer=document.createElement('div');list.className='chat-capability-list';footer.className='chat-capability-footer';menu.append(list,footer);state.list=list;state.footer=footer;
 menu.addEventListener('mouseover',event=>{const row=event.target.closest('a[data-i],.chat-capability-retry');if(row)menu.querySelectorAll('.active').forEach(node=>{if(node!==row)node.classList.remove('active');});});
 menu.addEventListener('scroll',()=>{if(menu.scrollHeight-menu.scrollTop-menu.clientHeight<=40)loadConversationCapabilityPage(state);},{passive:true});
 beginConversationCapabilitySearch(surface,session);if(_conversationCapabilitySearch)_conversationCapabilitySearch.page=state;
 loadConversationCapabilityPage(state,true);
}
function conversationCapabilityConfiguration(id){const c=(S.channels||[]).find(row=>String(row.id)===String(id));return JSON.stringify(c&&[c.id,c.provider,c.enabled,c.config_dir,c.executable,c.changeSequence]);}
function conversationCapabilityPageContext(state){return state.scope===workspaceAccountCacheToken()&&String(state.channel)===String(conversationChannelId(state.surface))&&state.owner===(state.surface==="panel"?S.conversationPanel:S.chatId)&&state.configuration===conversationCapabilityConfiguration(state.channel);}
function conversationCapabilityPageCurrent(state){return !state.closed&&state.menu.isConnected&&_popAnchor===state.anchor&&state.anchor.isConnected&&conversationCapabilityPageContext(state);}
function conversationCapabilitySkeleton(count){return `<div class="chat-capability-skeleton" role="status" aria-label="正在读取技能…" data-app-i18n-aria-label="composer.skillsLoading" aria-busy="true" inert>${Array.from({length:count},()=>'<div class="chat-capability-skeleton-row" aria-hidden="true"><i class="skeleton-block capability-skeleton-icon"></i><i class="skeleton-block capability-skeleton-name"></i><i class="skeleton-block capability-skeleton-description"></i></div>').join('')}</div>`;}
function paintConversationCapabilityFooter(state){
 const footer=state.footer,pinned=state.pending&&state.items.length&&state.menu.scrollHeight-state.menu.scrollTop-state.menu.clientHeight<=40;footer.replaceChildren();
 if(state.pending)footer.innerHTML=conversationCapabilitySkeleton(state.items.length?3:5);
 else if(state.error){const text=document.createElement('span'),retry=document.createElement('button');text.textContent=state.error;const key=new Map([['技能列表暂时无法读取','skillsFailed'],['模型渠道尚未连接','channelDisconnected'],['技能分页位置未更新，请重试','skillsCursor']]).get(state.error);if(key)text.dataset.appI18n='composer.'+key;text.setAttribute('role','status');retry.type='button';retry.className='chat-capability-retry';retry.textContent='重试';retry.dataset.appI18n='composer.retry';retry.onclick=event=>{event.stopPropagation();if(state.restart){state.items=[];state.seen.clear();state.list.replaceChildren();state.next=null;}state.error='';loadConversationCapabilityPage(state,!state.items.length);};footer.append(text,retry);}
 else if(!state.items.length){const empty=document.createElement('div');empty.className='menu-empty';empty.textContent=state.query?'没有匹配的技能':'暂无可用技能';empty.dataset.appI18n=state.query?'composer.noMatches':'composer.noSkills';footer.append(empty);}
 alignConversationCapabilityMenu();if(pinned)state.menu.scrollTop=state.menu.scrollHeight;
}
function appendConversationCapabilityRows(state,items){
 for(const plugin of items){const key=String(plugin.channel_id)+':'+String(plugin.id||plugin.name);if(state.seen.has(key))continue;state.seen.add(key);state.items.push(plugin);
  const capability=capabilityFromPlugin(plugin),entry={label:capability.label,description:capability.description,iconUrl:capability.icon_url,icon:'package',capability:true};
  const holder=document.createElement('div');holder.innerHTML=menuItemsMarkup([entry]);const row=holder.firstElementChild;row.dataset.capabilityKey=key;
  const image=row.querySelector('img.menu-icon');
  if(image)image.addEventListener('error',()=>{image.outerHTML=ICON('package');},{once:true});
  row.querySelectorAll('b,small').forEach(label=>label.lang=/[\u3400-\u9fff]/.test(label.textContent)?'zh':'en');
  row.onmousedown=event=>event.preventDefault();row.onmouseenter=()=>{state.menu.querySelectorAll('.active').forEach(node=>node.classList.remove('active'));row.classList.add('active');};
  row.onclick=event=>{event.stopPropagation();if(!conversationCapabilityPageCurrent(state))return;if(!RunTeamsModelChannels.connected(S,(S.channels||[]).find(channel=>String(channel.id)===String(state.channel)))){state.error='模型渠道尚未连接';state.items=[];state.next=null;state.list.replaceChildren();paintConversationCapabilityFooter(state);return;}if(plugin._installed){closePop();addConversationCapability(state.surface,capability);}else installConversationCapability(state.surface,plugin,row,item=>addConversationCapability(state.surface,item));};state.list.append(row);
 }
}
async function loadConversationCapabilityPage(state,initial=false){
 if(!conversationCapabilityPageCurrent(state)||state.pending||state.error&&!initial||!initial&&!state.next)return;
 const version=state.version,cursor=initial?'':state.next;state.pending=true;state.error='';state.restart=false;paintConversationCapabilityFooter(state);
 try{
  const result=await modelChannelData().capabilityPage(state.channel,{after:cursor,query:state.query,limit:40,chatId:conversationChatId(state.surface)});
  if(!conversationCapabilityPageCurrent(state)){if(document.getElementById('popmenu')===state.menu&&_popAnchor===state.anchor)closePop();return;}if(version!==state.version)return;
  if(!result)throw Error('技能列表暂时无法读取');if(result.error){state.restart=result.code==='catalog_changed';throw Error(result.error);}
  if(result.next_cursor&&result.next_cursor===cursor)throw Error('技能分页位置未更新，请重试');
  appendConversationCapabilityRows(state,result.items);state.next=result.next_cursor;
 }catch(error){if(conversationCapabilityPageCurrent(state)&&version===state.version)state.error=error.message||'技能列表暂时无法读取';}
 finally{if(conversationCapabilityPageCurrent(state)&&version===state.version){state.pending=false;paintConversationCapabilityFooter(state);}}
}
function filterConversationCapabilityPages(state,value){
 const query=String(value||'').trim().slice(0,240);if(query===state.query)return;
 clearTimeout(state.timer);state.query=query;state.version++;state.pending=true;state.error='';state.items=[];state.seen.clear();state.next=null;state.list.replaceChildren();state.menu.scrollTop=0;paintConversationCapabilityFooter(state);
 state.timer=setTimeout(()=>{if(!conversationCapabilityPageCurrent(state))return;state.pending=false;loadConversationCapabilityPage(state,true);},160);
}
/* module-function:conversationAddMenu */
function conversationAddMenu(event,surface){showConversationCapabilityMenu(event.currentTarget,surface);}

/* module-function:stopChat */
async function stopChat(){
  if(!S.chatBusy||S.chatStopping)return;S.chatStopping=true;if(typeof RunTeamsCreatorWork!=='undefined'&&RunTeamsCreatorWork.requestStop(S.chatId)){S.chatStopRequested=true;render();return;}S.chatStopRequested=true;conversationQueueState('chat').paused=true;const snapshot=stopLiveAgentMessageImmediately(S.chatMsgs);render();
  if(S.chatId==null||S.chatId==="new")return;
  try{const result=await api(`/api/chat/${S.chatId}/cancel`,"POST",{});if(result.error)throw new Error(result.error);}catch(error){S.chatStopping=false;S.chatStopRequested=false;restoreOptimisticallyStoppedMessage(snapshot);render();toast(error.message||"暂时无法确认是否已停止，请刷新任务状态。","err",!error.message?"conversationDetail.stopUnknown":undefined);}
}

/* module-function:chatMenu */
function chatMenu(e,cid){ openMenu(e.currentTarget,[
  {label:railChatPinned(cid)?"取消置顶":"置顶",labelKey:railChatPinned(cid)?"conversationDetail.unpin":"conversationDetail.pin",icon:railChatPinned(cid)?"pin-off":"pin",fn:()=>togglePinnedChat(cid)},
  {label:"重命名",labelKey:"conversationDetail.rename",icon:"edit",fn:()=>renameChatSession(cid)},
  {label:"删除对话",labelKey:"conversationDetail.delete",icon:"trash",fn:()=>deleteChatSession(cid)},
],{variant:"railItem",...(e.type==="contextmenu"?{at:{x:e.clientX,y:e.clientY}}:{})}); }

/* module-function:sendChat */
async function sendChat(options={}){
  const queued=options.queued,queueOwner=conversationQueueOwner("chat"),box=document.getElementById("cbox");if(!box||S.chatId==null)return;const rawDraft=queued?queued.text:conversationInputValue(box),hasUserText=!!rawDraft.replace(CAPABILITY_MARKER_RE,"").trim();
  if((!hasUserText&&!S.chatAttachments.length)||S.chatBusy){rerenderChatKeepingDraft();return;}
  if(!conversationRuntimeReady("chat")){conversationSyncSendState("chat");return;}
  const folderAtSend=typeof RunTeamsWorkFolders==="undefined"?null:await RunTeamsWorkFolders.prepare("chat");if(folderAtSend===false)return;
  const pending=queued?[]:S.chatAttachments.slice(),pendingCapabilities=queued?[]:conversationCapabilitiesForSend("chat",rawDraft),annotatedMessage=conversationMessageFromDraft(rawDraft,pendingCapabilities),firstPipelineRequest=S.chatMode==="pipeline-create"&&S.chatId==="new"&&hasUserText,msg=firstPipelineRequest&&!/^\s*(?:请)?(?:帮我)?创(?:建|造)(?:一个|一支)?智能体团队/.test(annotatedMessage)?`创建智能体团队：${annotatedMessage}`:annotatedMessage,attachmentTokens=pending.filter(x=>x.pickToken).map(x=>x.pickToken),startedAsNew=S.chatId==="new",activityContextAtSend=typeof RunTeamsChatActivity==='undefined'?'':RunTeamsChatActivity.context(S);let uploads,accepted=false,out=null,createdSession=false,attempted=false,completed=false,configurationRequired=false;
  try{uploads=(typeof RunTeamsCreatorWork==='undefined'?null:RunTeamsCreatorWork.pendingInput(S.chatId)?.attachments)||await Promise.all(pending.filter(x=>x.file).map(readChatFile));}catch(e){toast(e.message||"无法读取附件。请重新添加。","err",e.messageKey||(!e.message?"composer.attachmentRead":undefined),e.messageVars);return;}
  if(!conversationRuntimeReady("chat")){conversationSyncSendState("chat");return;}
  const sent={role:"user",ts:new Date().toISOString(),text:annotatedMessage,state:"sending",localId:"m"+Date.now()+Math.random().toString(16).slice(2),capabilities:pendingCapabilities,attachments:pending.map(x=>({id:x.localId,name:x.name,size:x.size,mime_type:x.mime_type,kind:x.kind,local_kind:x.local_kind,grant_id:x.grant_id,preview:x.preview}))},live=newLiveAgentMessage("chat-live-");
  S.chatMsgs.push(sent,live);if(!queued){S.chatAttachments=[];S.chatCapabilities=[];S.chatDraft="";}S.chatBusy=true;S.chatCanSteer=false;S.chatStopping=false;S.chatStopRequested=false;S.chatActivity="";render();requestAnimationFrame(scrollChat);let cancelled=false;
  try{
    if(S.chatId==="new"){ const r=await api("/api/conversations","POST",{kind:"general",...S.chatCfg}); if(r.error)throw new Error(r.error); S.chatId=r.session.id;if(queueOwner.id!==S.chatId){const oldQueueKey=String(queueOwner.id);delete S.chatMessageQueues[oldQueueKey];queueOwner.id=S.chatId;S.chatMessageQueues[String(S.chatId)]=queueOwner;if(queueOwner.messageQueue?.items.length){const saved=S.conversationPanelDrafts[`chat:${oldQueueKey}`];if(saved?.queue)delete saved.queue;conversationQueueSave("chat",queueOwner);}}createdSession=true; }
    else if((typeof RunTeamsCreatorWork==='undefined'||!RunTeamsCreatorWork.hasPending(S.chatId))){const configResult=await api("/api/chat/"+S.chatId+"/config","POST",S.chatCfg);if(configResult.error)throw new Error(configResult.error);}
    if(folderAtSend)await RunTeamsWorkFolders.bind(S.chatId,folderAtSend);
    const rewind=queued?null:S.chatRewind,reuseAttachmentIds=pending.filter(x=>x.reuseId).map(x=>x.reuseId);
    attempted=true;await (typeof RunTeamsCreatorWork==='undefined'?streamApi:RunTeamsCreatorWork.send)("/api/chat/"+S.chatId+"/stream",{message:msg,attachments:uploads,attachment_tokens:attachmentTokens,local_asset_ids:pending.filter(x=>x.kind==="local_asset"&&!x.reuseId).map(x=>x.grant_id),capabilities:pendingCapabilities,rewind_message_id:rewind&&rewind.messageId,reuse_attachment_ids:reuseAttachmentIds},event=>{
      if(event.type==="accepted"){accepted=true;if(typeof RunTeamsChatActivity!=='undefined')RunTeamsChatActivity.started(S,queueOwner.id,activityContextAtSend);if(queued)conversationQueueAccepted("chat",queueOwner,queued.id);if(!queued)S.chatRewind=null;sent.id=event.message_id;sent.state="sent";sent.attachments=(event.attachments||[]).map(x=>({...x}));sent.capabilities=event.capabilities||pendingCapabilities;pending.forEach(x=>{if(x.preview)URL.revokeObjectURL(x.preview);});if(startedAsNew)activateCreatedChat();else updatePendingChatMessage(sent.localId,"sent");if(S.chatStopRequested)api(`/api/chat/${S.chatId}/cancel`,"POST",{}).catch(()=>{});}
      else if(event.type==="steer_accepted"){conversationSteerAccepted("chat",event);}else if(event.type==="agent_event"){if(S.chatStopRequested)return;if(event.event?.kind==="turn_control"){S.chatCanSteer=!!event.event.can_steer;conversationSyncSendState("chat");return;}applyAgentStreamEvent(live,event.event);if(event.event?.message)conversationQuestionAnswerMessage("chat",event.event.message,null,event.event.prefix_message);refreshLiveAgentMessage(live,"chat");}
      else if(event.type==="result")out=event;
      else if(event.type==="cancelled")cancelled=true;
      else if(event.type==="error")throw event.message?new Error(event.message):Object.assign(new Error("模型没有响应。确认模型渠道已连接后再试"),{messageKey:"conversationDetail.modelNoResponse"});
    });
    if(cancelled){delete sent.state;finalizeStoppedAgentMessage(live);refreshLiveAgentMessage(live,"chat");}
    else{
    if(!out)throw Object.assign(new Error("模型没有返回最终回复"),{messageKey:"conversationDetail.modelNoFinal"});
    if(location.pathname==="/chats/new"&&S.chatId!=="new")setAppUrl(routeWithRailState(`/chat/${encodeURIComponent(S.chatId)}`,S.chatId),true);
    delete sent.state;
    live.id=out.message_id||live.id;live.text=typeof out.reply==="string"?out.reply:live.text;live.systemNotice=out.system_notice||null;live.streaming=false;live.stopped=live.systemNotice?.kind==="stopped";live.trace.cancelled=live.stopped;live.trace.complete=true;live.trace.failed=!live.stopped&&!!(out.failed||out.incomplete);live.trace.finishedAt=Date.now();
    live.applied=out.applied||[];live.runCards=out.run_cards||[];refreshLiveAgentMessage(live,"chat");
    completed=!out.failed&&!out.incomplete&&!S.chatStopRequested;
    try{const cl=await conversationChatDirectory();if(!cl.error){S.chats=cl.chats;expandRailSection("recent");}await refreshCoreTeam();}catch(ignore){}
    
    }
  }catch(e){
    const errorText=(e&&e.message)||String(e);
    configurationRequired=e?.configurationRequired===true;const guided=configurationRequired||handleAgentChannelError(errorText,{channelId:S.chatCfg.channel_id,model:S.chatCfg.model,continuation:accepted||queued?null:()=>sendChat()});
    if(accepted&&S.chatId!=="new"){
      try{const saved=await api("/api/chat/"+S.chatId);S.chatMsgs=(saved.messages||[]).map(storedConversationMessage);}catch(ignore){}
    }else{
      if(createdSession&&S.chatId!=="new"){try{await api(`/api/chat/${S.chatId}/delete`,"POST");}catch(ignore){}S.chatId="new";if(location.pathname.startsWith("/chats/"))setAppUrl(routeWithRailState("/chat/new","new"),true);}
      S.chatMsgs=S.chatMsgs.filter(m=>m!==sent&&m!==live);if(!queued){S.chatAttachments=pending;S.chatCapabilities=pendingCapabilities;S.chatDraft=rawDraft;}
    }
    if(!guided&&!e.creatorPending&&!conversationHasConfirmedReply(S.chatMsgs,sent.id)&&!S.chatMsgs.some(message=>message.ephemeral&&message.text===errorText))S.chatMsgs.push({role:"bot",text:errorText,applied:[],ephemeral:true,errorLocaleKey:e?.messageKey,retryAccepted:accepted,...(!accepted?{retryDraft:{text:rawDraft,capabilities:pendingCapabilities,attachments:pending}}:{})});
    try{const cl=await conversationChatDirectory();S.chats=cl.chats;if(accepted)expandRailSection("recent");}catch(ignore){}
  }
  completed=completed&&!cancelled&&!S.chatStopRequested;conversationQueueFinished("chat",queueOwner,completed);S.chatBusy=false;S.chatCanSteer=false;S.chatStopping=false;S.chatStopRequested=false;S.chatActivity="";render();if(completed)queueMicrotask(()=>void conversationQueueDrain("chat",queueOwner));requestAnimationFrame(()=>{scrollChat();if(configurationRequired){document.querySelector('#employee_configuration_form [aria-invalid="true"]')?.focus();}else if(!accepted&&!queued){const draft=document.getElementById("cbox");if(draft){setConversationInputValue(draft,rawDraft,S.chatCapabilities);syncChatEmptyState(draft);draft.focus();restoreConversationSelection("chat",rawDraft.length);}}});return {accepted,attempted,completed};
}

/* module-function:conversationContext */
function conversationContext(panel=S.conversationPanel){return normalizedConversationContext(panel||{});}

/* module-function:conversationContextType */
function conversationContextType(panel=S.conversationPanel){return conversationContext(panel).context_type;}

/* module-function:conversationIntent */
function conversationIntent(panel=S.conversationPanel){return conversationContext(panel).intent;}

/* module-function:conversationIs */
function conversationIs(panel,type,intent=""){return conversationContextType(panel)===type&&(!intent||conversationIntent(panel)===intent);}

/* module-function:conversationMessageGallery */
function conversationMessageGallery(){
  const label=text=>({role:"debug",text}),now=Date.now();
  return [
    label("用户消息 普通文本"),
    {id:"mock-user",role:"user",text:"帮我检查这个智能体团队为什么停在验收岗位，并给出可以直接执行的修复建议。"},
    label("用户消息 附件与技能"),
    {id:"mock-user-context",role:"user",text:"结合附件里的需求说明检查实现。",attachments:[{id:"mock-file",name:"产品需求说明.md",size:18432,mime_type:"text/markdown",kind:"file"},{id:"mock-folder",name:"design-assets",size:2468000,kind:"folder",file_count:18}],capabilities:[{kind:"plugin",id:"github",label:"GitHub"}]},
    label("用户消息 正在发送"),
    {role:"user",state:"sending",localId:`mock-sending-${now}`,text:"重新运行失败的步骤，保留上一轮工作区。"},
    label("助手 等待响应"),
    {role:"bot",streaming:true,localId:`mock-thinking-${now}`,text:"",trace:{structured:false,steps:[],reasoning:"",plan:"",current:"正在思考",startedAt:now-21000,complete:false},applied:[]},
    label("助手 正在执行"),
    {role:"bot",streaming:true,localId:`mock-running-${now}`,text:"",trace:{structured:true,steps:[{id:"mock-step-1",stepKind:"tool",label:"读取智能体团队配置",status:"completed",detail:"已检查 8 个岗位",output:""},{id:"mock-step-2",stepKind:"tool",label:"检查失败的验收条件",status:"running",detail:"正在比对任务材料和岗位要求",output:"checking card #1083\nloading validation rules..."}],activity:[{type:"text",id:"mock-work-1",text:"我先确认失败发生在哪一层，再决定是否需要修改任务或岗位。"},{type:"step",id:"mock-step-1"},{type:"text",id:"mock-work-2",text:"智能体团队配置没有异常，接下来比对任务材料与验收要求。"},{type:"step",id:"mock-step-2"}],reasoning:"",plan:"",current:"检查失败的验收条件",complete:false},applied:[]},
    label("助手 流式回复"),
    {role:"bot",streaming:true,localId:`mock-stream-${now}`,text:"问题已经定位到验收字段缺失。我正在整理不会破坏现有流程的修复步骤",trace:{structured:false,steps:[],reasoning:"",plan:"",current:"正在生成回复",complete:false},applied:[]},
    label("助手 完成回复（点击耗时展开过程）"),
    {id:"mock-answer",role:"bot",text:"问题来自 `bundleId` 没有随任务交接到验收岗位。现有工作区可以保留，只需补齐任务字段映射，然后从当前岗位重新运行。",trace:{structured:true,complete:true,durationSec:151,steps:[{id:"mock-done-1",stepKind:"tool",label:"读取智能体团队配置",status:"completed",detail:"已检查 8 个岗位",output:""},{id:"mock-done-2",stepKind:"tool",label:"检查任务字段",status:"completed",detail:"发现 1 个缺失字段",output:"bundleId: missing"},{id:"mock-done-3",stepKind:"file",label:"生成修复建议",status:"completed",detail:"未修改现有配置",output:""}],activity:[{type:"text",id:"mock-done-work-1",text:"我先确认失败发生在哪一层，再决定是否需要修改任务或岗位。"},{type:"step",id:"mock-done-1"},{type:"text",id:"mock-done-work-2",text:"智能体团队配置没有异常，接下来比对任务材料与验收要求。"},{type:"step",id:"mock-done-2"},{type:"text",id:"mock-done-work-3",text:"已经定位到字段交接缺失，正在整理最小修复。"},{type:"step",id:"mock-done-3"}],reasoning:"",plan:"",current:"已完成"},applied:[]},
    label("助手 已停止"),
    {id:"mock-stopped",role:"bot",text:"已保留当前工作区和已经完成的检查结果。",stopped:true,trace:{structured:true,complete:true,cancelled:true,steps:[{id:"mock-stop-1",label:"读取任务材料",status:"completed",detail:"已完成",output:""},{id:"mock-stop-2",label:"重新运行验收",status:"cancelled",detail:"由你停止",output:""}],reasoning:"",plan:"",current:"已停止"},applied:[]},
    label("助手 执行失败"),
    {role:"bot",ephemeral:true,text:"本地服务没有返回结果，请确认服务仍在运行。"},
    label("助手 需要选择"),
    {id:"mock-options",role:"bot",text:"你希望怎样处理这个阻塞？",options:[{label:"只补齐当前任务",description:"不修改智能体团队配置"},{label:"修复字段映射",description:"之后的新任务也会自动带上该字段"},{label:"先查看差异",description:"暂不应用任何修改"}]},
  ];
}

/* module-function:conversationMessageGalleryGroups */
function conversationMessageGalleryGroups(){
  const groups=[
    {key:"messages",label:"基础消息",description:"文本、附件与发送状态",messages:[]},
    {key:"execution",label:"执行过程",description:"等待、运行与完成状态",messages:[]},
    {key:"decision",label:"必要提问",description:"需要补充的信息与选择",messages:[]},
  ];
  const byLabel=text=>{
    const value=String(text||"");
    if(value.startsWith("用户"))return groups[0];
    if(/等待响应|正在执行|流式回复|完成回复|已停止|执行失败/.test(value))return groups[1];
    if(/需要选择/.test(value))return groups[2];
    return groups[0];
  };
  let current=groups[0],sampleLabel="";
  conversationMessageGallery().forEach(item=>{
    if(item.role==="debug"){
      current=byLabel(item.text);sampleLabel=String(item.text||"").replace(/^(用户|助手)[\s·\u2002]*/,"");
      return;
    }
    current.messages.push({...item,debugLabel:sampleLabel});
  });
  return groups.filter(group=>group.messages.length);
}

/* module-function:conversationMessageGalleryMarkup */
function conversationMessageGalleryMarkup(groups){
  return `<div class="conversation-gallery-groups">${(groups||[]).map(group=>`<section class="conversation-gallery-group" aria-labelledby="conversation-gallery-${group.key}"><div class="conversation-gallery-group-head" id="conversation-gallery-${group.key}"><strong>${esc(group.label)}</strong><span>${esc(group.description)}</span><small>${group.messages.length} 个样例</small></div><div class="conversation-gallery-group-body">${group.messages.map(item=>`<div class="conversation-gallery-sample"><div class="conversation-gallery-sample-label">${esc(item.debugLabel||"")}</div>${conversationMessages([item],{chatId:"mock-gallery",surface:"mock",showActions:false})}</div>`).join("")}</div></section>`).join("")}</div>`;
}

/* module-function:conversationDebugDescriptor */
function conversationDebugDescriptor(){return CONVERSATION_DEBUG_PREVIEWS.find(item=>item.key===S.conversationDebugType)||null;}

/* module-function:conversationDebugPanel */
function conversationDebugPanel(panel=S.conversationPanel){
  const preview=conversationDebugDescriptor();if(!preview)return panel;
  const source=panel||newRailConversationPanel();
  const galleryGroups=preview.gallery?conversationMessageGalleryGroups():null;
  return {...source,id:null,kind:"general",title:preview.label,status:"active",loading:false,error:null,busy:false,messages:galleryGroups?galleryGroups.flatMap(group=>group.messages):[],attachments:[],capabilities:[],context:{context_type:preview.type,intent:preview.intent},debug_preview:true,debug_gallery_groups:galleryGroups};
}

/* module-function:conversationPanelFromSession */
function conversationPanelFromSession(session,options={}){
  const channel=S.channels.find(c=>String(c.id)===String(session.channel_id)),model=session.model||session.context?.local_employee_package?.runtime?.model||"";
  const internalDraftMessages=new Set(["确认应用这份成员草稿","确认应用这份任务草稿","确认创建","确认修改","确认保存","取消当前草稿，不要继续修改。只回复已取消，不要返回草稿。"]),messages=(session.messages||[]).filter(m=>(session.kind||"general")==="general"||m.role!=="user"||!internalDraftMessages.has(String(m.text||"").trim())).map(storedConversationMessage);
  const context=normalizedConversationContext(session);
  const panel={id:session.id||null,owner_path:session.owner_path,subject_type:session.subject_type||'workspace',employee_binding:session.employee_binding||null,work_storage_scope:session.work_storage_scope||"",work_employee:session.work_employee||null,storage_scope:session.storage_scope||"cloud",kind:session.kind||"general",title:session.title||"新对话",status:session.status||"active",context,identity:session.identity||null,channel_id:session.channel_id,model,reasoning_effort:!catalogModel(channel,model)?session.reasoning_effort||"":normalizedEffort(channel,model,session.reasoning_effort||""),input:options.input||"",messages,historyPage:session.messages_page||null,historyLoading:false,historyError:'',attachments:[],capabilities:[],editRewind:null,busy:false,newDraftKey:options.newDraftKey||"default",rail_hosted:!!options.railHosted};
  if(panel.kind==='employee_design'&&panel.storage_scope==='device'){
    const source=session.employee?.source;
    if(source?.id&&source.id===context.creator_local_source_id&&
       (!context.creator_employee_source||source.path===context.creator_employee_source)){
      panel.authoringEmployeeReference=source.reference;
      panel.authoringCapabilities=source.capabilities;
    }
  }
  if(session.active_turn?.active){const live=newLiveAgentMessage('restored-live-');panel.messages.push(live);for(const receipt of session.active_turn.answers||[])conversationQuestionAnswerMessage('panel',receipt.message,panel,receipt.prefix_message);conversationRestoreLiveInteraction(live,session.active_turn);panel.busy=true;panel.interactionDetached=true;setTimeout(()=>conversationWatchDetachedInteraction(panel,live),0);}
  if(!panel.model&&!panel.busy&&S.modelCatalogReady&&S.settingsPreferencesState==='ready')normalizeConversationModelConfig(panel);
  return panel;
}

function conversationHistoryControls(panel){
  if(!panel.id||!panel.historyPage?.has_more&&!panel.historyError)return '';
  if(panel.historyError)return `<div class="read-list-more conversation-history-more">${RunTeamsLoadFailure.markup({variant:'local',title:panel.historyReset?'需要重新载入对话':'无法载入较早的消息',titleKey:panel.historyReset?'conversationDetail.historyReset':'conversationDetail.historyFailed',note:panel.historyReset?'':'已显示的消息会保留。你可以重试载入较早的消息。',noteKey:'conversationDetail.historyHint',error:panel.historyError,retry:'loadOlderConversationMessages()',busy:panel.historyLoading,label:panel.historyReset?'重新载入对话':'重试',labelKey:panel.historyReset?'conversationDetail.reload':'conversationDetail.retry',busyLabelKey:panel.historyReset?'conversationDetail.loading':'conversationDetail.olderLoading'})}</div>`;
  return `<div class="read-list-more conversation-history-more" aria-busy="${!!panel.historyLoading}"><button class="btn ghost" type="button" onclick="loadOlderConversationMessages()" ${panel.historyLoading?'disabled':''} data-app-i18n="conversationDetail.${panel.historyLoading?'olderLoading':'older'}">${panel.historyLoading?'正在载入较早的消息…':'载入较早的消息'}</button></div>`;
}
async function loadOlderConversationMessages(){
  const panel=S.conversationPanel;if(!panel?.id||panel.historyLoading)return;
  if(panel.historyReset){captureConversationPanelDraft();return loadConversationPanelSession(panel.id,{refresh:true});}
  const cursor=panel.historyPage?.next_cursor;if(!cursor)return;
  panel.historyLoading=true;panel.historyError='';render();
  try{
    const result=await api(`/api/chat/${panel.id}?messages_limit=30&cursor=${encodeURIComponent(cursor)}`);
    if(S.conversationPanel!==panel)return;
    if(result.error)throw Object.assign(new Error(result.error),{code:result.code});
    if(!Array.isArray(result.messages)||typeof result.messages_page?.has_more!=='boolean'||result.messages_page.has_more!==!!result.messages_page.next_cursor||result.messages_page.next_cursor===cursor)throw new Error('较早的消息没有载入');
    const ids=new Set(panel.messages.map(item=>Number(item.id)));
    panel.messages=[...result.messages.filter(item=>!ids.has(Number(item.id))).map(storedConversationMessage),...panel.messages];
    panel.historyPage=result.messages_page;panel.historyReset=false;
  }catch(error){if(S.conversationPanel===panel){panel.historyError=error.message||'较早的消息没有载入';panel.historyReset=error.code==='invalid_cursor';}}
  finally{panel.historyLoading=false;if(S.conversationPanel===panel)render();}
}




/* module-function:conversationPanelWorkspaceKey */
function conversationPanelWorkspaceKey(panel=S.conversationPanel){if(panel?.id!=null)return `chat:${panel.id}`;const entry=RunTeamsEmployeeDirectory.forPanel(panel);return entry?`employee:${entry.key}`:panel?.context?.purpose==='create-employee'?'global:create-employee':'global';}

/* module-function:conversationPanelIsVisibleHere */
function conversationPanelIsVisibleHere(panel=S.conversationPanel){return !!panel;}

/* module-function:conversationPanelDraftKey */
function conversationPanelDraftKey(panel=S.conversationPanel){if(!panel)return "";if(panel.id!=null)return `chat:${panel.id}`;const context=panel.context||{},type=context.context_type||panel.kind||"general",intent=context.intent||"general",target=RunTeamsEmployeeDirectory.referenceKey(RunTeamsEmployeeDirectory.panelReference(panel))||RunTeamsEmployeeDirectory.forPanel(panel)?.key||context.workflow_id||(context.purpose==='create-employee'?'create-employee':'default');return `new:global:${type}:${intent}:${target}`;}

/* module-function:conversationModeTitle */
function conversationModeTitle(panel=S.conversationPanel){const type=conversationContextType(panel),intent=conversationIntent(panel);if(type==="pipeline")return intent==="create"?"创建智能体团队":"调整智能体团队";if(type==="worker")return intent==="chat"||intent==="work"?`与 ${panel?.context?.worker_name||panel?.context?.label||"员工"} 对话`:intent==="repair"?"修复员工":intent==="create"?"创建员工":"调整员工";if(type==="standard")return intent==="create"?"创建工作规范":"调整工作规范";if(type==="card")return intent==="repair"?"继续任务":"调整任务";return "新对话";}

/* module-function:conversationPanelTitle */
function conversationPanelTitle(panel=S.conversationPanel){if(!panel)return "新对话";const fixed=conversationFixedContext(panel);if(fixed?.kind==="员工"&&["chat","work"].includes(conversationIntent(panel)))return fixed.label||"员工";if(panel.kind!=="general")return conversationModeTitle(panel);const chat=S.chats.find(item=>String(item.id)===String(panel.id)),title=chat&&chat.title||panel.title||"";return !(panel.messages||[]).length||!title||title==="新对话"?conversationModeTitle(panel):title;}

/* module-function:conversationHeaderTitle */
function conversationHeaderTitle(panel=S.conversationPanel){
  if(!panel)return "新对话";
  const fixed=conversationFixedContext(panel);
  if(fixed?.kind==="员工"&&["chat","work"].includes(conversationIntent(panel)))return fixed.label||"员工";
  if(fixed?.label&&conversationContextType(panel)!=="general"){
    const operation=conversationModeTitle(panel);
    if(fixed.kind==="智能体团队"&&conversationIntent(panel)==="manage")return fixed.label;
    if(operation&&operation!==fixed.label)return `${operation} ${fixed.label}`;
  }
  if(panel.kind!=="general")return conversationPanelTitle(panel);
  const chat=S.chats.find(item=>String(item.id)===String(panel.id)),title=chat&&chat.title||panel.title||"";
  return !(panel.messages||[]).length||!title||title==="新对话"?(conversationContextType(panel)==="worker"&&["chat","work"].includes(conversationIntent(panel))?conversationModeTitle(panel):"新对话"):title;
}

/* module-function:conversationSessionTitle */
function conversationSessionTitle(panel=S.conversationPanel){
  if(!panel)return "新对话";
  if(panel.kind==='employee_design'&&panel.context?.creator_local_source_id)return panel.identity?.name||'员工';
  const chat=panel.id!=null?(S.chats||[]).find(item=>String(item.id)===String(panel.id)):null;
  const title=String(chat?.title||panel.title||"").trim();
  return !title||title==="新对话"||title==="正在准备"?"新对话":title;
}

/* module-function:conversationSessionMenu */
function conversationSessionMenu(event){event.stopPropagation();return RunTeamsEmployeeDirectory.sessionMenu(event);}

/* module-function:conversationCreateAlternatives */
function conversationCreateAlternatives(event){
  event.preventDefault();event.stopPropagation();
  openMenu(event.currentTarget,[{head:true,label:"其他创建方式"},{label:"从空白开始",description:"直接进入智能体团队搭建",icon:"plus",fn:()=>beginCorePipelineDraft()},{divider:true},{empty:true,label:"模板与配置导入即将提供"}],{variant:"pipelineCreate"});
}

/* module-function:conversationPanelStarterItems */
function conversationPanelStarterItems(panel=S.conversationPanel){
  if(conversationEmployeeCreation(panel))return conversationHomeItems(panel).map(([,label,prompt,description,icon])=>[label,prompt,description,icon]);
  const type=conversationContextType(panel),intent=conversationIntent(panel);
  if(type==="card"&&intent==="repair")return [
    ["查看阻塞","告诉我这项任务卡在哪里","查看任务卡住的原因","search"],
    ["尝试修复","尝试修复问题并从已有进度继续","保留已有进度并继续","shield"],
    ["调整任务","调整任务要求，让它可以继续推进","修改要求后继续推进","edit"],
  ];
  if(type==="card")return [
    ["查看进展","总结这项任务目前的进展","查看已有成果和剩余工作","search"],
    ["补充要求","帮我补充这项任务的要求","补充目标、约束或交付","edit"],
    ["解决阻塞","检查这项任务为什么没有继续推进","找出任务没有推进的原因","shield"],
  ];
  if(type==="worker"&&intent==="repair")return [
    ["查找原因","检查这个员工为什么无法完成工作","找出员工无法工作的原因","search"],
    ["修复问题","修复这个员工当前的问题","只修复出问题的部分","shield"],
    ["重新验证","用失败的任务重新验证","确认员工已经恢复工作","play"],
  ];
  if(type==="worker")return [
    ["调整职责","调整这个员工的职责","改变员工负责的工作","user"],
    ["增加技能","给这个员工增加一项工作","增加一项可独立交办的技能","spark"],
    ["优化流程","优化这个员工的工作流程","调整输入、步骤或交付","flow"],
    ["验证改动","验证这次调整是否有效","用真实任务检查改动","play"],
  ];
  if(type==="standard"&&intent==="create")return [
    ["整理共同规则","帮我把团队共同遵守的规则整理成规范","明确规则与例外","doc"],
    ["限定适用员工","创建一条只适用于部分员工的专业规范","选择规范影响的员工","user"],
    ["从现有做法提炼","把我描述的工作习惯提炼成工作规范","减少重复说明","spark"],
  ];
  if(type==="standard")return [
    ["优化规范内容","把这条规范改得更清晰可执行","调整规则和例外","edit"],
    ["调整适用范围","帮我判断应该应用到哪些员工","更新影响范围","user"],
    ["检查冲突","检查这条规范是否过度约束或互相冲突","识别执行风险","search"],
  ];
  if(type==="pipeline"&&intent==="create")return [
    ["从零搭建","从目标开始帮我搭建这个智能体团队","从目标设计流程","spark"],
    ["迁移现有流程","把我现有的工作流程迁移到这里","把已有工作变成智能体团队","import"],
    ["先做简单版本","先帮我搭建一个可以运行的简单版本","先搭建最小可用流程","flow"],
  ];
  if(type==="general")return [
    ["创建员工","帮我创建一名员工","定义一名能独立工作的员工","user"],
    ["组建智能体团队","帮我组建一个智能体团队","把持续工作变成流程","flow"],
    ["开始一项工作","我想开始一项工作","直接研究、分析、创作或执行","spark"],
    ["优化现有智能体团队","检查并优化现有智能体团队","调整员工分工和流转","edit"],
  ];
  
  return [
    ["检查问题","检查这个智能体团队为什么没有顺利推进","找出流程中的问题","search"],
    ["调整流程","帮我调整这个智能体团队的工作流程","优化员工和流转","flow"],
    ["创建任务","在这个智能体团队里创建一项任务","把新工作放进智能体团队","plus"],
  ];
}

/* module-function:conversationPanelStarter */
function conversationPanelStarter(prompt,example=null,promptKey=""){if(S.conversationDebugType)return toast("这是调试预览，不会修改当前对话","info");const panel=S.conversationPanel;if(!panel||panel.busy)return;panel.input=String((promptKey?globalThis.RunTeamsLocale?.t(promptKey,{},prompt)??prompt:prompt)||"");panel.example_materials=example;panel.draft_restored=false;scheduleConversationPanelDraftSave();render();const box=document.getElementById("conversation_box");if(S.conversationPanel===panel&&box?.isContentEditable){box.focus();autoSizeChatInput(box);restoreConversationSelection("panel",panel.input.length);}}

/* module-function:conversationPanelEmptyPresentation */
function conversationPanelEmptyPresentation(){return {icon:'user-guide',title:'今天想完成什么？',detail:''};}

/* module-function:conversationPanelEmpty */
function conversationPanelEmpty(panel=S.conversationPanel,composer=''){
  if(panel?.context?.source_pipeline_workspace)return conversationNewEmpty({title:'讨论这个智能体团队',titleKey:'pipelineBoard.chatWelcome',notice:'在这里讨论目标、流程和进展。要新建任务，请打开看板上的岗位。',noticeKey:'pipelineBoard.chatHint',composer});
  const guidance=conversationEmployeeGuidance(panel),type=conversationContextType(panel),employeeCreation=conversationEmployeeCreation(panel);
  if(!employeeCreation&&(guidance||RunTeamsAssetOverview.employeeEligible(panel)||(type==='worker'&&['chat','work'].includes(conversationIntent(panel)))))return conversationEmployeeEmpty(panel,guidance,composer);
  if(type==='general'||employeeCreation){
    const actions=conversationHomeItems(panel).map(([key,label,,description,icon],index)=>{
      const prefix=employeeCreation?'employeeCreate':'newConversation';
      return conversationNewAction(label,`conversationHomeInsertChoice('${key}')`,icon,description,index,{title:`${prefix}.${key}Title`,detail:`${prefix}.${key}Detail`});
    }).join('');
    return conversationNewEmpty({title:employeeCreation?'这名员工要负责什么？':'今天想完成什么？',titleKey:employeeCreation?'employeeCreate.title':'newConversation.title',actions:actions+(employeeCreation?conversationNewAction('导入资产包','RunTeamsCreatorAuthor.choosePackage()','doc','使用已有员工和随附素材',2,{title:'materials.import',detail:'materials.use'}):''),composer});
  }
  const items=conversationPanelStarterItems(panel);
  const actions=items.map(([label,prompt,description,icon,key],index)=>{
    const encoded=encodeURIComponent(prompt).replace(/'/g,'%27');
    const copy=key?{title:`employeeChat.${key}Title`,detail:`employeeChat.${key}Detail`}:{};
    const args=key?`,null,'employeeChat.${key}Prompt'`:'';
    return conversationNewAction(label,`conversationPanelStarter(decodeURIComponent('${encoded}')${args})`,icon,description,index,copy);
  }).join('');
  const extra=conversationIs(panel,'pipeline','create')?`<button type="button" class="conversation-create-alternatives" aria-haspopup="menu" onclick="conversationCreateAlternatives(event)">其他创建方式${ICON('chev')}</button>`:'';
  return conversationNewEmpty({actions,extra,composer});
}

/* module-function:conversationPanelPlaceholder */
function conversationPanelPlaceholderCopy(panel){
  if(!panel)return null;
  if(panel.context?.source_pipeline_workspace)return {key:'pipelineBoard.chatPrompt',text:'聊聊这个智能体团队的工作…'};
  if(typeof conversationEmployeeAssetMissing==='function'&&conversationEmployeeAssetMissing(panel))return {key:'employeeChat.unavailable',text:'员工暂不可用。你仍可以查看已保存的工作。'};
  if(panel.kind==='employee_design'&&panel.context?.creator_local_source_id&&panel.identity?.name)return {key:'employeeChat.design',text:'交办工作，或调整员工…'};
  if(conversationContextType(panel)!=='worker'||!['chat','work'].includes(conversationIntent(panel)))return null;
  const name=(typeof RunTeamsEmployeeDirectory==='undefined'?null:RunTeamsEmployeeDirectory.forPanel(panel)?.record?.name)||panel.context?.worker_name||panel.context?.label;
  return name?{key:'employeeChat.assignNamed',text:`给${name}交办工作…`,vars:{name}}:{key:'employeeChat.assign',text:'交办工作…'};
}
function conversationPanelPlaceholder(panel=S.conversationPanel,copy=conversationPanelPlaceholderCopy(panel)){if(copy)return globalThis.RunTeamsLocale?.t(copy.key,copy.vars,copy.text)??copy.text;if(conversationEmployeeCreation(panel))return "描述员工要负责的工作…";const type=conversationContextType(panel),intent=conversationIntent(panel);if(type==="card")return intent==="repair"?"描述任务遇到的问题":"告诉助手接下来怎么做";if(type==="worker")return intent==="create"?"描述员工要负责的工作…":intent==="repair"?"描述遇到的问题":"描述你想改变的地方";if(type==="standard")return intent==="create"?"描述团队要共同遵守的规则":"描述规范内容或适用范围的变化";if(type==="pipeline")return intent==="create"?"描述一项持续发生的工作":"描述你想调整的地方";return "说说你想做什么…";}



/* module-function:adoptCreatedEmployeeConversation */
function adoptCreatedEmployeeConversation(panel,session,expectedGeneration){
  if(expectedGeneration!==undefined&&typeof _workspaceBusinessGeneration!=="undefined"&&expectedGeneration!==_workspaceBusinessGeneration)return false;
  if(!panel||Number(panel.id)!==Number(session?.id)||!session.context?.creator_local_source_id)return false;
  Object.assign(panel,{kind:session.kind,storage_scope:session.storage_scope,context:session.context,title:session.title,status:session.status,identity:session.identity});
  if(session.employee)RunTeamsEmployeeDirectory.accept(session.employee);
  deviceChatRemember(session);rememberConversationPanel(panel);
  return true;
}


/* module-function:conversationPanelConfig */
function conversationPanelConfig(panel=S.conversationPanel){return panel?{channel_id:panel.channel_id,model:panel.model,reasoning_effort:catalogModel(S.channels.find(c=>String(c.id)===String(panel.channel_id)),panel.model)?normalizedEffort(S.channels.find(c=>String(c.id)===String(panel.channel_id)),panel.model,panel.reasoning_effort):panel.reasoning_effort,extensions_enabled:false,...(panel.kind==="general"?{context:conversationContext(panel)}:{})}:{};}

/* module-function:conversationPanelModelItems */
function conversationPanelModelItems(panel=S.conversationPanel){normalizeConversationModelConfig(panel);return chatModelItems(conversationPanelConfig(panel));}

/* module-function:conversationPanelRouteValue */
function conversationPanelRouteValue(panel=S.conversationPanel){return chatRouteValue(conversationPanelConfig(panel));}

/* module-function:conversationPanelLoadingState */
function conversationPanelLoadingState(options={}){const cfg={...defaultChatConfig(),...(options.runtime||{})};return conversationPanelFromSession({...cfg,id:options.id||null,kind:options.kind||"general",title:options.title||"正在准备",context:options.context||{},messages:[]},{newDraftKey:Date.now(),railHosted:!!options.railHosted});}

function applyConversationRuntimeChoice(panel,choice){
  const modelChanged=String(panel.channel_id)!==String(choice.channel_id)||panel.model!==choice.model;
  panel.runtimeSelected=true;
  panel.channel_id=choice.channel_id;panel.model=choice.model;panel.reasoning_effort=choice.reasoning_effort;
  const channel=S.channels.find(item=>String(item.id)===String(choice.channel_id));
  rememberChatModel(channel,choice.model,choice.reasoning_effort);
  if(!modelChanged)return;
  if(S.conversationPanel===panel){
    clearConversationCapabilities("panel");
    updateCsel("conversation_effort",effortItems(channel,choice.model,choice.reasoning_effort,true),choice.reasoning_effort);
    refreshConversationDraftItems("panel");
  }else{
    panel.capabilities=[];
    panel.input=String(panel.input||'').replace(CAPABILITY_MARKER_RE,'');
  }
}
async function saveConversationRuntimeChoice(panel,choice){
  if(!panel.id){applyConversationRuntimeChoice(panel,choice);return;}
  const generation=_workspaceBusinessGeneration;
  panel.runtimeSaving=true;
  const trigger=document.getElementById('conversation_runtime'),menu=document.getElementById('popmenu');
  trigger?.setAttribute('aria-busy','true');
  conversationSyncSendState('panel');
  try{
    const saved=await api(`/api/chat/${panel.id}/config`,'POST',conversationPanelConfig({...panel,...choice}));
    if(saved?.error)throw Object.assign(Error(saved.error),{code:saved.code,status:saved.status});
    if(!saved||(S.localLibrary?saved.ok!==true:saved.ok===false))throw Error('Unconfirmed conversation settings');
    if(generation===_workspaceBusinessGeneration)applyConversationRuntimeChoice(panel,choice);
  }catch(error){
    if(generation!==_workspaceBusinessGeneration)return;
    if(error.status>=400&&error.status<500&&![408,429].includes(error.status)&&!['mutation_outcome_unknown','operation_unknown'].includes(error.code)){
      if(!menu?.isConnected){
        if(S.conversationPanel===panel)toast('设置未能保存。仍使用上次保存的设置。','err','runtimeSelector.saveRejected');
        return;
      }
      throw Object.assign(error,{runtimeRejected:true});
    }
    panel.runtimeUnconfirmed=true;
    if(S.conversationPanel===panel){
      const focus=document.getElementById('popmenu')?.contains(document.activeElement)||document.activeElement===document.body;
      closePop();render();
      toast('暂时无法确认设置是否已保存。核对后即可继续。','err','runtimeSelector.unconfirmed');
      if(focus)document.getElementById('conversation_runtime_recheck')?.focus({preventScroll:true});
    }
  }finally{
    panel.runtimeSaving=false;
    if(generation===_workspaceBusinessGeneration&&S.conversationPanel===panel){
      document.getElementById('conversation_runtime')?.removeAttribute('aria-busy');
      conversationSyncSendState('panel');
    }
  }
}
async function checkSavedConversationRuntime(){
  const panel=S.conversationPanel,generation=_workspaceBusinessGeneration,button=document.getElementById('conversation_runtime_recheck');
  if(!panel?.id||!panel.runtimeUnconfirmed||panel.runtimeSaving)return;
  panel.runtimeSaving=true;
  button?.setAttribute('aria-busy','true');button?.setAttribute('aria-disabled','true');
  try{
    const saved=await api(`/api/chat/${panel.id}`,undefined,undefined,{readCurrent:true});
    if(generation!==_workspaceBusinessGeneration)return;
    if(saved?.error||String(saved?.id)!==String(panel.id)||!Object.hasOwn(saved,'channel_id')||typeof saved.model!=='string'||typeof saved.reasoning_effort!=='string')throw Error('Unavailable conversation settings');
    panel.runtimeUnconfirmed=false;
    applyConversationRuntimeChoice(panel,saved);
    if(S.conversationPanel===panel){
      const focus=document.activeElement===button;render();
      if(focus)document.getElementById('conversation_runtime')?.focus({preventScroll:true});
    }
  }catch{
    if(generation===_workspaceBusinessGeneration&&S.conversationPanel===panel)
      toast('暂时无法读取已保存的设置。请重试。','err','runtimeSelector.recheckFailed');
  }finally{
    panel.runtimeSaving=false;
    button?.removeAttribute('aria-busy');button?.removeAttribute('aria-disabled');
    if(generation===_workspaceBusinessGeneration&&S.conversationPanel===panel)conversationSyncSendState('panel');
  }
}

/* module-function:conversationPanelRouteChanged */
async function conversationPanelRouteChanged(value){
  const panel=S.conversationPanel,split=String(value||"").indexOf("::");
  if(!panel||panel.busy||panel.loading||panel.runtimeSaving||panel.runtimeUnconfirmed||split<0)return;
  const id=String(value).slice(0,split),model=String(value).slice(split+2),channel=S.channels.find(item=>String(item.id)===id);
  if(!channel)return;
  const issue=agentSelectionIssue(channel.id,model);
  if(issue){openModelChannelGuide({issue,continuation:()=>{if(S.conversationPanel===panel)return conversationPanelRouteChanged(value);}});return;}
  await saveConversationRuntimeChoice(panel,{channel_id:channel.id,model,reasoning_effort:normalizedEffort(channel,model,panel.reasoning_effort)});
}

/* module-function:conversationPanelEffortChanged */
async function conversationPanelEffortChanged(value){
  const panel=S.conversationPanel;
  if(!panel||panel.busy||panel.loading||panel.runtimeSaving||panel.runtimeUnconfirmed)return;
  const channel=S.channels.find(item=>String(item.id)===String(panel.channel_id));
  await saveConversationRuntimeChoice(panel,{channel_id:panel.channel_id,model:panel.model,reasoning_effort:normalizedEffort(channel,panel.model,value)});
}

/* module-function:conversationWorkspaceMain */
function conversationWorkspaceMain(options={}){
  const view=railConversation(options);
  return `<main class="conversation-workspace-main" aria-label="对话工作区" data-app-i18n-aria-label="newConversation.workspace"><div class="conversation-main-frame">${view.replace('class="rail-assistant','class="rail-assistant conversation-main')}</div></main>`;
}

/* module-function:conversationScrollNearBottom */
function conversationScrollNearBottom(scroll,threshold=72){if(!scroll||scroll.clientHeight<=0)return true;return scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<=threshold;}

/* Local helpers compose existing host data and controls; no duplicate state. */
function conversationMessageDate(message,previous){
  if(message.role!=="user")return "";
  const date=docParseTime(message.ts),prior=docParseTime(previous?.ts);if(!date)return "";
  if(previous&&prior&&date.toDateString()===prior.toDateString()&&date-prior<30*60*1000)return "";
  const now=new Date(),clock=`${date.getHours()}:${String(date.getMinutes()).padStart(2,"0")}`,label=date.toDateString()===now.toDateString()?`今天 ${clock}`:`${date.getFullYear()}年${date.getMonth()+1}月${date.getDate()}日 ${clock}`;
  return `<div class="conversation-date-divider" role="separator">${esc(label)}</div>`;
}
function conversationMessageIdentity(surface,options={}){return '';}
/* module-function:conversationProgressLabel */
function conversationProgressLabel(label,waiting=false,key=""){
  // Keep the same phase when streaming or a surface refresh replaces this node.
  const clock=typeof document!=='undefined'&&Number.isFinite(document.timeline?.currentTime)?document.timeline.currentTime:Date.now(),delay=Math.round(clock%3000);
  return `<span class="${waiting?'cthinking-label ':''}conversation-progress-label" style="animation-delay:-${delay}ms"${key?` data-app-i18n="${esc(key)}"`:""}>${esc(label)}</span>`;
}
function conversationWaitingMarkup(label='',startedAt=Date.now(),key=''){
  const status=String(label||'正在思考'),statusKey=label?key:'conversationDetail.thinking';
  return `<div class="cthinking conversation-waiting" role="status" aria-live="polite" aria-label="${esc(status)}"${statusKey?` data-app-i18n-aria-label="${esc(statusKey)}"`:""} data-thinking-started-at="${Number(startedAt)||Date.now()}" data-thinking-label="${esc(status)}">${conversationProgressLabel(status,true,statusKey)}</div>`;
}
/* module-function:conversationProviderError */
function conversationProviderError(message){
  const trace=message?.trace;if(message?.streaming||message?.stopped||trace?.cancelled||trace?.providerError?.willRetry===true||!(trace?.failed||message?.ephemeral||message?.systemNotice))return null;
  return ['serverOverloaded','usageLimitExceeded'].includes(trace?.providerError?.code)?trace.providerError:null;
}
/* module-function:conversationQuotaReset */
function conversationQuotaReset(message){
  const windows=message?.trace?.rateLimits||[];const blocked=windows.filter(w=>typeof w.usedPercent==='number'&&w.usedPercent>=100);
  if(!blocked.length||blocked.some(w=>typeof w.resetsAt!=='number'||!Number.isFinite(w.resetsAt)||w.resetsAt*1000<=Date.now()))return '';
  return Math.max(...blocked.map(w=>w.resetsAt))*1000;
}
function conversationQuotaDate(timestamp){
  return new Intl.DateTimeFormat(window.RunTeamsLocale?.language||'zh-CN',{month:'long',day:'numeric',hour:'numeric',minute:'2-digit'}).format(timestamp);
}
globalThis.RunTeamsLocale?.onChange(()=>{
  for(const node of document.querySelectorAll('[data-conversation-quota-reset]')){
    node.dataset.appI18nVars=JSON.stringify({date:conversationQuotaDate(Number(node.dataset.conversationQuotaReset))});
    window.RunTeamsLocale.apply(node);
  }
});
/* module-function:conversationProviderNotice */
function conversationProviderNotice(message){
  const error=conversationProviderError(message);if(!error)return '';
  if(error.code==='serverOverloaded')return `<div class="conversation-provider-busy" role="status">${ICON('info')}<span data-app-i18n="conversationDetail.modelBusy">所选模型当前繁忙。请试试其他模型。</span></div>`;
  const reset=conversationQuotaReset(message),date=reset?conversationQuotaDate(reset):'';
  return `<div class="conversation-provider-quota" role="status"><strong data-app-i18n="conversationDetail.quotaUsed">Codex 使用额度已用完</strong>${reset?`<span data-conversation-quota-reset="${reset}" data-app-i18n="conversationDetail.quotaReset" data-app-i18n-vars="${esc(JSON.stringify({date}))}">额度将于 ${esc(date)} 重置。</span>`:''}</div>`;
}
/* module-function:conversationProviderBanner */
function conversationProviderBanner(surface){
  const messages=surface==='panel'?S.conversationPanel?.messages:S.chatMsgs,last=messages?.[messages.length-1];
  return conversationProviderError(last)?.code==='usageLimitExceeded'?conversationProviderNotice(last):'';
}

function conversationCanSteer(surface){
  if(typeof accountSettingsPrefs==='function'&&conversationQueueEnabled())return false;const owner=(surface==="panel"?S.conversationPanel:S);return !!(surface!=="chat"?owner?.canSteer&&!owner.stopping:owner.chatCanSteer&&!owner.chatStopping);}
// Queued text stays a local draft until the original sender confirms acceptance.
// Restoring a window never authorizes an automatic replay.
function conversationQueueEnabled(){return typeof accountSettingsPrefs==='function'&&accountSettingsPrefs().allow_supplement===false;}
function conversationQueueGeneration(){return typeof _workspaceBusinessGeneration==='number'?_workspaceBusinessGeneration:0;}
function conversationQueueOwner(surface){
  if(surface==='panel')return S.conversationPanel;
  S.chatMessageQueues=S.chatMessageQueues||{};
  const key=String(S.chatId);if(!S.chatMessageQueues[key]){const owner=S.chatMessageQueues[key]={id:S.chatId};conversationQueueRestore(owner,S.conversationPanelDrafts?.[`chat:${key}`]?.queue);}return S.chatMessageQueues[key];
}
function conversationQueueState(surface,owner=conversationQueueOwner(surface)){
  return owner?(owner.messageQueue||(owner.messageQueue={items:[],paused:false,generation:conversationQueueGeneration()})):null;
}
function conversationQueueSnapshot(owner){
  const q=owner?.messageQueue;return q?.items?.length?{items:q.items.map(item=>({id:item.id,text:item.text,uncertain:!!(item.uncertain||q.sending===item.id)}))}:null;
}
function conversationQueueRestore(owner,saved){
  if(!owner||!Array.isArray(saved?.items))return;
  owner.messageQueue={items:saved.items.filter(item=>typeof item.id==='string'&&/^queue-[A-Za-z0-9_-]+$/.test(item.id)&&typeof item.text==='string'&&item.text.trim()).map(item=>({id:item.id,text:item.text,uncertain:!!item.uncertain})),paused:true,generation:conversationQueueGeneration()};
}
function conversationQueueSave(surface,owner=conversationQueueOwner(surface)){
  if(!owner||owner.messageQueue?.generation!==conversationQueueGeneration())return;
  const key=surface==='panel'?conversationPanelDraftKey(owner):`chat:${owner.id}`,queue=conversationQueueSnapshot(owner),saved=S.conversationPanelDrafts[key]||{};
  if(surface==='panel'){saved.input=owner.input||'';saved.attachments=(owner.attachments||[]).map(serializableConversationDraftAttachment).filter(Boolean);saved.capabilities=serializableConversationDraftValue(owner.capabilities||[],[]);}
  if(queue)S.conversationPanelDrafts[key]={...saved,queue,saved_at:Date.now()};
  else if(saved.queue){delete saved.queue;if(!saved.input&&!saved.attachments?.length&&!saved.capabilities?.length)delete S.conversationPanelDrafts[key];}
  saveConversationPanelDrafts();
}
function conversationQueuePreviewText(value){return String(value||'').replace(/[ \t\r\n]+$/,'');}
function conversationQueueMarkup(surface){
  const q=conversationQueueState(surface);if(!q?.items.length)return '';
  const busy=surface==='panel'?S.conversationPanel?.busy:S.chatBusy,blocked=q.items.some(item=>item.uncertain);
  const items=q.items.map((item,index)=>{
    const sending=q.sending===item.id,vars=esc(JSON.stringify({index:index+1}));
    const editText=q.editText??item.text;
    const editor=`<div class="conversation-queue-edit"><textarea aria-label="编辑排队消息" data-app-i18n-aria-label="conversationQueue.editQueued" oninput="conversationQueueEditInput('${surface}',this.value)">${esc(editText)}</textarea><div><button type="button" data-queue-save data-queue-action="save" ${editText.trim()?'':'disabled'} onclick="conversationQueueEditSave('${surface}')" data-app-i18n="conversationQueue.save">保存</button><button type="button" data-queue-action="cancel" onclick="conversationQueueEditCancel('${surface}')" data-app-i18n="conversationQueue.cancel">取消</button></div></div>`;
    const status=item.uncertain?'<small role="status" data-app-i18n="conversationQueue.sendUnknown">发送结果待确认，请先查看对话。</small>':sending?'<small role="status" data-app-i18n="conversationQueue.sending">正在发送…</small>':'';
    const preview=`<div class="conversation-queue-copy"><div class="conversation-queue-text">${esc(conversationQueuePreviewText(item.text))}</div>${status}</div><div class="conversation-queue-actions"><button type="button" data-queue-action="edit" aria-label="编辑第 ${index+1} 条排队消息" data-app-i18n-aria-label="conversationQueue.editNth" data-app-i18n-vars="${vars}" title="编辑" data-app-i18n-title="conversationQueue.edit" onclick="conversationQueueEdit('${surface}','${item.id}')" ${sending||item.uncertain?'disabled':''}>${ICON('edit')}</button><button type="button" data-queue-action="remove" aria-label="从队列移除第 ${index+1} 条消息" data-app-i18n-aria-label="conversationQueue.removeNth" data-app-i18n-vars="${vars}" title="从队列移除" data-app-i18n-title="conversationQueue.remove" onclick="conversationQueueDelete('${surface}','${item.id}')" ${sending?'disabled':''}>${ICON('trash')}</button></div>`;
    return `<div class="conversation-queue-item" data-queue-id="${esc(item.id)}">${q.editing===item.id?editor:preview}</div>`;
  }).join('');
  const resume=!busy&&q.paused?`<div class="conversation-queue-resume">${blocked?'':'<small role="status" data-app-i18n="conversationQueue.paused">发送已暂停。</small>'}<button type="button" data-queue-action="resume" onclick="conversationQueueResume('${surface}')" ${blocked?'disabled':''} data-app-i18n="conversationQueue.resume">继续发送</button></div>`:'';
  return `<section class="conversation-queue" aria-label="待发送消息" data-app-i18n-aria-label="conversationQueue.queued"><div class="conversation-queue-list">${items}</div>${resume}</section>`;
}
function conversationQueuePaint(surface){
  const host=document.querySelector?.(`[data-conversation-queue="${surface}"]`);
  if(host){
    const active=document.activeElement,focused=host.contains(active);
    const row=focused?active.closest('[data-queue-id]'):null,action=focused?active.dataset.queueAction:'';
    const editing=focused&&active.matches('textarea'),selection=editing?[active.selectionStart,active.selectionEnd,active.selectionDirection]:null;
    const list=host.querySelector('.conversation-queue-list'),scroll=list?.scrollTop??0;
    const index=row?[...list.children].indexOf(row):0;
    host.innerHTML=conversationQueueMarkup(surface);globalThis.RunTeamsLocale?.apply(host);
    const updated=host.querySelector('.conversation-queue-list');if(updated)updated.scrollTop=scroll;
    if(focused){
      const same=row?host.querySelector(`[data-queue-id="${row.dataset.queueId}"]`):host;
      const target=editing?same?.querySelector('textarea'):action?same?.querySelector(`[data-queue-action="${action}"]:not(:disabled)`):null;
      const nearby=row?(same||updated?.children[Math.min(index,updated.children.length-1)]):null;
      const next=target||nearby?.querySelector('button:not(:disabled)')||host.querySelector('[data-queue-action="resume"]:not(:disabled)')||conversationInputElement(surface);
      next?.focus({preventScroll:true});
      if(target&&selection)target.setSelectionRange(...selection);
    }
  }
  conversationSyncSendState(surface);
}
function conversationQueueHasAttachments(surface,value){
  return !!(conversationAttachments(surface).length||conversationCapabilitiesForSend(surface,value).length);
}
function conversationQueueEnqueue(surface){
  const owner=conversationQueueOwner(surface),q=conversationQueueState(surface),box=conversationInputElement(surface),value=conversationInputValue(box);
  if(!q||!value.trim()||owner.steerSending||(surface==='panel'?owner.stopping:S.chatStopping))return;
  if(conversationQueueHasAttachments(surface,value))return toast('排队消息仅支持文字。请先移除附件和技能。','err','conversationQueue.textOnly');
  q.items.push({id:`queue-${Date.now()}-${Math.random().toString(36).slice(2)}`,text:value});
  setConversationDraftValue(surface,'');setConversationInputValue(box,'',[]);
  if(surface==='panel')captureConversationPanelDraft({fromState:true});
  conversationQueueSave(surface,owner);conversationQueuePaint(surface);return true;
}
function conversationQueueEdit(surface,id){
  const q=conversationQueueState(surface),item=q?.items.find(item=>item.id===id);if(!item||item.uncertain||q.sending===id)return;
  q.editing=id;q.editText=item.text;conversationQueuePaint(surface);document.querySelector?.(`[data-conversation-queue="${surface}"] textarea`)?.focus();
}
function conversationQueueEditInput(surface,value){const q=conversationQueueState(surface);if(q)q.editText=value;const save=document.querySelector?.(`[data-conversation-queue="${surface}"] [data-queue-save]`);if(save)save.disabled=!value.trim();}
function conversationQueueEditSave(surface){
  const q=conversationQueueState(surface),item=q?.items.find(item=>item.id===q.editing);if(!item||!q.editText?.trim())return;
  item.text=q.editText;delete q.editing;delete q.editText;conversationQueueSave(surface);conversationQueuePaint(surface);
  if(!q.paused)void conversationQueueDrain(surface);
}
function conversationQueueEditCancel(surface){const q=conversationQueueState(surface);if(!q)return;delete q.editing;delete q.editText;conversationQueuePaint(surface);if(!q.paused)void conversationQueueDrain(surface);}
function conversationQueueDelete(surface,id){
  const q=conversationQueueState(surface);if(!q||q.sending===id)return;q.items=q.items.filter(item=>item.id!==id);
  if(q.editing===id){delete q.editing;delete q.editText;}conversationQueueSave(surface);conversationQueuePaint(surface);if(!q.paused)void conversationQueueDrain(surface);
}
function conversationQueueResume(surface){const q=conversationQueueState(surface);if(!q||q.items.some(item=>item.uncertain))return;q.paused=false;void conversationQueueDrain(surface);}
function conversationQueueAccepted(surface,owner,id){
  const q=conversationQueueState(surface,owner);q.items=q.items.filter(item=>item.id!==id);q.accepted=id;
  conversationQueueSave(surface,owner);if(surface!=='panel'||S.conversationPanel===owner)conversationQueuePaint(surface);
}
async function conversationQueueDrain(surface,owner=conversationQueueOwner(surface)){
  const q=conversationQueueState(surface,owner),busy=surface==='panel'?owner?.busy:S.chatBusy;
  if(!q||q.generation!==conversationQueueGeneration()||q.paused||q.sending||q.editing||busy||!q.items.length||S.workspaceStartup?.pending)return;
  if(typeof RunTeamsCreatorWork!=='undefined'&&RunTeamsCreatorWork.hasPending(owner.id)){q.paused=true;return;}
  if(surface!=='panel'&&String(S.chatId)!==String(owner.id))return;
  if(q.items[0].uncertain){q.paused=true;return;}
  const item=q.items[0],generation=conversationQueueGeneration();q.sending=item.id;delete q.accepted;
  conversationQueueSave(surface,owner);if(surface!=='panel'||S.conversationPanel===owner)conversationQueuePaint(surface);
  let result;
  try{result=await (surface==='panel'?sendConversationPanel({panel:owner,queued:item}):sendChat({queued:item}));}
  catch(error){q.paused=true;if(generation===conversationQueueGeneration())toast(error.message||'发送已暂停，消息仍在队列中。','err',error.message?undefined:'conversationQueue.pausedWithDraft');}
  finally{
    if(q.items.includes(item)&&result?.attempted)item.uncertain=true;
    delete q.sending;
    if(!result?.completed||generation!==conversationQueueGeneration())q.paused=true;
    if(generation===conversationQueueGeneration()){conversationQueueSave(surface,owner);if(surface!=='panel'||S.conversationPanel===owner)conversationQueuePaint(surface);if(!q.paused)queueMicrotask(()=>void conversationQueueDrain(surface,owner));}
  }
}
function conversationQueueFinished(surface,owner,completed){
  const q=conversationQueueState(surface,owner);if(!q?.items.length)return;
  if(!completed)q.paused=true;
  conversationQueueSave(surface,owner);if(completed&&!q.sending)queueMicrotask(()=>void conversationQueueDrain(surface,owner));
}
// All idle send entry points use the same confirmed channel/model metadata.
function conversationRuntimeReady(surface,panel=null){
  const cfg=surface==='panel'?(panel||S.conversationPanel):S.chatCfg;
  if(!cfg||cfg.loading||cfg.saving||cfg.runtimeSaving||cfg.runtimeUnconfirmed||S.workspaceStartup?.pending||S.workspaceStartup?.channelsPending||S.workspaceStartup?.channelsError||!S.modelCatalogReady)return false;
  if(RunTeamsModelChannels.selectionIssue(S,cfg.channel_id,cfg.model))return false;
  const channel=(S.channels||[]).find(row=>String(row.id)===String(cfg.channel_id)),model=RunTeamsModelChannels.catalog(S,channel).models.find(row=>String(row.value)===String(cfg.model));
  // An empty confirmed effort list means model default; absent metadata is unknown.
  return Array.isArray(model?.efforts);
}
function conversationSendDisabled(surface,busy,value){
  const owner=(surface==="panel"?S.conversationPanel:S),hasText=!!String(value||"").replace(CAPABILITY_MARKER_RE,"").trim();
  if(S.workspaceStartup?.pending||owner?.steerSending)return true;
  if(!busy&&surface==='panel'&&conversationEmployeeGuidance(owner)?.unconfirmed)return true;
  if(!busy&&surface==='panel'&&typeof conversationEmployeeAssetMissing==='function'&&conversationEmployeeAssetMissing(owner))return true;
  if(!busy&&!conversationRuntimeReady(surface))return true;
  if(busy)return (!conversationQueueEnabled()&&!conversationCanSteer(surface))||!!(surface==='panel'?owner?.stopping:S.chatStopping)||!hasText||conversationQueueHasAttachments(surface,value);
  return !hasText&&!conversationAttachments(surface).length;
}
function conversationSteerAccepted(surface,event,panel=null){
  const owner=(surface==="panel"?(panel||S.conversationPanel):S),messages=surface!=="chat"?owner?.messages:S.chatMsgs;
  if(event.request_id&&owner?.steerRequest?.key===event.request_id){
    owner.steerAcknowledged=event.request_id;
    const visible=(surface!=="panel"||S.conversationPanel===owner),box=visible?conversationInputElement(surface):null;
    if(visible&&conversationInputValue(box).trim()===owner.steerRequest.text){setConversationDraftValue(surface,"");setConversationInputValue(box,"",[]);}
    else if(!visible&&owner.input?.trim()===owner.steerRequest.text)owner.input="";
    if(surface==="panel"&&visible)captureConversationPanelDraft({fromState:true});
  }
  if(!messages||messages.some(message=>Number(message.id)===Number(event.message_id)))return;
  const live=messages.find(message=>message.streaming),index=live?messages.indexOf(live):messages.length;
  const message={role:"user",id:event.message_id,text:event.text,ts:event.ts||new Date().toISOString()};messages.splice(index,0,message);
  if(live)live.ts=new Date(Math.max(Date.now(),new Date(message.ts).getTime()+1)).toISOString();
  if((surface==="panel"&&S.conversationPanel!==owner))return;
  const article=live&&document.querySelector(`[data-live-agent="${live.localId}"]`);
  if(article){
    const template=document.createElement("template");template.innerHTML=conversationMessages([{...message,originalIndex:index}],{surface});
    if(!conversationMessageDate(message,messages[index-1]))template.content.querySelector('.conversation-date-divider')?.remove();
    article.before(template.content);
  }else render();
  if(surface==="panel")rememberConversationPanel(owner);
}
async function conversationSteer(surface,recovering=false){
  const owner=(surface==="panel"?S.conversationPanel:S),box=conversationInputElement(surface),text=conversationInputValue(box).trim(),id=conversationChatId(surface);
  if((!recovering&&conversationSendDisabled(surface,true,text))||owner.steerSending||!id)return;
  const request=owner.steerRequest?.text===text?owner.steerRequest:{text,key:`steer-${Date.now()}-${Math.random().toString(36).slice(2)}`};
  owner.steerRequest=request;owner.steerSending=true;conversationSyncSendState(surface);
  try{
    let result;
    do{
      result=await api(`/api/chat/${id}/steer`,"POST",{message:text,request_id:request.key});
      if(result.error){delete owner.steerRequest;throw new Error(result.error);}
      if(result.pending)await new Promise(resolve=>setTimeout(resolve,300));
    }while(result.pending);
    if(!result.accepted||!result.message_id)throw Object.assign(new Error("暂时无法确认是否已接收。输入已保留，请先刷新对话。"),{messageKey:"conversationDetail.steerUnknown"});
    conversationSteerAccepted(surface,result,surface!=="chat"?owner:null);delete owner.steerRequest;
    const current=(surface!=="panel"||S.conversationPanel===owner);
    if(current&&conversationInputValue(conversationInputElement(surface)).trim()===text){setConversationDraftValue(surface,"");setConversationInputValue(conversationInputElement(surface),"",[]);}
    else if(!current&&owner.input?.trim()===text)owner.input="";
    if(surface==="panel"&&current)captureConversationPanelDraft({fromState:true});
  }catch(error){if(owner.steerAcknowledged===request.key)delete owner.steerRequest;else toast(error.message||"暂时无法确认是否已接收。输入已保留，请先刷新对话。","err",error.messageKey||(!error.message?"conversationDetail.steerUnknown":undefined));}
  finally{owner.steerSending=false;if((surface!=="panel"||S.conversationPanel===owner))conversationSyncSendState(surface);}
}
function conversationSyncSendState(surface){
  const box=conversationInputElement(surface),button=box?.closest('.ccomposer')?.querySelector('.sendbtn'),busy=(surface==="panel"?S.conversationPanel?.busy:S.chatBusy);
  if(!button)return;
  button.disabled=conversationSendDisabled(surface,!!busy,conversationInputValue(box));
  const [key,fallback]=conversationSendLabel(surface,!!busy);
  button.dataset.appI18nTitle=key;
  button.dataset.appI18nAriaLabel=key;
  const label=globalThis.RunTeamsLocale?.t(key,{},fallback)??fallback;
  button.title=label;
  button.setAttribute('aria-label',label);
}

function conversationComposerFocused(box,surface){
  if(!box.__conversationCompositionBound){
    box.__conversationCompositionBound=true;
    box.addEventListener('compositionstart',()=>{box.dataset.composing='true';});
    box.addEventListener('compositionend',()=>{box.dataset.composing='false';conversationInputChanged(box,surface);});
  }
  captureConversationSelection(surface);
}

// The host owns requests/session lifecycle. This UI adapter only restores a
// rejected preflight's exact draft after the host captures its cleared editor.
async function conversationSubmit(surface,send){
  const panel=(surface==="panel"?S.conversationPanel:null),busy=panel?panel.busy:S.chatBusy;
  if(!send||S.workspaceStartup?.pending)return;
  const owner=panel||S;
  if(owner?.steerRequest?.text===conversationInputValue(conversationInputElement(surface)).trim()){if(conversationCanSteer(surface))return conversationSteer(surface,true);return;}
  if(conversationSendDisabled(surface,!!busy,conversationInputValue(conversationInputElement(surface)))){conversationSyncSendState(surface);return;}
  if(busy){if(conversationQueueEnabled())return conversationQueueEnqueue(surface);if(conversationCanSteer(surface))return conversationSteer(surface);return;}
  const queue=conversationQueueState(surface);if(queue?.items.length){if(!conversationQueueEnqueue(surface))return;return conversationQueueResume(surface);}
  const messages=panel?(panel.messages||[]):(S.chatMsgs||[]),beforeCount=messages.length;
  const text=conversationInputValue(conversationInputElement(surface)),attachments=conversationAttachments(surface).slice(),capabilities=conversationCapabilities(surface).map(item=>({...item}));
  await send();
  if((surface==="panel"&&S.conversationPanel!==panel))return;
  const after=panel?(panel.messages||[]):(S.chatMsgs||[]),added=after.slice(beforeCount),failure=added.find(message=>message.ephemeral);
  if(!failure)return;
  if(added.some(message=>message.role==="user")){failure.retryAccepted=true;return;}
  failure.retryDraft={text,attachments,capabilities};
  const current=conversationDraftValue(surface),value=current.trim()?current:text;
  setConversationDraftValue(surface,value);
  const box=conversationInputElement(surface);if(box)setConversationInputValue(box,value,conversationCapabilities(surface));
  if(surface==="panel")captureConversationPanelDraft();
  render();
  requestAnimationFrame(()=>{const editor=conversationInputElement(surface);if(editor){editor.focus();restoreConversationSelection(surface,value.length);}});
}

/* module-function:conversationMarkdown */
function conversationMarkdown(value){
  const html=renderMarkdown(value);if(!document.createElement)return html;
  const template=document.createElement('template');template.innerHTML=html;
  template.content.querySelectorAll('pre>code').forEach(code=>{
    const pre=code.parentElement,block=document.createElement('div'),bar=document.createElement('div');block.className='conversation-code-block';bar.className='conversation-code-toolbar';
    const label=document.createElement('span');label.textContent=(code.className.match(/language-([\w+-]+)/)||[])[1]||'';bar.appendChild(label);
    const copy=document.createElement('button');copy.type='button';copy.setAttribute('aria-label','复制代码');copy.setAttribute('onclick','copyConversationCode(this)');copy.textContent='复制';copy.dataset.appI18n='conversationDetail.copy';copy.dataset.appI18nAriaLabel='conversationDetail.copyCode';bar.appendChild(copy);
    pre.replaceWith(block);block.append(bar,pre);
    if(code.textContent.split('\n').length>13){block.classList.add('is-long');const toggle=document.createElement('button');toggle.type='button';toggle.className='conversation-code-expand';toggle.setAttribute('aria-expanded','false');toggle.setAttribute('onclick','toggleConversationCode(this)');toggle.dataset.appI18n='conversationDetail.expandCode';toggle.textContent='展开全部';block.appendChild(toggle);}
  });
  template.content.querySelectorAll('table').forEach(table=>{const wrap=document.createElement('div');wrap.className='conversation-table-scroll';wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','表格，横向滚动查看');table.replaceWith(wrap);wrap.appendChild(table);});
  return template.innerHTML;
}
/* module-function:conversationCopied */
function conversationCopied(button){
  if(!button||button.dataset.copied)return;
  const original=button.innerHTML,label=button.getAttribute('aria-label'),key=button.dataset.appI18nAriaLabel,textKey=button.dataset.appI18n;
  delete button.dataset.appI18n;
  button.innerHTML=ICON('check');button.setAttribute('aria-label','已复制');button.dataset.appI18nAriaLabel='conversationDetail.copied';button.dataset.copied='true';window.RunTeamsLocale?.apply(button);
  setTimeout(()=>{
    if(!button.isConnected)return;
    button.innerHTML=original;
    if(label===null)button.removeAttribute('aria-label');else button.setAttribute('aria-label',label);
    if(key)button.dataset.appI18nAriaLabel=key;else delete button.dataset.appI18nAriaLabel;
    if(textKey)button.dataset.appI18n=textKey;
    delete button.dataset.copied;window.RunTeamsLocale?.apply(button);
  },2000);
}
/* module-function:copyConversationCode */
async function copyConversationCode(button){const text=button.closest('.conversation-code-block')?.querySelector('pre>code')?.textContent;if(text==null)return;try{await navigator.clipboard.writeText(text);conversationCopied(button);}catch(error){toast('无法复制。请手动选择要复制的文字。','err','conversationDetail.copyFailed');}}
/* module-function:toggleConversationCode */
function toggleConversationCode(button){const expanded=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(expanded));button.dataset.appI18n=expanded?'conversationDetail.collapseCode':'conversationDetail.expandCode';button.textContent=expanded?'收起':'展开全部';globalThis.RunTeamsLocale?.apply(button);button.closest('.conversation-code-block').classList.toggle('is-expanded',expanded);}

/* Welcome shortcuts only insert visible text; the editor is the sole request. */
function conversationNewRoute(purpose=''){return purpose==='create-employee'?'/chat/new?purpose=create-employee':'/chat/new';}
function conversationNewWindowKey(purpose=''){return purpose==='create-employee'?'chat:new:create-employee':'chat:new';}
function conversationEmployeeCreation(panel=S.conversationPanel){return !!panel&&!panel.context?.source_pipeline_workspace&&!panel.context?.creator_local_source_id&&((conversationContextType(panel)==='general'&&conversationContext(panel).purpose==='create-employee')||conversationIs(panel,'worker','create'));}
function conversationHomeHeader(panel,controls=''){
 const identity='<span class="conversation-panel-heading"><h2 id="conversation_panel_title" class="conversation-home-header-title" data-app-i18n="shell.newChat">新对话</h2></span>';
 const importAction=conversationEmployeeCreation(panel)?`<button type="button" class="conversation-home-import" title="在输入框中填写导入请求，发送前可编辑" data-app-i18n-title="employeeCreate.importHint" onclick="conversationHomeInsertChoice('import')">${ICON('import')}<span data-app-i18n="employeeCreate.import">准备导入资源包</span></button>`:'';
 return RunTeamsShell.pageHeader(identity,controls+importAction,false);
}
function conversationEmployeeImportPrompt(){return '帮我导入这个员工资源包。';}
function conversationHomeItems(panel=S.conversationPanel){
 if(conversationEmployeeCreation(panel))return [
  ['content','内容创作','创建一名内容创作员工，主要负责：','撰写文章、打磨文案，完成日常创作。','edit'],
  ['research','资料研究','创建一名研究助理，帮我研究以下主题：','查找资料、核对信息，整理研究结论。','search-rail'],
  ['analysis','数据分析','创建一名数据分析员工，帮我分析以下数据或问题：','整理数据、分析变化，生成清晰的报告。','file-table'],
 ];
 return [
 ['employee','创建员工','创建一名员工，帮我完成以下工作：','定义职责和工作方式，让 AI 负责一类工作。','users'],
 ['pipeline','创建智能体团队','创建一个智能体团队，处理以下工作：','安排员工岗位，让成员独立工作或相互交接。','flow'],
 ['resource','查找资源','查找适合以下工作的员工、技能或智能体团队：','根据你的需求，查找合适的员工、技能或智能体团队。','search-rail'],
];}
function conversationHomeAvailable(panel){return !!panel&&!panel.messages?.length&&!panel.work?.length&&!panel.busy&&!panel.context?.source_pipeline_workspace&&!conversationEmployeeGuidance(panel)&&(conversationContextType(panel)==='general'||conversationEmployeeCreation(panel));}
function conversationEmployeePromptChoices(panel){
 const entries=conversationHomeItems(panel).map(([key,,prompt])=>[key,prompt]);
 return [...entries,['import',conversationEmployeeImportPrompt()]];
}
function conversationHomeInsertChoice(key){
 const panel=S.conversationPanel;if(S.conversationDebugType||!conversationHomeAvailable(panel))return;
 const employee=conversationEmployeeCreation(panel),prefix=employee?'employeeCreate':'newConversation';
 const choices=employee?conversationEmployeePromptChoices(panel):conversationHomeItems(panel).map(([name,,prompt])=>[name,prompt]);
 const entry=choices.find(([name])=>name===key);if(!entry)return;
 const prompt=globalThis.RunTeamsLocale?.t(`${prefix}.${key}Prompt`,{},entry[1])??entry[1];
 const prompts=choices.flatMap(([name,fallback])=>[fallback,...['zh-CN','en'].map(locale=>globalThis.RUNTEAMS_LOCALES?.[locale]?.[`${prefix}.${name}Prompt`])]).filter(Boolean);
 const box=document.getElementById('conversation_box'),draft=box?conversationInputValue(box):String(panel.input||''),text=draft.trimStart(),previous=prompts.find(value=>text.startsWith(value));
 const body=previous?text.slice(previous.length):draft,tail=body.trim()?body:'';
 const value=previous?prompt+tail:prompt+(tail?'\n'+tail:'');
 if(box)setConversationInputValue(box,value,panel.capabilities||[]);
 conversationPanelStarter(value,panel.example_materials||null);
}
