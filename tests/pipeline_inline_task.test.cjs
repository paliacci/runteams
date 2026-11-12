const assert=require('node:assert/strict'),fs=require('node:fs'),test=require('node:test'),vm=require('node:vm');
const source=fs.readFileSync('web/ui/source-pipelines.js','utf8');
const code=source.slice(source.indexOf(' function composeDraft('),source.indexOf(' const workUpdateOwner='));
function fixture(){
 const s={data:{runtime:{status:'running'}},reference:{source_id:'fixture'},composer:null},calls=[],saved=new Map(),frames=[],timers=new Map();let now=0,nextTimer=0;
 const nodes=[{id:'source_pipeline_title',value:''},{id:'source_pipeline_parameter',value:''},{id:'source_pipeline_json',value:''}];
 for(const node of nodes){node.focus=()=>{context.document.activeElement=node;};node.scrollIntoView=()=>{};node.setSelectionRange=(start,end)=>{node.selectionStart=start;node.selectionEnd=end;};}
 const form={contains:node=>nodes.includes(node),dataset:{position:'a'},querySelector:q=>q==='[name="title"]'?nodes[0]:q==='[name="objective"]'?nodes[1]:null,querySelectorAll:()=>nodes};
 const context={window:{addEventListener(){},removeEventListener(){}},visible:true,scopeValid:true,Date:{now:()=>now},setTimeout:(fn,ms)=>{const id=++nextTimer;timers.set(id,{fn,at:now+ms});return id;},clearTimeout:id=>timers.delete(id),structuredClone,S:{sel:null},current:()=>context.visible?s:null,matches:x=>context.visible&&x===s,sameScope:()=>context.scopeValid,requestDetailWorkspaceLeave:()=>false,resetDetailWorkspace(){context.S.sel=null;},
  RunTeamsSourcePipelinePanels:{columns:()=>[{key:'a',kind:'employee'},{key:'b',kind:'approval'},{key:'done',kind:'done'}]},
  document:{addEventListener(){},removeEventListener(){},activeElement:{},body:{},getElementById:()=>form,querySelector:()=>null,querySelectorAll:()=>[]},
  requestAnimationFrame:f=>frames.push(f),render(){if(s.composer){form.dataset.position=s.composer.position;nodes[0].value=s.composer.title||'';nodes[1].value=s.composer.parameter||'';nodes[2].value='';}},
  request:async(action,data)=>{calls.push({action,data:structuredClone(data)});return action==='contract'?{input_schema:{type:'object'}}:context.reply;},
  FormData:class{get(key){return nodes[key==='title'?0:1].value;}},readCoreTaskParameters:()=>({json:'confirmed value'}),
  crypto:{randomUUID:()=> 'original-operation'},pendingKey:()=> 'pending',RunTeamsWorkState:{setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},
  refresh:async()=>{context.refreshed=true;},workCommitted(){},reply:{status:'committed',result:{workflow:{id:42}}},
  RunTeamsLocale:{t:(_key,_vars,fallback)=>fallback},taskSchemaFieldLabel:key=>key,queueMicrotask:f=>frames.push(f),api:async()=>({references:[]}),esc:String,ICON:()=>'',RunTeamsSkeletons:{region:()=> 'loading'},RunTeamsLoadFailure:{markup:()=> 'retry'},operationError:()=>'',coreTaskParameterFields:()=>'',coreWorkflowFrozenParameters:()=>[]};
 vm.createContext(context);vm.runInContext(code,context);
 return {s,calls,saved,frames,nodes,form,context,async advance(ms){now+=ms;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn();}await new Promise(resolve=>setImmediate(resolve));},blur(){context.document.activeElement=context.document.body;context.composerFocusout({currentTarget:form,relatedTarget:context.document.body});this.flush();},flush(){while(frames.length)frames.shift()();}};
}
test('column drafts preserve raw inputs when switching starting columns',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();f.nodes[0].value='Original title';f.nodes[1].value='Original objective';f.nodes[2].value='{"unfinished":';f.context.composeDraft(f.form);
 await f.context.compose('b');await f.context.compose('a');f.flush();
 assert.equal(f.nodes[0].value,'Original title');assert.equal(f.nodes[2].value,'{"unfinished":');
 assert.equal(f.calls.filter(c=>c.action==='contract'&&c.data.start_column_key==='a').length,1);
 assert.equal(f.context.S.sel,null);
});
test('a board repaint restores the active field, raw draft and caret without reopening a drawer',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();const input=f.nodes[0];input.closest=()=>f.form;input.value='Keep reading here';input.selectionStart=5;input.selectionEnd=9;f.context.document.activeElement=input;
 f.context.captureComposer(f.s);f.context.render();f.context.document.activeElement=f.context.document.body;f.flush();
 assert.equal(f.context.document.activeElement,input);assert.equal(input.value,'Keep reading here');assert.equal(input.selectionStart,5);assert.equal(input.selectionEnd,9);
});
test('an obsolete contract read does not reopen a closed column composer',async()=>{
 const f=fixture();let finish;f.context.request=()=>new Promise(resolve=>finish=resolve);const opening=f.context.compose('a');f.context.cancelCompose();finish({fields:[]});await opening;assert.equal(f.s.composer,null);
});
test('uncertain submission checks the same operation without dispatching another task',async()=>{
 const f=fixture();await f.context.compose('a');f.nodes[0].value='Task';f.nodes[1].value='Goal';let dispatches=0;
 f.context.request=async(action,data)=>{f.calls.push({action,data:structuredClone(data)});if(action==='dispatch'){dispatches++;throw Error('receipt missing');}return {status:'committed',result:{workflow:{id:42}}};};
 await f.context.submit();assert.equal(f.s.pending.operation_id,'original-operation');assert.equal(f.s.pending.start_column_key,'a');assert.equal(f.s.admissionUnknown,true);
 await f.context.submit();assert.equal(dispatches,1);assert.equal(f.calls.at(-1).action,'operation');assert.equal(f.calls.at(-1).data.operation_id,'original-operation');assert.equal(f.s.pending,null);assert.equal(f.saved.size,0);assert.equal(f.context.refreshed,true);
});
test('a removed starting column can recover its pending operation from a visible column',async()=>{
 const f=fixture();f.s.pending={operation_id:'retained',start_column_key:'removed',title:'Task',payload:{objective:'Goal'}};f.s.composer={position:'removed'};await f.context.compose('b');
 assert.equal(f.s.composer.position,'b');assert.equal(f.s.pending.start_column_key,'removed');assert.equal(f.s.pending.operation_id,'retained');
});
test('the board renders the task form inside its selected column and no compose drawer remains',()=>{
 const f=fixture();f.s.composer={position:'a',loading:true};assert.match(f.context.composeCard(f.s,{key:'a'}),/class="card title-only source-pipeline-inline-task"/);assert.equal(f.context.composeCard(f.s,{key:'b'}),'');
 assert.doesNotMatch(source,/select\('compose'\)|source-pipeline-compose-drawer/);
 assert.match(source,/s\.composer\?\.position===column\.key\?composeCard\(s,column\)/);
});

test('new tasks share the normal title-only card structure and typography',()=>{
 const f=fixture();f.s.composer={position:'a',contract:{input_schema:{properties:{optional:{type:'string'}}}},title:'',parameters:{}};
 const html=f.context.composeCard(f.s,{key:'a'});
 assert.match(html,/class="card title-only source-pipeline-inline-task"/);assert.match(html,/class="card-head"/);assert.match(html,/name="title" class="tt"/);
 assert.doesNotMatch(html,/<form|<fieldset|name="objective"|inline-task-|data-task-submit|任务信息|ICON/);
 const css=fs.readFileSync('web/ui/source-pipelines.css','utf8');const custom=css.slice(css.indexOf('/* Keep the normal card'));
 assert.doesNotMatch(custom,/font-size|font-weight|line-height|letter-spacing|height:/);
});
test('Escape discards the current draft, and an empty Enter creates no work',async()=>{
 const f=fixture();await f.context.compose('a');f.nodes[0].value='Discard me';f.context.cancelCompose();await f.context.compose('a');assert.equal(f.s.composer.title,'');
 f.nodes[0].value='';await f.context.submit();assert.equal(f.s.composer,null);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
});
test('Enter submits the title as objective without invented fields',async()=>{
 const f=fixture();await f.context.compose('a');f.nodes[0].value='One-line task';await f.context.submit();const command=f.calls.find(c=>c.action==='dispatch').data;
 assert.equal(command.title,'One-line task');assert.equal(command.payload.objective,command.title);assert.deepEqual(command.payload.inputs,[]);
});
test('keyboard composition and multiline parameters do not submit',async()=>{
 const f=fixture();await f.context.compose('a');f.nodes[0].value='Keep draft';let prevented=0;
 const event={key:'Enter',target:{tagName:'INPUT'},isComposing:true,preventDefault(){prevented++;}};
 f.context.composerKeydown(event);f.context.composerKeydown({...event,isComposing:false,target:{tagName:'TEXTAREA'}});
 assert.equal(prevented,0);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
 f.context.composerKeydown({...event,isComposing:false});await f.advance(5000);assert.equal(prevented,1);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,1);
});
test('required contract values expand only when needed and are never silently bypassed',async()=>{
 const f=fixture();f.context.request=async(action,data)=>{f.calls.push({action,data:structuredClone(data)});return action==='contract'?{input_schema:{required:['focus'],properties:{focus:{type:'string'}}}}:f.context.reply;};
 await f.context.compose('a');assert.equal(f.s.composer.needsInput,undefined);f.nodes[0].value='Needs input';await f.context.submit();assert.equal(f.s.composer.needsInput,true);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
 f.context.readCoreTaskParameters=()=>({focus:'Required value'});await f.context.submit();assert.equal(f.calls.at(-1).data.payload.parameters.focus,'Required value');
});
test('contract defaults are used while the initial card remains title-only',async()=>{
 const f=fixture();f.context.request=async(action,data)=>{f.calls.push({action,data:structuredClone(data)});return action==='contract'?{input_schema:{required:['focus'],properties:{focus:{type:'string',default:'Provided default'}}}}:f.context.reply;};
 await f.context.compose('a');f.nodes[0].value='Uses default';await f.context.submit();assert.equal(f.calls.at(-1).data.payload.parameters.focus,'Provided default');
});

test('opening a title-only card and typing edit a draft without starting position work',async()=>{
 const f=fixture();await f.context.compose('b');f.nodes[0].value='Draft only';f.context.composeDraft(f.form);
 assert.equal(f.s.composer.title,'Draft only');assert.equal(f.s.composer.position,'b');
 assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);assert.equal(f.s.pending,undefined);
 f.context.cancelCompose();assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
});

test('a nonempty title submits automatically five seconds after leaving the card',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();f.nodes[0].value='Automatic task';f.context.composeDraft(f.form);f.blur();
 await f.advance(4999);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
 await f.advance(1);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,1);assert.equal(f.calls.at(-1).data.title,'Automatic task');
});
test('returning to the title cancels the countdown; another blur restarts the full grace period',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();f.nodes[0].value='Before';f.context.composeDraft(f.form);f.blur();await f.advance(3000);
 f.context.composerFocusin();f.nodes[0].value='After';f.context.composeDraft(f.form);await f.advance(10000);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
 f.blur();await f.advance(4999);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);await f.advance(1);assert.equal(f.calls.at(-1).data.title,'After');
});
test('opening the draft menu holds dispatch until a full new grace period after closing',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();f.nodes[0].value='Keep editing';f.context.composeDraft(f.form);f.blur();await f.advance(4000);
 let menu;f.context.openMenu=(_anchor,items,options)=>{menu={items,options};};
 f.context.draftMenu({preventDefault(){},stopPropagation(){},currentTarget:{closest:()=>({})}},'a');
 await f.advance(10000);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
 menu.options.onClose();f.context.composerFocusin({target:{matches:()=>false}});f.flush();await f.advance(4999);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
 await f.advance(1);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,1);
});
test('cancel creation from the floating menu cannot dispatch after the menu closes',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();f.nodes[0].value='Discard';f.context.composeDraft(f.form);f.blur();
 let menu;f.context.openMenu=(_anchor,items,options)=>{menu={items,options};};
 f.context.draftMenu({preventDefault(){},stopPropagation(){},currentTarget:{closest:()=>({})}},'a');
 menu.options.onClose();menu.items[1].fn();f.flush();await f.advance(10000);
 assert.equal(f.s.composer,null);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
});
test('an uncertain card mutation checks its original receipt and retains the operation id',async()=>{
 const f=fixture();f.s.data.workflows=[{id:7,state:'ready',title:'Task',card_actions:{visit:2}}];f.context.referenceKey=()=> 'fixture';f.context.RunTeamsWorkState.getItem=()=>null;
 let requests=[];f.context.request=async(action,data)=>{requests.push({action,data:structuredClone(data)});throw Error('lost response');};
 await f.context.cardCommand(7,'pause');assert.equal(f.s.cardStates[7].pending.operation_id,'original-operation');
 f.context.request=async(action,data)=>{requests.push({action,data:structuredClone(data)});return {operation_id:data.operation_id,status:'committed',workflow:{id:7,state:'paused'}};};
 await f.context.cardCommand(7);
 assert.deepEqual(requests.map(x=>x.action),['card','card-operation']);assert.equal(requests[0].data.operation_id,requests[1].data.operation_id);assert.equal(f.s.cardStates[7].pending,null);
});
test('saved task menus keep all actions in the same order for every state',()=>{
 const f=fixture(),states=[{edit:true,pause:true,stop:true,trash:true},{stop:true},{edit:true,resume:true,stop:true,trash:true},{trash:true}];
 const expected=['查看详情','编辑任务','开始任务','停止任务','移到垃圾箱'];
 for(const caps of states){const items=f.context.cardMenuItems(f.s,{id:7,card_actions:caps},{});assert.deepEqual(Array.from(items,x=>x.label),expected);for(const item of items.filter(x=>x.disabled)){assert.ok(item.disabledReason);item.fn();}}
 assert.equal(f.calls.length,0);
 const paused=f.context.cardMenuItems(f.s,{id:7,card_actions:{resume:true}},{});assert.equal(paused[2].disabled,false);
 f.s.data.runtime.status='paused';const stopped=f.context.cardMenuItems(f.s,{id:7,card_actions:{resume:true}},{});assert.equal(stopped[2].disabled,true);assert.match(stopped[2].disabledReason,/启动流水线/);
});
test('pending receipts keep the full menu and append recovery without enabling another mutation',()=>{
 const f=fixture(),items=f.context.cardMenuItems(f.s,{id:7,card_actions:{edit:true,pause:true,stop:true,trash:true}},{pending:{},busy:true});
 assert.equal(items.length,6);assert.equal(items[0].disabled,undefined);assert.ok(items.slice(1,5).every(x=>x.disabled));assert.equal(items[5].label,'核对操作结果');
 for(const item of items.slice(1))item.fn();assert.equal(f.calls.length,0);
 assert.doesNotMatch(source,/taskCardToolbar|task-card-toolbar|task-card-more/);
});
test('Start task uses the original held task and cannot bypass the automatic-start grace period',()=>{
 const f=fixture(),started=[];f.context.cardCommand=(id,action)=>started.push({id,action});
 const held=f.context.cardMenuItems(f.s,{id:7,state:'paused',card_actions:{resume:true}},{});
 assert.equal(held[2].label,'开始任务');held[2].fn();assert.deepEqual(started,[{id:7,action:'resume'}]);
 const queued=f.context.cardMenuItems(f.s,{id:8,state:'ready',card_actions:{pause:true}},{});
 assert.equal(queued[2].disabled,true);assert.match(queued[2].disabledReason,/自动开始/);queued[2].fn();assert.equal(started.length,1);
 assert.ok(queued.every(item=>!['暂停开始','继续工作'].includes(item.label)));
});
test('Stop and Move to Trash execute the original task action directly without confirmation',()=>{
 const f=fixture(),commands=[];f.context.confirmModal=()=>assert.fail('Task actions must not open a confirmation dialog');
 f.context.cardCommand=(id,action)=>commands.push({id,action});
 const row={id:7,state:'ready',card_actions:{stop:true,trash:true}};
 const items=f.context.cardMenuItems(f.s,row,{});items[3].fn();items[4].fn();
 assert.deepEqual(commands,[{id:7,action:'stop'},{id:7,action:'trash'}]);
 const pending=f.context.cardMenuItems(f.s,row,{pending:{operation_id:'retained'}});pending[3].fn();pending[4].fn();assert.equal(commands.length,2);
 f.context.visible=false;items[3].fn();items[4].fn();assert.equal(commands.length,2,'stale menus must not act in another workspace');
 assert.doesNotMatch(source,/confirmCardAction/);
});
test('empty titles, Escape and owner changes never dispatch deferred work',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();f.nodes[0].value='   ';f.blur();await f.advance(5000);assert.equal(f.s.composer,null);
 await f.context.compose('a');f.flush();f.nodes[0].value='Cancel';f.context.composeDraft(f.form);f.blur();f.context.cancelCompose();await f.advance(5000);
 await f.context.compose('a');f.flush();f.nodes[0].value='Old owner';f.context.composeDraft(f.form);f.blur();f.context.scopeValid=false;await f.advance(5000);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,0);
});
test('leaving the board still submits the accepted title to its original pipeline',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();f.nodes[0].value='Original board';f.context.composeDraft(f.form);f.blur();f.context.visible=false;await f.advance(5000);
 assert.equal(f.calls.filter(c=>c.action==='dispatch').length,1);assert.equal(f.calls.at(-1).data.start_column_key,'a');assert.equal(f.s.pending,null);
});
test('a queued column submits without consuming the draft currently being edited in another column',async()=>{
 const f=fixture();await f.context.compose('a');f.flush();f.nodes[0].value='First column';f.context.composeDraft(f.form);await f.context.compose('b');f.flush();f.nodes[0].value='Still editing second';f.context.composeDraft(f.form);
 await f.advance(5000);assert.equal(f.calls.filter(c=>c.action==='dispatch').length,1);assert.equal(f.calls.at(-1).data.title,'First column');assert.equal(f.s.composer.position,'b');assert.equal(f.s.composer.title,'Still editing second');
});

test('Enter on required fields captures their values before navigating away during the grace period',async()=>{
 const f=fixture();await f.context.compose('a');f.s.composer.contract={input_schema:{required:['focus'],properties:{focus:{type:'string'}}}};f.s.composer.needsInput=true;f.nodes[0].value='With required input';f.context.readCoreTaskParameters=()=>({focus:'Final input'});
 f.context.composerKeydown({key:'Enter',target:{tagName:'INPUT'},preventDefault(){}});f.context.visible=false;await f.advance(5000);assert.equal(f.calls.at(-1).data.payload.parameters.focus,'Final input');
});

test('stopped cards can start after settlement and show why a settling card cannot start',()=>{
 const f=fixture(),started=[];f.context.cardCommand=(id,action)=>started.push({id,action});
 const stopped=f.context.cardMenuItems(f.s,{id:7,state:'canceled',card_actions:{resume:true}},{});
 assert.equal(stopped[2].disabled,false);stopped[2].fn();assert.deepEqual(started,[{id:7,action:'resume'}]);
 const settling=f.context.cardMenuItems(f.s,{id:7,state:'canceled',card_actions:{settling:true}},{});
 assert.equal(settling[2].disabled,true);assert.match(settling[2].disabledReason,/停止收尾/);
});
