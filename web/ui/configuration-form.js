/* Shared configuration composition and edit lifecycle. Scope, storage and API stay in adapters. */
(()=>{
'use strict';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const message=(key,fallback)=>({key,fallback});
const label=(key,fallback)=>'<span data-app-i18n="employeeSettings.'+key+'">'+esc(window.RunTeamsLocale?.t('employeeSettings.'+key,{},fallback)??fallback)+'</span>';
const canonical=value=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
function draft(fields,values,base,bindings={},baseBindings={}){
 const next=structuredClone(values);
 for(const field of fields){
  if(!field.required&&next[field.key]===''&&['number','select','date'].includes(field.type))next[field.key]=null;
  if(!Object.hasOwn(base,field.key)&&(next[field.key]===''||next[field.key]===null))delete next[field.key];
 }
 return canonical(next)!==canonical(base)||canonical(bindings)!==canonical(baseBindings)?next:null;
}
function groups({groups,idFor,renderField,collapsedSections,action,heading='h3'}){
 return groups.filter(group=>group.fields.length).map(group=>RunTeamsEmployeeDrawerHeader.section({
  id:idFor(group),title:esc(group.label),body:group.fields.map(renderField).join(''),
  collapsedSections,action,heading,className:'group'
 })).join('');
}
function markup({id,body,attrs=''}){
 return '<form id="'+esc(id)+'" class="configuration-surface settings-section-stack" novalidate '+attrs+'>'+body+'</form>';
}
function footer({state,receiptAttrs='',inline=false}){
 if(!state.pending||state.saving)return '';
 const action=state.retry?['retrySave','重试保存']:['checkSave','核对保存结果'];
 return '<footer class="configuration-save'+(inline?' configuration-save-inline':'')+'">'+
  '<span role="status" aria-live="polite">'+label('saveUnconfirmed','尚未确认是否保存')+'</span>'+
  '<button type="button" class="btn" '+receiptAttrs+'>'+label(...action)+'</button></footer>';
}
const scheduledSaves=new WeakMap();
function cancelSave(state){
 const scheduled=scheduledSaves.get(state);
 if(!scheduled)return;
 clearTimeout(scheduled.timer);
 scheduledSaves.delete(state);
}
function scheduleSave(state,save){
 cancelSave(state);
 const scheduled={};
 const current=()=>scheduledSaves.get(state)===scheduled;
 scheduledSaves.set(state,scheduled);
 // A native change can precede a button click. Let that interaction finish
 // before the transaction replaces the form.
 scheduled.timer=setTimeout(async()=>{
  try{await save(current);}
  finally{if(current())scheduledSaves.delete(state);}
 },250);
}
const heldInputs=new WeakSet();
function holdInput(input,owned,paint){
 if(!input?.matches?.('input,textarea')||input.selectionStart===null||input.disabled)return false;
 if(!heldInputs.has(input)){
  heldInputs.add(input);
  input.addEventListener('blur',event=>{
   heldInputs.delete(input);
   // A blur happens between pointerdown and click. Replacing the drawer here
   // can remove the action before its click arrives.
   const drawer=input.closest('.right-detail-drawer');
   if(drawer&&event.relatedTarget&&drawer.contains(event.relatedTarget))return;
   requestAnimationFrame(()=>{if(owned())paint();});
  },{once:true});
 }
 return true;
}
function revealErrors(groups,idFor,collapsedSections,errors){
 for(const group of groups)if(group.fields.some(field=>errors?.[field.key]))collapsedSections.delete(idFor(group));
}
// Persist the immutable operation before sending. An uncertain response can only
// be queried or retried with the same operation, values and expected revision.
async function transact(state,adapter,{receipt=false}={}){
 if(state.saving)return;
 const active=document.activeElement;
 const focusedId=active?.id&&adapter.form?.()?.contains(active)?active.id:'';
 let sent=false;
 state.saving=true;state.error='';state.errors={};state.notice='';
 try{
  if(!state.pending)state.pending={...adapter.prepare(),operation_id:crypto.randomUUID()};
  await adapter.persist();
  if(!adapter.owned())return;
  adapter.paint();sent=true;
  const result=await adapter.send(state.pending,receipt);
  if(!adapter.owned())return;
  if(result.status==='committed'){
   adapter.accept(result.value);
   state.pending=null;state.retry=false;state.unknown=false;state.draft=null;state.conflict=null;
   await adapter.accepted?.(receipt);
  }else{
   state.unknown=true;state.retry=result.status==='not_found';
   state.error=state.retry?message('receiptMissing','找不到保存结果。你可以重试保存。'):message('receiptUnavailable','无法核对保存结果。请重试。');
  }
 }catch(error){
  if(adapter.owned()){
   state.error=error.uiMessage||error.message;state.errors=error.fields||{};
   if(sent&&!receipt&&adapter.confirmedError(error)){state.pending=null;state.retry=false;state.unknown=false;}
   else if(state.pending){state.unknown=sent;state.retry=!sent;}
   await adapter.rejected?.(error);
  }
 }finally{
  state.saving=false;
  if(!adapter.owned()){if(state.pending)state.unknown=true;}
  else{
   try{await adapter.persist();}catch(error){state.error=error.uiMessage||error.message;}
   adapter.paint();
   if(adapter.form&&(focusedId||Object.keys(state.errors||{}).length))requestAnimationFrame(()=>{
    if(!adapter.owned())return;
    const form=adapter.form();
    const invalid=form?.querySelector('[aria-invalid="true"]');
    if(invalid)invalid.focus();
    else if(focusedId&&document.activeElement===document.body){
     const field=document.getElementById(focusedId);
     if(field&&form?.contains(field))field.focus({preventScroll:true});
    }
   });
  }
 }
}
document.addEventListener('keydown',event=>{
 const field=event.target;
 if(event.defaultPrevented||event.isComposing||event.key!=='Enter'||
  !field.matches?.('input[data-key]:is([type="text"],[type="number"],[type="date"],[type="url"],[type="email"])')||
  !field.closest('.configuration-surface')||field.closest('.credential-field'))return;
 event.preventDefault();
 field.blur();
});
window.RunTeamsConfigurationForm={draft,groups,markup,footer,scheduleSave,cancelSave,revealErrors,transact,holdInput};
})();
