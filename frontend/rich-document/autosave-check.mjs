import assert from 'node:assert/strict';
import {createAutosave} from './src/autosave.js';
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const value=n=>({name:'测试',document:{schema:'runteams.rich-document/1',blocks:[{type:'paragraph',content:String(n)}],sources:{}}});
let writes=[],states=[],dirty=[],navigated=0;
const c=createAutosave({revision:1,initial:value(0),delay:5,timeout:30,write:v=>writes.push(v),status:(...v)=>states.push(v),clean:v=>dirty.push(v)});
c.update(value(0));await wait(10);assert.equal(writes.length,0);
c.update(value(1));c.update(value(2));await wait(10);assert.equal(writes.length,1);assert.deepEqual(writes[0].document,value(2).document);
c.update(value(3));c.acknowledge({request_id:'stale',revision:99});assert.equal(writes.length,1);
c.before(()=>navigated++);assert.equal(navigated,0);
c.acknowledge({request_id:writes[0].request_id,revision:2});assert.equal(writes.length,2);assert.equal(writes[1].base_revision,2);assert.equal(navigated,0);assert.equal(dirty.at(-1),true);
c.acknowledge({request_id:writes[1].request_id,revision:3});assert.equal(navigated,1);assert.equal(dirty.at(-1),false);
c.update(value(4));c.flush();c.acknowledge({request_id:writes.at(-1).request_id,error:'空间不足'});assert.equal(states.at(-1)[0],'error');assert.equal(dirty.at(-1),true);await wait(10);assert.equal(writes.length,3);
c.retry();assert.equal(writes.length,4);c.acknowledge({request_id:writes.at(-1).request_id,revision:4});
c.update(value(5));c.flush();const pending=writes.at(-1);await wait(40);assert.equal(states.at(-1)[0],'error');c.retry();assert.deepEqual(writes.at(-1),pending);c.acknowledge({request_id:pending.request_id,revision:5});assert.equal(dirty.at(-1),false);c.dispose();

let afterDispose=0;const d=createAutosave({revision:1,initial:value(0),delay:5,write:()=>afterDispose++,status(){},clean(){}});d.update(value(1));d.dispose();await wait(10);assert.equal(afterDispose,0);
let queued=[],flags=[];const make=()=>createAutosave({revision:1,initial:value(0),write:v=>queued.push(v),clean:v=>flags.push(v),status(){}});const a=make();a.update(value(1));a.flush();a.update(value(0));assert.equal(flags.at(-1),true);a.acknowledge({request_id:queued[0].request_id,revision:2});a.flush();assert.equal(queued.length,2);assert.deepEqual(queued[1].document,value(0).document);a.dispose();const e=make();e.update(value(1));e.flush();assert.notEqual(queued[0].request_id,queued.at(-1).request_id);e.dispose();
console.log(JSON.stringify({passed:10,checks:['Opening and normalization do not save','Debounced latest edit','Stale acknowledgements ignored','Edits during save persist in next revision','Navigation waits for latest acknowledgement','Failure retains changes without retry loop','Unknown result retries same operation','Unmount clears pending timer','Undo during save remains protected until acknowledged','Reopening uses unique operation identifiers']}));
