/* Trusted pipeline panels: configuration, task details and work records. */
(()=>{
'use strict';
const host=()=>RunTeamsSourcePipelines,current=()=>host().taskWorkspace();
const STATUS_FIRST_ROUTING='status-first',OUTCOME_PREFIX='outcome:',WAIT_FOR_INPUT='wait-for-input',COMPLETE_HERE='complete-here';
const owned=s=>current()===s;
const state=s=>s.panels||(s.panels={loading:false,error:'',data:null,draft:null,pending:null});
const storageKey=s=>'runteams.pipeline-settings:'+s.storageScope+':'+JSON.stringify(s.reference);
function persist(s){const p=state(s);if(!p.draft&&!p.pending){RunTeamsWorkState.removeItem(storageKey(s));return;}RunTeamsWorkState.setItem(storageKey(s),JSON.stringify({data:p.data,draft:p.draft,pending:p.pending,unknown:p.unknown}));}
function select(kind){host().select(kind);}
async function settings({activityExpanded=false}={}){const s=current();if(!s)return;host().select('settings',{activityExpanded});return loadSettingsData(s);}
async function read(s=current()){
 if(!owned(s))return;const p=state(s);if(p.loading)return;p.loading=true;render();
 const selection=S.sel,overview=selection?.type==='source-pipeline'&&selection.id==='settings';
 try{const {configuration_states,...value}=await host().request('settings',{reference:s.reference,...(overview?{include_configuration:true}:{})});if(!owned(s))return false;
  if(overview&&selection===S.sel)selection.configurationSnapshot=configuration_states;
  if(p.draft&&p.data?.source_revision!==value.source_revision)p.conflict=!p.pending;
  else{p.data=value;p.conflict=false;}
  if(!(p.draft&&p.error==='pipelineEditor.saveRejected'))p.error='';
  if(S.sel?.type==='source-pipeline'&&S.sel.id==='position'){
   void readPositionRuntime(s,S.sel.positionKey);
   openPositionConfiguration(s);
  }
  return true;
 }catch(error){if(owned(s))p.error=error.message;return false;}
 finally{p.loading=false;if(owned(s))render();}
}
function draft(){const s=current(),p=s&&state(s);if(!p?.data||p.pending||p.saving||p.commitRefresh||s.data.ui.mode!=='creator')return null;p.draft||=structuredClone(p.data.asset);return p.draft;}
async function refreshCommitted(s){
 const p=state(s);
 void refreshCoreTeam({localFirst:true,readPriority:'background'}).catch(()=>{});
 const board=await host().refresh({afterEdit:true});
 if(!owned(s))return;
 const settings=await read(s);
 if(!owned(s)||!board||!settings)return;
 p.commitRefresh=null;
}
function focusAfterSettingsAction(s,focused){
 if(!focused||!owned(s)||document.activeElement!==document.body)return;
 const recovery=document.querySelector('.source-pipeline-settings-drawer [data-pipeline-recovery]:not(:disabled)');
 if(recovery){recovery.focus({preventScroll:true});return;}
 requestAnimationFrame(()=>{
  if(!owned(s)||document.activeElement!==document.body)return;
  document.querySelector('.asset-overview-trigger')?.focus({preventScroll:true});
 });
}
async function retryCommittedRefresh(){
 const s=current(),p=s&&state(s);if(!p?.commitRefresh||p.saving)return;
 const focused=document.activeElement?.matches?.('[data-pipeline-recovery]');
 p.saving='refresh';p.error='';render();
 try{await refreshCommitted(s);}
 finally{p.saving=false;if(owned(s)){render();focusAfterSettingsAction(s,focused);}}
}
function queueSave(s){
 const p=state(s);
 clearTimeout(p.saveTimer);
 try{persist(s);}catch{
  p.error='pipelineEditor.saveStorageFailed';render();return;
 }
 scheduleDraftSave(s,p);
}
function activeTextField(s){
 if(!s||!owned(s)||S.sel?.id!=='settings')return null;
 const active=document.activeElement;
 if(!active?.matches?.('#rgDrawer .configuration-surface :is(input,textarea):not([readonly])')||active.selectionStart===null||active.closest('.pipeline-configuration-session'))return null;
 const owner=active.closest('[data-pipeline-editor-owner]')?.dataset.pipelineEditorOwner;
 return owner===host().key(s.reference)?active:null;
}
function holdTextField(){
 const s=current(),selection=S.sel;
 if(s&&selection?.id==='work'&&selection.workflow){
  const state=taskConfigurationState(s,selection.workflow?.id),input=document.activeElement;
  if(!state.saving&&!state.pending&&input?.closest?.('#source_task_configuration'))
   return RunTeamsConfigurationForm.holdInput(input,()=>owned(s)&&S.sel===selection,()=>render());
 }
 const field=activeTextField(s);
 return field?RunTeamsConfigurationForm.holdInput(field,()=>owned(s),()=>render()):false;
}
function scheduleDraftSave(s,p){
 p.saveTimer=setTimeout(()=>{
  if(!p.draft||p.pending||p.conflict)return;
  if(activeTextField(s)){
   scheduleDraftSave(s,p);
   return;
  }
  void save(false,s);
 },240);
}
function changed(path,value){
 const s=current(),p=s&&state(s),asset=p&&(p.draft||p.data?.asset);
 if(!asset||path.reduce((node,key)=>node[key],asset)===value)return;
 const editable=draft();if(!editable)return;
 const target=path.slice(0,-1).reduce((node,key)=>node[key],editable);
 target[path.at(-1)]=value;
 queueSave(s);
}
async function save(retry=false,s=current()){
 if(!s||!owned(s)&&!host().sameScope(s))return;
 const p=state(s);clearTimeout(p.saveTimer);if(p.saving||p.pending&&!retry||p.conflict)return;
 const previous=p.pending;
 if(!p.pending){if(!p.draft)return;p.pending={operation_id:crypto.randomUUID(),reference:s.reference,base_revision:p.data.source_revision,asset:structuredClone(p.draft)};}
 const restoring=!!p.pending.restore_revision;
 try{persist(s);}catch{
  p.error=restoring?'pipelineSettings.restoreStorageFailed':previous?'pipelineEditor.draftStorageFailed':'pipelineEditor.saveStorageFailed';
  if(restoring)p.retry=true;
  p.pending=previous;if(owned(s))render();return;
 }
 p.saving=restoring?'restore':'save';p.error='';p.validationError='';if(owned(s))render();
 try{
  if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();
  if(!owned(s)&&!host().sameScope(s))return;
  const result=await host().request('edit',p.pending);
  if(typeof result?.revision!=='string'||!result.revision||!result.pipeline)throw Error('Unconfirmed pipeline edit');
  if(!owned(s)){
   if(host().sameScope(s)){
    const saved=JSON.parse(RunTeamsWorkState.getItem(storageKey(s))||'null');
    if(saved?.pending?.operation_id===p.pending.operation_id){
     RunTeamsWorkState.removeItem(storageKey(s));
     p.pending=null;p.draft=null;
    }
   }
   return;
  }
  if(result.pipeline){
   s.data={...s.data,source_revision:result.revision,pipeline:result.pipeline,name:result.pipeline.name};
   render();
  }
  p.pending=null;p.draft=null;p.unknown=false;p.retry=false;p.data=null;p.commitRefresh=restoring?'restore':'save';
  persist(s);await refreshCommitted(s);}
 catch(error){
  if(owned(s)){
   if(!p.pending)p.error=restoring?'pipelineSettings.restoredRefreshFailed':'pipelineEditor.savedRefreshFailed';
   else if(error.confirmedReply&&error.code!=='operation_unknown'){
    p.pending=null;p.unknown=false;p.retry=false;p.error=restoring?'pipelineSettings.restoreRejected':'pipelineEditor.saveRejected';p.validationError=error.message;
    if(error.message.includes('更新'))p.conflict=true;
   }else{p.unknown=true;p.retry=false;p.error=restoring?'employeeHistory.restoreUnconfirmed':'pipelineEditor.saveUnconfirmed';}
   persist(s);
  }
 }
 finally{p.saving=false;if(p.pending&&!owned(s))p.unknown=true;if(owned(s))render();}
}
async function rename(name,original){
 const s=current(),p=s&&state(s);
 if(!p||p.loading||p.saving||p.draft||p.pending||RunTeamsWorkState.getItem(storageKey(s)))throw Object.assign(Error('请先在智能体团队设置中处理未保存的修改。'),{pipelineRenameKey:'renameDraft'});
 const value=await host().request('settings',{reference:s.reference});
 if(!owned(s))return;
 if(p.loading||p.saving||p.draft||p.pending)throw Object.assign(Error('请先在智能体团队设置中处理未保存的修改。'),{pipelineRenameKey:'renameDraft'});
 if(value.asset.pipeline.name!==original)throw Object.assign(Error('智能体团队名称已在其他窗口更新，请重新编辑。'),{pipelineRenameKey:'renameConflict'});
 p.data=value;p.conflict=false;
 const asset=draft();if(!asset)throw Object.assign(Error('当前智能体团队名称不可编辑。'),{pipelineRenameKey:'renameUnavailable'});
 asset.pipeline.name=name;
 await save();
 if(owned(s)&&p.draft){
  const [pipelineRenameKey,copy]=p.pending?
   ['renamePending','请在智能体团队设置中核对名称。']:['renameRejected','无法更改智能体团队名称。可在智能体团队设置中继续编辑。'];
  throw Object.assign(Error(copy),{pipelineRenameKey});
 }
}
async function receipt(){const s=current(),p=s&&state(s);if(!p?.pending||p.saving)return;const focused=document.activeElement?.matches?.('[data-pipeline-recovery]');
 if(p.retry){p.unknown=false;await save(true);focusAfterSettingsAction(s,focused);return;}
 const restoring=!!p.pending.restore_revision;p.saving=restoring?'checkRestore':'check';p.error='';render();
 try{const r=await host().request('edit-operation',{reference:s.reference,operation_id:p.pending.operation_id});if(!owned(s))return;
  if(r?.state==='confirmed'&&typeof r.result?.revision==='string'&&r.result.revision){
   p.pending=null;p.draft=null;p.unknown=false;p.data=null;p.commitRefresh=restoring?'restore':'save';persist(s);await refreshCommitted(s);
  }else if(r?.state==='unknown'){p.retry=true;p.error=restoring?'pipelineSettings.restoreReceiptMissing':'pipelineEditor.receiptMissing';}
  else p.error=restoring?'pipelineSettings.restoreReceiptFailed':'pipelineEditor.receiptFailed';}
 catch{if(owned(s))p.error=p.pending?(restoring?'pipelineSettings.restoreReceiptFailed':'pipelineEditor.receiptFailed'):(restoring?'pipelineSettings.restoredRefreshFailed':'pipelineEditor.savedRefreshFailed');}finally{p.saving=false;if(p.pending&&!owned(s))p.unknown=true;if(owned(s)){render();focusAfterSettingsAction(s,focused);}}
}
function cancel(){const s=current();if(!s||state(s).pending)return;const p=state(s);clearTimeout(p.saveTimer);p.draft=null;p.conflict=false;p.error='';p.validationError='';persist(s);void read(s);}
const settingsFields={
 standard:{path:['pipeline','team_standard'],label:'团队规范',labelKey:'standards'},
 description:{path:['description'],label:'说明',labelKey:'description'}
};
const settingsValue=(asset,field)=>settingsFields[field].path.reduce((node,key)=>node[key],asset);
function focusSettingsField(s,id){
 requestAnimationFrame(()=>{
  if(owned(s)&&S.sel?.id==='settings')document.getElementById(id)?.focus({preventScroll:true});
 });
}
function startSettingsEdit(field){
 const s=current(),p=s&&state(s);
 if(!Object.hasOwn(settingsFields,field)||S.sel?.id!=='settings'||!p?.data||s.data.ui.mode!=='creator'||
    p.settingsEdit||p.draft||p.pending||p.saving||p.commitRefresh||p.conflict)return;
 p.settingsEdit={field,base:p.data,value:settingsValue(p.data.asset,field)||''};
 render();
 focusSettingsField(s,'source_pipeline_setting_'+field);
}
function updateSettingsEdit(field,value){
 const s=current(),edit=s&&state(s).settingsEdit;
 if(S.sel?.id==='settings'&&edit?.field===field)edit.value=value;
}
async function finishSettingsEdit(field,submit){
 const s=current(),p=s&&state(s),edit=p?.settingsEdit;
 if(S.sel?.id!=='settings'||edit?.field!==field)return;
 const value=field==='description'?edit.value:edit.value.trim(),original=settingsValue(edit.base.asset,field)||'';
 if(submit&&(s.data.ui.mode!=='creator'||p.draft||p.pending||p.saving||p.commitRefresh||!p.data))return;
 p.settingsEdit=null;
 document.activeElement?.blur?.();
 if(submit&&value!==original){
  const asset=structuredClone(edit.base.asset);
  const path=settingsFields[field].path,key=path.at(-1);
  const target=path.slice(0,-1).reduce((node,part)=>node[part],asset);
  target[key]=value;
  p.draft=asset;
  if(p.data.source_revision===edit.base.source_revision)await save();
  else{
   p.data=edit.base;p.conflict=true;
   try{persist(s);}catch{p.error='pipelineEditor.saveStorageFailed';}
   render();
  }
 }else render();
 if(!document.activeElement||document.activeElement===document.body)focusSettingsField(s,'source_pipeline_edit_'+field);
}
function settingsEditForm(p,field){
 const edit=p.settingsEdit;
 if(edit?.field!==field)return '';
 const {label,labelKey}=settingsFields[field],id='source_pipeline_setting_'+field;
 const attributes=`id="${id}" class="inp" oninput="RunTeamsSourcePipelinePanels.updateSettingsEdit('${field}',this.value)"`;
 const finish="RunTeamsSourcePipelinePanels.finishSettingsEdit('"+field+"',";
 return `<form class="configuration-surface source-pipeline-field-form" onsubmit="event.preventDefault();${finish}true)" onkeydown="if(event.key==='Escape'&&!event.isComposing){event.preventDefault();event.stopPropagation();${finish}false)}">
  <label class="sr-only" for="${id}" data-app-i18n="pipelineSettings.${labelKey}">${label}</label>
  <textarea ${attributes}>
${esc(edit.value)}</textarea>
  <div class="source-pipeline-field-actions"><button type="button" class="btn" onclick="${finish}false)" data-app-i18n="employeeSettings.cancel">取消</button><button class="btn pri" type="submit" data-app-i18n="pipelineSettings.saveField">保存</button></div>
 </form>`;
}
function settingsContent(s,p,asset){
 const employees=p.data.employees;
 const configuration=RunTeamsEmployeeConfiguration,selection=S.sel;
 const own=asset.configuration?.groups?.some(group=>group.fields.length)?ownConfigurationEntry(s):null;
 const memberEntries=employees.filter(employee=>employee.field_count&&!employee.error).map(employee=>memberConfigurationEntry(s,employee));
 const entries=[...(own?[own]:[]),...memberEntries];
 requestAnimationFrame(()=>{
  if(owned(s)&&S.sel===selection)configuration.mountGroup(entries,selection,selection.configurationSnapshot,p.loading);
 });
 const ownFields=own?configuration.groupParts(own.key,{name:'智能体团队自身',labelKey:'pipelineSettings.own'}):'';
 const programs=!own&&s.data.programs_available?RunTeamsWorkAuthorization.settings(ownConfigurationEntry(s)):'';
 const memberFields=memberEntries.map(entry=>configuration.groupParts(entry.key,{...entry.record,qualifyGroups:entries.length>1})).join('');
 const fields=ownFields+programs+memberFields;
 return fields?`<div class="source-pipeline-own-settings settings-section-stack">${fields}</div>`:'';
}
function drawer(){const s=current();if(!s)return '';const p=state(s),positionKey=S.sel?.id==='position'?S.sel.positionKey:null,asset=p.draft||p.data?.asset,locked=s.data.ui.mode!=='creator'||!!p.pending||p.saving||p.commitRefresh;
 const settingsLoading=(p.loading||!positionKey)&&!p.data&&!asset&&!p.error;
 let body=settingsLoading?RunTeamsSkeletons.region(positionKey?'detail':'overview-configuration',undefined,'pipelineSettings.loading'):'';
 if(asset){
  if(positionKey)body+=positionMarkup(asset,positionKey,locked||p.conflict);
  else body+=settingsContent(s,p,asset);
 }
 if(p.conflict)body+='<div class="configuration-conflict" role="alert" data-app-i18n="pipelineEditor.conflict">源码已在其他位置更新，你的输入已保留。取消本次修改后可读取最新定义。</div>';
 if(p.commitRefresh&&!p.saving){
  const key=p.commitRefresh==='restore'?'pipelineSettings.restoredRefreshFailed':'pipelineEditor.savedRefreshFailed';
  body+=`<p class="field-error" role="alert" data-app-i18n="${key}">${esc(RunTeamsLocale.t(key))}</p>`;
 }
 else if(/^(pipelineEditor|pipelineSettings|employeeHistory)\./.test(p.error))body+=`<p class="field-error" role="alert" data-app-i18n="${esc(p.error)}">${esc(RunTeamsLocale.t(p.error))}</p>`;
 else if(p.error)body+=RunTeamsLoadFailure.markup({variant:'local',title:'无法读取智能体团队设置',titleKey:'pipelineSettings.failed',labelKey:'employeeHistory.retry',busyLabelKey:'pipelineSettings.loading',error:p.error,retry:'RunTeamsSourcePipelinePanels.read()'});
 if(p.validationError)body+=`<p class="field-error" role="alert">${esc(p.validationError)}</p>`;
 body+=settingsActions(p);
 if(!positionKey){
  const overview=RunTeamsAssetOverview,sel=S.sel,pipeline=asset?.pipeline||s.data.pipeline||{};
  const standard=pipeline.team_standard||'',creator=s.data.ui.mode==='creator';
  const standardBody=p.settingsEdit?.field==='standard'?settingsEditForm(p,'standard'):standard?renderMarkdown(standard):'<span data-app-i18n="pipelineSettings.empty">尚未填写团队规范。</span>';
  const editable=creator&&asset&&!locked&&!p.conflict&&!p.settingsEdit;
  const description=asset?asset.description||'':s.data.description||'';
  const descriptionControl=p.settingsEdit?.field==='description'?settingsEditForm(p,'description'):editable?
   `<button type="button" id="source_pipeline_edit_description" class="overview-edit-description" aria-label="编辑说明" data-app-i18n-aria-label="pipelineSettings.editDescription" onclick="RunTeamsSourcePipelinePanels.startSettingsEdit('description')">${description?esc(description):'<span data-app-i18n="pipelineSettings.descriptionEmpty">尚未填写说明。</span>'}</button>`:'';
  const standardContent=`<div class="overview-standard markdown-compact" ${editable?'id="source_pipeline_edit_standard" role="button" tabindex="0" aria-label="编辑团队规范" data-app-i18n-aria-label="assetOverview.editStandard" onclick="RunTeamsSourcePipelinePanels.editStandard(event)" onkeydown="RunTeamsSourcePipelinePanels.editStandard(event)"':''}>${standardBody}</div>`;
  const hasStandard=!!(standard||creator&&asset);
  const standardId='overview-team-standard';
  const collapsed=hasStandard&&(sel.standardSections??=new Set([standardId])).has(standardId);
  const standardToggle=hasStandard?`<button type="button" class="overview-standard-toggle" aria-label="团队规范" title="团队规范" data-app-i18n-aria-label="pipelineSettings.standards" data-app-i18n-title="pipelineSettings.standards" aria-expanded="${!collapsed}" aria-controls="${standardId}" data-settings-section-key="${standardId}" onclick="RunTeamsSourcePipelinePanels.toggleStandard(this)" ${p.settingsEdit?'disabled':''}>${ICON('chev')}</button>`:'';
  const descriptionRow=descriptionControl||(hasStandard?(description?`<span>${esc(description)}</span>`:'<span data-app-i18n="pipelineSettings.descriptionEmpty">尚未填写说明。</span>'):'');
  const descriptionDetails=hasStandard?`<div id="${standardId}" class="settings-section-body overview-standard-body"${collapsed?' hidden':''}>${standardContent}</div>`:'';
  const version=creator?p.data?.version:s.data.installed_version||p.data?.version;
  const publication=window.RunTeamsPipelineMarket?.headerAction?.(s);
  const publish=publication?`<button type="button" id="pipeline_market_open" class="btn pri sm" onclick="RunTeamsSourcePipelinePanels.overviewVersion()" ${publication.disabled?'disabled':''}${publication.popup?' aria-haspopup="dialog" aria-expanded="'+!!publication.expanded+'"':''}><span data-app-i18n="${esc(publication.labelKey)}">${esc(publication.label)}</span></button>`:'';
  const mode=RunTeamsHost.pipeline?.creationModeControl(s)||'';
  const extras=s.data.programs_available?RunTeamsCreatorWork.controls(host().workContext()):'';
  return overview.shell({title:pipeline.name||s.data.name,description,descriptionControl:descriptionRow+standardToggle,descriptionDetails,avatar:host().pipelineIcon(s,false),
   environment:RunTeamsEnvironment.pipelineRows(p.data),configuration:body,records:RunTeamsWorkRecords.taskResults(s.data.workflows||[],s.reference).results,
   version,modeControl:mode,versionLoading:settingsLoading,actions:publish,extras:extras+(window.RunTeamsPipelineMarket?.versionPopover?.(s)||'')});
 }
 return detailDrawerShell({className:'employee-configuration-drawer source-pipeline-settings-drawer node-detail-drawer core-position-detail-drawer',
  header:positionHeader(s,asset,positionKey),body,bodyClass:'employee-configuration-body',
  attrs:`data-pipeline-editor-owner="${esc(host().key(s.reference))}" aria-label="岗位详情" data-app-i18n-aria-label="pipelineSettings.position"`});
}
const settingsBusyCopy={
 restore:['employeeHistory.restoring','正在恢复版本…'],
 checkRestore:['employeeHistory.checkingRestore','正在核对恢复结果…'],
 refresh:['pipelineSettings.refreshing','正在刷新智能体团队…']
};
function settingsActions(p){
 if(p.saving){
  if(p.saving==='save'||p.saving==='check')return '';
  const [key,label]=settingsBusyCopy[p.saving];
  return `<div class="configuration-save configuration-save-inline"><span role="status" data-app-i18n="${key}">${label}</span></div>`;
 }
 if(p.pending){
  const restoring=!!p.pending.restore_revision;
  const [statusKey,status]=restoring?['pipelineSettings.restorePending','恢复结果待核对']:['pipelineEditor.savePending','保存结果待核对'];
  const [actionKey,action]=restoring?(p.retry?['employeeHistory.retryRestore','重试恢复']:['employeeHistory.checkRestore','核对恢复结果']):
   p.retry?['pipelineEditor.retrySave','重试原保存']:['pipelineEditor.checkSave','核对保存结果'];
  return `<div class="configuration-save configuration-save-inline">${restoring&&p.retry?'':`<span data-app-i18n="${statusKey}">${status}</span>`}<button class="btn" type="button" data-pipeline-recovery onclick="RunTeamsSourcePipelinePanels.receipt()" data-app-i18n="${actionKey}" aria-label="${action}" data-app-i18n-aria-label="${actionKey}">${action}</button></div>`;
 }
 if(p.commitRefresh)return '<div class="configuration-save configuration-save-inline"><button class="btn" type="button" data-pipeline-recovery onclick="RunTeamsSourcePipelinePanels.retryCommittedRefresh()" data-app-i18n="pipelineSettings.retryRefresh" aria-label="重新加载智能体团队" data-app-i18n-aria-label="pipelineSettings.retryRefresh">重新加载智能体团队</button></div>';
 return p.draft&&(p.error||p.conflict)?`<div class="configuration-save configuration-save-inline"><button class="btn" type="button" onclick="RunTeamsSourcePipelinePanels.cancel()" data-app-i18n="employeeSettings.cancel">取消</button>${p.conflict?'':'<button class="btn" type="button" onclick="RunTeamsSourcePipelinePanels.save()" data-app-i18n="employeeHistory.retry">重试</button>'}</div>`:'';
}
function memberConfigurationEntry(s,e){
 return {key:'pipeline-config:'+JSON.stringify(s.reference)+':'+e.source,record:{name:e.name},source:{id:s.reference.source_id,path:e.source,reference:e.reference},pipeline_reference:s.reference,pipeline_name:s.data.name,configurationRevision:e.revision};
}
function positionConfigurationEntry(s,position){
 if(position?.kind!=='employee')return null;
 const member=memberFor(state(s),position);
 return member&&(member.field_count||member.error)?memberConfigurationEntry(s,member):null;
}
function openPositionConfiguration(s){
 const selection=S.sel,p=state(s);
 if(selection?.type!=='source-pipeline'||selection.id!=='position')return;
 const position=p.data?.asset.pipeline.positions.find(row=>row.key===selection.positionKey);
 const entry=positionConfigurationEntry(s,position);
 if(entry)void RunTeamsEmployeeConfiguration.mountInline(entry,selection);
}
function ownConfigurationEntry(s){
 return {key:'pipeline-own-config:'+JSON.stringify(s.reference),record:{name:s.data.name},pipeline_reference:s.reference,pipeline_name:s.data.name,pipeline_own:true,configurationRevision:state(s).data?.source_revision};
}
async function configurationRequest(session,method,body,receipt){const ref=session.entry.pipeline_reference;
 const command={reference:ref,...(session.entry.pipeline_own?{}:{employee_source:session.entry.source.path}),action:receipt?'receipt':method==='POST'?'save':'read',...(receipt?{operation_id:session.pending.operation_id}:body?Object.fromEntries(Object.entries(body).filter(([k])=>k!=='employee_source')):{})};
 return host().request(session.entry.pipeline_own?'configuration':'employee-configuration',command);
}
async function loadSettingsData(s){
 const p=state(s);
 if(!p.data){try{const saved=JSON.parse(RunTeamsWorkState.getItem(storageKey(s))||'null');if(saved){Object.assign(p,saved);if(p.pending)p.unknown=true;}}catch(error){p.error='上次输入暂时无法读取。';}}
 return read(s);
}
async function readEmployeeChoices(){
 const s=current(),p=s&&state(s);if(!p||p.choicesLoading)return;
 p.choicesLoading=true;render();
 let result;
 try{
  const reply=await host().request('creation-choices');
  if(Array.isArray(reply.items))result=reply;
 }catch{/* Keep the current binding on a catalog read failure. */}
 p.choicesLoading=false;
 if(!owned(s))return;
 if(result){
  p.choices=result.items;p.choiceErrors=Array.isArray(result.errors)?result.errors:[];
  p.choicesFailed=!p.choices.length&&p.choiceErrors.length>0;
 }else p.choicesFailed=true;
 render();
}
function employeeChoicesStatus(p){
 const retry='RunTeamsSourcePipelinePanels.readEmployeeChoices()';
 const retryOptions={variant:'local',labelKey:'employeeHistory.retry',busyLabelKey:'pipelineEditor.choicesLoading',retry};
 if(p.choicesLoading)return '<p class="help" role="status" data-app-i18n="pipelineEditor.choicesLoading">正在载入员工和技能…</p>';
 if(p.choicesFailed)return RunTeamsLoadFailure.markup({...retryOptions,title:'无法载入员工和技能',titleKey:'pipelineEditor.choicesFailed'});
 if(Array.isArray(p.choices)&&!p.choices.length)return '<p class="help" data-app-i18n="pipelineEditor.choicesEmpty">没有可选的员工和技能。</p>';
 if(!p.choiceErrors?.length)return '';
 return `<div><p role="status" data-app-i18n="pipelineCreate.partialChoices">部分员工或技能暂时无法载入。</p>${RunTeamsLoadFailure.button(retryOptions)}
  <div class="help">${p.choiceErrors.map(e=>`<p>${esc(e.employee)}：${esc(e.error)}</p>`).join('')}</div></div>`;
}
const stagePresets=[['pool','待定','pipelineBoard.stagePending'],['done','完成','pipelineEditor.stateDone'],['dropped','放弃','pipelineBoard.stageAbandoned']];
const stageTrigger=()=>document.querySelector('.source-pipeline-add-stage');
const stageCopy=(key,fallback)=>RunTeamsLocale.t(key,{},fallback);
function dismissMenuOnPageScroll(menu,close){
 // Menu lists and their submenus scroll independently of the page.
 const scroll=event=>{
  if(menu.contains(event.target)||menu._nestedTarget?.(event.target))return;
  cleanup();
  close();
 };
 const observer=new MutationObserver(()=>{if(!menu.isConnected)cleanup();});
 function cleanup(){
  cancelAnimationFrame(frame);
  window.removeEventListener('scroll',scroll,true);
  observer.disconnect();
 }
 // Let any scrolling that revealed the trigger finish before listening.
 const frame=requestAnimationFrame(()=>{
  if(menu.isConnected)window.addEventListener('scroll',scroll,{capture:true,passive:true});
 });
 observer.observe(menu.parentNode,{childList:true});
}
function stageConnections(pipeline){
 const {positions,edges}=pipeline,names=new Map([...positions,...(pipeline.states||[])].map(node=>[node.key,node.name]));
 const labels={
  completed:['pipelineEditor.routeAfterCompletion','完成后'],approved:['pipelineEditor.routeApproved','通过'],rejected:['pipelineEditor.routeRejected','退回'],
  failed:['pipelineEditor.routeFailed','失败'],blocked:['pipelineEditor.routeBlocked','阻塞'],exception:['pipelineEditor.routeException','异常'],
  needs_human:['pipelineEditor.routeNeedsHuman','需要人工'],always:['pipelineEditor.routeAlways','兜底'],
 };
 const caption=when=>Object.hasOwn(labels,when)?stageCopy(...labels[when]):when.replace(/^outcome:/,'');
 names.set(WAIT_FOR_INPUT,stageCopy('pipelineEditor.waitHere','留在当前岗位，待人工处理'));
 if(pipeline.routing_policy===STATUS_FIRST_ROUTING)names.set(COMPLETE_HERE,stageCopy('pipelineEditor.completeHere','留在当前岗位并完成'));
 const existing=edges.map((edge,index)=>({index,from:edge.from,when:edge.when||'completed',to:edge.to}));
 const free=positions.flatMap(position=>{
  const when=position.kind==='approval'?'approved':'completed';
  return existing.some(edge=>edge.from===position.key&&edge.when===when)?[]:[{from:position.key,when}];
 });
 return [...existing.filter(edge=>edge.to!==WAIT_FOR_INPUT),...free].map(edge=>({...edge,label:[names.get(edge.from),caption(edge.when),edge.to&&names.get(edge.to)].filter(Boolean).join(' → ')}));
}
function connectStage(pipeline,key,kind,connection){
 if(connection.index===undefined){
  pipeline.edges.push({from:connection.from,to:key,when:connection.when});
  return;
 }
 const edge=pipeline.edges[connection.index];
 const next={from:key,to:edge.to,when:kind==='approval'?'approved':'completed'};
 edge.to=key;
 pipeline.edges.push(next);
}
async function addStageMenu(trigger){
 const s=current();
 if(!owned(s)||!s?.data||s.error||s.view==='conversation'||s.data.ui.mode!=='creator')return;
 const existing=document.getElementById('sourcePipelineAddStage');
 if(existing){existing.querySelector('[data-stage-close]').click();return;}
 const p=state(s);
 if(p.draft||p.pending||p.saving||p.commitRefresh)return settings();
 closeTransientMenus();
 let nodes=false,ready=false,failed=false,observer,anchor=trigger,connections=[],routing=null;
 let scrollList;
 function updateListFade(){
  if(!scrollList)return;
  const {scrollTop,scrollHeight,clientHeight}=scrollList;
  scrollList.toggleAttribute('data-fade-top',scrollTop>1);
  scrollList.toggleAttribute('data-fade-bottom',scrollHeight-clientHeight-scrollTop>1);
 }
 const listResize=new ResizeObserver(updateListFade);
 const positionAnchor={
  getBoundingClientRect:()=>anchor.getBoundingClientRect(),
  contains:target=>anchor.contains(target),
 };
 const {menu,close}=openNestedMenu(trigger,[],{id:'sourcePipelineAddStage',placement:'below-start',positionAnchor,onClose:()=>{
  observer.disconnect();listResize.disconnect();
  anchor.classList.remove('menu-trigger-active');
  anchor.setAttribute('aria-haspopup','dialog');
  anchor.setAttribute('aria-expanded','false');
  if(document.activeElement===document.body)anchor.focus({preventScroll:true});
 }});
 dismissMenuOnPageScroll(menu,close);
 const updateAnchor=()=>{
  const button=stageTrigger();
  if(!owned(s)||!button||s.view==='conversation'||s.error||s.data.ui.mode!=='creator'){close();return;}
  anchor=button;
  anchor.setAttribute('aria-haspopup','dialog');
  anchor.setAttribute('aria-expanded','true');
 };
 trigger.setAttribute('aria-haspopup','dialog');
 menu.className='draft-column-popover source-pipeline-add-picker opening';
 menu.setAttribute('role','dialog');
 menu.setAttribute('aria-label',stageCopy('pipelineBoard.addStage','添加环节'));
 menu.addEventListener('scroll',event=>{if(event.target===scrollList)updateListFade();},{capture:true,passive:true});
 observer=new MutationObserver(updateAnchor);
 observer.observe(document.getElementById('rgBody'),{childList:true,subtree:true});
 const active=()=>menu.isConnected&&owned(s)&&!s.error&&s.data.ui.mode==='creator'&&s.view!=='conversation';
 const title='<header><b data-app-i18n="pipelineBoard.addStage">添加环节</b><button type="button" data-stage-close aria-label="关闭弹窗" data-app-i18n-aria-label="employeeSettings.closeDialog">'+ICON('x')+'</button></header>';
 const createButton=(type,attrs='')=>`<button class="draft-picker-create-worker" type="${type}" ${attrs}>${ICON('plus')}<span data-app-i18n="pipelineBoard.stageCreate">创建</span></button>`;
 const marker=added=>added?'<em data-app-i18n="pipelineBoard.stageAdded">已添加</em>':ICON('chev');
 const empty='<div class="draft-picker-empty" data-stage-no-results hidden data-app-i18n="pipelineBoard.noStageMatches">没有匹配的员工</div>';
 function rolesMarkup(){
  const loading=!ready||p.choicesLoading;
  const directory=RunTeamsEmployeeDirectory,choices=Array.isArray(p.choices)?p.choices:[],asset=p.data?.asset;
  const records=new Map();
  for(const entry of directory.current()){
   for(const ref of directory.references(entry))records.set(directory.referenceKey(ref),entry.record);
  }
  const members=new Map((asset?.employees||[]).map(member=>[member.ref,member]));
  const rows=loading||p.choicesFailed?'':choices.map((choice,index)=>{
   const record=records.get(directory.referenceKey(choice.reference));
   const added=asset.pipeline.positions.some(position=>position.skill_key===choice.skill_key&&matches(members.get(position.employee_ref),choice,s.reference));
   const filter=[choice.employee_name,choice.skill_name,choice.project_name].join(' ').toLocaleLowerCase();
   return `<button class="draft-picker-row${added?' added':''}" type="button" data-stage-choice="${index}" data-stage-filter="${esc(filter)}">${workerAvatarMarkup(record)}<span class="draft-picker-copy"><b>${esc(choice.employee_name)}</b><small>${esc(choice.skill_name)}</small></span>${marker(added)}</button>`;
  }).join('');
  const list=loading?RunTeamsSkeletons.region('pipeline-stage-employees',3,'pipelineEditor.choicesLoading'):rows+empty+employeeChoicesStatus(p);
  return `<div class="draft-picker-search-row"><label class="draft-picker-search rt-search-field rt-search-field--compact">${ICON('search')}<input type="search" data-stage-search ${loading?'disabled':''} placeholder="搜索员工" aria-label="搜索员工" autocomplete="off" data-app-i18n-placeholder="pipelineBoard.searchStages" data-app-i18n-aria-label="pipelineBoard.searchStages"></label>${createButton('button','data-stage-create-employee')}</div><div class="draft-picker-list">${list}</div>`;
 }
 function nodesMarkup(){
  const existing=new Set((p.data.asset.pipeline.states||[]).map(state=>state.kind));
  const rows=stagePresets.map(([kind,label,key])=>{
   const added=existing.has(kind);
   return `<button class="draft-picker-row state-row k-${kind}${added?' added':''}" type="button" data-stage-kind="${kind}"><i class="draft-state-dot"></i><span class="draft-picker-copy"><b data-app-i18n="${key}">${label}</b></span>${marker(added)}</button>`;
  }).join('');
  return `<form class="draft-picker-search-row"><label class="draft-picker-search rt-search-field rt-search-field--compact">${ICON('search')}<input type="search" name="stageName" required maxlength="160" aria-label="自定义状态名称" data-app-i18n-aria-label="pipelineBoard.customStage" placeholder="自定义状态名称" data-app-i18n-placeholder="pipelineBoard.customStage" autocomplete="off"></label>${createButton('submit')}</form><div class="draft-picker-list state-list"><button class="draft-picker-row state-row approval-row" type="button" data-stage-kind="approval"><i class="draft-state-dot approval"></i><span class="draft-picker-copy"><b data-app-i18n="pipelineBoard.stageApproval">人工审批</b></span>${ICON('chev')}</button>${rows}</div>`;
 }
 function paint(){
  if(!active())return;
  const tabs=`<div class="draft-picker-tabs" role="tablist" aria-label="环节类型" data-app-i18n-aria-label="pipelineBoard.stageTypes"><button type="button" role="tab" data-stage-tab="roles" aria-selected="${!nodes}" class="${nodes?'':'on'}" data-app-i18n="pipelineEditor.roles">岗位</button><button type="button" role="tab" data-stage-tab="nodes" aria-selected="${nodes}" class="${nodes?'on':''}" data-app-i18n="pipelineBoard.stageNodes">流程节点</button></div>`;
  let content;
  if(routing){
   content=`<form class="source-pipeline-stage-route"><label><span data-app-i18n="pipelineBoard.stageConnection">接入流转</span><select class="inp" required data-stage-connection>${options([['','选择接入位置','pipelineBoard.chooseStageConnection'],...connections.map((edge,index)=>[String(index),edge.label])],'')}</select></label><div class="source-pipeline-stage-route-actions"><button class="btn sm" type="button" data-stage-back data-app-i18n="shell.settingsBack">返回</button><button class="btn pri sm" type="submit" data-app-i18n="pipelineBoard.add">添加</button></div></form>`;
  }else if(!ready&&failed){
   content='<p role="alert" data-app-i18n="pipelineBoard.readFailed">无法读取智能体团队。</p><button class="btn sm" type="button" data-stage-retry data-app-i18n="employeeHistory.retry">重试</button>';
  }else content=nodes?(ready?nodesMarkup():RunTeamsSkeletons.region('history',3,'pipelineBoard.loading')):rolesMarkup();
  menu.innerHTML=title+(routing?'':tabs)+`<div class="draft-picker-panel">${content}</div>`;
  const retry=menu.querySelector('[data-read-retry]');
  if(retry)retry.onclick=readChoices;
  RunTeamsLocale.apply(menu);
  listResize.disconnect();
  scrollList=menu.querySelector('.draft-picker-list');
  if(scrollList){listResize.observe(scrollList);updateListFade();}
 }
 async function load(){
  failed=false;paint();
  await loadSettingsData(s);
  if(!active())return;
  if(p.draft||p.pending||p.saving||p.commitRefresh){close();return settings();}
  if(p.error||!p.data){failed=true;paint();return;}
  connections=stageConnections(p.data.asset.pipeline);
  ready=true;
  await readChoices();
 }
 async function readChoices(){
  if(p.choicesLoading)return;
  const reading=readEmployeeChoices();
  paint();await reading;if(!routing)paint();
  if(!nodes&&document.activeElement===document.body)menu.querySelector('[data-stage-search], [data-stage-tab="roles"]')?.focus({preventScroll:true});
 }
 function chooseStage(kind,options={}){
  if(!active()||!ready)return;
  if(connections.length===1)return commit(kind,options,connections[0]);
  routing={kind,options};paint();menu.querySelector('[data-stage-connection]')?.focus({preventScroll:true});
 }
 async function commit(kind,options,route=null){
  if(!active()||!ready||p.draft||p.pending||p.saving||p.commitRefresh||kind!=='states'&&!route)return;
  const selection=S.sel,sequence=_detailOpenSequence;
  const key=add(kind,{...options,immediate:true});
  if(key&&route)connectStage(p.draft.pipeline,key,kind,route);
  if(!key)return;
  close();
  await save(false,s);
  if(!owned(s)||s.view==='conversation'||S.sel!==selection||_detailOpenSequence!==sequence)return;
  if(p.draft||p.pending||p.commitRefresh)select('settings');
  else if(document.activeElement===document.body||document.activeElement===anchor){
   (document.querySelector(`.column-worker-title[data-position="${CSS.escape(key)}"]`)||stageTrigger())?.focus();
  }
 }
 menu.onclick=event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.matches('[data-stage-close]')){anchor.focus({preventScroll:true});close();return;}
  if(button.matches('[data-stage-retry]'))return load();
  if(button.matches('[data-stage-create-employee]')){close();return newEmployeeConversation();}
  if(button.matches('[data-stage-back]')){routing=null;paint();menu.querySelector(nodes?'[name="stageName"]':'[data-stage-search]')?.focus({preventScroll:true});return;}
  if(button.dataset.stageTab){
   nodes=button.dataset.stageTab==='nodes';paint();
   (menu.querySelector(nodes?'[name="stageName"]':'[data-stage-search]')||menu.querySelector(`[data-stage-tab="${button.dataset.stageTab}"]`))?.focus({preventScroll:true});return;
  }
  if(button.dataset.stageChoice!==undefined)return chooseStage('positions',{choiceIndex:Number(button.dataset.stageChoice)});
  const kind=button.dataset.stageKind,preset=stagePresets.find(([value])=>value===kind);
  if(kind==='approval')return chooseStage('approval',{name:stageCopy('pipelineBoard.stageApproval','人工审批')});
  if(preset){
   const existing=p.data.asset.pipeline.states?.find(state=>state.kind===kind);
   if(!existing)return commit('states',{stateKind:kind,name:stageCopy(preset[2],preset[1])});
   close();document.querySelector(`.column-worker-title[data-position="${CSS.escape(existing.key)}"]`)?.focus();
  }
 };
 menu.oninput=event=>{
  if(!event.target.matches('[data-stage-search]'))return;
  const term=event.target.value.trim().toLocaleLowerCase();
  const rows=[...menu.querySelectorAll('[data-stage-filter]')];
  for(const row of rows)row.hidden=!row.dataset.stageFilter.includes(term);
  menu.querySelector('[data-stage-no-results]').hidden=rows.some(row=>!row.hidden);
  updateListFade();
 };
 menu.onsubmit=event=>{
  event.preventDefault();
  if(routing){const route=connections[event.target.querySelector('[data-stage-connection]').value];if(route)void commit(routing.kind,routing.options,route);return;}
  const input=event.target.elements.stageName,name=input.value.trim();
  if(name)void commit('states',{stateKind:'pool',name});
 };
 menu.onkeydown=event=>{if(event.key!=='Escape')event.stopPropagation();};
 paint();menu.querySelector('[data-stage-tab="roles"]')?.focus({preventScroll:true});
 await load();
}
const defaultTone=kind=>({done:'green',dropped:'red',pool:'gray'})[kind]||'default';
// Record-only completion remains available through the original records view.
// Never hide an unfinished or failed run even if its cursor is on that state.
const boardColumns=s=>[...s.data.pipeline.positions,...(s.data.pipeline.states||[])].filter(column=>
 column.kind!=='done'||column.records_only!==true||s.data.workflows.some(row=>row.cursor_key===column.key&&row.state!=='completed'));
const boardKey=s=>'runteams.pipeline-board:'+s.storageScope+':'+JSON.stringify(s.reference);
function boardPreferences(s){
 if(!s.boardPreferences){
  try{s.boardPreferences=JSON.parse(workspaceBusinessStorage.getItem(boardKey(s))||'{}')||{};}
  catch(error){s.boardPreferences={};}
 }
 return s.boardPreferences;
}
function saveBoard(s,patch){
 if(!owned(s))return;
 const next={...boardPreferences(s),...patch};
 try{
  const key=boardKey(s),value=JSON.stringify(next);
  workspaceBusinessStorage.setItem(key,value);
  if(workspaceBusinessStorage.getItem(key)!==value)throw Error('显示设置写入未确认');
  s.boardPreferences=next;
 }
 catch(error){toast('无法保存看板显示设置。请重试。','err','pipelineBoard.displaySaveFailed');}
 render();
}
function columns(s,includeHidden=false){
 const prefs=boardPreferences(s),order=prefs.order||[],hidden=prefs.hidden||[];
 const rows=boardColumns(s).map(row=>{const color=prefs.colors?.[row.key]||'';return {...row,color,tone:color||defaultTone(row.kind)};});
 if(prefs.sort==='name'||prefs.sort==='name-desc')rows.sort((a,b)=>a.name.localeCompare(b.name,'zh')*(prefs.sort==='name-desc'?-1:1));
 else if(prefs.sort==='manual')rows.sort((a,b)=>(order.indexOf(a.key)+1||Infinity)-(order.indexOf(b.key)+1||Infinity));
 return includeHidden?rows:rows.filter(row=>!hidden.includes(row.key)&&(!prefs.hideEmpty||s.data.workflows.some(work=>work.cursor_key===row.key)));
}
function groupMenu(s,anchor,{focus=false}={}){
 const parent=anchor.closest('#popmenu');
 if(!parent||!owned(s))return;
 const existing=document.getElementById('sourcePipelineGroups');
 if(existing){if(focus)existing.querySelector('[data-sort]')?.focus({preventScroll:true});return;}
 let sortMenu=null;
 const {menu,close}=openNestedMenu(anchor,[],{id:'sourcePipelineGroups',variant:'columnAction',placement:'right',edgeAnchor:parent,dismissOutside:false,onClose:()=>{owner.disconnect();sortMenu?.close();delete parent._nestedTarget;parent.removeEventListener('pointerover',sibling);}});
 menu.classList.add('column-group-editor');
 parent._nestedTarget=target=>menu.contains(target)||!!sortMenu?.menu.contains(target);
 const owner=new MutationObserver(()=>{if(!parent.isConnected){owner.disconnect();close();}});
 owner.observe(parent.parentNode,{childList:true});
 const sibling=event=>{const item=event.target.closest('a[data-i]');if(item&&item!==anchor)close();};
 parent.addEventListener('pointerover',sibling);
 menu.dataset.appI18nAriaLabel='pipelineEditor.editGroup';
 menu.setAttribute('aria-label','编辑分组');
 const sortOptions=[['manual','手动'],['name','按名称升序'],['name-desc','按名称降序']];
 let rows=[],hidden=[];
 function paint(){
  const prefs=boardPreferences(s);rows=columns(s,true);hidden=prefs.hidden||[];
  menu.innerHTML=`<header><b data-app-i18n="pipelineGroup.groups">分组</b><button type="button" data-close data-app-i18n-aria-label="employeeSettings.closeDialog" aria-label="关闭弹窗">${ICON('x')}</button></header><section class="column-group-controls"><button type="button" class="column-group-sort" data-sort aria-haspopup="menu" aria-expanded="false"><span data-app-i18n="pipelineGroup.sort">排序方式</span><b data-app-i18n="pipelineGroup.${prefs.sort==='default'?'manual':prefs.sort||'manual'}">${sortOptions.find(([key])=>key===(prefs.sort==='default'?'manual':prefs.sort||'manual'))?.[1]||'手动'}</b>${ICON('chev')}</button><label class="column-group-switch"><span data-app-i18n="pipelineGroup.hideEmpty">隐藏空分组</span><input type="checkbox" data-empty ${prefs.hideEmpty?'checked':''}><i><em></em></i></label></section><div class="column-group-list-head"><b data-app-i18n="pipelineGroup.visibility">显示</b><button type="button" data-all ${rows.length?'':'disabled'} data-app-i18n="pipelineGroup.${rows.every(row=>hidden.includes(row.key))?'showAll':'hideAll'}">${rows.every(row=>hidden.includes(row.key))?'全部显示':'全部隐藏'}</button></div><div class="column-group-list">${rows.map((row,i)=>`<div class="column-group-row${hidden.includes(row.key)?' is-hidden':''}" draggable="true" data-row="${i}"><span class="column-group-grip" aria-hidden="true">${ICON('grip')}</span><b class="column-group-name column-swatch-${esc(row.tone)}" title="${esc(row.name)}">${esc(row.name)}</b><button type="button" class="column-group-visibility" data-visible="${i}" data-group-key="${esc(row.key)}" data-app-i18n-aria-label="pipelineGroup.${hidden.includes(row.key)?'show':'hide'}" data-app-i18n-vars="${esc(JSON.stringify({name:row.name}))}" aria-label="${hidden.includes(row.key)?'显示':'隐藏'}${esc(row.name)}">${ICON(hidden.includes(row.key)?'eye-off':'eye')}</button></div>`).join('')}</div>`;
 }
 paint();
 function focusControl(selector){menu.querySelector(selector)?.focus({preventScroll:true});}
 if(focus)focusControl('[data-sort]');
 function dismiss(){close();if(anchor.isConnected)anchor.focus({preventScroll:true});}
 function apply(patch,selector){
  saveBoard(s,patch);
  if(menu.isConnected){paint();if(selector)focusControl(selector);}
 }
 function reorder(from,to,selector){if(from===to||!rows[from]||!rows[to])return;const order=rows.map(row=>row.key);order.splice(to,0,order.splice(from,1)[0]);apply({sort:'manual',order},selector);}
 menu.onchange=event=>{if(event.target.matches('[data-empty]'))apply({hideEmpty:event.target.checked},'[data-empty]');};
 menu.onclick=event=>{event.stopPropagation();const button=event.target.closest('button');if(!button)return;
  if(button.hasAttribute('data-close'))return dismiss();
  if(button.hasAttribute('data-sort')){
   if(document.getElementById('sourcePipelineGroupSort'))return;
   const sort=boardPreferences(s).sort;
   const active=sort==='default'?'manual':sort||'manual';
   sortMenu=openNestedMenu(button,sortOptions.map(([sort,label])=>({label,labelKey:"pipelineGroup."+sort,selected:sort===active,fn:()=>apply({sort},'[data-sort]')})),{
    id:'sourcePipelineGroupSort',variant:'columnGroupSort',placement:'below-start',
    onClose:()=>{if(sortMenu?.menu.contains(document.activeElement)||document.activeElement===document.body)focusControl('[data-sort]');}
   });
   const options=[...sortMenu.menu.querySelectorAll('a[data-i]')];
   sortMenu.menu.dataset.appI18nAriaLabel='pipelineGroup.sort';
   sortMenu.menu.setAttribute('aria-label','排序方式');
   for(const option of options){
    option.tabIndex=-1;
    option.setAttribute('role','menuitemradio');
    option.setAttribute('aria-checked',String(option.classList.contains('selected')));
   }
   sortMenu.menu.onkeydown=event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();sortMenu.close();return;}
    if(!['ArrowDown','ArrowUp'].includes(event.key))return;
    const index=options.indexOf(event.target);
    if(index<0)return;
    event.preventDefault();event.stopPropagation();
    options[(index+(event.key==='ArrowDown'?1:-1)+options.length)%options.length].focus({preventScroll:true});
   };
   (options.find(option=>option.classList.contains('selected'))||options[0])?.focus({preventScroll:true});
   return;
  }
  if(button.hasAttribute('data-all'))return apply({hidden:rows.every(row=>hidden.includes(row.key))?[]:rows.map(row=>row.key)},'[data-all]');
  const row=rows[button.dataset.visible];if(row)apply({hidden:hidden.includes(row.key)?hidden.filter(key=>key!==row.key):[...hidden,row.key]},`[data-group-key="${CSS.escape(row.key)}"]`);
 };
 menu.onkeydown=event=>{
  event.stopPropagation();
  if(event.key==='Escape'){event.preventDefault();dismiss();return;}
  if(!event.altKey||!['ArrowUp','ArrowDown'].includes(event.key))return;
  const row=event.target.closest('[data-row]');if(!row)return;
  event.preventDefault();
  const index=Number(row.dataset.row),next=index+(event.key==='ArrowUp'?-1:1);
  reorder(index,next,`[data-group-key="${CSS.escape(rows[index].key)}"]`);
 };
 let moving=null;
 menu.ondragstart=event=>{moving=event.target.closest('[data-row]')?.dataset.row??null;if(moving!==null)event.dataTransfer.setData('text/plain',moving);};
 menu.ondragover=event=>{if(moving!==null&&event.target.closest('[data-row]'))event.preventDefault();};
 menu.ondrop=event=>{event.preventDefault();const target=event.target.closest('[data-row]');if(moving!==null&&target)reorder(Number(moving),Number(target.dataset.row));moving=null;};
}
function memberFor(p,position){return p.data?.employees.find(row=>row.member_ref===position.employee_ref);}
function skillFor(p,position,asset){
 const member=asset.employees.find(row=>row.ref===position.employee_ref);
 const choice=(p.choices||[]).find(row=>member&&matches(member,row,p.data.reference)&&row.skill_key===position.skill_key);
 const saved=memberFor(p,position);
 const original=p.data.asset.employees.find(row=>row.ref===position.employee_ref);
 return choice?.skill||(JSON.stringify(member)===JSON.stringify(original)?saved?.skills?.find(skill=>skill.key===position.skill_key):null);
}
async function position(key){
 const s=current();if(!s||!boardColumns(s).some(row=>row.key===key))return;
 if(S.sel?.positionKey!==key)state(s).expandedRoutePosition=null;
 host().select('position',{positionKey:key});
 openPositionConfiguration(s);
 await loadSettingsData(s);
}
function positionEmployeeEntry(s,key){
 const p=state(s),position=p.data?.asset.pipeline.positions.find(row=>row.key===key);
 const reference=position&&memberFor(p,position)?.reference;
 return reference?RunTeamsEmployeeDirectory.entryFor(reference):null;
}
async function openEmployee(s,key){
 const selection=S.sel;
 if(!state(s).data)await loadSettingsData(s);
 if(!owned(s)||S.sel!==selection)return;
 const entry=positionEmployeeEntry(s,key);
 if(!entry)return toast('员工暂不可用。请查看员工目录。','info','pipelineSettings.employeeMissing');
 try{await RunTeamsEmployeeDirectory.open(entry.key);}
 catch(error){if(owned(s)&&S.sel===selection)toast(error.message,'err');}
}
function columnClick(event,key){
 if(!event.target.closest('.card,button,a,input,textarea,select'))void position(key);
}
function columnAvatar(column){
 if(column.kind!=='employee')return '';
 const s=current(),member=s&&memberFor(state(s),column),directory=window.RunTeamsEmployeeDirectory;
 const ref=member?.reference&&directory?.referenceKey(member.reference);
 const entry=ref&&directory.current().find(item=>directory.references(item).some(value=>directory.referenceKey(value)===ref));
 return `<span class="column-worker-avatar">${typeof workerAvatarMarkup==='function'?workerAvatarMarkup(entry?.record):ICON('user')}</span>`;
}
async function columnMenu(event,key){
 event.preventDefault();event.stopPropagation();
 const s=current(),column=s&&columns(s,true).find(row=>row.key===key);
 if(!s||key&&!column)return;
 let anchor=event.currentTarget;
 const detail=!!anchor.closest('.node-detail-drawer');
 const options={variant:'columnAction',...(event.type==='contextmenu'?{at:{x:event.clientX,y:event.clientY},align:'left'}:{})};
 const creator=s.data.ui.mode==='creator',selection=S.sel;
 if(creator&&column?.kind==='employee'&&!state(s).data){
  await loadSettingsData(s);
  if(!owned(s)||S.sel!==selection||s.data.ui.mode!=='creator')return;
  if(!anchor.isConnected)anchor=document.querySelector(`#rgMid ${options.at?'.chd':'.column-more'}[data-position="${CSS.escape(key)}"]`);
  if(!anchor)return;
 }
 const items=[{label:'编辑分组',labelKey:'pipelineEditor.editGroup',icon:'board',submenu:true,keepOpen:true,hoverFn:anchor=>groupMenu(s,anchor),fn:anchor=>groupMenu(s,anchor,{focus:true})}];
 const showMenu=options=>{
  openMenu(anchor,items,options);
  const menu=document.getElementById('popmenu');
  if(menu)dismissMenuOnPageScroll(menu,closePop);
 };
 if(!column)return showMenu({variant:'columnAction'});
 if(column.kind==='employee'){
  items.push({label:'打开员工',labelKey:'pipelineEditor.openEmployee',icon:'users',fn:()=>openEmployee(s,key)});
 }
 if(!creator&&!detail)items.push({label:['employee','approval'].includes(column.kind)?'查看岗位详情':'查看环节详情',labelKey:['employee','approval'].includes(column.kind)?'pipelineEditor.viewRole':'pipelineEditor.viewStep',icon:'board',fn:()=>position(key)});
 if(creator)items.push({label:'移除环节',labelKey:'pipelineEditor.removeStep',icon:'trash',danger:true,fn:()=>removePosition(s,key)});
 if(!detail)items.push({divider:true},{head:true,label:'颜色',labelKey:'pipelineGroup.color'},...COLUMN_COLOR_OPTIONS.map(({value,label})=>({label,labelKey:'pipelineGroup.color.'+(value||'default'),swatch:value||'default',selected:value===column.color,fn:()=>saveBoard(s,{colors:{...boardPreferences(s).colors,[key]:value}})})));
 showMenu(options);
}
async function removePosition(s,key){
 await position(key);
 if(!owned(s)||S.sel?.positionKey!==key)return;
 const p=state(s),pipeline=(p.draft||p.data?.asset)?.pipeline;
 if(!pipeline||p.pending||p.saving||p.conflict)return;
 const kind=pipeline.positions.some(row=>row.key===key)?'positions':'states',index=pipeline[kind].findIndex(row=>row.key===key);
 if(index<0)return;
 const blocked=removalBlock(pipeline,kind,index);
 if(blocked)return toast(RunTeamsLocale.t(blocked.key,blocked.vars),'info',blocked.key,blocked.vars);
 confirmModal('从智能体团队移除环节？','相关流转规则也会移除，已有工作记录会保留。',()=>{
  if(owned(s)&&S.sel?.positionKey===key&&(state(s).draft||state(s).data?.asset)?.pipeline[kind][index]?.key===key)remove(kind,index);
 },true,{titleKey:"pipelineEditor.removeStepTitle",messageKey:"pipelineEditor.removeStepMessage",action:"移除环节",actionKey:"pipelineEditor.removeStep",cancelKey:"employeeSettings.cancel",closeKey:"employeeSettings.closeDialog"});
}
function routeRows(asset,position,locked,{flat=false}={}){
 const p=state(current()),pipeline=asset.pipeline,skill=skillFor(p,position,asset),key=position.key;
 const statusFirst=pipeline.routing_policy===STATUS_FIRST_ROUTING;
 const completion=['completed','完成后','pipelineEditor.routeAfterCompletion'];
 const decisions=[['approved','通过','pipelineEditor.routeApproved'],['rejected','退回','pipelineEditor.routeRejected']];
 const exceptions=[['failed','失败','pipelineEditor.routeFailed'],['blocked','阻塞','pipelineEditor.routeBlocked'],['exception','异常','pipelineEditor.routeException'],['needs_human','需要人工','pipelineEditor.routeNeedsHuman']];
 const fallback=statusFirst?['always','未匹配时','pipelineEditor.completionFallbackWhen']:['always','兜底','pipelineEditor.routeAlways'];
 if(!statusFirst)exceptions.push(fallback);
 const declared=[...new Set(skill?.routes||[])];
 const existing=pipeline.edges.filter(edge=>edge.from===key);
 const configured=value=>existing.some(edge=>(edge.when||'completed')===value);
 const approval=position.kind==='approval';
 const builtInKeys=new Set([completion,...decisions,...exceptions].map(([value])=>value));
 const declaredOutcomes=declared.map(value=>value.trim()).filter(value=>value&&[...value].length<=120);
 const outcomes=statusFirst&&!approval?[...new Set([
  ...declaredOutcomes,
  ...existing.map(edge=>edge.when||'').filter(value=>value.startsWith(OUTCOME_PREFIX)).map(value=>value.slice(OUTCOME_PREFIX.length)),
 ])]:[];
 const named=statusFirst?outcomes.map(value=>[OUTCOME_PREFIX+value,value]):declared.filter(value=>!builtInKeys.has(value)).map(value=>[value,value]);
 const results=approval?[...decisions,...named]:[...named,completion];
 const availableExceptions=statusFirst?(approval?[]:exceptions):exceptions.filter(([value])=>approval
  ?configured(value)||declared.includes(value)
  :flat||value!=='needs_human'||configured(value)||declared.includes(value));
 const known=new Set([...results,...availableExceptions,...(statusFirst&&!approval?[fallback]:[])].map(([value])=>value));
 const legacy=[...new Set(existing.map(edge=>edge.when||'completed'))].filter(value=>!known.has(value)).map(value=>[value,value]);
 const targets=[...pipeline.positions,...(pipeline.states||[])];
 const rows=entries=>entries.map(([value,label,labelKey])=>{
  const target=existing.find(edge=>(edge.when||'completed')===value)?.to||'';
  const selected=targets.find(row=>row.key===target);
  const tone=boardPreferences(current()).colors?.[target]||defaultTone(selected?.kind);
  const [captionKey,defaultCaption]=target===WAIT_FOR_INPUT?['waitHere','留在当前岗位，待人工处理']:
   statusFirst&&target===COMPLETE_HERE?['completeHere','留在当前岗位并完成']:
   target?['routeMissing','原目标（请核对）']:['routeUnset','未指定'];
  const caption=selected?.name||defaultCaption;
  return `<div class="bout node-route-row"><span class="bo-label" title="${esc(label)}"${labelKey?` data-app-i18n="${labelKey}" data-app-i18n-title="${labelKey}"`:''}>${esc(label)}</span><button type="button" data-menu-trigger="field" class="csel" aria-haspopup="menu" aria-expanded="false" data-app-i18n-aria-label="${labelKey?labelKey+'For':'pipelineEditor.routeFor'}" data-app-i18n-vars="${esc(JSON.stringify({name:position.name,route:label}))}" aria-label="${esc(position.name+' '+label+'的下游')}" data-position="${esc(key)}" data-route="${esc(value)}" data-value="${esc(target)}" onclick="RunTeamsSourcePipelinePanels.routeMenu(event)" ${locked?'disabled':''}><span class="cv"><span class="${selected?`column-group-name column-swatch-${esc(tone)}`:'node-route-empty'}"${selected?'':` data-app-i18n="pipelineEditor.${captionKey}"`}>${esc(caption)}</span></span>${ICON('chev')}</button></div>`;
 }).join('');
 const configuredExceptions=availableExceptions.filter(([value])=>configured(value));
 const optionalExceptions=availableExceptions.filter(([value])=>!configured(value));
 const grouped=entries=>`<div class="node-route-list">${rows(entries)}</div>`;
 const fallbackHint=availableExceptions.some(([value])=>value==='always')
  ?'<p class="help" data-app-i18n="pipelineEditor.legacyFallbackHint">兜底也适用于其他条件都未匹配的完成结果。</p>':'';
 const exceptionMarkup=availableExceptions.length?`<section class="node-route-list">
  <div class="node-section-head"><b data-app-i18n="pipelineEditor.exceptionHandling">异常处理</b></div>
  ${grouped([...configuredExceptions,...optionalExceptions])}${fallbackHint}
 </section>`:'';
 const completionFallback=statusFirst&&!approval?`<section class="node-route-list">
  <div class="node-section-head"><b data-app-i18n="pipelineEditor.completionFallback">完成兜底</b></div>
  ${grouped([fallback])}
 </section>`:'';
 const legacyMarkup=legacy.length?`<section class="node-route-list"><div class="node-section-head"><b data-app-i18n="pipelineEditor.existingConditions">已有条件（请核对）</b></div>${grouped(legacy)}</section>`:'';
 const skillHint=position.kind==='employee'&&!skill?'<p class="help" data-app-i18n="pipelineEditor.skillRoutesUnavailable">技能出口暂不可读取。</p>':'';
 if(flat){
  const hasDeclaredResults=statusFirst?declaredOutcomes.length>0:named.length>0;
  const manual=[...results.filter(([value])=>value!=='completed'||!hasDeclaredResults),
   ...availableExceptions.filter(([value])=>value!=='always'&&configured(value))];
  const manualKeys=new Set(manual.map(([value])=>value));
  const optional=[...results,...(statusFirst&&!approval?[fallback]:[]),...availableExceptions,...legacy]
   .filter(([value])=>!manualKeys.has(value));
  const expanded=p.expandedRoutePosition===key;
  const sectionId='position_route_conditions_'+key;
  const label=expanded?'pipelineEditor.hideRouteConditions':'pipelineEditor.moreRouteConditions';
  const more=optional.length?`<button type="button" class="settings-section-action settings-section-footer-action" aria-expanded="${expanded}" aria-controls="${esc(sectionId)}" data-position="${esc(key)}" data-app-i18n="${label}" onclick="RunTeamsSourcePipelinePanels.toggleRouteConditions(event)">${expanded?'收起额外条件':'更多流转条件'}</button>`:'';
  const body=`<div class="node-route-list">
   ${grouped(manual)}${skillHint}
   ${optional.length?`<div id="${esc(sectionId)}"${expanded?'':' hidden'}>${grouped(optional)}${fallbackHint}</div>`:''}
   </div>`;
  return positionSection(key,'routes','<span data-app-i18n="pipelineEditor.routeHeading">工作下游</span>',body,'node-route-section',more);
 }
 const body=`<div class="node-route-list">
  <div class="node-section-head"><b data-app-i18n="pipelineEditor.workResults">工作结果</b></div>
  ${grouped(results)}${skillHint}${completionFallback}${exceptionMarkup}${legacyMarkup}
 </div>`;
 return `<section class="node-route-section">${body}</section>`;
}
function toggleRouteConditions(event){
 const s=current(),button=event.currentTarget;
 const list=document.getElementById(button.getAttribute('aria-controls'));
 if(!s||!list)return;
 const expanded=list.hidden;
 state(s).expandedRoutePosition=expanded?button.dataset.position:null;
 list.hidden=!expanded;
 button.setAttribute('aria-expanded',String(expanded));
 button.dataset.appI18n=expanded?'pipelineEditor.hideRouteConditions':'pipelineEditor.moreRouteConditions';
 button.textContent=RunTeamsLocale.t(button.dataset.appI18n,{},expanded?'收起额外条件':'更多流转条件');
}
function canCompleteHere(graph,position,when){
 if(graph.routing_policy!==STATUS_FIRST_ROUTING||!position)return false;
 return position.kind==='approval'?when==='approved':
  ['completed','always'].includes(when)||when.startsWith(OUTCOME_PREFIX);
}
function routeMenu(event){
 const anchor=event.currentTarget,{position,route,value}=anchor.dataset,s=current(),p=s&&state(s);
 const graph=(p?.draft||p?.data?.asset)?.pipeline;
 if(!graph||anchor.disabled)return;
 const colors=boardPreferences(s).colors||{};
 const sender=graph.positions.find(row=>row.key===position);
 const choices=[{key:'',name:'未指定',labelKey:'pipelineEditor.routeUnset'}];
 if(graph.routing_policy===STATUS_FIRST_ROUTING&&sender?.kind==='employee')choices.push({key:WAIT_FOR_INPUT,name:'留在当前岗位，待人工处理',labelKey:'pipelineEditor.waitHere'});
 if(canCompleteHere(graph,sender,route))choices.push({key:COMPLETE_HERE,name:'留在当前岗位并完成',labelKey:'pipelineEditor.completeHere'});
 choices.push(...[...graph.positions,...(graph.states||[])].filter(row=>row.key!==position));
 openMenu(anchor,choices.map(row=>({label:row.name,labelKey:row.labelKey,labelClass:row.kind?`column-group-name column-swatch-${colors[row.key]||defaultTone(row.kind)}`:'',selected:row.key===value,fn:()=>{if(owned(s)&&anchor.isConnected)setRoute(position,route,row.key);}})),{variant:'routeSelect'});
}
function setRoute(key,when,target){
 const s=current(),p=s&&state(s),asset=p&&(p.draft||p.data?.asset);
 if(!asset||p.conflict)return;
 const graph=asset.pipeline,position=graph.positions.find(row=>row.key===key);
 const waitHere=target===WAIT_FOR_INPUT&&graph.routing_policy===STATUS_FIRST_ROUTING&&position?.kind==='employee';
 const completeHere=target===COMPLETE_HERE&&canCompleteHere(graph,position,when);
 if(!position||target&&!waitHere&&!completeHere&&!([...graph.positions,...(graph.states||[])].some(row=>row.key===target&&row.key!==key)))return;
 const prior=graph.edges.find(edge=>edge.from===key&&(edge.when||'completed')===when);
 if((prior?.to||'')===target)return;
 const edges=graph.edges.filter(edge=>edge!==prior);
 if(target)edges.push({from:key,to:target,when});
 changed(['pipeline','edges'],edges);
 render();
}
function positionRuntimeState(s,key){
 const positions=s.positionRuntimes||=(new Map());
 if(!positions.has(key))positions.set(key,{loading:false,saving:false,data:null,error:''});
 return positions.get(key);
}
const positionRuntimeSelected=(s,key)=>owned(s)&&S.sel?.type==='source-pipeline'&&S.sel.id==='position'&&S.sel.positionKey===key;
const positionRuntimeText=key=>RunTeamsLocale.t('pipelineRuntime.'+key);
function positionRuntimeRequest(s,key,change={}){
 const body={reference:s.reference,position_key:key,...change};
 return s.reference.schema==='runteams.rented-pipeline-reference/1'
  ?host().request('market',{action:'position-runtime',...body})
  :host().request('position-runtime',body);
}
async function readPositionRuntime(s,key){
 if(!owned(s)||!s.panels?.data?.asset?.pipeline?.positions?.some(p=>p.key===key&&p.kind==='employee'))return;
 const p=positionRuntimeState(s,key);if(p.loading||p.saving)return;
 p.loading=true;p.error='';if(positionRuntimeSelected(s,key))render();
 try{p.data=await positionRuntimeRequest(s,key);}
 catch(error){p.error=error.message;}
 finally{p.loading=false;if(positionRuntimeSelected(s,key))render();}
}
async function savePositionRuntime(s,key,selection){
 const p=positionRuntimeState(s,key);
 if(!positionRuntimeSelected(s,key)||!p.data||p.saving||p.loading)return;
 p.saving=true;p.error='';
 try{p.data=await positionRuntimeRequest(s,key,{selection,
      source_revision:p.data.source_revision,expected_selection:p.data.selection});}
 catch(error){p.error=error.message;throw error;}
 finally{
  p.saving=false;
  if(positionRuntimeSelected(s,key)){
   const trigger=document.getElementById('pipeline_position_runtime');
   const wrapper=trigger?.closest('.node-position-runtime');
   if(document.querySelector('.runtime-popover')){
    if(wrapper)wrapper.title=positionRuntimeTitle(p);
   }else if(wrapper){
    const focused=document.activeElement===trigger;
    wrapper.outerHTML=positionRuntimeHeader(s,key);
    const updated=document.getElementById('pipeline_position_runtime');
    if(updated)RunTeamsLocale.apply(updated);
    if(focused)updated?.focus({preventScroll:true});
   }else render();
  }
 }
}
function retryPositionRuntime(button){
 const s=current();if(s)void readPositionRuntime(s,button.dataset.position);
}
function positionRuntimeHeader(s,key){
 const p=positionRuntimeState(s,key),data=p.data,issue=p.error||data?.error;
 if(p.loading||!data&&!issue)return `<span class="node-position-runtime">${RunTeamsStaticPages.runtimePending()}</span>`;
 if(!data?.channels.length){
  return `<button type="button" class="node-position-runtime node-position-runtime-status btn ghost sm" title="${esc(issue||positionRuntimeText('unavailable'))}" data-position="${esc(key)}" data-app-i18n="pipelineRuntime.retry" onclick="RunTeamsSourcePipelinePanels.retryPositionRuntime(this)">重新读取模型</button>`;
 }
 const picker=runtimeCsel('pipeline_position_runtime',{
  getState:()=>{
   const latest=p.data,selected=latest.effective||{},channel=latest.channels.find(c=>c.id===selected.channel_id);
   const entry=channel?.models.find(m=>m.value===selected.model);
   const models=latest.channels.flatMap(c=>[
    {head:true,label:c.name},
    ...c.models.map(m=>({value:`${c.id}::${m.value}`,label:m.label||m.value}))
   ]);
   return {models,value:selected.model?`${selected.channel_id}::${selected.model}`:'',modelLabel:selected.model,
    status:entry?'ready':selected.model?'removed':'empty',preview:true,
    efforts:(entry?.efforts||[]).map(value=>({value,label:EFFORT_LABELS[value]||value})),effort:selected.effort,
    defaultEffort:entry?.default_effort,disabled:p.loading||!models.length,saving:p.saving};
  },
  onModel:value=>{
   const [id,...parts]=value.split('::'),model=parts.join('::');
   return savePositionRuntime(s,key,{channel_id:Number(id),model,effort:''});
  },
  onEffort:effort=>{
   const selected=p.data.effective;
   if(selected)return savePositionRuntime(s,key,{channel_id:selected.channel_id,model:selected.model,effort});
  }
 });
 return `<span class="node-position-runtime" title="${esc(positionRuntimeTitle(p))}">${picker}</span>`;
}
function positionRuntimeTitle(p){
 const data=p.data,source={author:'author',buyer_override:'override',buyer_default:'fallback',position_override:'positionOverride'}[data?.effective?.selection_source];
 return p.error||data?.error||(source?positionRuntimeText(source):positionRuntimeText('title'));
}
function positionHeader(s,asset,key){
 const node=(asset&&[...asset.pipeline.positions,...(asset.pipeline.states||[])].find(row=>row.key===key))||boardColumns(s).find(row=>row.key===key);
 const member=node&&memberFor(state(s),node),title=member?.name||node?.name;
 const description=node?.kind==='employee'?node.description:node?.prompt;
 const avatar=node?.kind==='approval'?'<span class="node-detail-avatar approval">'+ICON('check')+'</span>':node?.kind==='employee'?'<span class="node-detail-avatar">'+columnAvatar(node)+'</span>':'';
 const more=`<button type="button" class="detail-head-more" data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="false" aria-label="更多操作" data-app-i18n-aria-label="automationList.more" data-position="${esc(key)}" onclick="RunTeamsSourcePipelinePanels.columnMenu(event,this.dataset.position)">${ICON('more')}</button>`;
 return detailDrawerHeader(`<div class="node-detail-heading"><div class="node-detail-title-row">${avatar}<h2 class="tt"${title?'':' data-app-i18n="pipelineSettings.position"'}>${esc(title||'岗位详情')}</h2></div>${description?`<div class="sub node-goal-sub" title="${esc(description)}">${esc(description)}</div>`: ''}</div>`,'node-detail-head',(node?.kind==='employee'?positionRuntimeHeader(s,key):'')+more);
}
function positionSkillHint(button){
 const field=button.parentElement;
 const tooltip=field.querySelector('[role="tooltip"]');
 const anchor=button.getBoundingClientRect();
 const body=button.closest('.db');
 const bottom=Math.min(body?.getBoundingClientRect().bottom??window.innerHeight,window.innerHeight);
 const top=Math.max(body?.getBoundingClientRect().top??0,0);
 const below=bottom-anchor.bottom,above=anchor.top-top;
 const flip=tooltip.offsetHeight>below&&above>below;
 field.style.setProperty('--skill-hint-anchor',`${button.offsetTop+(flip?0:button.offsetHeight)}px`);
 field.classList.toggle('node-skill-hint-above',flip);
}
function dismissSkillHint(event){
 if(event.key!=='Escape')return;
 event.preventDefault();
 event.stopPropagation();
 event.currentTarget.parentElement.classList.add('node-skill-hint-dismissed');
}
function skillOutputUsage(p,asset,position,skill){
 const pipeline=asset.pipeline;
 const statusFirst=pipeline.routing_policy===STATUS_FIRST_ROUTING;
 const stateConditions=new Set(['completed','always','failed','blocked','exception','needs_human','approved','rejected']);
 const usesRoute=when=>statusFirst
  ?when.startsWith(OUTCOME_PREFIX)&&when.length>OUTCOME_PREFIX.length
  :skill.routes?.includes(when)||!stateConditions.has(when);
 const completedEdges=pipeline.edges.filter(edge=>edge.from===position.key&&
  (['completed','always'].includes(edge.when||'completed')||usesRoute(edge.when||'completed')));
 const routing=completedEdges.some(edge=>usesRoute(edge.when||'completed'));
 const parameters=(pipeline.parameters||[]).filter(field=>field.source==='employee'&&field.type!=='secret'&&
  (!field.writers?.length||field.writers.includes(position.key)));
 const readers=new Map();
 if(parameters.length){
  // Only completed outputs are carried forward. Subsequent branches may go through an approval.
  const seen=new Set([position.key]);
  const downstream=completedEdges.map(edge=>edge.to);
  for(const key of downstream){
   if(seen.has(key))continue;
   seen.add(key);
   const next=pipeline.positions.find(row=>row.key===key);
   if(!next)continue;
   for(const edge of pipeline.edges)if(edge.from===key)downstream.push(edge.to);
   if(next.kind!=='employee')continue;
   for(const input of skillFor(p,next,asset)?.inputs||[]){
    const fieldKey=typeof input==='string'?input:input.key;
    const parameter=parameters.find(field=>field.key===fieldKey);
    if(!parameter||parameter.visible_to?.length&&!parameter.visible_to.includes(key))continue;
    if(!readers.has(fieldKey))readers.set(fieldKey,[]);
    readers.get(fieldKey).push(next.name);
   }
  }
 }
 return {routing,readers};
}
const positionSectionsKey=s=>'runteams.position-sections:'+JSON.stringify([s.storageScope,host().key(s.reference)]);
function collapsedPositionSections(s){
 const p=state(s);
 if(!p.collapsedPositionSections){
  let values=[];
  try{const saved=JSON.parse(localStorage.getItem(positionSectionsKey(s))||'[]');if(Array.isArray(saved))values=saved;}catch{}
  p.collapsedPositionSections=new Set(values);
 }
 return p.collapsedPositionSections;
}
function positionSection(key,kind,title,body,className,footer){
 return RunTeamsEmployeeDrawerHeader.section({id:'position-section-'+kind,title,body,className,footer,
  collapsedSections:collapsedPositionSections(current()),stateKey:key+':'+kind,heading:'h2',
  action:'RunTeamsSourcePipelinePanels.togglePositionSection'});
}
function togglePositionSection(button){
 const s=current(),selection=S.sel;
 if(!s||selection?.type!=='source-pipeline'||selection.id!=='position'||!button.isConnected||
  !button.dataset.settingsSectionKey.startsWith(selection.positionKey+':'))return;
 const values=collapsedPositionSections(s);
 RunTeamsEmployeeDrawerHeader.toggleSection(button,values);
 try{localStorage.setItem(positionSectionsKey(s),JSON.stringify([...values]));}catch{}
}
function skillContractMarkup(key,skill,usage){
 const inputs=(skill.inputs||[]).map(field=>typeof field==='string'?{key:field}:field);
 const outputs=(skill.outputs||[]).map(field=>{
  const definition=typeof field==='string'?{key:field}:field;
  return {...definition, routing:definition.key==='route'&&usage.routing, readers:usage.readers.get(definition.key)};
 });
 const highlighted=outputs.filter(field=>field.routing||field.readers?.length);
 const list=(fields,kind)=>`<ul class="node-skill-fields">${fields.map((field,index)=>{
  const id=`skill_field_hint_${kind}_${index}`;
  const label=`${esc(field.title?.trim()||field.key)}${field.routing?'<small data-app-i18n="pipelineEditor.skillOutputRouting">用于流转</small>':''}${field.readers?.length?'<small data-app-i18n="pipelineEditor.skillOutputHandoff">下游交接</small>':''}`;
  const note=typeof field.description==='string'?field.description.trim():'';
  const description=[
   field.readers?.length?`<span data-app-i18n="pipelineEditor.skillOutputReaders" data-app-i18n-vars="${esc(JSON.stringify({names:field.readers.join('、')}))}">传给 ${esc(field.readers.join('、'))}</span>`:'',
   note?`<span>${esc(note)}</span>`:''
  ].filter(Boolean).join('');
  const trigger=description?`<button type="button" class="node-skill-tag" aria-describedby="${id}" onpointerenter="RunTeamsSourcePipelinePanels.positionSkillHint(this)" onfocus="RunTeamsSourcePipelinePanels.positionSkillHint(this)" onclick="this.focus()" onkeydown="RunTeamsSourcePipelinePanels.dismissSkillHint(event)">${label}</button><span class="node-skill-hint" id="${id}" role="tooltip">${description}</span>`:`<span class="node-skill-tag">${label}</span>`;
  return `<li class="node-skill-field"${description?' onpointerleave="this.classList.remove(\'node-skill-hint-dismissed\')" onfocusout="this.classList.remove(\'node-skill-hint-dismissed\')"':''}>${trigger}</li>`;
 }).join('')}</ul>`;
 const empty='<span class="node-skill-fields-empty" data-app-i18n="workRecordDetail.noItems">无</span>';
 const body=`<div class="node-skill-groups">
   <div class="node-skill-group">
    <span class="node-requirement-label" data-app-i18n="pipelineEditor.skillInputs">输入</span>
    ${inputs.length?list(inputs,'input'):empty}
   </div>
   ${highlighted.length||!outputs.length?`<div class="node-skill-group">
    <span class="node-requirement-label" data-app-i18n="pipelineEditor.skillOutputs">输出</span>
    <div class="node-skill-output-fields">${highlighted.length?list(highlighted,'output'):empty}</div>
   </div>`:''}
  </div>`;
 return positionSection(key,'work',esc(skill.name),body,'node-skill-contract');
}
function positionMarkup(asset,key,locked){
 const p=state(current()),position=asset.pipeline.positions.find(row=>row.key===key),node=position||asset.pipeline.states?.find(row=>row.key===key);
 if(!node)return '<p data-app-i18n="pipelineEditor.stepRemoved">已移除环节。</p>';
 const member=position&&memberFor(p,position),skill=position&&skillFor(p,position,asset);
 const work=skill?skillContractMarkup(key,skill,skillOutputUsage(p,asset,position,skill)):'';
 const facts=position?.kind==='employee'&&!member?'<p class="help" data-app-i18n="pipelineEditor.assigneeUnavailable">负责员工暂不可用</p>':!position?`<div class="node-contract"><div class="node-section-head"><span><b data-app-i18n="pipelineSettings.taskCount">任务数量</b></span></div><p>${current().data.workflows.filter(row=>row.cursor_key===key).length}</p></div>`:'';
 const entry=positionConfigurationEntry(current(),position);
 const config=entry?RunTeamsEmployeeConfiguration.inlineParts(entry.key):null;
 if(!position)return facts;
 return `<div class="settings-section-stack">${facts}${work}${config?'<div class="position-configuration settings-section-stack">'+config.body+'</div>':''}${routeRows(asset,position,locked,{flat:true})}</div>`;
}
function options(items,value){return items.map(([key,label,labelKey,vars])=>`<option value="${esc(key)}" ${key===value?'selected':''}${labelKey?` data-app-i18n="${esc(labelKey)}"`:''}${vars?` data-app-i18n-vars="${esc(JSON.stringify(vars))}"`:''}>${esc(label)}</option>`).join('');}
function add(kind,{choiceIndex=0,name,stateKind='done',immediate=false}={}){
 const s=current();if(!s)return;
 const panel=state(s),choice=panel.choicesLoading||panel.choicesFailed?null:panel.choices?.[choiceIndex];
 if(panel.conflict)return;
 if(kind==='positions'&&!choice){
  if(panel.choicesFailed)toast('无法读取员工与技能','err','pipelineEditor.choicesFailed');
  else if(Array.isArray(panel.choices))toast('没有可选的员工与技能。','info','pipelineEditor.choicesEmpty');
  return;
 }
 const asset=draft();if(!asset)return;
 const key='n-'+crypto.randomUUID().replace(/-/g,'').slice(0,12),p=asset.pipeline;
 const copy=(key,fallback)=>globalThis.RunTeamsLocale?.t(key,{},fallback)??fallback;
 if(kind==='states')(p.states||=[]).push({key,name:name||copy('pipelineEditor.defaultEnd','已完成'),kind:stateKind});
 else if(kind==='approval')p.positions.push({key,name:name||copy('pipelineEditor.defaultDecision','人工决定'),kind:'approval',prompt:copy('pipelineWork.review','请核对结果并决定下一步。')});
 else if(choice){
  const position={key,name:choice.employee_name,kind:'employee',employee_ref:'',skill_key:choice.skill_key};
  p.positions.push(position);
  assignEmployee(s,asset,position,choice);
 }
 if(!immediate){queueSave(s);render();}
 return key;
}
function samePin(a,b){if(!a||!b)return false;const keys=[...new Set([...Object.keys(a),...Object.keys(b)])].sort();return keys.every(k=>k==='skills'?JSON.stringify([...(a[k]||[])].sort())===JSON.stringify([...(b[k]||[])].sort()):a[k]===b[k]);}
function matches(member,choice,ref){return !!member&&(member.dependency?samePin(member.dependency,choice.dependency):choice.reference.schema==='runteams.local-employee-reference/1'&&ref.source_id===choice.reference.source_id&&member.source===choice.reference.employee_source);}
function assignEmployee(s,asset,position,choice){
 let member=asset.employees.find(m=>matches(m,choice,s.reference));
 if(!member){
  const local=choice.reference.schema==='runteams.local-employee-reference/1'&&choice.reference.source_id===s.reference.source_id;
  member={ref:'e-'+crypto.randomUUID().replace(/-/g,'').slice(0,12),...(local?{source:choice.reference.employee_source}:{dependency:structuredClone(choice.dependency)})};
  asset.employees.push(member);
 }
 Object.assign(position,{employee_ref:member.ref,skill_key:choice.skill_key});
 asset.employees=asset.employees.filter(m=>asset.pipeline.positions.some(p=>p.employee_ref===m.ref));
}
function removalBlock(pipeline,kind,index){
 if(kind!=='positions')return '';
 const position=pipeline.positions[index];
 if(!position)return '';
 if(pipeline.positions.length===1)return {key:'pipelineEditor.keepRole'};
 const field=(pipeline.parameters||[]).find(field=>['writers','visible_to','producers'].some(name=>field[name]?.includes(position.key)));
 if(field)return {key:'pipelineEditor.fieldUsesRole',vars:{name:field.label||field.key}};
 return '';
}
function remove(kind,index){
 const s=current(),p=s&&state(s),source=p&&(p.draft||p.data?.asset);
 if(!source?.pipeline[kind]?.[index]||p.conflict)return;
 const blocked=removalBlock(source.pipeline,kind,index);
 if(blocked)return toast(RunTeamsLocale.t(blocked.key,blocked.vars),'info',blocked.key,blocked.vars);
 const asset=draft();
 if(!asset)return;
 const graph=asset.pipeline,[removed]=graph[kind].splice(index,1);
 if(kind==='positions'||kind==='states')graph.edges=graph.edges.filter(edge=>edge.from!==removed.key&&edge.to!==removed.key);
 if(kind==='positions'&&removed.employee_ref&&!graph.positions.some(row=>row.employee_ref===removed.employee_ref)){
  asset.employees=asset.employees.filter(row=>row.ref!==removed.employee_ref);
 }
 queueSave(s);render();
}
const flowKey=(s,id)=>'runteams.pipeline-flow:'+s.storageScope+':'+JSON.stringify(s.reference)+':'+id;
function flowState(s,id){s.flowStates||={};if(!s.flowStates[id]){try{s.flowStates[id]=JSON.parse(RunTeamsWorkState.getItem(flowKey(s,id))||'null')||{};s.flowStates[id].busy=false;if(s.flowStates[id].pending)s.flowStates[id].unknown=true;}catch(error){s.flowStates[id]={error:{key:'flowReadFailed'}};}}return s.flowStates[id];}
function feedbackOption(selection){
 const w=selection?.workflow,s=current();
 if(!s||!w)return null;
 const f=flowState(s,w.id);
 if(f.feedbackVisit!==w.snapshot_json.pipeline_visit)return null;
 return selection.humanRequest?.options?.find(option=>option.label===f.choice)||null;
}
function feedbackConfigurationFields(selection){
 const waiting=selection?.workflow?.snapshot_json?.pipeline_waiting?.configuration_fields||[];
 const option=feedbackOption(selection);
 return [...new Set([...waiting,...(option?.configuration_fields||[])])];
}
function feedbackRequiresText(option){
 return ['text','fields_and_text'].includes(option?.input_mode);
}
function topicApprovalChoices(workflow){
 // The tarot pipeline already stores candidate IDs and reads the chosen ID from the approval note.
 const {pipeline_work:work,pipeline_waiting:wait}=workflow.snapshot_json||{};
 if(workflow.state!=='needs_approval'||workflow.cursor_key!=='choose-topic'||
  work?.asset?.key!=='production'||wait?.kind!=='approval')return [];
 const run=workflow.employee_runs?.find(run=>run.id===wait.source_run_id&&run.position_key==='topic');
 const brief=run?.output_json?.output?.topic_brief;
 const candidates=brief?.candidates;
 if(!Array.isArray(candidates)||!candidates.length||!candidates.every(candidate=>
  candidate&&['A','B','C'].includes(candidate.id)&&typeof candidate.title==='string'&&candidate.title.trim())||
  new Set(candidates.map(candidate=>candidate.id)).size!==candidates.length)return [];
 return candidates.map(({id,title})=>({id,label:`${id} · ${title}`,recommended:id===brief.recommended_id}));
}
async function flow(action,decision=''){const s=current(),selection=S.sel,w=selection?.workflow;if(!s||selection.id!=='work'||!w)return;const f=flowState(s,w.id);if(f.busy||f.preparing||f.error?.key==='flowReadFailed')return;const previous=f.pending;
 try{ if(!f.pending){
  let response=document.getElementById('source_pipeline_response')?.value||'';
  const topics=action==='decide'&&decision==='approved'?topicApprovalChoices(w):[];
  if(topics.length){
   const selected=document.querySelector('input[name="source_pipeline_choice"]:checked')?.value;
   const topic=topics.find(option=>option.label===selected);
   if(!topic){
    const key='pipelineWork.chooseFeedback';
    throw Object.assign(Error(workText('chooseFeedback','请先选择一项。')),{detailKey:key});
   }
   response=topic.id;
  }
  const choice=action==='respond'?document.querySelector('input[name="source_pipeline_choice"]:checked')?.value:'';
  if(action==='respond'&&selection.humanRequest?.options?.some(option=>option.input_mode)){
   const option=selection.humanRequest.options.find(item=>item.label===choice);
   if(!option){
    const key='pipelineWork.chooseFeedback';
    throw Object.assign(Error(workText('chooseFeedback','请先选择一项。')),{detailKey:key});
   }
   if(feedbackRequiresText(option)&&!response.trim()){
    const key='pipelineWork.fillFeedback';
    throw Object.assign(Error(workText('fillFeedback','请填写所选项要求的信息。')),{detailKey:key});
   }
  }
  const materialWait=action==='respond'&&(w.snapshot_json.pipeline_waiting?.configuration_before||feedbackConfigurationFields(selection).length);
  const configuration=materialWait&&activeTaskConfiguration();
  if(configuration){
   const {state}=configuration;
   const form=document.getElementById('source_task_configuration');
   if(form)taskConfigurationDraft(form);
   if(!state.saving&&state.draft&&!state.pending){
    f.preparing=true;
    try{await saveTaskConfiguration(configuration);}finally{delete f.preparing;}
    if(!owned(s)||S.sel!==selection||selection.workflow!==w)return;
   }
   if(state.saving||state.draft||state.pending||state.loadFailed||state.credentialBusy){
    const key='pipelineWork.finishSavingBeforeContinue';
    throw Object.assign(Error(RunTeamsLocale.t(key,{},'请先确认任务配置已保存，再继续。')),{detailKey:key});
   }
  }
  if(action==='respond'&&!materialWait&&!choice&&!response.trim()){
   const key=selection.humanRequest?'workflowDetail.responseRequired':'workflowDetail.responseTextRequired';
   throw Object.assign(Error(RunTeamsLocale.t(key)),{detailKey:key});
  }
  f.pending={operation_id:crypto.randomUUID(),reference:s.reference,workflow_id:w.id,expected_visit:w.snapshot_json.pipeline_visit,action,...(action==='input'?{parameters:readCoreTaskParameters(document.getElementById('source_pipeline_input_repair'))}:action==='decide'?{decision,note:response}:action==='respond'?{response,...(choice?{choice}:{})}:action==='retry'?{verified:decision===true}:{})};
 }}catch(error){if(action==='input')inputDraft(document.getElementById('source_pipeline_input_repair'));f.error={key:'flowInputInvalid',detail:error.message,detailKey:error.detailKey,detailVars:error.detailVars};render();return;}
 try{RunTeamsWorkState.setItem(flowKey(s,w.id),JSON.stringify(f));}catch(error){f.pending=previous;f.error={key:'controlNotSent',detail:error.message};render();return;}
 const command=f.pending,checking=!!f.unknown;
 f.busy=checking||command.action==='recover'?'checking':'submitting';render();
 try{
  if(RunTeamsWorkState.pending){
   try{await RunTeamsWorkState.flush();}catch{
    if(!owned(s))return;
    if(!checking)f.pending=previous;
    f.error={key:checking?'flowReceiptUnavailable':'controlNotSent'};
    return;
   }
  }
  if(!owned(s))return;
  let receipt;
  try{receipt=await host().request(checking?'flow-operation':'flow',command);}
  catch(error){
   if(checking||error.confirmedReply&&error.code!=='operation_unknown')throw error;
   if(!owned(s))return;
   f.unknown=true;f.busy='checking';render();
   receipt=await host().request('flow-operation',command);
  }
  if(!owned(s))return;
  if(receipt.status==='unknown'){f.unknown=true;f.retry=true;f.error={key:'flowReceiptMissing'};return;}
  if(receipt.status!=='committed'||Number(receipt.result?.workflow?.id)!==Number(w.id))throw Error('任务回执无效。');
  if(S.sel===selection)host().applyWorkReply(selection,receipt.result);
  Object.assign(f,{pending:null,unknown:false,retry:false,error:'',inputValues:null,rawInputs:null,response:''});
  delete f.choice;delete f.feedbackVisit;delete f.preparation;
  void host().refresh({silent:true});
  host().workCommitted(s,w.id);
 }catch(error){
  if(!owned(s))return;
  if(error.code==='workflow_visit_changed'){
   Object.assign(f,{pending:null,unknown:false,retry:false,error:{key:'flowMovedRefresh'},inputValues:null,rawInputs:null,response:''});
   delete f.choice;delete f.feedbackVisit;
   try{
    const current=await host().request('work',{reference:s.reference,workflow_id:w.id});
    if(owned(s)&&S.sel===selection&&(selection.workflow!==w||host().applyWorkReply(selection,current)))f.error={key:'flowMoved'};
   }catch{/* The operation was rejected. Keep the confirmed status even if the read fails. */}
   if(owned(s))void host().refresh({silent:true});
  }else if(error.code==='work_preparation_required'&&error.confirmedReply){
   Object.assign(f,{pending:null,unknown:false,retry:false,error:'',
    preparation:{visit:command.expected_visit,reason:error.reason}});
  }else if(f.unknown||!error.confirmedReply||error.code==='operation_unknown'){
   f.unknown=true;f.retry=false;f.error={key:'flowReceiptUnavailable'};
  }else{
   f.pending=null;f.error={key:'controlFailed'};
  }
 }finally{
  f.busy=false;
  if(!owned(s)){if(f.pending)f.unknown=true;}
  else{
   if(f.pending||f.error&&!['flowMoved','flowMovedRefresh'].includes(f.error.key))RunTeamsWorkState.setItem(flowKey(s,w.id),JSON.stringify(f));
   else RunTeamsWorkState.removeItem(flowKey(s,w.id));
   render();
  }
 }}
function inputDraft(form){const s=current(),w=S.sel?.workflow;if(!s||!w||!form)return;const f=flowState(s,w.id);if(f.error?.key==='flowReadFailed')return;f.rawInputs={};
 for(const field of form.querySelectorAll('[data-task-parameter]')){const {key,type}=field.dataset;if(!key)continue;f.rawInputs[key]=['multiselect','checklist'].includes(type)?[...field.querySelectorAll('input:checked')].map(n=>n.value):type==='checkbox'?!!field.querySelector('input')?.checked:field.querySelector('input,textarea,select')?.value||'';}
 try{f.inputValues=readCoreTaskParameters(form);}catch(error){/* Keep partial structured text without treating typing as submission. */}
 try{RunTeamsWorkState.setItem(flowKey(s,w.id),JSON.stringify({inputValues:f.inputValues,rawInputs:f.rawInputs,pending:f.pending,unknown:f.unknown}));}catch(error){f.error={key:'flowDraftFailed',detail:error.message};}}
function restoreInputDraft(s,selection,f){requestAnimationFrame(()=>{if(!owned(s)||S.sel!==selection||f.pending)return;const form=document.getElementById('source_pipeline_input_repair');for(const field of form?.querySelectorAll('[data-task-parameter]')||[]){const value=f.rawInputs?.[field.dataset.key];if(value===undefined)continue;if(['multiselect','checklist'].includes(field.dataset.type)){for(const n of field.querySelectorAll('input'))n.checked=value.includes(n.value);}else{const n=field.querySelector('input,textarea,select');if(n){if(field.dataset.type==='checkbox')n.checked=value;else n.value=value;}}}});}

function answer(value,choice){const s=current(),w=S.sel?.workflow;if(!s||!w)return;const f=flowState(s,w.id);if(f.error?.key==='flowReadFailed')return;
 if(f.feedbackVisit!==w.snapshot_json.pipeline_visit){delete f.choice;delete f.optionResponses;}
 const previous=f.choice;
 if(choice!==undefined){
  const options=S.sel.humanRequest?.options||[];
  if(options.some(option=>option.input_mode)&&previous!==choice){
   if(feedbackRequiresText(options.find(option=>option.label===previous))){
    f.optionResponses={...f.optionResponses,[previous]:value};
   }
   value=Object.hasOwn(f.optionResponses||{},choice)?f.optionResponses[choice]:'';
  }
  f.choice=choice;
 }
 f.response=value;f.feedbackVisit=w.snapshot_json.pipeline_visit;
 const changedChoice=choice!==undefined&&previous!==choice;
 const detailKey=f.error?.key==='flowInputInvalid'?f.error.detailKey:'';
 const cleared=detailKey==='pipelineWork.chooseFeedback'&&changedChoice||
  detailKey==='pipelineWork.fillFeedback'&&(changedChoice||!!value.trim());
 if(cleared)delete f.error;
 RunTeamsWorkState.setItem(flowKey(s,w.id),JSON.stringify({response:value,choice:f.choice,optionResponses:f.optionResponses,feedbackVisit:f.feedbackVisit,pending:f.pending,unknown:f.unknown}));
 if(changedChoice||cleared){
  const selection=S.sel;
  render();
  if(changedChoice)requestAnimationFrame(()=>{if(owned(s)&&S.sel===selection)document.querySelector('input[name="source_pipeline_choice"]:checked')?.focus({preventScroll:true});});
 }
}
function retryFlow(){const s=current(),w=S.sel?.workflow,f=s&&w&&flowState(s,w.id);if(!f?.pending||!f.retry)return;f.unknown=false;f.retry=false;return flow(f.pending.action);}
function handoffMarkup(issue,definition,contract,names,sourceRunId){
 if(!issue.message&&!issue.reason)return '';
 const labels=[...new Set((issue.fields||[]).map(key=>
  definition.parameters?.find(p=>p.key===key)?.label||contract?.input_schema?.properties?.[key]?.title
 ).filter(Boolean))];
 const missingAssets=!!issue.assets?.length;
 const responsible=issue.responsible_positions||[];
 const needsUser=issue.requires_user_input_or_authorization;
 const owner=responsible.map(key=>names.get(key)).filter(Boolean).join('、')||names.get(issue.from);
 const destination=names.get(issue.to);
 return `<section class="source-work-handoff doc-reader-prose work-record-report">
  <p>${destination?workLabel('handoffWaitingFor','{name}暂时无法继续。',{name:destination}):
   workLabel('handoffWaiting','下一岗位暂时无法继续。')}</p>
  ${labels.length?'<p>'+workLabel('handoffMissingInformation','还需要补充{name}。',{name:labels.join('、')})+'</p>':''}
  ${missingAssets?'<p>'+workLabel('handoffMissingMaterials','接收岗位缺少工作所需的资料。')+'</p>':''}
  <p>${needsUser?workLabel('handoffUserAccess','请补充所需资料，或确认接收岗位可以读取。'):
   owner?workLabel('handoffEmployeeOwns','这部分由{name}核对，你无需补填。',{name:owner}):
    workLabel('handoffNoUserAction','这次交接需要员工核对，你无需补填。')}</p>
  ${sourceRunId?attemptLink(sourceRunId,'viewHandoffExecution','查看来源执行'):''}</section>`;
}
function programWork(selection,runId,detached=false){
 const s=current(),w=selection?.workflow;if(!s||!selection||!detached&&selection!==S.sel||selection.id!=='work'||!w)return null;
 if(runId==null){
  const original=w.snapshot_json,preparation=original?.pipeline_setup_required;
  if(!preparation||original.send_admitted||original.employee_run_id||!Number.isSafeInteger(preparation.chat_id)||preparation.chat_id!==original.work_chat_id)return null;
  if(host().referenceKey(original.pipeline_work?.reference)!==host().referenceKey(s.reference)||!host().referenceKey(s.reference))return null;
  return {run:null,snapshot:original,id:preparation.chat_id};
 }
 const run=w.employee_runs?.find(row=>row.id===runId),order=run?.input_json;if(!order||!Number.isSafeInteger(order.chat_id))return null;
 const original=[w.snapshot_json,...(w.snapshot_json?.pipeline_history||[]).map(item=>item.snapshot)].find(snapshot=>
  snapshot?.employee_run_id===run.id&&snapshot.work_chat_id===order.chat_id&&snapshot.pipeline_visit===order.pipeline_visit&&snapshot.pipeline_generation===order.pipeline_generation);
 if(!original||host().referenceKey(original.pipeline_work?.reference)!==host().referenceKey(s.reference)||!host().referenceKey(s.reference))return null;
 return {run,snapshot:original,id:order.chat_id};
}
let programSelection=null,privateProgramContext=null;
function programContext(){
 const selection=programSelection,context=privateProgramContext,original=context&&programWork(selection,context.run?.id??null,true);
 return original&&context.owner===current()&&context.workflow===selection.workflow&&original.run===context.run&&original.snapshot===context.snapshot&&original.id===context.id?context:null;
}
function workAuthorizationContext(runId){
 const selection=S.sel,original=programWork(selection,runId);if(!original)return null;
 if(programSelection===selection&&privateProgramContext?.id===original.id&&privateProgramContext.snapshot===original.snapshot)return privateProgramContext;
 programSelection=selection;privateProgramContext=Object.assign(original,{owner:current(),workflow:selection.workflow});
 return privateProgramContext;
}
async function authorizeWork(runId){
 const original=workAuthorizationContext(runId);if(!original)return;
 const selected=S.sel;
 if(await RunTeamsWorkAuthorization.prepare({panel:original,privateWork:original,pipeline:false})&&S.sel===selected&&selected.workflow.snapshot_json?.pipeline_setup_required)return flow('recover');
}
async function configureWork(original,authorizationContext){
 const s=current();if(!s||original!==programContext())return;
 await loadSettingsData(s);if(original!==programContext())return;
 const ref=original.snapshot.package?.reference;
 const employee=state(s).data.employees.find(e=>JSON.stringify(e.reference)===JSON.stringify(ref));
 if(employee)return RunTeamsEmployeeConfiguration.open({...memberConfigurationEntry(s,employee),authorizationContext});
}
async function configureOwn(authorizationContext){
 const s=current();if(!s)return;
 return RunTeamsEmployeeConfiguration.open({...ownConfigurationEntry(s),authorizationContext});
}
const approvalCopy={approved:'通过',rejected:'退回',revise:'退回补齐',completed:'确认',always:'继续'};
function workText(key,fallback,vars={}){const locale=window.RunTeamsLocale||(typeof RunTeamsLocale==='undefined'?null:RunTeamsLocale);return locale?.t?.('pipelineWork.'+key,vars,fallback)??fallback;}
function workLabel(key,fallback,vars={}){
 const full='pipelineWork.'+key,attributes=Object.keys(vars).length?` data-app-i18n-vars="${esc(JSON.stringify(vars))}"`:'';
 return `<span data-app-i18n="${full}"${attributes}>${esc(workText(key,fallback,vars))}</span>`;
}
const taskConfigurationKey=(s,id)=>'runteams.pipeline-flow:'+s.storageScope+':'+JSON.stringify(s.reference)+':'+id+':configuration';
const taskConfigurationFields=()=>RunTeamsConfigurationFields.create({icon:ICON,singleSelect:csel,idPrefix:'source_task_configuration_'});
function taskConfigurationState(s,id){
 s.taskConfigurationStates||={};
 if(!s.taskConfigurationStates[id]){
  try{const saved=JSON.parse(RunTeamsWorkState.getItem(taskConfigurationKey(s,id))||'null')||{};delete saved.busy;saved.saving=false;if(saved.values&&!saved.draft)saved.draft=saved.values;delete saved.values;if(saved.pending)saved.unknown=true;s.taskConfigurationStates[id]=saved;}
  catch(error){s.taskConfigurationStates[id]={error:workText('configurationDraftFailed','无法读取配置草稿，请重新读取。'),loadFailed:true};}
 }
 return s.taskConfigurationStates[id];
}
function persistTaskConfiguration(s,id,state){const {credentialBusy,credentialError,...saved}=state;RunTeamsWorkState.setItem(taskConfigurationKey(s,id),JSON.stringify(saved));}
function requiredConfigurationReady(fields,values){
 return fields.every(key=>{
  const value=values?.[key];
  return value!=null&&(typeof value!=='string'||!!value.trim())&&(!Array.isArray(value)||value.length>0);
 });
}
function taskConfigurationDraft(form,commit=false,target=null){
 const s=current(),selection=S.sel,w=selection?.workflow,c=selection?.taskConfiguration;
 if(!s||selection?.id!=='work'||!w||!c?.editable||target?.closest('.credential-field'))return;
 const state=taskConfigurationState(s,w.id);if(state.saving||state.pending||state.loadFailed||state.credentialBusy)return;
 RunTeamsConfigurationForm.cancelSave(state);
 state.revision??=c.revision;state.draft=RunTeamsConfigurationForm.draft(c.fields,taskConfigurationFields().collect(c.fields,form,state.draft||c.values),c.values);if(!state.draft)state.revision=null;state.notice='';
 for(const node of form.querySelectorAll?.('.credential-field input,.credential-field button:not(.credential-info-trigger)')||[]){
  const key=node.closest('.credential-field')?.dataset.field;
  node.disabled=!!state.draft||!!state.credentialBusy||!c.credential_fields?.[key]?.ready;
 }
 try{persistTaskConfiguration(s,w.id,state);}catch(error){state.error=error.message;}
 const confirmation=form.closest?.('.source-pipeline-work-drawer')?.querySelector('[data-confirm-task-configuration]');
 if(confirmation)confirmation.disabled=!requiredConfigurationReady(w.snapshot_json.pipeline_waiting.configuration_fields,state.draft||c.values);
 const status=form.querySelector('[data-task-configuration-status]');if(status)status.innerHTML=state.error?RunTeamsConfigurationFields.errorMarkup(state.error):'';
 if(commit&&state.draft&&!state.conflict)RunTeamsConfigurationForm.scheduleSave(state,()=>saveTaskConfiguration({s,selection,w,c,state}));
}
function leaveTaskConfiguration(){
 const s=current(),w=S.sel?.workflow,form=document.getElementById('source_task_configuration');
 if(s&&w&&form&&!taskConfigurationState(s,w.id).error)taskConfigurationDraft(form,true);
}
async function saveTaskCredential(owner,key,value,input){
 const {s,selection,w,c,state}=owner;
 if(state.credentialBusy||state.saving||state.pending||state.draft||!c.editable)return;
 const inputId=input?.id,focused=input?.closest?.('.credential-field')?.contains(document.activeElement);
 state.credentialBusy=key;state.credentialError='';
 if(focused)document.activeElement.blur();
 render();
 try{
  const result=await host().request('work-configuration',{reference:s.reference,workflow_id:w.id,action:'credential',expected_revision:c.revision,field:key,value});
  if(!owned(s)||S.sel!==selection)return;
  selection.taskConfiguration=result.configuration;
 }catch(error){
  if(owned(s)&&S.sel===selection){state.credentialError=error.message;state.conflict=error.code==='task_configuration_conflict';}
 }finally{
  state.credentialBusy=null;
  if(owned(s)&&S.sel===selection){
   render();
   const next=inputId&&document.getElementById(inputId);
   const restoreFocus=focused&&document.activeElement===document.body;
   if(next&&state.credentialError&&typeof value==='string'&&value)RunTeamsConfigurationFields.restoreCredentialInput(next,value,restoreFocus);
   else if(next&&restoreFocus)RunTeamsConfigurationFields.focusCredentialAction(next);
  }
  value=null;
 }
}
function taskCredentialOwner(target){
 const s=current(),selection=S.sel,w=selection?.workflow,c=selection?.taskConfiguration;
 if(!s||selection.id!=='work'||!w||!c||!target.closest?.('#source_task_configuration'))return null;
 return {s,selection,w,c,state:taskConfigurationState(s,w.id)};
}
async function reloadTaskConfiguration(){
 const s=current(),selection=S.sel,w=selection?.workflow;if(!s||!w)return;
 const state=taskConfigurationState(s,w.id);if(state.saving||state.pending||state.credentialBusy)return;
 state.saving=true;render();
 try{const result=await host().request('work-configuration',{reference:s.reference,workflow_id:w.id,action:'read'});
  if(!owned(s)||S.sel!==selection)return;
  selection.taskConfiguration=result.configuration;s.taskConfigurationStates[w.id]={};RunTeamsWorkState.removeItem(taskConfigurationKey(s,w.id));
 }catch(error){state.error=error.message;}finally{state.saving=false;if(owned(s)&&S.sel===selection)render();}
}
function activeTaskConfiguration(){
 const s=current(),selection=S.sel,w=selection?.workflow,c=selection?.taskConfiguration;
 return s&&selection?.id==='work'&&w&&c?{s,selection,w,c,state:taskConfigurationState(s,w.id)}:null;
}
async function saveTaskConfiguration(owner=activeTaskConfiguration()){
 if(!owner)return;
 const {s,selection,w,c,state}=owner;
 const inScope=()=>host().sameScope(s);
 if(!inScope()||state!==taskConfigurationState(s,w.id)||state.saving||state.credentialBusy||state.conflict||state.loadFailed||
  !state.pending&&(!c.editable||!state.draft))return;
 const visible=()=>owned(s)&&S.sel?.type===selection.type&&S.sel?.id==='work'&&S.sel.workflow?.id===w.id;
 await RunTeamsConfigurationForm.transact(state,{
  prepare:()=>{
   const values=Object.fromEntries(Object.entries(state.draft).filter(([,value])=>value!==''&&value!==undefined&&value!==null));
   return {reference:s.reference,workflow_id:w.id,action:'save',expected_revision:state.revision||c.revision,values};
  },
  owned:inScope,paint:()=>{if(visible())render();},form:()=>visible()?document.getElementById('source_task_configuration'):null,
  persist:async()=>{persistTaskConfiguration(s,w.id,state);if(RunTeamsWorkState.pending)await RunTeamsWorkState.flush();},
  send:async(pending,checking)=>{
   const result=await host().request('work-configuration',{...pending,action:checking?'receipt':'save'});
   return {status:result.status==='committed'?'committed':result.status==='unknown'&&checking?'not_found':'unknown',value:result.configuration};
  },
  accept:configuration=>{
   if(!configuration||!Array.isArray(configuration.fields)||!configuration.values||typeof configuration.revision!=='string')throw Error(workText('configurationUnknown','尚未确认保存结果，请核对。'));
   if(visible())S.sel.taskConfiguration=configuration;
  },
  confirmedError:error=>!!error.confirmedReply,
  accepted:()=>{state.revision=null;},
  rejected:error=>{
   const drawer=visible()?S.sel:selection;
   RunTeamsConfigurationForm.revealErrors(taskConfigurationGroups(c.fields,s.data?.pipeline),taskConfigurationGroupId,drawer.configurationCollapsed||=new Set(),state.errors);
   if(!state.pending)state.conflict=error.code==='task_configuration_conflict';
  }
 },{receipt:!!state.pending&&!state.retry});
}
const taskConfigurationGroupId=group=>'source_task_configuration-group-'+encodeURIComponent(group.label);
function toggleTaskConfigurationSection(button){
 const selection=S.sel;
 if(!current()||selection?.type!=='source-pipeline'||selection.id!=='work'||!button.isConnected||!button.closest('#source_task_configuration'))return;
 RunTeamsEmployeeDrawerHeader.toggleSection(button,selection.configurationCollapsed||=new Set());
}
function taskConfigurationGroups(fields,pipeline){
 const definitions=new Map((pipeline?.parameters||[]).filter(p=>p.source==='user'&&p.display==='setup').map(p=>[p.key,p]));
 const groups=new Map();
 for(const field of fields){
  const current=definitions.get(field.key);
  // Existing work retains its fields and values; only an absent presentation group
  // can come from the matching current declaration.
  const title=field.group||(current?.type===field.type?current.group:'')||field.label||field.key;
  if(!groups.has(title))groups.set(title,[]);
  groups.get(title).push(field);
 }
 return [...groups].map(([label,fields])=>({label,fields}));
}
function taskConfigurationMarkup(selection,position,needed,actions=''){
 const s=current(),w=selection.workflow,c=selection.taskConfiguration;if(!c?.fields?.length)return '';
 const state=taskConfigurationState(s,w.id);
 // Scope the display to the active position while keeping the complete save payload.
 const feedbackFields=feedbackConfigurationFields(selection);
 const required=feedbackFields.length?feedbackFields:null;
 const fields=c.editable&&position?.kind==='employee'
  ?c.fields.filter(field=>(!required||required.includes(field.key))&&(!field.visible_to?.length||field.visible_to.includes(position.key)))
  :[];
 if(!fields.length&&!state.pending)return '';
 const locked=state.saving||!!state.pending||state.loadFailed||!!state.credentialBusy;
 const value=state.draft||c.values;
 const renderField=field=>{
  const credential=c.credential_fields?.[field.key];
  return taskConfigurationFields().field({...field,required:!!required||field.required,
   disabled:locked||!!credential&&(!credential.ready||!!state.draft),
   ...(credential?{localCredential:credential}:{}),
   options:(field.options||[]).map(option=>[option,option])},value?.[field.key],state.errors?.[field.key]);
 };
 const groups=required?fields.map(renderField).join(''):
  RunTeamsConfigurationForm.groups({groups:taskConfigurationGroups(fields,s.data?.pipeline),
   idFor:taskConfigurationGroupId,collapsedSections:selection.configurationCollapsed||=new Set(),
   action:'RunTeamsSourcePipelinePanels.toggleTaskConfigurationSection',renderField});
 const status=state.credentialError||state.error;
 const reload=fields.length&&(state.conflict||state.loadFailed)?`<div><p class="help">${workLabel('configurationReloadHint','重新读取将显示最新保存的值。')}</p><button type="button" class="settings-section-action" onclick="RunTeamsSourcePipelinePanels.reloadTaskConfiguration()" ${state.saving?'disabled':''}>${workLabel('configurationReload','重新读取配置')}</button></div>`:'';
 const footer=RunTeamsConfigurationForm.footer({state,inline:true,receiptAttrs:'onclick="RunTeamsSourcePipelinePanels.saveTaskConfiguration()"'});
 const publishingHint=selection.signingSetup&&fields.some(field=>['support_url','privacy_url','terms_url'].includes(field.key))?
  `<p class="source-work-muted">${workLabel('signingPublishingHint','Bundle ID 用于构建和签名。支持页面、隐私政策和使用条款可在准备发布时再填写。')}</p>`:'';
 const feedback=`<p class="configuration-error" role="status" aria-live="polite" data-task-configuration-status>${status?RunTeamsConfigurationFields.errorMarkup(status):''}</p>`+reload+footer;
 const body=required
  ?`<div><div class="configuration-field-list">${groups}</div>${feedback}${detailDrawerActions(actions)}</div>`
  :publishingHint+groups+feedback;
 const form=RunTeamsConfigurationForm.markup({id:'source_task_configuration',
  attrs:'onsubmit="event.preventDefault();RunTeamsSourcePipelinePanels.taskConfigurationDraft(this,true)" oninput="RunTeamsSourcePipelinePanels.taskConfigurationDraft(this,false,event.target)" onchange="RunTeamsSourcePipelinePanels.taskConfigurationDraft(this,true,event.target)"',
  body});
 const title=required?workLabel('configurationRequired','补充配置'):workLabel('configuration','任务配置');
 return RunTeamsWorkRecords.taskSection(selection,'configuration',title,form,!!(needed||state.pending||state.draft||status));
}
function attemptLink(runId,key,label){
 return `<button type="button" class="settings-section-action" onclick="RunTeamsWorkRecords.openAttempt(${Number(runId)})">${workLabel(key,label)}</button>`;
}
function workStatusEvent(w){
 const events=w.events||[];
 if(w.state==='running'){
  const latest=events.findLast(event=>['workflow.claimed','workflow.routed'].includes(event.type));
  return latest?.type==='workflow.claimed'?latest:null;
 }
 const type=w.state==='needs_approval'?'workflow.approval_requested':'workflow.'+w.state;
 return events.findLast(event=>event.type===type&&(!event.data_json?.position_key||event.data_json.position_key===w.cursor_key));
}
function workProgress(w,definition,statusEvent,currentExecution,action=''){
 const last=w.employee_runs?.[0],ended=['completed','canceled','superseded'].includes(w.state);
 const positions=definition.positions||[],states=definition.states||[];
 const cursor=[...positions,...states].find(row=>row.key===w.cursor_key);
 const lastRole=last&&(positions.find(row=>row.key===last.position_key)?.name||last.employee_name);
 let position='';
 if(currentExecution){
  const roleName=positions.find(row=>row.key===currentExecution.position_key)?.name;
  const name=w.state==='running'?currentExecution.employee_name||roleName:roleName||currentExecution.employee_name;
  position=name?esc(name):workLabel('viewCurrentExecution','查看当前执行');
 }else if(['failed','blocked','interrupted'].includes(w.state)&&(cursor?.name||lastRole)){
  position=esc(cursor?.name||lastRole);
 }else if(ended&&lastRole){
  position=workLabel('lastExecutionRole','最后执行岗位 '+lastRole,{name:lastRole});
 }else if(cursor){
  position=states.includes(cursor)
   ?workLabel('atGroup','所在分组 '+cursor.name,{name:cursor.name})
   :esc(cursor.name);
 }
 const matchingRun=last?.state===w.state&&last?.position_key===w.cursor_key?last:null;
 const time=(w.launch_error?w.updated_at:statusEvent?.created_at)||currentExecution?.updated_at||(w.state==='failed'?matchingRun?.updated_at:null);
 const frozen=w.snapshot_json||{};
 const unassigned=w.state==='needs_human'&&!frozen.pipeline_waiting&&!frozen.pipeline_setup_required&&!frozen.pipeline_handoff;
 const state=w.launch_error?`<span class="work-record-state error">${workLabel('launchFailed','启动失败')}</span>`:
  unassigned?`<span class="work-record-state warn">${frozen.send_admitted?
   workLabel('resultNeedsReview','结果待核对'):workLabel('reasonUnavailable','原因待核对')}</span>`:RunTeamsWorkRecords.stateMarkup(w.state);
 const controls=action?`<span class="source-work-status-controls">${state}${action}</span>`:state;
 const role=currentExecution?`<button type="button" class="source-work-role source-work-current-execution" aria-label="查看当前执行" data-app-i18n-aria-label="pipelineWork.viewCurrentExecution" onclick="RunTeamsWorkRecords.openAttempt(${Number(currentExecution.id)})">${position}${ICON('chev')}</button>`:
  position?`<span class="source-work-role">${position}</span>`:'';
 return `<div class="work-record-meta source-work-progress">${controls}${role}${RunTeamsWorkRecords.timeMarkup(time)}</div>`;
}
function taskDocumentReader(id,selection,s){
 const scroll=document.querySelector('.source-pipeline-work-drawer > .right-detail-body');
 if(scroll)selection.workScroll=scroll.scrollTop;
 return openMarkdownLink('runteams://document/'+id,{returnToPipelineTask:true,isCurrent:()=>owned(s)&&S.sel===selection});
}
async function openTaskReport(button){
 const s=current(),selection=S.sel,w=selection?.workflow;
 if(!s||selection?.id!=='work'||!w||selection.openingTaskReport||!button.isConnected)return;
 selection.openingTaskReport=true;button.disabled=true;button.setAttribute('aria-busy','true');
 try{
  const report=await host().request('task-report',{reference:s.reference,workflow_id:Number(w.id)});
  if(owned(s)&&S.sel===selection)await taskDocumentReader(report.document_id,selection,s);
 }catch(error){
  if(owned(s)&&S.sel===selection){
   toast(error.message||workText('deliveryFileFailed','无法打开交付文档，请重试。'),'err');
  }
 }finally{
  selection.openingTaskReport=false;
  if(button.isConnected){button.disabled=false;button.removeAttribute('aria-busy');}
 }
}
function finalDeliveryRow(selection){
 return RunTeamsWorkRecords.deliveryRowMarkup({purpose:'document',name:selection.workflow.task?.title||selection.recordTitle||workText('title','任务')},{
  key:'task-report-'+selection.workflow.id,action:'RunTeamsSourcePipelinePanels.openTaskReport(this)'
 });
}
function taskDeliveriesMarkup(selection){
 const rows=finalDeliveryRow(selection);
 return RunTeamsWorkRecords.taskSection(selection,'deliveries',workLabel('deliveryItems','交付物'),`<div class="work-deliverable-list" role="list" aria-label="交付物" data-app-i18n-aria-label="pipelineWork.deliveryItems">${rows}</div>`,true);
}
function signingEntry(selection){
 const s=current(),w=selection?.workflow,source=selection?.signingSetup?.employee_source;
 if(!s||!w||!source)return null;
 return memberConfigurationEntry(s,{name:w.employee_runs?.[0]?.employee_name,source,reference:w.snapshot_json.employee_reference});
}
function mountSigningConfiguration(selection){
 const entry=signingEntry(selection);
 if(entry)void RunTeamsEmployeeConfiguration.mountInline(entry,selection);
}
function savedSigningTeam(selection){
 const config=RunTeamsEmployeeConfiguration.current();
 return !!config&&config.entry.key===signingEntry(selection)?.key&&!config.draft&&!config.pending&&!config.saving&&
  !!String(config.data?.values?.apple_team_id||'').trim();
}
function resumeSigning(){
 const selection=S.sel;
 if(!selection?.signingSetup||!savedSigningTeam(selection)){
  toast(workText('signingSaveTeam','请填写 Apple Team ID，并等待自动保存完成。'),'info');return;
 }
 return flow('resume_setup');
}
function openSigningConversation(){
 const selection=S.sel,id=Number(selection?.workflow?.id);
 if(!current()||!selection?.signingSetup||!Number.isSafeInteger(id)||id<1)return;
 const draft=workText('signingChatDraft','请协助排查任务 {id} 的 iPhone 真机签名。先读取这项工作及最近一次执行的汇报，核对执行 Mac 上的开发证书、私钥和描述文件是否匹配这个 App 和测试设备。请在已授权的范围内协助处理，说明需要我确认或准备的事项。',{id});
 const open=()=>{if(S.sel===selection)return host().conversation(false,{draft,signingWorkflowId:id});};
 if(!requestDetailWorkspaceLeave(open))return open();
}
function signingConfigurationMarkup(selection){
 const entry=signingEntry(selection);
 if(!entry)return '';
 const config=RunTeamsEmployeeConfiguration.inlineParts(entry.key);
 return RunTeamsWorkRecords.taskSection(selection,'signing',workLabel('signingTitle','iPhone 真机签名'),
  `<div class="source-work-signing" data-signing-configuration>
   <p>${workLabel('signingTeamHelp','在下方填写项目所属的 Apple Team ID，离开输入框后自动保存。')}</p>
   <p>${workLabel('signingMacHelp','在执行用的 Mac 上准备有效的 Apple Development 证书（含私钥），以及覆盖当前 Bundle ID 和这台 iPhone 的开发描述文件。使用 Xcode 自动签名时，描述文件由 Xcode 管理。')}</p>
   ${detailDrawerActions(`<button type="button" class="btn" onclick="RunTeamsSourcePipelinePanels.openSigningConversation()">${ICON('message-circle-more')}${workLabel('signingAskAI','在对话中让 AI 协助')}</button>`)}
   ${config?.body||''}
  </div>`,true);
}
function parkedExecution(w,definition){
 const frozen=w.snapshot_json||{};
 if(w.state!=='blocked'||!frozen.pipeline_applied_result||!frozen.employee_run_id||
  frozen.pipeline_waiting||frozen.pipeline_handoff||frozen.pipeline_unresolved||frozen.pipeline_recovery_pending||
  !definition.states?.some(state=>state.key===w.cursor_key&&state.kind==='pool'))return null;
 const run=w.employee_runs?.find(run=>run.id===frozen.employee_run_id&&run.state==='completed'&&
  run.position_key===frozen.pipeline_work?.position_key);
 return run?.output_json?run:null;
}
function feedbackBlocker(wait){
 return wait.prompt?.trim()||wait.result?.summary?.trim()||
  (wait.kind==='result'&&wait.result?.issues?.filter(RunTeamsWorkRecords.hasFailureReason).join('\n'))||'';
}
function workContent(selection,w,definition,names,interaction,workActions,statusEvent,currentExecution,parkedRun,resultChecked=false,preparationReason,labelChoicesWithSummary=false,topicApproval=false){
 const frozen=w.snapshot_json||{},wait=frozen.pipeline_waiting||{},handoff=frozen.pipeline_handoff||{},feedback=frozen.pipeline_feedback||{};
 const runs=w.employee_runs||[],latest=runs[0],objective=w.task?.payload_json?.objective||'';
 const approval=wait.kind==='approval'&&w.state==='needs_approval',position=definition.positions.find(p=>p.key===w.cursor_key);
 const failedRun=latest?.state==='failed'&&latest.position_key===w.cursor_key;
 const reason=statusEvent?.data_json?.reason;
 const failure=RunTeamsWorkRecords.hasFailureReason(reason)?reason:failedRun?'':RunTeamsWorkRecords.missingFailureReason();
 const parkedResult=parkedRun?.output_json;
 const parkedReason=parkedResult?.summary?.trim()||parkedResult?.issues?.filter(Boolean).join('\n')||parkedResult?.title||'';
 const configuredApproval=approval&&!topicApproval&&!wait.approval_request?.question;
 const approvalQuestion=topicApproval?workText('chooseTopic','选择本期选题'):wait.approval_request?.question||position?.prompt;
 const attention=approval?approvalQuestion:feedbackBlocker(wait)||parkedReason;
 const normalize=text=>String(text||'').trim().replace(/\s+/g,' ');
 const latestSummary=normalize(latest&&RunTeamsWorkRecords.executionSummary(latest));
 const verified=frozen.pipeline_signing_verification;
 const signingVerified=verified&&verified.position_key===w.cursor_key&&!selection.signingSetup&&
  verified.bundle_id===frozen.pipeline_input?.parameters?.bundle_id&&
  ['ready','running','paused'].includes(w.state);
 const context=w.state==='failed'?failure:attention||(signingVerified?workText('signingVerified','iPhone 真机签名、安装和启动已验证。'):'');
 const primary=currentExecution?context||RunTeamsWorkRecords.executionSummary(currentExecution):
  parkedReason||wait.configuration_before||normalize(context)!==latestSummary||interaction?context:'';
 const systemHint=(key,fallback)=>`<p class="source-work-muted">${workLabel('systemNotice','系统提示')} · ${workLabel(key,fallback)}</p>`;
 const sourceLabel=configuredApproval?workLabel('configuredApproval','流程审批'):
  primary&&signingVerified&&!attention?workLabel('systemNotice','系统提示'):'';
 const summary=primary?RunTeamsWorkRecords.prose(primary):'';
 let currentBody=(sourceLabel?`<p class="source-work-muted">${sourceLabel}</p>`:'')+
  (labelChoicesWithSummary?`<div id="source_pipeline_question">${summary}</div>`:summary);
 const diagnostic=detail=>detail?`<p class="source-work-muted">${esc(detail)}</p>`:'';
 if(configuredApproval){
  if(!attention)currentBody=`<p>${workLabel('configuredApproval','流程审批')}</p><p>${workLabel('approvalNoBrief','这项审批没有附上说明。你可以查看上一岗位的结果，再做决定。')}</p>`;
  if(wait.source_run_id)currentBody+=attemptLink(wait.source_run_id,'viewHandoffExecution','查看来源执行');
 }
 if(w.launch_error){
  currentBody=`<p>${workLabel('launchFailedDetail','这一步没能启动，员工还没有开始本轮工作。')}</p>`+diagnostic(w.launch_error);
 }else if(frozen.pipeline_setup_required){
  const setupMessage={
   program_disabled:['setupEnableProgram','员工还没开始工作。请先在本机功能中启用这项工作需要的员工程序。'],
   workspace_required:['setupSelectWorkspace','员工还没开始工作。请先选择这项工作要访问的业务空间。'],
   connection_required:['setupAuthorizeService','员工还没开始工作。请授权所需服务，员工才能读取这项工作需要的资料。'],
   service_unavailable:['setupServiceUnavailable','暂时无法核对工作所需的服务，员工还没开始工作。可以稍后重新检查。'],
  };
  const message=Object.hasOwn(setupMessage,preparationReason)?setupMessage[preparationReason]:
   ['setupBeforeStart','这一步还需要完成设置，员工尚未开始工作。'];
  currentBody=`<p>${workLabel(...message)}</p>`+
   diagnostic(frozen.pipeline_setup_required.message);
 }else if(frozen.pipeline_result_correction?.approval&&['ready','running'].includes(w.state)){
  currentBody=`<p>${workLabel(w.state==='running'?'writingApprovalBrief':'queuedApprovalBrief',
   w.state==='running'?'员工正在补充审批说明。':'已安排员工补充审批说明。')}</p>`;
 }else if(frozen.pipeline_result_correction?.handoff&&['ready','running'].includes(w.state)){
  currentBody=workLabel(w.state==='running'?'checkingHandoff':'queuedHandoff',
   w.state==='running'?'员工正在核对交接材料。':'已安排员工核对交接材料。');
 }else if(frozen.pipeline_result_correction?.handoff&&!primary&&!wait.kind&&['blocked','interrupted','needs_human'].includes(w.state)){
  currentBody=systemHint('handoffStillUnconfirmed','这次交接还没有补齐。已有工作已保留，可查看原执行。');
 }else if(frozen.pipeline_recovery_pending){
  currentBody=`<p>${workLabel('settlementPending','系统正在核对这次执行留下的结果。已有工作会保留。')}</p>`;
 }else if(frozen.send_admitted&&!frozen.pipeline_applied_result&&['blocked','failed','interrupted','needs_human'].includes(w.state)&&!wait.kind){
  currentBody=`<p>${resultChecked?
   workLabel('executionResultUnknown','系统没有找到可确认的结果。如果这次执行涉及提交或发布，请先到对应服务核对是否已经生效。') :
   workLabel('executionResultCheck','这次执行已结束，结果尚未确认。可以先核对本次执行留下的记录。')}</p>`;
  if(resultChecked&&frozen.employee_run_id)currentBody+=attemptLink(frozen.employee_run_id,'viewCheckedExecution','查看原执行记录');
 }else if(!primary&&!wait.kind&&['blocked','needs_human'].includes(w.state)&&!parkedReason&&!handoff.to){
  currentBody=`<p>${workLabel('noActionRecorded','这项工作已停下，记录里没有可确认的原因。暂时没有需要你补充的信息。')}</p>`+diagnostic(reason);
 }
 if(w.state==='blocked'&&handoff.to===w.cursor_key&&!frozen.send_admitted){
  const source=handoff.from===feedback.from&&runs.find(run=>Number(run.id)===Number(feedback.employee_run_id));
  currentBody+=handoffMarkup(handoff,definition,selection.inputContract,names,source?.id);
 }
 const configurationActions=wait.configuration_fields?.length&&!selection.humanRequest?workActions:'';
 const standaloneActions=configurationActions?'':workActions;
 const actionBody=interaction||standaloneActions?`<div class="doc-reader-prose work-record-report source-work-response">${interaction}${detailDrawerActions(standaloneActions)}</div>`:'';
 const materialWait=!!wait.configuration_before;
 if(!selection.signingSetup&&!materialWait)currentBody+=actionBody;
 if(currentExecution?.state==='running'){
  const activity=RunTeamsWorkRecords.liveActivityMarkup(currentExecution,true);
  if(activity)currentBody+=`<div class="doc-reader-prose work-record-report" data-pipeline-activity="${Number(currentExecution.id)}">${activity}</div>`;
 }
 let content=currentBody?`<div class="source-work-context">${currentBody}</div>`:'';
 if(selection.signingSetup)content+=signingConfigurationMarkup(selection)+actionBody;
 const configurationNeeded=materialWait||!!frozen.pipeline_setup_required||
  (handoff.fields||[]).some(key=>selection.taskConfiguration?.fields?.some(field=>field.key===key));
 const inlineConfiguration=selection.humanRequest&&(materialWait||selection.humanRequest.options?.some(option=>option.input_mode)||feedbackConfigurationFields(selection).length);
 const configuration=inlineConfiguration?'':taskConfigurationMarkup(selection,position,configurationNeeded,configurationActions);
 if(configurationNeeded)content+=configuration;
 if(materialWait&&!selection.signingSetup)content+=actionBody;
 const historyRuns=currentExecution?runs.filter(run=>run!==currentExecution):runs;
 const shownOutcome=parkedRun&&parkedReason&&primary===parkedReason&&!w.launch_error&&!frozen.pipeline_setup_required
  ?{runId:parkedRun.id,text:parkedReason}:null;
 const history=historyRuns.length||!currentExecution?RunTeamsWorkRecords.executionSectionMarkup(w,historyRuns,shownOutcome):'';
 content+=taskDeliveriesMarkup(selection);
 if(runs.length)content+=history;
 if(objective)content+=RunTeamsWorkRecords.taskSection(selection,'objective',workLabel('objective','任务说明'),RunTeamsWorkRecords.prose(objective),!runs.length);
 if(!configurationNeeded)content+=configuration;
 if(!runs.length)content+=history;
 return `<div class="source-work-content settings-section-stack">${content}</div>`;
}
function workDrawer(selection){const s=current(),w=selection.workflow;let body='',interaction='',workActions='',statusAction='',labelChoicesWithSummary=false;
 const statusEvent=w&&workStatusEvent(w);
 const currentExecution=w&&RunTeamsWorkRecords.currentExecutionOutsideHistory(w);
 if(selection.loading)body=RunTeamsSkeletons.region('task-detail',undefined,'pipelineWork.loading');else if(selection.error)body=RunTeamsLoadFailure.markup({variant:'local',title:'无法读取任务',titleKey:'pipelineWork.failed',labelKey:'employeeHistory.retry',busyLabelKey:'pipelineWork.loading',error:selection.error,retry:`RunTeamsSourcePipelines.openWork(${selection.workflowId})`});else if(w){
  workAuthorizationContext(w.snapshot_json?.employee_run_id??null);
  const frozen=w.snapshot_json||{},wait=frozen.pipeline_waiting||{},definition=frozen.pipeline_work?.asset?.pipeline||s.data.pipeline,names=new Map([...definition.positions,...definition.states].map(p=>[p.key,p.name])),f=flowState(s,w.id);
  const topics=topicApprovalChoices(w);
  const parkedRun=parkedExecution(w,definition);
  const preparationReason=f.preparation?.visit===frozen.pipeline_visit?f.preparation.reason:frozen.pipeline_setup_required?.reason;
  const resultChecked=w.events?.some(event=>event.type==='workflow.result_checked'&&event.data_json?.visit===frozen.pipeline_visit);
  const stopped=!['ready','running','completed','canceled'].includes(w.state)&&!(frozen.pipeline_execution||{}).active;
  const canCheck=stopped&&(w.retry_mode==='verify'||frozen.pipeline_unresolved||frozen.pipeline_recovery_pending);
  if(f.error)interaction+=host().operationError(typeof f.error==='string'||f.error.key==='controlFailed'?{key:'controlFailed'}:f.error,{inline:true});
  const operationLabel=f.busy||(f.retry?'retryControl':'checkControl');
  if(f.pending){
   const stageRetry=f.pending.action==='retry';
   const button=`<button type="button" ${stageRetry?'class="work-record-state source-work-retry" data-stage-recovery':'class="btn pri"'} onclick="${f.retry?'RunTeamsSourcePipelinePanels.retryFlow()':`RunTeamsSourcePipelinePanels.flow('${f.pending.action}')`}" ${f.busy?'disabled aria-busy="true"':''} data-app-i18n="pipelineBoard.${operationLabel}">${f.busy==='submitting'?'正在提交…':f.busy?'正在核对…':f.retry?'重试操作':'核对操作结果'}</button>`;
   if(stageRetry)statusAction=button;
   else workActions=button;
  }
  else if(s.data.runtime.status==='running'&&w.state==='needs_approval'&&wait.kind==='approval'){
   const choices=wait.approval_request?.options??definition.edges
    .filter(edge=>edge.from===w.cursor_key)
    .map(edge=>({decision:edge.when||'completed'}));
   const selected=f.feedbackVisit===frozen.pipeline_visit?f.choice:'';
   if(topics.length){
    labelChoicesWithSummary=true;
    interaction+=workflowHumanChoicesMarkup(topics,'source_pipeline_choice',selected,'RunTeamsSourcePipelinePanels.answer(document.getElementById(\'source_pipeline_response\')?.value||\'\',this.value)','source_pipeline_question');
   }
   const noteLabel=topics.length?workLabel('topicReturnNote','退回说明（选填）'):workLabel('note','决定说明');
   const response=!topics.length||f.feedbackVisit===frozen.pipeline_visit?f.response||'':'';
   interaction+=`<label class="lbl" for="source_pipeline_response">${noteLabel}</label><textarea class="input${topics.length?' source-work-custom-answer':''}" id="source_pipeline_response" oninput="RunTeamsSourcePipelinePanels.answer(this.value)">${esc(response)}</textarea>`;
   workActions=choices.map(option=>{
    const decision=option.decision;
    const confirmTopic=topics.length&&decision==='approved';
    const label=option.label?esc(option.label):Object.hasOwn(approvalCopy,decision)
     ?`<span data-app-i18n="pipelineWork.decision.${decision}">${approvalCopy[decision]}</span>`
     :esc(decision);
    return `<button type="button" class="btn${confirmTopic||option.recommended?' pri':''}" data-decision="${esc(decision)}"${confirmTopic&&!topics.some(topic=>topic.label===selected)?' disabled':''}${!confirmTopic&&option.description?` title="${esc(option.description)}"`:''} onclick="RunTeamsSourcePipelinePanels.flow('decide',this.dataset.decision)">${label}</button>`;
   }).join('');
  }else if(selection.signingSetup){
   workActions=`<button type="button" class="btn pri" onclick="RunTeamsSourcePipelinePanels.resumeSigning()" ${s.data.runtime.status==='running'&&savedSigningTeam(selection)?'':'disabled'}>${workLabel('signingContinue','材料已准备好，继续验证')}</button>`;
  }else if(s.data.runtime.status==='running'&&w.state==='needs_human'&&wait.configuration_fields?.length&&!selection.humanRequest){
   const configuration=taskConfigurationState(s,w.id);
   const ready=requiredConfigurationReady(wait.configuration_fields,configuration.draft||selection.taskConfiguration?.values);
   workActions=`<button type="button" class="btn pri" data-confirm-task-configuration onclick="RunTeamsSourcePipelinePanels.flow('respond')" ${ready&&!configuration.saving&&!configuration.pending?'':'disabled'}>${workLabel('confirmConfiguration','确认配置并继续')}</button>`;
  }else if(s.data.runtime.status==='running'&&['blocked','needs_human'].includes(w.state)&&wait.kind==='result'&&['blocked','needs_human'].includes(wait.result?.status)){
   const request=selection.humanRequest,options=workflowHumanOptions(request),sameVisit=f.feedbackVisit===frozen.pipeline_visit;
   const typed=options.some(option=>option.input_mode),selected=feedbackOption(selection),requiresText=feedbackRequiresText(selected);
   labelChoicesWithSummary=!!(options.length&&feedbackBlocker(wait));
   const questionId=labelChoicesWithSummary||request?.question?'source_pipeline_question':'';
   let responseBody='';
   if(request?.question&&!labelChoicesWithSummary)responseBody+=`<p class="core-human-question" id="source_pipeline_question">${esc(request.question)}</p>`;
   if(options.length)responseBody+=workflowHumanChoicesMarkup(options,'source_pipeline_choice',sameVisit?f.choice:'','RunTeamsSourcePipelinePanels.answer(document.getElementById(\'source_pipeline_response\')?.value||\'\',this.value)',questionId);
   else responseBody+=`${request?.question?'':`<p class="source-work-muted">${workLabel('systemNotice','系统提示')} · ${workLabel('noEmployeeQuestion','员工没有留下具体问题。你可以根据上方执行结果补充信息。')}</p>`}<label class="lbl" for="source_pipeline_response">${workLabel('supplementInformation','补充信息')}</label>`;
   const feedbackFields=(!typed||selected)?feedbackConfigurationFields(selection):[];
   if(feedbackFields.length)responseBody+=taskConfigurationMarkup(selection,definition.positions.find(row=>row.key===w.cursor_key),true);
   const noteKey=sameVisit&&f.choice?'workflowDetail.replyNotePlaceholder':'workflowDetail.customReplyPlaceholder';
   const noteText=sameVisit&&f.choice?'补充说明（可选）':'输入自定义回答';
   const customReply=options.length?` placeholder="${esc(noteText)}" aria-label="${esc(noteText)}" data-app-i18n-placeholder="${noteKey}" data-app-i18n-aria-label="${noteKey}"`:'';
   if(!typed&&selected)responseBody+=`<label class="lbl" for="source_pipeline_response">${workLabel('legacyFeedbackNote','如需补充资料，请填写在这里')}</label>`;
   if(!typed||requiresText){
    const input=`<textarea class="input${options.length?' source-work-custom-answer':''}" id="source_pipeline_response"${requiresText?' required maxlength="4000"':customReply} oninput="RunTeamsSourcePipelinePanels.answer(this.value)">${esc(sameVisit||f.feedbackVisit==null?f.response||'':'')}</textarea>`;
    responseBody+=requiresText?`<div class="source-work-feedback-text"><label class="source-work-feedback-prompt" for="source_pipeline_response">${esc(selected.response_prompt)} ${workLabel('feedbackRequiredMark','（必填）')}</label>${input}</div>`:input;
   }
   interaction+=feedbackFields.length||requiresText?`<div class="settings-section-stack">${responseBody}</div>`:responseBody;
   workActions=`<button type="button" class="btn pri" onclick="RunTeamsSourcePipelinePanels.flow('respond')" ${typed&&!selected?'disabled':''}>${typed?(feedbackFields.length||requiresText?workLabel('continueAfterInput','补充后继续'):workflowDetailCopy('confirm','确认并继续')):wait.configuration_before?workLabel('continueAfterInput','补充后继续'):options.length?workflowDetailCopy('confirm','确认并继续'):workLabel('reply','回复并继续')}</button>`;
  }else if(frozen.pipeline_setup_required&&!frozen.send_admitted&&programWork(selection,null)&&['blocked','needs_human'].includes(w.state)){
   const check=preparationReason==='service_unavailable',enable=preparationReason==='program_disabled';
   const disabled=s.data.runtime.status!=='running'?'disabled':'';
   const action=check?"RunTeamsSourcePipelinePanels.flow('recover')":enable?'RunTeamsSourcePipelinePanels.authorizeWork(null)':'RunTeamsSourcePipelinePanels.workSettings(null)';
   const label=check?workLabel('checkSetup','重新检查'):enable?workLabel('enableSetupProgram','启用员工程序'):workLabel('openSetup','打开本机功能');
   workActions=(check||enable?'':`<button type="button" class="btn" onclick="RunTeamsSourcePipelinePanels.authorizeWork(null)" ${disabled}>${workLabel('checkSetupContinue','检查并继续')}</button>`)+
    `<button type="button" class="btn pri" onclick="${action}" ${disabled}>${label}</button>`;
  }else if(selection.inputContract&&w.state==='blocked'&&s.data.runtime.status==='running'){
   interaction+=`<p>${workLabel('systemNotice','系统提示')} · ${workLabel('repairHint','更新任务信息后，系统会重新核对输入。')}</p><form id="source_pipeline_input_repair" oninput="RunTeamsSourcePipelinePanels.inputDraft(this)">${coreTaskParameterFields(coreWorkflowFrozenParameters(selection.inputContract),f.inputValues||selection.inputContract.values,'source_pipeline_repair')}</form>`;
   workActions='<button type="button" class="btn pri" onclick="RunTeamsSourcePipelinePanels.flow(\'input\')" data-app-i18n="pipelineWork.complete">更新并继续</button>';
   restoreInputDraft(s,selection,f);
  }else if(w.retry_mode==='launch'){
   workActions=`<button type="button" class="btn" data-stage-recovery onclick="RunTeamsSourcePipelinePanels.flow('retry',false)" ${s.data.runtime.status==='running'?'':'disabled'}>${workLabel('retryLaunch','重新启动此岗位')}</button>`;
  }else if(w.retry_mode==='retry'){
   statusAction=`<button type="button" class="work-record-state source-work-retry" data-stage-recovery onclick="RunTeamsSourcePipelinePanels.flow('retry',false)" ${s.data.runtime.status==='running'?'':'disabled'} data-app-i18n="employeeHistory.retry">重试</button>`;
  }else if(canCheck&&!parkedRun){
   if(resultChecked&&w.retry_mode==='verify')workActions=`<button type="button" class="btn" data-stage-recovery onclick="RunTeamsSourcePipelinePanels.flow('retry',true)" ${s.data.runtime.status==='running'?'':'disabled'}>${workLabel('confirmedRestart','确认未生效，重新执行')}</button>`;
   else workActions=`<button type="button" class="btn" onclick="RunTeamsSourcePipelinePanels.flow('recover')">${workLabel('checkExecutionResult','核对执行结果')}</button>`;
  }
  body=workContent(selection,w,definition,names,interaction,workActions,statusEvent,currentExecution,parkedRun,resultChecked,preparationReason,labelChoicesWithSummary,topics.length>0&&s.data.runtime.status==='running');
 }
 const definition=w?.snapshot_json?.pipeline_work?.asset?.pipeline||s.data?.pipeline;
 const progress=w?workProgress(w,definition,statusEvent,currentExecution,statusAction):'';
 const title=w?.task?.title;
 const cardTitle=s.data?.workflows?.find(row=>Number(row.id)===Number(selection.workflowId))?.title||selection.recordTitle;
 return RunTeamsWorkRecords.taskDetailMarkup({selection,title:title||cardTitle||workText('title','任务'),
  titleKey:title||cardTitle?undefined:'pipelineWork.title',metadata:progress,
  back:RunTeamsWorkRecords.taskBackMarkup(selection),body,inputId:'source_pipeline_response'});
}

window.addEventListener('beforeunload',event=>{const p=current()?.panels;if(p?.draft||p?.pending){event.preventDefault();event.returnValue='';}});
async function revealTaskCredential({s,selection,w,c,state},field){
 if(state.credentialBusy||state.saving||state.pending||state.draft||!c.editable)return null;
 const reply=await host().request('work-configuration',{reference:s.reference,workflow_id:w.id,action:'reveal-credential',expected_revision:c.revision,field});
 return owned(s)&&S.sel===selection&&selection.taskConfiguration===c?reply.value:null;
}
RunTeamsConfigurationFields.bindCredentialEditor(taskCredentialOwner,saveTaskCredential,revealTaskCredential);
function editStandard(event){if(event.type==='keydown'&&!['Enter',' '].includes(event.key)||event.target.closest('a,input,button,textarea'))return;event.preventDefault();startSettingsEdit('standard');}
function toggleStandard(button){
 if(RunTeamsAssetOverview.pipeline()&&!state(current()).settingsEdit)RunTeamsEmployeeDrawerHeader.toggleSection(button,S.sel.standardSections);
}
function overviewVersion(){const s=current();if(!s||!RunTeamsAssetOverview.pipeline())return;const action=window.RunTeamsPipelineMarket?.headerAction?.(s);if(action&&!action.disabled)action.onPress();}
window.RunTeamsSourcePipelinePanels={loadSettingsData,editStandard,toggleStandard,overviewVersion,openTaskReport,mountSigningConfiguration,resumeSigning,openSigningConversation,taskConfigurationDraft,leaveTaskConfiguration,saveTaskConfiguration,reloadTaskConfiguration,toggleTaskConfigurationSection,addStageMenu,columns,columnClick,columnAvatar,columnMenu,position,retryPositionRuntime,setRoute,routeMenu,togglePositionSection,toggleRouteConditions,positionSkillHint,dismissSkillHint,programContext,authorizeWork,configureWork,configureOwn,workSettings:runId=>{const original=workAuthorizationContext(runId);if(original)return configureWork(original,RunTeamsWorkAuthorization.state({panel:original,privateWork:original,pipeline:false}));},settings,startSettingsEdit,updateSettingsEdit,finishSettingsEdit,rename,read,drawer,changed,save,receipt,retryCommittedRefresh,cancel,readEmployeeChoices,configurationRequest,holdTextField,workDrawer,flow,retryFlow,answer,inputDraft};
})();
