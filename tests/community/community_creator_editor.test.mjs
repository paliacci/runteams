import {test} from 'node:test';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {setup} from './creator_author_fixture.cjs';
test('same editor uses captured library generation and never reads official publications',async()=>{
 const e=setup();await e.author.open();assert.equal(e.author.current().file.content,'original source');
 assert.ok(e.calls.length>=5);for(const {path,options} of e.calls){assert.equal(options.headers['X-RunTeams-Library'],'library');assert.equal(options.headers['X-RunTeams-Library-Generation'],'generation-1');assert.equal(options.headers['X-RunTeams-Device-Scope'],undefined);assert.doesNotMatch(path,/publication|configuration/);}
 e.author.decorateHeader();assert.deepEqual(Array.from(e.header().extras.actions,x=>x.id),['build','resources','history']);
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
});

test('restored library generation never revives an older unsaved editor or unknown write',async()=>{
 const e=setup();await e.author.open();e.author.edit();e.author.changed('pre-restore unsaved edit');
 assert.equal(e.author.current().editing.content,'pre-restore unsaved edit');
 e.S.localLibrary.generation='generation-2';await e.author.open();
 assert.equal(e.author.current().editing,undefined);assert.equal(e.author.current().pending,undefined);
 assert.equal(e.calls.at(-1).options.headers['X-RunTeams-Library-Generation'],'generation-2');
});
