import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function subject(){
 const S={localLibrary:{library_id:'library-a'},account:null,conversationPanel:{kind:'general',id:null,input:'keep draft',attachments:[],capabilities:[]}};
 let finish;const calls=[],folder={id:'selected',path:'/tmp/Project',display_path:'/tmp/Project',name:'Project',available:true,custom:true};
 const context={S,window:{addEventListener(){}},_workspaceBusinessGeneration:0,workspaceAccountCacheToken:()=>S.localLibrary?.library_id||'',esc:String,ICON:()=>'<svg></svg>',queueMicrotask,document:{querySelectorAll:()=>[],querySelector:()=>null,getElementById:()=>null},toast(){},closePop(){},render(){},conversationDraftValue:()=>S.conversationPanel.input,conversationAttachments:()=>S.conversationPanel.attachments,conversationCapabilities:()=>S.conversationPanel.capabilities,api:async(path,method,body)=>{calls.push({path,method,body});if(!method)return new Promise(resolve=>{finish=resolve;});return {folder};}};
 context.window=context;context.addEventListener=()=>{};
 vm.createContext(context);
 const load=name=>vm.runInContext(fs.readFileSync(new URL('../../web/ui/'+name+'.js',import.meta.url),'utf8'),context);
 load('host');
 load('work-folder');
 return {S,context,feature:context.window.RunTeamsWorkFolders,calls,folder,resolve:()=>finish({folder})};
}

test('unsigned local library uses the same folder prepare and binding flow',async()=>{
 const s=subject();assert.match(s.feature.markup('panel'),/data-work-folder="panel"/);await Promise.resolve();
 const waiting=s.feature.prepare('panel');s.resolve();const selection=await waiting;
 assert.equal(selection.selection_id,'selected');assert.match(s.feature.markup('panel'),/>Project</);
 await s.feature.bind(41,selection);assert.equal(s.calls.at(-1).path,'/api/work-folders/bind');
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls.at(-1).body)),{chat_id:41,selection_id:'selected'});
 assert.equal(s.S.account,null);assert.equal(s.S.conversationPanel.input,'keep draft');
});

test('library switch rejects stale selection and protected contexts stay hidden',async()=>{
 const s=subject();const waiting=s.feature.prepare('panel');s.S.localLibrary={library_id:'library-b'};s.resolve();assert.equal(await waiting,false);
 s.S.conversationPanel={kind:'employee_design'};assert.equal(s.feature.markup('panel'),'');
 s.S.conversationPanel={kind:'general',scope_pipeline_id:2};assert.equal(s.feature.markup('panel'),'');
 s.S.conversationPanel={kind:'general'};s.context.RunTeamsHost.configure({session:{workspace:state=>state.workspaceOpen}});s.S.workspaceOpen=true;assert.equal(s.feature.markup('panel'),'');
 s.S.workspaceOpen=false;s.S.localLibrary=null;assert.equal(s.feature.markup('panel'),'');
});

test('returning after clear keeps the original frozen project controls usable',async()=>{
 const s=subject(),original=s.S.conversationPanel;const ready=s.feature.prepare('panel');s.resolve();await ready;
 const managed={...s.folder,id:'managed',custom:false};
 s.context.RunTeamsEmployeeDirectory={employeePanel:()=>false};
 s.context.newRailChat=async()=>{s.S.conversationPanel={kind:'general',id:null,input:'',attachments:[],capabilities:[]};};
 s.context.api=async(path,method)=>method?{folder:managed,new_conversation:true}:{folder:managed};
 await s.feature.clear({preventDefault(){},stopPropagation(){}},'panel');
 assert.notEqual(s.S.conversationPanel,original);assert.equal(s.S.conversationPanel.input,'keep draft');
 s.S.conversationPanel=original;const restored=s.feature.markup('panel');
 assert.match(restored,/>Project</);assert.doesNotMatch(restored,/disabled/);
});

test('folder labels preserve the path root and shorten long names within the available space', () => {
  const {feature} = subject();
  const shorten = (value, width) => feature.compactPath(value, text => [...text].length <= width);
  for (const [path, label] of [
    ['~/Projects/品牌 A', '~/.../品牌 A'], ['/Users/test/projects/final', '/.../final'],
    ['C:\\Users\\test\\projects\\output', 'C:\\...\\output'],
    ['\\\\server\\share\\first\\second\\final', '\\\\server\\share\\...\\final'],
    ['~/品牌 A', '~/品牌 A'], ['/', '/'], ['~', '~'],
  ]) assert.equal(shorten(path, 100), label);
  const uuid = shorten('~/device-data/workspaces/888ee91b-0548-4d69-b821-8ff671811517', 30);
  assert.match(uuid, /^~\/\.\.\.\/888ee.*811517$/);
  assert.ok(uuid.length <= 30);
  const single = shorten('/a-very-long-single-folder-name-with-a-finish', 20);
  assert.match(single, /^\/a-.*finish$/);
  assert.ok(single.length <= 20);
  const emoji = shorten('~/项目/中间目录/👨‍👩‍👧‍👦最终目录名字很长👨‍👩‍👧‍👦', 27);
  assert.ok([...emoji].length <= 27);
  assert.ok(!emoji.replaceAll('👨‍👩‍👧‍👦', '').includes('\u200d'));
  assert.ok(emoji.isWellFormed());
});

test('selected folder menu opens the captured folder and clearing it keeps the current draft', async () => {
  const {feature, folder, S, calls, context, resolve} = subject();
  const event = {currentTarget:{}, preventDefault(){}, stopPropagation(){}};
  let items;
  context.openMenu = (_anchor, entries) => { items = entries; };
  const pending = feature.prepare('panel');
  resolve();
  await pending;
  await feature.menu(event, 'panel');
  assert.deepEqual(Array.from(items, item => item.label), [folder.display_path, '选择其他文件夹']);
  items[0].fn();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.at(-1))), {
    path:'/api/work-folders/open', method:'POST', body:{chat_id:null, selection_id:folder.id},
  });
  const original = S.conversationPanel;
  context.api = async (path, method, body) => {
    assert.equal(path, '/api/work-folders/clear');
    assert.equal(method, 'POST');
    assert.equal(body.selection_id, folder.id);
    return {folder:{...folder, custom:false}};
  };
  await feature.clear(event, 'panel');
  assert.equal(S.conversationPanel, original);
  assert.equal(original.input, 'keep draft');
  assert.doesNotMatch(feature.markup('panel'), /conversation-folder-clear/);
});

test('an unselected folder opens one picker and cancellation preserves the conversation', async () => {
  const {feature, folder, S, context} = subject();
  let picks = 0;
  let finish;
  context.api = async (path, method) => {
    if (!method) return {folder:{...folder, custom:false}};
    assert.equal(path, '/api/work-folders/pick');
    picks++;
    return new Promise(resolve => { finish = resolve; });
  };
  const original = S.conversationPanel;
  await feature.prepare('panel');
  const event = {currentTarget:{}};
  assert.doesNotMatch(feature.markup('panel'), /aria-haspopup|conversation-folder-clear/);
  const first = feature.menu(event, 'panel');
  await feature.menu(event, 'panel');
  assert.equal(picks, 1);
  assert.match(feature.markup('panel'), /disabled/);
  finish({cancelled:true});
  await first;
  assert.equal(S.conversationPanel, original);
  assert.equal(original.input, 'keep draft');
  assert.doesNotMatch(feature.markup('panel'), /disabled/);
  context.api = async () => ({folder});
  await feature.menu(event, 'panel');
  assert.match(feature.markup('panel'), /conversation-folder-clear/);
});

test('changing a frozen employee folder carries the draft into the new employee session', async () => {
  const {feature, folder, S, context} = subject();
  const original = S.conversationPanel;
  original.id = 31;
  original.attachments = ['attached'];
  original.capabilities = ['selected'];
  const next = {...folder, id:'other', name:'Other'};
  context.RunTeamsEmployeeDirectory = {
    employeePanel: panel => panel === original,
    forPanel: panel => panel === original && {key:'employee-key'},
    newSession: async key => {
      assert.equal(key, 'employee-key');
      S.conversationPanel = {kind:'general', id:32};
    },
  };
  context.api = async (path, method) => {
    if (!method) return {folder:{...folder, custom:false}};
    assert.equal(path, '/api/work-folders/pick');
    return {folder:next, new_conversation:true};
  };
  await feature.prepare('panel');
  await feature.menu({currentTarget:{}}, 'panel');
  assert.equal(S.conversationPanel.id, 32);
  assert.equal(S.conversationPanel.input, original.input);
  assert.deepEqual(S.conversationPanel.attachments, original.attachments);
  assert.deepEqual(S.conversationPanel.capabilities, original.capabilities);
  assert.match(feature.markup('panel'), />Other</);
});
