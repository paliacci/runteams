/* Shared dialogs, menus, model/effort selectors and toasts. Main session owns this file.
 * Classic script: uses host state/helpers at call time; no duplicate application state. */

/* module-function:toast */
function toast(msg, kind){
  kind=kind||"info";
  let host=document.getElementById("toasts");
  if(!host){ host=document.createElement("div"); host.id="toasts"; host.className="toasts"; document.body.appendChild(host); }
  const t=document.createElement("div"); t.className="toast "+kind;
  t.innerHTML=`${ICON(kind==="ok"?"check":(kind==="err"?"x":"info"))}<span>${esc(msg)}</span>`;
  host.appendChild(t);
  setTimeout(()=>{ t.style.opacity="0"; t.style.transform="translateY(8px)"; setTimeout(()=>t.remove(),260); }, 2600);
}

/* module-function:openModal */
function openModal(html){ closeModal(); const d=document.createElement("div"); d.id="modalHost"; d.innerHTML=html; d.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing&&!event.defaultPrevented){const close=d.querySelector('.modal-x:not([disabled])');if(close){event.preventDefault();event.stopPropagation();close.click();}}}); document.body.appendChild(d); return d; }

/* module-function:dialogMarkup */
function dialogMarkup(opts={}){
  const closeAction=opts.closeAction||"closeModal()",scrimHandler=opts.scrimHandler||(opts.closeOnScrim===false?"":`if(event.target===this)${closeAction}`),scrimAttr=scrimHandler?` onclick="${scrimHandler}"`:"";
  const classes=["modal","dialog-shell",opts.className||""].filter(Boolean).join(" "),attrs=opts.attrs?` ${opts.attrs}`:"";
  const header=opts.headerHtml!=null?`<div class="mh ${opts.headerClass||""}">${opts.headerHtml}</div>`:(opts.title!=null?`<div class="mh ${opts.headerClass||""}">${opts.leading||""}<div class="tt">${esc(opts.title)}${opts.subtitle?`<div class="s">${esc(opts.subtitle)}</div>`:""}</div>${opts.headerActions||""}${opts.showClose===false?"":`<button type="button" class="x modal-x" aria-label="关闭${esc(opts.title||'弹窗')}" onclick="${closeAction}">${ICON("x")}</button>`}</div>`:"");
  const body=opts.content!=null?opts.content:(opts.body!=null?`<div class="${opts.bodyClass||"mb"}"${opts.bodyAttrs?` ${opts.bodyAttrs}`:""}>${opts.body}</div>`:"");
  const footer=opts.footer!=null?`<div class="${opts.footerClass||"mf"}"${opts.footerAttrs?` ${opts.footerAttrs}`:""}>${opts.footer}</div>`:"";
  return `<div class="scrim ${opts.scrimClass||""}"${scrimAttr}><div class="${classes}"${attrs}>${header}${body}${footer}</div></div>`;
}

/* module-function:openDialog */
function openDialog(opts){return openModal(dialogMarkup(opts));}

/* module-function:replaceDialog */
function replaceDialog(opts){closeTransientMenus();const host=document.getElementById("modalHost");if(host)host.innerHTML=dialogMarkup(opts);return host;}

/* module-function:childDialogMarkup */
function childDialogMarkup(opts={}){return dialogMarkup({...opts,closeAction:"closeChildDialog()",scrimHandler:opts.scrimHandler||"if(event.target===this)closeChildDialog()",scrimClass:[opts.scrimClass||"","nested-scrim"].filter(Boolean).join(" ")});}

/* module-function:openChildDialog */
function openChildDialog(opts){
  closeChildDialog();
  closeTransientMenus();
  const host=document.createElement("div");host.id="childModalHost";
  host.innerHTML=childDialogMarkup(opts);
  document.body.appendChild(host);
  if(opts.manageFocus){
    host._returnFocus=document.activeElement;
    const focusable=()=>[...host.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')].filter(e=>e.getClientRects().length);
    host.addEventListener('keydown',event=>{if(event.key!=="Tab")return;const items=focusable(),first=items[0],last=items[items.length-1];if(!first)return;if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}});
    focusable()[0]?.focus();
  }
  return host;
}

/* module-function:replaceChildDialog */
function replaceChildDialog(opts){closeTransientMenus();const host=document.getElementById("childModalHost");if(host)host.innerHTML=childDialogMarkup(opts);return host;}

/* module-function:closeChildDialog */
function closeChildDialog(){const host=document.getElementById("childModalHost");if(!host)return;if(window.RunTeamsResourceViewer)host.querySelectorAll("[data-extension-resource-viewer]").forEach(viewer=>{try{window.RunTeamsResourceViewer.unmount(viewer);}catch(error){}});const returnFocus=host._returnFocus;host.remove();if(returnFocus?.isConnected)returnFocus.focus();}

/* module-function:closeModal */
function closeModal(){
  if(typeof closeModelChannelGuide==="function")closeModelChannelGuide();
  closeChildDialog();
  closeTransientMenus();
  if(typeof closeWorkerAvatarPicker==="function")closeWorkerAvatarPicker();
  const m=document.getElementById("modalHost");if(m)m.remove();
}

/* module-function:confirmModal */
function confirmModal(title, msg, onOk, danger){
  const actionLabel=danger&&/删除/.test(String(title||""))?"删除":"确认";
  const d=openDialog({className:"modal-confirm",title,showClose:false,headerActions:`<button type="button" class="x modal-x" aria-label="关闭弹窗" onclick="closeModal()">${ICON("x")}</button>`,body:`<div class="modal-copy">${esc(msg)}</div>`,footer:`<div class="grow"></div><button class="btn" onclick="closeModal()">取消</button><button class="btn ${danger?'danger':'pri'}" id="_ok">${esc(actionLabel)}</button>`});
  d.querySelector("#_ok").onclick=()=>{ closeModal(); onOk&&onOk(); };
}

/* module-function:inputModal */
function inputModal(opts, onOk){
  const d=openDialog({className:`modal-input ${opts.variant==="rename"?"modal-rename":""}`,title:opts.title,subtitle:opts.sub,body:`<div class="field"><label>${esc(opts.label||"名称")}</label><input class="inp" id="_v1" placeholder="${esc(opts.ph1||"")}" value="${esc(opts.v1||"")}"></div>${opts.label2?`<div class="field"><label>${esc(opts.label2)}</label><textarea class="ta" id="_v2" placeholder="${esc(opts.ph2||"")}">${esc(opts.v2||"")}</textarea></div>`:""}`,footer:`<div class="grow"></div><button class="btn" onclick="closeModal()">取消</button><button class="btn pri" id="_ok">${esc(opts.ok||"保存")}</button>`});
  const i1=d.querySelector("#_v1"); i1.focus(); i1.select&&i1.select();
  const submit=()=>{ const v1=i1.value.trim(); if(!v1){ i1.focus(); return; } const v2=d.querySelector("#_v2"); closeModal(); onOk(v1, v2?v2.value.trim():""); };
  d.querySelector("#_ok").onclick=submit;
  i1.addEventListener("keydown",e=>{ if(e.key==="Enter"&&!opts.label2) submit(); });
}

/* module-function:menuVariantClasses */
function menuVariantClasses(variant="default"){const preset=MENU_VARIANTS[variant];if(preset==null)throw new Error(`未知菜单规格: ${variant}`);return preset;}

/* module-function:createMenuSurface */
function createMenuSurface({id="",variant="default",role="",base=true}={}){const menu=document.createElement("div"),classes=menuVariantClasses(variant);menu.className=(base?"menu":"")+(classes?(base?" ":"")+classes:"");if(id)menu.id=id;if(role)menu.setAttribute("role",role);return menu;}

/* module-function:menuItemsMarkup */
function menuItemsMarkup(items){return items.map((it,i)=>it.account?`<div class="channel-menu-account">${it.label?`<div class="channel-menu-email" title="${esc(it.label)}">${esc(it.label)}</div>`:''}${it.plan?`<span class="channel-menu-plan">${esc(it.plan)}</span>`:''}</div>`:it.head?`<div class="menuhead">${it.provider&&providerBrandIcon(it.provider)?`<span class="model-menu-provider-icon">${providerBrandIcon(it.provider)}</span>`:""}<span>${esc(it.label)}</span>${it.action?`<button type="button" class="menu-head-action" data-menu-head-action="${i}"${it.action.disabled?' disabled':''}>${it.action.icon?ICON(it.action.icon):''}<span>${esc(it.action.label)}</span></button>`:""}</div>`:it.divider?`<div class="menu-divider" role="separator"></div>`:it.empty?`<div class="menu-empty ${esc(it.emptyClass||"chat-capability-empty")}" ${it.hidden?'hidden':''}>${esc(it.label)}</div>`:`<a data-i="${i}" ${it.capability?'data-chat-capability="1"':''}${it.submenu?' aria-haspopup="menu" aria-expanded="false"':''}${it.disabled?' aria-disabled="true" data-disabled="true"':''}${it.help?' data-help="true"':''} data-search="${esc(String(it.searchText||it.label||'').toLowerCase())}" class="${it.danger?'danger':''}${it.selected?' selected':''}${it.disabled?' disabled':''}${it.submenu?' has-submenu':''}">${it.swatch?`<i class="menu-swatch column-swatch-${esc(it.swatch)}" aria-hidden="true"></i>`:(it.provider&&providerBrandIcon(it.provider)?`<span class="menu-provider-icon ${providerTone(it.provider)}">${providerBrandIcon(it.provider)}</span>`:(it.iconUrl?`<img class="menu-icon" src="${esc(it.iconUrl)}" alt="">`:(it.iconBox?`<span class="menu-icon menu-vector-icon">${ICON(it.iconBox)}</span>`:(it.icon?ICON(it.icon):""))))}<span class="menu-copy"><b${it.labelClass?` class="${esc(it.labelClass)}"`:""}>${esc(it.label)}</b>${it.description?`<small>${esc(it.description)}</small>`:""}</span><span class="menu-check">${ICON("check")}</span>${it.submenu?`<span class="menu-submenu-arrow" aria-hidden="true">${ICON("chev")}</span>`:""}</a>`).join("");}

/* module-function:filterSkillPickerMenu */
function filterSkillPickerMenu(value){const menu=document.getElementById("popmenu");if(!menu?.classList.contains("skill-picker-menu"))return;const query=String(value||"").trim().toLowerCase(),rows=[...menu.querySelectorAll("a[data-i]")];rows.forEach(row=>{row.hidden=!!query&&!String(row.dataset.search||"").includes(query);row.classList.remove("active");});let empty=menu.querySelector(".skill-picker-empty"),visible=rows.some(row=>!row.hidden);if(!empty){empty=document.createElement("div");empty.className="menu-empty skill-picker-empty";empty.textContent="没有匹配的技能";menu.appendChild(empty);}empty.hidden=visible||!query;}

/* module-function:openSkillPickerMenu */
function openSkillPickerMenu(anchor,items,options={}){openMenu(anchor,items,{variant:"skillPicker",align:options.align||"left",placement:options.placement});if(_popAnchor!==anchor)return;const menu=document.getElementById("popmenu");if(!menu)return;const placeholder=options.placeholder||"搜索可执行技能";menu.insertAdjacentHTML("afterbegin",`<label class="skill-picker-search rt-search-field rt-search-field--compact">${ICON("search")}<input type="search" placeholder="${esc(placeholder)}" aria-label="${esc(placeholder)}" autocomplete="off" oninput="filterSkillPickerMenu(this.value)"></label>`);requestAnimationFrame(()=>menu.querySelector("input")?.focus());}

/* module-function:openNestedMenu */
function openNestedMenu(anchor,items,config={}){const {id="nestedMenu",variant="default",onClose=null,placement="below",positionAnchor=anchor,horizontalAnchor=positionAnchor,edgeAnchor=horizontalAnchor,dismissOutside=true,gap=6}=config,menu=createMenuSurface({id,variant,role:"menu"});menu.innerHTML=menuItemsMarkup(items);menu.addEventListener("click",event=>event.stopPropagation());document.body.appendChild(menu);setMenuTriggerActive(anchor,true);const margin=8,position=()=>{const rect=positionAnchor?.getBoundingClientRect?.()||anchor.getBoundingClientRect(),horizontalRect=horizontalAnchor?.getBoundingClientRect?.()||rect,edgeRect=edgeAnchor?.getBoundingClientRect?.()||horizontalRect,width=menu.offsetWidth,height=menu.offsetHeight,spaceBelow=window.innerHeight-rect.bottom-gap-margin;let left,top;if(placement==="right"){const rightLeft=edgeRect.right+gap,rightWidth=rightLeft+width;left=rightWidth<=window.innerWidth-margin?rightLeft:Math.max(margin,edgeRect.left-width-gap);const centered=rect.top+(rect.height-height)/2;top=Math.max(margin,Math.min(centered,window.innerHeight-height-margin));}else{left=Math.max(margin,Math.min(placement==="below-start"?horizontalRect.left:horizontalRect.right-width,window.innerWidth-width-margin));top=spaceBelow>=height?rect.bottom+gap:Math.max(margin,rect.top-height-gap);}menu.style.left=`${left}px`;menu.style.top=`${top}px`;};position();requestAnimationFrame(position);let closed=false,index=-1;const links=[];const close=()=>{if(closed)return;closed=true;document.removeEventListener("pointerdown",outside,true);document.removeEventListener("keydown",keydown);menu.remove();setMenuTriggerActive(anchor,false);if(onClose)onClose();},outside=event=>{if(menu.contains(event.target)||anchor.contains(event.target)||positionAnchor?.contains?.(event.target)||edgeAnchor?.contains?.(event.target))return;close();},setActive=next=>{if(!links.length)return;index=(next+links.length)%links.length;links.forEach((link,i)=>link.classList.toggle("active",i===index));},keydown=event=>{if(event.key==="Escape"){event.preventDefault();close();}else if(event.key==="ArrowDown"){event.preventDefault();setActive(index+1);}else if(event.key==="ArrowUp"){event.preventDefault();setActive(index-1);}else if(event.key==="Enter"&&index>=0){event.preventDefault();links[index].click();}};items.forEach((entry,itemIndex)=>{const item=entry.head?entry.action:entry;if(!item||item.head||item.divider||item.empty||item.disabled)return;const link=menu.querySelector(entry.head?`[data-menu-head-action="${itemIndex}"]`:`[data-i="${itemIndex}"]`);if(!link)return;links.push(link);link.onfocus=()=>setActive(links.indexOf(link));link.onmousemove=()=>setActive(links.indexOf(link));let activated=false;const activate=event=>{event.preventDefault();event.stopPropagation();if(activated)return;activated=true;if(item.fn)item.fn();close();};if(variant==="docBlockSubmenu"){link.onpointerdown=activate;link.onmousedown=activate;}link.onclick=activate;});if(dismissOutside)setTimeout(()=>{if(!closed)document.addEventListener("pointerdown",outside,true);},0);document.addEventListener("keydown",keydown);return {menu,close};}

/* module-function:openMenu */
function openMenu(anchor,items,config={}){const {variant="default",...opts}=config||{};return popMenu(anchor,items,variant,opts);}

/* module-function:setMenuTriggerActive */
function setMenuTriggerActive(anchor,active){
  if(!anchor||!anchor.matches||!anchor.matches("button,.csel,[role='button'],.pl,.card"))return;
  if(anchor.matches("button,[role='button']")){
    anchor.setAttribute("aria-haspopup",anchor.matches(".runtime-csel")?"dialog":"menu");
    if(!anchor.hasAttribute("data-menu-trigger"))anchor.setAttribute("data-menu-trigger",anchor.matches(".csel")?"field":"quiet");
  }
  anchor.classList.toggle("menu-trigger-active",active);anchor.setAttribute("aria-expanded",String(active));
}

/* module-function:popMenu */
function popMenu(anchor, items, variant, opts){
  opts=opts||{};
  if(document.getElementById("popmenu")&&_popAnchor===anchor&&!opts.at){closePop();return;}
  closePop();
  const menuClass=menuVariantClasses(variant),m=createMenuSurface({id:"popmenu",variant});
  m.innerHTML=menuItemsMarkup(items);
  if(variant==='channelAccount'){m.setAttribute('role','menu');m.tabIndex=-1;m.querySelectorAll('a[data-i]').forEach(a=>{a.id='channel_menu_option_'+a.dataset.i;a.setAttribute('role','menuitem');a.tabIndex=-1;});}
  if(variant==='settingsSelect'){m.setAttribute('role','menu');m.tabIndex=-1;m.querySelectorAll('a[data-i]').forEach(a=>{a.id='settings_option_'+a.dataset.i;a.setAttribute('role','menuitemradio');a.setAttribute('aria-checked',String(a.classList.contains('selected')));});}
  document.body.appendChild(m);
  if(opts.multi)m.addEventListener("click",e=>e.stopPropagation());
  _popAnchor=anchor;setMenuTriggerActive(anchor,true);
  const positionAnchor=opts.positionAnchor||anchor,r=opts.at?{left:opts.at.x,right:opts.at.x,top:opts.at.y,bottom:opts.at.y}:positionAnchor.getBoundingClientRect();
  const gap=variant==='channelAccount'?4:6, margin=8, full=variant==='settingsSelect'?Math.min(280,m.offsetHeight):m.offsetHeight;
  const spaceBelow=window.innerHeight-r.bottom-gap-margin, spaceAbove=r.top-gap-margin;
  let top, maxH;
  if(opts.placement==="above"){maxH=Math.max(96,spaceAbove);top=Math.max(margin,r.top-Math.min(full,maxH)-gap);}
  else if(full<=spaceBelow){ top=r.bottom+gap; maxH=spaceBelow; }       // 下方放得下
  else if(full<=spaceAbove){ top=r.top-full-gap; maxH=spaceAbove; }     // 上方放得下
  else if(spaceBelow>=spaceAbove){ top=r.bottom+gap; maxH=spaceBelow; } // 都放不下→选空间大的一侧,内部滚动
  else { top=margin; maxH=spaceAbove; }
  m.style.top=top+"px";
  m.style.maxHeight=Math.max(96,Math.min(full,maxH))+"px"; m.style.overflowY="auto";   // 保留组件自身限高,避免定位后变高覆盖锚点
  // 右对齐：菜单右边缘贴按钮右边缘；变换原点同时挪到右上角，出现动画才不会把右边缘拉走
  if(opts.align==="right")m.classList.add("menu-align-right");
  const wanted=opts.align==="right"?r.right-m.offsetWidth:r.left;
  m.style.left=Math.max(margin, Math.min(wanted, window.innerWidth-m.offsetWidth-margin))+"px";
  const sel=[]; let cur=-1;
  const setActive=(k)=>{ cur=k; sel.forEach((a,j)=>a.classList.toggle("active",j===k));if(variant==='settingsSelect'||variant==='channelAccount'){sel[k]?.scrollIntoView({block:"nearest"});if(sel[k])m.setAttribute('aria-activedescendant',sel[k].id);} };
  items.forEach((item,i)=>{ const it=item.head?item.action:item;if(!it||it.head||it.divider||it.empty||(it.disabled&&(item.head||variant==='settingsSelect'))) return; const a=m.querySelector(item.head?`[data-menu-head-action="${i}"]`:`[data-i="${i}"]`);if(!a)return; const k=sel.length; sel.push(a);a.onfocus=()=>setActive(k);
    if(menuClass&&menuClass.includes("chat-add-menu"))a.onmousedown=e=>e.preventDefault();a.onclick=(e)=>{ e.stopPropagation();if(opts.multi){ it.selected=!it.selected; a.classList.toggle("selected",it.selected); it.fn&&it.fn(it.selected); } else if(it.keepOpen){it.fn&&it.fn(a);}else { closePop(); it.fn&&it.fn(); } }; a.onmouseenter=()=>{setActive(k);if(it.hoverFn)it.hoverFn(a);};a.onmousemove=()=>setActive(k); });
  _popKey=(e)=>{ if(variant==='chatAdd'&&(e.isComposing||e.keyCode===229||e.target?.dataset?.composing==='true'))return;if(e.key==="Escape"){e.preventDefault();e.stopPropagation();closePop();anchor.focus({preventScroll:true});return;}if(variant==='chatAdd'&&m._capabilityPage){
      const rows=[...m.querySelectorAll('a[data-i],.chat-capability-retry')].filter(row=>!row.hidden&&!row.disabled&&row.dataset.disabled!=='true'&&row.dataset.installing!=='1'),index=rows.findIndex(row=>row.classList.contains('active'));
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){if(!rows.length)return;e.preventDefault();const next=rows[(index+(e.key==='ArrowDown'?1:index<0?0:-1)+rows.length)%rows.length];m.querySelectorAll('.active').forEach(row=>row.classList.remove('active'));next.classList.add('active');next.scrollIntoView({block:'nearest'});}
      else if(e.key==='Enter'&&index>=0){e.preventDefault();rows[index].click();}return;
    }const visible=sel.filter(a=>!a.hidden);if(!visible.length)return;const current=visible.indexOf(sel[cur]);
    if(e.key==="Tab"&&['settingsSelect','channelAccount'].includes(variant)){closePop();return;}
    if(e.key==="ArrowDown"){ e.preventDefault();const next=visible[(current+1)%visible.length];setActive(sel.indexOf(next)); }
    else if(e.key==="ArrowUp"){ e.preventDefault();const next=visible[(current-1+visible.length)%visible.length];setActive(sel.indexOf(next)); }
    else if(e.key==="Enter"||e.key===" "&&variant==="channelAccount"){ if(cur>=0&&!sel[cur].hidden){ e.preventDefault(); sel[cur].click(); } }
    };
  document.addEventListener("keydown",_popKey);
  if(variant==='settingsSelect'){const selected=items.findIndex(item=>item.selected);if(selected>=0)setActive(sel.findIndex(a=>Number(a.dataset.i)===selected));m.focus({preventScroll:true});}
  setTimeout(()=>document.addEventListener("pointerdown",popMenuOutsidePointer,true),0);
}

/* module-function:popMenuOwnsTarget */
function popMenuOwnsTarget(target){const menu=document.getElementById("popmenu");return !!(menu?.contains(target)||_popAnchor?.contains(target));}

/* module-function:popMenuOutsidePointer */
function popMenuOutsidePointer(event){if(popMenuOwnsTarget(event.target))return;closePop(event);}

/* module-function:closePop */
function closePop(event){ if(_runtimeCselCleanup){const cleanup=_runtimeCselCleanup;_runtimeCselCleanup=null;cleanup();}const m=document.getElementById("popmenu"),anchor=_popAnchor,settingsMenu=!!(m?.classList.contains("settings-select-menu")||m?.classList.contains("channel-account-menu")),capabilitySearch=!!(m&&m.classList.contains("chat-add-menu"));if(event&&capabilitySearch&&_conversationCapabilitySearch){const box=conversationInputElement(_conversationCapabilitySearch.surface);if(box&&(event.target===box||box.contains(event.target)))return;}if(m)m.remove(); setMenuTriggerActive(anchor,false);_popAnchor=null; document.removeEventListener("click",closePop);document.removeEventListener("pointerdown",popMenuOutsidePointer,true); if(_popKey){ document.removeEventListener("keydown",_popKey); _popKey=null; }if(capabilitySearch)endConversationCapabilitySearch(true);if(settingsMenu&&!event&&anchor?.isConnected)anchor.focus({preventScroll:true}); }

/* module-function:closeTransientMenus */
function closeTransientMenus(){closePop();}

/* module-function:csel */
function csel(id, items, value, onpick, options){
  _csel[id]={items,onpick,options:options||{}};
  const cur=items.find(i=>!i.head&&String(i.value)===String(value==null?"":value));
  return `<button type="button" class="csel" id="${id}" data-menu-trigger="field" aria-haspopup="menu" aria-expanded="false"${options?.disabled?' disabled aria-disabled="true"':''} data-value="${value==null?"":value}" onclick="cselOpen(event,'${id}')"><span class="cv">${esc(cur?cur.label:"—")}</span>${ICON("chev")}</button>`;
}

/* module-function:modelControlLoading */
function modelControlLoading(kind){return `<span class="csel model-control-loading ${kind}" aria-hidden="true"><span></span></span>`;}

/* module-function:modelCsel */
function modelCsel(id,items,value,onpick,options={}){if(!S.modelCatalogReady||S.channelUsageLoading&&!S.channelUsage)return modelControlLoading("model");return csel(id,items,value,onpick,{...options,menuVariant:"modelSelect",modelGuide:true});}

/* module-function:effortCsel */
function effortCsel(id,items,value,onpick,options={}){if(!S.modelCatalogReady)return modelControlLoading("effort");return csel(id,items,value,onpick,{...options,menuVariant:"effortSelect"});}

/* module-function:cselOpen */
function cselOpen(e,id){ const cfg=_csel[id]; if(!cfg||cfg.options.disabled||e.currentTarget.disabled) return;
  const current=e.currentTarget.dataset.value||"";
  let source=cfg.items;
  if(cfg.options.modelGuide){
    const usable=source.filter(item=>!item.head&&item.value!=null&&String(item.value).split("::").pop()!=="");
    if(!usable.length){const split=current.indexOf("::");openModelChannelGuide({reason:"model",channelId:split>=0?current.slice(0,split):null,model:split>=0?current.slice(split+2):""});return;}
    const allowed=new Set(usable),next=[];let pendingHead=null;
    source.forEach(item=>{if(item.head){pendingHead=item;return;}if(!allowed.has(item))return;if(pendingHead){next.push(pendingHead);pendingHead=null;}next.push(item);});source=next;
  }
  const menuItems=source.map(it=>it.head?{head:true,label:it.label,provider:it.provider}:{label:it.label,labelClass:it.labelClass||"",selected:String(it.value)===String(current),disabled:!!it.disabled,fn:()=>{
    if(it.disabled)return;
    if(_csel[id]?.options.disabled||document.getElementById(id)?.disabled)return;
    if(cfg.options.modelGuide){const value=String(it.value||''),split=value.indexOf('::');if(split<0||!ensureAgentSelection({channelId:value.slice(0,split),model:value.slice(split+2)}))return;}
    const b=document.getElementById(id); if(b){ b.dataset.value=(it.value==null?"":it.value); const cv=b.querySelector(".cv"); if(cv) cv.textContent=it.label; }
    if(cfg.onpick) cfg.onpick(it.value); }});
  if(cfg.options.modelGuide&&!allSupportedAgentChannelsReady())menuItems.push({label:"更多模型",fn:()=>openAgentChannels()});
  const menuConfig={variant:cfg.options.menuVariant||"default"};
  if(cfg.options.menuAlign)menuConfig.align=cfg.options.menuAlign;
  openMenu(e.currentTarget,menuItems,menuConfig);
}

/* module-function:updateCsel */
function updateCsel(id,items,value){ const cfg=_csel[id];if(cfg)cfg.items=items;const b=document.getElementById(id);if(!b)return;b.dataset.value=value==null?"":value;const cur=items.find(x=>!x.head&&String(x.value||"")===String(value||"")),cv=b.querySelector(".cv");if(cv)cv.textContent=cur?cur.label:"—"; }

// Render closures read the active chat/editor; no second source of model preferences.
const _runtimeCselConfigs=new Map();
let _runtimeCselCleanup=null;

/* module-function:runtimeCselState */
function runtimeCselState(id,options=null){
  const cfg=options||_runtimeCselConfigs.get(id),state=cfg?.getState?.()||{};
  const models=(state.models||[]).filter(item=>item.head||(item.value!=null&&String(item.value).includes('::')&&String(item.value).slice(String(item.value).indexOf('::')+2)));
  const efforts=(state.efforts||[]).filter(item=>!item.head&&item.value!=null&&String(item.value)!=='');
  const selected=efforts.find(item=>String(item.value)===String(state.effort)),fallback=efforts.find(item=>String(item.value)===String(state.defaultEffort))||efforts.find(item=>item.value==='high')||efforts[Math.floor(efforts.length/2)];
  return {...state,effort:selected?.value??fallback?.value??'',effortLabel:state.effortLabel||(state.efforts||[]).find(item=>String(item.value||'')==='')?.label,models,efforts,disabled:!!(cfg?.disabled||state.disabled),cfg};
}

/* module-function:runtimeCsel */
function runtimeCsel(id,options){
  _runtimeCselConfigs.set(id,options);
  const state=runtimeCselState(id);
  if(!S.modelCatalogReady&&!state.preview)return modelControlLoading('runtime');if(state.loading)return modelControlLoading('runtime');const model=state.models.find(item=>!item.head&&String(item.value)===String(state.value)),effort=state.efforts.find(item=>String(item.value)===String(state.effort)),label=effort?.label||state.effortLabel||'模型默认';
  return `<button type="button" class="csel runtime-csel" id="${esc(id)}" data-menu-trigger="quiet" aria-haspopup="dialog" aria-expanded="false" aria-label="模型与思考强度：${esc(model?.label||state.modelLabel||'暂无可用模型')}，${esc(label)}"${state.disabled?' disabled aria-disabled="true"':''} onclick="runtimeCselOpen(event,'${esc(id)}')"><span class="runtime-model">${esc(model?.label||state.modelLabel||'暂无可用模型')}</span><span class="runtime-effort">${esc(label)}</span>${ICON('chev')}</button>`;
}

/* module-function:runtimeCselOpen */
function runtimeCselOpen(event,id){
  event.preventDefault();event.stopPropagation();
  let state=runtimeCselState(id);if(state.disabled||event.currentTarget.disabled)return;
  if(!state.models.some(item=>!item.head)){const value=String(state.value||''),split=value.indexOf('::');openModelChannelGuide({reason:'model',channelId:split>=0?value.slice(0,split):null,model:split>=0?value.slice(split+2):''});return;}
  if(document.getElementById('popmenu')&&_popAnchor===event.currentTarget){closePop();return;}
  closePop();
  const menu=document.createElement('div');menu.id='popmenu';menu.className='runtime-popover';menu.setAttribute('role','dialog');menu.setAttribute('aria-label','模型与思考强度');document.body.appendChild(menu);
  _popAnchor=event.currentTarget;setMenuTriggerActive(_popAnchor,true);_popAnchor.setAttribute('aria-haspopup','dialog');
  let view='effort',pending=false,closed=false;
  const originConfig=state.cfg,read=()=>runtimeCselState(id,originConfig),anchor=()=>document.getElementById(id);
  const updateTrigger=(restore=false)=>{const current=anchor(),s=restore?runtimeCselState(id):read();if(!current)return;const m=s.models.find(item=>!item.head&&String(item.value)===String(s.value)),e=s.efforts.find(item=>String(item.value)===String(s.effort)),label=e?.label||s.effortLabel||'模型默认';const choosing=!restore&&view==='effort'&&!closed,modelText=current.querySelector('.runtime-model'),effortText=current.querySelector('.runtime-effort');const displayed=choosing?'选择强度':m?.label||s.modelLabel||'暂无可用模型';if(modelText.textContent!==displayed)modelText.textContent=displayed;if(effortText.textContent!==label)effortText.textContent=label;effortText.hidden=choosing;current.setAttribute('aria-label',choosing?'选择强度':`模型与思考强度：${m?.label||s.modelLabel||'暂无可用模型'}，${label}`);};
  const position=()=>{if(closed)return;const current=anchor();if(!current){closePop();return;}_popAnchor=current;setMenuTriggerActive(current,true);current.setAttribute('aria-haspopup','dialog');updateTrigger();const rect=current.getBoundingClientRect(),gap=8,margin=8,w=menu.offsetWidth,h=menu.offsetHeight;menu.style.left=Math.max(margin,Math.min((rect.left+rect.right-w)/2,window.innerWidth-w-margin))+'px';const above=rect.top-h-gap;menu.style.top=(above>=margin?above:Math.min(rect.bottom+gap,Math.max(margin,window.innerHeight-h-margin)))+'px';};
  const submit=async(kind,value)=>{
    const current=read();if(closed||pending||current.disabled||anchor()?.disabled){if(current.disabled)closePop();return;}
    if(kind==='effort'&&!current.efforts.some(item=>String(item.value)===String(value)))return;
    if(kind==='model'&&!current.models.some(item=>!item.head&&!item.disabled&&String(item.value)===String(value)))return;
    pending=true;menu.setAttribute('aria-busy','true');menu.querySelectorAll('button,input').forEach(el=>el.disabled=true);
    try{await (kind==='model'?current.cfg.onModel?.(value):current.cfg.onEffort?.(value));if(closed)return;view='effort';pending=false;if(read().disabled){closePop();return;}updateTrigger();render();position();menu.querySelector(kind==='effort'?'.runtime-range':'.runtime-model-switch')?.focus({preventScroll:true});}
    catch(error){if(!closed){render();const status=menu.querySelector('.runtime-selection-error');if(status)status.textContent='设置未保存，请重试。';}}
    finally{pending=false;if(!closed){menu.removeAttribute('aria-busy');menu.querySelectorAll('button,input').forEach(el=>el.disabled=read().disabled||el.dataset.fixedDisabled==='true');}}
  };
  const preview=index=>{const s=read(),i=Math.max(0,Math.min(index,s.efforts.length-1));menu.querySelector('.runtime-strength-value').textContent=s.efforts[i]?.label||'模型默认';const input=menu.querySelector('.runtime-range');if(input){input.value=String(i);input.setAttribute('aria-valuetext',s.efforts[i]?.label||'');}const pct=s.efforts.length>1?i/(s.efforts.length-1):0;menu.querySelector('.runtime-track-fill').style.width=`calc(14px + (100% - 28px) * ${pct})`;menu.querySelector('.runtime-slider-thumb').style.left=`calc(14px + (100% - 28px) * ${pct})`;menu.querySelectorAll('.runtime-slider-tick').forEach((el,j)=>el.classList.toggle('passed',j<=i));};
  function render(){
    if(closed)return;const s=read(),model=s.models.find(item=>!item.head&&String(item.value)===String(s.value)),index=s.efforts.findIndex(item=>String(item.value)===String(s.effort)),value=s.efforts[index]?.label||s.effortLabel||'模型默认',canReset=s.efforts.some(item=>String(item.value)===String(s.defaultEffort));
    if(view==='models'){
      menu.classList.add('runtime-model-list-view');menu.innerHTML=`<div class="runtime-model-title">选择模型</div><div class="runtime-model-list" role="group" aria-label="可用模型">${s.models.map((item,i)=>{
        if(item.head){const logo=item.provider?providerBrandIcon(item.provider):'';return `<div class="runtime-model-channel">${logo?`<span class="runtime-provider-icon" data-provider="${esc(item.provider)}" aria-hidden="true">${logo}</span>`:''}<span>${esc(item.label)}</span></div>`;}
        return `<button type="button" class="runtime-model-option${String(item.value)===String(s.value)?' selected':''}" data-model-index="${i}"${item.disabled?' disabled data-fixed-disabled="true"':''} aria-pressed="${String(item.value)===String(s.value)}"><span>${esc(item.label)}</span><span class="runtime-model-check" aria-hidden="true">${String(item.value)===String(s.value)?ICON('check'):''}</span></button>`;
      }).join('')}${!allSupportedAgentChannelsReady()?'<button type="button" class="runtime-more-models">更多模型</button>':''}</div><p class="runtime-selection-error" role="status"></p>`;
      menu.querySelectorAll('[data-model-index]').forEach(el=>el.onclick=()=>submit('model',s.models[Number(el.dataset.modelIndex)]?.value));
      const more=menu.querySelector('.runtime-more-models');if(more)more.onclick=()=>{closePop();openAgentChannels();};
    }else{
      menu.classList.remove('runtime-model-list-view');menu.innerHTML=`<div class="runtime-effort-header${canReset?' has-reset':''}"><button type="button" class="runtime-model-switch" aria-label="切换模型，当前${esc(model?.label||s.modelLabel||'暂无可用模型')}"><span class="runtime-strength-value${s.efforts.length?' adjustable':''}" aria-live="polite">${esc(value)}</span><span class="runtime-model-line"><span>${esc(model?.label||s.modelLabel||'暂无可用模型')}</span>${ICON('chev')}</span></button></div>${canReset?`<button type="button" class="runtime-reset" aria-label="恢复模型默认思考强度" title="恢复模型默认思考强度"><svg class="i runtime-reset-glyph" aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M13.3326 7.33333C13.2748 6.11022 12.7979 4.94424 11.982 4.03121C11.1661 3.11819 10.0608 2.51373 8.85185 2.31935C7.6429 2.12497 6.40388 2.3525 5.34288 2.96375C4.28188 3.57499 3.46351 4.53271 3.02523 5.67606C2.58694 6.81941 2.55543 8.07876 2.93599 9.2426C3.31654 10.4064 4.08599 11.4039 5.11509 12.0674C6.1442 12.731 7.37029 13.0202 8.58745 12.8865C9.80461 12.7528 10.9387 12.2044 11.7993 11.3333M8.66593 7.33333H13.3326V2.66666" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg></button>`:''}${s.efforts.length>1?`<div class="runtime-slider"><div class="runtime-track" aria-hidden="true"></div><div class="runtime-track-fill" aria-hidden="true"></div>${s.efforts.map((item,i)=>`<span class="runtime-slider-tick" aria-hidden="true" style="left:calc(14px + (100% - 28px) * ${i/(s.efforts.length-1)})"></span>`).join('')}<span class="runtime-slider-thumb" aria-hidden="true"></span><input type="range" class="runtime-range" min="0" max="${s.efforts.length-1}" step="1" value="${Math.max(0,index)}" aria-label="思考强度" aria-valuetext="${esc(value)}"></div>`:''}<p class="runtime-selection-error" role="status"></p>`;
      menu.querySelector('.runtime-model-switch').onclick=()=>{if(read().disabled)return;view='models';render();position();const selected=menu.querySelector('.runtime-model-option.selected')||menu.querySelector('.runtime-model-option');selected?.focus({preventScroll:true});selected?.scrollIntoView({block:'nearest'});};
      const reset=menu.querySelector('.runtime-reset');if(reset)reset.onclick=()=>submit('effort',read().defaultEffort);
      const range=menu.querySelector('.runtime-range');if(range){preview(Math.max(0,index));range.oninput=()=>preview(Number(range.value));range.onchange=()=>submit('effort',read().efforts[Number(range.value)]?.value);range.onkeydown=e=>{const s=read(),current=Number(range.value),next={ArrowLeft:current-1,ArrowDown:current-1,ArrowRight:current+1,ArrowUp:current+1,Home:0,End:s.efforts.length-1}[e.key];if(next==null)return;e.preventDefault();const i=Math.max(0,Math.min(next,s.efforts.length-1));preview(i);submit('effort',s.efforts[i]?.value);};}
    }
    menu.querySelectorAll('button,input').forEach(el=>el.disabled=s.disabled||pending||el.disabled);position();
  }
  _popKey=e=>{if(e.key==='Escape'){e.preventDefault();const target=anchor();closePop();target?.focus();return;}if(e.key==='Tab'){const controls=[...menu.querySelectorAll('button:not(:disabled),input:not(:disabled)')];const first=controls[0],last=controls[controls.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}if(view==='models'&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){const rows=[...menu.querySelectorAll('.runtime-model-option:not(:disabled),.runtime-more-models')],index=rows.indexOf(document.activeElement);if(!rows.length)return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?rows.length-1:(index+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length;rows[next].focus();}};
  document.addEventListener('keydown',_popKey);document.addEventListener('pointerdown',popMenuOutsidePointer,true);window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
  const observer=new MutationObserver(()=>{if(closed)return;if(!anchor()||read().disabled||anchor().disabled){closePop();return;}position();});observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','inert']});
  _runtimeCselCleanup=()=>{closed=true;observer.disconnect();updateTrigger(true);window.removeEventListener('resize',position);window.removeEventListener('scroll',position,true);};
  render();menu.querySelector('.runtime-range,.runtime-model-switch')?.focus({preventScroll:true});
}
