/* Live attention projection. Work data is memory-only; section visibility is a local display preference. */
(function(global){
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let host,timer,state={scope:null};
  const empty=scope=>({scope,status:'idle',data:null,localStatus:'idle',localData:null,pending:null,due:0,localPending:null,localDue:0});
  function context(){const value=host?.context()||{},scope=value.signedIn?String(value.scope):'';if(state.scope!==scope)state=empty(scope);return value;}
  function items(){
    const rows=[],seen=new Set();
    for(const work of state.status==='ready'?state.data.work_items:[]){
      if(!['needs_approval','needs_human'].includes(work.state))continue;
      rows.push({key:'work:'+work.id,id:work.id,title:work.title||'等待处理',name:work.name,kind:work.kind});seen.add('cloud:'+work.id);
    }
    for(const work of host?.context()?.localReady&&state.localStatus==='ready'?state.localData.work_items:[]){
      if(!['needs_approval','needs_human'].includes(work.state))continue;
      rows.push({key:'device-work:'+work.id,id:work.id,title:work.title||'等待处理',name:work.name,kind:work.kind,storage_scope:'device'});seen.add('device:'+work.id);
    }
    // Interventions already carry an explicit workflow/automation destination.
    for(const item of host?.attention?.()||[]){
      if(item.workflow_id&&seen.has((item.storage_scope==='device'?'device:':'cloud:')+item.workflow_id))continue;
      if(!item.id||!(item.workflow_id||item.automation_id||item.kind==='automation'))continue;
      rows.push({key:'attention:'+item.id,id:String(item.id),attention:true,storage_scope:item.storage_scope,title:item.title||item.reason||'等待处理',name:item.pipeline_name||item.employee_name||item.automation_name||(item.pipeline_id?'流水线':'员工'),kind:item.pipeline_id?'pipeline':'employee'});
    }
    return rows;
  }
  function row(item){return `<button type="button" class="rail-pending-item" data-pending-key="${escape(item.key)}" onclick="RunTeamsSidebar.openItem(this.dataset.pendingKey)"><span class="rail-pending-source-icon" aria-hidden="true">${host.icon(item.kind==='pipeline'?'flow':'users')}</span><span class="rail-pending-copy"><span class="rail-pending-title" title="${escape(item.title)}">${escape(item.title)}</span><small>${escape(item.name)}</small></span></button>`;}
  function contents(){
    const values=items(),value=host.context(),local=!!value.localReady&&!!host.localWork;
    const failed=state.status==='error'||local&&state.localStatus==='error'||!value.deviceWorkOnly&&!value.ready&&state.localStatus==='ready';

    const rows=values.length?values.slice(0,3).map(row).join('')+`<button class="rail-pending-more" type="button" onclick="RunTeamsSidebar.showAll()">查看全部</button>`:'';
    const error=failed?`<div class="rail-pending-error" role="alert"><span>${values.length?'部分待处理暂时无法加载':'待处理暂时无法加载'}</span>${global.RunTeamsLoadFailure.button({variant:'local',compact:true,retry:'RunTeamsSidebar.refresh(true)',busy:!!state.pending||!!state.localPending})}</div>`:'';
    const body=rows+error;
    return `<details class="rail-pending-section" data-rail-section="pending" ${host.sectionOpen()?'open':''}><summary class="rail-section-toggle" onclick="RunTeamsSidebar.toggle(event)"><span>待处理</span><span class="rail-section-chevron" aria-hidden="true">${host.icon('chev')}</span></summary><div class="rail-pending-list">${body}</div></details>`;
  }
  function markup(){const value=context(),html=value.signedIn?contents():'';return `<section data-sidebar-pending ${html?'':'hidden'} aria-label="待处理">${html}</section>`;}
  function paint(){const value=context(),node=document.querySelector('[data-sidebar-pending]');if(!node)return;const html=value.signedIn?contents():'';node.hidden=!html;if(node.innerHTML===html)return;const key=document.activeElement?.dataset?.pendingKey,summary=document.activeElement?.classList?.contains('rail-section-toggle');node.innerHTML=html;if(key)node.querySelector(`[data-pending-key="${CSS.escape(key)}"]`)?.focus({preventScroll:true});else if(summary)node.querySelector('summary')?.focus({preventScroll:true});}
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
  function openItem(key){const value=context(),item=items().find(row=>row.key===key);if(!value.signedIn||!item||(item.storage_scope==='device'?!value.localReady:!value.ready))return;host.closeAll?.();return item.attention?host.openAttention(item.id):item.storage_scope==='device'?host.openWork(item.id,{storage_scope:'device'}):host.openWork(item.id);}
  function showAll(){context();const rows=items();if(rows.length)host.showAll(rows.map(row).join(''));}
  function sync(){context();paint();void refresh();if(!timer)timer=setInterval(()=>{if(!document.hidden){context();paint();void refresh();}},15000);}
  global.RunTeamsSidebar=Object.freeze({connect:value=>{host=value;},markup,sync,refresh,setOpen,toggle,openItem,showAll,closeAll:()=>host.closeAll?.(),
    open:id=>openItem('work:'+id),upgrade:()=>host.upgrade(),reset:()=>{state=empty('');paint();}});
})(window);
