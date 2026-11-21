/* Public field renderer. Host supplies icons and select menus; no product state or API. */
(function(){
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const message=(key,fallback)=>({key,fallback});
 const labelError=value=>'<span data-app-i18n="employeeSettings.'+esc(value.key)+'">'+esc(window.RunTeamsLocale?.t('employeeSettings.'+value.key,{},value.fallback)??value.fallback)+'</span>';
const fieldErrors=new Map([
 ["请填写此项。",message("fieldError.required","此项为必填项。")],
 ["此项还需配置。",message("fieldError.needsConfiguration","请完成此项配置。")],
 ["本机凭据已不可用，请重新核对。",message("fieldError.credentialLost","本机凭据已不可用。请重新选择。")],
 ["资料内容已变化，请重新核对这次工作。",message("fieldError.resourceChanged","资料已变更。请重新核对这次工作。")],
 ["资料在准备过程中发生变化。",message("fieldError.resourceChangedDuringSetup","资料在准备期间已变更。")],
 ["此项还需核对。",message("fieldError.checkSetting","请核对此项。")],
 ["运行环境暂不可用，请重新核对。",message("fieldError.runtimeUnavailable","运行环境暂不可用。请重新检查。")],
 ["配置格式无效。",message("fieldError.invalidForm","无法读取这些配置。")],
 ["包含当前员工没有声明的配置。",message("fieldError.unknownSettings","部分配置项已不可用。请重新读取配置。")],
 ["资料配置格式无效。",message("fieldError.invalidResourceForm","无法读取资料配置。")],
 ["资料项已变化，请重新选择。",message("fieldError.resourceSelectionChanged","资料选项已变更。请重新选择。")],
 ["请填写凭据。",message("fieldError.credentialRequired","请输入凭据。")],
 ["此项必须通过平台的资料选择、连接或凭据入口配置。",message("fieldError.privateSetting","请使用此项的资料、连接或凭据选项。")],
 ["请填写文本。",message("fieldError.textRequired","请输入文字。")],
 ["文本长度不符合要求。",message("fieldError.textLength","请检查文字长度。")],
 ["请选择有效的本机位置。",message("fieldError.invalidLocation","请选择有效的本机位置。")],
 ["请选择有效日期。",message("fieldError.invalidDate","请选择有效日期。")],
 ["选项已变化，请重新选择。",message("fieldError.optionsChanged","可用选项已变更。请重新选择。")],
 ["请填写有效数字。",message("fieldError.invalidNumber","请输入有效数字。")],
 ["数字超出允许范围。",message("fieldError.numberRange","请输入范围内的数字。")],
 ["数字精度不符合要求。",message("fieldError.numberStep","请输入符合步长要求的数字。")],
 ["请选择是或否。",message("fieldError.booleanRequired","请选择「是」或「否」。")],
 ["请选择有效且不重复的选项。",message("fieldError.invalidSelections","请从可用选项中选择，每项只选一次。")],
 ["请至少选择一项。",message("fieldError.selectionRequired","请至少选择一项。")],
]);
const fieldErrorMarkup=value=>{const translated=fieldErrors.get(value)||value;return typeof translated==='string'?esc(translated):labelError(translated);};

window.RunTeamsConfigurationFields = {errorMarkup:fieldErrorMarkup,create({icon: ICON, singleSelect: csel, idPrefix="employee_config_",errorMarkup}) {
 const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const renderError=errorMarkup||fieldErrorMarkup;
 const text=(key,fallback)=>window.RunTeamsLocale?.t("configurationField."+key,{},fallback)??fallback;
 const localized=(key,fallback,vars={})=>'<span data-app-i18n="'+key+'"'+(Object.keys(vars).length?' data-app-i18n-vars="'+esc(JSON.stringify(vars))+'"':'')+'>'+esc(window.RunTeamsLocale?.t(key,vars,fallback)??fallback)+'</span>';
 const label=(key,fallback)=>localized("configurationField."+key,fallback);
 const displayValue=(f,v)=>{
  if(Array.isArray(v))return esc(v.map(x=>(f.options||[]).find(o=>o[0]===x)?.[1]||x).join("、"));
  if(f.type==="checkbox")return v?label("yes","是"):label("no","否");
  if(f.type==="secret")return label("secretHidden","已保存的密钥不会显示。");
  return esc((f.options||[]).find(o=>o[0]===v)?.[1]||v);
 };
 const valueLabel=(f,v)=>(f.options||[]).find(x=>x[0]===v)?.[1]||"";
 const statuses={selected:label("serviceSelected","已选择服务"),connected:label("connected","已连接"),expired:label("expired","连接已失效"),missing:label("notConnected","尚未连接"),ready:label("ready","可用"),checking:label("checking","正在核对…"),unknown:label("unknown","尚未确认"),unavailable:label("unavailable","暂时不可用")};
 function information(help,content,name,labelKey=""){
  return '<span class="credential-info"><button type="button" class="credential-info-trigger" aria-label="'+esc(name)+'"'+(labelKey?' data-app-i18n-aria-label="'+esc(labelKey)+'"':'')+' aria-describedby="'+help+'">'+ICON("info-compact")+'</button><span class="credential-tooltip" role="tooltip" id="'+help+'">'+content+'</span></span>';
 }
 function field(field,v,error=""){
  const f={helpTooltip:true,...field,...field.constraints,options:(field.options||[]).map(o=>Array.isArray(o)?o:[o.value,o.label])};
  const id=idPrefix+f.key,help=id+"-help",err=id+"-error",disabled=f.disabled?"disabled":"";
  const credential=f.localCredential;
  const helpCopy=f.localService?label("localService","保存服务选择后，在下方授权连接。"):
   f.type==="secret"&&!f.note?label("secretHidden","已保存的密钥不会显示。"):"";
  const requiredHint=f.required_when?esc(f.required_when):f.required&&f.showRequiredHint!==false?label("required","必填"):"";
  const limitHints=[f.min_length!=null?text("minLength","最少 {count} 个字符").replace('{count}',f.min_length):'',f.max_length!=null?text("maxLength","最多 {count} 个字符").replace('{count}',f.max_length):'',f.min!=null?text("minimum","最小值 {count}").replace('{count}',f.min):'',f.max!=null?text("maximum","最大值 {count}").replace('{count}',f.max):'',f.step!=null?text("step","步长 {count}").replace('{count}',f.step):''].filter(Boolean).map(esc).join('；');
  const hint=[requiredHint,esc(f.note),limitHints,helpCopy].filter(Boolean).join(" ");
  const requiredMark=f.required||f.required_when?'<span class="required-mark" aria-hidden="true">*</span><span class="sr-only">'+(f.required?label("required","必填"):label("conditionalRequired","按使用场景必填"))+'</span>':'';
  const descriptions=[f.type==="resource"||hint||credential?help:"",error?err:""].filter(Boolean).join(" ");
  const descriptionAttr=descriptions?' aria-describedby="'+descriptions+'"':"";
  const attrs='id="'+id+'" data-key="'+esc(f.key)+'" '+disabled+descriptionAttr+' '+(f.required?'aria-required="true"':'')+' '+(error?'aria-invalid="true"':"")+' '+(f.min_length!=null?'minlength="'+f.min_length+'"':'')+' '+(f.max_length!=null?'maxlength="'+f.max_length+'"':'')+' '+(f.pattern?'pattern="'+esc(f.pattern)+'"':'');
  const fieldAction=(attribute,key,fallback,content=label(key,fallback))=>{
   const accessible=esc(text(key,fallback)),translation='configurationField.'+key;
   return '<button type="button" '+attribute+' '+disabled+' aria-label="'+accessible+'" title="'+accessible+'" data-app-i18n-aria-label="'+translation+'" data-app-i18n-title="'+translation+'">'+content+'</button>';
  };
  const fileInput=()=>'<input '+attrs+' hidden tabindex="-1" type="file" accept="'+esc(f.file_input.accept)+'" aria-label="'+esc(f.label)+'">';
  const fileFrame=content=>'<div class="inp credential-control credential-file-control"'+(error?' aria-invalid="true"':'')+'>'+content+'</div>';
  const secretInput=(ready=false)=>{
   const length=credential?.mask_length;
   const mask=Number.isSafeInteger(length)&&length>0&&length<=8192?'•'.repeat(length):'…';
   const placeholder=ready?'placeholder="'+mask+'"':'placeholder="'+esc(text('credentialInput','输入凭据'))+'" data-app-i18n-placeholder="configurationField.credentialInput"';
   return '<input class="inp" '+attrs+' '+(ready?'data-configured-secret ':'')+'type="password" autocomplete="new-password" spellcheck="false" '+placeholder+'>';
  };
  const reveal=()=>fieldAction('class="secret-toggle" data-secret="'+id+'" aria-pressed="false"','showSecret','显示明文',ICON('eye'));
  if(credential&&!f.readonly){
   const file=!!f.file_input,ready=!!credential.selected&&credential.state==='configured';
   let control;
   if(file){
    const filename=ready&&credential.filename;
    const name=filename?'<span class="credential-file-name" title="'+esc(filename)+'">'+esc(filename)+'</span>':'';
    const status=ready?'<span class="credential-file-status"><span aria-hidden="true">'+ICON('check')+'</span>'+
     (filename?label('credentialFileSelected','已选择'):label('credentialFileActive','已选择私钥'))+'</span>':
     '<span class="credential-file-name">'+label('credentialEmpty','尚未配置')+'</span>';
    const choose=fieldAction('data-credential-file="'+esc(f.key)+'"',ready?'change':'chooseFile',ready?'更换':'选择文件');
    const clear=ready?fieldAction('class="credential-action credential-clear" data-credential-clear="'+esc(f.key)+'"','credentialClear','取消使用凭据',ICON('x')):'';
    control=fileFrame('<div class="credential-file-value">'+name+status+'</div>'+fileInput()+choose+clear);
   }else control='<div class="input-unit">'+secretInput(ready)+reveal()+'</div>';
   const pipelineName=credential.pipelineName;
   const scope=pipelineName?localized('employeeSettings.pipelineScope','仅用于「'+pipelineName+'」。',{name:pipelineName}):'';
   const info=information(help,[requiredHint,esc(f.note),label('localCredential','凭据仅保存在这台电脑上，不会加入对话、作品或便携备份。'),(file?label('credentialFileAutosave','选择文件后自动保存。'):label('credentialAutosave','离开输入框或按回车后自动保存。')),scope].filter(Boolean).join(' '),text('credentialInfo','凭据说明'),'configurationField.credentialInfo');
   return '<div class="field credential-field'+(file?' credential-file-field':'')+'" data-field="'+esc(f.key)+'"><div class="credential-heading"><label for="'+id+'">'+esc(f.label)+requiredMark+'</label>'+info+'</div>'+control+
    (error?'<p class="error" role="alert" id="'+err+'">'+renderError(error)+'</p>':'')+'</div>';
  }
  const placeholder=f.placeholder?' placeholder="'+esc(f.placeholder)+'"':'';
  let control="";
  if(f.readonly) control='<div class="readonly">'+displayValue(f,v)+'<small>'+label("readOnly","只读")+'</small></div>';
  else if(f.type==='secret'&&f.file_input)control=fileFrame(fileInput()+fieldAction('data-credential-file="'+esc(f.key)+'"','chooseFile','选择文件'));
  else if(f.type==='secret')control='<div class="input-unit">'+secretInput()+reveal()+'</div>';
  else if(f.type==='file_path'||f.type==='directory_path'){
   const folder=f.type==='directory_path';
   const choose=fieldAction('class="btn sm" data-location-pick="'+(folder?'folder':'file')+'"',folder?'chooseFolder':'chooseFile',folder?'选择文件夹':'选择文件',folder?label('choose','选择'):undefined);
   control='<div class="inp configuration-location"'+(error?' aria-invalid="true"':'')+'><input '+attrs+' readonly value="'+esc(v)+'" title="'+esc(v)+'" placeholder="'+esc(text('noSelection','尚未选择'))+'" data-app-i18n-placeholder="configurationField.noSelection">'+choose+'</div>';
  }
  else if(["text","number","date"].includes(f.type)) control='<div class="input-unit"><input class="inp" '+attrs+' type="'+f.type+'" value="'+esc(v)+'"'+(f.type==="text"?placeholder:'')+' '+(f.min!=null?'min="'+f.min+'"':'')+' '+(f.max!=null?'max="'+f.max+'"':'')+' '+(f.step!=null?'step="'+f.step+'"':'')+'>'+(f.unit?'<span>'+esc(f.unit)+'</span>':'')+'</div>';
  else if(f.type==="textarea")control='<textarea class="ta" '+attrs+placeholder+' rows="3">'+esc(v)+'</textarea>';
  else if(f.type==="select"){
   control=csel(id,(f.options||[]).map(o=>({value:o[0],label:o[1]})),v,()=>document.getElementById(id)?.dispatchEvent(new Event("change",{bubbles:true})),{disabled:!!f.disabled,menuVariant:"compactSelect",required:!!f.required,accessibleAttrs:'aria-labelledby="'+id+'-label"'+descriptionAttr+(error?' aria-invalid="true"':'')});
   control=control.replace('data-menu-trigger="field"','data-menu-trigger="field" data-key="'+esc(f.key)+'" aria-labelledby="'+id+'-label"'+descriptionAttr+' '+(error?'aria-invalid="true"':""));
  }
  else if(["multiselect","checklist"].includes(f.type))control='<div class="choices '+(f.type==="checklist"?"vertical":"")+'" role="group" aria-labelledby="'+id+'-label">'+(f.options||[]).map(o=>'<label><input type="checkbox" data-key="'+esc(f.key)+'" value="'+esc(o[0])+'" '+((v||[]).includes(o[0])?"checked":"")+' '+disabled+descriptionAttr+' '+(error?'aria-invalid="true"':"")+'>'+esc(o[1])+'</label>').join("")+'</div>';
  else if(f.type==="checkbox")control='<label class="check"><input '+attrs+' type="checkbox" '+(v?"checked":"")+'><span>'+esc(f.label)+requiredMark+'</span></label>';
  else if(f.type==="resource"){
   const expired=f.state==="expired";
   const access=f.resourceAccess==="view"?label("viewAccess","仅查看"):f.resourceAccess==="edit"?label("editAccess","查看、添加和更新"):f.resourceAccess==="copy"?label("copyAccess","仅查看副本"):esc(f.access);
   const summary=(valueLabel(f,v)?esc(valueLabel(f,v)):label("noSelection","尚未选择"))+(f.note?' · '+esc(f.note):access?' · '+access:'');
   const title='<label id="'+id+'-label">'+esc(f.label)+(f.required?'<span class="required-mark" aria-hidden="true">*</span><span class="sr-only">'+label("required","必填")+'</span>':'')+'</label>';
   const action='<button type="button" '+(expired?'data-reconnect="'+esc(f.key)+'"':'data-expand="'+esc(f.key)+'"')+' '+disabled+' aria-describedby="'+help+(error?' '+err:'')+'" '+(error?'aria-invalid="true"':'')+' aria-expanded="'+Boolean(f.pickerOpen)+'">'+(expired?label("reconnect","重新连接"):v?label("change","更换"):label("choose","选择"))+'</button>';
   const picker='<div class="picker" data-picker="'+esc(f.key)+'" '+(f.pickerOpen?'':'hidden')+'><p>'+(f.pipelinePicker?label("pipelinePicker","选择智能体团队可使用的资料"):f.pickerTitle?esc(f.pickerTitle):label("employeePicker","选择员工可使用的资料"))+'</p><p>'+label("access","使用权限：")+access+'</p>'+(f.options||[]).map(o=>'<label><input type="radio" name="'+id+'" data-key="'+esc(f.key)+'" value="'+esc(o[0])+'" '+(o[0]===v?'checked':'')+' '+disabled+'>'+esc(o[1])+'</label>').join('')+(f.pickerActions||'')+'</div>';
   return '<div class="field resource-field" data-field="'+esc(f.key)+'"><div class="resource-heading">'+title+action+'</div><p class="resource-summary '+(!v?'warning':'')+'" id="'+help+'" title="'+esc(valueLabel(f,v)+(f.note?' · '+f.note:f.access?' · '+f.access:''))+'">'+summary+'</p>'+(expired?'<p class="error">'+label("expiredResource","连接已失效。已有成果仍保留。")+'</p>':'')+picker+(error?'<p class="error" id="'+err+'">'+renderError(error)+'</p>':'')+'</div>';
  }
  else if(f.type==="connection")control='<div class="binding"><div><strong class="'+(v==="expired"?"warning":"")+'">'+(f.localService&&v==="missing"?label("noServiceSelected","尚未选择服务"):f.connectionStatus?esc(f.connectionStatus):statuses[v])+'</strong><small>'+(f.localService?esc(f.account)+' · '+label("access","使用权限：")+(f.serviceScopes.length?esc(f.serviceScopes.join(', ')):label("noExtraAccess","无额外权限")):esc(v==='connected'||v==='expired'?f.account+' · '+f.access:f.access))+'</small></div><button type="button" data-connect="'+esc(f.key)+'" '+disabled+'>'+(f.localService?(v==="selected"?label("deselectService","取消选择"):label("selectService","选择服务")):f.connectionAction||(v==="connected"?label("manage","管理"):v==="expired"?label("reconnect","重新连接"):label("connect","连接")))+'</button></div>';
  else if(f.type==="runtime")control='<div class="binding"><div><strong>'+statuses[v]+'</strong><small>'+(v==="unknown"?label("unknownRuntime","无法读取运行状态。"):v==="ready"?label("readyRuntime","运行条件已满足。"):v==="unavailable"?label("unavailableRuntime","请检查运行条件。"):label("pendingRuntime","正在核对运行条件…"))+'</small></div><button type="button" data-check="'+esc(f.key)+'" '+(v==="checking"||f.disabled?"disabled":"")+'>'+label("checkAgain","重新检查")+'</button></div>';
  const title=f.type==="checkbox"?"":'<label id="'+id+'-label" '+(["multiselect","checklist","resource","connection","runtime"].includes(f.type)?"":'for="'+id+'"')+'>'+esc(f.label)+requiredMark+'</label>';
  const info=f.helpTooltip&&hint?information(help,hint,f.label+' '+text("fieldInfo","填写说明")):'';
  return '<div class="field'+(info?' configuration-help-field':'')+'" data-field="'+esc(f.key)+'">'+(info?'<div class="credential-heading">'+(f.type==='checkbox'?control:title)+info+'</div>':title)+(info&&f.type==='checkbox'?'':control)+(!info&&hint?'<p class="help" id="'+help+'">'+hint+'</p>':'')+(error?'<p class="error" role="alert" id="'+err+'">'+renderError(error)+'</p>':"")+'</div>';

 }
 function collect(fields,root,base){
  const values=structuredClone(base);
  for(const f of fields){
   if(f.readonly||f.disabled||["connection","runtime","secret"].includes(f.type))continue;
   const nodes=[...root.querySelectorAll("[data-key]")].filter(n=>n.dataset.key===f.key);
   if(!nodes.length)continue;
   values[f.key]=["multiselect","checklist"].includes(f.type)?nodes.filter(n=>n.checked).map(n=>n.value):f.type==="checkbox"?nodes[0].checked:f.type==="resource"?(nodes.find(n=>n.checked)?.value||""):nodes[0].value;
   if(f.type==="select")values[f.key]=nodes[0].dataset.value;
   if(f.type==="number"&&values[f.key]!==""&&Number.isFinite(Number(values[f.key])))values[f.key]=Number(values[f.key]);
  }
  return values;
 }
 return {field,collect};
}};
const credentialReaders=[];
const pendingCredentials=new WeakMap(),originalCredentials=new WeakMap();
const isUnchangedCredential=input=>originalCredentials.get(input)===input.value;
function setSecretVisibility(input,button,show){
 input.type=show?'text':'password';button.setAttribute('aria-pressed',String(show));
 const key=show?'configurationField.hideSecret':'configurationField.showSecret';
 const fallback=show?'隐藏明文':'显示明文',label=window.RunTeamsLocale?.t(key,{},fallback)??fallback;
 button.setAttribute('data-app-i18n-aria-label',key);button.setAttribute('aria-label',label);
 button.setAttribute('data-app-i18n-title',key);button.title=label;
 button.innerHTML=ICON(show?'eye-off':'eye');
}
function releaseSavedCredential(input){
 if(pendingCredentials.delete(input))input.readOnly=false;
 if(!originalCredentials.has(input))return;
 if(isUnchangedCredential(input))input.value='';
 originalCredentials.delete(input);
 const button=input.parentElement?.querySelector('[data-secret]');
 if(button&&input.type==='text')setSecretVisibility(input,button,false);
}
async function readSavedCredential(input,button,owner,read,show){
 const ticket={show};pendingCredentials.set(input,ticket);
 input.readOnly=true;
 try{
  const value=await read(owner,input.dataset.key);
  if(value===null||pendingCredentials.get(input)!==ticket||!input.isConnected||input.disabled||input.value||
     !input.parentElement.contains(document.activeElement)||document.hidden)return;
  if(typeof value!=='string'||!value)throw Error('Missing credential');
  originalCredentials.set(input,value);input.value=value;
  input.placeholder='•'.repeat([...value].length);
  if(ticket.show)setSecretVisibility(input,button,true);
 }catch{
  if(pendingCredentials.get(input)===ticket&&input.isConnected)toast('无法显示凭据，请重试。','err','configurationField.credentialRevealFailed');
 }finally{if(pendingCredentials.get(input)===ticket){pendingCredentials.delete(input);input.readOnly=false;}}
}
function loadSavedCredential(input,show=false){
 if(!input?.matches('input[data-configured-secret]')||input.disabled||input.readOnly||input.value)return;
 const button=input.parentElement.querySelector('[data-secret]');
 if(!button)return;
 for(const {resolve,read} of credentialReaders){
  const owner=resolve(input);
  if(owner){void readSavedCredential(input,button,owner,read,show);return;}
 }
}
document.addEventListener('click',event=>{
 const button=event.target.closest?.('button[data-secret]');if(!button?.closest('.configuration-surface'))return;
 const input=document.getElementById(button.dataset.secret);if(!input||!button.closest('.field')?.contains(input))return;
 const show=input.type==='password';
 if(!input.value&&input.hasAttribute('data-configured-secret')){
  const pending=pendingCredentials.get(input);
  if(pending)pending.show=!pending.show;
  else{button.focus({preventScroll:true});loadSavedCredential(input,show);}
  return;
 }
 setSecretVisibility(input,button,show);
});
document.addEventListener('focusin',event=>loadSavedCredential(event.target));
document.addEventListener('focusout',event=>{
 const editor=event.target.closest?.('.input-unit');
 if(editor&&!editor.contains(event.relatedTarget)){
  const input=editor.querySelector('input[data-configured-secret]');
  if(input)releaseSavedCredential(input);
 }
});
const hideSavedCredentials=()=>document.querySelectorAll('input[data-configured-secret]').forEach(releaseSavedCredential);
window.addEventListener('blur',hideSavedCredentials);
window.addEventListener('focus',()=>loadSavedCredential(document.activeElement));
window.addEventListener('runteams:business-scope-will-change',hideSavedCredentials);
document.addEventListener('visibilitychange',()=>{if(document.hidden)hideSavedCredentials();});
document.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&event.target.matches('.configuration-surface .credential-info-trigger')){event.stopPropagation();event.target.blur();}
});
// One credential interaction contract for employee, position, pipeline and task forms.
window.RunTeamsConfigurationFields.isUnchangedCredential=isUnchangedCredential;
window.RunTeamsConfigurationFields.restoreCredentialInput=function(input,value,focus=false){
 if(!input||input.disabled||input.type==='file'||!value)return;
 input.value=value;
 if(focus)input.focus({preventScroll:true});
};
window.RunTeamsConfigurationFields.focusCredentialAction=function(input){
 const target=input?.type==='file'?input.closest('.credential-field')?.querySelector('[data-credential-file]'):input;
 target?.focus({preventScroll:true});
};
window.RunTeamsConfigurationFields.bindCredentialEditor=function(resolve,commit,read){
 if(read)credentialReaders.push({resolve,read});
 const handle=(event,kind)=>{
  const row=event.target.closest?.('.credential-field');if(!row)return;
  const owner=resolve(event.target);if(!owner)return;
  const input=row.querySelector('input');if(!input||input.disabled||input.readOnly||input.type==='file'&&kind!=='click')return;
  const editor=input.closest('.input-unit');
  const submit=()=>{if(!isUnchangedCredential(input)&&input.value.trim())commit(owner,row.dataset.field,input.value,input);};
  if(kind==='blur'&&editor?.contains(event.target)&&!editor.contains(event.relatedTarget))submit();
  if(kind==='key'&&!event.isComposing){
   if(event.key==='Enter'&&event.target===input){event.preventDefault();submit();}
   if(event.key==='Escape'&&editor?.contains(event.target)){
    event.preventDefault();event.stopPropagation();releaseSavedCredential(input);
    if(input.type==='text')setSecretVisibility(input,editor.querySelector('[data-secret]'),false);
    input.value='';
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.focus({preventScroll:true});
    loadSavedCredential(input);
   }
  }
  if(kind==='click'){
   const button=event.target.closest('button');
   if(button?.dataset.credentialClear)commit(owner,row.dataset.field,'',input);
  }
 };
 document.addEventListener('focusout',event=>handle(event,'blur'));
 document.addEventListener('keydown',event=>handle(event,'key'));
 document.addEventListener('click',event=>handle(event,'click'));
};
})();
