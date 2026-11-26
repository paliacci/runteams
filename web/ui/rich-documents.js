/* Trusted local content renderer. Product APIs, identity and navigation stay in the host. */
(()=>{
 'use strict';
 const channel='runteams-rich-document/1',reports=new Map(),pending=new Map(),readyFrames=new WeakSet(),observedReportRoots=new WeakSet();
 const theme=()=>document.documentElement.dataset.theme==='dark'||!document.documentElement.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
 function supported(doc){return !doc?.data_view&&!/data-type=["']NodeAttributeView["']/.test(doc?.content||'')&&!doc?.task_input&&!doc?.work_artifact&&['rich-document','markdown','json'].includes(doc?.content_model);}
 function frame(token,embedded=false){return `<div class="rich-frame-shell"><div class="rich-frame-loading">${documentReaderSkeletonMarkup(true,false,embedded?'workRecordDetail.reportLoading':undefined)}</div><iframe onload="RunTeamsRichDocuments.loaded(this)" class="rich-document-frame${embedded?' rich-report-frame':''}" ${embedded?'':'id="rich_document_frame"'} data-rich-token="${esc(token)}" title="${embedded?'工作汇报':'文档内容'}" data-app-i18n-title="documentReader.${embedded?'reportFrame':'contentFrame'}" src="/rich-document/dist/index.html#${esc(token)}" referrerpolicy="no-referrer" allow="clipboard-write"></iframe></div>`;}
 function outlineMarkup(state){
  const collapsed=!!S.docOutlineCollapsed,label=collapsed?'展开大纲':'收起大纲',labelKey=collapsed?'documentReader.showOutline':'documentReader.hideOutline',outline=state.richOutline||{items:[],name:state.doc.name,active_id:''};
  return `<div class="rich-document-outline-list">${outline.items.map(item=>`<button type="button" class="doc-outline-link level-h${item.level}${outline.active_id===item.id?' on':''}" data-outline-id="${esc(item.id)}" title="${esc(item.text)}"${outline.active_id===item.id?' aria-current="location"':''} onclick="RunTeamsRichDocuments.jumpOutline(this.dataset.outlineId)">${esc(item.text)}</button>`).join('')}</div><div class="rich-document-outline-footer"><button type="button" class="detail-panel-collapse" title="${label}" aria-label="${label}" data-app-i18n-aria-label="${labelKey}" data-app-i18n-title="${labelKey}" aria-expanded="${!collapsed}" onclick="RunTeamsRichDocuments.toggleOutline()">${ICON(collapsed?'panel-left-open':'panel-left-close')}</button></div>`;
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
  const title=documentDisplayTitle(state.doc);
  return `<main class="environment-page doc-reader-page rich-document-page"><header class="doc-reader-bar" oncontextmenu="documentReaderMoreMenu(event)">${documentReaderBackMarkup(state.doc)}<div class="doc-reader-bar-copy"><span class="doc-reader-bar-title" id="doc_bar_title"${documentReaderTitleAttributes(title)}>${esc(title.title)}</span></div><div class="doc-reader-actions" id="doc_reader_actions">${documentReaderActionsMarkup(state.doc)}</div></header><div id="doc_reader_stale">${documentReaderStaleMarkup()}</div><div class="rich-document-layout"><aside class="rich-document-outline-slot${S.docOutlineCollapsed?' is-collapsed':''}" id="rich_document_outline_slot"><nav class="doc-reader-outline open rich-document-outline${S.docOutlineCollapsed?' is-collapsed':''}" id="rich_document_outline" aria-label="文档大纲" data-app-i18n-aria-label="documentReader.outline">${outlineMarkup(state)}</nav></aside><div class="rich-document-body">${frame(state.richToken)}</div><div class="doc-reader-versions-slot ${S.docVersionsOpen?'':'is-hidden'}" id="doc_reader_versions_slot"><nav class="doc-reader-versions" id="doc_reader_versions" aria-label="历史版本" data-app-i18n-aria-label="employeeHistory.title">${documentReaderVersionsMarkup()}</nav></div></div></main>`;
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
    if(response.device_page_ids)deviceChatRemember({device_page_ids:response.device_page_ids});
    if(response.id!==state.doc.id)state.revisions=[];
    state.doc={...state.doc,...response};state.text=JSON.stringify(data.document);if(state.richProtocol!==2)state.richDirty=false;state.saveStatus='saved';state.saveError='';
    const title=document.getElementById('doc_bar_title');
    if(title){
     const parts=documentDisplayTitle(state.doc);
     title.textContent=parts.title;
     if(parts.titleKey)title.dataset.appI18n=parts.titleKey;
     else title.removeAttribute('data-app-i18n');
     RunTeamsLocale.apply(title);
    }
    post(frame,'saved',{request_id:data.request_id,revision:response.revision});ok=true;loadDocumentRevisions(state.doc);
   }catch(error){if(S.docReader===state&&account===workspaceAccountCacheToken()){state.saveStatus='error';state.saveError=error.message||'保存失败，请重试。';post(frame,'saved',{request_id:data.request_id,error:state.saveError});}}
   finally{const wait=pending.get(state.richToken);if(wait&&(!ok||state.richProtocol!==2)){pending.delete(state.richToken);wait.done(ok);}}
   return ok;
  })();state.richSaving=run;try{return await run;}finally{if(state.richSaving===run)state.richSaving=null;}
 }
 function flush(state){
  const frame=currentFrame(state.richToken);
  // A live editor may have queued a dirty notification that the host hasn't received yet.
  const liveEditor=state.richProtocol===2&&state.doc.editable&&frame&&readyFrames.has(frame);
  if(!liveEditor&&!state.richDirty&&!state.richSaving)return Promise.resolve(true);
  if(!frame)return Promise.resolve(false);
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
 // Store already-encoded attachments without recompression in a UTF-8 ZIP32 archive.
 function zipFiles(files){
  const utf8=new TextEncoder(),parts=[],directory=[];
  const crcTable=Uint32Array.from({length:256},(_,i)=>{
   for(let bit=0;bit<8;bit++)i=(i>>>1)^((i&1)?0xedb88320:0);
   return i>>>0;
  });
  let offset=0,centralSize=0;
  for(const {name,bytes} of files){
   const path=utf8.encode(name);
   let crc=0xffffffff;
   for(const byte of bytes)crc=crcTable[(crc^byte)&255]^(crc>>>8);
   crc=(crc^0xffffffff)>>>0;
   const local=new DataView(new ArrayBuffer(30));
   local.setUint32(0,0x04034b50,true);
   local.setUint16(4,20,true);local.setUint16(6,0x800,true);local.setUint16(12,33,true);
   local.setUint32(14,crc,true);local.setUint32(18,bytes.length,true);
   local.setUint32(22,bytes.length,true);local.setUint16(26,path.length,true);
   const central=new DataView(new ArrayBuffer(46));
   central.setUint32(0,0x02014b50,true);central.setUint16(4,20,true);
   new Uint8Array(central.buffer,6,26).set(new Uint8Array(local.buffer,4,26));
   central.setUint32(42,offset,true);
   parts.push(local.buffer,path,bytes);directory.push(central.buffer,path);
   offset+=30+path.length+bytes.length;centralSize+=46+path.length;
  }
  const end=new DataView(new ArrayBuffer(22));
  end.setUint32(0,0x06054b50,true);end.setUint16(8,files.length,true);end.setUint16(10,files.length,true);
  end.setUint32(12,centralSize,true);end.setUint32(16,offset,true);
  return new Blob([...parts,...directory,end.buffer],{type:'application/zip'});
 }
 function portableDelivery(doc,filename){
  if(doc.schema!=='runteams.rich-document/1'||!Array.isArray(doc.blocks))throw Error('Invalid document');
  function clean(name){
   let component=String(name).replace(/[/\\:*?"<>|\u0000-\u001f\u007f]/g,'_').replace(/^[ .]+|[ .]+$/g,'');
   if(component.length>160){
    const dot=component.lastIndexOf('.');
    const extension=dot>0&&component.length-dot<160?component.slice(dot):'';
    component=component.slice(0,160-extension.length).replace(/[\uD800-\uDBFF]$/,'').replace(/[ .]+$/,'')+extension;
   }
   if(!component)return 'document';
   const stem=component.split('.',1)[0].trimEnd();
   return /^(?:con|prn|aux|nul|conin\$|conout\$|(?:com|lpt)[1-9¹²³])$/i.test(stem)?'_'+component:component;
  }
  const title=clean(filename.replace(/\.json$/i,'').replace(/\.md$/i,''));
  const files=new Map(),utf8=new TextEncoder();
  const ref=p=>`[${p.label||p.blockId}](runteams://document/${p.documentId}#${p.blockId})`;
  function inline(value){
   if(typeof value==='string')return value;
   if(Array.isArray(value))return value.map(inline).join('');
   if(value?.type==='blockReference')return ref(value.props);
   const text=value?.text??(value?.content?inline(value.content):'');
   if(value?.href)return `[${text}](<${value.href}>)`;
   return value?.styles?.code?'`'+text+'`':text;
  }
  function table(rows){
   if(!rows.length)return '';
   const line=r=>'| '+r.map(v=>String(v??'').replaceAll('|','\\|').replaceAll('\n','<br>')).join(' | ')+' |';
   return [line(rows[0]),line(rows[0].map(()=>'---')),...rows.slice(1).map(line)].join('\n');
  }
  function fenced(text,language=''){
   let width=3;for(const match of text.matchAll(/`+/g))width=Math.max(width,match[0].length+1);
   const ticks='`'.repeat(width);
   return ticks+language+'\n'+text+'\n'+ticks;
  }
  function blockText(b){
   const p=b.props||{},text=inline(b.content),kind=b.type;
   switch(kind){
    case 'markdown':return p.text;
    case 'heading':return '#'.repeat(Math.max(1,Math.min(6,Number(p.level)||1)))+' '+text;
    case 'bulletListItem':return '- '+text;
    case 'numberedListItem':return '1. '+text;
    case 'checkListItem':return (p.checked?'- [x] ':'- [ ] ')+text;
    case 'quote':return text.replace(/^/gm,'> ');
    case 'codeBlock':return fenced(text,p.language);
    case 'table':return table((b.content?.rows||[]).map(row=>row.cells.map(inline)));
    case 'divider':return '---';
    case 'reference':return ref(p);
    case 'math':return '$$\n'+(p.formula||'')+'\n$$';
    case 'metric':return [p.label,p.value].join(' ');
    case 'barChart':case 'dataTable':case 'jsonData':{
     const data=p.data?JSON.parse(p.data):doc.sources[p.source].data;
     const tabular=p.data&&data.columns&&data.rows&&!data.invalidCells?.length;
     const body=tabular?table([data.columns.map(c=>c.name),...data.rows.map(row=>data.columns.map(c=>row[c.id]))]):fenced(JSON.stringify(data,null,2),'json');
     return [p.title,body].filter(Boolean).join('\n\n');
    }
    case 'file':case 'video':case 'image':{
     if(!p.assetId)return p.name||'';
     if(!/^[a-f0-9]{64}$/.test(p.assetId))throw Error('Invalid attachment');
     const file=doc.assets?.[p.assetId];
     if(!file)throw Error('Missing attachment');
     const name='assets/'+p.assetId+'/'+clean(file.name);
     if(!files.has(name)){
      const data=String(file.data),i=data.indexOf(';base64,');
      if(!data.startsWith('data:')||i<0)throw Error('Invalid attachment');
      const binary=atob(data.slice(i+8)),bytes=new Uint8Array(binary.length);
      for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
      files.set(name,{name,bytes});
     }
     const label=(p.name||file.name).replace(/[\[\]\\]/g,'\\$&');
     return (kind==='image'?'!':'')+`[${label}](${name.split('/').map(encodeURIComponent).join('/')})`;
    }
    default:return text;
   }
  }
  function markdown(blocks){
   return blocks.map(b=>{
    let children=markdown(b.children||[]);
    if(children&&['bulletListItem','numberedListItem','checkListItem'].includes(b.type))children=children.replace(/^/gm,'   ');
    return [blockText(b),children].filter(Boolean).join('\n\n');
   }).filter(Boolean).join('\n\n');
  }
  const body=markdown(doc.blocks),name=title+'.md';
  if(!files.size)return {blob:new Blob([body],{type:'text/markdown;charset=utf-8'}),name};
  return {blob:zipFiles([{name,bytes:utf8.encode(body)},...files.values()]),name:title+'.zip'};
 }
 async function downloadSaved(path,{handoff=false}={}){
  const scope=documentsBinding();
  try{
   const response=await fetch(path,{headers:RunTeamsHost.session.headers(S),redirect:'error'});
   const filename=response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
   if(!response.ok||!filename)throw Error();
   const blob=await response.blob();
   const name=decodeURIComponent(filename);
   if(handoff&&blob.size>128*1024*1024)throw Error('Export too large');
   const file=handoff&&response.headers.get('Content-Type')?.includes('application/json')?
    portableDelivery(JSON.parse(await blob.text()),name):{blob,name};
   if(scope!==documentsBinding())return false;
   download(file.blob,file.name);
   return true;
  }catch{
   if(scope===documentsBinding())toast('无法导出文件。请重试。','err','fileBrowser.exportFailed');
   return false;
  }
 }
 function downloadDelivery(id){
  return downloadSaved(deviceWorkPath(`/api/core/documents/${id}/download`),{handoff:true});
 }
 function exportSaved(id){return downloadSaved(`/api/device/work/documents/${id}/download`);}
 function exportSelection(ids){return downloadSaved('/api/device/work/documents/export?'+new URLSearchParams({ids:ids.join(',')}));}
 function retrySave(){editorAction('retry-save');}
 async function resource(frame,target,data){
  const account=workspaceAccountCacheToken(),state=target.state;
  try{
   if(!/^[a-zA-Z0-9-]{1,80}$/.test(data.request_id||'')||target.doc.content_model!=='rich-document'||RunTeamsHost.session.workspace(S))throw Error('当前文档不支持这项操作。');
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
   if(operation==='export-download'){if(data.document?.schema!=='runteams.rich-document/1')throw Error('导出内容不完整。');const blob=new Blob([JSON.stringify(data.document,null,2)],{type:'application/json'});if(blob.size>128*1024*1024)throw Object.assign(Error('导出内容过大，请单独下载附件。'),{code:'export-too-large'});download(blob,(data.name||target.doc.name)+'.json');}
   post(frame,'resource-result',{request_id:data.request_id,result:response});
  }catch(error){if(account===workspaceAccountCacheToken()&&frame.isConnected&&(!state||S.docReader===state))post(frame,'resource-result',{request_id:data.request_id,error:error.message||'操作未完成，请重试。',code:error.code});}
 }

 function loaded(frame){if(readyFrames.has(frame))return;setTimeout(()=>{if(!frame.isConnected||readyFrames.has(frame))return;const label=frame.closest('.rich-frame-shell')?.querySelector('.rich-frame-loading');if(label){label.classList.add('is-error');label.setAttribute('role','alert');label.innerHTML='<span data-app-i18n="documentReader.editorLoadFailed">无法打开编辑器。已保存的内容仍在。</span><button type="button" class="btn" data-app-i18n="employeeHistory.retry" onclick="RunTeamsRichDocuments.retry(this)">重试</button>';}},15000);}
 function retry(button){const shell=button.closest('.rich-frame-shell'),frame=shell?.querySelector('iframe');if(!frame)return;readyFrames.delete(frame);const label=shell.querySelector('.rich-frame-loading');label.classList.remove('is-error');label.removeAttribute('role');label.innerHTML=documentReaderSkeletonMarkup(true,false,frame.classList.contains('rich-report-frame')?'workRecordDetail.reportLoading':undefined);frame.src=frame.src;}
 let creation=null;
 function createMenuItem(folder){
  const pending=creation?.account===workspaceAccountCacheToken()?creation:null;
  const [labelKey,label]=pending?.busy?['documentList.creating','正在创建文档…']:
    pending?.payload?['documentList.retryCreate','核对并打开文档']:['documentList.new','新建文档'];
  return {labelKey,label,icon:'plus',disabled:!!pending?.busy,fn:()=>create(folder)};
 }
 async function create(folder=S.docsFolder){
  if(RunTeamsHost.session.workspace(S)||creation?.busy)return;
  const account=workspaceAccountCacheToken(),source=S.docReader,surface=S.surface,url=location.href,move=activeDocsMove();
  if(creation?.account!==account)creation={account,payload:null,busy:false};
  const operation=creation,current=()=>creation===operation&&workspaceAccountCacheToken()===account;
  const samePage=()=>S.docReader===source&&S.surface===surface&&location.href===url&&
    activeDocsMove()===move&&(!move||move.folder===folder);
  operation.busy=true;
  try{
   if(!await flushDocument()||!current()||!samePage())return;
   operation.payload||={
    name:RunTeamsLocale.t('documentList.untitled',{},'未命名文档'),content_model:'rich-document',base_revision:0,
    ...(folder?{folder}:{}),
    document_key:'document-'+crypto.randomUUID(),
    document:{schema:'runteams.rich-document/1',blocks:[{id:crypto.randomUUID(),type:'paragraph',props:{},content:[],children:[]}],sources:{}}
   };
   let doc;
   try{
    doc=await api('/api/device/work/documents','POST',operation.payload);
    if(doc?.error)throw Object.assign(Error(doc.error),{status:doc.status,code:doc.code});
    if(!Number.isSafeInteger(doc?.id)||doc.id<1||doc.document_key!==operation.payload.document_key)throw Error('Invalid document receipt');
   }catch(error){
    if(!current())return;
    const rejected=error.status>=400&&error.status<500&&![408,409].includes(error.status)&&error.code!=='mutation_outcome_unknown';
    if(rejected)operation.payload=null;
    if(samePage()){
     if(rejected)toast('无法创建文档。请重试。','err','documentList.createFailed');
     else toast('未能确认文档是否已创建。请选择「核对并打开文档」。','err','documentList.createUnconfirmed');
    }
    return;
   }
   if(!current())return;
   operation.payload=null;
   if(!samePage())return;
   deviceChatRemember(doc);
   try{if(await openDocumentReader({...doc,rich_new_document:true}))return;}catch{}
   if(current()&&samePage())toast('文档已创建，但无法打开。请从文档列表打开。','err','documentList.createdOpenFailed');
  }catch{
   if(current()&&samePage())toast('未能确认当前文档已保存。','err','documentReader.leavingUnconfirmed');
  }finally{
   if(current()){operation.busy=false;if(!operation.payload)creation=null;}
  }
 }
 function observeReportSize(frame){
  const root=frame.contentDocument?.getElementById('root');
  if(!root||observedReportRoots.has(root))return;
  const resize=()=>{
   if(!frame.isConnected||!root.isConnected){observer.disconnect();return;}
   const height=root.getBoundingClientRect().height;
   if(!height)return;
   // The intrinsic height includes fractional pixels that scrollHeight rounds away.
   const fitted=Math.max(160,Math.ceil(height),root.scrollHeight+1)+'px';
   if(frame.style.height!==fitted)frame.style.height=fitted;
  };
  const observer=new frame.contentWindow.ResizeObserver(resize);
  observedReportRoots.add(root);
  observer.observe(root);
  resize();
 }
 window.addEventListener('message',event=>{
  const data=event.data;if(event.origin!==location.origin||data?.channel!==channel)return;
  const frame=currentFrame(data.token);if(!frame||event.source!==frame.contentWindow)return;
  const target=resolve(data.token);if(!target)return;
  if(data.type==='ready'){if(target.state)target.state.richProtocol=data.protocol===2?2:1;if(data.render_ack!==true){readyFrames.add(frame);frame.closest('.rich-frame-shell')?.querySelector('.rich-frame-loading')?.remove();}let document_url='';try{document_url=new URL(documentInternalLinkHref(target.state?.workspaceDocumentId||target.doc.id),location.origin).href;}catch{}post(frame,'open',{payload:{doc:{...target.doc,host_protocol:2,header_in_host:!target.embedded,outline_enabled:!target.embedded,resources_available:!RunTeamsHost.session.workspace(S),document_url,initial_block:target.state?.anchor||''},embedded:target.embedded,theme:theme(),language:RunTeamsLocale.language}});return;}
  if(data.type==='rendered'){
   readyFrames.add(frame);
   frame.closest('.rich-frame-shell')?.querySelector('.rich-frame-loading')?.remove();
   if(target.embedded)observeReportSize(frame);
   return;
  }
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
 RunTeamsLocale.onChange(({language})=>{
  for(const frame of document.querySelectorAll('iframe[data-rich-token]'))if(resolve(frame.dataset.richToken))post(frame,'language',{language});
 });
 window.addEventListener('beforeunload',event=>{if(S.docReader?.richDirty){event.preventDefault();event.returnValue='';}});
 window.addEventListener('runteams:business-scope-will-change',()=>{creation=null;syncCreateButton();reports.clear();for(const item of pending.values())item.done(false);pending.clear();});
 window.RunTeamsRichDocuments=Object.freeze({supported,main,reportMarkup,flush,create,createMenuItem,loaded,retry,exportCurrent,exportSaved,downloadDelivery,downloadSaved,exportSelection,retrySave,toggleOutline,jumpOutline});
})();

function documentReaderTitleAttributes(parts,tooltip=false){
  return parts.titleKey?` data-app-i18n="${parts.titleKey}"${tooltip?` data-app-i18n-title="${parts.titleKey}"`:""}`:"";
}

function documentDisplayTitle(doc){
  const file=doc?.task_input||doc?.work_artifact;
  const title=file?documentPreviewFilename(doc):doc?.name;
  return {title:title||(file?'未命名文件':'未命名文档'),titleKey:title?'':file?'workRecordDetail.untitledFile':'documentList.untitled'};
}

function documentReaderBackMarkup(doc){
  const returnsToSource=!!(doc.work_return_url||doc.task_input_return_url);
  const label=returnsToSource?"返回":"返回文档列表";
  const labelKey=returnsToSource?"documentReader.backToSource":"documentReader.back";
  return `<button type="button" class="doc-reader-back" aria-label="${label}" data-app-i18n-aria-label="${labelKey}" onclick="closeDocumentReader()">${ICON("chev")}<span data-app-i18n="${returnsToSource?labelKey:"documentList.title"}">${returnsToSource?"返回":"文档"}</span></button>`;
}

function documentReaderSkeletonMarkup(title=false,file=false,labelKey=file?'workRecordDetail.loading':'documentReader.opening'){
  const label=window.RunTeamsLocale?.t(labelKey,{},file?'正在读取文件…':'正在打开文档')??'正在加载…';
  return `<div class="doc-reader-skeleton" role="status" aria-label="${esc(label)}" data-app-i18n-aria-label="${labelKey}" aria-busy="true">${title?'<span class="skeleton-block doc-skeleton-title" aria-hidden="true"></span>':""}<div class="doc-skeleton-section" aria-hidden="true"><span class="skeleton-block"></span><span class="skeleton-block"></span><span class="skeleton-block short"></span></div><div class="doc-skeleton-section" aria-hidden="true"><span class="skeleton-block heading"></span><span class="skeleton-block"></span><span class="skeleton-block"></span><span class="skeleton-block short"></span></div><div class="doc-skeleton-section" aria-hidden="true"><span class="skeleton-block"></span><span class="skeleton-block short"></span></div></div>`;
}

function documentPaperHeadMarkup(){
  const state=S.docReader;
  if(!state)return "";
  const doc=state.doc,parts=documentTitleParts();
  if(state.status==="loading"||docKind(doc)==="markdown")return `<h1 id="doc_paper_title" title="${esc(parts.title)}"${documentReaderTitleAttributes(parts,true)}>${esc(parts.title)}</h1>`;
  const employee=RunTeamsEmployeeDirectory.assets().find(item=>Number(item.id)===Number(doc.employee_id));
  const edited=documentReaderRevisions().slice(-1)[0]?.created_at||doc.created_at;
  const filename=String(doc.path||doc.name||"").trim(),extension=docSuffix(doc).replace(/^\./,"").toUpperCase();
  const kindKey="fileBrowser.kind."+docKind(doc),formatLabel=extension||RunTeamsLocale.t(kindKey,{},docKindLabel(doc));
  const modeKey=doc.editable?"editable":"readOnly",mode=doc.editable?"可编辑":"只读";
  const typeChip=`<span class="doc-paper-kind"${filename?` data-app-i18n-title="fileBrowser.${modeKey}Format" data-app-i18n-vars="${esc(JSON.stringify({filename}))}" title="${esc(filename)}"`:''}><span${extension?'':` data-app-i18n="${kindKey}"`}>${esc(formatLabel)}</span> <span data-app-i18n="fileBrowser.${modeKey}">${mode}</span></span>`;
  const lineage=Number(doc.workflow_id)&&doc.task_title
    ?`<i aria-hidden="true"></i><button type="button" class="doc-paper-run" title="打开运行记录" data-app-i18n-title="fileBrowser.openRun" data-app-i18n="fileBrowser.fromTask" data-app-i18n-vars="${esc(JSON.stringify({name:doc.task_title}))}" onclick="documentReaderOpenRun()">来自 ${esc(doc.task_title)}</button>`:"";
  return `<h1 id="doc_paper_title" title="${esc(parts.title)}"${documentReaderTitleAttributes(parts,true)}>${esc(parts.title)}</h1><div class="doc-paper-byline"><span class="doc-paper-author">${workerAvatarMarkup(employee||{})}<b>${documentVersionAuthor(false,doc)}</b></span><i aria-hidden="true"></i>${typeChip}<i aria-hidden="true"></i><span class="doc-paper-facts"><span data-app-i18n="fileBrowser.lastEdited">最后编辑</span> <span data-document-date="${esc(edited||"")}">${esc(docsTime(edited))}</span></span>${lineage}</div>`;
}

function documentReaderMoreMenu(event){
  event.preventDefault();event.stopPropagation();
  const doc=S.docReader?.doc;
  if(!doc||doc.work_artifact)return;
  const rich=!!S.docReader?.richToken;
  const items=[{label:"历史版本",labelKey:"employeeHistory.title",icon:"clock",selected:!!S.docVersionsOpen,fn:()=>rich?toggleRichDocumentVersions():toggleDocumentVersions()},
               {label:"导出",labelKey:"documentReader.export",icon:"download",fn:()=>rich&&doc.content_model==='rich-document'?RunTeamsRichDocuments.exportCurrent():exportCoreArtifact(S.docReader?.doc)}];
  if(doc.source!=="pipeline_task_report")items.push({label:"移到垃圾箱",labelKey:"documentList.trash",icon:"trash",fn:()=>trashDocumentFromReader()});
  if(S.docReader?.saveStatus==="error"&&(rich||docKind(doc)==='table'))items.push({divider:true},{label:"重试保存",labelKey:"employeeSettings.retrySave",icon:"refresh",fn:()=>rich?RunTeamsRichDocuments.retrySave():retryDocumentTableSave()});
  openMenu(event.currentTarget,items,{variant:"compactSelect",align:"right",...(event.type==="contextmenu"?{at:{x:event.clientX,y:event.clientY},align:"left"}:{})});
}
