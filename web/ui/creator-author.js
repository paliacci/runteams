/* Trusted full-folder editor. Reuses the product resource tree and viewer. */
(function(){
'use strict';
let state=null,operationOwner=null,operationMarkup='',mountedPreview=null;
const scope=()=>workspaceAccountCacheToken();
const deviceScope=()=>S.localLibrary?JSON.stringify([S.localLibrary.library_id,S.localLibrary.generation]):S.account?.device_data_scope;
let sourceActions=null;
const extension=()=>sourceActions?.enabled()?sourceActions:null;
function attachSourceActions(create){if(sourceActions||typeof create!=='function')throw Error('Source actions already composed');sourceActions=create({current,valid,busy,repaint,localCall,closeHistory,openOperation,syncOperationDialog,buildLocal,sync});}
const sourceHeaders=s=>s.library?{'X-RunTeams-Library':s.library.library_id,'X-RunTeams-Library-Generation':s.library.generation}:{'X-RunTeams-Device-Scope':s.deviceScope||''};
const panel=()=>S.conversationPanel?.kind==='employee_design'&&S.conversationPanel.context?.creator_local_source_id?S.conversationPanel:null;
const current=()=>state&&valid(state)&&S.sel?.type==='creator-assets'&&S.sel.id===state.session?state:null;
const valid=s=>s===state&&s.scope===scope()&&s.deviceScope===deviceScope()&&(s.standalone||s.session===panel()?.id&&(!s.sourceId||s.sourceId===panel()?.context.creator_local_source_id));
const busy=s=>!!(s.loading||s.saving||s.pending||s.exporting||s.buildSending||extension()?.busy(s)||(panel()?.busy&&(!s.standalone||panel().context?.creator_local_source_id===s.localDraft?.id)));
const repaint=()=>{render();syncOperationDialog();};
const localPath='/api/creator-source/drafts';
async function localCall(s,suffix='',options={}){
 const response=await fetch(localPath+suffix,{...options,credentials:'same-origin',cache:'no-store',redirect:'error',headers:{...sourceHeaders(s),...options.headers}});
 const value=await response.json();if(!response.ok||value.error)throw Object.assign(Error(value.error||'本机源码未能读取'),{rejected:response.status>=400&&response.status<500,code:value.code,receipt:value.receipt});return value;
}
async function exportSource(){
 const s=current();if(!s?.localDraft||!s.revision||busy(s)||s.editing)return;
 const id=s.localDraft.id,revision=s.revision,request=new AbortController();s.exportRequest=request;s.exporting=true;s.error='';repaint();
 try{
  const response=await fetch(localPath+'/'+id+'/export?revision='+encodeURIComponent(revision),{signal:request.signal,credentials:'same-origin',cache:'no-store',redirect:'error',headers:sourceHeaders(s)});
  if(!response.ok){const value=await response.json();throw Error(value.error||'源码包未能导出，请重试。');}
  if(response.headers.get('Content-Type')!=='application/zip'||response.headers.get('X-RunTeams-Source-Revision')!==revision)throw Error('导出的源码版本未能核对，请刷新后重试。');
  const blob=await response.blob();if(!valid(s)||s.localDraft?.id!==id||s.revision!==revision)return;
  if(!blob.size||blob.size>33*1024*1024)throw Error('源码包无效，请保留当前源码后重试。');
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='runteams-source-'+id.slice(0,12)+'.zip';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
 }catch(e){if(valid(s)&&e.name!=='AbortError')s.error=e.message;}
 finally{if(valid(s)){s.exporting=false;s.exportRequest=null;repaint();}}
}

function validDraft(r){return r?.schema==='runteams.local-source-draft/1'&&r.scope==='device-source-draft'&&r.published===false&&r.cloud_verified===false&&/^[a-f0-9]{64}$/.test(r.id)&&r.source?.sha256===r.id&&Array.isArray(r.source.files)&&r.source.files.length<=500&&r.source.files.every(f=>typeof f.path==='string'&&typeof f.sha256==='string')&&typeof r.project?.name==='string'&&typeof r.project?.version==='string';}
function acceptLocal(s,r){if(!validDraft(r))throw Error('本机源码回执无效');extension()?.reset(s,r);if(s.buildPoll&&typeof clearTimeout==='function')clearTimeout(s.buildPoll);s.buildPoll=null;s.buildRequest=null;s.build=null;s.buildError='';s.localDraft=r;s.files=r.source.files;s.activeFile='';s.file=null;s.resourceFolders=[];s.error='';s.request=null;}

async function defaultSoulPath(s){
 const read=async path=>{
  const expected=s.files.find(file=>file.path===path);if(!expected)throw Error('员工资源入口不存在。');
  const file=await localCall(s,'/'+s.localDraft.id+'/file?path='+encodeURIComponent(path));
  if(!valid(s))throw Error('账户或员工已改变，请重新打开资源。');
  if(file.sha256!==expected.sha256)throw Error('文件已有更新，请重新打开资源后再查看。');
  return JSON.parse(file.content);
 };
 let employeePath=s.employeeSource;
 if(!employeePath){const project=await read('project.json');const employees=project.entrypoints?.employees;if(!Array.isArray(employees)||employees.length!==1)return '';employeePath=employees[0];}
 const employee=await read(employeePath);if(employee.schema==='runteams.pipeline-source/3')return employeePath;const path=employee.soul_file;
 if(typeof path!=='string'||!s.files.some(file=>file.path===path))throw Error('员工灵魂文件不存在。');
 return path;
}

async function openLocal(id){
 const s=current();if(!s||busy(s)||!/^[a-f0-9]{64}$/.test(id))return;
 const known=s.treeSource===id&&s.localDraft?.id===id;let directoryAccepted=false;
 if(!known){s.treeSource=null;s.files=[];s.activeFile='';s.file=null;s.fileError='';s.resourceFolders=[];s.resourceFocus='';}
 extension()?.beforeRead(s,known);
 s.loading=true;s.error='';repaint();
 try{const r=await localCall(s,'/'+id);const workspace=await localCall(s,'/'+id+'/workspace');if(valid(s)){if(r.id!==id)throw Error('员工源码已改变，请重新打开资源。');if(typeof workspace?.revision!=='string'||!workspace.revision||!Array.isArray(workspace.source?.files)||workspace.source.files.length>500||!workspace.source.files.every(file=>typeof file?.path==='string'&&typeof file.sha256==='string'))throw Error('员工资源目录回执无效，请重试。');const previous={path:s.activeFile,file:s.file,folders:s.resourceFolders||[],focus:s.resourceFocus},activeFile=known?previous.path:'';acceptLocal(s,r);s.revision=workspace.revision;s.files=workspace.source.files;directoryAccepted=true;if(!known)s.history=null;s.pendingAuthoring=workspace.pending_authoring||[];s.build=workspace.build||null;s.buildError='';scheduleBuild(s);
  if(known){s.resourceFolders=previous.folders.filter(path=>s.files.some(file=>file.path.startsWith(path+'/')));s.resourceFocus=s.files.some(file=>file.path===previous.focus||file.path.startsWith(previous.focus+'/'))?previous.focus:'';
   if(activeFile&&previous.file?.sha256===s.files.find(file=>file.path===activeFile)?.sha256){s.activeFile=activeFile;s.file=previous.file;}}
  try{const draft=JSON.parse(window.RunTeamsBusinessStorage?.getItem(draftKey(s))||'null');if(draft){s.editing=draft.editing;s.pending=draft.pending;s.buildRequest=draft.buildRequest;}}catch(e){}
  if(s.editing)s.activeFile=s.editing.path;else if(activeFile&&s.files.some(f=>f.path===activeFile))await select(activeFile,false,true);
  else{const path=await defaultSoulPath(s);if(valid(s)&&s.localDraft?.id===id&&s.revision===workspace.revision&&!s.activeFile&&!s.editing&&path)await select(path,false);}
  await readHistory(s);
  await extension()?.read(s,id);
 }}
 catch(e){if(valid(s))s.error=e.message;}
 finally{if(valid(s)){if(directoryAccepted&&current()===s)s.treeSource=id;s.loading=false;extension()?.afterRead(s);repaint();}}
}
// Open only real, validated SDK source. Missing source is an explicit error.
async function openEmployee(id,{onBack=null}={}){
 if(S.sel?.type==='core-pipeline-parameters'&&requestDetailWorkspaceLeave(()=>openEmployee(id,{onBack})))return;
 capture();
 id=Number(id);const local=RunTeamsEmployeeDirectory.sourceFor(id);if(!id||!local&&!employeeCanEdit(employeeSummary(id))||current()?.editing||current()&&busy(current()))return;
 const selection='employee:'+id;
 state={standalone:true,assetRecordId:id,employeeSource:local?.path,session:selection,scope:scope(),deviceScope:deviceScope(),library:S.localLibrary?{library_id:S.localLibrary.library_id,generation:S.localLibrary.generation}:null,files:[],resourceFolders:[],activeFile:'',file:null,error:'',loading:true,localSession:true,configurationReturn:onBack};
 const s=state;selectDetailWorkspace({type:'creator-assets',id:selection});repaint();
 if(local){extension()?.source(s,local);s.loading=false;return openLocal(local.id);}
 try{const result=await RunTeamsNativeAssets.authoring(id,draftRuntimeConfig());if(!valid(s))return;
  const c=result.session?.context;if(!c?.creator_local_source_id)throw Error('这名员工的资源暂时无法读取。');
  extension()?.source(s,{context:c});s.employeeSource=c.creator_employee_source;s.loading=false;await openLocal(c.creator_local_source_id);
 }catch(error){if(valid(s)){s.loading=false;s.error=error.message;repaint();}}
}
async function openSource(source,{onBack=null}={}){
 if(S.sel?.type==='core-pipeline-parameters'&&requestDetailWorkspaceLeave(()=>openSource(source,{onBack})))return;
 capture();
 if(!source||!/^[a-f0-9]{64}$/.test(source.id)||typeof source.path!=='string')throw Error('员工源码入口无效。');
 const session='source:'+source.id+':'+source.path;
 if(!state||state.session!==session||state.scope!==scope()||state.deviceScope!==deviceScope())state={standalone:true,session,sourceId:source.id,employeeSource:source.path,scope:scope(),deviceScope:deviceScope(),library:S.localLibrary?{library_id:S.localLibrary.library_id,generation:S.localLibrary.generation}:null,files:[],resourceFolders:[],activeFile:'',file:null,error:'',localSession:true};
 const s=state;
 extension()?.source(s,source);
 s.configurationReturn=onBack;
 selectDetailWorkspace({type:'creator-assets',id:session});
 if(!busy(s)&&!s.editing)return openLocal(source.id);
 repaint();
}
function leave(){closeHistory(false);}
function close(){if(!current())return;closeDetailWorkspace();}


const draftKey=s=>'runteams.creator.author.local.'+s.localDraft.id+(s.library?':'+s.library.generation:'');
function persist(s){if(!valid(s))return;try{if(s.editing||s.pending||s.buildRequest)window.RunTeamsBusinessStorage?.setItem(draftKey(s),JSON.stringify({editing:s.editing||null,pending:s.pending||null,buildRequest:s.buildRequest||null,revision:s.revision}));else window.RunTeamsBusinessStorage?.removeItem(draftKey(s));}catch(e){s.error='当前编辑仅保留在此页面，关闭前请保存或核对结果。';}}
function capture(){const s=current(),edit=document.getElementById('creator_asset_text');if(s?.editing&&edit){s.editing.content=edit.value;persist(s);}}
async function sync(keepError=false){
 const s=current();if(!s||s.loading||s.saving)return;
 if(s.assetRecordId&&!s.localDraft)return openEmployee(s.assetRecordId);
 if(!s.localDraft)return;
 const error=s.error;await openLocal(s.localDraft.id);
 if(keepError&&error&&valid(s)){s.error=error;repaint();}
}
async function open(){
 const p=panel();if(!p)return;
 if(current())return close();
 if(!state||state.session!==p.id||state.scope!==scope()||state.deviceScope!==deviceScope()||state.sourceId!==p.context.creator_local_source_id){
  state={session:p.id,sourceId:p.context.creator_local_source_id,localSession:!!p.context?.creator_local_source_id,employeeSource:p.context?.creator_employee_source,scope:scope(),deviceScope:deviceScope(),library:S.localLibrary?{library_id:S.localLibrary.library_id,generation:S.localLibrary.generation}:null,files:[],resourceFolders:[],activeFile:'',revision:null,error:'',file:null};
 }

 extension()?.source(state,{context:p.context});
 selectDetailWorkspace({type:'creator-assets',id:p.id});
 if(busy(state)||state.editing){repaint();return;}
 await openLocal(p.context.creator_local_source_id);
}
async function select(path,paint=true,keepTree=false){
 const s=current();if(!s||s.editing||!s.files.some(f=>f.path===path))return;


 const request={};s.request=request;const keepFile=keepTree&&s.activeFile===path&&s.file?.sha256===s.files.find(file=>file.path===path)?.sha256;s.activeFile=path;if(!keepFile)s.file=null;s.fileError='';if(!keepTree)skillsResourceRevealPath(s,path);if(paint)repaint();
 try{const r=await localCall(s,'/'+s.localDraft.id+'/file?path='+encodeURIComponent(path));if(!valid(s)||s.request!==request)return;
  const expected=s.files.find(f=>f.path===path);if(r.sha256!==expected?.sha256)throw Error('文件已有更新，请重新打开资源后再查看。');s.file=r;
 }catch(e){if(valid(s)&&s.request===request)s.fileError=e.message;}
 if(paint&&valid(s))repaint();
}
function edit(){const s=current();if(!s||busy(s)||s.file?.kind!=='text')return;s.editing={path:s.activeFile,content:s.file.content,newFile:false,base_revision:s.revision};if(s.localDraft)s.operationView='edit';persist(s);repaint();}
function add(){const s=current();if(!s||busy(s)||s.editing)return;s.editing={path:'',content:'',newFile:true,base_revision:s.revision};if(s.localDraft)s.operationView='edit';persist(s);repaint();}
function cancel(){const s=current();if(!s||s.saving||s.pending)return;s.editing=null;persist(s);repaint();}
function changed(value){const s=current();if(s?.editing&&!s.saving&&!s.pending){s.editing.content=value;persist(s);}}
function pathChanged(value){const s=current();if(s?.editing?.newFile){s.editing.path=value;persist(s);}}


async function commit(changes){
 const s=current();if(!s?.localDraft||busy(s))return;
 s.saving=true;s.error='';s.pending={action:'edit',base_revision:s.editing?.base_revision||s.revision,operation_key:crypto.randomUUID(),changes};persist(s);repaint();
 try{const {action,...body}=s.pending;const r=await localCall(s,'/'+s.localDraft.id+'/edit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(valid(s))accept(s,r);}
 catch(e){if(valid(s)){if(e.rejected){s.pending=null;s.error=e.message;persist(s);}else s.error='保存结果待核对，编辑内容已保留。';}}
 finally{if(valid(s)){s.saving=false;if(!s.pending)await sync(true);else repaint();}}
}
function accept(s,r){if(!r?.revision)throw Error('保存回执无效');extension()?.sourceSaved(s);s.revision=r.revision;s.source_sha256=r.source_sha256;s.pending=null;s.check=null;s.compilation=null;
 const path=s.editing?.path;s.editing=null;if(path)s.activeFile=path;s.file=null;persist(s);}
async function receipt(){
 const s=current();if(!s?.localDraft||!s.pending||s.saving)return;s.saving=true;s.error='';repaint();
 try{const r=await localCall(s,'/'+s.localDraft.id+'/receipt?operation_key='+encodeURIComponent(s.pending.operation_key));if(!valid(s))return;
  if(r.state!=='confirmed')throw Error('尚未找到保存结果，可以使用原内容重试保存。');accept(s,r.result);
 }catch(e){if(valid(s))s.error=e.message;}
 finally{if(valid(s)){s.saving=false;if(!s.pending)await sync(true);else repaint();}}
}
async function retryLocalSave(){const s=current();if(!s?.localDraft||!s.pending||s.saving)return;s.saving=true;s.error='';repaint();try{const {action,...body}=s.pending;const r=await localCall(s,'/'+s.localDraft.id+(action==='restore'?'/restore':'/edit'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(valid(s))accept(s,r);}catch(e){if(valid(s)){s.error=e.message;if(e.rejected){s.pending=null;persist(s);}}}finally{if(valid(s)){s.saving=false;if(!s.pending)await sync(true);else repaint();}}}
async function readHistory(s){
 if(!valid(s)||!s.localDraft)return;
 const request={};s.historyRequest=request;s.historyLoading=true;s.historyError='';
 try{
  const value=await localCall(s,'/'+s.localDraft.id+'/history');
  if(!valid(s)||s.historyRequest!==request)return;

  if(!Array.isArray(value.items)||typeof value.original_revision!=='string')throw Error('历史版本暂时无法读取');s.history=value;
 }catch(error){if(valid(s)&&s.historyRequest===request)s.historyError=error.message;}
 finally{if(valid(s)&&s.historyRequest===request)s.historyLoading=false;}
}
function hasHistory(s){return !!(s.history?.items?.length||s.historyError);}
async function history(){
 const s=current();if(!s||!s.localDraft||busy(s)||s.editing)return;
 if(s.historyOpen){closeHistory();return;}
 s.historyOpen=true;repaint();
 if(!s.history||s.historyError){await readHistory(s);if(valid(s))repaint();}
}
function closeHistory(focus=true){const s=current();if(!s)return;s.historyOpen=false;document.getElementById('creator_history_popover')?.remove();const trigger=document.getElementById('creator_history_trigger');trigger?.setAttribute('aria-expanded','false');if(focus)trigger?.focus();}
function historyRows(s){
 if(!s.history)return [];

 return [...s.history.items,{revision:s.history.original_revision,created_at:s.localDraft.created_at,source:s.localDraft.source,original:true}].map((item,index,all)=>{
  const previous=all[index+1],files=item.source?.files||[],before=new Map((previous?.source?.files||[]).map(f=>[f.path,f.sha256])),after=new Map(files.map(f=>[f.path,f.sha256]));
  const changes=previous?[...files.filter(f=>before.get(f.path)!==f.sha256).map(f=>(before.has(f.path)?'修改 ':'新增 ')+f.path),...Array.from(before.keys()).filter(p=>!after.has(p)).map(p=>'移除 '+p)]:[];
  const notes=item.update_notes||item.change_summary||item.summary||item.notes;
  const version=item.version||item.project?.version||(item.original?s.localDraft.project.version:`修订 ${all.length-index-1}`);
  return {...item,version:String(version),notes:typeof notes==='string'?notes:Array.isArray(notes)?notes.join('\n'):changes.length?changes.join('\n'):item.original?'导入的原始资源。':'未填写更新说明。'};
 });
}
function historyList(rows,actionFor,disabled=false){return rows.map((item,index)=>{
  const date=new Date(item.created_at),dateText=Number.isNaN(date.getTime())?'日期未记录':date.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
  return `<details class="creator-history-item"><summary><span class="creator-history-chevron" aria-hidden="true">${ICON('chev')}</span><span>${esc(item.version)}</span><time datetime="${esc(item.created_at||'')}">${esc(dateText)}</time></summary><div class="creator-history-notes"><div>更新说明</div><p>${esc(item.notes)}</p>${!!actionFor?.(item,index)?`<button type="button" class="btn ghost sm" onclick="${esc(actionFor(item,index))}" ${disabled?'disabled':''}>恢复此版本</button>`:''}</div></details>`;
 }).join('');}
function historyMarkup(s){
 if(!s.historyOpen)return '';
 const rows=historyRows(s),content=s.historyLoading?RunTeamsSkeletons.region('history'):s.historyError?`<p role="alert">${esc(s.historyError)}</p><button type="button" class="btn sm" onclick="RunTeamsCreatorAuthor.retryHistory()">重试</button>`:historyList(rows,(item,index)=>canRestoreHistory(s,item)?`RunTeamsCreatorAuthor.confirmRestore(${index})`:'',busy(s));
 return `<section id="creator_history_popover" class="creator-history-popover" role="dialog" aria-label="历史版本"><div class="creator-history-title">历史版本</div><div class="creator-history-list">${content||'<p class="creator-asset-note">还没有历史版本。</p>'}</div></section>`;
}
function retryHistory(){const s=current();if(s){s.historyOpen=false;return history();}}
function canRestoreHistory(s,item){return item.revision!==s.revision;}
function confirmRestore(index){const s=current(),item=s&&historyRows(s)[index];if(!item||busy(s)||s.editing||!canRestoreHistory(s,item))return;const baseline=s.revision;closeHistory(false);confirmModal(`恢复到 ${item.version}？`,extension()?.restoreMessage()||'将用此版本替换当前源码，现有历史版本仍会保留。',()=>{if(!valid(s)||current()!==s)return;if(s.revision!==baseline){s.error='资源已有新修改，请重新查看后再恢复。';repaint();return;}return restore(item.revision);});}
function editorMarkup(s){const e=s.editing;if(!e)return '';return `<div class="skills-file-edit"><div class="skills-file-edit-actions"><button class="btn pri sm" onclick="RunTeamsCreatorAuthor.save()" ${busy(s)?'disabled':''}>保存文件</button><button class="btn sm" onclick="RunTeamsCreatorAuthor.cancel()" ${s.saving||s.pending?'disabled':''}>返回预览</button></div>${e.newFile?`<label>文件路径<input aria-label="文件路径" value="${esc(e.path)}" oninput="RunTeamsCreatorAuthor.pathChanged(this.value)" ${busy(s)?'disabled':''}></label>`:''}<label class="skills-file-upload">上传资源<input type="file" aria-label="上传作品资源" onchange="RunTeamsCreatorAuthor.upload(this)" ${busy(s)?'disabled':''}></label><label class="skills-file-edit-label">文件内容<textarea id="creator_asset_text" aria-label="编辑作品文件" oninput="RunTeamsCreatorAuthor.changed(this.value)" ${busy(s)?'readonly':''}>${esc(e.content)}</textarea></label></div>`;}
function recoveryMarkup(s){return (s.pendingAuthoring||[]).map(item=>item.state==='running'?'<p role="status">Agent 正在修改这份源码。</p>':`<section><p>${esc(item.error||'恢复会保存为新修订，当前版本保留。')}</p><ul>${(item.changes||[]).map(c=>`<li>${esc(c.kind==='deleted'?'删除':c.kind==='added'?'新增':'修改')}：${esc(c.path)}</li>`).join('')||'<li>没有文件差异</li>'}</ul><button class="btn sm" onclick="RunTeamsCreatorAuthor.recoverAuthoring(${Number(item.session_id)})" ${busy(s)?'disabled':''}>恢复这些修改</button></section>`).join('');}
function resourceReceiptMarkup(s){return s.pending?`<p role="status">${s.saving?'正在保存资源…':'保存结果待核对，原内容仍保留。'}</p><button class="btn sm" onclick="RunTeamsCreatorAuthor.receipt()" ${s.saving?'disabled':''}>核对保存结果</button><button class="btn sm" onclick="RunTeamsCreatorAuthor.retryLocalSave()" ${s.saving?'disabled':''}>重试保存</button>`:'';}
function openOperation(kind,action){const s=current();if(!s)return;closeHistory(false);s.operationView=kind;syncOperationDialog();return action?.();}
function closeOperation(){const s=operationOwner;if(s?.editing&&current()===s)capture();if(s){s.operationView=null;extension()?.closeOperation(s);}operationOwner=null;operationMarkup='';if(document.querySelector?.('.creator-operation-dialog'))closeModal();}
function resourceActions(s){
 return `<div class="creator-asset-actions"><button class="btn sm" onclick="RunTeamsCreatorAuthor.edit()" ${busy(s)||s.file?.kind!=='text'?'disabled':''}>编辑文件</button><button class="btn sm" onclick="RunTeamsCreatorAuthor.add()" ${busy(s)?'disabled':''}>添加文件</button><button class="btn sm" onclick="RunTeamsCreatorAuthor.remove()" ${busy(s)||!s.activeFile?'disabled':''}>删除文件</button><button class="btn sm" onclick="RunTeamsCreatorAuthor.exportSource()" ${busy(s)?'disabled':''}>导出源码</button></div>`;
}
function syncOperationDialog(){
 if(typeof openDialog!=='function')return;
 const s=current();if(!s||!s.localDraft&&!s.localSession){if(operationOwner)closeOperation();return;}
 if(s.operationView==='edit'&&!s.editing&&!s.pending)s.operationView=null;
 const kind=s.operationView;if(!kind){if(operationOwner)closeOperation();if(s.error&&s.noticeError!==s.error){s.noticeError=s.error;if(typeof toast==='function')toast(s.error,'err');}return;}
 const extra=extension()?.dialog(s,kind),titles={build:'构建作品',edit:s.editing?.newFile?'添加文件':'编辑文件',recovery:'未完成的修改',resource:'资源操作'};
 const content=extra?extra.body:kind==='build'?buildSummary(s):kind==='edit'?editorMarkup(s)+resourceReceiptMarkup(s):kind==='recovery'?recoveryMarkup(s):resourceReceiptMarkup(s)||resourceActions(s);
 const body=content+(s.error?`<p role="alert">${esc(s.error)}</p>`:'');
 const signature=kind+body;if(operationOwner===s&&operationMarkup===signature&&document.querySelector?.('.creator-operation-dialog'))return;
 const opts={className:'creator-operation-dialog',title:extra?.title||titles[kind],body,closeAction:'RunTeamsCreatorAuthor.closeOperation()',attrs:`role="dialog" aria-label="${extra?.title||titles[kind]}"`};
 if(operationOwner===s&&document.querySelector?.('.creator-operation-dialog'))replaceDialog(opts);else openDialog(opts);operationOwner=s;operationMarkup=signature;
}
document.addEventListener?.('pointerdown',event=>{const s=current();if(s?.historyOpen&&!event.target.closest?.('#creator_history_popover,#creator_history_trigger'))closeHistory(false);});
document.addEventListener?.('keydown',event=>{if(event.key==='Escape'&&current()?.historyOpen){event.preventDefault();event.stopPropagation();closeHistory();}});
async function continueWithAgent(){const s=current();if(!s?.localDraft||busy(s)||s.editing)return;s.saving=true;s.error='';repaint();try{const r=await localCall(s,'/'+s.localDraft.id+'/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({runtime:draftRuntimeConfig()})});if(valid(s)){if(r.session?.storage_scope!=='device'||r.session?.context?.creator_local_source_id!==s.localDraft.id)throw Error('本机创作会话绑定无效');deviceChatRemember(r);s.saving=false;await openConversationSession(r.session.id,'employee_design');}}catch(e){if(valid(s))s.error=e.message;}finally{if(valid(s)){s.saving=false;repaint();}}}
async function recoverAuthoring(sessionId){const s=current();if(!s?.localDraft||busy(s)||s.editing||s.pending)return;s.saving=true;s.error='';repaint();try{await localCall(s,'/'+s.localDraft.id+'/recovery',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,base_revision:s.revision})});}catch(e){if(valid(s))s.error=e.message;}finally{if(valid(s)){s.saving=false;await sync(true);}}}
async function restore(revision){const s=current();if(!s?.history||busy(s)||s.editing||s.pending)return;s.saving=true;s.error='';s.pending={action:'restore',base_revision:s.revision,operation_key:crypto.randomUUID(),revision};persist(s);repaint();try{const {action,...body}=s.pending;const r=await localCall(s,'/'+s.localDraft.id+'/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(valid(s))accept(s,r);}catch(e){if(valid(s)){if(e.rejected){s.pending=null;persist(s);}s.error=e.message;}}finally{if(valid(s)){s.saving=false;if(!s.pending)await sync(true);else repaint();}}}
function save(){const s=current();if(!s?.editing)return;capture();return writeBytes(s,s.editing.path,new TextEncoder().encode(s.editing.content));}
function remove(){const s=current();if(!s?.activeFile||s.editing)return;return commit([{path:s.activeFile,content_base64:null}]);}
async function upload(input){const s=current(),file=input.files?.[0];if(!s||!file||busy(s))return;
 if(file.size>32*1024*1024){s.error='作品资源不能超过 32 MB。';repaint();return;}
 const bytes=new Uint8Array(await file.arrayBuffer());if(!valid(s))return;
 if(!s.editing)s.editing={path:s.activeFile,content:'',newFile:false};
 if(s.editing.newFile&&!s.editing.path)s.editing.path='assets/'+file.name;
 return writeBytes(s,s.editing.path,bytes);
}
async function writeBytes(s,path,bytes){
 if(!s.localDraft)return;
 if(bytes.length>2*1024*1024){s.error='单次编辑暂限 2 MB，原文件和当前编辑已保留。';repaint();return;}
 return commit([{path,content_base64:btoa(Array.from(bytes,b=>String.fromCharCode(b)).join(''))}]);
}


function scheduleBuild(s){
 if(s.build?.latest?.state!=='running'||s.buildPoll||typeof setTimeout!=='function')return;
 const id=s.localDraft?.id;s.buildPoll=setTimeout(()=>{s.buildPoll=null;if(current()===s&&s.localDraft?.id===id)void readBuild();},900);
}
async function readBuild(){
 const s=current();if(!s?.localDraft)return;const id=s.localDraft.id;
 try{const value=await localCall(s,'/'+id+'/build'+(s.buildRequest?'?operation_key='+encodeURIComponent(s.buildRequest.operation_key):''));if(valid(s)&&s.localDraft?.id===id){s.build=value;s.buildError='';if(s.buildRequest&&value.latest?.operation_key===s.buildRequest.operation_key){s.buildRequest=null;persist(s);}scheduleBuild(s);if(current()===s&&!s.editing)repaint();await extension()?.buildRead(s,id);}}
 catch(e){if(valid(s)&&s.localDraft?.id===id){s.buildError='构建结果暂时无法读取，请重新核对。';repaint();}}
}
async function buildLocal(){
 const s=current();if(!s?.localDraft||busy(s)||s.editing||s.build?.latest?.state==='running')return;
 const id=s.localDraft.id,body=s.buildRequest||{action:'start',base_revision:s.revision,operation_key:crypto.randomUUID()};
 s.buildRequest=body;s.buildSending=true;s.buildError='';persist(s);repaint();
 try{const result=await localCall(s,'/'+id+'/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(valid(s)&&s.localDraft?.id===id){s.buildRequest=null;persist(s);s.build={...s.build,latest:result};scheduleBuild(s);}}
 catch(e){if(valid(s)&&s.localDraft?.id===id){if(e.rejected){s.buildRequest=null;persist(s);}s.buildError=e.rejected?e.message:'构建请求结果待核对，请先刷新构建状态。';}}
 finally{if(valid(s)){s.buildSending=false;repaint();}}
}
async function cancelBuild(){
 const s=current(),key=s?.build?.latest?.operation_key;if(!s?.localDraft||!key||s.buildSending)return;
 s.buildSending=true;s.buildError='';repaint();
 try{await localCall(s,'/'+s.localDraft.id+'/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'cancel',operation_key:key})});await readBuild();}
 catch(e){if(valid(s))s.buildError=e.message;}
 finally{if(valid(s)){s.buildSending=false;repaint();}}
}
function buildSummary(s){
 const job=s.build?.latest,stale=job&&(job.current===false||job.revision!==s.revision);
 const label=s.buildRequest?'构建请求结果待核对':!job?'尚未构建':job.state==='running'?'正在构建已保存源码…':job.stale_reason==='toolchain_unavailable'?'构建工具暂不可用，源码与原构建结果已保留。':job.stale_reason==='toolchain_changed'?'构建工具已更新，请重新构建。':stale?'源码已更新，请重新构建':job.state==='succeeded'?'运行资源已准备好。':job.state==='cancelled'?'构建已取消，源码与上一份有效产物保留。':job.state==='interrupted'?'上次构建已中断，可以重新构建。':'构建未完成，请检查源码后重试。';
 return `<section class="creator-build-status" aria-label="平台构建"><p role="status">${label}</p>${job?.state==='running'?'<button class="btn sm" onclick="RunTeamsCreatorAuthor.cancelBuild()">取消构建</button>':''}${job?.diagnostic?`<details><summary>${stale?'上次构建问题':'查看构建问题'}</summary><pre>${esc(job.diagnostic)}</pre></details>`:''}${s.buildError?`<p role="alert">${esc(s.buildError)}</p>`:''}${s.buildError||s.buildRequest?'<button class="btn sm" onclick="RunTeamsCreatorAuthor.readBuild()">核对构建结果</button>':''}${job&&!['succeeded','cancelled'].includes(job.state)&&s.build?.valid?`<p class="creator-asset-note">${s.build.valid.current&&s.build.valid.revision===s.revision?'这份源码的上一份有效产物已保留。':String(s.build.valid.stale_reason||'').startsWith('toolchain_')?'上一份构建结果已保留，请以重新构建后的结果为准。':'上一份有效产物已保留，不代表当前源码。'}</p>`:''}</section>`;
}
function releasePreview(){
 if(mountedPreview)window.RunTeamsResourceViewer?.unmount?.(mountedPreview.host);
 mountedPreview=null;
}
function mount(s,path,file){let host=document.getElementById('creator_asset_preview');
 if(!host||current()!==s||s.activeFile!==path||s.file!==file)return;
 const previous=mountedPreview,sameFile=previous?.owner===s&&previous.source===s.localDraft?.id&&previous.path===path;
 const sameContent=sameFile&&['kind','sha256','content','data_url','size'].every(key=>previous.file[key]===file[key]);
 // drawer() also runs when only the sidebar/messages update. A mount is not a
 // paint operation: it unmounts React and loses mode, scroll and selection.
 if(sameContent){
  if(host!==previous.host&&typeof host.replaceWith==='function')host.replaceWith(previous.host);
  return;
 }
 const initialState=sameFile?window.RunTeamsResourceViewer?.captureFileState?.(previous.host):undefined;
 releasePreview();
 if(file.kind==='binary')host.textContent=`二进制资源，${file.size} 字节。`;
 else{
  if(!window.RunTeamsResourceViewer?.mountFile)return;
  window.RunTeamsResourceViewer.mountFile(host,{compact:true,path,file,...(initialState?{initialState}:{})});
 }
 mountedPreview={owner:s,source:s.localDraft?.id,path,file:{kind:file.kind,sha256:file.sha256,content:file.content,data_url:file.data_url,size:file.size},host};
}
function drawer(){
 const s=current();if(!s)return '';
 const header={toolbar:RunTeamsEmployeeDrawerHeader.markup('settings')+historyMarkup(s),intro:''};
 const tree=skillsResourceTreeMarkup(s.files,s,'creator',s.session);
 const known=!!s.treeSource&&s.treeSource===s.localDraft?.id;
 const recovery=s.error?`<p role="alert">${esc(s.error)} <button type="button" class="btn sm" onclick="RunTeamsCreatorAuthor.sync()">重试</button></p>`:'';
 let preview='';
 if(s.file){const path=s.activeFile,file=s.file;preview='<div id="creator_asset_preview"></div>';requestAnimationFrame(()=>mount(s,path,file));}
 else preview=s.fileError?'':s.error?'':s.activeFile||s.loading?RunTeamsSkeletons.region('creator-file'):'<p class="creator-asset-note">选择文件查看内容。</p>';
 if(s.fileError)preview=`<p role="alert">${esc(s.fileError)} <button type="button" class="btn sm" onclick="RunTeamsCreatorAuthor.select(${esc(JSON.stringify(s.activeFile))})">重试</button></p>`+preview;
 const body=`<div class="creator-asset-tree skills-resource-files">${recovery}${known?tree:s.loading?RunTeamsSkeletons.region('creator-files'):''}</div><div class="creator-asset-file">${preview}</div>`;
 return detailDrawerShell({className:'creator-author-drawer creator-resources-drawer',header,body,footer:'',bodyClass:'creator-author-body',fixedIntroClass:'',attrs:'aria-label="资源"'});
}
function decorateHeader(){
 const s=current();if(!s)return;
 const disabled=busy(s)||!!s.editing,actions=[];
 if(s.localDraft){
  // A cached action is presentation only; the handler always checks live facts.
  const actionsProvider=extension();
  if(!actionsProvider){
   actions.push({id:'build',label:s.build?.latest?.state==='running'?'查看构建':'构建',disabled:!!s.loading||!!s.editing||!!s.pending,onPress:()=>{if(current()===s)void openOperation('build',s.build?.latest?.state==='running'?readBuild:buildLocal);}});
   actions.push({id:'resources',label:'更多操作',popup:'dialog',disabled,onPress:()=>{if(current()===s)openOperation('resource');}});
  }
  if(hasHistory(s))actions.push({id:'history',label:'历史版本',platformId:'creator_history_trigger',popup:'dialog',expanded:!!s.historyOpen,disabled,onPress:()=>{if(current()===s)void history();}});
  if(actionsProvider)actions.push(...actionsProvider.header(s));
 }
 RunTeamsEmployeeDrawerHeader.mount('settings',s,{onCollapse:s.configurationReturn||close,
  collapseLabel:s.configurationReturn?'返回员工设置':'关闭详情',extras:{text:'资源',actions}});
}
for(const event of ['runteams:business-scope-will-change','runteams:business-scope-changed'])window.addEventListener(event,()=>{state?.exportRequest?.abort();if(operationOwner)closeOperation();releasePreview();state=null;});
window.RunTeamsCreatorAuthor={historyList,leave,decorateHeader,openSource,openEmployee,close,exportSource,current,open,sync,select,edit,add,cancel,changed,pathChanged,save,remove,upload,receipt,retryLocalSave,drawer,capture,openLocal,history,closeHistory,retryHistory,confirmRestore,attachSourceActions,openOperation,closeOperation,restore,continueWithAgent,recoverAuthoring,buildLocal,readBuild,cancelBuild};
})();
