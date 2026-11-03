/* Platform drawer chrome: one UI Kit component for work, settings and automation. */
(()=>{
 'use strict';
 const mounts=new Map();
 function create({onCollapse,kind='work'}){
  const view=RunTeamsUIComponents.createDrawerHeader({onCollapse});
  view.element.classList.add('employee-drawer-header');view.element.dataset.employeeHeader=kind;
  view.collapseButton.setAttribute('aria-label','关闭详情');view.collapseButton.title='关闭详情';
  const setExtras=view.setExtras.bind(view);
  view.setExtras=(extras={})=>{
   setExtras(extras);
   const nodes=view.element.querySelector('.rt-drawer-actions').children;
   (extras.actions||[]).forEach((action,index)=>{
    const node=nodes[index],primary=kind!=='settings'&&action.primary===true;node.classList.toggle('is-primary',primary);node.classList.toggle('rt-primary-button',primary);node.classList.toggle('employee-automation-add',kind==='automation'&&action.id==='new');
    node.toggleAttribute('data-read-pending',action.readPending===true);
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
  if(!entry||entry.owner!==owner){entry?.view.dispose();entry={owner,view:create({...options,kind})};mounts.set(kind,entry);}
  if(node.firstChild!==entry.view.element)node.replaceChildren(entry.view.element);
  entry.view.collapseButton.setAttribute('aria-label',options.collapseLabel||'关闭详情');
  entry.view.setExtras(options.extras);
 }
 function decorate(){
  for(const [kind,entry] of mounts)if(!document.querySelector(`#rgDrawer [data-employee-header-host="${kind}"]`)){entry.view.dispose();mounts.delete(kind);}
  window.RunTeamsCreatorAuthor?.decorateHeader();window.RunTeamsEmployeeAutomation?.decorateHeader();
  window.RunTeamsEmployeeConfiguration?.decorateHeader();
 }
 window.RunTeamsEmployeeDrawerHeader=Object.freeze({create,markup,mount,decorate});
 window.addEventListener('runteams-ui-ready',decorate);
 for(const event of ['runteams:business-scope-will-change','pagehide'])window.addEventListener(event,()=>{for(const entry of mounts.values())entry.view.dispose();mounts.clear();});
})();
