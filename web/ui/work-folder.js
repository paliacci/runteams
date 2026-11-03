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
 function supported(surface){const p=owner(surface);return !!p&&!S.activeOrganization&&(S.localLibrary?.library_id||S.account?.signed_in)&&p.kind!=='employee_design'&&(surface!=='panel'||p.kind==='general')&&!p.scope_pipeline_id&&!p.scope_run_id&&!['pipeline-create','employee-design'].includes(S.chatMode)&&!p.context?.creator_authoring;}
 function state(surface){const p=owner(surface);if(!p||!supported(surface))return null;let s=states.get(p);if(!s||s.scope!==scope()){s={scope:scope(),folder:null,pending:null,picking:false,error:'',version:0};states.set(p,s);}return s;}
 function current(surface,s,p){return scope()===s.scope&&owner(surface)===p&&states.get(p)===s;}
 function validate(folder){if(!folder||typeof folder.id!=='string'||typeof folder.path!=='string'||typeof folder.display_path!=='string'||typeof folder.available!=='boolean')throw Error('工作文件夹未能读取，请重试。');return folder;}
 function paint(surface){document.querySelectorAll(`[data-work-folder="${surface}"]`).forEach(node=>{(node.closest('.conversation-folder-control')||node).outerHTML=markup(surface,surface==='panel'?!!S.conversationPanel?.busy:!!S.chatBusy);});}
 async function ensure(surface,force=false){const s=state(surface),p=owner(surface);if(!s)return null;if(s.pending)return s.pending;if(s.folder&&!force)return s.folder;const version=++s.version,id=chatId(surface);s.pending=(async()=>{try{const result=await api('/api/work-folders'+(id&&id!=='new'?'?chat_id='+encodeURIComponent(id):''),undefined,undefined,{readCurrent:true});if(!current(surface,s,p)||version!==s.version)return null;if(result.error)throw Error(result.error);s.folder=validate(result.folder);s.error='';return s.folder;}catch(error){if(current(surface,s,p)){s.error=error.message||'工作文件夹未能读取';}return null;}finally{if(current(surface,s,p)&&version===s.version){s.pending=null;paint(surface);}}})();return s.pending;}
 function markup(surface,busy=false){const s=state(surface);if(!s)return '';if(!s.folder&&!s.pending&&!s.error)queueMicrotask(()=>void ensure(surface));const f=s.folder,selected=f?.custom===true,label=selected?f.name:'未选工作区',disabled=busy||s.picking||!!s.pending&&!f;return `<span class="conversation-folder-control"><button type="button" data-work-folder="${surface}" class="conversation-folder-trigger${selected&&!f.available?' is-unavailable':''}" ${selected?'data-menu-trigger="quiet" aria-haspopup="menu" aria-expanded="false"':''} ${disabled?'disabled':''} ${s.pending?'aria-busy="true"':''} title="${esc(s.error||(selected?f.path:'选择工作文件夹'))}" onclick="RunTeamsWorkFolders.menu(event,'${surface}')">${ICON('folder')}<span>${esc(label)}</span></button>${selected?`<button type="button" class="conversation-folder-clear" aria-label="清除工作文件夹" title="清除工作文件夹" ${disabled?'disabled':''} onclick="RunTeamsWorkFolders.clear(event,'${surface}')">${ICON('x')}</button>`:''}</span>`;}
 async function menu(event,surface){const anchor=event.currentTarget,s=state(surface),p=owner(surface);if(!s||s.picking||(surface==='panel'?p.busy:S.chatBusy))return;if(!s.folder){await ensure(surface,true);if(!current(surface,s,p))return;const next=document.querySelector(`[data-work-folder="${surface}"]`);if(!s.folder)return toast(s.error,'err');if(next)return menu({currentTarget:next},surface);return;}
 const f=s.folder,selected=f.custom===true,items=[];
 if(!selected){closePop();return pick(surface,s,p);}
 if(selected)items.push({label:f.display_path,disabled:!f.available,labelClass:'conversation-folder-path',fn:()=>void open(surface,s,p)});
 items.push({label:'选择文件夹',fn:()=>void pick(surface,s,p)});
 openMenu(anchor,items,{variant:'workFolder',placement:'above'});const m=document.getElementById('popmenu');if(m){m.setAttribute('role','menu');m.querySelectorAll('a[data-i]').forEach((node,i)=>{node.setAttribute('role','menuitem');node.tabIndex=0;if(selected&&i===0){node.classList.add('conversation-folder-path-row');node.title=f.path;node.setAttribute('aria-label','打开工作文件夹：'+f.path);fitPath(node.querySelector('.conversation-folder-path'),f.display_path);}});if(selected){const rect=anchor.getBoundingClientRect();m.style.top=Math.max(8,rect.top-m.offsetHeight-6)+'px';}}}

 async function open(surface,s,p){if(!current(surface,s,p))return;try{const result=await api('/api/work-folders/open','POST',{chat_id:chatId(surface),selection_id:s.folder.id});if(result.error)throw Error(result.error);}catch(error){if(current(surface,s,p))toast(error.message,'err');}}
 async function clear(event,surface){event.preventDefault();event.stopPropagation();const s=state(surface),p=owner(surface);if(!s||!s.folder?.custom||(surface==='panel'?p.busy:S.chatBusy))return;closePop();await pick(surface,s,p,true);}
 async function pick(surface,s,p,clearing=false){if(!current(surface,s,p)||s.picking)return;if(surface==='panel'?p.editRewind:S.chatRewind){toast('请先完成或取消当前消息编辑，再更换文件夹','info');return;}const draft=conversationDraftValue(surface),attachments=conversationAttachments(surface),capabilities=conversationCapabilities(surface);s.picking=true;paint(surface);try{const result=await api('/api/work-folders/'+(clearing?'clear':'pick'),'POST',{chat_id:chatId(surface),...(clearing?{selection_id:s.folder.id}:{})});if(!current(surface,s,p)||result.cancelled)return;if(result.error)throw Error(result.error);const folder=validate(result.folder);
 if(result.new_conversation){if(surface==='panel'&&RunTeamsEmployeeDirectory.employeePanel(p)){const entry=RunTeamsEmployeeDirectory.forPanel(p);if(!entry)throw Error('员工资产暂不可用，请恢复资产后开始新对话。');await RunTeamsEmployeeDirectory.newSession(entry.key);}else await newRailChat({draft});if(scope()!==s.scope)return;const next=owner('panel');if(next===p)throw Error('新对话未能打开，请重试。');next.input=draft;next.attachments=attachments;next.capabilities=capabilities;const nextState=state('panel');if(nextState){nextState.folder=clearing?null:folder;nextState.error='';}render();if(clearing)await ensure('panel',true);return;}
 s.folder=folder;s.error='';paint(surface);
 }catch(error){if(current(surface,s,p))toast(error.message||'工作文件夹未能选择','err');}finally{s.picking=false;if(current(surface,s,p))paint(surface);}}
 async function prepare(surface){const s=state(surface);if(!s)return null;if(s.picking){toast('请先完成文件夹选择','info');return false;}const p=owner(surface),f=await ensure(surface);if(!current(surface,s,p))return false;if(!f||!f.available){toast(s.error||'工作文件夹不可用，请重新选择','err');return false;}return {selection_id:f.id,scope:s.scope};}
 async function bind(id,selection){if(scope()!==selection.scope)throw Error('账户已变化，请重新打开对话。');const result=await api('/api/work-folders/bind','POST',{chat_id:id,selection_id:selection.selection_id});if(result.error)throw Error(result.error);if(scope()!==selection.scope)throw Error('账户已变化，请重新打开对话。');return validate(result.folder);}
 window.RunTeamsWorkFolders=Object.freeze({markup,menu,clear,prepare,bind,compactPath});
 window.addEventListener('runteams:business-scope-changed',()=>{states=new WeakMap();});
})();
