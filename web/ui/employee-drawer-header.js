/* Platform drawer chrome: one UI Kit component for work, settings and automation. */
(()=>{
 'use strict';
 const mounts=new Map();
 function collapseCopy(button,label='关闭详情',key=label==='关闭详情'?'shell.closeDetails':''){
  button.setAttribute('aria-label',label);
  button.title=label;
  for(const marker of ['data-app-i18n-aria-label','data-app-i18n-title']){
   if(key)button.setAttribute(marker,key);else button.removeAttribute(marker);
  }
 }
 function create({onCollapse,kind='work'}){
  const view=RunTeamsUIComponents.createDrawerHeader({onCollapse});
  view.element.classList.add('employee-drawer-header');view.element.dataset.employeeHeader=kind;
  collapseCopy(view.collapseButton);
  const text=view.element.querySelector('.rt-drawer-text');
  const setExtras=view.setExtras.bind(view);
  let backButton;
  view.setExtras=(extras={})=>{
   const back=extras.back;
   setExtras(extras);
   if(back){
    if(!backButton){
     backButton=document.createElement('button');
     backButton.type='button';backButton.className='run-back';
     backButton.innerHTML=ICON('back');
    }
    backButton.title=back.label;
    backButton.setAttribute('aria-label',back.label);
    backButton.setAttribute('data-app-i18n-aria-label',back.labelKey);
    backButton.setAttribute('data-app-i18n-title',back.labelKey);
    backButton.onclick=back.onPress;
    if(!backButton.parentElement)text.before(backButton);
    text.parentElement.hidden=false;
   }else if(backButton){
    backButton.remove();
    backButton.onclick=null;
   }
   if(text)for(const marker of ['data-app-i18n','data-app-i18n-title']){
    if(extras.textKey)text.setAttribute(marker,extras.textKey);else text.removeAttribute(marker);
   }
   const nodes=view.element.querySelector('.rt-drawer-actions').children;
   (extras.actions||[]).forEach((action,index)=>{
    const node=nodes[index],primary=kind!=='settings'&&action.primary===true;node.classList.toggle('is-primary',primary);node.classList.toggle('rt-primary-button',primary);
    node.toggleAttribute('data-read-pending',action.readPending===true);
    for(const marker of ['data-app-i18n','data-app-i18n-title']){
     if(action.labelKey)node.setAttribute(marker,action.labelKey);else node.removeAttribute(marker);
    }
    if(action.platformId)node.id=action.platformId;
    if(action.popup)node.setAttribute('aria-haspopup',action.popup);else node.removeAttribute('aria-haspopup');
    if(typeof action.expanded==='boolean')node.setAttribute('aria-expanded',String(action.expanded));else node.removeAttribute('aria-expanded');
    if(action.icon==='plus'){
     const glyph=document.createElement('span');glyph.className='employee-drawer-action-icon';glyph.setAttribute('aria-hidden','true');glyph.innerHTML=ICON('plus');
     node.replaceChildren(glyph,document.createTextNode(action.label));
    }
   });
  };
  return view;
 }
 const markup=kind=>`<div class="employee-drawer-header-host" data-rt-ui data-employee-header-host="${kind}"></div>`;
 function mount(kind,owner,options){
  const node=document.querySelector(`#rgDrawer [data-employee-header-host="${kind}"]`);
  if(!node||!owner||!window.RunTeamsUIComponents)return;
  let entry=mounts.get(kind);
  if(!entry||entry.owner!==owner){entry?.view.dispose();entry={owner,view:create({kind,...options})};mounts.set(kind,entry);}
  if(node.firstChild!==entry.view.element)node.replaceChildren(entry.view.element);
  collapseCopy(entry.view.collapseButton,options.collapseLabel,options.collapseLabelKey);
  entry.view.setExtras(options.extras);
  window.RunTeamsLocale?.apply(entry.view.element);
 }
 let scrollRegion=null;
 const scrollObserver=new ResizeObserver(()=>updateScrollFade());
 function updateScrollFade(){
  if(!scrollRegion?.isConnected)return;
  const {scrollTop,scrollHeight,clientHeight}=scrollRegion;
  scrollRegion.toggleAttribute('data-fade-top',scrollTop>1);
  scrollRegion.toggleAttribute('data-fade-bottom',scrollHeight-clientHeight-scrollTop>1);
 }
 function decorateScrollFade(){
  const region=document.querySelector('#rgDrawer > .right-detail-drawer > :is(.right-detail-scroll, .right-detail-body:not(.creator-author-body))');
  if(region!==scrollRegion){
   scrollObserver.disconnect();
   scrollRegion?.removeEventListener('scroll',updateScrollFade);
   scrollRegion=region;
   if(region){
    region.addEventListener('scroll',updateScrollFade,{passive:true});
    scrollObserver.observe(region);
    for(const child of region.children)scrollObserver.observe(child);
   }
  }
  updateScrollFade();
 }
 function decorate(){
  decorateScrollFade();
  for(const [kind,entry] of mounts)if(!document.querySelector(`#rgDrawer [data-employee-header-host="${kind}"]`)){entry.view.dispose();mounts.delete(kind);}
  window.RunTeamsCreatorAuthor?.decorateHeader();
  window.RunTeamsEmployeeConfiguration?.decorateHeader();
 }
 const sectionAnimations=new WeakMap();
 function animateSection(body,collapsed){
  const start=body.getBoundingClientRect().height;
  sectionAnimations.get(body)?.cancel();
  sectionAnimations.delete(body);
  body.hidden=false;
  body.inert=collapsed;
  const end=collapsed?0:body.getBoundingClientRect().height;
  const duration=Number(getComputedStyle(body).getPropertyValue('--settings-section-motion-ms'));
  if(!duration||start===end||window.matchMedia('(prefers-reduced-motion: reduce)').matches){
   body.hidden=collapsed;
   body.classList.remove('is-animating');
   return;
  }
  body.classList.add('is-animating');
  const animation=body.animate([{height:start+'px'},{height:end+'px'}],{duration,easing:'ease-in-out',fill:'both'});
  sectionAnimations.set(body,animation);
  animation.onfinish=()=>{
   if(sectionAnimations.get(body)!==animation)return;
   body.hidden=collapsed;
   body.classList.remove('is-animating');
   sectionAnimations.delete(body);
   animation.cancel();
  };
 }
 function section({id,title,body,footer='',headerActions='',collapsedSections,stateKey=id,action,heading='h3',className=''}){
  const collapsed=collapsedSections?.has(stateKey);
  const button=`<button type="button" class="settings-section-toggle" aria-expanded="${!collapsed}" aria-controls="${esc(id)}" data-settings-section-key="${esc(stateKey)}" onclick="${action}(this)">
   <span class="settings-section-title">${title}</span>${ICON('chev')}
  </button>`;
  return `<section class="drawer-settings-section ${className}">
   ${headerActions?'<div class="settings-section-bar">':''}<${heading} class="settings-section-heading">${button}</${heading}>${headerActions?headerActions+'</div>':''}
   <div class="settings-section-body" id="${esc(id)}"${collapsed?' hidden':''}><div class="settings-section-content">${body}${footer}</div></div>
  </section>`;
 }
 function toggleSection(button,collapsedSections){
  const body=document.getElementById(button.getAttribute('aria-controls'));
  if(!body)return;
  const collapsed=button.getAttribute('aria-expanded')==='true';
  button.setAttribute('aria-expanded',String(!collapsed));
  const key=button.dataset.settingsSectionKey;
  if(collapsed)collapsedSections.add(key);else collapsedSections.delete(key);
  animateSection(body,collapsed);
 }
 window.RunTeamsEmployeeDrawerHeader=Object.freeze({create,markup,mount,decorate,section,toggleSection});
 window.addEventListener('runteams-ui-ready',decorate);
 for(const event of ['runteams:business-scope-will-change','pagehide'])window.addEventListener(event,()=>{for(const entry of mounts.values())entry.view.dispose();mounts.clear();});
})();
