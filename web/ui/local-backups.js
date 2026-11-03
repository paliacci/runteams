/* Backup controls in the existing settings rows; data stays in the host library. */
(function(global){
 'use strict';
 const key='runteams_pending_backup';let loaded=false,busy=false,busyKind='',pending=null,notice='',error='',latest=null,safety=null,policy=null,automatic=[],automaticError='',selectedBackup='',automaticWaiting=false;
 const valid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
 const paint=()=>{if(typeof accountSettingsPaint==='function')accountSettingsPaint();};
 function remember(value){const raw=JSON.stringify(value);sessionStorage.setItem(key,raw);if(sessionStorage.getItem(key)!==raw)throw Error('无法保存本次操作记录，请检查浏览器存储后重试。');pending=value;automaticWaiting=false;}
 function forget(){sessionStorage.removeItem(key);pending=null;}
 function download(id){if(!valid(id))return;const link=document.createElement('a');link.href='/api/backups/'+id+'/download';link.download='RunTeams-backup.zip';document.body.appendChild(link);link.click();link.remove();}
 function confirmed(value){
  automaticWaiting=false;
  if(value.state==='pending'){notice='操作结果正在确认，请稍后重新读取。';return false;}
  if(value.state==='failed'){error=value.error||'操作未完成，原资料已保留。';forget();return false;}
  if(value.state!=='completed')throw Error('备份结果暂时无法确认，请重新读取。');
  if(value.kind==='policy'){policy=value.policy;notice='自动备份设置已保存。';}
  else if(value.kind==='backup'){latest=value.backup_id;notice='备份已创建，可保存到你选择的位置。';}
  else{safety=value.safety_backup_id;notice='备份已恢复。恢复前的资料已另存备份。';}
  forget();return true;
 }
 async function check(){
  if(busy)return;busy=true;busyKind=pending?.kind||'';error='';paint();
  try{
   const policyCheck=pending?.kind==='policy';
   if(pending)confirmed(await api('/api/backups/'+(policyCheck?'policy/':'')+pending.operation_id+'/status'));
   if(!pending&&(!busyKind||policyCheck)){
    const value=await api('/api/backups');automaticWaiting=false;latest=value.last_backup?.backup_id||null;safety=value.last_restore?.safety_backup_id||null;
    policy=value.policy||null;automatic=value.automatic_backups||[];automaticError=value.automatic_error?(value.automatic_error.stage==='retention'?'自动备份清理未完成：':'自动备份未完成：')+value.automatic_error.error:'';
    if(!automatic.some(v=>v.backup_id===selectedBackup))selectedBackup=automatic[0]?.backup_id||'';
   }
  }catch(e){if(e.status===409&&!pending)automaticWaiting=true;else if(e.status===404&&pending){forget();error='原操作未开始，可以重新操作。';}else error=e.status===403?'资料库已恢复，请刷新窗口后继续。':e.message||'结果暂时无法确认，请重试。';}
  finally{busy=false;paint();}
 }
 async function savePolicy(patch){
  if(busy||pending||!policy)return;busy=true;busyKind='policy';error='';notice='';
  try{
   remember({operation_id:crypto.randomUUID(),kind:'policy',expected_revision:policy.revision,patch});paint();
   const {kind,...data}=pending;confirmed(await api('/api/backups/policy','POST',data));
  }catch(e){if([400,403,409].includes(e.status)){forget();policy=null;}error=e.message||'设置保存结果尚未确认，请读取原操作。';}
  finally{busy=false;paint();}
 }
 async function downloadAutomatic(){
  if(busy||pending||!valid(selectedBackup))return;const id=selectedBackup;
  await check();if(error)return;if(automatic.some(v=>v.backup_id===id))download(id);
  else{error='这份自动备份已按保留策略清理，请重新选择。';paint();}
 }
 async function start(){
  if(busy||pending)return;busy=true;busyKind='backup';error='';notice='';
  try{
   if(!await flushDocument()){error='文档更改尚未保存，请先处理保存结果。';return;}
   remember({operation_id:crypto.randomUUID(),kind:'backup'});paint();
   const value=await api('/api/backups','POST',{operation_id:pending.operation_id});
   if(confirmed(value))download(value.backup_id);
  }catch(e){error=e.message||'备份结果尚未确认，请读取原操作。';}
  finally{busy=false;paint();}
 }
 async function selected(input){
  const file=input.files?.[0];input.value='';if(!file||busy||pending)return;
  if(file.size>512*1024*1024){error='请选择不超过512MB的备份。';paint();return;}
  busy=true;busyKind='import';error='';notice='';paint();let preview;
  try{preview=await RunTeamsApplication.uploadBackup(file,crypto.randomUUID());}
  catch(e){error=e.message||'备份未能读取，请重新选择。';}
  finally{busy=false;paint();}
  if(!preview)return;
  confirmModal('从备份恢复？','备份创建于'+new Date(preview.created_at).toLocaleString()+'。将替换当前已保存资料，恢复前会保留一份备份；外部工作目录中的文件不会改动。',()=>restore(preview.import_id),true);
 }
 async function restore(importId){
  if(busy||pending||!valid(importId))return;busy=true;busyKind='restore';error='';notice='';
  try{
   if(!await flushDocument()){error='文档更改尚未保存，请先处理保存结果。';return;}
   remember({operation_id:crypto.randomUUID(),kind:'restore'});paint();
   await api('/api/backups/restore','POST',{operation_id:pending.operation_id,import_id:importId});
   // A full reload starts a new verified library generation. Other open
   // windows cannot write with the old generation, even for the same UUID.
   location.replace('/?settings=general');
  }catch(e){
   if(pending&&pending.kind==='restore'){location.replace('/?settings=general');return;}
   error=e.message||'恢复未开始，请重试。';
  }finally{busy=false;paint();}
 }
 function initialize(){
  if(loaded)return;loaded=true;
  try{const raw=sessionStorage.getItem(key);if(raw){const value=JSON.parse(raw);if(!valid(value.operation_id)||!['backup','restore','policy'].includes(value.kind))throw Error('原操作记录无效，请保留当前窗口。');pending=value;}}
  catch(e){error=e.message;return;}
  queueMicrotask(()=>void check());
 }
 function markup(){
  if(typeof S==='undefined'||!S.localLibrary)return '';
  initialize();const disabled=busy||!!pending,spin='<span class="env-spinner" aria-hidden="true"></span>';
  const backupAction=`<button class="btn" type="button" onclick="RunTeamsBackups.create()" ${disabled?'disabled':''}>${busy&&busyKind==='backup'?spin+'正在备份':'创建备份'}</button>`;
  const restoreAction=`<button class="btn" type="button" onclick="RunTeamsBackups.choose()" ${disabled?'disabled':''}>${busy&&['import','restore'].includes(busyKind)?spin+(busyKind==='import'?'正在读取':'正在恢复'):'选择备份'}</button><input id="localBackupImport" type="file" accept=".zip,application/zip" hidden onchange="RunTeamsBackups.selected(this)">`;
  const message=automaticWaiting?'资料正在备份或恢复，完成后会更新记录。':notice;
  const status=error?`<div class="settings-inline-error" role="alert"><span>${esc(error)}</span><button class="btn" onclick="RunTeamsBackups.check()">${pending?'读取原操作':'重新读取'}</button></div>`:message?`<p class="settings-footnote" role="status">${esc(message)}</p>`:'';
  const saved=latest?accountSettingsRow('最近备份',`<button class="btn" onclick="RunTeamsBackups.download('${latest}')">保存到文件</button>`):'';
  const previous=safety?accountSettingsRow('恢复前的备份',`<button class="btn" onclick="RunTeamsBackups.download('${safety}')">保存到文件</button>`):'';
  const toggle=policy?`<button type="button" role="switch" aria-label="自动备份" aria-checked="${policy.enabled}" aria-busy="${busy&&busyKind==='policy'}" class="settings-switch" ${disabled?'disabled':''} onclick="RunTeamsBackups.savePolicy({enabled:${!policy.enabled}})"><span></span></button>`:`<span class="settings-footnote">${error?'暂时无法读取':'正在读取…'}</span>`;
  const retention=policy?accountSettingsRow('保留自动备份',csel('localBackupRetention',[7,14,30].map(n=>({value:String(n),label:'最近 '+n+' 份'})),String(policy.keep),next=>savePolicy({keep:Number(next)}),{disabled,menuVariant:'settingsSelect',menuAlign:'right'}).replace('aria-haspopup="menu"','aria-label="保留自动备份" aria-haspopup="menu"'),'只清理已验证的自动备份，手动备份和恢复前备份保留。'):'';
  const history=automatic.length?accountSettingsRow('自动备份记录',csel('localBackupHistory',automatic.map(v=>({value:v.backup_id,label:new Date(v.created_at).toLocaleString()})),selectedBackup,next=>{selectedBackup=next;paint();},{disabled,menuVariant:'settingsSelect',menuAlign:'right'}).replace('aria-haspopup="menu"','aria-label="自动备份记录" aria-haspopup="menu"')+`<button class="btn" onclick="RunTeamsBackups.downloadAutomatic()" ${disabled?'disabled':''}>保存到文件</button>`):'';
  const warning=automaticError?`<div class="settings-inline-error" role="alert">${esc(automaticError)}<button class="btn" onclick="RunTeamsBackups.check()">重新读取</button></div>`:'';
  return accountSettingsGroup('备份与恢复',accountSettingsRow('本机资料备份',backupAction,'包含已保存的对话、附件、文档、本机资产、托管工作文件与交互设置。')+accountSettingsRow('自动备份',toggle,'应用运行且空闲时每天备份已保存资料；运行中的对话或文件选择结束后再备份。')+retention+history+accountSettingsRow('从备份恢复',restoreAction,'外部项目文件和模型厂商凭据需单独保管。')+saved+previous)+status+warning+(pending&&!busy&&!error?'<button class="btn" onclick="RunTeamsBackups.check()">读取原操作</button>':'');
 }
 global.RunTeamsBackups=Object.freeze({markup,create:start,savePolicy,downloadAutomatic,choose:()=>document.getElementById('localBackupImport')?.click(),selected,check,download,get pending(){return busy||!!pending;}});
 global.setInterval?.(()=>{if(S.localLibrary&&S.settingsTab==='general'&&!document.hidden&&document.getElementById('settingsWorkspace')&&!busy&&!pending)void check();},30000);
})(window);
