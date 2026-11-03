/* Static page chrome is available before account or business requests. */
(function(global){
'use strict';
const values=Object.create(null);let change=null;
const esc=value=>String(value??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const icon=name=>`<svg class="i" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const line=(name='copy')=>`<span class="skeleton-block route-sk-${name}"></span>`;
const shape=(label,body)=>`<div class="route-sk-region" role="status" aria-label="正在读取${label}" aria-busy="true"><div aria-hidden="true" inert>${body}</div></div>`;
const search=(name,label,cls='environment-search',id='')=>`<label class="${cls} rt-search-field">${icon('search')}<input type="search" data-static-field="${name}" ${id?`id="${id}"`:''} autocomplete="off" aria-label="${label}" placeholder="${label}" value="${esc(values[name]||'')}" oninput="RunTeamsStaticPages.set('${name}',this.value)"></label>`;
const back=(href,label='返回')=>`<a class="page-back" href="${href}">${icon('back')}<span>${label}</span></a>`;
const head=(title,description='',actions='')=>`<header class="environment-title environment-extension-header list-page-header list-page-header--controls"><div class="environment-extension-heading list-page-heading"><h1>${title}</h1>${description?`<p>${description}</p>`:''}</div>${actions?`<div class="environment-catalog-actions list-page-controls">${actions}</div>`:''}</header>`;
const nav=(items,selected,label,cls='page-tabs')=>`<div class="${cls}" role="tablist" aria-label="${label}">${items.map(([key,text,url])=>`<a role="tab" href="${url}" aria-selected="${key===selected}" tabindex="${key===selected?0:-1}"><span>${text}</span></a>`).join('')}</div>`;
const staticTabs=(items,label,cls='page-tabs')=>`<div class="${cls}" role="tablist" aria-label="${label}">${items.map((text,i)=>`<button type="button" role="tab" aria-selected="${i===0}" disabled><span>${text}</span></button>`).join('')}</div>`;
const data=(body,options)=>`<div class="pending-page-data" data-pending-data>${options.error?error(options):(options.retryMarkup||global.RunTeamsLoadFailure?.pending(options.boot?'boot()':'applyAppRoute()')||body)}</div>`;
function error(options){return global.RunTeamsHost.pages.error(options)||global.RunTeamsLoadFailure.markup({title:'内容暂时无法加载',error:options.error,retry:options.boot?'boot()':'applyAppRoute()'});}
// One real composer frame from first paint; only unresolved inner controls load.
function runtimePending(){return `<button class="csel runtime-csel" type="button" disabled aria-busy="true" aria-label="正在读取模型与思考设置…"><span class="skeleton-block sk-runtime-model" aria-hidden="true" inert></span><span class="skeleton-block sk-runtime-effort" aria-hidden="true" inert></span></button>`;}
function composer(content=null,{surface='panel',busy=false,attributes=''}={}){
 const body=content??`<div class="ccomposer-editor" role="textbox" aria-multiline="true" aria-label="说说你要做的事…" aria-disabled="true" aria-busy="true" contenteditable="false" data-placeholder="说说你要做的事…" data-empty="true"></div><div class="cfoot"><div class="cfoot-left"><button class="cattach-btn" type="button" disabled aria-label="添加内容">${icon('plus')}</button><div class="copt runtime">${runtimePending()}</div></div><div class="cfoot-right"><button class="sendbtn" type="button" disabled aria-label="发送">${icon('arrow')}</button></div></div>`;
 return `<div data-conversation-surface="${esc(surface)}" class="ccomposer${surface==='panel'?' conversation-composer':''}${busy?' is-busy':''}" ${attributes}>${body}</div>`;
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

function documentSkeleton(){return `<div class="docs-table">${shape('文档列表',Array.from({length:4},()=>`<div class="docs-row skeleton-docs-row" data-skeleton-row inert><span class="docs-cell docs-cell-title">${line('name')}</span><span class="docs-cell docs-cell-editor">${line('meta')}</span><span class="docs-cell docs-cell-time">${line('meta')}</span><span class="docs-cell docs-cell-more">${line('meta')}</span></div>`).join(''))}</div>`;}
function page(value,options={}){
 const kind=global.RunTeamsSkeletons.normalize(value),region=global.RunTeamsSkeletons.region;
 const extension=global.RunTeamsHost.pages.render(kind,options);if(extension!==null)return extension;
 let failed=false;const body=(html)=>{if(options.error&&failed)return '';if(options.error)failed=true;return data(html,options);},rows=(label,count=3)=>shape(label,Array.from({length:count},()=>`<div class="route-sk-row" data-skeleton-row inert>${line('avatar')}<div class="route-sk-copy-group">${line('name')}${line('copy')}</div></div>`).join(''));
 const fields=(labels)=>labels.map(label=>`<div class="field"><label>${label}</label>${options.error?'':shape(label,line(label==='详细介绍'?'editor':'field'))}</div>`).join('');
 switch(kind){
 case 'docs':return frame(kind,head('文档','查看和管理对话与员工交付的文档。',search('docs','搜索文档名和正文','environment-search','docs_search'))+body(documentSkeleton()),'environment-page docs-page list-page','environment-content docs-content list-page-content');
 case 'trash':return frame(kind,`<header class="trash-head list-page-header"><div class="trash-head-copy"><h1>垃圾箱</h1><div class="trash-head-subline"><p>移除的项目通常保留 30 天；含文档的项目不会自动清除。</p></div></div></header>`+body(region('trash')),'trash-page list-page','trash-content list-page-content');
 case 'automations':return frame(kind,head('旧自动化','这里保留以前创建的计划；新的自动化请在员工工作中创建。')+body(rows('自动化',4)),'environment-page automation-page');
 case 'document-reader':return `<main class="doc-reader-page pending-page" data-pending-page="${kind}"><header class="doc-reader-bar">${back('/documents')} ${shape('文档名',line('name'))}</header><div class="doc-reader-column">${body(`<div class="doc-reader-skeleton">${shape('文档正文',line('title')+region('skill-summary'))}</div>`)}</div></main>`;
 case 'employee-settings':return frame(kind,back('/chats/new')+head('员工设置')+body(rows('员工名称与描述',1)));
 case 'run-detail':return frame(kind,back('/chats/new')+body(rows('工作名称与状态',1))+staticTabs(['进度','原始记录'],'工作记录视图')+`<h3>工作过程</h3>`+body(region('history')));
 case 'pipeline-new':case 'pipeline':return `<main class="pending-page pending-pipeline" data-pending-page="${kind}"><div class="vhead core-pipeline-head"><div class="pipeline-title-host">${shape('流水线名称',line('name'))}</div><div class="grow"></div>${global.RunTeamsSkeletons.conversationHeaderActions()}</div>${body(`<div class="board skeleton-board"><div class="cols">${Array.from({length:4},()=>`<div class="col skeleton-column column-color-gray"><div class="col-surface">${shape('岗位',line('name')+rows('任务',3))}</div></div>`).join('')}</div></div>`)}</main>`;
 case 'conversation-new':case 'conversation':case 'employee-examples':return `<main class="conversation-workspace-main pending-page" data-pending-page="${kind}"><div class="conversation-main-frame"><section class="rail-assistant conversation-main"><header class="conversation-panel-header">${kind==='conversation-new'?'<b>新对话</b>':shape('对话名称',line('name'))}${kind==='conversation-new'||options.error?'':global.RunTeamsSkeletons.conversationHeaderActions()}</header><div class="conversation-scroll-shell"><div class="rail-assistant-scroll">${kind==='conversation-new'?'<div class="conversation-empty-state conversation-new-state"><strong>今天想完成什么？</strong></div>'+(options.error?body(''):''):body(kind==='employee-examples'?global.RunTeamsBoot.guidanceSkeleton():region('conversation-messages'))}</div></div><div class="rail-assistant-input">${composer()}</div></section></div></main>`;
 case 'design-system':return global.designSystemMain?.()||frame(kind,head('RunTeams 设计系统','所有产品控件必须从这里继承颜色、边框、层级和交互状态。'));
 default:return frame(kind,head('工作区')+body(region('source-list')));
 }
}
function fail(root,options){const regions=[...root.querySelectorAll('[data-pending-data]')];regions.forEach((region,i)=>{region.innerHTML=i?'':error(options);});root.querySelectorAll('.route-sk-region').forEach(region=>region.remove());}
function title(kind){const extra=global.RunTeamsHost.pages.title(kind);if(extra!==null)return extra;return ({'conversation-new':'新对话',conversation:'对话','employee-examples':'员工',docs:'文档','document-reader':'文档',pipeline:'流水线','pipeline-new':'新建流水线',trash:'垃圾箱',automations:'旧自动化','employee-settings':'员工设置','run-detail':'工作记录','design-system':'设计系统'})[kind]||'工作区';}
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

global.RunTeamsStaticPages={composer,captureComposer,restoreComposer,runtimePending,page,title,fail,error,keys,icon,search,documentSkeleton,values,set,select,choose,capture,restore,connect:callback=>{change=callback;},reset:()=>{for(const key of Object.keys(values))delete values[key];}};
})(window);
