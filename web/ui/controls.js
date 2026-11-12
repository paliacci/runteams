/* Shared dialogs, menus, model/effort selectors and toasts. Main session owns this file.
 * Classic script: uses host state/helpers at call time; no duplicate application state. */

/* module-function:toast */
function toast(msg, kind, messageKey, messageVars){
  kind=kind||"info";
  let host=document.getElementById("toasts");
  if(!host){ host=document.createElement("div"); host.id="toasts"; host.className="toasts"; document.body.appendChild(host); }
  const t=document.createElement("div"); t.className="toast "+kind;
  t.innerHTML=`${ICON(kind==="ok"?"check":(kind==="err"?"x":"info"))}<span${messageKey?` data-app-i18n="${esc(messageKey)}"${messageVars?` data-app-i18n-vars="${esc(JSON.stringify(messageVars))}"`:''}`:''}>${esc(msg)}</span>`;
  host.appendChild(t);
  if(messageKey)window.RunTeamsLocale?.apply(t);
  setTimeout(()=>{ t.style.opacity="0"; t.style.transform="translateY(8px)"; setTimeout(()=>t.remove(),260); }, 2600);
}

/* module-function:openModal */
function openModal(html){ closeModal(); const d=document.createElement("div"); d.id="modalHost"; d.innerHTML=html; d.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing&&!event.defaultPrevented){const close=d.querySelector('.modal-x:not([disabled])');if(close){event.preventDefault();event.stopPropagation();close.click();}}}); document.body.appendChild(d); return d; }

/* module-function:dialogMarkup */
function dialogMarkup(opts={}){
  const closeAction=opts.closeAction||"closeModal()",scrimHandler=opts.scrimHandler||(opts.closeOnScrim===false?"":`if(event.target===this)${closeAction}`),scrimAttr=scrimHandler?` onclick="${scrimHandler}"`:"";
  const classes=["modal","dialog-shell",opts.className||""].filter(Boolean).join(" "),attrs=opts.attrs?` ${opts.attrs}`:"";
  const header=opts.headerHtml!=null?`<div class="mh ${opts.headerClass||""}">${opts.headerHtml}</div>`:(opts.title!=null?`<div class="mh ${opts.headerClass||""}">${opts.leading||""}<div class="tt">${opts.titleKey?`<span data-app-i18n="${esc(opts.titleKey)}"${opts.titleVars?` data-app-i18n-vars="${esc(JSON.stringify(opts.titleVars))}"`:""}>${esc(opts.title)}</span>`:esc(opts.title)}${opts.subtitle?`<div class="s"${opts.subtitleKey?` data-app-i18n="${esc(opts.subtitleKey)}"${opts.subtitleVars?` data-app-i18n-vars="${esc(JSON.stringify(opts.subtitleVars))}"`:""}`:""}>${esc(opts.subtitle)}</div>`:""}</div>${opts.headerActions||""}${opts.showClose===false?"":`<button type="button" class="x modal-x" aria-label="关闭${esc(opts.title||'弹窗')}"${opts.closeLabelKey?` data-app-i18n-aria-label="${esc(opts.closeLabelKey)}"`:""} onclick="${closeAction}">${ICON("x")}</button>`}</div>`:"");
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
function confirmModal(title, msg, onOk, danger, labels={}){
  const actionLabel=labels.action||(danger&&/删除/.test(String(title||""))?"删除":"确认");
  const i18n=(key,attribute="data-app-i18n")=>key?` ${attribute}="${esc(key)}"`:"";
  const trigger=labels.focusCancel?document.activeElement:null;
  const vars=labels.titleVars?` data-app-i18n-vars="${esc(JSON.stringify(labels.titleVars))}"`:"";
  const attrs=labels.focusCancel?`role="dialog" aria-modal="true" aria-label="${esc(title)}"${i18n(labels.titleKey,"data-app-i18n-aria-label")}${vars}`:"";
  const d=openDialog({className:"modal-confirm",title,titleKey:labels.titleKey,titleVars:labels.titleVars,showClose:false,attrs,headerActions:`<button type="button" class="x modal-x" aria-label="${esc(labels.close||"关闭弹窗")}"${i18n(labels.closeKey,"data-app-i18n-aria-label")} onclick="closeModal()">${ICON("x")}</button>`,body:`<div class="modal-copy"${i18n(labels.messageKey)}${labels.messageVars?` data-app-i18n-vars="${esc(JSON.stringify(labels.messageVars))}"`:""}>${esc(msg)}</div>`,footer:`<div class="grow"></div><button class="btn" data-confirm-cancel onclick="closeModal()"${i18n(labels.cancelKey)}>${esc(labels.cancel||"取消")}</button><button class="btn ${danger?'danger':'pri'}" id="_ok"${i18n(labels.actionKey)}>${esc(actionLabel)}</button>`});
  window.RunTeamsLocale?.apply(d);
  d.querySelector("#_ok").onclick=()=>{ closeModal(); onOk&&onOk(); };
  if(labels.focusCancel){
    const cancel=d.querySelector("[data-confirm-cancel]");
    const close=d.querySelector(".modal-x");
    const dismiss=()=>{closeModal();(labels.returnFocus?.()||trigger)?.focus({preventScroll:true});};
    if(cancel)cancel.onclick=dismiss;
    if(close)close.onclick=dismiss;
    d.addEventListener("click",event=>{if(event.target===d.firstElementChild)dismiss();});
    cancel?.focus();
  }
}

/* module-function:inputModal */
function inputModal(opts, onOk){
  const marker=key=>key?` data-app-i18n="${esc(key)}"`:"";
  const d=openDialog({className:`modal-input ${opts.variant==="rename"?"modal-rename":""}`,title:opts.title,titleKey:opts.titleKey,closeLabelKey:opts.closeLabelKey,subtitle:opts.sub,body:`<div class="field"><label for="_v1"${marker(opts.labelKey)}>${esc(opts.label||"名称")}</label><input class="inp" id="_v1" placeholder="${esc(opts.ph1||"")}" value="${esc(opts.v1||"")}"></div>${opts.label2?`<div class="field"><label>${esc(opts.label2)}</label><textarea class="ta" id="_v2" placeholder="${esc(opts.ph2||"")}">${esc(opts.v2||"")}</textarea></div>`:""}`,footer:`<div class="grow"></div><button class="btn" onclick="closeModal()"${marker(opts.cancelKey)}>取消</button><button class="btn pri" id="_ok"${marker(opts.okKey)}>${esc(opts.ok||"保存")}</button>`});
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
function menuItemsMarkup(items){return items.map((it,i)=>it.account?`<div class="channel-menu-account">${it.label?`<div class="channel-menu-email" title="${esc(it.label)}">${esc(it.label)}</div>`:''}${it.plan?`<span class="channel-menu-plan">${esc(it.plan)}</span>`:''}</div>`:it.head?`<div class="menuhead">${it.provider&&providerBrandIcon(it.provider)?`<span class="model-menu-provider-icon">${providerBrandIcon(it.provider)}</span>`:""}<span${it.labelKey?` data-app-i18n="${esc(it.labelKey)}"`:""}>${esc(it.label)}</span>${it.action?`<button type="button" class="menu-head-action" data-menu-head-action="${i}"${it.action.disabled?' disabled':''}>${it.action.icon?ICON(it.action.icon):''}<span${it.action.labelKey?` data-app-i18n="${esc(it.action.labelKey)}"`:""}>${esc(it.action.label)}</span></button>`:""}</div>`:it.divider?`<div class="menu-divider" role="separator"></div>`:it.empty?`<div class="menu-empty ${esc(it.emptyClass||"chat-capability-empty")}" ${it.hidden?'hidden':''}${it.labelKey?` data-app-i18n="${esc(it.labelKey)}"`:''}>${esc(it.label)}</div>`:`<a data-i="${i}" ${it.capability?'data-chat-capability="1"':''}${it.submenu?' aria-haspopup="menu" aria-expanded="false"':''}${it.disabled?' aria-disabled="true" data-disabled="true"':''}${it.help?' data-help="true"':''} data-search="${esc(String(it.searchText||it.label||'').toLowerCase())}"${it.disabled&&it.disabledReason?` title="${esc(it.disabledReason)}" aria-description="${esc(it.disabledReason)}"`:""} class="${it.danger?'danger':''}${it.selected?' selected':''}${it.disabled?' disabled':''}${it.submenu?' has-submenu':''}">${it.swatch?`<i class="menu-swatch column-swatch-${esc(it.swatch)}" aria-hidden="true"></i>`:(it.provider&&providerBrandIcon(it.provider)?`<span class="menu-provider-icon ${providerTone(it.provider)}">${providerBrandIcon(it.provider)}</span>`:(it.iconUrl?`<img class="menu-icon" src="${esc(it.iconUrl)}" alt="">`:(it.iconBox?`<span class="menu-icon menu-vector-icon">${ICON(it.iconBox)}</span>`:(it.icon?ICON(it.icon):""))))}<span class="menu-copy"><b${it.labelClass?` class="${esc(it.labelClass)}"`:""}${it.labelKey?` data-app-i18n="${esc(it.labelKey)}"`:""}>${esc(it.label)}</b>${it.description?`<small${it.descriptionKey?` data-app-i18n="${esc(it.descriptionKey)}"`:""}>${esc(it.description)}</small>`:""}</span><span class="menu-check">${ICON("check")}</span>${it.submenu?`<span class="menu-submenu-arrow" aria-hidden="true">${ICON("chev")}</span>`:""}</a>`).join("");}

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
  const focusMenu=typeof opts.keyboardReturn==='function';
  const restoreFocus=()=>{const target=focusMenu?opts.keyboardReturn():anchor;target?.focus({preventScroll:true});};
  const existing=document.getElementById("popmenu");
  if(existing&&(existing._currentAnchor?.()||_popAnchor)===anchor&&!opts.at){closePop();if(focusMenu)restoreFocus();return;}
  closePop();
  const menuClass=menuVariantClasses(variant),m=createMenuSurface({id:"popmenu",variant});
  m.innerHTML=menuItemsMarkup(items);
  if(variant==='channelAccount'){m.setAttribute('role','menu');m.tabIndex=-1;m.querySelectorAll('a[data-i]').forEach(a=>{a.id='channel_menu_option_'+a.dataset.i;a.setAttribute('role','menuitem');a.tabIndex=-1;});}
  if(variant==='settingsSelect'){m.setAttribute('role','menu');m.tabIndex=-1;m.querySelectorAll('a[data-i]').forEach(a=>{a.id='settings_option_'+a.dataset.i;a.setAttribute('role','menuitemradio');a.setAttribute('aria-checked',String(a.classList.contains('selected')));});}
  if(focusMenu){
    m._currentAnchor=opts.currentAnchor;
    m.setAttribute('role','menu');m.tabIndex=-1;
    for(const attr of ['aria-label','data-app-i18n-aria-label','data-app-i18n-vars']){
      const value=anchor.getAttribute(attr);if(value!==null)m.setAttribute(attr,value);
    }
    m.querySelectorAll('a[data-i], [data-menu-head-action]').forEach((a,i)=>{a.id='popmenu_option_'+i;a.setAttribute('role','menuitem');a.tabIndex=-1;if(a.getAttribute('aria-disabled')==='true')a.addEventListener('pointerdown',event=>event.preventDefault());});
    window.RunTeamsLocale?.apply(m);
  }
  document.body.appendChild(m);
  m._onClose=opts.onClose;
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
  const setActive=(k)=>{ cur=k; sel.forEach((a,j)=>a.classList.toggle("active",j===k));if(focusMenu||variant==='settingsSelect'||variant==='channelAccount'){sel[k]?.scrollIntoView({block:"nearest"});if(sel[k])m.setAttribute('aria-activedescendant',sel[k].id);} };
  items.forEach((item,i)=>{ const it=item.head?item.action:item;if(!it||it.head||it.divider||it.empty||(it.disabled&&(item.head||variant==='settingsSelect'||variant==='workFolder'||variant==='cardContext'))) return; const a=m.querySelector(item.head?`[data-menu-head-action="${i}"]`:`[data-i="${i}"]`);if(!a)return; const k=sel.length; sel.push(a);a.onfocus=()=>setActive(k);
    if(menuClass&&menuClass.includes("chat-add-menu"))a.onmousedown=e=>e.preventDefault();a.onclick=(e)=>{ e.stopPropagation();if(it.disabled){e.preventDefault();return;}if(opts.multi){ it.selected=!it.selected; a.classList.toggle("selected",it.selected); it.fn&&it.fn(it.selected); } else if(it.keepOpen){it.fn&&it.fn(a);}else { closePop(); if(focusMenu)restoreFocus(); it.fn&&it.fn(); } }; a.onmouseenter=()=>{setActive(k);if(it.hoverFn)it.hoverFn(a);};a.onmousemove=()=>setActive(k); });
  _popKey=(e)=>{ if(m._nestedTarget?.(e.target))return;if(variant==='chatAdd'&&(e.isComposing||e.keyCode===229||e.target?.dataset?.composing==='true'))return;if(e.key==="Escape"){e.preventDefault();e.stopPropagation();closePop();restoreFocus();return;}if(variant==='chatAdd'&&m._capabilityPage){
      const rows=[...m.querySelectorAll('a[data-i],.chat-capability-retry')].filter(row=>!row.hidden&&!row.disabled&&row.dataset.disabled!=='true'&&row.dataset.installing!=='1'),index=rows.findIndex(row=>row.classList.contains('active'));
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){if(!rows.length)return;e.preventDefault();const next=rows[(index+(e.key==='ArrowDown'?1:index<0?0:-1)+rows.length)%rows.length];m.querySelectorAll('.active').forEach(row=>row.classList.remove('active'));next.classList.add('active');next.scrollIntoView({block:'nearest'});}
      else if(e.key==='Enter'&&index>=0){e.preventDefault();rows[index].click();}return;
    }const visible=sel.filter(a=>!a.hidden);if(!visible.length)return;const current=visible.indexOf(sel[cur]);
    if(e.key==="Tab"&&(focusMenu||['settingsSelect','channelAccount'].includes(variant))){closePop();if(focusMenu)restoreFocus();return;}
    if(e.key==="ArrowDown"){ e.preventDefault();const next=visible[(current+1)%visible.length];setActive(sel.indexOf(next)); }
    else if(e.key==="ArrowUp"){ e.preventDefault();const next=visible[(current-1+visible.length)%visible.length];setActive(sel.indexOf(next)); }
    else if(e.key==="Enter"||e.key===" "&&(focusMenu||variant==="channelAccount")){ if(cur>=0&&!sel[cur].hidden){ e.preventDefault(); sel[cur].click(); } }
    };
  document.addEventListener("keydown",_popKey);
  if(variant==='settingsSelect'){const selected=items.findIndex(item=>item.selected);if(selected>=0)setActive(sel.findIndex(a=>Number(a.dataset.i)===selected));m.focus({preventScroll:true});}
  if(focusMenu){setActive(0);m.focus({preventScroll:true});}
  if(opts.dismissOnScroll){
    m._dismissOnScroll=event=>{
      if(!event.target.matches?.(opts.dismissOnScroll))return;
      const returnFocus=focusMenu&&m.contains(document.activeElement);
      closePop(event);
      if(returnFocus)restoreFocus();
    };
    document.addEventListener("scroll",m._dismissOnScroll,true);
  }
  setTimeout(()=>document.addEventListener("pointerdown",popMenuOutsidePointer,true),0);
}

/* module-function:popMenuOwnsTarget */
function popMenuOwnsTarget(target){const menu=document.getElementById("popmenu");return !!(menu?.contains(target)||menu?._nestedTarget?.(target)||(menu?._currentAnchor?.()||_popAnchor)?.contains(target));}

/* module-function:popMenuOutsidePointer */
function popMenuOutsidePointer(event){if(popMenuOwnsTarget(event.target))return;closePop(event);}

/* module-function:closePop */
function closePop(event){ if(_runtimeCselCleanup){const cleanup=_runtimeCselCleanup;_runtimeCselCleanup=null;cleanup();}const m=document.getElementById("popmenu"),anchor=m?._currentAnchor?.()||_popAnchor,settingsMenu=!!(m?.classList.contains("settings-select-menu")||m?.classList.contains("channel-account-menu")),capabilitySearch=!!(m&&m.classList.contains("chat-add-menu"));if(event&&capabilitySearch&&_conversationCapabilitySearch){const box=conversationInputElement(_conversationCapabilitySearch.surface);if(box&&(event.target===box||box.contains(event.target)))return;}if(m?._dismissOnScroll)document.removeEventListener("scroll",m._dismissOnScroll,true);if(m)m.remove(); setMenuTriggerActive(anchor,false);_popAnchor=null; document.removeEventListener("click",closePop);document.removeEventListener("pointerdown",popMenuOutsidePointer,true); if(_popKey){ document.removeEventListener("keydown",_popKey); _popKey=null; }if(capabilitySearch)endConversationCapabilitySearch(true);if(settingsMenu&&!event&&anchor?.isConnected)anchor.focus({preventScroll:true});if(m?._onClose){const onClose=m._onClose;delete m._onClose;onClose();} }

/* module-function:closeTransientMenus */
function closeTransientMenus(){closePop();}

/* module-function:csel */
function csel(id, items, value, onpick, options){
  _csel[id]={items,onpick,options:options||{}};
  const cur=items.find(i=>!i.head&&String(i.value)===String(value==null?"":value));
  return `<button type="button" class="csel" id="${id}" data-menu-trigger="field" aria-haspopup="menu" aria-expanded="false"${options?.disabled?' disabled aria-disabled="true"':''} data-value="${value==null?"":value}" onclick="cselOpen(event,'${id}')"><span class="cv"${cur?.labelKey?` data-app-i18n="${esc(cur.labelKey)}"`:""}>${esc(cur?cur.label:"—")}</span>${ICON("chev")}</button>`;
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
  const menuItems=source.map(it=>it.head?{head:true,label:it.label,provider:it.provider}:{label:it.label,labelKey:it.labelKey,labelClass:it.labelClass||"",selected:String(it.value)===String(current),disabled:!!it.disabled,fn:()=>{
    if(it.disabled)return;
    if(_csel[id]?.options.disabled||document.getElementById(id)?.disabled)return;
    if(cfg.options.modelGuide){const value=String(it.value||''),split=value.indexOf('::');if(split<0||!ensureAgentSelection({channelId:value.slice(0,split),model:value.slice(split+2)}))return;}
    const b=document.getElementById(id); if(b){ b.dataset.value=(it.value==null?"":it.value); const cv=b.querySelector(".cv"); if(cv) setCselLabel(cv,it); }
    if(cfg.onpick) cfg.onpick(it.value); }});
  if(cfg.options.modelGuide&&!allSupportedAgentChannelsReady())menuItems.push({label:"更多模型",fn:()=>openAgentChannels()});
  const menuConfig={variant:cfg.options.menuVariant||"default"};
  if(cfg.options.menuAlign)menuConfig.align=cfg.options.menuAlign;
  openMenu(e.currentTarget,menuItems,menuConfig);
}

function setCselLabel(node,item){
  node.textContent=item?.label??"—";
  if(item?.labelKey){node.dataset.appI18n=item.labelKey;window.RunTeamsLocale?.apply(node);}
  else node.removeAttribute("data-app-i18n");
}

/* module-function:updateCsel */
function updateCsel(id,items,value){ const cfg=_csel[id];if(cfg)cfg.items=items;const b=document.getElementById(id);if(!b)return;b.dataset.value=value==null?"":value;const cur=items.find(x=>!x.head&&String(x.value||"")===String(value||"")),cv=b.querySelector(".cv");if(cv)setCselLabel(cv,cur); }

// Render closures read the active chat/editor; no second source of model preferences.
const _runtimeCselConfigs=new Map();
let _runtimeCselCleanup=null;

/* module-function:runtimeCselState */
function runtimeCselState(id,options=null){
  const cfg=options||_runtimeCselConfigs.get(id),state=cfg?.getState?.()||{};
  const models=(state.models||[]).filter(item=>item.head||(item.value!=null&&String(item.value).includes('::')&&String(item.value).slice(String(item.value).indexOf('::')+2)));
  const efforts=(state.efforts||[]).filter(item=>!item.head&&item.value!=null&&String(item.value)!=='');
  const selected=efforts.find(item=>String(item.value)===String(state.effort)),fallback=efforts.find(item=>String(item.value)===String(state.defaultEffort))||efforts.find(item=>item.value==='high')||efforts[Math.floor(efforts.length/2)];
  return {...state,effort:selected?.value??fallback?.value??'',effortLabelValue:state.effort,effortLabel:state.effortLabel||(state.efforts||[]).find(item=>String(item.value||'')==='')?.label,models,efforts,disabled:!!(cfg?.disabled||state.disabled),cfg};
}

function runtimeModelCopy(state){
  const model=state.models.find(item=>!item.head&&String(item.value)===String(state.value));
  const name=model?.label||state.modelLabel;
  if(name){
    if(state.status==='disconnected')return {key:'runtimeSelector.disconnectedModel',text:`${name}（未连接）`,vars:{name}};
    if(state.status==='removed')return {key:'runtimeSelector.unavailableModel',text:`${name}（不可用）`,vars:{name}};
    return {text:name};
  }
  return state.modelLabelKey?{key:state.modelLabelKey,text:'模型设置未能读取'}:{key:'runtimeSelector.noModel',text:'暂无可用模型'};
}
function runtimeEffortCopy(state,effort){
  const value=effort?.value||state.effortLabelValue, label=effort?.label||state.effortLabel;
  if(value&&Object.hasOwn(EFFORT_LABELS,value))return {key:`runtimeSelector.level.${value}`,text:label||EFFORT_LABELS[value]};
  if(label&&label!=='模型默认')return {text:label};
  return {key:'runtimeSelector.defaultEffort',text:'模型默认'};
}
function runtimeCopyAttrs(copy,attribute=''){
  return copy.key?` data-app-i18n${attribute}="${esc(copy.key)}"${copy.vars?` data-app-i18n-vars="${esc(JSON.stringify(copy.vars))}"`:''}`:'';
}
function runtimeSetCopy(node,copy,attribute=''){
  if(!node)return;
  const marker='data-app-i18n'+(attribute?'-'+attribute:'');
  if(copy.key){if(node.getAttribute(marker)!==copy.key)node.setAttribute(marker,copy.key);}
  else if(node.hasAttribute(marker))node.removeAttribute(marker);
  if(copy.vars){
    const vars=JSON.stringify(copy.vars);
    if(node.dataset.appI18nVars!==vars)node.dataset.appI18nVars=vars;
  }else if(node.hasAttribute('data-app-i18n-vars'))delete node.dataset.appI18nVars;
  const text=copy.key?(window.RunTeamsLocale?.t(copy.key,copy.vars,copy.text)??copy.text):copy.text;
  if(attribute){if(node.getAttribute(attribute)!==text)node.setAttribute(attribute,text);}
  else if(node.textContent!==text)node.textContent=text;
}

/* module-function:runtimeCsel */
function runtimeCsel(id,options){
  _runtimeCselConfigs.set(id,options);
  const state=runtimeCselState(id,options);
  if((!S.modelCatalogReady&&!state.preview)||state.loading)return RunTeamsStaticPages.runtimePending();
  const model=runtimeModelCopy(state),effort=runtimeEffortCopy(state,state.efforts.find(item=>String(item.value)===String(state.effort))),key=esc(id);
  const content=`<span class="sr-only" id="${key}_title" data-app-i18n="runtimeSelector.title">模型与思考强度</span><span class="runtime-model" id="${key}_model"${runtimeCopyAttrs(model)}>${esc(model.text)}</span><span class="runtime-effort" id="${key}_effort"${runtimeCopyAttrs(effort)}>${esc(effort.text)}</span>`;
  return `<button type="button" class="csel runtime-csel" id="${key}" data-menu-trigger="quiet" aria-haspopup="dialog" aria-expanded="false" aria-labelledby="${key}_title ${key}_model ${key}_effort"${state.saving?' aria-busy="true"':''}${state.disabled?' disabled aria-disabled="true"':''} onclick="runtimeCselOpen(event,'${key}')">${content}${ICON('chev')}</button>`;
}

/* module-function:runtimeCselOpen */
function runtimeCselOpen(event,id){
  event.preventDefault();event.stopPropagation();
  let state=runtimeCselState(id);if(state.saving||state.disabled||event.currentTarget.disabled)return;
  if(!state.models.some(item=>!item.head)){const value=String(state.value||''),split=value.indexOf('::');openModelChannelGuide({reason:'model',channelId:split>=0?value.slice(0,split):null,model:split>=0?value.slice(split+2):''});return;}
  if(document.getElementById('popmenu')&&_popAnchor===event.currentTarget){closePop();return;}
  closePop();
  const menu=document.createElement('div');menu.id='popmenu';menu.className='runtime-popover';menu.setAttribute('role','dialog');menu.setAttribute('aria-label','模型与思考强度');menu.dataset.appI18nAriaLabel='runtimeSelector.title';document.body.appendChild(menu);
  _popAnchor=event.currentTarget;setMenuTriggerActive(_popAnchor,true);_popAnchor.setAttribute('aria-haspopup','dialog');
  let view='effort',pending=false,closed=false;
  const originConfig=state.cfg,read=()=>runtimeCselState(id,originConfig),anchor=()=>document.getElementById(id);
  const updateTrigger=(restore=false)=>{
    const current=anchor(),s=restore?runtimeCselState(id):read();if(!current)return;
    const choosing=!restore&&view==='effort'&&!closed;
    const model=choosing?{key:'runtimeSelector.chooseEffort',text:'选择强度'}:runtimeModelCopy(s);
    const effort=runtimeEffortCopy(s,s.efforts.find(item=>String(item.value)===String(s.effort))),effortText=current.querySelector('.runtime-effort');
    if(!effortText)return;
    runtimeSetCopy(current.querySelector('.runtime-model'),model);
    runtimeSetCopy(effortText,effort);
    effortText.hidden=choosing;
    current.setAttribute('aria-labelledby',choosing?`${id}_model`:`${id}_title ${id}_model ${id}_effort`);
  };
  const position=()=>{if(closed)return;const current=anchor();if(!current){closePop();return;}_popAnchor=current;setMenuTriggerActive(current,true);current.setAttribute('aria-haspopup','dialog');updateTrigger();const rect=current.getBoundingClientRect(),gap=8,margin=8,w=menu.offsetWidth,h=menu.offsetHeight;menu.style.left=Math.max(margin,Math.min((rect.left+rect.right-w)/2,window.innerWidth-w-margin))+'px';const above=rect.top-h-gap;menu.style.top=(above>=margin?above:Math.min(rect.bottom+gap,Math.max(margin,window.innerHeight-h-margin)))+'px';};
  const submit=async(kind,value)=>{
    const current=read();if(closed||pending||current.saving||current.disabled||anchor()?.disabled){if(current.disabled)closePop();return;}
    if(kind==='effort'&&!current.efforts.some(item=>String(item.value)===String(value)))return;
    if(kind==='model'&&!current.models.some(item=>!item.head&&!item.disabled&&String(item.value)===String(value)))return;
    pending=true;menu.setAttribute('aria-busy','true');menu.querySelectorAll('button,input').forEach(el=>el.disabled=true);
    try{
      await (kind==='model'?current.cfg.onModel?.(value):current.cfg.onEffort?.(value));
      if(closed)return;
      if(kind==='model'){
        closePop();
        anchor()?.focus({preventScroll:true});
        return;
      }
      pending=false;
      if(read().disabled){closePop();return;}
      updateTrigger();render();position();
      menu.querySelector('.runtime-range')?.focus({preventScroll:true});
    }
    catch(error){
      if(!closed){
        pending=false;render();
        const copy=error.runtimeRejected?{key:'runtimeSelector.saveRejected',text:'设置未能保存。仍使用上次保存的设置。'}:{key:'runtimeSelector.saveFailed',text:'无法确认设置是否已保存。请重试。'};
        runtimeSetCopy(menu.querySelector('.runtime-selection-error'),copy);
        const retry=view==='models'
          ?menu.querySelector(`[data-model-index="${current.models.findIndex(item=>String(item.value)===String(value))}"]:not(:disabled)`)||menu.querySelector('.runtime-model-option.selected')
          :menu.querySelector('.runtime-range')||menu.querySelector('.runtime-model-switch');
        retry?.focus({preventScroll:true});
      }
    }
    finally{pending=false;if(!closed){menu.removeAttribute('aria-busy');menu.querySelectorAll('button,input').forEach(el=>el.disabled=read().disabled||el.dataset.fixedDisabled==='true');}}
  };
  const preview=index=>{const s=read(),i=Math.max(0,Math.min(index,s.efforts.length-1));const copy=runtimeEffortCopy(s,s.efforts[i]);runtimeSetCopy(menu.querySelector('.runtime-strength-value'),copy);const input=menu.querySelector('.runtime-range');if(input){input.value=String(i);runtimeSetCopy(input,copy,'aria-valuetext');}const pct=s.efforts.length>1?i/(s.efforts.length-1):0;menu.querySelector('.runtime-track-fill').style.width=`calc(14px + (100% - 28px) * ${pct})`;menu.querySelector('.runtime-slider-thumb').style.left=`calc(14px + (100% - 28px) * ${pct})`;menu.querySelectorAll('.runtime-slider-tick').forEach((el,j)=>el.classList.toggle('passed',j<=i));};
  function render(){
    if(closed)return;const s=read(),model=runtimeModelCopy(s),index=s.efforts.findIndex(item=>String(item.value)===String(s.effort)),effort=runtimeEffortCopy(s,s.efforts[index]),canReset=s.efforts.some(item=>String(item.value)===String(s.defaultEffort));
    if(view==='models'){
      menu.classList.add('runtime-model-list-view');menu.innerHTML=`<div class="runtime-model-title" data-app-i18n="runtimeSelector.chooseModel">选择模型</div><div class="runtime-model-list" role="group" aria-label="可用模型" data-app-i18n-aria-label="runtimeSelector.availableModels">${s.models.map((item,i)=>{
        if(item.head){const logo=item.provider?providerBrandIcon(item.provider):'';return `<div class="runtime-model-channel">${logo?`<span class="runtime-provider-icon" data-provider="${esc(item.provider)}" aria-hidden="true">${logo}</span>`:''}<span>${esc(item.label)}</span></div>`;}
        return `<button type="button" class="runtime-model-option${String(item.value)===String(s.value)?' selected':''}" data-model-index="${i}"${item.disabled?' disabled data-fixed-disabled="true"':''} aria-pressed="${String(item.value)===String(s.value)}"><span>${esc(item.label)}</span><span class="runtime-model-check" aria-hidden="true">${String(item.value)===String(s.value)?ICON('check'):''}</span></button>`;
      }).join('')}${!allSupportedAgentChannelsReady()?'<button type="button" class="runtime-more-models" data-app-i18n="runtimeSelector.moreModels">更多模型</button>':''}</div><p class="runtime-selection-error" role="status"></p>`;
      menu.querySelectorAll('[data-model-index]').forEach(el=>el.onclick=()=>submit('model',s.models[Number(el.dataset.modelIndex)]?.value));
      const more=menu.querySelector('.runtime-more-models');if(more)more.onclick=()=>{closePop();openAgentChannels();};
    }else{
      menu.classList.remove('runtime-model-list-view');menu.innerHTML=`<div class="runtime-effort-header${canReset?' has-reset':''}"><button type="button" class="runtime-model-switch" aria-labelledby="runtime_model_switch_label runtime_model_switch_value"><span id="runtime_model_switch_label" class="sr-only" data-app-i18n="runtimeSelector.changeModel">切换模型</span><span class="runtime-strength-value${s.efforts.length?' adjustable':''}" aria-live="polite"${runtimeCopyAttrs(effort)}>${esc(effort.text)}</span><span class="runtime-model-line"><span id="runtime_model_switch_value"${runtimeCopyAttrs(model)}>${esc(model.text)}</span>${ICON('chev')}</span></button></div>${canReset?`<button type="button" class="runtime-reset" aria-label="恢复模型默认思考强度" title="恢复模型默认思考强度" data-app-i18n-aria-label="runtimeSelector.reset" data-app-i18n-title="runtimeSelector.reset"><svg class="i runtime-reset-glyph" aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M13.3326 7.33333C13.2748 6.11022 12.7979 4.94424 11.982 4.03121C11.1661 3.11819 10.0608 2.51373 8.85185 2.31935C7.6429 2.12497 6.40388 2.3525 5.34288 2.96375C4.28188 3.57499 3.46351 4.53271 3.02523 5.67606C2.58694 6.81941 2.55543 8.07876 2.93599 9.2426C3.31654 10.4064 4.08599 11.4039 5.11509 12.0674C6.1442 12.731 7.37029 13.0202 8.58745 12.8865C9.80461 12.7528 10.9387 12.2044 11.7993 11.3333M8.66593 7.33333H13.3326V2.66666" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg></button>`:''}${s.efforts.length>1?`<div class="runtime-slider"><div class="runtime-track" aria-hidden="true"></div><div class="runtime-track-fill" aria-hidden="true"></div>${s.efforts.map((item,i)=>`<span class="runtime-slider-tick" aria-hidden="true" style="left:calc(14px + (100% - 28px) * ${i/(s.efforts.length-1)})"></span>`).join('')}<span class="runtime-slider-thumb" aria-hidden="true"></span><input type="range" class="runtime-range" min="0" max="${s.efforts.length-1}" step="1" value="${Math.max(0,index)}" aria-label="思考强度" data-app-i18n-aria-label="runtimeSelector.effort" aria-valuetext="${esc(effort.text)}"${runtimeCopyAttrs(effort,'-aria-valuetext')}></div>`:''}<p class="runtime-selection-error" role="status"></p>`;
      menu.querySelector('.runtime-model-switch').onclick=()=>{if(read().disabled)return;view='models';render();position();const selected=menu.querySelector('.runtime-model-option.selected')||menu.querySelector('.runtime-model-option');selected?.focus({preventScroll:true});selected?.scrollIntoView({block:'nearest'});};
      const reset=menu.querySelector('.runtime-reset');if(reset)reset.onclick=()=>submit('effort',read().defaultEffort);
      const range=menu.querySelector('.runtime-range');if(range){preview(Math.max(0,index));range.oninput=()=>preview(Number(range.value));range.onchange=()=>submit('effort',read().efforts[Number(range.value)]?.value);range.onkeydown=e=>{const s=read(),current=Number(range.value),next={ArrowLeft:current-1,ArrowDown:current-1,ArrowRight:current+1,ArrowUp:current+1,Home:0,End:s.efforts.length-1}[e.key];if(next==null)return;e.preventDefault();const i=Math.max(0,Math.min(next,s.efforts.length-1));preview(i);submit('effort',s.efforts[i]?.value);};}
    }
    menu.querySelectorAll('button,input').forEach(el=>el.disabled=s.disabled||pending||el.disabled);window.RunTeamsLocale?.apply(menu);position();
  }
  _popKey=e=>{if(e.key==='Escape'){e.preventDefault();const target=anchor();closePop();target?.focus();return;}if(e.key==='Tab'){const controls=[...menu.querySelectorAll('button:not(:disabled),input:not(:disabled)')];const first=controls[0],last=controls[controls.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}if(view==='models'&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){const rows=[...menu.querySelectorAll('.runtime-model-option:not(:disabled),.runtime-more-models')],index=rows.indexOf(document.activeElement);if(!rows.length)return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?rows.length-1:(index+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length;rows[next].focus();}};
  document.addEventListener('keydown',_popKey);document.addEventListener('pointerdown',popMenuOutsidePointer,true);window.addEventListener('resize',position);window.addEventListener('scroll',position,true);window.addEventListener('runteams:languagechange',position);
  const observer=new MutationObserver(()=>{if(closed)return;if(!anchor()||read().disabled||anchor().disabled){closePop();return;}position();});observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','inert']});
  _runtimeCselCleanup=()=>{closed=true;observer.disconnect();updateTrigger(true);window.removeEventListener('resize',position);window.removeEventListener('scroll',position,true);window.removeEventListener('runteams:languagechange',position);};
  render();menu.querySelector('.runtime-range,.runtime-model-switch')?.focus({preventScroll:true});
}
