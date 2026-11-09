/* Loading geometry follows the destination page. No records or controls are fabricated. */
(function(global){
'use strict';
const line=(size='copy')=>`<span class="skeleton-block route-sk-${size}"></span>`;
const repeat=(count,markup)=>Array.from({length:count},()=>markup).join('');
const copy=()=>`<div class="route-sk-copy-group">${line('name')}${line('copy')}${line('short')}</div>`;
const tabs=()=>`<div class="route-sk-tabs">${repeat(3,line('tab'))}</div>`;
const heading=(back=false)=>`${back?line('back'):''}<div class="route-sk-heading"><div>${line('title')}${line('subtitle')}</div>${line('action')}</div>`;
const row=()=>`<div class="route-sk-row" data-skeleton-row inert>${line('avatar')}${copy()}${line('meta')}</div>`;
const card=()=>`<div class="route-sk-card"><div class="route-sk-identity">${line('avatar')}${copy()}</div>${line('copy')}${line('copy')}${line('short')}<div class="route-sk-card-foot">${line('meta')}${line('meta')}</div></div>`;
const paragraph=()=>`<div class="route-sk-paragraph">${line('name')}${repeat(3,line('copy'))}${line('short')}</div>`;
const table=(columns=5)=>`<div class="route-sk-table" style="--skeleton-columns:${columns}"><div class="route-sk-table-head" data-skeleton-row inert>${repeat(columns,line('tab'))}</div>${repeat(4,`<div class="route-sk-table-row" data-skeleton-row inert>${copy()}${repeat(columns-1,line('meta'))}</div>`)}</div>`;
const fields=()=>`<div class="route-sk-fields">${repeat(3,`<div>${line('tab')}${line('field')}</div>`)}${line('editor')}</div>`;
const tree=()=>`<div class="route-sk-tree">${line('tab')}${repeat(6,line('tree-row'))}</div>`;
const composer=()=>`<div class="route-sk-composer">${line('copy')}<div>${line('tab')}${line('meta')}</div></div>`;
const chat=()=>`<div class="route-sk-chat">${heading()}<div class="route-sk-chat-body">${repeat(3,paragraph())}</div>${composer()}</div>`;
const skillRows=()=>`<div class="route-sk-skill-grid">${repeat(8,`<div class="route-sk-row" data-skeleton-row inert>${line('avatar')}${copy()}</div>`)}</div>`;
const library=()=>`${heading()}<div class="route-sk-tabs">${repeat(2,line('tab'))}</div>${skillRows()}`;
const detail=()=>`${heading(true)}<div class="route-sk-identity route-sk-detail-identity">${line('large-avatar')}${copy()}${line('action')}</div>${tabs()}<div class="route-sk-detail-columns"><div>${repeat(3,paragraph())}</div><div class="route-sk-card">${copy()}${line('field')}${line('field')}</div></div>`;
const frame=(kind,body,classes='')=>`<div class="route-sk-page route-sk-page-${kind} ${classes}"><div class="route-sk-content">${body}</div></div>`;
const pageStatus={
 'employee-settings':['employeeSettings.loading','正在读取员工设置…'],
 'run-detail':['skeleton.workRecord','正在读取工作记录…'],
 'conversation-new':['skeleton.newConversation','正在打开新对话…'],
 conversation:['conversationDetail.loading','正在读取对话…'],
 'employee-examples':['conversationDetail.loading','正在读取员工对话…'],
 pipeline:['pipelineBoard.loading','正在读取流水线…'],
 'pipeline-new':['skeleton.newPipeline','正在打开新建流水线…'],
 docs:['documentList.loading','正在读取文档…'],
 'document-reader':['documentReader.opening','正在打开文档…'],
 automations:['automationList.loading','正在读取自动化…'],
 trash:['trash.loading','正在读取垃圾箱…'],
 'design-system':['skeleton.designSystem','正在读取设计系统…'],
 workspace:['skeleton.workspace','正在打开工作区…']
};
const regionStatus={
 reviews:['skeleton.reviews','正在读取评价…'],
 versions:['employeeHistory.loading','正在读取历史版本…'],
 documents:pageStatus.docs,trash:pageStatus.trash,
 'skill-summary':['skeleton.skillSummary','正在读取工作说明…'],
 'skill-file':['employeeResource.loadingFile','正在读取文件…'],
 'conversation-messages':pageStatus.conversation,
 parameters:['taskEdit.loadingInputs','正在加载任务输入…'],
 history:['employeeHistory.loading','正在读取历史版本…'],
 'employee-automations':pageStatus.automations,
 'source-list':['skeleton.list','正在读取列表…'],
 skills:['skeleton.skills','正在读取技能…']
};
const escapeAttr=value=>String(value).replace(/[&<>"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));
function statusAttrs(key='skeleton.loading',fallback='正在加载…'){
 const label=global.RunTeamsLocale?.t(key,{},fallback)??fallback;
 return `role="status" aria-label="${escapeAttr(label)}" data-app-i18n-aria-label="${escapeAttr(key)}" aria-busy="true"`;
}
function normalize(value){
 if(typeof value==='string'&&Object.hasOwn(pageStatus,value))return value;
 const route=typeof value==='string'?{kind:value}:value||{},kind=route.kind;
 if(kind==='bot')return route.settings?'employee-settings':route.chatId==='new'?'employee-examples':'conversation';
 if(kind==='docs')return route.documentId?'document-reader':'docs';
 const contributed=global.RunTeamsHost.pages.normalize(value);if(contributed!==null)return contributed;
 if(['home','team','chat-new'].includes(kind))return 'conversation-new';
 if(['chat'].includes(kind))return 'conversation';
 if(kind==='source-pipeline-new')return 'pipeline-new';
 if(kind==='source-pipeline')return 'pipeline';
 return Object.hasOwn(pageStatus,kind)?kind:'workspace';
}
function fromLocation(){
 return normalize(global.RunTeamsRoutes.preview(location.href));
}

function region(kind,count,labelKey){
 const extension=global.RunTeamsHost.pages.skeletonRegion?.(kind,count,labelKey);if(extension!=null)return extension;
 let body;
 switch(kind){
  case 'documents':case 'trash':body=table(3);break;
  case 'parameters':body=fields();break;
  case 'employee-automations':body=repeat(count||3,`<div class="route-sk-automation-row" data-skeleton-row inert>${line('automation-toggle')}<div class="route-sk-automation-copy">${line('automation-name')}${line('automation-time')}</div>${line('automation-more')}</div>`);break;
  case 'history':body=repeat(count||3,`<div class="route-sk-history-row" data-skeleton-row inert>${line('name')}${line('meta')}</div>`);break;

  case 'pipeline-stage-employees':body=repeat(count||3,`<div class="route-sk-stage-employee" data-skeleton-row inert>${line('stage-avatar')}<div class="route-sk-stage-copy">${line('stage-name')}${line('stage-skill')}</div></div>`);break;
  case 'task-detail':case 'work-records':{
   const group=kind==='task-detail'?line('drawer-section'):'';
   const record=`<div class="route-sk-work-record" data-skeleton-row inert><div>${line('name')}${line('meta')}</div><div>${line('short')}${line('meta')}</div></div>`;
   body=group+repeat(count||3,record);break;
  }
  case 'source-list':body=repeat(count||4,row());break;
  case 'versions':body=repeat(count||3,row());break;
  case 'reviews':body=repeat(count||3,`<div class="route-sk-row" data-skeleton-row inert>${line('avatar')}${paragraph()}</div>`);break;
  case 'conversation-messages':body=repeat(2,paragraph());break;
  default:body=repeat(count||2,paragraph());
 }
 const [key,label]=Object.hasOwn(regionStatus,kind)?regionStatus[kind]:[];
 return `<div class="route-sk-region" data-skeleton-region="${kind}" ${statusAttrs(labelKey||key,label)}><div aria-hidden="true" inert>${body}</div></div>`;
}
function page(kind){
 const extension=global.RunTeamsHost.pages.skeletonPage?.(kind);if(extension!=null)return extension;
 switch(kind){
  case 'conversation-new':case 'employee-examples':return global.RunTeamsStaticPages.page(kind);
  case 'employee-settings':return `<div class="route-sk-split">${chat()}<div class="route-sk-side">${heading()}${line('name')}${line('copy')}</div></div>`;
  case 'run-detail':return frame(kind,`${heading(true)}${line('subtitle')}<div class="route-sk-detail-columns"><div>${repeat(3,paragraph())}</div><div>${repeat(3,row())}</div></div>`);
  case 'document-reader':return `<div class="doc-reader-page"><header class="doc-reader-bar">${line('back')}${line('name')}</header><div class="doc-reader-column"><div class="doc-reader-skeleton" aria-hidden="true">${line('title doc-skeleton-title')}${repeat(3,paragraph())}</div></div></div>`;
  case 'design-system':return frame(kind,`${heading()}${tabs()}<div class="route-sk-market-cards">${repeat(6,card())}</div>`);
  case 'workspace':return frame(kind,heading()+repeat(3,row()));
  default:return null; // Existing conversation, board, document list, trash and automation shapes.
 }
}
function drawerHeading({title='',leading='',meta=0,description=false}={}){
 const heading=title?`<h2 class="detail-drawer-title">${escapeAttr(title)}</h2>`:
  `<div class="route-sk-drawer-title" aria-hidden="true" inert>${line('title')}</div>`;
 const details=meta?`<div class="route-sk-drawer-meta" aria-hidden="true" inert>${repeat(meta,line('meta'))}</div>`:
  description?`<div class="route-sk-drawer-description" aria-hidden="true" inert>${line('copy')}</div>`:'';
 const identity=title&&leading?`<div class="detail-drawer-heading-row detail-drawer-heading-row--identity">${leading}${heading}</div>`:heading;
 return `<div class="detail-drawer-heading">${identity}${details}</div>`;
}
function pipelineColumns(){
 const block=shape=>`<span class="skeleton-block ${shape}"></span>`;
 const task=`<div class="skeleton-task">${block('sk-copy wide')}${block('sk-copy')}${block('sk-meta')}</div>`;
 const columns=Array.from({length:4},(_,index)=>`<div class="col skeleton-column column-color-gray"><div class="col-surface"><div class="chd">${block(index===0?'sk-name short':'sk-name')}${block('sk-count')}</div><div class="lane">${repeat(index===0?2:3,task)}</div></div></div>`).join('');
 return `<div class="cols" aria-hidden="true" inert>${columns}</div>`;
}
function pipelineBoard(){
 return `<main class="home-workspace source-pipeline-workspace pipeline-board-loading" role="status" aria-label="正在读取流水线" data-app-i18n-aria-label="pipelineBoard.loading" aria-busy="true"><div class="board core-pipeline-board skeleton-board">${pipelineColumns()}</div></main>`;
}
function conversationHeaderActions(){return '<div class="conversation-panel-controls conversation-header-skeleton-actions" inert aria-hidden="true">'+repeat(3,'<span class="skeleton-block conversation-header-skeleton-action"></span>')+'</div>';}
function workspaceHeader({pipeline=false}={}){
 const label=pipeline?'正在读取流水线信息':'正在读取对话信息';
 const title=`<span class="conversation-header-skeleton" aria-hidden="true"><span class="skeleton-block conversation-header-skeleton-title"></span></span>`;
 return `<header class="conversation-panel-header workspace-header-loading${pipeline?' employee-desk':''}" role="status" aria-label="${label}" data-app-i18n-aria-label="${pipeline?'pipelineBoard.loading':'conversationDetail.headerLoading'}" aria-busy="true">${title}${conversationHeaderActions()}</header>`;
}
function wrap(kind,body){
 const status=Object.hasOwn(pageStatus,kind)?pageStatus[kind]:global.RunTeamsHost.pages.skeletonStatus?.(kind)||[];
 return `<div class="route-skeleton" data-page-skeleton="${kind}" ${statusAttrs(...status)}><div class="route-sk-shapes" aria-hidden="true" inert>${body}</div></div>`;
}
global.RunTeamsSkeletons={normalize,fromLocation,page,region,wrap,statusAttrs,drawerHeading,conversationHeaderActions,pipelineColumns,pipelineBoard,workspaceHeader};
})(window);
