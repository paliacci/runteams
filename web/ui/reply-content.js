/* Inline reply components: bounded data only, never HTML, scripts or remote URLs. */
window.RunTeamsReplyContent=(()=>{
 'use strict';
 const records=new Map(),mounted=new Map();let serial=0,scheduled=false,bundlePromise;
 const safe=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
 function validate(value){
  if(!value||value.version!==1||!['table','chart','explorer'].includes(value.type))throw Error('Unsupported content');
  if(typeof value.title!=='string'||!value.title.trim()||value.title.length>120)throw Error('Missing title');
  if(!Array.isArray(value.columns)||!value.columns.length||value.columns.length>12||!Array.isArray(value.rows)||value.rows.length>500)throw Error('Table limits');
  const keys=new Set();for(const col of value.columns){if(!col||typeof col.key!=='string'||!/^[a-zA-Z][\w-]{0,49}$/.test(col.key)||['constructor','prototype','__proto__'].includes(col.key)||keys.has(col.key)||typeof col.label!=='string'||!col.label||col.label.length>80||!['text','number',undefined].includes(col.format))throw Error('Invalid column');keys.add(col.key);}
  for(const row of value.rows){if(!row||typeof row!=='object'||Array.isArray(row))throw Error('Invalid row');for(const [key,cell]of Object.entries(row)){if(!keys.has(key)||!(cell===null||['string','number','boolean'].includes(typeof cell))||typeof cell==='string'&&cell.length>2000||typeof cell==='number'&&!Number.isFinite(cell))throw Error('Invalid cell');}for(const col of value.columns)if(col.format==='number'&&row[col.key]!=null&&typeof row[col.key]!=='number')throw Error('Numeric column');}
  if(value.caption!=null&&(typeof value.caption!=='string'||value.caption.length>500))throw Error('Invalid caption');
  if(value.type==='chart'&&(!keys.has(value.x)||!Array.isArray(value.metrics)||!value.metrics.length||value.metrics.length>4||value.metrics.some(key=>!value.columns.some(col=>col.key===key&&col.format==='number'))))throw Error('Chart fields');
  if(value.type==='explorer'&&(!keys.has(value.category)||!value.columns.some(col=>col.key===value.threshold&&col.format==='number')))throw Error('Explorer fields');
  return value;
 }
 // Scan all code fences so examples nested in longer fences remain ordinary code.
 function split(text,streaming=false){
  if(text.length>1000000)return [{type:'text',text}];
  const lines=text.match(/[^\n]*\n|[^\n]+$/g)||[],parts=[];let ordinary='',fence=null,block='';
  const flush=()=>{if(ordinary){parts.push({type:'text',text:ordinary});ordinary='';}};
  for(const line of lines){
   if(!fence){const match=line.match(/^ {0,3}(`{3,}|~{3,})([^\n]*)\n?$/);if(match){fence={char:match[1][0],length:match[1].length,rich:match[2].trim()==='runteams-view'};block=line;}else ordinary+=line;continue;}
   block+=line;const close=line.trim();if(close.length>=fence.length&&[...close].every(c=>c===fence.char)){
    if(fence.rich&&parts.filter(p=>p.type==='view').length<12){try{if(block.length>100000)throw Error();const json=block.slice(block.indexOf('\n')+1,block.lastIndexOf(line));const data=validate(JSON.parse(json));flush();parts.push({type:'view',data,raw:block});}catch{ordinary+=block;}}else ordinary+=block;
    fence=null;block='';
   }
  }
  if(fence?.rich&&streaming){flush();parts.push({type:'loading'});}else ordinary+=block;flush();return parts;
 }
 function markup(text,context,markdown){
  const parts=split(String(text),context.streaming);let index=0;
  return parts.map(part=>{
   if(part.type==='text')return `<div class="cmessage-markdown">${markdown(part.text)}</div>`;
   if(part.type==='loading')return '<div class="reply-content-loading" role="status">正在整理数据…</div>';
   const key=context.key+':'+index++,signature=JSON.stringify(part.data);let record=records.get(key);
   if(!record||record.signature!==signature){record={token:'reply-view-'+(++serial),data:part.data,signature};records.set(key,record);}
   queue();return `<div class="reply-content-slot" data-reply-view="${record.token}" aria-label="${safe(part.data.title)}"><p role="status">正在显示${safe(part.data.type==='table'?'表格':part.data.type==='chart'?'图表':'交互内容')}…</p></div>`;
  }).join('');
 }
 function plainText(text){return split(String(text)).map(part=>part.type==='text'?part.text:part.type==='view'?part.data.title+'\n'+[part.data.columns.map(c=>c.label).join('\t'),...part.data.rows.map(row=>part.data.columns.map(c=>row[c.key]??'—').join('\t'))].join('\n'):'').join('\n');}
 async function load(){
  if(!bundlePromise)bundlePromise=(async()=>{
   const bundle=window.RunTeamsReplyBundle;if(!bundle)throw Error('Missing renderer');
   for(const href of bundle.css){if(!document.querySelector(`link[data-reply-style="${href}"]`)){const link=document.createElement('link');link.rel='stylesheet';link.href=href;link.dataset.replyStyle=href;document.head.appendChild(link);}}
   return import(bundle.entry);
  })().catch(error=>{bundlePromise=null;throw error;});return bundlePromise;
 }
 function queue(){if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;void scan();});}
 async function scan(){
  const slots=[...document.querySelectorAll('[data-reply-view]')].filter(node=>!node.dataset.replyMounted&&!node.dataset.replyLoading);
  if(!slots.length)return;
  slots.forEach(node=>node.dataset.replyLoading='true');
  try{
   const renderer=await load();
   for(const node of slots){if(!node.isConnected)continue;const token=node.dataset.replyView,record=[...records.values()].find(r=>r.token===token);if(!record)continue;
    const old=mounted.get(token);
    if(old){if(old.node!==node)node.replaceWith(old.node);continue;}
    node.textContent='';node.dataset.replyMounted='true';const root=renderer.mount(node,record.data);mounted.set(token,{node,root});
   }
   // Retain limited detached roots for host re-renders. No persistent browser storage.
   for(const [token,item]of mounted){if(mounted.size<=80)break;if(!item.node.isConnected){item.root.unmount();mounted.delete(token);}}
   const activeTokens=new Set([...document.querySelectorAll('[data-reply-view]')].map(n=>n.dataset.replyView));
   for(const [key,record]of records)if(!mounted.has(record.token)&&!activeTokens.has(record.token))records.delete(key);
  }catch{
   for(const node of slots){if(!node.isConnected)continue;const record=[...records.values()].find(r=>r.token===node.dataset.replyView);node.innerHTML='<p>内容暂时无法显示。</p><button type="button" data-reply-retry>重试</button>'+(record?`<details><summary>查看数据</summary><pre>${safe(plainText('```runteams-view\n'+record.signature+'\n```'))}</pre></details>`:'');delete node.dataset.replyLoading;}
  }
 }
 if(typeof MutationObserver!=='undefined'&&typeof document!=='undefined'){
  const start=()=>{new MutationObserver(changes=>{if(changes.some(c=>[...c.addedNodes].some(n=>n.nodeType===1&&(n.matches?.('[data-reply-view]')||n.querySelector?.('[data-reply-view]')))))queue();}).observe(document.body,{childList:true,subtree:true});document.addEventListener('click',event=>{if(event.target.closest('[data-reply-retry]'))queue();});};
  if(document.body)start();else document.addEventListener('DOMContentLoaded',start,{once:true});
 }
 return {markup,plainText,split,validate,scan};
})();
