const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('drawer list requests preserve an in-flight result; an edit refreshes it', async () => {
 const knowledge = '/api/device/work/source-pipelines/asset-knowledge';
 const apps = '/api/mcp-connections';
 const results = '/api/device/work/results';
 for (const mutation of [false, true]) {
  let count = 0, finish;
  const response = () => ({status:200,text:async()=>'{}'});
  const window = {fetch:async path=>{
   if(path===results && ++count===1)return new Promise(resolve=>{finish=()=>resolve(response());});
   return response();
  }};
  vm.runInNewContext(fs.readFileSync('web/ui/requests.js','utf8'), {window,URL,AbortController,setTimeout,clearTimeout});
  const transport = window.RunTeamsRequests;
  const request = transport.request(results,{device:true,readCurrent:true});
  for(const [path,body] of [[knowledge,{chat:2}],[apps,{action:'employee-apps-read',employee:{}}]]){
   await transport.request(path,{method:'POST',device:true,body:JSON.stringify(body)});
  }
  if(mutation)await transport.request(knowledge,{method:'POST',device:true,body:JSON.stringify({chat:2,upload:{}})});
  finish();await request;
  assert.equal(count,mutation?2:1);
  assert.equal(transport.isRead(apps,'POST',{action:'employee-apps-set',employee:{}}),false);
 }
});
