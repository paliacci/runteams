/* Native Supabase assets. Numeric UI handles never cross the business boundary. */
(function(root){
 'use strict';
 let profile=null,scope=null,sequence=0;
 const employees=new Map(),releases=new Map(),skills=new Map();
 const token=()=>`${RunTeamsBusinessStorage.generation()}:${workspaceAccountCacheToken()}`;
 const stale=()=>Object.assign(new Error('工作区已改变，请重新打开。'),{code:'business_scope_changed'});
 function reset(){profile=null;scope=null;sequence++;employees.clear();releases.clear();skills.clear();}
 async function request(action,body={},options={}){
   const start=token(),seq=sequence;
   const value=await api('/api/assets/read/'+action,'POST',body,options);
   if(start!==token()||seq!==sequence)throw stale();
   if(value?.error)throw Object.assign(new Error(value.error),{code:value.code});
   return value;
 }
 async function session(){
   const value=await request('session',{}, {readCurrent:true});
   const next=value.profile;
   if(profile&&['deployment_id','workspace_id','actor_id','data_epoch'].some(key=>next[key]!==profile[key]))reset();
   profile=next;scope=token();return value;
 }
 async function hydrate(value){
   const start=token(),seq=sequence,next=value?.profile,publicProfile=value?.workspace_profile;
   const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v);
   if(!S.account?.signed_in||!next||Object.keys(next).sort().join(',')!=='actor_id,data_epoch,deployment_id,readonly,revision,schema,workspace_id'||
      next.schema!=='runteams.native-workspace/v1'||next.actor_id!==S.account.user_id||!uuid(next.actor_id)||
      next.workspace_id!==(S.activeOrganization||S.account.user_id)||!uuid(next.workspace_id)||!uuid(next.data_epoch)||
      next.deployment_id!==S.account.auth_issuer||!Number.isSafeInteger(next.revision)||next.revision<0||typeof next.readonly!=='boolean'||
      !publicProfile||Object.keys(publicProfile).sort().join(',')!=='actor_scope,data_epoch,product_model_version,schema'||
      publicProfile.schema!=='runteams.workspace-profile/v2'||publicProfile.product_model_version!==2||publicProfile.data_epoch!==next.data_epoch)throw stale();
   const domain=[next.deployment_id,next.workspace_id,next.actor_id].join('\n');
   const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(domain));
   const actorScope=Array.from(new Uint8Array(digest),n=>n.toString(16).padStart(2,'0')).join('');
   if(start!==token()||seq!==sequence||actorScope!==publicProfile.actor_scope)throw stale();
   if(profile&&['deployment_id','workspace_id','actor_id','data_epoch'].some(key=>next[key]!==profile[key]))reset();
   profile=structuredClone(next);scope=start;
 }
 async function current(){if(!profile||scope!==token())await session();return profile;}
 function remember(reference){
   if(reference?.resource==='employees')employees.set(Number(reference.id),structuredClone(reference));
 }
 async function reference(id){
   await current();const ref=employees.get(Number(id));
   if(!ref)throw new Error('员工链接尚未确认，请刷新员工列表。');
   return structuredClone(ref);
 }
 async function all(action,options={}){
   const p=await current(),start=token(),seq=sequence,items=[];let after=null;
   do{const page=await request(action,{profile:p,after,limit:40},options);items.push(...page.items);after=page.next_after;}while(after);
   if(start!==token()||seq!==sequence)throw stale();return items;
 }
 async function restoreTrash(item,operation){
   return assetCommand('employee-restore',item.reference,item.revision,operation);
 }
 async function purgeTrash(item,operation){return assetCommand('employee-purge',item.reference,item.revision,operation);}
 async function assetCommand(action,ref,revision,operation){
   await current();const start=token(),seq=sequence,key='asset-admin:'+action+':'+ref.id;
   let saved=RunTeamsBusinessStorage.getItem(key);saved=saved?JSON.parse(saved):null;
   const data=saved||{reference:ref,expected_revision:revision,operation_id:operation||crypto.randomUUID()};
   if(!sameReference(data.reference,ref))throw stale();
   if(!saved)RunTeamsBusinessStorage.setItem(key,JSON.stringify(data));
   const result=await api('/api/assets/command/'+action,'POST',data);
   if(start!==token()||seq!==sequence)throw stale();
   if(result?.error){if(['22023','PT409','conflict','PT404','42501','PT423'].includes(result.code))RunTeamsBusinessStorage.removeItem(key);throw Object.assign(new Error(result.error),{code:result.code});}
   RunTeamsBusinessStorage.removeItem(key);
   return result;
 }
 async function authoring(id,runtime){
   id=Number(id);if(!Number.isSafeInteger(id)||id<1)throw new Error('请选择已有员工的源码。');
   const p=await current(),start=token(),seq=sequence;
   const ref=await reference(id);
   const result=await api('/api/assets/command/employee-authoring-session','POST',{
     profile:p,reference:ref,runtime:{channel_id:runtime.channel_id??null,model:runtime.model||'',reasoning_effort:runtime.reasoning_effort||''}});
   if(start!==token()||seq!==sequence)throw stale();
   if(result?.error)throw Object.assign(new Error(result.error),{code:result.code});
   return result;
 }
 async function history(id){
   const ref=await reference(id),items=[];let before=null;
   do{const page=await request('employee-releases',{reference:ref,before,limit:100});
     for(const row of page.items){releases.set(`${id}@${row.id}`,row.reference);items.push(row);}before=page.next_before;
   }while(before);return {releases:items};
 }
 async function releaseReference(id,releaseId){
   if(!releases.has(`${id}@${releaseId}`))await history(id);
   const ref=releases.get(`${id}@${releaseId}`);if(!ref)throw new Error('发布版本尚未确认，请重新读取。');return ref;
 }
 async function skillCatalog(){
   const packages=await all('skill-catalog');for(const row of packages)skills.set(`${row.package_key}@${row.revision_id}`,row.reference);return {packages};
 }
 async function skillRevision(key,id){
   await current();const ref=skills.get(`${key}@${id}`);
   if(!ref)throw new Error('所选技能版本尚未确认，请重新读取。');
   const row=await request('skill-revision',{reference:ref});
   if(row.package_key!==key||row.revision_id!==Number(id))throw new Error('所选技能版本不匹配。');return row;
 }
 async function employeeRequest(path,method='GET',body){
   const match=/^\/api\/core\/employees\/(\d+)(.*)$/.exec(path);
   if(!match)throw new Error('员工入口无法识别。');
   const id=Number(match[1]),suffix=match[2],ref=await reference(id);
   if(method==='POST'&&suffix==='/trash'){
     const item=await request('employee-summary',{reference:ref});
     if(!Number.isSafeInteger(item.draft_revision))throw Error('员工版本尚未确认，请重新读取');
     return assetCommand('employee-trash',ref,item.draft_revision);
   }
   if(method==='POST')throw new Error('员工须通过 SDK 源码编辑、构建与发布。');
   if(method==='GET'&&!suffix)return request('employee-summary',{reference:ref});
   if(method==='GET'&&suffix==='/releases')return history(id);
   const release=/^\/releases\/(\d+)\/definition$/.exec(suffix);
   if(method==='GET'&&release)return request('release-definition',{reference:ref,release_reference:await releaseReference(id,Number(release[1]))});
   // A missing native action must never silently call the retired service.
   throw new Error('这项员工操作尚未接通，请稍后重试。');
 }
 function sameReference(a,b){return !!a&&!!b&&['schema','deployment_id','workspace_id','data_epoch','resource','id'].every(key=>a[key]===b[key]);}
 async function localWork(item,downloaded){
   const existing=downloaded.find(row=>sameReference(row.native_asset?.employee_reference,item.reference));
   // Starting more work does not silently adopt a newer asset release. A full
   // already-acquired personal release works without a platform round trip.
   if(existing)return {employee_id:existing.id,acquired:false};
   const release=item.active_release?.reference;
   if(!release)throw new Error('请先发布员工版本，再开始工作。');
   const ref=await reference(item.id),start=token(),seq=sequence;
   if(!sameReference(ref,item.reference))throw stale();
   const result=await api('/api/assets/command/employee-download','POST',{reference:ref,release_reference:release});
   if(start!==token()||seq!==sequence)throw stale();
   if(result?.error)throw Object.assign(new Error(result.error),{code:result.code});
   if(result.storage_scope!=='device'||!Number.isSafeInteger(result.employee_id)||!sameReference(result.native_asset?.employee_reference,ref)||!sameReference(result.native_asset?.release_reference,release))throw new Error('所选员工版本尚未完整取得，请重试。');
   return {employee_id:result.employee_id,acquired:true};
 }
 root.RunTeamsNativeAssets=Object.freeze({session,hydrate,remember,reference,history,skillCatalog,skillRevision,employeeRequest,localWork,authoring,restoreTrash,purgeTrash,reset});
 root.addEventListener?.('runteams:business-scope-changed',reset);
})(window);
