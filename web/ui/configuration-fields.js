/* Public field renderer. Host supplies icons and select menus; no product state or API. */
(function(){
window.RunTeamsConfigurationFields = {create({icon: ICON, singleSelect: csel, idPrefix="employee_config_"}) {
 const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const displayValue=(f,v)=>Array.isArray(v)?v.map(x=>(f.options||[]).find(o=>o[0]===x)?.[1]||x).join("、"):f.type==="checkbox"?(v?"是":"否"):f.type==="secret"?"密钥原文不显示":(f.options||[]).find(o=>o[0]===v)?.[1]||({unknown:"未能确认",ready:"可用",connected:"已连接",expired:"连接已失效"}[v])||v;
 const valueLabel=(f,v)=>(f.options||[]).find(x=>x[0]===v)?.[1]||"尚未选择";
 const statuses={selected:"已选择服务",connected:"已连接",expired:"连接已失效",missing:"尚未连接",ready:"可用",checking:"正在核对…",unknown:"未能确认",unavailable:"当前不可用"};
 function field(field,v,error=""){
  const f={...field,...field.constraints,options:(field.options||[]).map(o=>Array.isArray(o)?o:[o.value,o.label])};
  const id=idPrefix+f.key,help=id+"-help",err=id+"-error",disabled=f.disabled?"disabled":"";
  const hint=f.note||(f.type==="secret"?"已保存的密钥原文不显示。":"");
  const descriptions=[f.type==="resource"||hint?help:"",error?err:""].filter(Boolean).join(" ");
  const descriptionAttr=descriptions?' aria-describedby="'+descriptions+'"':"";
  const attrs='id="'+id+'" data-key="'+esc(f.key)+'" '+disabled+descriptionAttr+' '+(error?'aria-invalid="true"':"");
  let control="";
  if(f.readonly) control='<div class="readonly">'+esc(displayValue(f,v))+'<small>此项为只读</small></div>';
  else if(["text","number","date","secret"].includes(f.type)) control='<div class="input-unit"><input '+attrs+' type="'+({secret:"password"}[f.type]||f.type)+'" value="'+(f.type==="secret"?"":esc(v))+'" '+(f.type==="secret"?'autocomplete="new-password" placeholder="输入后由平台安全保管"':"")+' '+(f.min!=null?'min="'+f.min+'"':"")+' '+(f.max!=null?'max="'+f.max+'"':"")+' '+(f.step!=null?'step="'+f.step+'"':"")+'>'+(f.type==="secret"?'<button type="button" class="secret-toggle" data-secret="'+id+'" aria-label="显示明文" aria-pressed="false" '+disabled+'>'+ICON("eye")+'</button>':"")+(f.unit?'<span>'+esc(f.unit)+'</span>':"")+'</div>';
  else if(f.type==="textarea")control='<textarea '+attrs+' rows="3">'+esc(v)+'</textarea>';
  else if(f.type==="select"){
   control=csel(id,(f.options||[]).map(o=>({value:o[0],label:o[1]})),v,()=>document.getElementById(id)?.dispatchEvent(new Event("change",{bubbles:true})),{disabled:!!f.disabled,menuVariant:"compactSelect"});
   control=control.replace('data-menu-trigger="field"','data-menu-trigger="field" data-key="'+esc(f.key)+'" aria-labelledby="'+id+'-label"'+descriptionAttr+' '+(error?'aria-invalid="true"':""));
  }
  else if(["multiselect","checklist"].includes(f.type))control='<div class="choices '+(f.type==="checklist"?"vertical":"")+'" role="group" aria-labelledby="'+id+'-label">'+(f.options||[]).map(o=>'<label><input type="checkbox" data-key="'+esc(f.key)+'" value="'+esc(o[0])+'" '+((v||[]).includes(o[0])?"checked":"")+' '+disabled+descriptionAttr+' '+(error?'aria-invalid="true"':"")+'>'+esc(o[1])+'</label>').join("")+'</div>';
  else if(f.type==="checkbox")control='<label class="check"><input '+attrs+' type="checkbox" '+(v?"checked":"")+'><span>'+esc(f.label)+'</span></label>';
  else if(f.type==="resource"){
   const expired=f.state==="expired",summary=valueLabel(f,v)+(f.note?' · '+f.note:f.access?' · '+f.access:'');
   const title='<label id="'+id+'-label">'+esc(f.label)+(f.required?'<span class="required-mark" aria-hidden="true">*</span><span class="sr-only">必填</span>':'')+'</label>';
   const action='<button type="button" '+(expired?'data-reconnect="'+esc(f.key)+'"':'data-expand="'+esc(f.key)+'"')+' '+disabled+' aria-describedby="'+help+(error?' '+err:'')+'" '+(error?'aria-invalid="true"':'')+' aria-expanded="false">'+(expired?'重新连接':v?'更换':'选择')+'</button>';
   const picker='<div class="picker" data-picker="'+esc(f.key)+'" '+(f.pickerOpen?'':'hidden')+'><p>'+esc(f.pickerTitle||'选择员工可以使用的资料')+'</p><p>使用权限：'+esc(f.access)+'</p>'+(f.options||[]).map(o=>'<label><input type="radio" name="'+id+'" data-key="'+esc(f.key)+'" value="'+esc(o[0])+'" '+(o[0]===v?'checked':'')+' '+disabled+'>'+esc(o[1])+'</label>').join('')+(f.pickerActions||'')+'</div>';
   return '<div class="field resource-field" data-field="'+esc(f.key)+'"><div class="resource-heading">'+title+action+'</div><p class="resource-summary '+(!v?'warning':'')+'" id="'+help+'" title="'+esc(summary)+'">'+esc(summary)+(f.state==='pending'?' 已选择，保存配置后使用。':'')+'</p>'+(expired?'<p class="error">连接已失效，原有成果已保留。</p>':'')+picker+(error?'<p class="error" id="'+err+'">'+esc(error)+'</p>':'')+'</div>';
  }
  else if(f.type==="connection")control='<div class="binding"><div><strong class="'+(v==="expired"?"warning":"")+'">'+esc(f.connectionStatus||statuses[v])+'</strong><small>'+esc(v==='connected'||v==='expired'?f.account+' · '+f.access:f.access)+'</small></div><button type="button" data-connect="'+esc(f.key)+'" '+disabled+'>'+(f.connectionAction||(v==="connected"?"管理":v==="expired"?"重新连接":"连接"))+'</button></div>';
  else if(f.type==="runtime")control='<div class="binding"><div><strong>'+statuses[v]+'</strong><small>'+(v==="unknown"?"暂时无法读取运行状态":v==="ready"?"由平台检查":v==="unavailable"?"检查未通过，请核对运行条件":"等待平台核对")+'</small></div><button type="button" data-check="'+esc(f.key)+'" '+(v==="checking"||f.disabled?"disabled":"")+'>重新检查</button></div>';
  return '<div class="field" data-field="'+esc(f.key)+'">'+(f.type==="checkbox"?"":'<label id="'+id+'-label" '+(["multiselect","checklist","resource","connection","runtime"].includes(f.type)?"":'for="'+id+'"')+'>'+esc(f.label)+(f.required?'<span class="required-mark" aria-hidden="true">*</span><span class="sr-only">必填</span>':"")+'</label>')+control+(hint?'<p class="help" id="'+help+'">'+esc(hint)+'</p>':'')+(error?'<p class="error" id="'+err+'">'+esc(error)+'</p>':"")+'</div>';
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
})();
