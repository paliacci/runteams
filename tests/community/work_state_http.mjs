// Component integration over the actual scoped local HTTP server; no browser APIs.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import {createLocalClient} from './community_transport_fixture.mjs';
let input='';for await(const chunk of process.stdin)input+=chunk;
const {origin,token,mode,original}=JSON.parse(input);let drop=mode==='seed';const writes=[];
const client=createLocalClient(async(path,options={})=>{
 const response=await fetch(origin+path,{...options,headers:{...options.headers,Authorization:'Bearer '+token}});
 if(path.endsWith('ui-state-save')){writes.push(options.body);if(drop&&response.ok){drop=false;throw Error('explicit isolated lost persistence acknowledgement');}}
 return response;
});
const library=await client.connect();
const c={Map,JSON,Number,Object,Promise,Error,queueMicrotask,crypto:crypto.webcrypto,_workspaceBusinessGeneration:1,S:{localLibrary:library,account:{signed_in:false}},api:(...args)=>client.request(...args)};
c.window=c;c.workspaceAccountCacheToken=()=>JSON.stringify(c.S.localLibrary);c.workspaceDeviceStorageScope=()=>JSON.stringify(['library',library.library_id]);
Object.defineProperty(c,'localStorage',{get(){throw Error('Native browser storage must not be required');}});
vm.runInNewContext(fs.readFileSync(new URL('../../web/ui/work-state.js',import.meta.url),'utf8'),c);
const state=c.RunTeamsWorkState,key='runteams.pipeline-control:'+c.workspaceDeviceStorageScope()+':HTTP-fixture';await state.connect();
if(mode==='seed'){
 state.setItem(key,JSON.stringify({operation_id:original}));try{await state.flush();throw Error('Expected dropped acknowledgement');}catch(error){if(!error.message.includes('lost persistence'))throw error;}
 await state.flush();if(writes.length!==2||writes[0]!==writes[1])throw Error('Persistence retry changed original operation');
}else{
 if(JSON.parse(state.getItem(key)).operation_id!==original)throw Error('Fresh process lost original operation');
 state.removeItem(key);await state.flush();
}
console.log(JSON.stringify({mode,original,writes:writes.length,pending:state.pending,restored:mode==='cold'}));
