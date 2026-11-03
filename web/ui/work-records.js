/* Platform navigation for the employee's records. No author code or business writes. */
(()=>{
 'use strict';
 const saved=new Map();
 function target(panel=S.conversationPanel){
  if(!panel||panel.loading||panel.error||panel.debug_preview||!RunTeamsEmployeeDirectory.employeePanel(panel))return null;
  const reference=RunTeamsEmployeeDirectory.panelReference(panel),entry=RunTeamsEmployeeDirectory.forPanel(panel);
  const scope=reference?{employee_reference:reference}:entry?.record?.id?{employee_id:Number(entry.record.id)}:null;
  if(!scope)return null;
  return {scope,key:JSON.stringify([workspaceAccountCacheToken(),Number(panel.id),reference?RunTeamsEmployeeDirectory.referenceKey(reference):scope.employee_id])};
 }
 function matches(selection,t){
  if(selection?.type!=='core-results'||!t)return false;
  return t.scope.employee_reference?RunTeamsEmployeeDirectory.referenceKey(selection.scope?.employee_reference)===RunTeamsEmployeeDirectory.referenceKey(t.scope.employee_reference):Number(selection.scope?.employee_id)===t.scope.employee_id;
 }
 function capture(){
  const t=target(),selection=S.sel;if(!matches(selection,t)||!selection.data)return;
  const node=document.querySelector('#rgDrawer .context-results-body');
  selection.recordScrollTop=node?.scrollTop||0;
  saved.delete(t.key);saved.set(t.key,selection);
  while(saved.size>30)saved.delete(saved.keys().next().value);
 }
 function controls(panel){
  const t=target(panel);if(!t)return '';
  const on=matches(S.sel,t);
  return `<button type="button" class="conversation-header-action employee-records-trigger${on?' on':''}" aria-label="工作记录" aria-pressed="${on}" aria-expanded="${on}" onclick="RunTeamsWorkRecords.toggle()">${ICON('clock')}<span>工作记录</span></button>`;
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
   requestAnimationFrame(()=>{if(S.sel===previous){const node=document.querySelector('#rgDrawer .context-results-body');if(node)node.scrollTop=previous.recordScrollTop||0;}});
   return refreshContextResults(true);
  }
  return openContextResults(t.scope);
 }
 function position(selection){
  const node=document.querySelector('#rgDrawer .context-results-body');
  if(!node)return;
  const key=selection.resultKey||'list';selection.recordPositions||={};selection.recordPositions[key]=node.scrollTop;
 }
 function restore(selection){
  requestAnimationFrame(()=>{if(S.sel!==selection)return;const node=document.querySelector('#rgDrawer .context-results-body');if(node)node.scrollTop=selection.recordPositions?.[selection.resultKey||'list']||0;});
 }
 async function loadReport(selection=S.sel,force=false){
  const result=selection?.data?.results?.find(item=>item.key===selection.resultKey),ref=result?.report_document;
  if(S.sel!==selection||selection?.type!=='core-results'||!ref)return;
  const account=workspaceAccountCacheToken();selection.reportDocuments||={};
  let saved=selection.reportDocuments[ref.id];
  if(saved?.status==='loading'&&saved.refRevision>=ref.revision||!force&&saved?.status==='ready'&&saved.doc?.revision>=ref.revision)return;
  const state={status:'loading',refRevision:ref.revision,doc:saved?.doc||null,error:''};selection.reportDocuments[ref.id]=state;
  const current=()=>S.sel===selection&&selection.resultKey===result.key&&workspaceAccountCacheToken()===account&&selection.reportDocuments[ref.id]===state;
  render();
  try{
   const doc=await api('/api/core/documents/'+Number(ref.id));
   if(!current()){if(selection.reportDocuments[ref.id]===state)state.status='idle';return;}
   if(doc?.error)throw Error(doc.error);
   if(!doc||typeof doc.content!=='string'||ref.document_key&&doc.document_key!==ref.document_key)throw Error('汇报文档归属未能确认');
   state.doc=doc;state.status='ready';
  }catch(error){if(current()){state.status='error';state.error=error.message||'汇报暂时无法读取';}else if(selection.reportDocuments[ref.id]===state)state.status='idle';}
  if(current())render();
 }
 function reportMarkup(result,selection){
  const state=selection.reportDocuments?.[result.report_document.id];
  const body=state?.doc?(typeof RunTeamsRichDocuments!=='undefined'&&RunTeamsRichDocuments.supported(state.doc)?RunTeamsRichDocuments.reportMarkup(state.doc,result.report_document.id):renderMarkdown(state.doc.content,{imageUrls:state.doc.native?.image_urls})):result.summary?`<p>${esc(result.summary)}</p>`:'';
  const notice=state?.status==='error'?RunTeamsLoadFailure.markup({variant:'local',title:'汇报暂时无法读取',error:state.error,retry:'RunTeamsWorkRecords.loadReport(S.sel,true)'}):!state?.doc?'<p class="work-record-report-loading" role="status">正在读取汇报…</p>':'';
  return notice+body;
 }
 function reportActionMarkup(result,selection){
  const ref=result?.report_document;
  if(!ref||!selection.reportDocuments?.[ref.id]?.doc)return '';
  return `<button type="button" class="work-record-report-open" data-record-report="${esc(result.key)}" onclick="RunTeamsWorkRecords.openReport(this.dataset.recordReport)">在文档中打开</button>`;
 }
 async function openReport(key){
  const owner=S.sel,result=owner?.data?.results?.find(item=>item.key===key),ref=result?.report_document;
  if(owner?.type!=='core-results'||!ref)return;
  capture();
  return openDocumentReaderById(Number(ref.id));
 }
 async function openOrigin(key){
  const owner=S.sel,scope=workspaceAccountCacheToken(),result=owner?.data?.results?.find(r=>r.key===key);if(owner?.type!=='core-results'||!result)return;
  capture();
  if(owner.scope?.source_pipeline_reference)return RunTeamsSourcePipelines.openWork(Number(result.workflow_id));
  if(result.origin?.kind==='employee_chat'&&Number(result.origin.chat_id)>0)return openConversationSession(Number(result.origin.chat_id),'general');
  let workflow;
  try{
  workflow=await api(`/api/core/workflows/${Number(result.workflow_id)}`);
  }catch(error){if(S.sel===owner&&workspaceAccountCacheToken()===scope)toast(error.message||'原工作暂时无法读取','err');return;}
  if(S.sel!==owner||workspaceAccountCacheToken()!==scope)return;
  if(!workflow)return toast('原工作暂时无法读取','err');
  if(workflow.error)return toast(workflow.error,'err');
  if(Number(workflow.id)!==Number(result.workflow_id))return toast('原工作归属未能确认','err');
  selectDetailWorkspace({type:'core-workflow',id:Number(result.workflow_id),workflow,returnTo:owner});render();
 }
 function returnFromOrigin(){
  const selection=S.sel?.returnTo;if(selection?.type!=='core-results')return;
  selectDetailWorkspace(selection);
  const url=new URL(contextResultsRoute(selection.scope),location.href);
  if(selection.resultKey)url.searchParams.set('delivery',selection.resultKey);
  setAppUrl(url.pathname+url.search+url.hash,true);render();restore(selection);
 }
 window.RunTeamsWorkRecords=Object.freeze({controls,toggle,refreshForPanel,capture,position,restore,loadReport,reportMarkup,reportActionMarkup,openReport,openOrigin,returnFromOrigin});
 window.addEventListener('runteams:business-scope-will-change',()=>saved.clear());
 window.addEventListener('pagehide',()=>saved.clear());
})();
