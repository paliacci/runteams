/* Shared employee asset resources and native Agent extension helpers.
 * Classic script: functions retain their existing names and access the host's S/helpers at call time.
 * Do not run initialization here; do not redeclare S, api, ICON, esc, render or shared controls. */

let skillsBusinessScopeState;
let skillsWarmGeneration;
function skillsScopeState(){
  const state=skillsBusinessScopeState||(skillsBusinessScopeState={bound:false});
  if(!state.bound&&typeof window.addEventListener==='function'){
    window.addEventListener('runteams:business-scope-changed',skillsBusinessScopeChanged);state.bound=true;
  }
  return state;
}
function skillsScopeGeneration(){skillsScopeState();return window.RunTeamsBusinessStorage?.generation()??0;}
function skillsScopeCurrent(generation){return generation===skillsScopeGeneration();}

function skillsBusinessScopeChanged(){
  S.environmentLoading=false;
}

/* module-function:environmentChannelAvailabilityKey */
function environmentChannelAvailabilityKey(environment){return ((environment&&environment.channels)||[]).map(channel=>`${channel.id}:${channel.ready||channel.status==="ready"?1:0}`).sort().join("|");}
function environmentConnectedChannelIds(){return RunTeamsModelChannels.connectedIds(S);}

/* module-function:warmEnvironment */
async function warmEnvironment(refresh,notify){
  const scope=skillsScopeGeneration();if(_environmentWarmPromise&&skillsWarmGeneration===scope)return _environmentWarmPromise;
  const previousAvailability=environmentChannelAvailabilityKey(S.environment);let availabilityChanged=false;S.environmentLoading=true;
  const pending=(async()=>{const params=new URLSearchParams();if(refresh)params.set("refresh","1");
    // Establish connection state first; the status read never enumerates assets.
    const status=await modelChannelData().status(refresh);if(!status||!skillsScopeCurrent(scope))return false;
    if(status.error)throw new Error(status.error);syncChannelsFromEnvironment(status);
    const selected=environmentConnectedChannelIds().join(',');params.set('channel_ids',selected);
    const result=await modelChannelData().extensions(refresh);if(!result||!skillsScopeCurrent(scope)||selected!==environmentConnectedChannelIds().join(','))return false;
    if(result.error)throw new Error(result.error);
    result.channels=(status.channels||[]).map(channel=>(result.channels||[]).find(row=>String(row.id)===String(channel.id))||{...channel,ready:false,status:channel.status==='ready'?'disconnected':channel.status});
    if(result.counts)result.counts.channels=result.channels.length;
    S.environment=result;availabilityChanged=previousAvailability!==environmentChannelAvailabilityKey(result);
    syncChannelsFromEnvironment(result);saveEnvironmentSnapshot(result);refreshPersistentAgentWarnings();
    if(document.getElementById("channel_list"))renderChannels(false);return true;
  })();_environmentWarmPromise=pending;skillsWarmGeneration=scope;
  try{return await pending;}catch(e){if(skillsScopeCurrent(scope)&&notify)toast(refresh?"环境检查没有完成。请确认 Agent CLI 可用后再试":"模型与可执行技能没有载入。请确认本地服务正在运行","err");return false;}
  finally{if(_environmentWarmPromise===pending)_environmentWarmPromise=null;if(skillsScopeCurrent(scope)){S.environmentLoading=false;if(!S.booting&&availabilityChanged)render();if(S.settingsTab==='tools')accountReadSettingsExtensions();}}
}

/* module-function:environmentProvider */
function environmentProvider(value){const item=providerDefinition(value);return item&&item.label||value||"模型渠道";}

/* module-function:extensionResourceFileResult */
function extensionResourceFileResult(file,path){if(file.kind==="text")return {code:String(file.content||"")};if(file.kind==="image"&&file.media_type&&file.content)return {imageUrl:`data:${file.media_type};base64,${file.content}`};const reason=file.kind==="large"?"此文件较大，不在浏览器中展开。":"此文件是二进制资源，无法以文本方式显示。";return {code:`${reason}\n\n路径：${path}\n大小：${formatFileSize(file.size)}`};}

/* module-function:installedPluginResourcePayload */
async function installedPluginResourcePayload(channelId,pluginId){const listed=await modelChannelData().resources(channelId,pluginId);if(!listed)throw Error("渠道状态已变化。");if(listed.error)throw new Error(listed.error);const files={};(listed.files||[]).forEach(item=>{files[`/${String(item.path||"").replace(/^[/]+/,"")}`]={code:"",loaded:false};});const token=String(listed.token||"");return {files,activeFile:listed.active_file?`/${listed.active_file}`:"",loadFile:async path=>{const file=await modelChannelData().resourceFile(token,path);if(!file)throw Error("渠道状态已变化。");if(file.error)throw new Error(file.error);return extensionResourceFileResult(file,path);}};}

/* module-function:openInstalledPluginResources */
async function openInstalledPluginResources(channelId,pluginId){const item=((S.environment||{}).plugins||[]).find(value=>Number(value.channel_id)===Number(channelId)&&String(value.id||value.name)===String(pluginId));if(!item)return toast("插件已不在当前清单中，请重新读取。","err");if(!window.RunTeamsResourceViewer)return toast("资源查看器没有加载成功","err");const dialog=openChildDialog({className:"core-package-resources-modal",manageFocus:true,attrs:'role="dialog" aria-modal="true" onkeydown="if(event.key===\'Escape\'){event.preventDefault();event.stopPropagation();closeChildDialog()}"',title:`${item.display_name||item.name||item.id} 资源`,body:`<div id="installed_plugin_resource_viewer" class="core-package-resource-viewer-host" data-extension-resource-viewer><div class="core-package-resource-loading"><span class="env-spinner"></span><span>正在读取资源…</span></div></div>`,bodyClass:"mb core-package-resources-modal-body"});try{const payload=await installedPluginResourcePayload(channelId,pluginId),host=document.getElementById("installed_plugin_resource_viewer");if(!host||!dialog?.isConnected||!dialog.contains(host))return;window.RunTeamsResourceViewer.mount(host,payload);}catch(error){const host=document.getElementById("installed_plugin_resource_viewer");if(host&&dialog?.isConnected&&dialog.contains(host))host.innerHTML=RunTeamsLoadFailure.markup({variant:'modal',title:'资源暂时无法加载',error,retry:`openInstalledPluginResources(${Number(channelId)},${JSON.stringify(pluginId)})`});}}

function skillsResourceTreeModel(files){
  const root={children:[],folders:new Map()},seen=new Set();
  for(const file of files||[]){
    if(typeof file?.path!=='string'||!file.path||seen.has(file.path))continue;
    seen.add(file.path);const parts=file.path.split('/').filter(Boolean);if(!parts.length)continue;
    let parent=root;
    for(let i=0;i<parts.length-1;i++){const path=parts.slice(0,i+1).join('/');let folder=parent.folders.get(path);if(!folder){folder={name:parts[i],path,children:[],folders:new Map()};parent.folders.set(path,folder);parent.children.push(folder);}parent=folder;}
    parent.children.push({name:parts.at(-1),path:file.path,file});
  }
  const priority=node=>node.file&&node.path==='SKILL.md'?0:node.file&&node.path==='runteams.json'?1:node.children?2:3;
  const sort=parent=>{parent.children.sort((a,b)=>priority(a)-priority(b)||a.name.localeCompare(b.name,'zh-CN',{numeric:true}));for(const node of parent.children)if(node.children)sort(node);};sort(root);return root.children;
}
function skillsResourceRevealPath(state,path){
  const parts=String(path).split('/').filter(Boolean),open=new Set(state.resourceFolders||[]);
  for(let i=1;i<parts.length;i++)open.add(parts.slice(0,i).join('/'));
  state.resourceFolders=[...open];state.resourceFocus=path;state.resourceReveal=true;
}
function skillsResourceTreeMarkup(files,state={},scope='creator',id=0){
  const provider=scope==='creator'?{label:'作品文件与目录',select:encoded=>`RunTeamsCreatorAuthor.select(decodeURIComponent('${encoded}'))`}:RunTeamsHost.resources.tree(scope,id);
  const roots=skillsResourceTreeModel(files),open=new Set(state.resourceFolders||[]),visible=[];
  const collect=nodes=>{for(const node of nodes){visible.push(node);if(node.children&&open.has(node.path))collect(node.children);}};collect(roots);
  const focus=visible.find(node=>node.path===state.resourceFocus)?.path||visible.find(node=>node.path===state.activeFile)?.path||visible[0]?.path;
  const rows=(nodes,depth=0)=>nodes.map((node,index)=>{const folder=!!node.children,expanded=folder&&open.has(node.path),selected=!folder&&node.path===state.activeFile,encoded=skillsEncodePath(node.path),action=folder?`skillsToggleResourceFolder(event,'${scope}',${Number(id)},decodeURIComponent('${encoded}'))`:provider?.select(encoded)||'';
    return `<li role="treeitem" class="skills-resource-node" data-resource-path="${esc(node.path)}" data-resource-kind="${folder?'folder':'file'}" aria-label="${esc(node.name)}" aria-level="${depth+1}" aria-posinset="${index+1}" aria-setsize="${nodes.length}" ${folder?`aria-expanded="${expanded}"`:`aria-selected="${selected}"`} tabindex="${node.path===focus?0:-1}"><button type="button" tabindex="-1" class="skills-resource-file ${selected?'selected':''}" style="--resource-depth:${Math.min(depth,8)};padding-left:${8+Math.min(depth,8)*14}px" title="${esc(node.path)}" onclick="${action}"><span class="skills-resource-chevron ${folder?'':'spacer'}" aria-hidden="true">${folder?ICON('chev'):''}</span>${ICON(folder?'folder':'file')}<span>${esc(node.name)}</span></button>${expanded?`<ul role="group" class="skills-resource-tree">${rows(node.children,depth+1)}</ul>`:''}</li>`;
  }).join('');
  return roots.length?`<ul role="tree" aria-label="${esc(provider?.label||'技能文件与目录')}" class="skills-resource-tree" onkeydown="skillsResourceTreeKeydown(event,'${scope}',${Number(id)})" onfocusin="skillsResourceTreeFocus(event,'${scope}',${Number(id)})">${rows(roots)}</ul>`:'';
}
function skillsResourceTreeContext(scope,id){
  if(scope==='creator'){const state=window.RunTeamsCreatorAuthor?.current();return state?{state,files:state.files,selector:'.creator-asset-tree'}:null;}
  return RunTeamsHost.resources.tree(scope,id)||null;
}
function skillsResourceTreeFocus(event,scope,id){
  const row=event.target.closest('[role="treeitem"]'),context=skillsResourceTreeContext(scope,id);if(!row||!context)return;
  context.state.resourceFocus=row.dataset.resourcePath;for(const item of row.closest('[role="tree"]').querySelectorAll('[role="treeitem"]'))item.tabIndex=item===row?0:-1;
}

function skillsToggleResourceFolder(event,scope,id,path){
  event?.stopPropagation();const context=skillsResourceTreeContext(scope,id);if(!context)return;
  if(scope==='creator')RunTeamsCreatorAuthor.capture();
  const list=document.querySelector(context.selector);if(!list)return;
  const open=new Set(context.state.resourceFolders||[]),scroll=list.scrollTop;open.has(path)?open.delete(path):open.add(path);context.state.resourceFolders=[...open];context.state.resourceFocus=path;
  list.innerHTML=skillsResourceTreeMarkup(context.files,context.state,scope,id);
  Array.from(list.querySelectorAll('[role="treeitem"]')).find(row=>row.dataset.resourcePath===path)?.focus({preventScroll:true});
  list.scrollTop=scroll;skillsUpdateResourceEdges(list,true);
}
function skillsResourceTreeKeydown(event,scope,id){
  const row=event.target.closest('[role="treeitem"]');if(!row)return;
  const tree=row.closest('[role="tree"]'),items=Array.from(tree.querySelectorAll('[role="treeitem"]')),index=items.indexOf(row),folder=row.dataset.resourceKind==='folder',expanded=row.getAttribute('aria-expanded')==='true';let target;
  if(event.key==='ArrowDown')target=items[Math.min(index+1,items.length-1)];
  else if(event.key==='ArrowUp')target=items[Math.max(index-1,0)];
  else if(event.key==='Home')target=items[0];
  else if(event.key==='End')target=items.at(-1);
  else if(event.key==='ArrowRight'){if(folder&&!expanded){event.preventDefault();skillsToggleResourceFolder(event,scope,id,row.dataset.resourcePath);return;}if(folder)target=items[index+1];}
  else if(event.key==='ArrowLeft'){if(folder&&expanded){event.preventDefault();skillsToggleResourceFolder(event,scope,id,row.dataset.resourcePath);return;}target=row.parentElement.closest('[role="treeitem"]');}
  else if((event.key==='Enter'||event.key===' ')&&event.target===row){event.preventDefault();event.stopPropagation();row.querySelector('button').click();return;}
  else return;
  event.preventDefault();event.stopPropagation();target?.focus();
}
function skillsUpdateResourceEdges(list,remember=false){
  if(!list?.parentElement)return;
  const max=Math.max(0,list.scrollHeight-list.clientHeight),scroll=Math.max(0,list.scrollTop);
  list.parentElement.classList.toggle('has-before',max>1&&scroll>1);
  list.parentElement.classList.toggle('has-after',max>1&&scroll<max-1);
}
function skillsUpdatePreviewEdges(preview,remember=false){
  if(!preview?.parentElement)return;
  const max=Math.max(0,preview.scrollHeight-preview.clientHeight),scroll=Math.max(0,preview.scrollTop);
  preview.parentElement.classList.toggle('has-before',max>1&&scroll>1);
  preview.parentElement.classList.toggle('has-after',max>1&&scroll<max-1);
}
function skillsUpdateFileEdges(preview){
  const viewer=preview?.querySelector('.rt-file-viewer');if(!viewer)return null;
  const body=viewer.querySelector('.cm-scroller')||viewer.querySelector('.rt-file-body');
  const max=body?Math.max(0,body.scrollHeight-body.clientHeight):0,scroll=body?Math.max(0,body.scrollTop):0;
  viewer.classList.toggle('skills-file-has-before',max>1&&scroll>1);
  viewer.classList.toggle('skills-file-has-after',max>1&&scroll<max-1);
  const top=body?Math.max(0,body.getBoundingClientRect().top-viewer.getBoundingClientRect().top):0;
  viewer.style.setProperty('--skills-file-fade-top',`${top}px`);
  return body;
}
function skillsBindPreviewEdges(preview){
  if(!preview)return;
  if(skillsBindPreviewEdges.target===preview){skillsBindPreviewEdges.update?.();return;}
  skillsBindPreviewEdges.cleanup?.();skillsBindPreviewEdges.target=preview;
  let body=null,child=null,observer=null,mutations=null;
  const cleanup=()=>{observer?.disconnect();mutations?.disconnect();preview.removeEventListener('scroll',onScroll,true);};
  const update=()=>{
    if(!preview.isConnected){cleanup();return;}
    skillsUpdatePreviewEdges(preview);
    const next=skillsUpdateFileEdges(preview),nextChild=next?.firstElementChild;
    if(observer&&(next!==body||nextChild!==child)){
      if(body)observer.unobserve(body);if(child)observer.unobserve(child);
      body=next;child=nextChild;if(body)observer.observe(body);if(child)observer.observe(child);
    }
  };
  const onScroll=event=>{if(event.target!==preview)skillsUpdateFileEdges(preview);};
  if(typeof ResizeObserver!=='undefined'){observer=new ResizeObserver(update);observer.observe(preview);if(preview.firstElementChild)observer.observe(preview.firstElementChild);}
  if(typeof MutationObserver!=='undefined'){mutations=new MutationObserver(update);mutations.observe(preview,{childList:true,subtree:true,characterData:true});}
  preview.addEventListener('scroll',onScroll,true);skillsBindPreviewEdges.cleanup=cleanup;skillsBindPreviewEdges.update=update;update();
}

/* Skills-owned helpers. Native extension management above remains a separate source. */

function skillsEncodePath(path){return encodeURIComponent(path).replace(/'/g,"%27");}
