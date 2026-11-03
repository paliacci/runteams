/* Trusted local content renderer. Product APIs, identity and navigation stay in the host. */
(()=>{
 'use strict';
 const channel='runteams-rich-document/1',reports=new Map(),pending=new Map(),readyFrames=new WeakSet();
 const theme=()=>document.documentElement.dataset.theme==='dark'||!document.documentElement.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
 function supported(doc){return !doc?.data_view&&!/data-type=["']NodeAttributeView["']/.test(doc?.content||'')&&!doc?.task_input&&!doc?.work_artifact&&['rich-document','markdown','json'].includes(doc?.content_model);}
 function frame(token,embedded=false){return `<div class="rich-frame-shell"><div class="rich-frame-loading">${documentReaderSkeletonMarkup(true)}</div><iframe onload="RunTeamsRichDocuments.loaded(this)" class="rich-document-frame${embedded?' rich-report-frame':''}" ${embedded?'':'id="rich_document_frame"'} data-rich-token="${esc(token)}" title="${embedded?'工作汇报':'文档内容'}" src="/rich-document/dist/index.html#${esc(token)}" referrerpolicy="no-referrer" allow="clipboard-write"></iframe></div>`;}
 function outlineMarkup(state){
  const collapsed=!!S.docOutlineCollapsed,label=collapsed?'展开大纲':'收起大纲',outline=state.richOutline||{items:[],name:state.doc.name,active_id:''};
  return `<div class="rich-document-outline-list">${outline.items.map(item=>`<button type="button" class="doc-outline-link level-h${item.level}${outline.active_id===item.id?' on':''}" data-outline-id="${esc(item.id)}" title="${esc(item.text)}"${outline.active_id===item.id?' aria-current="location"':''} onclick="RunTeamsRichDocuments.jumpOutline(this.dataset.outlineId)">${esc(item.text)}</button>`).join('')}</div><div class="rich-document-outline-footer"><button type="button" class="detail-panel-collapse" title="${label}" aria-label="${label}" aria-expanded="${!collapsed}" onclick="RunTeamsRichDocuments.toggleOutline()">${ICON(collapsed?'panel-left-open':'panel-left-close')}</button></div>`;
 }
 function updateOutline(state,data){
  if(!Array.isArray(data.items)||data.items.length>500||data.items.some(item=>!item||typeof item.id!=='string'||item.id.length>128||typeof item.text!=='string'||item.text.length>500||![1,2,3].includes(item.level)))return;
  const next={name:String(data.name||state.doc.name||'文档').slice(0,200),items:data.items,active_id:typeof data.active_id==='string'?data.active_id:''};
  const nav=document.getElementById('rich_document_outline');if(!nav)return;
  const previous=state.richOutline;state.richOutline=next;
  if(!previous||JSON.stringify(previous.items)!==JSON.stringify(next.items)){
   const focused=nav.contains(document.activeElement)?document.activeElement?.dataset.outlineId:undefined;
   nav.innerHTML=outlineMarkup(state);
   if(focused!==undefined)[...nav.querySelectorAll('[data-outline-id]')].find(node=>node.dataset.outlineId===focused)?.focus({preventScroll:true});
  }else for(const node of nav.querySelectorAll('[data-outline-id]')){const active=node.dataset.outlineId===next.active_id;node.classList.toggle('on',active);if(active)node.setAttribute('aria-current','location');else node.removeAttribute('aria-current');}
 }
 function toggleOutline(){
  const state=S.docReader;if(!state?.richToken||!resolve(state.richToken))return;
  S.docOutlineCollapsed=!S.docOutlineCollapsed;try{localStorage.setItem(DOC_OUTLINE_KEY,S.docOutlineCollapsed?'1':'0');}catch{}
  const slot=document.getElementById('rich_document_outline_slot'),nav=document.getElementById('rich_document_outline');slot?.classList.toggle('is-collapsed',!!S.docOutlineCollapsed);nav?.classList.toggle('is-collapsed',!!S.docOutlineCollapsed);
  if(nav){nav.innerHTML=outlineMarkup(state);nav.querySelector('.detail-panel-collapse')?.focus({preventScroll:true});}
 }
 function jumpOutline(id){
  const state=S.docReader,frame=currentFrame(state?.richToken);if(!frame||!resolve(state.richToken))return;
  if(id&&!state.richOutline?.items.some(item=>item.id===id))return;post(frame,'outline-jump',{id});
  const width=document.querySelector('.rich-document-layout')?.clientWidth;if(width>0&&width<=820&&!S.docOutlineCollapsed)toggleOutline();
 }
 function main(state){
  state.richToken||=crypto.randomUUID();state.richAccount||=workspaceAccountCacheToken();
  return `<main class="environment-page doc-reader-page rich-document-page"><header class="doc-reader-bar" oncontextmenu="documentReaderMoreMenu(event)"><button type="button" class="doc-reader-back" aria-label="返回" onclick="closeDocumentReader()">${ICON('chev')}<span>文档</span></button><div class="doc-reader-bar-copy"><span class="doc-reader-bar-title" id="doc_bar_title">${esc(state.doc.name||'文档')}</span></div><div class="doc-reader-actions" id="doc_reader_actions">${documentReaderActionsMarkup(state.doc)}</div></header><div class="rich-document-layout"><aside class="rich-document-outline-slot${S.docOutlineCollapsed?' is-collapsed':''}" id="rich_document_outline_slot"><nav class="doc-reader-outline open rich-document-outline${S.docOutlineCollapsed?' is-collapsed':''}" id="rich_document_outline" aria-label="文档大纲">${outlineMarkup(state)}</nav></aside><div class="rich-document-body">${frame(state.richToken)}</div><div class="doc-reader-versions-slot ${S.docVersionsOpen?'':'is-hidden'}" id="doc_reader_versions_slot"><nav class="doc-reader-versions" id="doc_reader_versions" aria-label="历史版本">${documentReaderVersionsMarkup()}</nav></div></div></main>`;
 }
 function reportMarkup(doc,id){
  const key=workspaceAccountCacheToken()+':'+id+':'+doc.revision;
  let saved=[...reports.values()].find(item=>item.key===key);
  if(!saved){saved={key,token:crypto.randomUUID(),doc:{...doc,editable:false},account:workspaceAccountCacheToken()};reports.set(saved.token,saved);}
  while(reports.size>40)reports.delete(reports.keys().next().value);
  return frame(saved.token,true);
 }
 function post(frame,type,value={}){frame?.contentWindow?.postMessage({channel,token:frame.dataset.richToken,type,...value},location.origin);}
 function currentFrame(token){return [...document.querySelectorAll('iframe[data-rich-token]')].find(f=>f.dataset.richToken===token);}
 function resolve(token){
  const state=S.docReader;
  if(state?.richToken===token&&state.richAccount===workspaceAccountCacheToken()&&state.status==='ready')return {state,doc:{...state.doc,content:state.text,editable:state.doc.editable&&state.doc.is_current_revision!==false},embedded:false};
  const report=reports.get(token);
  if(report?.account===workspaceAccountCacheToken())return {doc:report.doc,embedded:true};
  return null;
 }
 async function save(frame,state,data){
  if(state.richSaving)return state.richSaving;
  const account=workspaceAccountCacheToken();
  const run=(async()=>{
   let ok=false;
   try{
    if(state.doc.content_model!=='rich-document'||!state.doc.editable||state.doc.is_current_revision===false)throw Error('这份文档当前不能编辑。');
    const response=await api('/api/core/documents/'+Number(state.doc.id),'POST',{content_model:'rich-document',name:data.name,document:data.document,base_revision:data.base_revision});
    if(S.docReader!==state||account!==workspaceAccountCacheToken()||!frame.isConnected)return false;
    if(response?.error||response?.conflict)throw Error(response.error||'文档已变化，请重新打开后核对。');
    state.doc={...state.doc,...response};state.text=JSON.stringify(data.document);if(state.richProtocol!==2)state.richDirty=false;state.saveStatus='saved';state.saveError='';
    const title=document.getElementById('doc_bar_title');if(title)title.textContent=state.doc.name||'文档';
    post(frame,'saved',{request_id:data.request_id,revision:response.revision});ok=true;loadDocumentRevisions(state.doc);
   }catch(error){if(S.docReader===state&&account===workspaceAccountCacheToken()){state.saveStatus='error';state.saveError=error.message||'保存失败，请重试。';post(frame,'saved',{request_id:data.request_id,error:state.saveError});}}
   finally{const wait=pending.get(state.richToken);if(wait&&state.richProtocol!==2){pending.delete(state.richToken);wait.done(ok);}}
   return ok;
  })();state.richSaving=run;try{return await run;}finally{if(state.richSaving===run)state.richSaving=null;}
 }
 function flush(state){
  if(!state.richDirty&&!state.richSaving)return Promise.resolve(true);
  const frame=currentFrame(state.richToken);if(!frame)return Promise.resolve(false);
  const current=pending.get(state.richToken);if(current)return current.promise;
  if(state.richProtocol!==2&&state.richSaving)return state.richSaving;
  const flush_id=crypto.randomUUID();let finish;
  const promise=new Promise(resolve=>finish=resolve);
  const timeout=setTimeout(()=>{pending.delete(state.richToken);finish(false);},15000);
  const done=ok=>{clearTimeout(timeout);finish(ok);};pending.set(state.richToken,{promise,done,flush_id});post(frame,'save-request',{flush_id});return promise;
 }
 function download(blob,name){
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=String(name||'文档').replace(/[\\/]/g,'_');document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 function editorAction(action){
  const state=S.docReader,frame=currentFrame(state?.richToken);
  if(!state||!frame||!resolve(state.richToken))return;
  post(frame,'header-action',{action});
 }
 function exportCurrent(){editorAction('export');}
 function retrySave(){editorAction('retry-save');}
 async function resource(frame,target,data){
  const account=workspaceAccountCacheToken(),state=target.state;
  try{
   if(!/^[a-zA-Z0-9-]{1,80}$/.test(data.request_id||'')||target.doc.content_model!=='rich-document'||S.activeOrganization)throw Error('当前文档不支持这项操作。');
   const operation=data.operation,reading=['asset-read','asset-download','export-download'].includes(operation);
   if((target.embedded||!target.doc.editable||target.doc.is_current_revision===false)&&!reading)throw Error('这份文档当前只可阅读。');
   const base='/api/device/work/documents/'+Number(target.doc.id);let response;
   if(operation==='asset-upload')response=await api(base+'/assets','POST',{content_model:'rich-document',file:data.file});
   else if(['asset-read','asset-download'].includes(operation)&&/^[a-f0-9]{64}$/.test(data.id||''))response=await api(base+'/assets/'+data.id);
   else if(operation==='templates-read')response=await api(base+'/templates');
   else if(operation==='template-read'&&/^[a-f0-9]{64}$/.test(data.id||''))response=await api(base+'/templates/'+data.id);
   else if(operation==='template-save')response=await api(base+'/templates','POST',{content_model:'rich-document',name:data.name,fragment:data.fragment});
   else if(operation==='export-download')response={download:true};
   else throw Error('不支持的文档操作。');
   if(response?.error)throw Error(response.error);
   if(account!==workspaceAccountCacheToken()||!frame.isConnected||state&&S.docReader!==state)return;
   if(operation==='asset-download'){const raw=atob(response.data.split(',')[1]),blob=new Blob([Uint8Array.from(raw,c=>c.charCodeAt(0))],{type:response.type});download(blob,response.name);response={download:true};}
   if(operation==='export-download'){if(data.document?.schema!=='runteams.rich-document/1')throw Error('导出内容不完整。');const blob=new Blob([JSON.stringify(data.document,null,2)],{type:'application/json'});if(blob.size>128*1024*1024)throw Error('导出内容过大，请单独下载附件。');download(blob,(data.name||target.doc.name)+'.json');}
   post(frame,'resource-result',{request_id:data.request_id,result:response});
  }catch(error){if(account===workspaceAccountCacheToken()&&frame.isConnected&&(!state||S.docReader===state))post(frame,'resource-result',{request_id:data.request_id,error:error.message||'操作未完成，请重试。'});}
 }

 function loaded(frame){if(readyFrames.has(frame))return;setTimeout(()=>{if(!frame.isConnected||readyFrames.has(frame))return;const label=frame.closest('.rich-frame-shell')?.querySelector('.rich-frame-loading');if(label){label.classList.add('is-error');label.setAttribute('role','alert');label.innerHTML='<span>内容界面暂时未能打开，已保存的文档仍保留。</span><button type="button" class="btn" onclick="RunTeamsRichDocuments.retry(this)">重试</button>';}},15000);}
 function retry(button){const shell=button.closest('.rich-frame-shell'),frame=shell?.querySelector('iframe');if(!frame)return;readyFrames.delete(frame);const label=shell.querySelector('.rich-frame-loading');label.classList.remove('is-error');label.removeAttribute('role');label.innerHTML=documentReaderSkeletonMarkup(true);frame.src=frame.src;}
 async function create(){
  if(S.activeOrganization)return;
  if(S._richDocumentCreating)return;S._richDocumentCreating=true;
  try{if(!await flushDocument())return;const doc=await api('/api/device/work/documents','POST',{name:'未命名文档',content_model:'rich-document',base_revision:0,document_key:'document-'+crypto.randomUUID(),document:{schema:'runteams.rich-document/1',blocks:[{id:crypto.randomUUID(),type:'paragraph',props:{},content:[],children:[]}],sources:{}}});if(doc.error)throw Error(doc.error);await openDocumentReader({...doc,rich_new_document:true});}
  catch(error){toast(error.message||'文档创建失败，请重试。','err');}finally{S._richDocumentCreating=false;}
 }
 window.addEventListener('message',event=>{
  const data=event.data;if(event.origin!==location.origin||data?.channel!==channel)return;
  const frame=currentFrame(data.token);if(!frame||event.source!==frame.contentWindow)return;
  const target=resolve(data.token);if(!target)return;
  if(data.type==='ready'){if(target.state)target.state.richProtocol=data.protocol===2?2:1;if(data.render_ack!==true){readyFrames.add(frame);frame.closest('.rich-frame-shell')?.querySelector('.rich-frame-loading')?.remove();}let document_url='';try{document_url=new URL(documentInternalLinkHref(target.state?.workspaceDocumentId||target.doc.id),location.origin).href;}catch{}post(frame,'open',{payload:{doc:{...target.doc,host_protocol:2,header_in_host:!target.embedded,outline_enabled:!target.embedded,resources_available:!S.activeOrganization,document_url,initial_block:target.state?.anchor||''},embedded:target.embedded,theme:theme()}});return;}
  if(data.type==='rendered'){readyFrames.add(frame);frame.closest('.rich-frame-shell')?.querySelector('.rich-frame-loading')?.remove();return;}
  if(data.type==='height'&&target.embedded){const height=Number(data.height);if(Number.isFinite(height))frame.style.height=Math.max(160,Math.min(15000,height))+'px';return;}
  if(data.type==='resource'){void resource(frame,target,data);return;}
  if(data.type==='link'){if(typeof data.href==='string')void openMarkdownLink(data.href);return;}
  if(target.embedded)return;
  const state=target.state;
  if(data.type==='outline'){updateOutline(state,data);return;}
  if(data.type==='dirty'){state.richDirty=data.dirty===true;state.saveStatus=state.richDirty?'error':'saved';}
  if(data.type==='save')save(frame,state,data);
  if(data.type==='flushed'){const wait=pending.get(state.richToken);if(wait&&wait.flush_id===data.flush_id){pending.delete(state.richToken);wait.done(data.ok===true&&!state.richDirty);}}
  if(data.type==='open-block'&&/^[1-9][0-9]{0,15}$/.test(String(data.document_id||''))&&/^[a-zA-Z0-9._:-]{1,128}$/.test(data.block_id||''))void openDocumentReaderById(Number(data.document_id),{anchor:data.block_id});
  if(data.type==='back')closeDocumentReader();
  if(data.type==='versions')toggleRichDocumentVersions();
 });
 new MutationObserver(()=>{for(const frame of document.querySelectorAll('iframe[data-rich-token]'))post(frame,'theme',{theme:theme()});}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
 window.addEventListener('beforeunload',event=>{if(S.docReader?.richDirty){event.preventDefault();event.returnValue='';}});
 window.addEventListener('runteams:business-scope-will-change',()=>{reports.clear();for(const item of pending.values())item.done(false);pending.clear();});
 window.RunTeamsRichDocuments=Object.freeze({supported,main,reportMarkup,flush,create,loaded,retry,exportCurrent,retrySave,toggleOutline,jumpOutline});
})();
