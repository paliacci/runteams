const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

test('employee overview answers one request, including all its questions, in one submission', async () => {
  const request = {id: 'meeting', status: 'pending', questions: [
    {id: 'time', question: '时段', options: [{label: '上午'}, {label: '下午'}]},
    {id: 'room', question: '会议室', options: [{label: '一楼'}]},
  ]};
  const other = {id: 'reply', status: 'pending', questions: [{id: 'reply', question: '回复', options: []}]};
  const message = {streaming: true, trace: {requests: [request, other]}};
  const panel = {id: 7, messages: [message]};
  const sent = [];
  const context = vm.createContext({
    window: {RunTeamsAssetOverview: {employee: () => true}},
    S: {conversationPanel: panel}, ICON: () => '', esc: String, renderMarkdown: String,
    api: async (url, method, body) => {sent.push({url, method, body});return {accepted: true};},
  });
  vm.runInContext(fs.readFileSync('web/modules/conversation.js', 'utf8'), context);
  context.conversationQuestionRefresh = () => {};
  const show = () => context.conversationQuestionDock('panel');
  assert.match(show(), /会议室/);
  assert.doesNotMatch(show(), /下一步|上一步|data-question-id="reply"/);
  context.conversationQuestionSelect('panel', 0, 1, 0);
  await context.conversationQuestionSubmit('panel', 0);
  assert.equal(sent.length, 0);
  context.conversationQuestionSelect('panel', 0, 0, 1);
  await context.conversationQuestionSubmit('panel', 0);
  assert.equal(sent.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(sent[0])), {
    url: '/api/chat/7/interaction', method: 'POST',
    body: {request_id: 'meeting', answers: {time: {answers: ['下午']}, room: {answers: ['一楼']}}},
  });
  assert.equal(other.status, 'pending');
  assert.match(show(), /data-question-id="reply"/);
});

test('late activity reads cannot replace the next asset’s records', async () => {
  const first = {type: 'employee-overview', id: 1};
  const second = {type: 'employee-overview', id: 2};
  const state = {sel: first};
  let finish;
  const context = vm.createContext({
    window: {}, S: state, RunTeamsSourcePipelines: {current: () => null},
    RunTeamsWorkRecords: {scopeForPanel: () => ({employee_id: 1}), readResults: data => data},
    api: () => new Promise(resolve => {finish = resolve;}), render() {},
  });
  vm.runInContext(fs.readFileSync('web/ui/asset-overview.js', 'utf8'), context);
  const pending = context.window.RunTeamsAssetOverview.load();
  state.sel = second;
  finish({results: [{key: 'private-to-first'}]});
  await pending;
  assert.equal(second.overviewRecords, undefined);
  assert.equal(first.overviewRecords, undefined);
});

test('overview lists finalized documents and files directly, with overflow only above two items', () => {
  const selection = {type: 'employee-overview', overviewLoading: true};
  const context = vm.createContext({
    RunTeamsHost: {session: {workspace: () => true}},
    RunTeamsEnvironment: {markup: () => ''},
    window: {}, S: {sel: selection}, esc: String, ICON: () => '',
    RunTeamsEmptyStates: {markup: kind => `<figure data-kind="${kind}"></figure>`},
    RunTeamsSkeletons: {region: () => '<div aria-busy="true"></div>'},
    RunTeamsEmployeeAutomation: {overviewSection: () => ''},
    RunTeamsWorkRecords: {rowMarkup: row => `<button>${row.key}</button>`},
  });
  context.window.addEventListener=()=>{};
  vm.runInContext(fs.readFileSync('web/ui/work-records.js','utf8'),context);
  context.RunTeamsWorkRecords.deliveryRowMarkup=context.window.RunTeamsWorkRecords.deliveryRowMarkup;
  vm.runInContext(fs.readFileSync('web/ui/asset-overview.js', 'utf8'), context);
  const opened=[];
  context.openDocumentReaderById=id=>opened.push(id);
  context.openResultEvidenceFile=(id,files)=>opened.push([id,files[0].name]);
  const hostSource=fs.readFileSync('web/index.html','utf8');
  for(const name of ['resultEvidencePreviewKind','resultEvidenceIcon']){
    vm.runInContext(hostSource.match(new RegExp('function '+name+'\\([^]*?\\n}'))[0],context);
  }
  const render = () => context.window.RunTeamsAssetOverview.shell({title:'Employee',avatar:''});
  assert.match(render(), /overview-loading-bar/);
  assert.doesNotMatch(render(), /assetOverview\.(activity|all)|<figure/);
  assert.doesNotMatch(render(), /class="overview-section overview-delivery-section"/);
  selection.overviewLoading = false;
  selection.overviewError = true;
  assert.match(render(), /assetOverview.retry/);
  assert.doesNotMatch(render(), /<figure/);
  selection.overviewError = false;
  selection.overviewRecords = [];
  assert.match(render(), /<figure data-kind="records"/);
  assert.match(render(), /assetOverview.activity/);
  assert.doesNotMatch(render(), /assetOverview.all/);
  assert.doesNotMatch(render(), /class="overview-section overview-delivery-section"/);
  for(const count of [1,2]){
    selection.overviewRecords=Array.from({length:count},(_,i)=>({key:'finished-'+i,outputs:[]}));
    assert.doesNotMatch(render(), /assetOverview.all/);
  }
  assert.doesNotMatch(render(), /class="overview-section overview-delivery-section"/);
  const file={id:33,name:'final.pdf',purpose:'deliverable'};
  selection.overviewRecords = [
    {key:'waiting',state:'needs_human',report_document:{id:4,name:'Progress only'}},
    {key:'one',state:'completed',delivery_document:{id:10,name:'Final document'},report_document:{id:9,name:'Draft'}},
    {key:'two',state:'completed',contributions:[{artifacts:[file,file,{id:44,name:'Evidence',purpose:'evidence'}]}]},
  ];
  const sections=()=>[...render().matchAll(/<section class="overview-section[^"]*">.*?<\/section>/gs)].map(match=>match[0]);
  assert.match(sections()[0],/Final document.*final.pdf/s);
  assert.match(sections()[0],/class="work-deliverable-title".*Final document.*>文档<.*>打开<.*final.pdf.*>PDF<.*>预览</s);
  assert.doesNotMatch(sections()[0],/Progress only|Draft|Evidence|assetOverview.all/);
  assert.match(sections()[0],/downloadDelivery\(10\)/);
  assert.doesNotMatch(sections()[0],/downloadDelivery\(33\)/);
  assert.match(sections()[1],/assetOverview.activity/);
  assert.match(sections()[1],/assetOverview.all/);
  assert.match(sections()[0],/class="sr-only"><span[^>]+>文档</);
  assert.doesNotMatch(sections()[0],/rt-list-row|work-deliverable-type/);
  for(const [filename,type,icon,action] of [
    ['cover.png','图片','image','预览'],['take.mp3','音频','audio','查看'],['cut.mp4','视频','video','查看'],
    ['bundle.zip','压缩包','package','预览'],['unknown.bin','文件','file','查看'],
  ]){
    context.ICON=name=>`<svg data-icon="${name}"></svg>`;
    const row=context.RunTeamsWorkRecords.deliveryRowMarkup({name:filename},{key:'file',action:'open()'});
    for(const token of [`data-icon="${icon}"`,filename,`>${type}<`,`>${action}<`])assert.ok(row.includes(token));
  }
  context.window.RunTeamsAssetOverview.openDelivery('doc-10');
  context.window.RunTeamsAssetOverview.openDelivery('file-33');
  assert.deepEqual(opened,[10,[33,'final.pdf']]);
  selection.overviewRecords.push({key:'three',state:'recorded',report_document:{id:77,name:'Third document'}});
  assert.match(sections()[0],/assetOverview.all/);
  assert.doesNotMatch(sections()[0],/Third document/);
  context.RunTeamsLocale={t:()=> '收起'};
  context.render=render;
  context.document={querySelector:()=>null};
  const overview=context.window.RunTeamsAssetOverview;
  overview.toggleDeliveries();
  assert.match(sections()[0], /aria-expanded="true".*收起.*Third document/s);
  assert.match(sections()[1], /assetOverview.activity/);
  overview.openDelivery('doc-77');
  assert.equal(opened.at(-1),77);
  overview.toggleDeliveries();
  assert.match(sections()[0], /aria-expanded="false".*assetOverview.all/s);
  assert.doesNotMatch(sections()[0], /Third document/);
  overview.toggleActivity();
  assert.match(sections()[1], /aria-expanded="true".*收起.*<button>three<\/button>/s);
  assert.doesNotMatch(sections()[0], /Third document/);
  overview.toggleActivity();
  assert.match(sections()[1], /aria-expanded="false"/);
  assert.doesNotMatch(sections()[1], /<button>three<\/button>/);
});

test('overview restores module choices before layout without requesting manual motion', () => {
  const stored = new Map();
  const source = fs.readFileSync('web/ui/asset-overview.js', 'utf8');
  function visit(width, kind, query = '') {
    const url = new URL('http://localhost/workspace' + query);
    const panel = {id: 5}, workspace = {data: {}};
    const state = {surface: kind === 'pipeline' ? 'source-pipeline' : 'team', conversationPanel: panel};
    const context = vm.createContext({
      window: {innerWidth: width}, S: state, location: url, URL,
      appRouteLocation: () => url, detailWorkspaceContext: () => kind,
      RunTeamsSourcePipelines: {current: () => kind === 'pipeline' ? workspace : null},
      RunTeamsEmployeeDirectory: {employeePanel: value => value === panel},
      localStorage: {getItem: k => stored.get(k), setItem: (k,v) => stored.set(k,v)},
      sessionStorage: {setItem() {}}, queueMicrotask() {},
      selectDetailWorkspace: next => state.sel = next,
    });
    vm.runInContext(source, context);
    const overview = context.window.RunTeamsAssetOverview;
    overview.prepare(kind === 'pipeline', kind === 'employee');
    assert.equal(overview.takeManualMotion(), false);
    return {state, overview};
  }
  const {overview, state} = visit(1100, 'employee');
  assert.equal(state.sel.type, 'employee-overview');
  overview.closed();
  assert.equal(overview.takeManualMotion(), true);
  assert.equal(visit(1440, 'employee').state.sel, undefined);
  assert.equal(visit(1099, 'pipeline').state.sel, undefined);
  stored.clear();
  assert.equal(visit(1440, 'pipeline', '?workflow=9').state.sel, undefined);
  assert.equal(visit(1440, 'pipeline').overview.pipeline(), true);
  assert.equal(visit(820, 'pipeline').overview.pipeline(), true);
});

test('the header toggle closes a nested drawer and reopens the overview', () => {
  const state = {sel:{type:'source-pipeline',id:'work'},_selKey:'source-pipeline:work'};
  const preferences = new Map();
  const context = vm.createContext({
    S:state, window:{}, ICON:String,
    RunTeamsShell:{headerAction:options=>options},
    RunTeamsSourcePipelines:{current:()=>({})},
    RunTeamsSourcePipelinePanels:{settings:()=>{state.sel={type:'source-pipeline',id:'settings'};state._selKey='source-pipeline:settings';}},
    localStorage:{setItem:(key,value)=>preferences.set(key,value)},
    requestDetailWorkspaceLeave:()=>false,selectDetailWorkspace:selection=>{state.sel=selection;},
    render:()=>{state._selKey='';},
  });
  vm.runInContext(fs.readFileSync('web/ui/asset-overview.js','utf8'),context);
  const overview=context.window.RunTeamsAssetOverview;
  assert.equal(overview.active(),false);
  assert.equal(overview.trigger().selected,true);
  overview.toggle();
  assert.equal(state.sel,null);
  assert.equal(overview.trigger().selected,false);
  assert.equal(preferences.get('runteams.overview.open.pipeline'),'closed');
  overview.toggle();
  assert.equal(overview.pipeline(),true);
  assert.equal(overview.trigger().selected,true);
});

test('open drawers reserve description and employee shortcuts in both startup renders', () => {
  for (const kind of ['employee', 'pipeline']) {
    const url = new URL('http://localhost/workspace');
    const context = vm.createContext({
      window:{innerWidth:1440,RunTeamsHost:{pages:{}}}, location:url, URL, esc:String, S:{surface:'team'},
      appRouteLocation:()=>url, loadRightDetailWidth:()=>360,
      RunTeamsSourcePipelines:{current:()=>null},
      RunTeamsRoutes:{preview:()=>({kind:kind==='employee'?'bot':'source-pipeline'})},
      RunTeamsLocale:{t:key=>key},
    });
    vm.runInContext(fs.readFileSync('web/ui/page-skeletons.js','utf8'),context);
    context.RunTeamsSkeletons=context.window.RunTeamsSkeletons;
    vm.runInContext(fs.readFileSync('web/ui/asset-overview.js','utf8'),context);
    const overview=context.window.RunTeamsAssetOverview;
    const cold=overview.pendingPage('<main></main>',{});
    const hydrating=overview.prepare(kind==='pipeline',kind==='employee').content();
    for(const markup of [cold,hydrating]){
      assert.equal((markup.match(/overview-loading-bar/g)||[]).length,3);
      assert.match(markup,/overview-deliveries[\s\S]+overview-activity[\s\S]+overview-automation[\s\S]+overview-configuration/);
      assert.match(markup,/data-skeleton-region="overview-activity"/);
      assert.match(markup,/data-skeleton-region="overview-automation"/);
      for(const list of ['overview-deliveries','overview-activity','overview-automation']){
        const section=markup.split('data-skeleton-region="'+list+'"')[1].split('</section>')[0];
        assert.equal((section.match(/data-skeleton-row/g)||[]).length,2);
      }
      assert.doesNotMatch(markup,/<h3>|<button/);
      assert.equal(markup.includes('data-skeleton-region="overview-runtime"'),kind==='employee');
      assert.match(markup,/data-skeleton-region="overview-description"/);
      assert.equal(markup.includes('data-skeleton-region="overview-examples"'),kind==='employee');
    }
  }
});

test('pipeline activity uses the matching work record and keeps new board tasks visible', () => {
  const records = [
    {key:'new',state:'ready',objective:'New task objective'},
    {key:'waiting',state:'needs_human',summary:''},
  ];
  const selection = {
    type:'source-pipeline',id:'settings',
    overviewWorkRevision:JSON.stringify(records.map(row=>[row.key,row.state,row.updated_at])),
    overviewRecords:[
      {key:'unrelated',state:'needs_human',summary:'Another task'},
      {key:'waiting',state:'needs_human',summary:'Waiting for the editor to sign in'},
    ],
  };
  const context = vm.createContext({
    RunTeamsHost: {session: {workspace: () => true}},
    RunTeamsEnvironment: {markup: () => ''},
    window:{},S:{sel:selection},esc:String,ICON:()=>'',RunTeamsEmployeeAutomation:{overviewSection:()=>''},
    RunTeamsWorkRecords:{rowMarkup:row=>row.summary},
  });
  vm.runInContext(fs.readFileSync('web/ui/asset-overview.js','utf8'),context);
  const render = () => context.window.RunTeamsAssetOverview.shell({title:'Pipeline',avatar:'',records});
  assert.match(render(),/New task objective/);
  assert.match(render(),/Waiting for the editor to sign in/);
  assert.doesNotMatch(render(),/Another task/);
  selection.overviewRecords[1].state='completed';
  assert.doesNotMatch(render(),/Waiting for the editor to sign in/);
});

test('media repair keeps the warning through approval until the device probe succeeds', async () => {
  const selection = {}, stored = new Map(), requests = [];
  let status = 'missing', release, start;
  const started = new Promise(resolve => {start = resolve;});
  const context = vm.createContext({
    window:{}, S:{sel:selection}, esc:String, render(){}, document:{addEventListener(){}},
    workspaceAccountCacheToken:()=>1, workspaceDeviceStorageScope:()=>2,
    localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},
    setTimeout:()=>1, clearTimeout(){}, navigator:{},
    RunTeamsLocale:{t:(k,v)=>k+Object.values(v||{}).join(',')},
    RunTeamsSourcePipelines:{request:async()=>({checks:{ffprobe:status}})},
    defaultChatConfig:()=>({channel_id:2,model:'configured'}),
    api:async(path,method,body)=>{requests.push({path,body});return {session:{id:'repair-chat'}};},
    streamApi:async(path,body,event)=>{
      requests.push({path,body});event({type:'agent_event',event:{kind:'user_input'}});
      start();await new Promise(resolve=>{release=resolve;});event({type:'result'});
    },
  });
  vm.runInContext(fs.readFileSync('web/ui/asset-overview.js','utf8'),context);
  context.window.RunTeamsAssetOverview.active=()=>true;
  const env=vm.runInContext('RunTeamsEnvironment',context);
  const rows=env.pipelineRows({asset:{pipeline:{positions:[
    {employee_ref:'employee',skill_key:'draft',name:'Write'},
    {employee_ref:'employee',skill_key:'record',name:'Voice'},
    {employee_ref:'employee',skill_key:'record',name:'Export'},
  ]}},employees:[{member_ref:'employee',skills:[{key:'record',environment_tools:['ffprobe']}]}]});
  assert.equal(env.markup(rows),'');
  await env.retry();
  assert.match(env.markup(rows),/Voice、Export/);
  assert.doesNotMatch(env.markup(rows),/Write|aria-expanded/);
  const done=env.repair();await started;await env.repair();
  assert.match(env.markup(rows),/environmentCheck.approval/);
  assert.deepEqual(requests.map(item=>item.path),['/api/conversations','/api/chat/repair-chat/stream']);
  release();await done;
  assert.match(env.markup(rows),/environmentCheck.missing/);
  status='ready';await env.retry();
  assert.equal(env.markup(rows),'');
});
