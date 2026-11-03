/* Read-only fixture gallery. Every message/card uses the production renderer. */
window.RunTeamsConversationPreview=(()=>{
  let groups=[],theme='light',selection='all',width='desktop';
  const sample=(id,label,data)=>({id,role:'bot',text:'',debugLabel:label,...data});
  const choices=[{label:'当前员工',description:'检查这名员工的配置与技能'},{label:'全部员工',description:'检查当前工作区的所有员工'}];
  const question=(id,label,questions,options={})=>{
    const request={id:`preview-${id}`,status:'pending',isBlocking:false,questions};
    const message=sample(id,label,{streaming:true,trace:{structured:true,complete:false,steps:[],requests:[request]},previewQuestion:true});
    const state=conversationQuestionState(message,request);
    Object.assign(state,options);
    return message;
  };
  function samples(){
    const now=Date.now(),process='我会先核对原文信息，再整理时间安排和交付要求。',final='整理结果如下：\n\n1. 项目目标：保留原文描述。\n2. 时间安排：按原文顺序列出。\n3. 交付要求：保留原有约定。\n\n原始文件保持不变。';
    const trace=(extra={})=>({steps:[],activity:[],requests:[],complete:false,startedAt:now-354000,...extra});
    const authoringTrace=()=>trace({activity:[{type:'text',id:'intro',text:'我会先核对需求和可用能力，再创建这名员工。'},...['ctx','skill','schema','ref','submit-a','submit-b'].map(id=>({type:'step',id}))],steps:[
      {id:'ctx',stepKind:'tool',status:'completed',label:'读取当前上下文',meta:{tool:'runteams_get_context',arguments:{}}},
      {id:'skill',stepKind:'command',status:'completed',label:'cat SKILL.md',meta:{command:'cat /workspace/skills/employee-authoring/SKILL.md',commandActions:[{type:'read',path:'/workspace/skills/employee-authoring/SKILL.md'}]}},
      {id:'schema',stepKind:'tool',status:'completed',label:'编辑员工资源',meta:{tool:'runteams_creator_source',arguments:{action:'schema',kind:'skill'}}},
      {id:'ref',stepKind:'tool',status:'completed',label:'编辑员工资源',meta:{tool:'runteams_creator_source',arguments:{action:'reference',kind:'authoring'}}},
      ...['submit-a','submit-b'].map((id,index)=>({id,stepKind:'tool',status:index?'running':'completed',label:'编辑员工资源',meta:{tool:'runteams_creator_source',arguments:{action:'submit',files:{'SKILL.md':'ZXhhbXBsZQ=='}}}})),
    ]});
    return [
      {key:'flow',label:'回复流程',description:'真实组件的工程样例：思考 → 阶段性文字 → 流式正文 → 完成折叠',messages:[
        sample('thinking','等待回复 / 正在思考高光',{streaming:true,trace:trace()}),
        sample('commentary','过程消息',{streaming:true,trace:trace({activity:[{type:'text',id:'process',text:process}],runtimeStatus:{phase:'thinking',id:'thinking'}})}),
        sample('stream','最终正文逐段输出',{streaming:true,text:'这份说明包含项目目标、时间安排和交付要求。\n\n关于时间安排，',trace:trace()}),
        sample('complete','正常完成 / 过程收起',{text:final,trace:trace({complete:true,durationSec:354,activity:[{type:'text',id:'process',text:process}]})}),
        sample('complete-open','正常完成 / 过程展开',{text:final,previewOpen:true,trace:trace({complete:true,durationSec:354,activity:[{type:'text',id:'process',text:process}]})}),
        sample('complete-plain','正常完成 / 无过程',{text:'已整理完成。',trace:trace({complete:true,durationSec:12})}),
        ...['running','done','failed','cancelled'].map(status=>sample('tool-'+status,({running:'工具执行中',done:'工具已完成',failed:'工具未完成',cancelled:'工具已停止'})[status],{streaming:status==='running',previewOpen:status==='done',trace:trace({complete:status!=='running',cancelled:status==='cancelled',failed:status==='failed',durationSec:12,steps:[{id:'file',stepKind:'file',label:'更新项目说明',status,detail:'README.md',output:status==='done'?'项目说明已更新。':''}]})})),
        sample('optimizing','正在优化会话 / 共用文字高光',{streaming:true,trace:trace({runtimeStatus:{phase:'compacting',id:'compaction'}})}),
      ]},
      {key:'tools',label:'执行反馈',description:'仅展示简短的动作反馈，无技术详情',messages:[
        sample('process-compact','创建过程 / 默认精简',{streaming:true,trace:authoringTrace()}),
        sample('tool-image','查看图像',{previewOpen:true,trace:trace({complete:true,durationSec:1,steps:[{id:'image',stepKind:'image',status:'completed',label:'imageView',meta:{path:'/workspace/example.png'}}]})}),
        sample('tool-mixed','读取文件和运行命令',{previewOpen:true,trace:trace({complete:true,durationSec:2,steps:[{id:'read',stepKind:'command',status:'completed',label:'cat /workspace/readme.md',meta:{command:'cat /workspace/readme.md',commandActions:[{type:'read',path:'/workspace/readme.md'}]}},{id:'run',stepKind:'command',status:'completed',label:'python3 check.py',meta:{command:'python3 check.py',commandActions:[{type:'unknown',command:'python3 check.py'}]}}]})}),
        sample('tool-read','读取文件',{previewOpen:true,trace:trace({complete:true,durationSec:2,steps:[{id:'long-read',stepKind:'command',status:'completed',label:"/bin/zsh -lc 'cat /Users/example/Projects/runteams/agent_skills/runteams-employee-authoring/SKILL.md'",meta:{command:"/bin/zsh -lc 'cat /Users/example/Projects/runteams/agent_skills/runteams-employee-authoring/SKILL.md'",cwd:'/Users/example/Projects/runteams',commandActions:[{type:'read',name:'SKILL.md',path:'/Users/example/Projects/runteams/agent_skills/runteams-employee-authoring/SKILL.md'}],exitCode:0,durationMs:1240},output:'# 员工编写说明\n\n以下内容为静态 UI 样例。'}]})}),
        sample('tool-script','运行命令',{previewOpen:true,trace:trace({complete:true,durationSec:3,steps:[{id:'script',stepKind:'command',status:'completed',label:'python3 脚本',meta:{command:"/bin/zsh -lc 'python3 - <<\"PY\"\nfrom pathlib import Path\nproject = Path(\"/Users/example/Projects/runteams\")\nfor path in project.glob(\"**/SKILL.md\"):\n    print(path)\nPY'",cwd:'/Users/example/Projects/runteams',commandActions:[{type:'unknown'}],exitCode:0,durationMs:2150},output:Array.from({length:35},(_,i)=>'示例输出第 '+(i+1)+' 行').join('\n')}]})}),
        sample('tool-context','查看资料',{previewOpen:true,trace:trace({complete:true,durationSec:1,steps:[{id:'context',stepKind:'tool',status:'completed',label:'读取当前上下文',meta:{namespace:'',tool:'runteams_get_context',arguments:{}},output:'当前工作区：示例工作区'}]})}),
        sample('tool-long-title','搜索资料',{previewOpen:true,streaming:true,trace:trace({steps:[{id:'search-long',stepKind:'command',status:'running',label:'搜索',meta:{command:'rg -n "'+('需要核对的示例字段与状态'.repeat(12))+'" /Users/example/Projects/runteams/web/modules',commandActions:[{type:'search',query:'需要核对的示例字段与状态'.repeat(12),path:'/Users/example/Projects/runteams/web/modules'}]}}]})}),
      ]},
      {key:'content',label:'Markdown 正文',description:'一个组件覆盖所有内容格式，复制与长代码为同一组件内的操作',messages:[
        sample('user','用户消息',{role:'user',text:'帮我整理这份说明，保留原始信息。'}),
        sample('attachments','用户消息 / 文件与文件夹',{role:'user',text:'参考这些资料。',attachments:[{name:'项目说明.md',size:2048},{kind:'folder',name:'员工资源',size:4096,file_count:4},{kind:'image',name:'示例图标.svg',preview:'/favicon.svg',size:1024}]}),
        sample('markdown','混合正文',{text:'### 核对结果\n\n**保留原始信息**，按原文顺序整理。\n\n> 以下内容仅用于样式核对。\n\n1. 项目目标\n2. 时间安排\n\n- 原始资料\n- 交付要求\n\n| 检查项 | 结果 |\n| --- | --- |\n| 原文 | 保留 |\n| 输出 | 已整理 |\n\n```json\n{\n  "files": ["result.txt"]\n}\n```\n\n[查看文件](#preview-content) / `result.txt`\n\n![RunTeams 图标](/favicon.svg)'}),
        sample('long-code','长代码 / 复制与展开',{text:'```text\n'+Array.from({length:22},(_,i)=>'示例内容第 '+(i+1)+' 行').join('\n')+'\n```'}),
      ]},
      {key:'questions',label:'必要提问',description:'自由输入、单选、多选、多题共用提问组件，无语音',messages:[
        question('text','自由输入',[{id:'note',question:'你希望结果怎样组织？',options:[]}]),
        question('single','单选',[{id:'scope',question:'先检查哪个范围？',options:choices}]),
        question('multi','多选',[{id:'outputs',question:'需要哪些交付内容？',multiSelect:true,options:[{label:'核对结果'},{label:'修改说明'},{label:'交付文件'}]}],{selected:{outputs:[0,2]}}),
        question('pages','多题 / 第一题',[{id:'scope',question:'先检查哪个范围？',options:choices},{id:'note',question:'还需要补充哪些要求？',options:[]}]),
        question('pages-last','多题 / 最后一题',[{id:'scope',question:'先检查哪个范围？',options:choices},{id:'note',question:'还需要补充哪些要求？',options:[]}],{page:1,custom:{note:'保留原始文件。'}}),
        question('secret','敏感信息输入',[{id:'secret',question:'请输入测试密钥',isSecret:true,options:[]}]),
        question('collapsed','提问已收起',[{id:'scope',question:'先检查哪个范围？',options:choices}],{collapsed:true}),
        sample('answered','提问已回答 / 继续处理',{streaming:true,trace:trace({current:'正在继续处理',requests:[{id:'answered',status:'answered',questions:[{id:'scope',question:'检查哪个范围？'}],answers:{scope:{answers:['当前员工']}}}]})}),
        question('sending','提交中 / 共用文字高光',[{id:'scope',question:'需要检查哪些员工？',options:choices}],{sending:true}),
        question('error','提交失败 / 保留已填答案',[{id:'scope',question:'需要检查哪些员工？',options:choices}],{error:'暂时未能发送，原回答已保留。',selected:{scope:[1]}}),
      ]},
      {key:'branches',label:'停止与两种异常',description:'停止／中断保留原文；只有原生错误分类触发专用提示，无重试／核对／支付卡',messages:[
        sample('stopping','正在停止',{streaming:true,stopping:true,text:'这份说明包含项目目标。',trace:trace()}),
        sample('stopped','停止后保留部分正文',{text:'这份说明包含项目目标、时间安排和交付要求。\n\n关于时间安排，',stopped:true,trace:trace({complete:true,cancelled:true})}),
        sample('interrupted','中断重开 / 保留已保存正文',{text:'这份说明包含项目目标、时间安排和交付要求。\n\n关于时间安排，',trace:trace({complete:true,failed:true}),systemNotice:{kind:'runtime_interrupted',text:'工程夹具中断'}}),
        sample('busy','模型繁忙',{trace:trace({complete:true,failed:true,providerError:{code:'serverOverloaded',willRetry:false}})}),
        sample('retrying','原生自动重试 / 继续等待',{streaming:true,trace:trace({providerError:{code:'serverOverloaded',willRetry:true}})}),
        sample('generic-error','普通错误 / 行内提示',{ephemeral:true,systemNotice:{kind:'error',text:'暂时无法连接服务，请稍后再试。'},trace:trace({complete:true,failed:true})}),
        sample('quota-unknown','额度耗尽 / 重置时间未知',{trace:trace({complete:true,failed:true,providerError:{code:'usageLimitExceeded',willRetry:false},rateLimits:[{usedPercent:100,resetsAt:null}]})}),
        sample('quota','额度耗尽 / 有真实结构化时间时显示',{trace:trace({complete:true,failed:true,providerError:{code:'usageLimitExceeded',willRetry:false},rateLimits:[{usedPercent:100,resetsAt:Math.floor(now/1000)+3600}]})}),
      ]},
    ];
  }
  function syncUrl(){
    if(!window.history?.replaceState)return;
    const url=new URL(location.href);url.searchParams.set('state',selection);url.searchParams.set('theme',theme);url.searchParams.set('width',width);
    window.history.replaceState(null,'',url);
  }
  function select(value){
    selection=value==='all'||groups.some(group=>'group:'+group.key===value||group.messages.some(message=>message.id===value))?value:'all';
    syncUrl();renderPreview(true);
  }
  function setTheme(value){theme=value==='dark'?'dark':'light';syncUrl();renderPreview();}
  function setWidth(value){width=value==='narrow'?'narrow':'desktop';syncUrl();renderPreview();}
  function reset(){groups=samples();renderPreview();}
  function renderPreview(resetScroll=false){
    const scroll=document.getElementById('conversation_preview_scroll'),top=resetScroll?0:scroll?.scrollTop||0;
    const nav=document.getElementById('conversation_preview_nav'),navTop=nav?.scrollTop||0;
    const active=document.activeElement,questionId=active?.closest('[data-question-id]')?.dataset.questionId;
    const navFocused=!!active?.closest?.('[data-preview-select]'),controlFocus=['data-preview-theme','data-preview-width','data-preview-reset'].find(attr=>active?.hasAttribute?.(attr));
    const focusTag=active?.tagName,range=active&&['TEXTAREA','INPUT'].includes(focusTag)?[active.selectionStart,active.selectionEnd]:null;
    S.chatMsgs=groups.flatMap(group=>group.messages);
    S.chatMsgs.forEach((message,index)=>message.originalIndex=index);
    document.title='消息 UI / Mock';document.documentElement.dataset.theme=theme;
    const visible=groups.map(group=>({...group,messages:group.messages.filter(message=>selection==='all'||selection==='group:'+group.key||selection===message.id)})).filter(group=>group.messages.length);
    const navButton=(value,label,extra='')=>`<button type="button" data-preview-select="${esc(value)}" aria-pressed="${selection===value}" ${extra}>${esc(label)}</button>`;
    const directory=navButton('all','全部消息 / '+S.chatMsgs.length)+groups.map(group=>`<div class="message-preview-nav-group">${navButton('group:'+group.key,group.label,'class="message-preview-group-link"')}${group.messages.map(message=>navButton(message.id,message.debugLabel)).join('')}</div>`).join('');
    const gallery=visible.map(group=>`<section class="conversation-gallery-group" id="preview-${group.key}" aria-labelledby="label-${group.key}"><div class="conversation-gallery-group-head" id="label-${group.key}"><strong>${esc(group.label)}</strong><small>${group.messages.length} 个样例</small></div><div class="conversation-gallery-group-body">${group.messages.map(message=>{
      const request=message.trace?.requests?.[0],state=request&&conversationQuestionState(message,request);
      const dock=message.previewQuestion&&!state.collapsed?`<div class="agent-question-dock">${conversationDockCard(message,message.originalIndex,'chat',request)}</div>`:'';
      return `<article class="conversation-gallery-sample" data-preview-sample="${esc(message.id)}" ${message.previewOpen?'data-preview-open':''}><div class="conversation-gallery-sample-label">${esc(message.debugLabel)}</div><div class="conversation-messages">${conversationMessages([message],{surface:'chat',chatId:null})}${conversationProviderError(message)?.code==='usageLimitExceeded'&&!conversationMessageFailure(message,message.originalIndex,'chat',null)?conversationProviderNotice(message):''}</div>${dock}</article>`;
    }).join('')}</div></section>`).join('');
    document.getElementById('app').innerHTML=`<main class="conversation-workspace-main message-ui-preview" data-preview-width="${width}"><header class="message-preview-toolbar"><strong>消息 UI <span>Mock</span></strong><div><button type="button" data-preview-theme>${theme==='dark'?'切换浅色':'切换深色'}</button><button type="button" data-preview-width>${width==='narrow'?'切换桌面 720':'切换窄屏 364'}</button><button type="button" data-preview-reset>重置样例</button><button type="button" data-preview-reload>刷新样式</button><a href="/" data-preview-exit>返回应用</a></div></header><div class="message-preview-body"><nav class="message-preview-nav" id="conversation_preview_nav" aria-label="消息状态目录">${directory}</nav><section class="rail-assistant conversation-main is-debug-preview is-message-gallery"><div class="message-preview-hint">${visible.reduce((sum,group)=>sum+group.messages.length,0)} / ${S.chatMsgs.length} 个样例 / 复用正式组件 / 不调用模型、不保存业务数据</div><div class="rail-assistant-scroll" id="conversation_preview_scroll"><div class="message-preview-canvas"><div class="conversation-messages is-debug-gallery"><div class="conversation-gallery-groups">${gallery}</div></div></div></div></section></div></main>`;
    document.getElementById('conversation_preview_scroll').scrollTop=top;
    document.getElementById('conversation_preview_nav').scrollTop=navTop;
    document.querySelectorAll('[data-preview-open] details.agent-work-history').forEach(node=>node.open=true);
    if(navFocused)document.querySelectorAll('[data-preview-select]').forEach(node=>{if(node.dataset.previewSelect===selection)node.focus({preventScroll:true});});
    if(controlFocus)document.querySelector(`button[${controlFocus}]`)?.focus({preventScroll:true});
    if(questionId&&range){const field=document.querySelector(`[data-question-id="${questionId}"] ${focusTag.toLowerCase()}`);field?.focus({preventScroll:true});field?.setSelectionRange(...range);}
  }
  function boot(){
    // Normal startup/account/native-settings hooks are skipped by the entry page.
    const network=window.fetch.bind(window);
    window.fetch=(resource,options)=>{
      const url=new URL(typeof resource==='string'?resource:resource.url,location.href);
      if(url.origin===location.origin&&url.pathname.startsWith('/api/'))return Promise.resolve(new Response(JSON.stringify({error:'Mock 页面不执行真实操作。'}),{status:403,headers:{'Content-Type':'application/json'}}));
      return network(resource,options);
    };
    S.booting=false;S.conversationPanel=null;S.chatId=null;S.chatBusy=false;
    S.account={...ACCOUNT_DEFAULT,signed_in:false,name:'Mock 预览'};
    const params=new URLSearchParams(location.search);
    theme=params.get('theme')==='dark'?'dark':'light';width=params.get('width')==='narrow'?'narrow':'desktop';
    groups=samples();
    selection=params.get('state')||'all';if(!groups.some(group=>'group:'+group.key===selection||group.messages.some(message=>message.id===selection)))selection='all';
    render=renderPreview;
    conversationQuestionRefresh=()=>renderPreview();
    // Each fixture is independent; reopening one must not collapse other samples.
    conversationQuestionOpen=(surface,index,id)=>{
      const message=S.chatMsgs[index],request=message?.trace?.requests?.find(item=>item.id===id&&item.status==='pending');if(!request)return;
      conversationQuestionState(message,request).collapsed=false;renderPreview();
    };
    conversationQuestionSubmit=async(surface,index)=>{
      const message=S.chatMsgs[index],request=message&&conversationQuestionRequest(message,index);
      if(!request)return;
      const state=conversationQuestionState(message,request);
      if(state.sending)return;
      if(state.page<request.questions.length-1){state.page++;renderPreview();return;}
      state.error='仅预览：答案不会发送给模型。';renderPreview();
    };
    document.addEventListener('click',event=>{
      const choice=event.target.closest('[data-preview-select]');if(choice){select(choice.dataset.previewSelect);return;}
      if(event.target.closest('[data-preview-theme]')){setTheme(theme==='dark'?'light':'dark');return;}
      if(event.target.closest('[data-preview-width]')?.tagName==='BUTTON'){setWidth(width==='narrow'?'desktop':'narrow');return;}
      if(event.target.closest('[data-preview-reset]')){reset();return;}
      if(event.target.closest('[data-preview-reload]')){location.reload();return;}
      const target=event.target.closest('button,a');if(!target)return;
      if(target.matches('[data-preview-exit]')||target.getAttribute('href')?.startsWith('#'))return;
      const action=target.getAttribute('onclick')||'';
      if(/^(?:conversationQuestion(?:Select|Page|Open|Collapse|Submit)|copyConversation(?:Message|Code)|toggleConversationCode)\(/.test(action))return;
      event.preventDefault();event.stopImmediatePropagation();
    },true);
    renderPreview();
  }
  return {boot,samples,select,setTheme,setWidth,reset};
})();
