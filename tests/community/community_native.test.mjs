import {test} from 'node:test';
import assert from 'node:assert/strict';
import {NativeCloseGuard, windowsSettingsBridge} from '../../frontend/community/native.js';

test('Windows settings resolve only the matching native receipt', async () => {
  const listeners = new Set(), sent = [];
  const bridge = windowsSettingsBridge({
    addEventListener: (_, listener) => listeners.add(listener),
    removeEventListener: (_, listener) => listeners.delete(listener),
    postMessage: message => sent.push(message)
  });
  const first = bridge.postMessage({action:'get'});
  const second = bridge.postMessage({action:'set',key:'close_action',value:'background'});
  assert.equal(sent[1].split(':').slice(2).join(':'), 'set:close_action:background');
  for (const index of [1, 0]) {
    for (const listener of listeners) listener({data:{kind:'desktop-settings',id:sent[index].split(':')[1],result:{index}}});
  }
  assert.deepEqual(await Promise.all([first, second]), [{index:0}, {index:1}]);
  assert.equal(listeners.size, 0);
});

test('ready page freezes new interactions before native shutdown', () => {
  let frozen = false;
  const guard = new NativeCloseGuard(() => ({dirty:false,pending:false}), () => { frozen = true; });
  assert.equal(guard.prepareClose(), 'ready'); assert.equal(frozen, true);
});
test('dirty draft stays editable until explicit discard is chosen', () => {
  let freezes = 0;
  const guard = new NativeCloseGuard(() => ({dirty:true,pending:false}), () => { freezes++; });
  assert.equal(guard.prepareClose(), 'dirty'); assert.equal(freezes, 0);
  assert.equal(guard.prepareClose('true'), 'dirty'); assert.equal(freezes, 0);
  assert.equal(guard.prepareClose(true), 'ready'); assert.equal(freezes, 1);
});
test('pending or unknown save cannot be discarded by a native close', () => {
  let freezes = 0;
  const guard = new NativeCloseGuard(() => ({dirty:true,pending:true}), () => { freezes++; });
  assert.equal(guard.prepareClose(), 'pending'); assert.equal(guard.prepareClose(true), 'pending'); assert.equal(freezes, 0);
});
