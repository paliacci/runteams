import {test} from 'node:test';
import assert from 'node:assert/strict';
import {connectHostTheme} from '../host.js';

test('host theme follows snapshots, preserves drafts and detaches once', () => {
  const root = {dataset:{theme:'light'}, draft:'unsaved'};
  let state = {theme:'dark'}, listener, removed = 0;
  const host = {version:'0.1.0',kind:'platform',getSnapshot:()=>state,
    subscribe(fn) {listener=fn; return ()=>removed++;}};
  const binding = connectHostTheme(host, root);
  assert.equal(root.dataset.theme,'dark');
  state={theme:'light'};listener();
  assert.equal(root.dataset.theme,'light');assert.equal(root.draft,'unsaved');
  binding.dispose();binding.dispose();state={theme:'dark'};listener();
  assert.equal(removed,1);assert.equal(root.dataset.theme,'light');
});
test('missing host and unknown theme fail explicitly without fixture fallback', () => {
  assert.throws(()=>connectHostTheme(null,{dataset:{}}),/unavailable/);
  for (const theme of ['system', '', null, '<script>']) {
    const root={dataset:{theme:'light'}};
    assert.throws(()=>connectHostTheme({version:'0.1.0',kind:'platform',
      getSnapshot:()=>({theme}),subscribe(){}},root),/invalid/);
    assert.equal(root.dataset.theme,'light');
  }
});

import {createHostControls} from '../host.js';
function fixture() {
  let snapshot={theme:'light',presentation:{mode:'panel',viewId:null}},change,action,hold;
  const requests=[];
  const host={version:'0.1.0',kind:'platform',capabilities:['presentation','drawer-header'],getSnapshot:()=>snapshot,
    subscribe(fn){change=fn;return()=>{change=null;}},onAction(fn){action=fn;return()=>{action=null;}},
    async request(method,params){requests.push({method,params});if(hold)await hold;
      if(method==='present'){snapshot={...snapshot,presentation:{mode:params.mode,viewId:params.viewId}};change?.();}
      return snapshot.presentation;}};
  return {host,requests,action:value=>action?.(value),hold:value=>hold=value};
}
test('native display completion is acknowledged; metadata and actions stay separate from business',async()=>{
  const f=fixture(),client=createHostControls(f.host);let pressed=0;
  await client.setHeader({text:'<b>literal</b>',actions:[{id:'inspect',label:'Inspect',onPress(){pressed++;}}]});
  const original=f.requests.at(-1).params.ticket;
  assert.equal(JSON.stringify(f.requests).includes('onPress'),false);
  f.action({revision:original,id:'inspect'});assert.equal(pressed,1);
  await client.setHeader({actions:[{id:'inspect',label:'Disabled',disabled:true,onPress(){pressed++;}}]});
  f.action({revision:original,id:'inspect'});f.action({revision:f.requests.at(-1).params.ticket,id:'inspect'});assert.equal(pressed,1);
  await client.openFull('module');assert.equal(client.getSnapshot().mode,'full');
  await assert.rejects(client.openFull('other'),/return-required/);
  await client.returnToPanel();assert.equal(client.getSnapshot().viewId,null);
  await client.dispose();assert.deepEqual(f.requests.at(-1).params.actions,[]);
});
test('native controls reject malformed descriptors before dispatch',async()=>{
  const f=fixture(),client=createHostControls(f.host);
  await assert.rejects(client.setHeader({actions:[{id:'same',label:'a',onPress(){}},{id:'same',label:'b',onPress(){}}]}));
  await assert.rejects(client.setHeader({text:'x'.repeat(257)}));
  await assert.rejects(client.setHeader({actions:[{id:'x',label:'',onPress(){}}]}));
  await assert.rejects(client.openFull('../url'));assert.equal(f.requests.length,0);
  await client.dispose();
});
test('one controller owns a document and concurrent requests do not overwrite callbacks',async()=>{
  const f=fixture(),client=createHostControls(f.host);let release;
  assert.throws(()=>createHostControls(f.host),/already_connected/);
  f.hold(new Promise(resolve=>release=resolve));const opening=client.openFull('module');
  await assert.rejects(client.setHeader({text:'overlap'}),/busy/);assert.equal(f.requests.length,1);
  release();await opening;f.hold(null);await client.dispose();await createHostControls(f.host).dispose();
});
test('disposing an in-flight request asks native to cancel and ignores late acknowledgement',async()=>{
  const f=fixture(),client=createHostControls(f.host);let release;
  f.hold(new Promise(resolve=>release=resolve));const opening=client.openFull('module');
  const expected=f.requests[0].params.ticket;const disposed=client.dispose();
  assert.equal(f.requests.at(-1).method,'cancel');assert.equal(f.requests.at(-1).params.ticket,expected);
  release();await assert.rejects(opening,/disposed/);await disposed;assert.equal(client.getSnapshot().mode,'panel');
});
