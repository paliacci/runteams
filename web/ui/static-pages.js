/* Static page chrome is available before account or business requests. */
(function(global){
'use strict';
const values=Object.create(null);let change=null;
const esc=value=>String(value??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const icon=name=>`<svg class="i" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const line=(name='copy')=>`<span class="skeleton-block route-sk-${name}"></span>`;
const shape=(label,body)=>`<div class="route-sk-region" role="status" aria-label="正在读取${label}" aria-busy="true"><div aria-hidden="true" inert>${body}</div></div>`;
const search=(name,label,cls='environment-search',id='')=>`<label class="${cls} rt-search-field">${icon('search')}<input type="search" data-static-field="${name}" ${id?`id="${id}"`:''} autocomplete="off" aria-label="${label}" placeholder="${label}" value="${esc(values[name]||'')}" oninput="RunTeamsStaticPages.set('${name}',this.value)"></label>`;
const back=(href,label='返回')=>`<a class="marketplace-publish-back" href="${href}">${icon('back')}<span>${label}</span></a>`;
const head=(title,description='',actions='')=>`<header class="environment-title environment-extension-header list-page-header list-page-header--controls"><div class="environment-extension-heading list-page-heading"><h1>${title}</h1>${description?`<p>${description}</p>`:''}</div>${actions?`<div class="environment-catalog-actions list-page-controls">${actions}</div>`:''}</header>`;
const nav=(items,selected,label,cls='account-billing-tabs')=>`<div class="${cls}" role="tablist" aria-label="${label}">${items.map(([key,text,url])=>`<a role="tab" href="${url}" aria-selected="${key===selected}" tabindex="${key===selected?0:-1}"><span>${text}</span></a>`).join('')}</div>`;
const staticTabs=(items,label,cls='market-creator-tabs')=>`<div class="${cls}" role="tablist" aria-label="${label}">${items.map((text,i)=>`<button type="button" role="tab" aria-selected="${i===0}" disabled><span>${text}</span></button>`).join('')}</div>`;
const data=(body,options)=>`<div class="pending-page-data" data-pending-data>${options.error?error(options):(options.retryMarkup||global.RunTeamsLoadFailure?.pending(options.boot?'boot()':'applyAppRoute()')||body)}</div>`;
function error(options){const revoked=options.error?.code==='workspace_access_revoked';return global.RunTeamsLoadFailure.markup({title:options.login?'登录以继续':revoked?'组织访问已结束':'内容暂时无法加载',note:options.login?'登录后继续使用你的云端数据。':'',error:options.login?'':options.error,label:options.login?'登录':revoked?'切换工作区':undefined,retry:options.login?'openLoginDialog()':revoked?'accountTeamOpen()':options.boot?'boot()':'applyAppRoute()'});}
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

// Public plan copy and prices are shared by first paint and the account page.
// They describe the offer only; no renderer can grant access or start checkout.
function subscriptionPlans(){return [
 {id:'free',name:'Free',headline:'创建员工，搭建流水线',includes:'',features:['创建不限数量的 AI 员工','搭建不限数量的流水线','自定义员工技能与工作方式','从市场安装员工与流水线','同时启用 3 个定时计划']},
 {id:'pro',name:'Pro',headline:'让日常工作按计划执行',includes:'包含 Free 全部权益',monthly:12,annual:115.20,features:['不限同时启用的计划数','员工与流水线定时启动','周期工作一次安排，重复执行']},
 {id:'max',name:'Max',headline:'用手机跟进电脑上的工作',includes:'包含 Pro 全部权益',monthly:24,annual:230.40,features:['手机查看工作进展与成果','接收完成、异常与待处理通知','手机回复人工确认请求','远程取消执行中的任务','统一管理多台在线电脑']},
 {id:'team',name:'Team',headline:'和同事共享员工与工作成果',includes:'成员在组织内享 Max 权益',monthly:69,annual:662.40,features:['共享组织员工与流水线','在组织工作区共享成果','邀请成员，设置访问权限','查看任务发起人与执行电脑','组织统一付款']}
];}
function subscriptionPrice(plan,interval){
 if(plan.id==='free')return {amount:'$0',unit:'',note:'免费使用',detail:''};
 const annual=interval==='year';
 return {amount:'$'+(annual?plan.annual.toFixed(2):plan.monthly),unit:annual?'/年':'/月',note:plan.id==='team'?'含 3 席，所有者占 1 席':annual?`相当于 $${(plan.annual/12).toFixed(2)}/月`:'',detail:plan.id==='team'?`额外席位 $${annual?'182.40':'19'}/人/${annual?'年':'月'}`:''};
}
const subscriptionFAQ=[["Free 的 3 个计划怎样计算？", "按同时启用的计划数计算，员工、流水线与周期自动化共用 3 个名额。暂停或删除会释放名额；单次手动交办、失败和重试不额外占用。"], ["套餐包含 Agent 厂商的订阅费用吗？", "不包含。目前支持 Codex CLI 和 Claude Code，使用你自己的厂商账号与额度。厂商订阅费用单独计算，使用限制以厂商规则为准。"], ["套餐包含市场员工与流水线的租用费吗？", "不包含。免费员工与流水线可直接安装；付费项目需要单独租用。具体价格与周期以项目详情为准。"], ["Team 包含几个人？还能增加成员吗？", "Team 含 3 席，所有者占 1 席，成员接受邀请时占用席位。可增加额外席位，费用随套餐按月或按年计算。成员在组织内享 Max 权益，个人空间的套餐单独计算。"], ["手机管理时，电脑需要在线吗？", "需要。Agent 仍在执行电脑上工作，电脑须保持在线，且 RunTeams、Agent、额度与所需授权均可用。手机用于查看进展和成果、处理人工确认及取消任务。"], ["可以取消续费吗？", "可以。取消后，已确认的付费权益保留至当前周期结束。个人套餐到期回到 Free；若启用计划超过 3 个，全部暂停，由你重新选择最多 3 个。计划、历史和成果保留，已开始执行的工作正常完结。"], ["套餐、计费周期或席位变更何时生效？", "首次购买在确认付款后生效。套餐、计费周期和席位变更从下一周期生效；减席不能低于已占席数。重新购买或升级不会自动恢复暂停的计划，也不会补跑错过的周期。"], ["付款中断后怎样确认结果？", "在订阅设置与账单中查看付款结果。结果待确认时，先核实订单，避免重复付款；付款失败后可重试。"]];
function pricingLabel(value){return esc(global.SiteLocale?.text(value)??value).replace(/流水线|工作方式|人工确认|在线电脑/g,term=>'<span class="pricing-term">'+term+'</span>');}
function subscriptionComparison(interval){return [
 ['创作与使用',[
  ['创建 AI 员工','不限','不限','不限','不限'],['搭建流水线','不限','不限','不限','不限'],['自定义技能与工作方式','支持','支持','支持','支持'],['安装市场员工与流水线','支持','支持','支持','支持']
 ]],['自动化',[
  ['同时启用的定时计划','3 个','不限','不限','不限'],['员工与流水线定时执行','支持','支持','支持','支持'],['单次手动交办','支持','支持','支持','支持']
 ]],['手机与多电脑',[
  ['查看进展、成果与通知','—','—','支持','支持'],['回复人工确认与取消任务','—','—','支持','支持'],['管理多台在线电脑','—','—','支持','支持']
 ]],['团队协作',[
  ['组织共享员工与流水线','—','—','—','支持'],['组织内共享成果','—','—','—','支持'],['邀请成员与分配权限','—','—','—','支持'],['包含席位','个人','个人','个人','3 席'],['额外席位','—','—','—',interval==='year'?'$182.40/人/年':'$19/人/月']
 ]]
];}
function subscriptionAction(plan,options={}){
 const current=options.currentPlan===plan.id,restricted=options.organization&&plan.id!=='team',canceling=options.canceling&&plan.id!=='team';
 if(current)return {label:'当前套餐',disabled:true};
 if(plan.id==='free')return {label:'免费开始',disabled:!options.live&&!options.guestCheckout};
 if(restricted)return {label:'个人套餐',disabled:true};
 return {label:options.canManage&&plan.id!=='team'?'下周期改为 '+plan.name:'选择 '+plan.name,disabled:!!canceling||!!options.live&&!options.available||!options.live&&!options.guestCheckout};
}
function updateSubscriptionActions(root,options={}){
 if(!root)return;
 for(const plan of subscriptionPlans()){
  const button=root.querySelector(`[data-plan-cta="${plan.id}"]`);if(!button||button.tagName==='A')continue;const action=subscriptionAction(plan,options);
  button.disabled=action.disabled;button.textContent=action.label;button.title=action.label;
  const card=button.closest('[data-subscription-plan]');if(card)card.toggleAttribute('data-current-plan',options.currentPlan===plan.id);
 }
}
function subscriptionPending(){return '<div class="pricing-status-skeleton" aria-busy="true" aria-label="正在读取订阅"><span class="skeleton-block"></span></div>';}
function subscription(options={}){
 const interval=options.interval||(values.interval==='year'?'year':'month'),live=!!options.live,desktop=!!options.desktop;
 const action=key=>live?`accountSelectSubscription('interval','${key}')`:`RunTeamsStaticPages.choose(this,'interval','${key}')`;
 const cycle=`<div class="account-subscription-cycle" role="radiogroup" aria-label="付费周期" onkeydown="${live?"accountSubscriptionKey(event,'interval')":"RunTeamsStaticPages.keys(event)"}">${[['month','月付'],['year','年付']].map(([key,label])=>`<button type="button" role="radio" id="subscription_interval_${key}" aria-checked="${interval===key}" tabindex="${interval===key?0:-1}" onclick="${action(key)}"><span>${label}</span>${key==='year'?'<span class="account-subscription-saving">省 20%</span>':''}</button>`).join('')}</div>`;
 const websiteCopy=global.SiteLocale?global.SITE_PRICING_COPY:null;
 const plans=subscriptionPlans().map(plan=>({...plan,...websiteCopy?.plans?.[plan.id]}));
 const comparison=subscriptionComparison(interval).map((group,index)=>index===2&&websiteCopy?.mobileComparison?websiteCopy.mobileComparison:group);
 const cards=plans.map(plan=>{
  const price=subscriptionPrice(plan,interval),state=subscriptionAction(plan,options);
  const cta=plan.id==='free'&&options.freeHref?`<a class="btn account-subscription-cta" data-plan-cta="free" href="${esc(options.freeHref)}">免费开始</a>`:`<button type="button" class="btn account-subscription-cta${plan.id==='max'?' pri':''}" data-plan-cta="${plan.id}" ${state.disabled?'disabled':''} onclick="accountChooseSubscription('${plan.id}')" title="${esc(state.label)}">${esc(state.label)}</button>`;
  return `<article class="account-subscription-plan${plan.id==='max'?' is-featured':''}" data-subscription-plan="${plan.id}" ${options.currentPlan===plan.id?'data-current-plan':''} aria-labelledby="subscription_plan_${plan.id}"><div class="account-subscription-plan-heading"><h2 id="subscription_plan_${plan.id}">${plan.name}</h2><p>${esc(plan.headline)}</p></div><div class="account-subscription-price"><div class="account-subscription-amount"><strong data-price-amount>${price.amount}</strong><span data-price-unit>${price.unit}</span></div><span data-price-note>${desktop&&plan.id==='free'?'':price.note}</span><span data-price-detail>${price.detail}</span></div><div class="account-subscription-benefits"><p class="account-subscription-includes"${plan.includes?'':' aria-hidden="true"'}>${plan.includes?esc(plan.includes):'&#8203;'}</p><ul>${plan.features.map(text=>`<li>${esc(text)}</li>`).join('')}</ul></div>${cta}</article>`;
 }).join('');
 const summary=options.summary??(options.error?error(options):subscriptionPending());
 const fees=[['RunTeams 套餐','按套餐提供定时执行、<br>手机管理与团队协作。','本页的 Free、Pro、Max、Team'],['Agent 厂商订阅','通过 Codex CLI 或 Claude Code，使用你已有的厂商账号与额度。','由相应厂商单独收费'],['市场员工与流水线','免费项目可直接安装；付费员工与流水线按详情价格另行租用。','套餐不包含市场租用费用']];
 return `<section class="account-subscription${desktop?' is-desktop':''}" aria-label="价格与套餐"><header class="pricing-hero"><rt-dot-field aria-hidden="true"></rt-dot-field><div class="pricing-container"><h1>为你的 AI 团队<span class="pricing-title-break"></span>选择套餐</h1><p>从免费开始，需要更多定时计划、手机管理或团队协作时再升级。</p>${cycle}</div></header><div class="pricing-container pricing-plans-section">${live||!options.guestCheckout?`<div id="accountSubscriptionSummary" aria-live="polite">${summary}</div>`:''}<div class="account-subscription-plans">${cards}</div><div class="pricing-payment-notes"><p>金额以美元计价。Agent 厂商订阅与市场租用单独计费。</p>${desktop?'':'<p>付款前会显示应付金额与续订周期。你可在订阅设置中管理续费。</p>'}</div><button class="pricing-compare-link" type="button" onclick="RunTeamsStaticPages.pricingScroll(this,'pricing-compare')">查看完整权益对比 ↓</button></div><section class="pricing-container pricing-fees" aria-labelledby="pricing-fees-title"><h2 id="pricing-fees-title">三类费用，分别计算</h2><div class="pricing-fee-grid">${fees.map(([title,copy,note],i)=>`<article><span class="pricing-fee-number">0${i+1}</span><h3>${title}</h3><p>${copy}</p><small>${note}</small></article>`).join('')}</div></section><section id="team" class="pricing-team-section"><div class="pricing-container"><div class="pricing-team"><div><h2>在同一工作区，<span class="pricing-title-break"></span>共享员工与成果</h2><p>组织统一订阅，<span class="pricing-title-break"></span>成员在组织内享 Max 权益。<span class="pricing-title-break"></span>个人空间的套餐单独计算。</p><button class="btn" type="button" onclick="RunTeamsStaticPages.pricingScroll(this,'pricing-team-benefits')">查看 Team 权益</button></div><div class="pricing-team-seats"><strong>Team 含 3 席，所有者占 1 席</strong><p data-seat-price>${interval==='year'?'$182.40 / 人 / 年':'$19 / 人 / 月'}</p><small>额外席位与套餐使用相同计费周期。</small><small>加入组织不会自动共享 Agent 厂商账号或文件授权。</small></div></div></div></section><section id="pricing-compare" class="pricing-container pricing-comparison" aria-labelledby="pricing-compare-title"><header><h2 id="pricing-compare-title">逐项比较套餐权益</h2><p>所有套餐都能创建员工、搭建流水线，并使用你已有的 Agent。</p></header><p id="pricing-table-hint" class="pricing-table-hint">左右滑动，比较四档套餐 →</p><div class="pricing-table-scroll" role="region" aria-label="套餐权益对比表，可横向滚动" aria-describedby="pricing-table-hint" tabindex="0"><table><caption class="visually-hidden">Free、Pro、Max 与 Team 完整权益对比</caption><thead><tr>${['权益','Free','Pro','Max','Team'].map((name,i)=>`<th scope="col"${i===4?' data-team-column':''}>${name}</th>`).join('')}</tr></thead>${comparison.map(([name,rows],g)=>`<tbody${g===3?' id="pricing-team-benefits"':''}><tr class="pricing-table-group"><th colspan="5" scope="rowgroup"><span>${name}</span></th></tr>${rows.map(row=>`<tr><th scope="row">${pricingLabel(row[0])}</th>${row.slice(1).map((text,i)=>`<td${g===3&&row[0]==='额外席位'&&i===3?' data-seat-comparison':''}>${text}</td>`).join('')}</tr>`).join('')}</tbody>`).join('')}</table></div><p class="pricing-limit-note">不限计划数不代表不限模型额度、并发或电脑算力。定时执行和手机管理均需执行电脑在线，并具备相应授权。</p></section><section class="pricing-container pricing-faq" aria-labelledby="pricing-faq-title"><div><h2 id="pricing-faq-title">常见问题</h2><p>了解费用、使用条件与订阅规则。</p><div class="pricing-faq-list">${subscriptionFAQ.map(([q,a],i)=>`<details data-pricing-faq="${i}"${(values['pricingFAQ'+i]|| (i===0?'open':'closed'))==='open'?' open':''} ontoggle="RunTeamsStaticPages.pricingFAQ(this)"><summary>${esc(q)}<span aria-hidden="true"></span></summary><p>${esc(a)}</p></details>`).join('')}</div></div></section></section>`;
}
function pricingScroll(button,id){
 const root=button.closest('.account-subscription'),target=root?.querySelector('#'+id);if(!target)return;
 target.scrollIntoView({block:'start',behavior:'instant'});
 if(id==='pricing-team-benefits'){const region=root.querySelector('.pricing-table-scroll'),column=root.querySelector('[data-team-column]');if(region&&column)region.scrollLeft=column.offsetLeft;}
 target.tabIndex=-1;target.focus({preventScroll:true});
}
function pricingFAQ(detail){const index=detail.dataset.pricingFaq;values['pricingFAQ'+index]=detail.open?'open':'closed';}
function updateSubscription(root,interval){
 if(!root)return;
 root.querySelectorAll('.account-subscription-cycle [role="radio"]').forEach(button=>{const selected=button.id==='subscription_interval_'+interval;button.setAttribute('aria-checked',String(selected));button.tabIndex=selected?0:-1;});
 for(const plan of subscriptionPlans()){
  const card=root.querySelector(`[data-subscription-plan="${plan.id}"]`),price=subscriptionPrice(plan,interval);if(!card)continue;
  for(const [field,value]of Object.entries(price))card.querySelector('[data-price-'+field+']').textContent=field==='note'&&plan.id==='free'&&root.classList?.contains('is-desktop')?'':value;
 }
 const seat=root.querySelector('[data-seat-price]'),comparison=root.querySelector('[data-seat-comparison]');if(seat)seat.textContent=interval==='year'?'$182.40 / 人 / 年':'$19 / 人 / 月';if(comparison)comparison.textContent=interval==='year'?'$182.40/人/年':'$19/人/月';
 global.SiteLocale?.apply(root);
}

function documentSkeleton(){return `<div class="docs-table">${shape('文档列表',Array.from({length:4},()=>`<div class="docs-row skeleton-docs-row" data-skeleton-row inert><span class="docs-cell docs-cell-title">${line('name')}</span><span class="docs-cell docs-cell-editor">${line('meta')}</span><span class="docs-cell docs-cell-time">${line('meta')}</span><span class="docs-cell docs-cell-more">${line('meta')}</span></div>`).join(''))}</div>`;}
function publisherSkeleton(){return `<div class="market-creator-table-wrap"><table class="market-creator-table"><tbody data-skeleton-list aria-busy="true" aria-label="正在读取发布资产">${Array.from({length:4},()=>`<tr aria-hidden="true" inert>${Array.from({length:6},()=>`<td>${line('name')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function page(value,options={}){
 const kind=global.RunTeamsSkeletons.normalize(value),region=global.RunTeamsSkeletons.region;
 let failed=false;const body=(html)=>{if(options.error&&failed)return '';if(options.error)failed=true;return data(html,options);},rows=(label,count=3)=>shape(label,Array.from({length:count},()=>`<div class="route-sk-row" data-skeleton-row inert>${line('avatar')}<div class="route-sk-copy-group">${line('name')}${line('copy')}</div></div>`).join(''));
 const fields=(labels)=>labels.map(label=>`<div class="field"><label>${label}</label>${options.error?'':shape(label,line(label==='详细介绍'?'editor':'field'))}</div>`).join('');
 switch(kind){
 case 'marketplace':return global.marketplaceStartupMain();
 case 'docs':return frame(kind,head('文档','查看和管理对话与员工交付的文档。',search('docs','搜索文档名和正文','environment-search','docs_search'))+body(documentSkeleton()),'environment-page docs-page list-page','environment-content docs-content list-page-content');
 case 'trash':return frame(kind,`<header class="trash-head list-page-header"><div class="trash-head-copy"><h1>垃圾箱</h1><div class="trash-head-subline"><p>移除的项目通常保留 30 天；含文档的项目不会自动清除。</p></div></div></header>`+body(region('trash')),'trash-page list-page','trash-content list-page-content');
 case 'automations':return frame(kind,head('旧自动化','这里保留以前创建的计划；新的自动化请在员工工作中创建。')+body(rows('自动化',4)),'environment-page automation-page');
 case 'billing-subscription':return frame(kind,subscription(options),'environment-page billing-page subscription-page list-page','account-page-content list-page-content');
 case 'billing-rentals':case 'billing-records':{
  const tab=kind.slice(8),navigation=`<div class="account-billing-navigation">${nav([['rentals','租用资产','/billing'],['records','资金记录','/billing/records']],tab,'账单内容','account-billing-tabs')}</div>`;
  return frame(kind,`<header class="account-page-header list-page-header"><h1>账单</h1><p>查看租用资产和资金记录。</p></header>`+navigation+(body(rows(tab==='records'?'资金记录':'资产',4))),'environment-page billing-page list-page','account-page-content list-page-content');
 }
 case 'wallet':return frame(kind,`<header class="account-page-header list-page-header"><h1>钱包</h1><p>可用余额（USD）</p></header>`+body(`<section class="account-wallet-balance account-wallet-page-balance">${shape('钱包余额',line('amount'))}</section><section class="account-wallet-records"><h2>资金记录</h2>${rows('资金记录',4)}</section>`),'environment-page wallet-page list-page','account-page-content list-page-content');
 case 'marketplace-published':return frame(kind,`<header class="market-creator-head list-page-header list-page-header--controls"><div class="list-page-heading"><h1>我发布的资产</h1></div><div class="market-creator-actions list-page-controls"><a class="btn pri" href="/marketplace/publish">发布资产</a></div></header><section class="market-creator-list-body"><div class="market-creator-tools">${search('published','搜索已发布的资产','market-creator-search')}${staticTabs(['全部','已上架','已下架'],'上架状态')}</div>${body(publisherSkeleton())}</section>`,'environment-page marketplace-page market-creator-page list-page','marketplace-content market-creator-content list-page-content');
 case 'marketplace-choose':return frame(kind,back('/marketplace/published')+`<header class="market-creator-head"><div><h1>发布资产</h1><p>选择要发布的员工或流水线。</p></div></header><section class="market-creator-list-body">${staticTabs(['全部','员工','流水线'],'资产类型')}${body(region('source-list'))}</section>`,'environment-page marketplace-page market-creator-page','marketplace-content market-creator-content');
 case 'marketplace-publish':return frame(kind,back('/marketplace/published')+`<header class="market-creator-head"><h1>${/\/edit(?:[?#]|$)/.test(global.location?.href||'')?'编辑市场信息':line('name')}</h1></header>`+body(`<div class="market-creator-form-grid"><div class="market-creator-form">${shape('资产身份',line('name'))}${fields(['市场名称','一句话介绍','详细介绍'])}<div class="field"><span>定价</span>${staticTabs(['免费','每月订阅'],'定价')}</div><button class="btn pri" disabled aria-label="正在读取发布操作">${line('action')}</button></div><aside class="market-creator-preview"><h3>预览</h3>${region('market-cards',1)}</aside></div>`),'environment-page marketplace-page market-creator-page','marketplace-content market-creator-content');
 case 'marketplace-manage':return frame(kind,back('/marketplace/published')+head(line('name'))+staticTabs(['概览','版本','评价'],'资产管理')+body(rows('资产名称与状态')+region('versions')),'environment-page marketplace-page market-creator-page','marketplace-content market-creator-content');
 case 'marketplace-detail':return frame(kind,back('/marketplace')+body(`<section class="marketplace-detail-hero">${rows('资产名称与说明',1)}</section>`)+`<div class="marketplace-detail-columns"><div class="marketplace-detail-primary">${staticTabs(['概览','评价'],'资产详情')}${body(region('skill-summary'))}</div><aside class="marketplace-detail-sidebar"><h3>价格</h3>${body(shape('价格',line('amount')))}<h3>发布者</h3>${body(rows('发布者',1))}<dl><dt>当前版本</dt><dd>${body(shape('版本',line('meta')))}</dd><dt>最近更新</dt><dd>${body(shape('更新时间',line('meta')))}</dd></dl></aside></div>`,'environment-page marketplace-page marketplace-detail-page','marketplace-content marketplace-detail-content');
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
function title(kind){return ({'conversation-new':'新对话',conversation:'对话','employee-examples':'员工',docs:'文档','document-reader':'文档',pipeline:'流水线','pipeline-new':'新建流水线',wallet:'钱包',trash:'垃圾箱',automations:'旧自动化','employee-settings':'员工设置','run-detail':'工作记录','design-system':'设计系统','billing-subscription':'升级计划'})[kind]||(kind.startsWith('billing-')?'账单':kind.startsWith('marketplace')?'市场':'工作区');}
function keys(event){if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const buttons=[...event.currentTarget.querySelectorAll('button:not([disabled]),a[role=tab]')],at=buttons.indexOf(event.target);if(at<0)return;event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?buttons.length-1:(at+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[index].click();buttons[index].focus({preventScroll:true});}
function set(name,value,notify=true){values[name]=String(value||'');if(notify)change?.(name,values[name]);}
function select(button,name,value){set(name,value);button.closest('[role="tablist"]')?.querySelectorAll('[role="tab"]').forEach(el=>{el.setAttribute('aria-selected',String(el===button));});}
function choose(button,name,value){set(name,value);if(name==='interval')updateSubscription(button.closest('.account-subscription'),value);}

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

global.RunTeamsStaticPages={composer,captureComposer,restoreComposer,runtimePending,subscriptionPlans,subscriptionPrice,subscriptionAction,subscriptionComparison,subscriptionFAQ,subscriptionPending,subscription,updateSubscription,updateSubscriptionActions,pricingScroll,pricingFAQ,page,title,fail,error,keys,icon,search,documentSkeleton,publisherSkeleton,values,set,select,choose,capture,restore,connect:callback=>{change=callback;},reset:()=>{for(const key of Object.keys(values))delete values[key];}};
})(window);
