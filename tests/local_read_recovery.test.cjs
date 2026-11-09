const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/index.html','utf8');
function fn(name){const start=source.search(new RegExp('^(?:async )?function '+name+'\\(','m'));assert(start>=0);const tail=source.slice(start+1),next=tail.search(/\n(?:(?:async )?function |(?:const|let|class) )/);return next<0?source.slice(start):source.slice(start,start+1+next);}
function fixture(){
 const host={},c={window:host,console,Map,Set,Error,Promise};
 vm.runInNewContext(fs.readFileSync('web/ui/load-failure.js','utf8'),c);
 Object.assign(c,{RunTeamsLoadFailure:host.RunTeamsLoadFailure,S:{chats:[{id:1,title:'Keep original conversation'}],booting:false},_workspaceBusinessGeneration:1,
  workspaceAccountCacheToken:()=> 'same-scope',RunTeamsHost:{session:{workspace:()=>false},lifecycle:{}},updateWorkspaceNavigationError:()=>{},render:()=>{},railRecentChats:()=>c.S.chats,
  api:async()=>({error:'private internal path',code:'local_storage_full'})});
 vm.runInNewContext(fn('refreshChatDirectory')+'\n'+fn('railNavigationFailure'),c);return c;
}
test('storage-full failures retain known chats and show the actionable cause without raw internals',async()=>{
 const c=fixture(),original=c.S.chats;await assert.rejects(c.refreshChatDirectory());
 assert.equal(c.S.chats,original);assert.equal(c.S.chatDirectoryErrorCode,'local_storage_full');
 const html=c.railNavigationFailure();assert.match(html,/磁盘空间不足/);assert.match(html,/仍显示上次读取的对话/);assert.doesNotMatch(html,/private internal/);
 assert.equal((html.match(/data-read-retry=/g)||[]).length,1);
});
test('a successful original read clears the cause and replaces the list with confirmed data',async()=>{
 const c=fixture();await assert.rejects(c.refreshChatDirectory());const confirmed=[{id:2,title:'Confirmed conversation'}];c.api=async()=>({chats:confirmed});
 await c.refreshChatDirectory();assert.equal(c.S.chats,confirmed);assert.equal(c.S.chatDirectoryErrorCode,'');assert.equal(c.S.chatDirectoryError,'');assert.equal(c.railNavigationFailure(),'');
});
test('an obsolete scope cannot project a storage failure into the next workspace',async()=>{
 const c=fixture();let finish;c.api=()=>new Promise(resolve=>finish=resolve);const pending=c.refreshChatDirectory();c._workspaceBusinessGeneration++;
 finish({error:'full',code:'local_storage_full'});await pending;assert.notEqual(c.S.chatDirectoryErrorCode,'local_storage_full');assert.equal(c.S.chats[0].id,1);
});
