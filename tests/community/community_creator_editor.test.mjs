import {test} from 'node:test';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {setup} from './creator_author_fixture.cjs';
test('same editor uses captured library generation and never reads official publications',async()=>{
 const e=setup();await e.author.open();assert.equal(e.author.current().file.content,'original source');
 assert.ok(e.calls.length>=5);for(const {path,options} of e.calls){assert.equal(options.headers['X-RunTeams-Library'],'library');assert.equal(options.headers['X-RunTeams-Library-Generation'],'generation-1');assert.equal(options.headers['X-RunTeams-Device-Scope'],undefined);assert.doesNotMatch(path,/publication|configuration/);}
 e.author.decorateHeader();assert.deepEqual(Array.from(e.header().extras.actions,x=>x.id),['resources','history']);
 const count=e.calls.length;assert.equal(e.author.publicationAction,undefined);assert.equal(e.context.window.RunTeamsCreatorPublication,undefined);assert.equal(e.calls.length,count);
});
test('unknown save keeps original bytes and operation; receipt clears without an official refresh',async()=>{
 const e=setup();await e.author.open();e.author.edit();e.author.changed('edited source');
 e.setRespond(async()=>{throw Error('lost response')});await e.author.save();const s=e.author.current(),pending=JSON.stringify(s.pending);assert.ok(s.pending);assert.equal(s.editing.content,'edited source');
 const revision='r-'+createHash('sha256').update(s.pending.operation_key).digest('hex');
 const reply=(original_revision)=>async path=>({ok:true,json:async()=>path.includes('/receipt?')?
  {state:'confirmed',result:{original_revision,revision}}:path.endsWith('/workspace')?{revision,source:{files:s.files}}:
  path.endsWith('/history')?{items:[],original_revision:e.id}:{...s.localDraft}});
 e.setRespond(reply('wrong-source'));await e.author.receipt();assert.equal(JSON.stringify(s.pending),pending);
 e.setRespond(reply(e.id));await e.author.receipt();assert.equal(s.pending,null);assert.equal(s.editing,null);assert.equal(s.revision,revision);
 assert.equal(e.calls.filter(c=>c.options.method==='POST'&&c.path.endsWith('/edit')).length,1);
 assert.equal(Buffer.from(JSON.parse(pending).changes[0].content_base64,'base64').toString(),'edited source');
});
test('changing restoration generation invalidates original in-flight editor',async()=>{
 const e=setup();await e.author.open();let resolve;e.setRespond(()=>new Promise(r=>resolve=r));const pending=e.author.select('project.json');e.S.localLibrary.generation='generation-2';resolve({ok:true,json:async()=>({sha256:'hash',kind:'text',content:'late'})});await pending;assert.equal(e.author.current(),null);
});
test('explicit save conflict retains file editing and the original error',async()=>{
 const e=setup();await e.author.open();e.author.edit();e.author.changed('keep edit');
 e.setRespond(async path=>path.endsWith('/edit')?{ok:false,status:409,json:async()=>({error:'newer revision',code:'source_revision_conflict'})}:{ok:false,status:503,json:async()=>({error:'offline'})});
 await e.author.save();assert.equal(e.author.current().editing.content,'keep edit');assert.equal(e.author.current().pending,null);assert.match(e.author.current().error,/offline|newer/);
 e.setRespond((url, options) => url.endsWith('/edit')
   ? Response.json({error:'source updated', code:'source_revision_conflict'}, {status:409})
   : e.defaultRespond(url, options));
 await e.author.save();
 assert.equal(e.author.current().editing.content, 'keep edit');
 assert.equal(e.author.current().error, 'source updated');

});

test('restored library generation never revives an older unsaved editor or unknown write',async()=>{
 const e=setup();await e.author.open();e.author.edit();e.author.changed('pre-restore unsaved edit');
 assert.equal(e.author.current().editing.content,'pre-restore unsaved edit');
 e.S.localLibrary.generation='generation-2';await e.author.open();
 assert.equal(e.author.current().editing,undefined);assert.equal(e.author.current().pending,undefined);
 assert.equal(e.calls.at(-1).options.headers['X-RunTeams-Library-Generation'],'generation-2');
});

test('opening a selected employee reads its soul and syncing preserves the selected file', async () => {
  const e = setup();
  const employee = 'employees/second.json';
  const soul = 'employees/second/Soul.md';
  e.S.conversationPanel.context.creator_employee_source = employee;
  e.files.push({path: employee, sha256: 'hash'}, {path: soul, sha256: 'hash'});
  e.setRespond(async (url, options) => {
    const path = new URL(url, 'http://fixture').searchParams.get('path');
    if (path === employee || path === soul) {
      const content = path === employee ? JSON.stringify({soul_file: soul}) : 'second employee';
      return Response.json({kind: 'text', sha256: 'hash', content});
    }
    return e.defaultRespond(url, options);
  });
  await e.author.open();
  assert.equal(e.author.current().activeFile, soul);
  assert.equal(e.author.current().file.content, 'second employee');
  assert.ok(!e.calls.some(call => call.path.includes('path=project.json')));
  await e.author.select(employee);
  await e.author.sync();
  assert.equal(e.author.current().activeFile, employee);
});

test('explicit retry after an unknown receipt reuses the exact save request', async () => {
  const e = setup();
  await e.author.open();
  e.author.edit();
  e.author.changed('retained text');
  e.setRespond(async () => { throw Error('lost response'); });
  await e.author.save();
  const edits = () => e.calls.filter(call => call.path.endsWith('/edit'));
  const original = edits()[0].options.body;
  assert.equal(JSON.parse(original).base_revision, e.id);
  await e.author.retryLocalSave();
  assert.equal(edits().length, 1);
  const revision = 'r-' + createHash('sha256').update(JSON.parse(original).operation_key).digest('hex');
  e.setRespond(async (url, options) => {
    if (url.includes('/receipt?')) return Response.json({state: 'unknown'});
    if (url.endsWith('/edit')) return Response.json({revision, original_revision: e.id});
    if (url.endsWith('/workspace')) return Response.json({revision, source: {files: e.files}});
    if (url.includes('/file?')) return Response.json({kind: 'text', sha256: 'hash', content: 'retained text'});
    return e.defaultRespond(url, options);
  });
  await e.author.receipt();
  await e.author.retryLocalSave();
  assert.deepEqual(edits().map(call => call.options.body), [original, original]);
  assert.equal(e.author.current().pending, null);
  assert.equal(e.author.current().file.content, 'retained text');
});

test('a running build retains its baseline and blocks a second start while editing remains available', async () => {
  const e = setup();
  await e.author.open();
  e.setRespond(async (url, options) => {
    assert.ok(url.endsWith('/build'));
    const request = JSON.parse(options.body);
    assert.equal(request.base_revision, e.id);
    return Response.json({state: 'running', revision: e.id, operation_key: request.operation_key});
  });
  await e.author.buildLocal();
  assert.equal(e.author.current().build.latest.state, 'running');
  await e.author.buildLocal();
  assert.equal(e.calls.filter(call => call.options.method === 'POST' && call.path.endsWith('/build')).length, 1);
  e.author.edit();
  assert.ok(e.author.current().editing);
});

test('a lost build reply can be reconciled and a late read cannot cross a library change', async () => {
  const e = setup();
  await e.author.open();
  e.setRespond(async () => { throw Error('lost response'); });
  await e.author.buildLocal();
  const state = e.author.current();
  assert.ok(state.buildError);
  const completed = {latest: {state: 'succeeded', operation_key: state.buildRequest.operation_key, revision: e.id}};
  e.setRespond(async () => Response.json(completed));
  await e.author.readBuild();
  assert.equal(state.buildError, '');
  assert.equal(state.buildRequest, null);
  let finish;
  e.setRespond(() => new Promise(resolve => { finish = resolve; }));
  const read = e.author.readBuild();
  e.S.localLibrary.generation = 'generation-2';
  finish(Response.json({latest: {state: 'failed'}}));
  await read;
  assert.equal(e.author.current(), null);
  assert.equal(state.build.latest.state, 'succeeded');
});

test('source export downloads only the requested revision from the active library', async () => {
  const e = setup();
  await e.author.open();
  const downloads = [];
  e.context.URL = {createObjectURL: () => 'blob:fixture', revokeObjectURL() {}};
  e.context.setTimeout = () => 0;
  e.context.document.body = {appendChild() {}};
  e.context.document.createElement = () => ({click() { downloads.push(this.download); }, remove() {}});
  const archive = revision => new Response('archive', {headers: {
    'Content-Type': 'application/zip', 'Content-Length': '7', 'X-RunTeams-Source-Revision': revision,
  }});
  e.setRespond(async () => archive(e.id));
  await e.author.exportSource();
  const {path, options} = e.calls.at(-1);
  assert.ok(path.endsWith('/' + e.id + '/export?revision=' + e.id));
  assert.equal(options.headers['X-RunTeams-Library-Generation'], 'generation-1');
  assert.deepEqual(downloads, ['runteams-source-' + e.id.slice(0, 12) + '.zip']);
  e.setRespond(async () => archive('another-revision'));
  await e.author.exportSource();
  assert.ok(e.author.current().error);
  e.setRespond(async () => new Response('', {status: 409}));
  await e.author.exportSource();
  assert.ok(e.author.current().error);
  let finish;
  e.setRespond(() => new Promise(resolve => { finish = resolve; }));
  const late = e.author.exportSource();
  e.events['runteams:business-scope-will-change']();
  assert.equal(e.calls.at(-1).options.signal.aborted, true);
  finish(archive(e.id));
  await late;
  assert.equal(downloads.length, 1);
});
