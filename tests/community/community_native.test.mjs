import {test} from 'node:test';
import assert from 'node:assert/strict';
import {NativeCloseGuard} from '../../frontend/community/native.js';

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
