import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {createLocalClient} from './community_transport_fixture.mjs';
globalThis.crypto??=webcrypto;
const lib='11111111-1111-4111-8111-111111111111';
const stream=events=>new Response(events.map(e=>JSON.stringify(e)).join('\n')+'\n');
test('stream carries real library scope and preserves canonical event protocol',async()=>{
 let posted;const client=createLocalClient(async(path,opts)=>{posted=opts;return stream([{type:'accepted',message_id:7},{type:'agent_event',event:{kind:'reply_delta',delta:'hello'}},{type:'result',message_id:8,reply:'hello'}]);});client.libraryId=lib;
 const events=[];await client.stream('/api/chat/123/stream',{message:'hello'},e=>events.push(e));
 assert.equal(posted.headers['X-RunTeams-Library'],lib);assert.match(JSON.parse(posted.body).operation_id,/^[a-f0-9-]{36}$/);assert.equal(events.length,3);assert.equal(events[2].reply,'hello');
});
test('lost acceptance recovers stored reply without running model twice',async()=>{
 let payload,posts=0;const client=createLocalClient(async(path,opts)=>{
  if(path.endsWith('/stream')){posts++;payload=JSON.parse(opts.body);throw Error('connection lost');}
  return Response.json({messages:[{id:1,role:'user',text:'hello',metadata:{local_turn_id:payload.operation_id}},{id:2,role:'bot',text:'saved',metadata:{local_turn_id:payload.operation_id}}]});
 });client.libraryId=lib;const events=[];await client.stream('/api/chat/123/stream',{message:'hello'},e=>events.push(e));
 assert.equal(posts,1);assert.deepEqual(events.map(e=>e.type),['accepted','result']);assert.equal(events[1].reply,'saved');
});
test('unconfirmed loss retains the session and prevents blind cleanup',async()=>{
 let operation;
 const client=createLocalClient(async(path,options)=>{
  if(path.endsWith('/stream'))operation=JSON.parse(options.body).operation_id;
  throw Error('offline');
 });client.libraryId=lib;
 await assert.rejects(client.stream('/api/chat/123/stream',{message:'hello'},()=>{}),e=>e.localPending===true&&e.localTurnId===operation);
});
test('explicit rejection never fetches history or retries a turn',async()=>{
 let calls=0;const client=createLocalClient(async()=>{calls++;return Response.json({error:'attachment unavailable'},{status:400});});client.libraryId=lib;
 await assert.rejects(client.stream('/api/chat/123/stream',{message:'hello'},()=>{}),e=>e.status===400&&!e.localTurnId);assert.equal(calls,1);
});

test('a stalled result keeps the same operation ID even if acceptance was already delivered', async () => {
 let operation;
 const client = createLocalClient(async (path, options) => {
  if (path.endsWith('/stream')) {
   operation = JSON.parse(options.body).operation_id;
   return stream([{type: 'accepted', operation_id: operation, message_id: 7}]);
  }
  return Response.json({error: 'History unavailable'}, {status: 403});
 });
 client.libraryId = lib;
 const events = [];
 await assert.rejects(client.stream('/api/chat/123/stream', {message: 'hello'}, event => events.push(event)),
  error => error.localTurnId === operation && !error.localPending);
 assert.deepEqual(events.map(event => event.type), ['accepted']);
});
test('401 renews only the local cookie and reuses the same operation',async()=>{
 const ops=[];const client=createLocalClient(async(path,opts)=>{
  if(path==='/')return new Response('html');if(path==='/api/library')return Response.json({storage_kind:'local',generation:'test-generation',library_id:lib});
  ops.push(JSON.parse(opts.body).operation_id);return ops.length===1?Response.json({error:'expired'},{status:401}):stream([{type:'accepted',message_id:1},{type:'result',reply:'ok'}]);
 });client.libraryId=lib;await client.stream('/api/chat/123/stream',{message:'hello'},()=>{});assert.equal(ops.length,2);assert.equal(ops[0],ops[1]);
});

test('bodyless shared channel actions send strict JSON',async()=>{
 let posted;const client=createLocalClient(async(path,opts)=>{posted=opts;return Response.json({channel:{id:2}});});client.libraryId=lib;
 await client.request('/api/channel/2/probe','POST');assert.equal(posted.body,'{}');assert.equal(posted.headers['Content-Type'],'application/json');
});

test('dropped stream observes the accepted worker until its saved result',async()=>{
 let payload,reads=0,posts=0;const client=createLocalClient(async(path,opts)=>{
  if(path.endsWith('/stream')){posts++;payload=JSON.parse(opts.body);throw Error('disconnected');}
  reads++;return Response.json({active_turn:{active:reads===1},messages:[{id:1,role:'user',metadata:{local_turn_id:payload.operation_id}},...(reads===1?[]:[{id:2,role:'bot',text:'recovered',metadata:{local_turn_id:payload.operation_id}}])]});
 });client.libraryId=lib;const events=[];await client.stream('/api/chat/123/stream',{message:'hi'},e=>events.push(e));assert.equal(posts,1);assert.equal(reads,2);assert.equal(events.at(-1).reply,'recovered');
});

test('lost acceptance restores the saved attachment cards',async()=>{
 let operation;const attachments=[{id:'saved-image',name:'image.png',kind:'image'}];
 const client=createLocalClient(async(path,opts)=>{
  if(path.endsWith('/stream')){operation=JSON.parse(opts.body).operation_id;throw Error('lost receipt');}
  return Response.json({messages:[{id:1,role:'user',attachments,metadata:{local_turn_id:operation}},{id:2,role:'bot',text:'done',metadata:{local_turn_id:operation}}]});
 });client.libraryId=lib;const events=[];await client.stream('/api/chat/123/stream',{message:'read image'},e=>events.push(e));assert.deepEqual(events[0].attachments,attachments);
});

test('recovery tolerates brief history failures and delivers the saved stop notice without another POST', async () => {
  const attachments = [{id: 'saved-image', name: '截图.png', kind: 'image'}];
  const notice = {kind: 'stopped', text: '已停止。'};
  let operation, reads = 0, posts = 0;
  const client = createLocalClient(async (path, options) => {
    if (path.endsWith('/stream')) {
      posts++;
      operation = JSON.parse(options.body).operation_id;
      throw new TypeError('connection lost');
    }
    if (++reads <= 2) return Response.json({error: 'unavailable'}, {status: 503});
    return Response.json({messages: [
      {id: 11, role: 'user', attachments, metadata: {local_turn_id: operation}},
      {id: 12, role: 'bot', text: 'partial', metadata: {local_turn_id: operation, stopped: true, system_notice: notice}},
    ]});
  });
  client.libraryId = lib;
  const events = [];
  await client.stream('/api/chat/123/stream', {message: 'read image'}, event => events.push(event));
  assert.equal(posts, 1);
  assert.equal(reads, 3);
  assert.deepEqual(events.map(event => event.type), ['accepted', 'result']);
  assert.deepEqual(events[0].attachments, attachments);
  assert.equal(events[1].incomplete, true);
  assert.deepEqual(events[1].system_notice, notice);
});
