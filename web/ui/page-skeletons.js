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
const chat=(fresh=false)=>`<div class="route-sk-chat">${heading()}<div class="route-sk-chat-body">${fresh?`<div class="route-sk-prompt">${line('title')}${line('subtitle')}<div>${repeat(4,line('suggestion'))}</div></div>`:repeat(3,paragraph())}</div>${composer()}</div>`;
const skillRows=()=>`<div class="route-sk-skill-grid">${repeat(8,`<div class="route-sk-row" data-skeleton-row inert>${line('avatar')}${copy()}</div>`)}</div>`;
const library=()=>`${heading()}<div class="route-sk-tabs">${repeat(2,line('tab'))}</div>${skillRows()}`;
const detail=()=>`${heading(true)}<div class="route-sk-identity route-sk-detail-identity">${line('large-avatar')}${copy()}${line('action')}</div>${tabs()}<div class="route-sk-detail-columns"><div>${repeat(3,paragraph())}</div><div class="route-sk-card">${copy()}${line('field')}${line('field')}</div></div>`;
const frame=(kind,body,classes='')=>`<div class="route-sk-page route-sk-page-${kind} ${classes}"><div class="route-sk-content">${body}</div></div>`;
const labels={marketplace:'市场', 'marketplace-detail':'市场资产详情','marketplace-published':'我发布的资产',
 'marketplace-choose':'选择发布资产','marketplace-manage':'资产管理','marketplace-publish':'发布资产',
 'employee-settings':'员工设置','run-detail':'执行记录',wallet:'钱包',
 'billing-subscription':'升级计划','billing-rentals':'租用资产','billing-records':'资金记录',
 'conversation-new':'新对话',conversation:'对话','employee-examples':'员工对话',pipeline:'流水线','pipeline-new':'新建流水线',
 docs:'文档','document-reader':'文档正文',automations:'自动化',trash:'垃圾箱','design-system':'设计系统',workspace:'工作区'};
function normalize(value){
 if(typeof value==='string'&&Object.hasOwn(labels,value))return value;
 const route=typeof value==='string'?{kind:value}:value||{},kind=route.kind;
 if(kind==='bot')return route.settings?'employee-settings':route.chatId==='new'?'employee-examples':'conversation';
 if(kind==='docs')return route.documentId?'document-reader':'docs';
 if(kind==='marketplace-publisher')return route.listingId?(route.section==='edit'?'marketplace-publish':'marketplace-manage'):'marketplace-published';
 if(kind==='marketplace-publish')return route.sourceType&&route.sourceId?'marketplace-publish':'marketplace-choose';
 if(kind==='billing')return `billing-${['subscription','rentals','records'].includes(route.tab)?route.tab:'rentals'}`;
 if(['home','team','chat-new'].includes(kind))return 'conversation-new';
 if(['chat'].includes(kind))return 'conversation';
 if(kind==='source-pipeline-new')return 'pipeline-new';
 if(kind==='source-pipeline')return 'pipeline';
 return Object.hasOwn(labels,kind)?kind:'workspace';
}
function fromLocation(){
 return normalize(global.RunTeamsRoutes.preview(location.href));
}

function region(kind,count){
 let body;
 switch(kind){
  case 'market-catalog':body=`<div class="route-sk-search">${line('field')}${line('action')}</div><div class="route-sk-market-cards">${repeat(count||6,card())}</div>`;break;
  case 'market-cards':body=`<div class="route-sk-market-cards">${repeat(count||6,card())}</div>`;break;
  case 'publisher-list':body=table(6);break;
  case 'documents':case 'trash':body=table(3);break;
  case 'parameters':body=fields();break;
  case 'employee-automations':body=repeat(count||3,`<div class="route-sk-automation-row" data-skeleton-row inert>${line('automation-toggle')}<div class="route-sk-automation-copy">${line('automation-name')}${line('automation-time')}</div>${line('automation-more')}</div>`);break;
  case 'history':body=repeat(count||3,`<div class="route-sk-history-row" data-skeleton-row inert>${line('name')}${line('meta')}</div>`);break;

  case 'source-list':body=repeat(count||4,row());break;
  case 'versions':body=repeat(count||3,row());break;
  case 'reviews':body=repeat(count||3,`<div class="route-sk-row" data-skeleton-row inert>${line('avatar')}${paragraph()}</div>`);break;
  case 'conversation-messages':body=repeat(2,paragraph());break;
  default:body=repeat(count||2,paragraph());
 }
 const label=({'reviews':'正在读取评论','versions':'正在读取版本','documents':'正在读取文档','trash':'正在读取垃圾箱',
  'skill-summary':'正在读取工作说明','skill-file':'正在读取文件','conversation-messages':'正在打开对话',
  'parameters':'正在读取任务输入','history':'正在读取历史版本','market-catalog':'正在读取市场资产',
  'employee-automations':'正在读取自动化','publisher-list':'正在读取发布资产','source-list':'正在读取列表','skills':'正在读取技能'})[kind]||'正在加载';
 return `<div class="route-sk-region" data-skeleton-region="${kind}" role="status" aria-label="${label}" aria-busy="true"><div aria-hidden="true" inert>${body}</div></div>`;
}
function page(kind){
 switch(kind){
  case 'marketplace':return frame(kind,`<div class="route-sk-market-hero"><div>${line('tab')}${line('hero-title')}${line('subtitle')}</div>${line('hero-art')}</div><div class="route-sk-search">${line('field')}${line('action')}</div><div class="route-sk-market-cards">${repeat(6,card())}</div>`,'marketplace-page');
  case 'marketplace-detail':case 'marketplace-manage':return frame(kind,detail(),'marketplace-page');
  case 'marketplace-published':return frame(kind,`${heading()}<div class="route-sk-search">${line('field')}${tabs()}</div>${table(6)}`,'marketplace-page');
  case 'marketplace-choose':return frame(kind,`${heading(true)}${tabs()}${repeat(4,row())}`,'marketplace-page');
  case 'marketplace-publish':return frame(kind,`${heading(true)}<div class="route-sk-detail-columns">${fields()}${card()}</div>`,'marketplace-page');
  case 'conversation-new':return chat(true);
  case 'employee-settings':return `<div class="route-sk-split">${chat()}<div class="route-sk-side">${heading()}${line('name')}${line('copy')}</div></div>`;
  case 'run-detail':return frame(kind,`${heading(true)}${line('subtitle')}<div class="route-sk-detail-columns"><div>${repeat(3,paragraph())}</div><div>${repeat(3,row())}</div></div>`);
  case 'wallet':return frame(kind,`${heading()}<div class="route-sk-balance">${line('tab')}${line('amount')}${line('action')}</div>${table(4)}`,'account-wallet-page');
  case 'billing-subscription':return frame(kind,`${heading()}${tabs()}${row()}<div class="route-sk-market-cards">${repeat(3,card())}</div>`,'billing-page');
  case 'billing-rentals':case 'billing-records':return frame(kind,`${heading()}${tabs()}${table(kind==='billing-records'?4:5)}`,'billing-page');
  case 'document-reader':return `<div class="doc-reader-page"><header class="doc-reader-bar">${line('back')}${line('name')}</header><div class="doc-reader-column"><div class="doc-reader-skeleton" aria-hidden="true">${line('title doc-skeleton-title')}${repeat(3,paragraph())}</div></div></div>`;
  case 'design-system':return frame(kind,`${heading()}${tabs()}<div class="route-sk-market-cards">${repeat(6,card())}</div>`);
  case 'workspace':return frame(kind,heading()+repeat(3,row()));
  default:return null; // Existing conversation, board, document list, trash and automation shapes.
 }
}
function conversationHeaderActions(){return '<div class="conversation-panel-controls conversation-header-skeleton-actions" inert aria-hidden="true">'+repeat(3,'<span class="skeleton-block conversation-header-skeleton-action"></span>')+'</div>';}
function wrap(kind,body){return `<div class="route-skeleton" data-page-skeleton="${kind}" role="status" aria-label="正在加载${labels[kind]||'页面'}" aria-busy="true"><div class="route-sk-shapes" aria-hidden="true" inert>${body}</div></div>`;}
global.RunTeamsSkeletons={normalize,fromLocation,page,region,wrap,conversationHeaderActions};
})(window);
