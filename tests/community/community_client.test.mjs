import {test} from 'node:test';
import assert from 'node:assert/strict';
import {LocalAPIError, PendingWrite} from '../../frontend/community/client.js';

import {createLocalClient} from './community_transport_fixture.mjs';

const library = 'a1111111-1111-4111-8111-111111111111';
const reference = {schema:'runteams.local-asset/1', library_id:library, id:'b2222222-2222-4222-8222-222222222222', kind:'employee'};
const receipt = body => ({reference, operation_id:body.operation_id, revision:1, sha256:'a'.repeat(64)});
const response = (status, value) => Response.json(value,{status});

test('unknown response keeps exactly the same operation and source text for retry', async () => {
  const sent = []; let drop = true;
  const source_text = '{"large":900719925474099312345}';
  const client = {libraryId:library, request:async (path, method, body) => { sent.push(JSON.stringify(body)); if (drop) { drop = false; throw new Error('lost response'); } return receipt(body); }};
  const writer = new PendingWrite(client); writer.prepare('/api/assets/import', {kind:'employee', name:'Own', source_text});
  await assert.rejects(writer.send()); assert.ok(writer.operation);
  assert.throws(() => writer.prepare('/api/assets/import', {}));
  const saved = await writer.send(); assert.equal(writer.operation, null);
  assert.equal(sent[0], sent[1]); assert.equal(saved.body.source_text, source_text);
});

test('server uncertainty and scope change retain the original operation', async () => {
  for (const status of [0, 403, 500, 503]) {
    const writer = new PendingWrite({libraryId:library, request:async () => { throw new LocalAPIError('not_confirmed', status); }});
    writer.prepare('/api/assets/import', {kind:'employee', name:'One', source_text:'{}'});
    const original = structuredClone(writer.operation); await assert.rejects(writer.send());
    assert.deepEqual(writer.operation, original);
  }
});

test('explicit validation or conflict rejection releases the pending operation', async () => {
  for (const status of [400, 404, 409, 413, 415]) {
    const writer = new PendingWrite({libraryId:library, request:async () => { throw new LocalAPIError('rejected', status); }});
    writer.prepare('/api/assets/import', {kind:'employee', name:'One', source_text:'{}'});
    await assert.rejects(writer.send()); assert.equal(writer.operation, null);
  }
});

test('mismatched receipt cannot confirm a save', async () => {
  for (const change of [{operation_id:'another'}, {reference:{...reference, library_id:'other'}}, {reference:{...reference, kind:'pipeline'}}, {sha256:'invalid'}, {revision:0}]) {
    const writer = new PendingWrite({libraryId:library, request:async (path, method, body) => ({...receipt(body), ...change})});
    writer.prepare('/api/assets/import', {kind:'employee', name:'One', source_text:'{}'});
    await assert.rejects(writer.send(), /invalid_receipt/); assert.ok(writer.operation);
  }
});

test('receipt reference key ordering does not prevent recovery', async () => {
  const client = {libraryId:library, request:async (path, method, body) => ({...receipt(body), reference:{id:reference.id, kind:'employee', library_id:library, schema:reference.schema}})};
  const writer = new PendingWrite(client); writer.prepare('/api/assets/rename', {reference, name:'Renamed', expected_revision:1});
  await writer.send(); assert.equal(writer.operation, null);
});

test('connection renewal verifies the same library before repeating the request', async () => {
  const calls = []; let first = true;
  const fetcher = async (path, options) => {
    calls.push({path, options});
    if (path === '/') return {ok:true};
    if (path === '/api/library') return response(200, {storage_kind:'local', generation:'test-generation', library_id:library});
    if (first) { first = false; return response(401, {error:'local_session_required'}); }
    return response(200, {items:[]});
  };
  const client = createLocalClient(fetcher); client.libraryId = library;
  await client.request('/api/assets');
  assert.deepEqual(calls.map(call => call.path), ['/api/assets','/','/api/library','/api/assets']);
  assert.equal(calls[3].options.headers['X-RunTeams-Library'], library);
  assert.equal(calls[2].options.headers['X-RunTeams-Library'], undefined);
  assert.equal(calls[0].options.credentials, 'same-origin');
});

test('different library after reconnect cannot receive an old pending import', async () => {
  const calls = [];
  const client = createLocalClient(async (path, options) => {
    calls.push({path, options});
    if (path === '/') return {ok:true};
    if (path === '/api/library') return response(200, {storage_kind:'local', generation:'test-generation', library_id:'different'});
    return response(401, {error:'local_session_required'});
  });
  client.libraryId = library;
  const writer = new PendingWrite(client); writer.prepare('/api/assets/import', {kind:'employee', name:'Own', source_text:'{}'});
  await assert.rejects(writer.send(), /library_scope_changed/);
  assert.equal(calls.filter(call => call.options.method === 'POST').length, 1);
  assert.ok(writer.operation); assert.equal(client.libraryId, library);
});
