import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createLocalClient} from './community_transport_fixture.mjs';

test('the shared chip converter preserves a native skill trigger and plugin identity',()=>{
 const source=fs.readFileSync('web/index.html','utf8').match(/^function capabilityFromPlugin\(item\).*$/m)[0],context={};
 vm.createContext(context);vm.runInContext(source,context);
 const skill=context.capabilityFromPlugin({kind:'skill',id:'skill:atlas-method',name:'Atlas Method',trigger_name:'atlas-method',channel_id:2});
 assert.equal(skill.kind,'skill');assert.equal(skill.trigger_name,'atlas-method');assert.equal(skill.id,'skill:atlas-method');
 const plugin=context.capabilityFromPlugin({id:'tools@native',display_name:'Tools',channel_id:2});
 assert.equal(plugin.kind,'plugin');assert.equal(plugin.id,'tools@native');
});

test('a lost rewind receipt restores the saved skill and attachment without another model submission',async()=>{
 let payload,posts=0;const capabilities=[{kind:'skill',id:'skill:atlas',mention_id:'m1',mention_token:'[[capability:m1]]'}],attachments=[{id:'original',name:'original.txt'}];
 const client=createLocalClient(async(path,options)=>{
  if(path.endsWith('/stream')){posts++;payload=JSON.parse(options.body);throw Error('receipt lost');}
  return Response.json({messages:[{id:41,role:'user',capabilities,attachments,metadata:{local_turn_id:payload.operation_id}},{id:42,role:'bot',text:'replacement',metadata:{local_turn_id:payload.operation_id}}]});
 });client.libraryId='library';const events=[];
 await client.stream('/api/chat/123/stream',{message:'new [[capability:m1]]',rewind_message_id:21,capabilities,reuse_attachment_ids:['original']},event=>events.push(event));
 assert.equal(posts,1);assert.equal(payload.rewind_message_id,21);assert.deepEqual(events[0].capabilities,capabilities);assert.deepEqual(events[0].attachments,attachments);assert.equal(events[1].reply,'replacement');
});
