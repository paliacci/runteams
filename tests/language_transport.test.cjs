const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
test('a failed preference save retries before the next mutation',async()=>{
 let change,attempts=0;const writes=[];
 const sandbox={console:{error(){}},document:{documentElement:{hasAttribute:()=>false}},window:{},RunTeamsLocale:{language:'en',onChange(fn){change=fn;}},RunTeamsRequests:{request(){},isRead:(_path,method)=>method==='GET'},fetch(){},NativeCloseGuard:class{},LocalClient:class{
  connect(){return Promise.resolve({});}
  async request(path,method,body){if(path==='/api/language-preference'){attempts++;if(attempts===1)throw Error('offline');}writes.push([path,body]);return {};}
 }};
 vm.createContext(sandbox);
 const source=fs.readFileSync(path.join(root,'frontend/community/bootstrap.js'),'utf8').replace(/^import .*;$/gm,'').replace(/export /g,'');
 vm.runInContext(source,sandbox);
 change();await new Promise(resolve=>setImmediate(resolve));
 await sandbox.request('/api/test','POST',{});
 assert.equal(attempts,2);assert.equal(writes[0][0],'/api/language-preference');assert.equal(writes[1][0],'/api/test');
 assert.equal(writes[0][1].communication_language,'en');
});
test('stream retries retain the original resolved language',async()=>{
 let language='en',calls=[];
 const sandbox={crypto:{randomUUID:()=> 'operation'},RunTeamsLocale:{get language(){return language;}},TextDecoder,URL,console,setTimeout};
 vm.createContext(sandbox);
 vm.runInContext(fs.readFileSync(path.join(root,'frontend/community/client.js'),'utf8').replace(/export /g,'')+';globalThis.Client=LocalClient;',sandbox);
 const client=new sandbox.Client({request(){},fetcher:async(_path,options)=>{calls.push(JSON.parse(options.body));if(calls.length===1){language='zh-CN';return {status:401};}return new Response('{"type":"result","reply":"ok"}\n');}});
 client.reconnect=async()=>{};
 await client.stream('/api/chat/1/stream',{message:'French deliverable'},()=>{});
 assert.equal(calls.length,2);assert.equal(calls[0].language_policy.communication_language,'en');assert.deepEqual(calls[0],calls[1]);
});
