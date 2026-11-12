/* Static page chrome is available before account or business requests. */
(function(global){
'use strict';
const values=Object.create(null);let change=null;
const esc=value=>String(value??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const icon=name=>`<svg class="i" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const pageCopy=(label,key)=>`<span data-app-i18n="${key}">${label}</span>`;
const line=(name='copy')=>`<span class="skeleton-block route-sk-${name}"></span>`;
const shape=(label,body,labelKey='skeleton.loading')=>`<div class="route-sk-region" role="status" aria-label="${esc(global.RunTeamsLocale?.t(labelKey,{},'正在读取'+label)||'正在读取'+label)}" data-app-i18n-aria-label="${esc(labelKey)}" aria-busy="true"><div aria-hidden="true" inert>${body}</div></div>`;
const search=(name,label,cls='environment-search',id='',labelKey)=>`<label class="${cls} rt-search-field">${icon('search')}<input type="search" data-static-field="${name}" ${id?`id="${id}"`:''} autocomplete="off" aria-label="${label}" placeholder="${label}"${labelKey?` data-app-i18n-aria-label="${labelKey}" data-app-i18n-placeholder="${labelKey}"`: ''} value="${esc(values[name]||'')}" oninput="RunTeamsStaticPages.set('${name}',this.value)"></label>`;
const back=(href,label='返回',labelKey='shell.history.back')=>`<a class="page-back" href="${href}">${icon('back')}<span${labelKey?` data-app-i18n="${labelKey}"`:''}>${label}</span></a>`;
const head=(title,description='',actions='')=>`<header class="environment-title environment-extension-header list-page-header list-page-header--controls"><div class="environment-extension-heading list-page-heading"><h1>${title}</h1>${description?`<p>${description}</p>`:''}</div>${actions?`<div class="environment-catalog-actions list-page-controls">${actions}</div>`:''}</header>`;
const nav=(items,selected,label,cls='page-tabs')=>`<div class="${cls}" role="tablist" aria-label="${label}">${items.map(([key,text,url])=>`<a role="tab" href="${url}" aria-selected="${key===selected}" tabindex="${key===selected?0:-1}"><span>${text}</span></a>`).join('')}</div>`;
const staticTabs=(items,label,labelKey)=>`<div class="page-tabs" role="tablist" aria-label="${label}" data-app-i18n-aria-label="${labelKey}">${items.map((text,i)=>`<button type="button" role="tab" aria-selected="${i===0}" disabled>${text}</button>`).join('')}</div>`;
const data=(body,options)=>`<div class="pending-page-data" data-pending-data>${options.error?error(options):(options.retryMarkup||global.RunTeamsLoadFailure?.pending(options.boot?'boot()':'applyAppRoute()')||body)}</div>`;
function error(options){
 const retry=options.boot?'boot()':'applyAppRoute()';
 if(options.pageKind==='document-reader'&&!options.login&&options.error?.code!=='workspace_access_revoked')return global.RunTeamsLoadFailure.markup({variant:'modal',title:'无法打开文档',titleKey:'documentReader.openFailed',labelKey:'employeeHistory.retry',busyLabelKey:'documentReader.opening',focusFallback:'.doc-reader-back,.doc-reader-bar .page-back',retry});
 const custom=global.RunTeamsHost.pages.error(options);if(custom)return custom;
 if(['conversation','conversation-new','employee-examples'].includes(options.pageKind)){
  const missing=options.pageKind==='conversation'&&(options.error?.status===404||options.error==='这段对话已不存在'||options.error?.message==='这段对话已不存在');
  return global.RunTeamsLoadFailure.markup({variant:'modal',title:missing?'这段对话已不存在':'无法读取对话',titleKey:missing?'conversationDetail.missing':'conversationDetail.loadFailed',label:'重试',labelKey:'conversationDetail.retry',busyLabelKey:'conversationDetail.loading',error:options.error,retry});
 }
 if(options.pageKind==='pipeline')return global.RunTeamsLoadFailure.markup({title:'无法读取流水线',titleKey:'pipelineBoard.readFailed',label:'重试',labelKey:'employeeHistory.retry',busyLabelKey:'pipelineBoard.loading',error:options.error,retry});
 return global.RunTeamsLoadFailure.markup({title:'暂时无法加载此页面',titleKey:'skeleton.pageFailed',labelKey:'employeeHistory.retry',busyLabelKey:'skeleton.loading',error:options.error,retry});
}
// One real composer frame from first paint; only unresolved inner controls load.
function runtimePending(){return `<button class="csel runtime-csel" type="button" disabled aria-busy="true" aria-label="正在读取模型与思考设置…" data-app-i18n-aria-label="composer.runtimeLoading"><span class="skeleton-block sk-runtime-model" aria-hidden="true" inert></span><span class="skeleton-block sk-runtime-effort" aria-hidden="true" inert></span></button>`;}
function composer(content=null,{surface='panel',busy=false,attributes='',runtime=true,placeholder='说说你想做什么…',placeholderKey='composer.prompt'}={}){
 const body=content??`<div class="ccomposer-editor" role="textbox" aria-multiline="true" aria-label="${esc(placeholder)}"${placeholderKey?` data-app-i18n-aria-label="${esc(placeholderKey)}"`:''} aria-disabled="true" aria-busy="true" contenteditable="false" data-placeholder="${esc(placeholder)}"${placeholderKey?` data-app-i18n-data-placeholder="${esc(placeholderKey)}"`:''} data-empty="true"></div><div class="cfoot"><div class="cfoot-left"><button class="cattach-btn" type="button" disabled aria-label="添加内容" data-app-i18n-aria-label="composer.add">${icon('plus')}</button>${runtime?`<div class="copt runtime">${runtimePending()}</div>`:''}</div><div class="cfoot-right"><button class="sendbtn" type="button" disabled aria-label="发送" data-app-i18n-aria-label="composer.send">${icon('arrow')}</button></div></div>`;
 return `<div data-conversation-surface="${esc(surface)}" class="ccomposer${surface==='panel'?' conversation-composer':''}${busy?' is-busy':''}" ${attributes}>${body}</div>`;
}
function conversationWelcomeOptions(kind){
 const placeholder='<span class="conversation-new-action-placeholder"><span class="skeleton-block"></span><span class="skeleton-block"></span></span>';
 return `<div class="conversation-new-actions" inert aria-hidden="true">${placeholder.repeat(kind==='employee'?2:3)}</div>`;
}
function conversationWelcomeContent(kind='general',withComposer=true){
 const employee=kind==='employee',pipeline=kind==='pipeline',creating=kind==='create-employee';
 const title=employee?'你想交办什么工作？':pipeline?'讨论这条流水线':creating?'这名员工要负责什么？':'今天想完成什么？';
 const prompt=employee?'交办工作…':pipeline?'聊聊这条流水线的工作…':creating?'描述员工要负责的工作…':undefined;
 const promptKey=employee?'employeeChat.assign':creating?'employeeCreate.prompt':pipeline?'pipelineBoard.chatPrompt':undefined;
 const options=pipeline?'<p class="conversation-new-notice" data-app-i18n="pipelineBoard.chatHint">在这里讨论目标、流程和进展。要新建任务，请打开看板上的岗位。</p>':conversationWelcomeOptions(kind);
 return `<div class="conversation-empty-state conversation-employee-guidance conversation-new-state" role="status" aria-busy="true"><strong${employee?' data-app-i18n="employeeChat.emptyTitle"':creating?' data-app-i18n="employeeCreate.title"':pipeline?' data-app-i18n="pipelineBoard.chatWelcome"':' data-app-i18n="newConversation.title"'}>${title}</strong>${options}${withComposer?`<div class="rail-assistant-input conversation-home-composer">${composer(null,{runtime:false,placeholder:prompt,placeholderKey:promptKey})}</div>`:''}</div>`;
}
function conversationWelcome(kind,header=''){
 return `<section class="rail-assistant is-home-start" aria-busy="true">${header}<div class="rail-assistant-scroll conversation-start-scroll">${conversationWelcomeContent(kind)}</div></section>`;
}
function conversationAwaitingLocal(header='',{label='对话',labelKey='conversationDetail.loading'}={}){
 return `<section class="rail-assistant is-home-start" aria-busy="true">${header}<div class="rail-assistant-scroll conversation-start-scroll"><div class="conversation-new-state">${shape(label,line('name'),labelKey)}</div></div></section>`;
}
function localConversationId(value=global.location.href){
 const url=new URL(global.RunTeamsRoutes.unmount(value),global.location.origin);
 const id=url.pathname.match(/^\/chats\/(local-[a-f0-9]{32})\/?$/)?.[1]||url.searchParams.get('chat')||'';
 return /^local-[a-f0-9]{32}$/.test(id)?id:'';
}
function localConversationRoute(value){return !!localConversationId(value);}
function conversationPendingHeader({route,layout='',failed=false}={}){
 const id=localConversationId(route);
 const saved=id&&global.RunTeamsBoot?.savedWorkspaceWindows()?.find(row=>localConversationId(row.route)===id);
 const employee=layout==='employee'||!!saved?.employeeReference;
 if(employee&&!failed)return global.RunTeamsSkeletons.workspaceHeader();
 const newChat=!id&&(layout==='general'||layout==='create-employee');
 const title=saved?.employeeName||saved?.title||(newChat?'新对话':layout==='pipeline'?'流水线对话':failed?'对话':'');
 if(!title)return global.RunTeamsSkeletons.workspaceHeader();
 const label=saved?.employeeName||saved?.title?'':newChat?'shell.newChat':layout==='pipeline'?'conversationDetail.pipelineTitle':'conversationDetail.title';
 const heading=`<span class="conversation-panel-heading"><h2 id="conversation_panel_title" class="conversation-panel-name"${label?` data-app-i18n="${label}"`: ''}>${esc(title)}</h2></span>`;
 return global.RunTeamsShell.pageHeader(heading,'',employee);
}
const localLayouts=new Map(),localLayoutReads=new Map();
const validConversationLayout=layout=>['history','general','employee','pipeline','create-employee'].includes(layout);
function localLayoutStorageKey(id){
 const scope=global.RunTeamsDeviceDisplay?.scope;
 return scope&&id?'runteams.local-conversation-layout.v1:'+scope+':'+id:'';
}
function rememberConversationLayouts(receipt){
 for(const [id,layout] of Object.entries(receipt?.conversation_layouts||{})){
  if(!/^local-[a-f0-9]{32}$/.test(id)||!validConversationLayout(layout))continue;
  localLayouts.set(id,layout);
  const key=localLayoutStorageKey(id);
  try{if(key&&global.sessionStorage.getItem(key)!==layout)global.sessionStorage.setItem(key,layout);}catch{}
 }
}
function localConversationLayout(value){
 const id=localConversationId(value);
 if(!id)return '';
 if(localLayouts.has(id))return localLayouts.get(id);
 try{
  const key=localLayoutStorageKey(id),layout=key&&global.sessionStorage.getItem(key);
  return validConversationLayout(layout)?layout:'';
 }catch{return '';}
}
function localSessionLayout(session){
 if(session.messages.length||session.messages_page?.has_more||session.active_turn?.active)return 'history';
 if(session.kind==='employee_design')return 'employee';
 if(session.kind!=='general')return '';
 const context=session.context||{};
 return context.source_pipeline_workspace?'pipeline':context.context_type==='worker'?'employee':context.purpose==='create-employee'?'create-employee':'general';
}
function rememberLocalSessionLayout(session){
 if(session?.storage_scope!=='device'||!Array.isArray(session.messages))return;
 const layout=localSessionLayout(session);
 if(layout)rememberConversationLayouts({conversation_layouts:{[session.public_id]:layout}});
}
function repaintLocalConversation(id){
 const current=global.location.href;
 const pending=global.document.querySelector(`[data-local-conversation-pending="${id}"]`);
 if(!pending||localConversationId(current)!==id||!localLayouts.has(id))return;
 pending.outerHTML=page(global.RunTeamsRoutes.preview(current),{route:current});
}
function requestConversationLayout(value){
 const id=localConversationId(value),scope=global.RunTeamsDeviceDisplay?.scope;
 if(!id||!scope||localLayoutReads.get(id)?.scope===scope)return;
 const headers={'X-RunTeams-Device-Scope':scope};
 const read=path=>global.fetch(path,{headers}).then(response=>response.ok?response.json():null);
 const entry={scope,started:Date.now(),used:false};
 entry.session=read('/api/device/page-ids').then(receipt=>{
   if(global.RunTeamsDeviceDisplay?.scope!==scope||!receipt)return null;
   rememberConversationLayouts(receipt);
   repaintLocalConversation(id);
   const row=receipt.items?.find(item=>item.resource==='chats'&&item.public_id===id);
   if(!row||!/^\d+$/.test(row.id))return null;
   return read('/api/chat/'+row.id+'?messages_limit=30');
  }).then(session=>{
   if(global.RunTeamsDeviceDisplay?.scope!==scope||session?.storage_scope!=='device'||session.public_id!==id||!Array.isArray(session.messages))return null;
   rememberLocalSessionLayout(session);
   repaintLocalConversation(id);
   return session;
  }).catch(()=>null).finally(()=>{
   global.setTimeout(()=>{if(localLayoutReads.get(id)===entry)localLayoutReads.delete(id);},5000);
  });
 localLayoutReads.set(id,entry);
}
async function takeLocalConversation(id,scope){
 const key=localConversationId(),entry=localLayoutReads.get(key);
 if(!entry||entry.used||entry.scope!==scope||Date.now()-entry.started>5000)return null;
 entry.used=true;
 const session=await entry.session;
 return String(session?.id)===String(id)&&key===localConversationId()&&global.RunTeamsDeviceDisplay?.scope===scope?session:null;
}
function pipelineViewKey(route){
 const scope=global.RunTeamsDeviceDisplay?.scope||global.document.querySelector('meta[name="runteams-library-id"]')?.content;
 const path=new URL(global.RunTeamsRoutes.unmount(route||global.location.href),global.location.origin).pathname;
 return scope&&/^\/pipelines\/local\/[a-f0-9]{64}\/[A-Za-z0-9_-]+$/.test(path)?'runteams.pipeline-view.v1:'+scope+':'+path:'';
}
function pipelineViewHint(route){
 try{const key=pipelineViewKey(route);return key&&global.sessionStorage.getItem(key)==='conversation'?'conversation':'';}catch{return '';}
}
function rememberPipelineView(route,view){
 try{const key=pipelineViewKey(route);if(key)global.sessionStorage.setItem(key,view==='conversation'?'conversation':'board');}catch{}
}
function pipelinePendingHeader(failed=false){
 if(!failed)return global.RunTeamsSkeletons.workspaceHeader({pipeline:true});
 return global.RunTeamsShell.pageHeader('<span class="conversation-panel-heading"><h2 class="conversation-panel-name pipeline-title" data-app-i18n="pipelineBoard.pipeline">流水线</h2></span>','',true);
}
function pipelineConversationPending(){
 return `<main class="conversation-workspace-main"><div class="conversation-main-frame">${conversationAwaitingLocal('',{label:'流水线对话',labelKey:'pipelineBoard.conversationOpening'}).replace('class="rail-assistant','class="rail-assistant conversation-main')}</div></main>`;
}
function captureComposer(root=global.document?.getElementById('app')){return root?.querySelector?.('.conversation-main .conversation-composer')||null;}
function restoreComposer(previous,root=global.document?.getElementById('app')){
 const next=captureComposer(root);if(!previous||!next||next===previous)return;
 // Reuse only the neutral frame. All contents and handlers come from the current
 // render, so no old draft, controls or account state can cross into another view.
 for(const attr of [...previous.attributes])if(!next.hasAttribute(attr.name))previous.removeAttribute(attr.name);
 for(const attr of [...next.attributes])previous.setAttribute(attr.name,attr.value);
 previous.replaceChildren(...next.childNodes);next.replaceWith(previous);
}
function frame(kind,body,classes='environment-page',content='environment-content list-page-content'){return `<main class="${classes} pending-page" data-pending-page="${kind}"><div class="${content}">${body}</div></main>`;}

function documentSkeleton(){return `<div class="docs-table">${shape('文档列表',Array.from({length:4},()=>`<div class="docs-row skeleton-docs-row" data-skeleton-row inert><span class="docs-cell docs-cell-title">${line('name')}</span><span class="docs-cell docs-cell-editor">${line('meta')}</span><span class="docs-cell docs-cell-time">${line('meta')}</span><span class="docs-cell docs-cell-more">${line('meta')}</span></div>`).join(''),'documentList.loading')}</div>`;}
function page(value,options={}){
 const kind=global.RunTeamsSkeletons.normalize(value),region=global.RunTeamsSkeletons.region;
 const extension=global.RunTeamsHost.pages.render(kind,options);if(extension!==null)return extension;
 let failed=false;const body=(html)=>{if(options.error&&failed)return '';if(options.error)failed=true;return data(html,{...options,pageKind:kind});},rows=(label,count=3,key)=>shape(label,Array.from({length:count},()=>`<div class="route-sk-row" data-skeleton-row inert>${line('avatar')}<div class="route-sk-copy-group">${line('name')}${line('copy')}</div></div>`).join(''),key);
 const fields=(labels)=>labels.map(label=>`<div class="field"><label>${label}</label>${options.error?'':shape(label,line(label==='详细介绍'?'editor':'field'))}</div>`).join('');
 switch(kind){
 case 'docs':return frame(kind,`<header class="environment-title environment-extension-header list-page-header list-page-header--controls"><div class="environment-extension-heading list-page-heading"><h1 data-app-i18n="documentList.title">文档</h1><p data-app-i18n="documentList.description">查看和管理对话与员工交付的文档。</p></div><div class="environment-catalog-actions list-page-controls">${search('docs','搜索文档名和正文','environment-search','docs_search','documentList.search')}</div></header>`+body(documentSkeleton()),'environment-page docs-page list-page','environment-content docs-content list-page-content');
 case 'trash':return frame(kind,`<header class="trash-head list-page-header"><div class="trash-head-copy"><h1 data-app-i18n="trash.title">垃圾箱</h1><div class="trash-head-subline"><p data-app-i18n="trash.retention">项目通常保留 30 天。含文档的员工、流水线、岗位或任务不会自动清除。</p></div></div></header>`+body(region('trash',undefined,'trash.loading')),'trash-page list-page','trash-content list-page-content');
 case 'document-reader':return `<main class="doc-reader-page pending-page" data-pending-page="${kind}"><header class="doc-reader-bar">${back('/documents','返回文档列表','documentReader.back')} ${options.error?'':`<div aria-hidden="true">${line('name')}</div>`}</header><div class="doc-reader-column">${body(`<div class="doc-reader-skeleton">${shape('文档',line('title')+line(),'documentReader.opening')}</div>`)}</div></main>`;
 case 'employee-settings':return frame(kind,back('/chats/new')+head(pageCopy('员工设置','employeeSettings.title'))+body(rows('员工设置',1,'employeeSettings.loading')));
 case 'run-detail':return frame(kind,back('/chats/new')+body(rows('工作记录',1,'skeleton.workRecord'))+staticTabs([pageCopy('进度','workflowDetail.progress'),pageCopy('原始记录','workflowDetail.raw')],'工作记录视图','workflowDetail.runViews')+`<h3>${pageCopy('工作过程','workflowDetail.activity')}</h3>`+body(region('history',undefined,'skeleton.workActivity')));
 case 'pipeline': {
  const pending=pipelineViewHint(options.route)==='conversation'?pipelineConversationPending():global.RunTeamsSkeletons.pipelineBoard();
  return `<main class="pending-page pending-pipeline" data-pending-page="${kind}">${pipelinePendingHeader(!!options.error)}${body(pending)}</main>`;
 }
 case 'pipeline-new':return `<main class="pending-page pending-pipeline" data-pending-page="${kind}"><div class="vhead core-pipeline-head"><div class="pipeline-title-host">${shape('流水线名称',line('name'),'skeleton.pipelineName')}</div><div class="grow"></div>${global.RunTeamsSkeletons.conversationHeaderActions()}</div>${body(`<div class="board skeleton-board"><div class="cols">${Array.from({length:4},()=>`<div class="col skeleton-column column-color-gray"><div class="col-surface">${shape('岗位',line('name')+rows('任务',3,'skeleton.tasks'),'skeleton.roles')}</div></div>`).join('')}</div></div>`)}</main>`;
 case 'conversation-new':case 'employee-examples': {
  const employee=kind==='employee-examples';
  const purpose=global.RunTeamsRoutes.preview(options.route||location.href)?.purpose;
  const layout=employee?'employee':purpose==='create-employee'?'create-employee':'general';
  const header=conversationPendingHeader({route:options.route,layout,failed:!!options.error});
  const welcome=options.error?`<section class="rail-assistant">${header}<div class="rail-assistant-scroll">${body('')}</div><div class="rail-assistant-input">${composer()}</div></section>`:conversationWelcome(layout,header);
  return `<main class="conversation-workspace-main pending-page" aria-label="对话工作区" data-app-i18n-aria-label="newConversation.workspace" data-pending-page="${kind}"><div class="conversation-main-frame">${welcome.replace('class="rail-assistant','class="rail-assistant conversation-main')}</div></main>`;
 }
 case 'conversation':
  const localId=localConversationId(options.route);
  if(!options.error&&(options.conversationLayout!==undefined||localId)){
   const layout=options.conversationLayout??localConversationLayout(options.route);
   if(localId)requestConversationLayout(options.route);
   if(layout!=='history'){
    const header=conversationPendingHeader({route:options.route,layout});
    const content=layout?conversationWelcome(layout,header):conversationAwaitingLocal(header);
    return `<main class="conversation-workspace-main pending-page" aria-label="对话工作区" data-app-i18n-aria-label="newConversation.workspace" data-pending-page="${kind}"${layout||!localId?'':` data-local-conversation-pending="${localId}"`}><div class="conversation-main-frame">${content.replace('class="rail-assistant','class="rail-assistant conversation-main')}</div></main>`;
   }
  }
 case 'conversation':return `<main class="conversation-workspace-main pending-page" aria-label="对话工作区" data-app-i18n-aria-label="newConversation.workspace" data-pending-page="${kind}"><div class="conversation-main-frame"><section class="rail-assistant conversation-main">${conversationPendingHeader({route:options.route,failed:!!options.error})}<div class="conversation-scroll-shell"><div class="rail-assistant-scroll">${body(region('conversation-messages'))}</div></div><div class="rail-assistant-input">${composer()}</div></section></div></main>`;
 case 'design-system':return global.designSystemMain?.()||frame(kind,head('RunTeams 设计系统','所有产品控件必须从这里继承颜色、边框、层级和交互状态。'));
 default:return frame(kind,head(pageCopy('工作区','shell.mode.team'))+body(region('source-list')));
 }
}
function fail(root,options){
 const workspace=root.querySelector('.conversation-workspace-main[data-pending-page],.pending-pipeline[data-pending-page="pipeline"]');
 if(workspace){workspace.outerHTML=page(workspace.dataset.pendingPage,options);return;}
 const regions=[...root.querySelectorAll('[data-pending-data]')];regions.forEach((region,i)=>{region.innerHTML=i?'':error(options);});root.querySelectorAll('.route-sk-region,.workspace-header-loading').forEach(region=>region.remove());}
function title(kind){const extra=global.RunTeamsHost.pages.title(kind);if(extra!==null)return extra;return ({'conversation-new':'新对话',conversation:'对话','employee-examples':'员工',docs:'文档','document-reader':'文档',pipeline:'流水线','pipeline-new':'新建流水线',trash:'垃圾箱','employee-settings':'员工设置','run-detail':'工作记录','design-system':'设计系统'})[kind]||'工作区';}
function keys(event){if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const buttons=[...event.currentTarget.querySelectorAll('button:not([disabled]),a[role=tab]')],at=buttons.indexOf(event.target);if(at<0)return;event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?buttons.length-1:(at+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[index].click();buttons[index].focus({preventScroll:true});}
function set(name,value,notify=true){values[name]=String(value||'');if(notify)change?.(name,values[name]);}
function select(button,name,value){set(name,value);button.closest('[role="tablist"]')?.querySelectorAll('[role="tab"]').forEach(el=>{el.setAttribute('aria-selected',String(el===button));});}
function choose(button,name,value){set(name,value);global.RunTeamsHost.pages.changed?.(button,name,value);}

function capture(){
 const root=document.querySelector('#rgMid .pending-page,#rgMid .environment-page,#rgMid .trash-page'),active=document.activeElement,field=active?.matches?.('#rgMid [data-static-field]')?active:null;
 if(!root&&!field)return null;
 return {node:field,key:field?.dataset.staticField,value:field?.value,start:field?.selectionStart,end:field?.selectionEnd,top:root?.scrollTop||0,left:root?.scrollLeft||0,url:location.href};
}
function restore(saved){
 if(!saved||saved.url!==location.href)return;
 const root=document.querySelector('#rgMid .pending-page,#rgMid .environment-page,#rgMid .trash-page');if(root){root.scrollTop=saved.top;root.scrollLeft=saved.left;}
 if(!saved.node)return;
 const next=document.querySelector(`#rgMid [data-static-field="${saved.key}"]`);if(!next||next.value!==saved.value)return;
 if(next!==saved.node)next.replaceWith(saved.node);saved.node.focus({preventScroll:true});if(saved.start!==null)saved.node.setSelectionRange(saved.start,saved.end);
}

global.RunTeamsStaticPages={composer,pipelineViewHint,rememberPipelineView,pipelineConversationPending,conversationWelcome,conversationWelcomeContent,conversationWelcomeOptions,conversationAwaitingLocal,conversationPendingHeader,localConversationRoute,localConversationLayout,rememberConversationLayouts,rememberLocalSessionLayout,takeLocalConversation,captureComposer,restoreComposer,runtimePending,page,title,fail,error,keys,icon,search,documentSkeleton,values,set,select,choose,capture,restore,connect:callback=>{change=callback;},reset:()=>{for(const key of Object.keys(values))delete values[key];}};
})(window);
