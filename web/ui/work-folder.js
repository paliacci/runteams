/* Work folder context shared by ordinary and employee conversation composers. */
(()=>{
 'use strict';
 let states=new WeakMap();
 function compactPath(value,fits){
  const separator=value.includes('\\')&&!value.includes('/')?'\\':'/';
  const parts=value.split(/[\\/]+/).filter(Boolean);
  let prefix='';
  if(value.startsWith('~'+separator)){prefix='~'+separator;parts.shift();}
  else if(/^[A-Za-z]:[\\/]/.test(value)){prefix=parts.shift()+separator;}
  else if(value.startsWith('\\\\')){prefix='\\\\'+parts.splice(0,2).join(separator)+separator;}
  else if(value.startsWith('/'))prefix='/';
  if(!prefix&&parts.length>1)prefix=parts.shift()+separator;
  const tail=parts.at(-1);if(!tail)return value;
  const head=prefix+(parts.length>1?'...'+separator:'');
  const candidate=head+tail;if(fits(candidate))return candidate;
  const graphemes=text=>typeof Intl!=='undefined'&&typeof Intl.Segmenter==='function'?[...new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(text)].map(part=>part.segment):Array.from(text);
  function middle(text,head=''){
   const characters=graphemes(text);let low=0,high=characters.length-1,result=head+'...';
   while(low<=high){const count=Math.floor((low+high)/2),left=Math.ceil(count/2),right=Math.floor(count/2),candidate=head+characters.slice(0,left).join('')+'...'+(right?characters.slice(-right).join(''):'');if(fits(candidate)){result=candidate;low=count+1;}else high=count-1;}
   return result;
  }
  return fits(head+'...')?middle(tail,head):middle(value);
 }
 function fitPath(label,value){
  const width=label.clientWidth;if(!width)return;
  label.textContent=compactPath(value,candidate=>{label.textContent=candidate;return label.scrollWidth<=width;});
 }
 const scope=()=>`${_workspaceBusinessGeneration}:${workspaceAccountCacheToken()}`;
 const owner=surface=>surface==='panel'?S.conversationPanel:S.chatCfg;
 const chatId=surface=>surface==='panel'?S.conversationPanel?.id:S.chatId;
 function supported(surface){const p=owner(surface);return !!p&&!RunTeamsHost.session.workspace(S)&&(S.localLibrary?.library_id||RunTeamsHost.session.ready(S))&&p.kind!=='employee_design'&&(surface!=='panel'||p.kind==='general')&&!p.scope_pipeline_id&&!p.scope_run_id&&!['pipeline-create','employee-design'].includes(S.chatMode)&&!p.context?.creator_authoring;}
 function state(surface){const p=owner(surface);if(!p||!supported(surface))return null;let s=states.get(p);if(!s||s.scope!==scope()){s={scope:scope(),folder:null,pending:null,picking:false,error:'',version:0};states.set(p,s);}return s;}
 function current(surface,s,p){return scope()===s.scope&&owner(surface)===p&&states.get(p)===s;}
 function validate(folder){if(!folder||typeof folder.id!=='string'||typeof folder.path!=='string'||typeof folder.display_path!=='string'||typeof folder.available!=='boolean')throw Error('工作文件夹未能读取，请重试。');return folder;}
 function paint(surface){
  document.querySelectorAll(`[data-work-folder="${surface}"]`).forEach(node=>{
   const control=node.closest('.conversation-folder-control')||node;
   const active=document.activeElement,keepFocus=control.contains(active),clearFocused=active?.classList.contains('conversation-folder-clear');
   const template=document.createElement('template');
   template.innerHTML=markup(surface,surface==='panel'?!!S.conversationPanel?.busy:!!S.chatBusy);
   const next=template.content.firstElementChild;
   if(!next){control.remove();return;}
   RunTeamsLocale.apply(next);
   control.replaceWith(next);
   if(keepFocus){
    const button=(clearFocused?next.querySelector('.conversation-folder-clear:not(:disabled)'):null)||next.querySelector('[data-work-folder]:not(:disabled)');
    button?.focus({preventScroll:true});
   }
  });
 }
 async function ensure(surface,force=false){const s=state(surface),p=owner(surface);if(!s)return null;if(s.pending)return s.pending;if(s.folder&&!force)return s.folder;const version=++s.version,id=chatId(surface);s.pending=(async()=>{try{const result=await api('/api/work-folders'+(id&&id!=='new'?'?chat_id='+encodeURIComponent(id):''),undefined,undefined,{readCurrent:true});if(!current(surface,s,p)||version!==s.version)return null;if(result.error)throw Error(result.error);s.folder=validate(result.folder);s.error='';return s.folder;}catch{if(current(surface,s,p))s.error=true;return null;}finally{if(current(surface,s,p)&&version===s.version){s.pending=null;paint(surface);}}})();return s.pending;}
 function markup(surface,busy=false){
  const s=state(surface);if(!s)return '';
  if(!s.folder&&!s.pending&&!s.error)queueMicrotask(()=>void ensure(surface));
  const f=s.folder,selected=f?.custom===true,disabled=busy||s.picking||!!s.pending&&!f;
  const hint=selected?esc(f.path):s.error?'无法读取工作文件夹。请重试。':'选择工作文件夹';
  const hintKey=selected?'':` data-app-i18n-title="workFolder.${s.error?'readFailed':'choose'}"`;
  const label=selected?`<span>${esc(f.name)}</span>`:'<span data-app-i18n="workFolder.unselected">未选工作区</span>';
  const unavailable=selected&&!f.available;
  const access=unavailable?` aria-label="工作文件夹“${esc(f.name)}”不可用" data-app-i18n-aria-label="workFolder.selectedUnavailable" data-app-i18n-vars="${esc(JSON.stringify({name:f.name}))}"`:'';
  return `<span class="conversation-folder-control"><button type="button" data-work-folder="${surface}" class="conversation-folder-trigger${unavailable?' is-unavailable':''}" ${selected?'data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="false"':''} ${disabled?'disabled':''} ${s.pending?'aria-busy="true"':''} title="${hint}"${hintKey}${access} onclick="RunTeamsWorkFolders.menu(event,'${surface}')">${ICON('folder')}${label}</button>${selected?`<button type="button" class="conversation-folder-clear" aria-label="清除工作文件夹" title="清除工作文件夹" data-app-i18n-aria-label="workFolder.clear" data-app-i18n-title="workFolder.clear" ${disabled?'disabled':''} onclick="RunTeamsWorkFolders.clear(event,'${surface}')">${ICON('x')}</button>`:''}</span>`;
 }
 async function menu(event,surface){
  const anchor=event.currentTarget,s=state(surface),p=owner(surface);
  if(!s||s.picking||(surface==='panel'?p.busy:S.chatBusy))return;
  if(!s.folder){
   await ensure(surface,true);if(!current(surface,s,p))return;
   const next=document.querySelector(`[data-work-folder="${surface}"]`);
   if(!s.folder)return toast('无法读取工作文件夹。请重试。','err','workFolder.readFailed');
   if(next)return menu({currentTarget:next,detail:event.detail},surface);
   return;
  }
  const f=s.folder;
  if(!f.custom){closePop();return pick(surface,s,p);}
  openMenu(anchor,[
   {label:f.display_path,disabled:!f.available,labelClass:'conversation-folder-path',fn:()=>void open(surface,s,p)},
   {label:'选择其他文件夹',labelKey:'workFolder.change',fn:()=>void pick(surface,s,p)}
  ],{variant:'workFolder',placement:'above'});
  const menu=document.getElementById('popmenu');if(!menu)return;
  menu.setAttribute('role','menu');
  menu.setAttribute('aria-label','工作文件夹');
  menu.dataset.appI18nAriaLabel='workFolder.title';
  menu.querySelectorAll('a[data-i]').forEach((node,i)=>{
   node.setAttribute('role','menuitem');node.tabIndex=node.getAttribute('aria-disabled')==='true'?-1:0;
   if(i!==0)return;
   node.classList.add('conversation-folder-path-row');
   node.title=f.path;
   node.setAttribute('aria-label',f.available?`打开工作文件夹“${f.path}”`:`工作文件夹“${f.path}”不可用`);
   node.dataset.appI18nAriaLabel=f.available?'workFolder.open':'workFolder.pathUnavailable';
   node.dataset.appI18nVars=JSON.stringify({path:f.path});
   fitPath(node.querySelector('.conversation-folder-path'),f.display_path);
  });
  RunTeamsLocale.apply(menu);
  menu.style.top=Math.max(8,anchor.getBoundingClientRect().top-menu.offsetHeight-6)+'px';
  if(event.detail===0)menu.querySelector('a[data-i]:not([aria-disabled="true"])')?.focus({preventScroll:true});
 }
 async function open(surface,s,p){if(!current(surface,s,p))return;try{const result=await api('/api/work-folders/open','POST',{chat_id:chatId(surface),selection_id:s.folder.id});if(result.error)throw Error(result.error);}catch{if(current(surface,s,p)){await ensure(surface,true);if(current(surface,s,p))toast('无法打开工作文件夹。','err','workFolder.openFailed');}}}
 async function clear(event,surface){event.preventDefault();event.stopPropagation();const s=state(surface),p=owner(surface);if(!s||!s.folder?.custom||(surface==='panel'?p.busy:S.chatBusy))return;closePop();await pick(surface,s,p,true);}
 async function pick(surface,s,p,clearing=false){if(!current(surface,s,p)||s.picking)return;if(surface==='panel'?p.editRewind:S.chatRewind){toast('请先完成或取消消息编辑，再更换文件夹。','info','workFolder.finishEditing');return;}const draft=conversationDraftValue(surface),attachments=conversationAttachments(surface),capabilities=conversationCapabilities(surface);s.picking=true;paint(surface);try{const result=await api('/api/work-folders/'+(clearing?'clear':'pick'),'POST',{chat_id:chatId(surface),...(clearing?{selection_id:s.folder.id}:{})});if(!current(surface,s,p)||result.cancelled)return;if(result.error)throw Object.assign(Error(result.error),{code:result.code});const folder=validate(result.folder);
 if(result.new_conversation){if(surface==='panel'&&RunTeamsEmployeeDirectory.employeePanel(p)){const entry=RunTeamsEmployeeDirectory.forPanel(p);if(!entry){toast('请先恢复员工资产，再开始新对话。','err','workFolder.employeeUnavailable');return;}await RunTeamsEmployeeDirectory.newSession(entry.key);}else await newRailChat({draft});if(scope()!==s.scope)return;const next=owner('panel');if(next===p){toast('无法打开新对话。请重试。','err','workFolder.conversationFailed');return;}next.input=draft;next.attachments=attachments;next.capabilities=capabilities;const nextState=state('panel');if(nextState){nextState.folder=clearing?null:folder;nextState.error='';}render();if(clearing)await ensure('panel',true);return;}
 s.folder=folder;s.error='';
 }catch(error){
  if(current(surface,s,p)){
   if(error.code==='mutation_outcome_unknown'){
    await ensure(surface,true);
    if(current(surface,s,p))toast('暂时无法确认更改结果。请核对当前工作文件夹。','err','workFolder.changeUnknown');
   }else if(error.message==='工作文件夹已变化，请重新读取。'){
    await ensure(surface,true);
    if(current(surface,s,p))toast('工作文件夹已变化。请核对当前选择。','err','workFolder.selectionChanged');
   }else if(error.message==='请在本机桌面版选择工作文件夹。')toast(error.message,'info','workFolder.desktopOnly');
   else if(error.message==='已有资料选择窗口。')toast('请先关闭当前文件选择窗口。','info','workFolder.pickerAlreadyOpen');
   else if(error.message==='请先结束当前回复或文件夹选择。'||error.message==='请先结束当前回复。')toast('请等待当前回复结束，再更换工作文件夹。','info','workFolder.replyInProgress');
   else if(error.message==='工作文件夹不可用，请重新选择。')toast(error.message,'err','workFolder.unavailable');
   else if(clearing)toast('无法清除工作文件夹。请重试。','err','workFolder.clearFailed');
   else toast('无法选择工作文件夹。请重试。','err','workFolder.pickFailed');
  }
 }finally{
  s.picking=false;
  if(current(surface,s,p)){
   paint(surface);
   if(document.activeElement===document.body)document.querySelector(`[data-work-folder="${surface}"]:not(:disabled)`)?.focus({preventScroll:true});
  }
 }}
 async function prepare(surface){const s=state(surface);if(!s)return null;if(s.picking){toast('请先完成文件夹选择。','info','workFolder.finishPicking');return false;}const p=owner(surface),f=await ensure(surface);if(!current(surface,s,p))return false;if(!f||!f.available){if(s.error)toast('无法读取工作文件夹。请重试。','err','workFolder.readFailed');else toast('工作文件夹不可用，请重新选择。','err','workFolder.unavailable');return false;}return {selection_id:f.id,scope:s.scope};}
 async function bind(id,selection){if(scope()!==selection.scope)throw Error('账户已变化，请重新打开对话。');const result=await api('/api/work-folders/bind','POST',{chat_id:id,selection_id:selection.selection_id});if(result.error)throw Error(result.error);if(scope()!==selection.scope)throw Error('账户已变化，请重新打开对话。');return validate(result.folder);}
 window.RunTeamsWorkFolders=Object.freeze({markup,menu,clear,prepare,bind,compactPath});
 window.addEventListener('runteams:business-scope-changed',()=>{states=new WeakMap();});
})();
