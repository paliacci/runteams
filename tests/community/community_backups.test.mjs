import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {createLocalClient} from './community_transport_fixture.mjs';
const op='11111111-1111-4111-8111-111111111111';
function harness({pending,api=async()=>({}),flush=true}={}){
 const values=new Map(pending?[['runteams_pending_backup',JSON.stringify(pending)]]:[]),tasks=[],downloads=[],locations=[];
 const c={S:{localLibrary:{}},crypto:{randomUUID:()=>op},sessionStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},queueMicrotask:f=>tasks.push(f),api,flushDocument:async()=>flush,esc:String,accountSettingsPaint:()=>{},accountSettingsGroup:(name,body)=>`<group>${name}${body}</group>`,accountSettingsRow:(name,action,help='')=>`<row>${name}${action}${help}</row>`,location:{replace:p=>locations.push(p)},document:{body:{appendChild:()=>{}},createElement:()=>({click(){downloads.push(this.href)},remove(){}})},confirmModal:(...args)=>{c.confirm=args},RunTeamsApplication:{uploadBackup:async()=>({import_id:op,created_at:'2026-10-31T00:00:00Z'})}};
 c.window=c;
 c.navigator={language:'zh-CN'};c.addEventListener=()=>{};
 c.document.documentElement={dataset:{}};c.document.readyState='loading';c.document.addEventListener=()=>{};
 for(const name of ['locale-zh-cn','locale']){
  vm.runInNewContext(fs.readFileSync(new URL('../../web/ui/'+name+'.js',import.meta.url),'utf8'),c);
 }
 vm.runInNewContext(fs.readFileSync(new URL('../../web/ui/local-backups.js',import.meta.url),'utf8'),c);
 return {ui:c.RunTeamsBackups,c,tasks,values,downloads,locations};
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
test('an unknown result resumes the original receipt without creating a new backup',async()=>{
 const calls=[];const h=harness({pending:{operation_id:op,kind:'backup'},api:async(p,m)=>{calls.push([p,m]);return {state:'completed',kind:'backup',backup_id:op}}});h.ui.markup();assert.equal(h.ui.pending,true);await h.tasks[0]();await new Promise(r=>setImmediate(r));assert.deepEqual(calls,[[`/api/backups/${op}/status`,undefined]]);assert.equal(h.ui.pending,false);
});
test('choosing a valid file only previews until the existing confirmation accepts',async()=>{
 let writes=0;const h=harness({api:async()=>{writes++;return {state:'completed'}}});await h.ui.selected({files:[{size:50}],value:'fixture'});assert.equal(writes,0);assert.equal(h.c.confirm[0],'从备份恢复？');assert.ok(h.c.confirm[1].includes('先保留一份备份'));await h.c.confirm[2]();assert.equal(writes,1);assert.deepEqual(h.locations,['/?settings=general']);
});
test('official settings do not expose the local backup controls',()=>{const h=harness();h.c.S.localLibrary=null;assert.equal(h.ui.markup(),'')});
