/* Live attention projection. Work data is memory-only; section visibility is a local display preference. */
(function(global){
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const painted=new WeakMap();
  const initialSize=3;
  let host,timer,state={scope:null};
  const empty=scope=>({scope,status:'idle',data:null,localStatus:'idle',localData:null,pending:null,due:0,localPending:null,localDue:0,expanded:false});
  function context(){const value=host?.context()||{},scope=value.signedIn?String(value.scope):'';if(state.scope!==scope)state=empty(scope);return value;}
  function workRow({id,title,name,kind,employee,pipeline_name},device=false){
    return {key:(device?'device-work:':'work:')+id,id,title,name,kind,employee,pipeline_name,
      storage_scope:device?'device':undefined};
  }
  function items(){
    const rows=[],seen=new Set();
    for(const work of state.status==='ready'?state.data.work_items:[]){
      if(!['needs_approval','needs_human'].includes(work.state))continue;
      rows.push(workRow(work));seen.add('cloud:'+work.id);
    }
    for(const work of host?.context()?.localReady&&state.localStatus==='ready'?state.localData.work_items:[]){
      if(!['needs_approval','needs_human'].includes(work.state))continue;
      rows.push(workRow(work,true));seen.add('device:'+work.id);
    }
    // Interventions already carry an explicit workflow/automation destination.
    for(const item of host?.attention?.()||[]){
      if(item.workflow_id&&seen.has((item.storage_scope==='device'?'device:':'cloud:')+item.workflow_id))continue;
      if(!item.id||!(item.workflow_id||item.automation_id||item.kind==='automation'))continue;
      const kind=item.kind==='automation'?'automation':item.work_kind||(item.pipeline_id?'pipeline':'employee');
      rows.push({key:'attention:'+item.id,id:String(item.id),attention:true,storage_scope:item.storage_scope,
        title:item.card_title||item.title||item.reason,kind,pipeline_name:item.pipeline_name,
        employee:item.employee||{name:item.employee_name}});
    }
    return rows;
  }
  function row(item){
    const kind=item.kind,title=item.title||'等待处理';
    const titleCopy=item.title?'':' data-app-i18n="sidebarAttention.item" data-app-i18n-title="sidebarAttention.item"';
    const employee=host.employee?.(item.employee)||item.employee;
    const pipeline=kind==='pipeline'&&(item.pipeline_name||item.name);
    const subtitle=[employee?.name||(kind==='employee'?item.name:''),pipeline].filter(Boolean).join('\u2002');
    const fallback={pipeline:'流水线',employee:'员工',automation:'自动化'}[kind]||'员工';
    const nameCopy=subtitle?` title="${escape(subtitle)}"`:` data-app-i18n="sidebarAttention.${kind}"`;
    const icon=employee?.name&&host.avatar?host.avatar(employee):host.icon(kind==='pipeline'?'flow':kind==='automation'?'clock':'user');
    return `<button type="button" class="rail-pending-item" data-pending-key="${escape(item.key)}" onclick="RunTeamsSidebar.openItem(this.dataset.pendingKey)"><span class="rail-pending-source-icon${kind==='pipeline'&&!employee?.name?' is-pipeline-fallback':''}" aria-hidden="true">${icon}</span><span class="rail-pending-copy"><span class="rail-pending-title" title="${escape(title)}"${titleCopy}>${escape(title)}</span><small${nameCopy}>${escape(subtitle||fallback)}</small></span></button>`;}
  function readState(value){
    const local=!!value.localReady&&!!host.localWork;
    const failed=state.status==='error'||local&&state.localStatus==='error'||!value.deviceWorkOnly&&!value.ready&&state.localStatus==='ready';
    const ready=value.deviceWorkOnly?state.localStatus==='ready':state.status==='ready'&&(!local||state.localStatus==='ready');
    return {failed,ready};
  }
  const statusCopy=count=>`<span data-app-i18n="sidebarAttention.${count?'partial':'failed'}">${count?'部分待处理事项无法读取。':'无法读取待处理事项。'}</span>`;
  const emptyCopy='<div class="rail-section-hint" role="status" data-app-i18n="sidebarAttention.empty">没有待处理事项。</div>';
  function contents(values,value){
    const {failed,ready}=readState(value);
    const expanded=state.expanded,shown=expanded?values:values.slice(0,initialSize);
    const more=values.length>initialSize?`<button class="rail-section-more rail-pending-more" type="button" aria-expanded="${expanded}" aria-controls="rail-pending-items" onclick="RunTeamsSidebar.toggleMore()" data-app-i18n="sidebarAttention.${expanded?'showLess':'showMore'}">${expanded?'显示更少':'显示更多'}</button>`:'';
    const error=failed?`<div class="rail-pending-error" role="alert">${statusCopy(values.length)}${global.RunTeamsLoadFailure.button({variant:'local',compact:true,retry:'RunTeamsSidebar.refresh(true)',labelKey:'sidebarAttention.retry',busyLabelKey:'sidebarAttention.loading',busy:!!state.pending||!!state.localPending,focusFallback:'[data-rail-section="pending"] > summary'})}</div>`:'';
    const body=`<div id="rail-pending-items">${shown.map(row).join('')}</div>`+more+error+(!shown.length&&!error&&ready?emptyCopy:'');
    return `<details class="rail-pending-section" data-rail-section="pending" ${host.sectionOpen()?'open':''}><summary class="rail-section-toggle" onclick="RunTeamsSidebar.toggle(event)"><span data-app-i18n="sidebarAttention.title">待处理</span><span class="rail-section-chevron" aria-hidden="true">${host.icon('chev')}</span></summary><div class="rail-pending-list">${body}</div></details>`;
  }
  function markup(){const value=context(),html=value.signedIn?contents(items(),value):'';return `<section data-sidebar-pending ${html?'':'hidden'} aria-label="待处理" data-app-i18n-aria-label="sidebarAttention.title">${html}</section>`;}
  function paint(){
    const value=context(),node=document.querySelector('[data-sidebar-pending]');if(!node)return;
    const values=value.signedIn?items():[];
    const html=value.signedIn?contents(values,value):'';node.hidden=!html;
    if(painted.get(node)===html)return;
    painted.set(node,html);
    if(node.innerHTML===html)return;
    const active=document.activeElement,key=active?.dataset?.pendingKey,inside=node.contains(active);
    const target=key?`[data-pending-key="${CSS.escape(key)}"]`:active?.matches('.rail-pending-more')?'.rail-pending-more':active?.matches('[data-read-retry]')?'[data-read-retry]':'summary';
    node.innerHTML=html;global.RunTeamsLocale?.apply(node);
    if(inside)(node.querySelector(target)||node.querySelector('summary'))?.focus({preventScroll:true});
  }
  async function refresh(force=false){
    const value=context(),local=!!value.localReady&&!!host.localWork;if(!value.signedIn||!value.ready&&!local)return;
    const current=state,scope=state.scope,reads=[];
    // Personal work stays on this executor. Unwired shared work is an error,
    // never a request to the retired backend or the personal work database.
    if(value.cloudWorkUnavailable){current.status='error';paint();}
    for(const device of [...(!value.deviceWorkOnly&&!value.cloudWorkUnavailable&&(value.ready||local)?[false]:[]),...(local?[true]:[])]){
      const pending=device?'localPending':'pending',due=device?'localDue':'due';
      if(current[pending]){reads.push(current[pending]);continue;}
      if(!force&&Date.now()<current[due])continue;
      current[due]=Date.now()+15000;
      current[pending]=(async()=>{try{const result=await (device?host.localWork():host.request('/api/workspace/sidebar'));if(state!==current||context().scope!==scope)return;
        if(result?.schema!=='runteams.sidebar-activity/v1'||!Array.isArray(result.work_items)||result.work_items.some(item=>!['employee','pipeline'].includes(item.kind)||!['ready','running','waiting_retry','needs_approval','needs_human'].includes(item.state)||!Number.isSafeInteger(item.id)||item.id<=0||typeof item.title!=='string'||typeof item.name!=='string'))throw Error('invalid attention projection');
        if(device){if(result.storage_scope!=='device')throw Error('invalid device work projection');current.localData=result;current.localStatus='ready';}
        else{host.authority?.(result);current.data=result;current.status='ready';}
      }catch(error){if(state===current&&context().scope===scope){if(device){current.localData=null;current.localStatus='error';}else{host.authorityFailed?.();current.data=null;current.status='error';}current[due]=Date.now()+30000;}}
      finally{if(state===current){current[pending]=null;paint();}}})();
      reads.push(current[pending]);
    }
    return Promise.all(reads);
  }
  function setOpen(open){context();host.setSectionOpen(!!open);}
  function toggle(event){event.preventDefault();context();setOpen(!host.sectionOpen());const details=event.currentTarget.closest('details');if(details)details.open=host.sectionOpen();}
  function openItem(key){const value=context(),item=items().find(row=>row.key===key);if(!value.signedIn||!item||(item.storage_scope==='device'?!value.localReady:!value.ready))return;return item.attention?host.openAttention(item.id):item.storage_scope==='device'?host.openWork(item.id,{storage_scope:'device'}):host.openWork(item.id);}
  function toggleMore(){
    if(!context().signedIn||items().length<=initialSize)return;
    state.expanded=!state.expanded;
    paint();
    const section=document.querySelector('[data-sidebar-pending]');
    const target=state.expanded?section?.querySelectorAll('[data-pending-key]')[initialSize]:section?.querySelector('.rail-pending-more');
    target?.focus();
  }
  function sync(){context();paint();void refresh();if(!timer)timer=setInterval(()=>{if(!document.hidden){context();paint();void refresh();}},15000);}
  global.RunTeamsSidebar=Object.freeze({connect:value=>{host=value;},markup,sync,refresh,setOpen,toggle,openItem,toggleMore,
    open:id=>openItem('work:'+id),upgrade:()=>host.upgrade(),reset:()=>{state=empty('');paint();}});
})(window);
