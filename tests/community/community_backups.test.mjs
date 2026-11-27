import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {createLocalClient} from './community_transport_fixture.mjs';
const op='11111111-1111-4111-8111-111111111111';
function harness({pending,api=async()=>({}),flush=true}={}){
 const values=new Map(pending?[['runteams_pending_backup',JSON.stringify(pending)]]:[]),tasks=[],downloads=[],locations=[],calls=[],selects={};
 const c={S:{localLibrary:{}},crypto:{randomUUID:()=>op},sessionStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},queueMicrotask:f=>tasks.push(f),api:(...args)=>{calls.push(args);return api(...args);},flushDocument:async()=>flush,esc:String,accountSettingsPaint:()=>{},accountSettingsGroup:(name,body)=>`<group>${name}${body}</group>`,accountSettingsRow:(name,action,help='')=>`<row>${name}${action}${help}</row>`,location:{replace:p=>locations.push(p)},document:{body:{appendChild:()=>{}},createElement:()=>({click(){downloads.push(this.href)},remove(){}})},confirmModal:(...args)=>{c.confirm=args},RunTeamsApplication:{}};
 c.csel=(name,items,value,pick,options)=>{
  selects[name]={items,value,pick,options};
  return `<select>${items.find(item=>item.value===value)?.label||''}</select>`;
 };
 c.window=c;
 c.navigator={language:'zh-CN'};c.addEventListener=()=>{};
 c.document.documentElement={dataset:{}};c.document.readyState='loading';c.document.addEventListener=()=>{};
 for(const name of ['locale-zh-cn','locale']){
  vm.runInNewContext(fs.readFileSync(new URL('../../web/ui/'+name+'.js',import.meta.url),'utf8'),c);
 }
 vm.runInNewContext(fs.readFileSync(new URL('../../web/ui/local-backups.js',import.meta.url),'utf8'),c);
 return {ui:c.RunTeamsBackups,c,tasks,values,downloads,locations,calls,selects};
}
test('binary upload keeps its File body and verified generation',async()=>{
 const calls=[],file=new Blob(['backup']);const client=createLocalClient(async(p,o)=>{calls.push([p,o]);return {ok:true,json:async()=>({import_id:op})}});
 client.libraryId='library';client.generation='generation';await client.uploadBackup(file,op);
 assert.equal(calls[0][1].body,file);assert.equal(calls[0][1].headers['X-RunTeams-Library-Generation'],'generation');assert.equal(calls[0][1].headers['X-RunTeams-Operation'],op);
});
test('same UUID with a new recovery generation cannot reconnect an old write',async()=>{
 let posts=0;const client=createLocalClient(async(p,o)=>{if(p==='/')return {ok:true};if(p==='/api/library')return Response.json({storage_kind:'local',library_id:'same',generation:'new'});posts++;return Response.json({error:'expired'},{status:401})});
 client.libraryId='same';client.generation='old';await assert.rejects(client.request('/api/settings','POST',{}),e=>e.status===403);assert.equal(posts,1);assert.equal(client.generation,'old');
});
test('backup uses the shared rows and a single loading position',async()=>{
 let finish;const h=harness({api:()=>new Promise(r=>finish=r)});h.ui.markup();const running=h.ui.create();await new Promise(r=>setImmediate(r));const html=h.ui.markup();assert.equal((html.match(/env-spinner/g)||[]).length,1);assert.ok(html.includes('备份与恢复'));finish({state:'completed',kind:'backup',backup_id:op});await running;assert.equal(h.downloads.length,1);assert.equal(h.ui.pending,false);
});
test('a document flush failure sends no backup request',async()=>{
 let calls=0;const h=harness({flush:false,api:async()=>{calls++}});h.ui.markup();await h.ui.create();assert.equal(calls,0);assert.ok(h.ui.markup().includes('更改未保存'));assert.equal(h.ui.pending,false);
});
test('manual backup shows the recorded failure immediately or the reason a request was refused',async()=>{
 for(const admitted of [true,false]){
  const h=harness({api:async(p,m)=>{
   if(m)throw Object.assign(Error(admitted?'invalid_request':'Finish the file selection first'),{status:admitted?400:409});
   if(admitted)return {state:'failed',kind:'backup',error:'Managed folder is unavailable'};
   throw Object.assign(Error('not_found'),{status:404});
  }});
  await h.ui.create();
  assert.deepEqual(h.calls.map(c=>c[0]),['/api/backups',`/api/backups/${op}/status`]);
  assert.match(h.ui.markup(),/localBackup\.backupFailed/);
  assert.ok(h.ui.markup().includes(admitted?'Managed folder is unavailable':'Finish the file selection first'));
  assert.equal(h.ui.pending,false);assert.deepEqual(h.downloads,[]);
 }
});
test('a lost backup acknowledgement downloads the committed archive using its original receipt',async()=>{
 const h=harness({api:async(p,m)=>{if(m)throw Error('lost acknowledgement');return {state:'completed',kind:'backup',backup_id:op};}});
 await h.ui.create();
 assert.deepEqual(h.calls.map(c=>c[0]),['/api/backups',`/api/backups/${op}/status`]);
 assert.deepEqual(h.downloads,[`/api/backups/${op}/download`]);assert.equal(h.ui.pending,false);
});
test('an interrupted receipt check retains the operation until the original result is available',async()=>{
 let ready=false;
 const h=harness({api:async(p,m)=>{
  if(m)throw Error('lost acknowledgement');
  if(!ready)throw Object.assign(Error('not found yet'),{status:404});
  return {state:'completed',kind:'backup',backup_id:op};
 }});
 await h.ui.create();assert.equal(h.ui.pending,true);assert.match(h.ui.markup(),/localBackup\.backupUnknown/);
 ready=true;await h.ui.check();assert.equal(h.ui.pending,false);assert.deepEqual(h.downloads,[]);
 assert.deepEqual(h.calls.map(c=>c[0]),['/api/backups',`/api/backups/${op}/status`,`/api/backups/${op}/status`]);
 assert.match(h.ui.markup(),/localBackup\.backupCreated/);
});
test('an unknown result resumes the original receipt without creating a new backup',async()=>{
 const calls=[];const h=harness({pending:{operation_id:op,kind:'backup'},api:async(p,m)=>{calls.push([p,m]);return {state:'completed',kind:'backup',backup_id:op}}});h.ui.markup();assert.equal(h.ui.pending,true);await h.tasks[0]();await new Promise(r=>setImmediate(r));assert.deepEqual(calls,[[`/api/backups/${op}/status`,undefined]]);assert.equal(h.ui.pending,false);
});
test('choosing a valid file only previews until the existing confirmation accepts',async()=>{
 const h=harness(),uploads=[],file={size:50},sha256='a'.repeat(64);
 h.c.RunTeamsApplication.uploadBackup=async(...args)=>{
  uploads.push(args);return {sha256,created_at:'2026-10-31T00:00:00Z'};
 };
 await h.ui.selected({files:[file],value:'fixture'});
 assert.deepEqual(uploads,[[file,op,'preview']]);assert.equal(h.c.confirm[0],'从备份恢复？');
 assert.ok(h.c.confirm[1].includes('先保留一份备份'));await h.c.confirm[2]();
 assert.deepEqual(uploads[1],[file,op,'restore',sha256]);assert.deepEqual(h.locations,['/?settings=general']);
});
test('a file selection and a restore confirmation survive an overlapping summary read',async()=>{
 for(const readFails of [false,true]){
  let finishRead;
  const h=harness({api:()=>new Promise((resolve,reject)=>{
   finishRead=()=>readFails?reject(Error('Read interrupted')):resolve({});
  })});
  const uploads=[],file={size:50},sha256='d'.repeat(64);
  h.c.RunTeamsApplication.uploadBackup=async(...args)=>{
   uploads.push(args);return {sha256,created_at:'2026-10-31T00:00:00Z'};
  };
  const reading=h.ui.check();
  const selection=h.ui.selected({files:[file],value:'backup.zip'});
  finishRead();await Promise.all([reading,selection]);
  assert.deepEqual(uploads,[[file,op,'preview']]);
  const refreshing=h.ui.check();
  const first=h.c.confirm[2](),second=h.c.confirm[2]();
  finishRead();await Promise.all([refreshing,first,second]);
  assert.deepEqual(uploads,[[file,op,'preview'],[file,op,'restore',sha256]]);
  assert.deepEqual(h.locations,['/?settings=general']);
 }
});
test('empty and oversized files explain why they cannot be imported before uploading',async()=>{
 const h=harness();let uploads=0;
 h.c.RunTeamsApplication.uploadBackup=async()=>{uploads++;return {import_id:op};};
 for(const [size,error] of [[0,'importEmpty'],[512*1024*1024+1,'importTooLarge']]){
  const input={files:[{size}],value:'backup.zip'};await h.ui.selected(input);
  assert.equal(input.value,'');assert.ok(h.ui.markup().includes('localBackup.'+error));
  assert.equal(h.ui.pending,false);assert.equal(h.c.confirm,undefined);assert.equal(uploads,0);
 }
});
test('a refused restore keeps the reason, while an uncertain restore reloads to check its receipt',async()=>{
 for(const refused of [true,false]){
  const h=harness({api:async()=>{throw Object.assign(Error('Receipt unavailable'),{status:refused?404:403});}});
  h.c.RunTeamsApplication.uploadBackup=async(file,id,action)=>{
   if(action==='preview')return {sha256:'b'.repeat(64),created_at:'2026-10-31T00:00:00Z'};
   throw Object.assign(Error('Finish the file selection first'),{status:refused?409:0});
  };
  await h.ui.selected({files:[{size:50}],value:'backup.zip'});await h.c.confirm[2]();
  assert.deepEqual(h.calls.map(a=>a[0]),['/api/backups/'+op+'/status']);
  assert.equal(h.ui.pending,!refused);assert.equal(h.values.has('runteams_pending_backup'),!refused);
  if(refused){assert.deepEqual(h.locations,[]);assert.match(h.ui.markup(),/Finish the file selection first/);}
  else assert.deepEqual(h.locations,['/?settings=general']);
 }
});
test('a restore blocked by an unsaved work record stays in the current window without a receipt',async()=>{
 const h=harness();
 h.c.RunTeamsApplication.uploadBackup=async(file,id,action)=>{
  if(action==='preview')return {sha256:'c'.repeat(64),created_at:'2026-10-31T00:00:00Z'};
  throw Object.assign(Error('Work record unsaved'),{backupNotStarted:true});
 };
 await h.ui.selected({files:[{size:50}],value:'backup.zip'});await h.c.confirm[2]();
 assert.equal(h.ui.pending,false);assert.equal(h.values.has('runteams_pending_backup'),false);
 assert.deepEqual(h.calls,[]);assert.deepEqual(h.locations,[]);assert.match(h.ui.markup(),/Work record unsaved/);
});
test('official settings do not expose the local backup controls',()=>{const h=harness();h.c.S.localLibrary=null;assert.equal(h.ui.markup(),'')});

const summary=()=>({policy:{enabled:true,keep:7,revision:0},automatic_backups:[{backup_id:op,created_at:'2026-10-31T01:00:00Z'}]});
function policySettings(api,pending){
 const h=harness({api,pending});
 h.ui.markup();
 return h;
}
test('automatic policy and history use the original settings group, switch and menu',async()=>{
 const h=policySettings(async()=>summary());await h.ui.check();const html=h.ui.markup();assert.match(html,/class="settings-switch"/);assert.match(html,/aria-label="自动备份" aria-checked="true"/);assert.match(html,/手动备份和恢复前的备份会保留/);assert.deepEqual(Array.from(h.selects.localBackupRetention.items,i=>i.value),['7','14','30']);assert.equal(h.selects.localBackupHistory.value,op);assert.equal(h.selects.localBackupRetention.options.menuVariant,'settingsSelect');
});
test('policy save uses revision and stable operation, and never creates a backup',async()=>{
 const h=policySettings(async(p,m,d)=>m?{state:'completed',kind:'policy',policy:{enabled:false,keep:7,revision:1}}:summary());await h.ui.check();await h.ui.savePolicy({enabled:false});assert.equal(h.calls.at(-1)[0],'/api/backups/policy');assert.equal(h.calls.at(-1)[2].expected_revision,0);assert.equal(h.calls.at(-1)[2].operation_id,op);assert.ok(!h.values.has('runteams_pending_backup'));assert.match(h.ui.markup(),/aria-checked="false"/);assert.equal(h.downloads.length,0);
});
test('unknown policy outcome reads the same receipt without replaying a write',async()=>{
 const first=policySettings(async(p,m)=>{if(m)throw Error('lost acknowledgement');return summary();});await first.ui.check();await first.ui.savePolicy({keep:14});const stored=JSON.parse(first.values.get('runteams_pending_backup'));assert.equal(stored.kind,'policy');
 const next=policySettings(async p=>p.includes('/policy/')?{state:'completed',kind:'policy',policy:{enabled:true,keep:14,revision:1}}:{...summary(),policy:{enabled:true,keep:14,revision:1}},stored);await next.ui.check();assert.equal(next.calls.filter(a=>a[1]==='POST').length,0);assert.equal(next.calls[0][0],'/api/backups/policy/'+op+'/status');assert.match(next.ui.markup(),/最近 14 份/);
});
test('conflicting policy write is shown for reread instead of claiming it was saved',async()=>{
 const h=policySettings(async(p,m)=>{if(m)throw Object.assign(Error('设置已变化'),{status:409});return summary();});await h.ui.check();await h.ui.savePolicy({keep:30});assert.equal(h.ui.pending,false);assert.match(h.ui.markup(),/设置已变化/);assert.doesNotMatch(h.ui.markup(),/设置已保存/);
});
test('automatic download rechecks retention and never downloads an expired selection',async()=>{
 let expired=false;const h=policySettings(async()=>expired?{policy:summary().policy,automatic_backups:[]}:summary());await h.ui.check();await h.ui.downloadAutomatic();assert.equal(h.downloads.length,1);expired=true;await h.ui.downloadAutomatic();assert.equal(h.downloads.length,1);assert.match(h.ui.markup(),/已按保留策略清理/);
});
test('ordinary automatic maintenance is an in-context wait, with one operation indicator',async()=>{
 let resolve;const h=policySettings(async(p,m)=>m?new Promise(r=>resolve=r):summary());await h.ui.check();const saving=h.ui.savePolicy({enabled:false});await new Promise(r=>setImmediate(r));const html=h.ui.markup();assert.match(html,/aria-busy="true"/);assert.equal((html.match(/env-spinner/g)||[]).length,0);resolve({state:'completed',kind:'policy',policy:{enabled:false,keep:7,revision:1}});await saving;
 let maintained=false;const waiting=policySettings(async()=>{if(!maintained)throw Object.assign(Error('busy'),{status:409});return summary();});await waiting.ui.check();assert.doesNotMatch(waiting.ui.markup(),/role="alert"/);assert.match(waiting.ui.markup(),/完成后会更新记录/);maintained=true;await waiting.ui.check();assert.doesNotMatch(waiting.ui.markup(),/完成后会更新记录/);
});
