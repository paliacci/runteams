/* Backup controls in the existing settings rows; data stays in the host library. */
(function(global){
 'use strict';
 const key='runteams_pending_backup';let loaded=false,busy=false,busyKind='',pending=null,notice='',error='',latest=null,safety=null,policy=null,automatic=[],automaticError='',selectedBackup='',automaticWaiting=false;
 const text=(name,vars={})=>global.RunTeamsLocale.t('localBackup.'+name,vars);
 const label=(name,vars={})=>`<span data-app-i18n="localBackup.${name}"${Object.keys(vars).length?` data-app-i18n-vars="${esc(JSON.stringify(vars))}"`:''}>${esc(text(name,vars))}</span>`;
 const aria=name=>`data-app-i18n-aria-label="localBackup.${name}" aria-label="${esc(text(name))}"`;
 const date=(value,language)=>{
  const instant=new Date(value);
  return Number.isNaN(instant.valueOf())?text('unknownDate'):new Intl.DateTimeFormat(language,{dateStyle:'medium',timeStyle:'short'}).format(instant);
 };
 const report=(name,detail='')=>{error={name,detail};};
 const requestError=(cause,fallback)=>report(cause.status===403?'libraryChanged':cause.message==='backup_operation_storage'?'operationStorage':fallback,cause.status===403||cause.message==='backup_operation_storage'?'':cause.message);
 const valid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
 const paint=()=>{if(typeof accountSettingsPaint==='function')accountSettingsPaint();};
 function remember(value){
  const raw=JSON.stringify(value);
  try{
   sessionStorage.setItem(key,raw);
   if(sessionStorage.getItem(key)!==raw)throw Error();
  }catch{throw Error('backup_operation_storage');}
  pending=value;automaticWaiting=false;
 }
 function forget(){sessionStorage.removeItem(key);pending=null;}
 function download(id){if(!valid(id))return;const link=document.createElement('a');link.href='/api/backups/'+id+'/download';link.download='RunTeams-backup.zip';document.body.appendChild(link);link.click();link.remove();}
 function confirmed(value){
  automaticWaiting=false;
  if(value.state==='pending'){notice='pending';return false;}
  if(value.state==='failed'){report(value.kind==='restore'?'restoreFailed':value.kind==='policy'?'policyFailed':'backupFailed',value.error);forget();return false;}
  if(value.state!=='completed')throw Error('backup_receipt_invalid');
  if(value.kind==='policy'){policy=value.policy;notice='policySaved';}
  else if(value.kind==='backup'){latest=value.backup_id;notice='backupCreated';}
  else{safety=value.safety_backup_id;notice='restoreDone';}
  forget();return true;
 }
 async function check(){
  if(busy)return;busy=true;busyKind=pending?.kind||'';error='';paint();
  try{
   const policyCheck=pending?.kind==='policy';
   if(pending)confirmed(await api('/api/backups/'+(policyCheck?'policy/':'')+pending.operation_id+'/status'));
   if(!pending&&(!busyKind||policyCheck)){
    const value=await api('/api/backups');automaticWaiting=false;latest=value.last_backup?.backup_id||null;safety=value.last_restore?.safety_backup_id||null;
    policy=value.policy||null;automatic=value.automatic_backups||[];automaticError=value.automatic_error?{name:value.automatic_error.stage==='retention'?'retentionFailed':'automaticFailed',detail:value.automatic_error.error}:null;
    if(!automatic.some(v=>v.backup_id===selectedBackup))selectedBackup=automatic[0]?.backup_id||'';
   }
  }catch(e){if(e.status===409&&!pending)automaticWaiting=true;else if(e.status===404&&pending){forget();report('operationAbsent');}else requestError(e,pending?'operationUnknown':'readFailed');}
  finally{busy=false;paint();}
 }
 async function savePolicy(patch){
  if(busy||pending||!policy)return;busy=true;busyKind='policy';error='';notice='';
  try{
   remember({operation_id:crypto.randomUUID(),kind:'policy',expected_revision:policy.revision,patch});paint();
   const {kind,...data}=pending;confirmed(await api('/api/backups/policy','POST',data));
  }catch(e){if([400,403,409].includes(e.status)){forget();policy=null;}requestError(e,e.status===409?'policyChanged':pending?'policyUnknown':'policyFailed');}
  finally{busy=false;paint();}
 }
 async function downloadAutomatic(){
  if(busy||pending||!valid(selectedBackup))return;const id=selectedBackup;
  await check();if(error)return;if(automatic.some(v=>v.backup_id===id))download(id);
  else{report('backupExpired');paint();}
 }
 async function createReceipt(id){
  try{return await api('/api/backups','POST',{operation_id:id});}
  catch(writeError){
   if(writeError.status===403)throw writeError;
   // The host can commit a final receipt even when its response is lost or reports an error.
   try{return await api('/api/backups/'+id+'/status');}
   catch(readError){
    if(readError.status===403)throw readError;
    if(readError.status===404&&[400,409].includes(writeError.status))forget();
    throw writeError;
   }
  }
 }
 async function start(){
  if(busy||pending)return;busy=true;busyKind='backup';error='';notice='';
  try{
   if(!await flushDocument()){report('documentPending');return;}
   remember({operation_id:crypto.randomUUID(),kind:'backup'});paint();
   const value=await createReceipt(pending.operation_id);
   if(confirmed(value))download(value.backup_id);
  }catch(e){requestError(e,pending?'backupUnknown':'backupFailed');}
  finally{busy=false;paint();}
 }
 async function selected(input){
  const file=input.files?.[0];input.value='';if(!file||busy||pending)return;
  if(file.size===0){report('importEmpty');paint();return;}
  if(file.size>512*1024*1024){report('importTooLarge');paint();return;}
  busy=true;busyKind='import';error='';notice='';paint();let preview;
  try{preview=await RunTeamsApplication.uploadBackup(file,crypto.randomUUID());}
  catch(e){requestError(e,e.status===413?'importTooLarge':e.status===415?'importNotZip':'importFailed');}
  finally{busy=false;paint();}
  if(!preview)return;
  const dates={dateZh:date(preview.created_at,'zh-CN'),dateEn:date(preview.created_at,'en')};
  confirmModal(text('restoreTitle'),text('restoreMessage',dates),()=>restore(preview.import_id),true,{
   titleKey:'localBackup.restoreTitle',messageKey:'localBackup.restoreMessage',messageVars:dates,
   action:text('restore'),actionKey:'localBackup.restore',cancel:text('cancel'),cancelKey:'localBackup.cancel',
   close:text('close'),closeKey:'localBackup.close',focusCancel:true,returnFocus:()=>document.getElementById('localBackupRestore')
  });
 }
 async function restore(importId){
  if(busy||pending||!valid(importId))return;busy=true;busyKind='restore';error='';notice='';
  try{
   if(!await flushDocument()){report('documentPending');return;}
   remember({operation_id:crypto.randomUUID(),kind:'restore'});paint();
   await api('/api/backups/restore','POST',{operation_id:pending.operation_id,import_id:importId});
   // A full reload starts a new verified library generation. Other open
   // windows cannot write with the old generation, even for the same UUID.
   location.replace('/?settings=general');
  }catch(e){
   if(pending&&pending.kind==='restore'){location.replace('/?settings=general');return;}
   requestError(e,'restoreNotStarted');
  }finally{busy=false;paint();}
 }
 function initialize(){
  if(loaded)return;loaded=true;
  try{const raw=sessionStorage.getItem(key);if(raw){const value=JSON.parse(raw);if(!valid(value.operation_id)||!['backup','restore','policy'].includes(value.kind))throw Error('backup_receipt_invalid');pending=value;}}
  catch(e){report('invalidOperation');return;}
  queueMicrotask(()=>void check());
 }
 function markup(){
  if(typeof S==='undefined'||!S.localLibrary)return '';
  initialize();const disabled=busy||!!pending,spin='<span class="env-spinner" aria-hidden="true"></span>';
  const backupAction=`<button class="btn" type="button" onclick="RunTeamsBackups.create()" ${disabled?'disabled':''}>${busy&&busyKind==='backup'?spin+label('creating'):label('create')}</button>`;
  const restoreAction=`<button class="btn" type="button" id="localBackupRestore" onclick="RunTeamsBackups.choose()" ${disabled?'disabled':''}>${busy&&['import','restore'].includes(busyKind)?spin+label(busyKind==='import'?'readingFile':'restoring'):label('choose')}</button><input id="localBackupImport" type="file" accept=".zip,application/zip" hidden onchange="RunTeamsBackups.selected(this)">`;
  const message=automaticWaiting?'automaticWaiting':notice;
  const retry=`<button class="btn" onclick="RunTeamsBackups.check()">${label(pending?'checkOperation':'reload')}</button>`;
  const details=value=>value.detail?`<details><summary>${label('details')}</summary><p translate="no">${esc(value.detail)}</p></details>`:'';
  const warning=value=>`<div class="settings-inline-error" role="alert"><div>${label(value.name)}${details(value)}</div>${retry}</div>`;
  const status=error?warning(error):message?`<p class="settings-footnote" role="status">${label(message)}</p>`:'';
  const save=id=>`<button class="btn" onclick="RunTeamsBackups.download('${esc(id)}')">${label('saveFile')}</button>`;
  const saved=latest?accountSettingsRow(label('latest'),save(latest)):'';
  const previous=safety?accountSettingsRow(label('beforeRestore'),save(safety)):'';
  const toggle=policy?`<button type="button" role="switch" ${aria('automatic')} aria-checked="${policy.enabled}" aria-busy="${busy&&busyKind==='policy'}" class="settings-switch" ${disabled?'disabled':''} onclick="RunTeamsBackups.savePolicy({enabled:${!policy.enabled}})"><span></span></button>`:`<span class="settings-footnote" role="status">${label(error?'unavailable':'loading')}</span>`;
  const retention=policy?accountSettingsRow(label('retention'),csel('localBackupRetention',[7,14,30].map(n=>({value:String(n),label:text('retentionCount',{count:n})})),String(policy.keep),next=>savePolicy({keep:Number(next)}),{disabled,menuVariant:'settingsSelect',menuAlign:'right'}).replace('aria-haspopup="menu"',aria('retention')+' aria-haspopup="menu"'),label('retentionHint')):'';
  const history=automatic.length?accountSettingsRow(label('history'),csel('localBackupHistory',automatic.map(v=>({value:v.backup_id,label:date(v.created_at,global.RunTeamsLocale.language)})),selectedBackup,next=>{selectedBackup=next;paint();},{disabled,menuVariant:'settingsSelect',menuAlign:'right'}).replace('aria-haspopup="menu"',aria('history')+' aria-haspopup="menu"')+`<button class="btn" onclick="RunTeamsBackups.downloadAutomatic()" ${disabled?'disabled':''}>${label('saveFile')}</button>`):'';
  return accountSettingsGroup(label('title'),accountSettingsRow(label('library'),backupAction,label('libraryHint'))+accountSettingsRow(label('automatic'),toggle,label('automaticHint'))+retention+history+accountSettingsRow(label('restoreRow'),restoreAction,label('restoreHint'))+saved+previous)+status+(automaticError?warning(automaticError):'')+(pending&&!busy&&!error?retry:'');
 }
 global.RunTeamsBackups=Object.freeze({markup,create:start,savePolicy,downloadAutomatic,choose:()=>document.getElementById('localBackupImport')?.click(),selected,check,download,get pending(){return busy||!!pending;}});
 global.setInterval?.(()=>{if(S.localLibrary&&S.settingsTab==='general'&&!document.hidden&&document.getElementById('settingsWorkspace')&&!busy&&!pending)void check();},30000);
})(window);
