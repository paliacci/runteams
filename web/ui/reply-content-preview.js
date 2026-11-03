/* Explicit, non-persistent fixture rendered through production conversationMessages. */
if(new URLSearchParams(location.search).get('preview')==='rich-reply')window.RunTeamsConversationPreview=(()=>{
 let theme='light',narrow=false;
 const columns=[{key:'name',label:'需求方向'},{key:'category',label:'分类'},{key:'signals',label:'相关反馈',format:'number'},{key:'pain',label:'痛点强度',format:'number'}];
 const rows=[{name:'旅行优惠核验',category:'旅行',signals:38,pain:84},{name:'行程变更提醒',category:'旅行',signals:27,pain:72},{name:'写作上下文延续',category:'效率',signals:34,pain:79},{name:'会议行动项跟进',category:'效率',signals:22,pain:68},{name:'订阅到期提醒',category:'生活',signals:18,pain:61},{name:'家庭账单分摊',category:'生活',signals:15,pain:56},{name:'离线旅行清单',category:'旅行',signals:12,pain:49}];
 const view=data=>'```runteams-view\n'+JSON.stringify({version:1,columns,rows,...data})+'\n```';
 function sample(){return '**建议先比较旅行优惠核验和写作上下文延续。** 下面把候选方向、对比图和筛选工具直接放在这条回复里，方便你查看。\n\n'+view({type:'table',title:'候选需求',caption:'点击表头排序，点击需求名称查看详情。数据为交互演示样例。'})+'\n\n反馈数量和痛点强度代表不同信息，可以切换指标对比。\n\n'+view({type:'chart',title:'哪些方向更值得关注',caption:'示例评分用于展示交互，不代表真实市场判断。',x:'name',metrics:['signals','pain'],rows:rows.slice(0,4)})+'\n\n也可以自己缩小范围，看看哪些方向满足你的条件。\n\n'+view({type:'explorer',title:'按你的关注点筛选',caption:'选择分类、拖动最低分，结果立即更新；不会提交任务或修改业务数据。',category:'category',threshold:'pain'})+'\n\n这些操作都在当前回复里完成。普通文字、代码和原有消息操作仍然保留。';}
 function paint(){
  const old=document.getElementById('reply_preview_scroll'),top=old?.scrollTop||0;
  document.documentElement.dataset.theme=theme;document.title='AI 回复 · 富内容预览';
  S.chatMsgs=[{id:'preview-user',role:'user',text:'把候选方向整理给我，我想直接在回复里比较和筛选。'},{id:'preview-reply',role:'bot',text:sample(),metadata:{}}];
  document.getElementById('app').innerHTML=`<main class="reply-preview-page ${narrow?'is-narrow':''}"><header class="reply-preview-header"><div><strong>对话内容预览</strong><span>示例数据</span></div><nav aria-label="预览操作"><button data-reply-preview-theme>${theme==='dark'?'浅色':'深色'}</button><button data-reply-preview-width>${narrow?'桌面宽度':'窄屏宽度'}</button><a href="/">返回应用</a></nav></header><div class="reply-preview-scroll" id="reply_preview_scroll"><div class="conversation-messages">${conversationMessages(S.chatMsgs,{surface:'chat',chatId:null})}</div></div><footer><div>这是交互预览，不会发送消息或调用模型。</div></footer></main>`;
  document.getElementById('reply_preview_scroll').scrollTop=top;
 }
 function boot(){
  const network=window.fetch.bind(window);window.fetch=(resource,options)=>{const url=new URL(typeof resource==='string'?resource:resource.url,location.href);if(url.origin===location.origin&&url.pathname.startsWith('/api/'))return Promise.resolve(new Response(JSON.stringify({error:'预览不执行业务操作'}),{status:403,headers:{'Content-Type':'application/json'}}));return network(resource,options);};
  const style=document.createElement('link');style.rel='stylesheet';style.href='/ui/reply-content-preview.css?v=20261029-1';document.head.appendChild(style);
  S.booting=false;S.conversationPanel=null;S.chatId=null;S.chatBusy=false;S.account={...ACCOUNT_DEFAULT,signed_in:false};
  theme=new URLSearchParams(location.search).get('theme')==='dark'?'dark':'light';narrow=new URLSearchParams(location.search).get('width')==='narrow';render=paint;
  document.addEventListener('click',event=>{if(event.target.closest('[data-reply-preview-theme]')){theme=theme==='light'?'dark':'light';paint();}if(event.target.closest('[data-reply-preview-width]')){narrow=!narrow;paint();}});
  paint();
 }
 return {active:true,boot,sample,paint};
})();
