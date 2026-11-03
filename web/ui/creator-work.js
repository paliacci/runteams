/* Trusted platform UI only. Author pages never load this file or receive Chat methods. */
(function(){
  'use strict';
  let scope='',chat=null,workContext='',items=[],active=null,reading=null,opening=false,lastRead=0,layoutBusy=false,lastFrame='',generation=0,readError='';
  let header=null,headerOwner=null,headerRevision=null,displayRevision=0,layoutQueued=false,frameRetries=0;
  let discoveryVersion='',lastDiscovery=0;
  const pipelineSlots=new Map();
  const pending=new Map();
  const recovery=new Map();
  const uid=()=>crypto.randomUUID(),token=()=>workspaceAccountCacheToken(),workspace=()=>String(S.activeOrganization||'');
  const bridge=()=>window.RunTeamsWorkHost;
  const call=async value=>{if(!bridge())throw Error('当前窗口无法打开工作内容');return bridge().postMessage(value);};
  const key=id=>token()+':'+String(id),get=id=>pending.get(key(id));
  const checked=value=>{if(value?.error)throw Object.assign(Error(value.error),{creatorRejected:value.state==='rejected'});return value;};
  const error=(p,message='发送状态待核对，请先核对上一条消息。')=>Object.assign(new Error(message),{creatorPending:true,creatorScopeChanged:p.scope!==token()});
  const pipelinePanel=()=>window.RunTeamsSourcePipelines?.workContext()||null;
  const isPipeline=p=>!!p?.context?.source_pipeline_workspace;
  const context=()=>{if(S.booting||S.workspaceSwitchPending||S.pageTransition)return null;const own=pipelinePanel();if(own)return own;const p=S.conversationPanel;return !S.booting&&!S.workspaceSwitchPending&&!S.pageTransition&&activeRailMode()==='assistant'&&(p?.kind==='general'||p?.kind==='employee_design')&&!p.loading&&!p.error&&Number(p.id)>0?p:null;};
  const employeePanel=p=>isPipeline(p)||RunTeamsEmployeeDirectory.employeePanel(p);
  const contextIdentity=p=>JSON.stringify([workspace(),p?.kind,p?.subject_type,
    RunTeamsEmployeeDirectory.referenceKey(RunTeamsEmployeeDirectory.panelReference(p)),
    p?.context?.creator_local_scope,p?.context?.creator_local_source_id,
    p?.context?.creator_employee_source,p?.context?.creator_work_binding,p?.context?.source_pipeline_workspace,
    isPipeline(p)?[S.sourcePipelineWorkspace?.data?.runtime?.applied_revision,S.sourcePipelineWorkspace?.data?.runtime?.generation]:null]);
  const emptyPanel=p=>({chat:Number(p.id),title:'工作台',empty:true});
  const closedPanel=entry=>({...emptyPanel({id:entry.chat}),pipelineWindow:entry.pipelineWindow,
    slotKey:entry.slotKey,slotScope:entry.slotScope,reopenRequired:true});
  // Work records are a platform view; this host only presents author-provided pages.

  const mcpEmployee=employee=>employee?.local_mcp===true||(typeof downloadedEmployeeSummary==='function'&&downloadedEmployeeSummary(employee?.id??S.conversationPanel?.context?.target_employee_id)?.local_mcp===true);
  const folderEmployee=employee=>!mcpEmployee(employee)&&(employee?.schema==='runteams.downloaded-employee/v1'?employee.sdk_resources===true:employee?.source_mode==='folder');
  const needsRecovery=id=>{
    if(!bridge()||isPipeline(S.conversationPanel)||isPipeline(context()))return false;
    if(active?.mcp&&Number(active.chat)===Number(id))return false;
    const p=S.conversationPanel;if(p?.context?.creator_local_source_id)return false;if(Number(p?.id)!==Number(id))return false;
    const employee=RunTeamsEmployeeDirectory.forPanel(p)?.record||p.employee_binding;
    if(mcpEmployee(employee))return false;
    const last=[...(p.messages||[])].reverse().find(m=>m.role==='user');
    return !!active?.id&&!active.mcp||!!last?.metadata?.creator_context_ref;
  };
  const repaint=()=>{if(typeof render==='function')render();};
  async function release(entry){if(!entry?.id)return;try{await call({action:'unmount',id:entry.id,chat_id:entry.chat});}catch(e){} }
  function refreshContext(){
    const p=context(),next=token(),nextContext=contextIdentity(p);
    if(scope!==next||chat!==(p?.id||null)||workContext!==nextContext){
      const old=active;if(old?.id)void call({action:'visibility',id:old.id,chat_id:old.chat,visible:false}).catch(()=>{});
      const nextScope=next+':'+String(S.localLibrary?.cache_scope||S.account?.device_data_scope||'');
      // Only pipeline pages are retained; independent employees keep their lifecycle.
      if(old?.pipelineWindow&&scope===next&&old.slotScope===nextScope&&(!isPipeline(p)||old.pipelineWindow!==RunTeamsSourcePipelines.key(p.context.source_pipeline_workspace)||workContext===nextContext)){
        pipelineSlots.set(old.slotKey,{active:old,items,lastRead,readError});
      }else void release(old);
      for(const [id,saved] of pipelineSlots){
        if(saved.active.slotScope!==nextScope){pipelineSlots.delete(id);void release(saved.active);}
      }
      const slotKey=isPipeline(p)?nextScope+':'+nextContext:null;
      for(const [id,saved] of pipelineSlots)if(isPipeline(p)&&saved.active.pipelineWindow===RunTeamsSourcePipelines.key(p.context.source_pipeline_workspace)&&id!==slotKey){pipelineSlots.delete(id);void release(saved.active);}
      const saved=pipelineSlots.get(slotKey);
      if(saved)pipelineSlots.delete(slotKey);
      if(saved?.active.id)saved.active.recheck=true;
      active=saved?.active||(employeePanel(p)?emptyPanel(p):null);items=saved?.items||[];lastRead=saved?.lastRead||0;readError=saved?.readError||'';
      scope=next;chat=p?.id||null;workContext=nextContext;generation++;lastFrame='';opening=false;discoveryVersion='';lastDiscovery=0;
      if(active&&isPipeline(p))Object.assign(active,{pipelineWindow:RunTeamsSourcePipelines.key(p.context.source_pipeline_workspace),slotKey,slotScope:nextScope});
    }
    return p;
  }
  async function sync(force=false){
    if(S.surface==='source-pipeline'&&!pipelinePanel()){
      try{await window.RunTeamsSourcePipelines?.ensureWorkContext();}catch(e){return;}
    }
    const p=refreshContext();
    if(!p||(!S.localLibrary&&!S.account?.signed_in)||!bridge()||p.kind==='employee_design')return;
    if(!employeePanel(p)&&!active?.id&&!needsRecovery(Number(p.id)))return;
    const epoch=generation;
    if(isPipeline(p)&&active?.recheck){
      const owner=active;if(owner.checking)return;owner.checking=true;
      try{
        const verified=await RunTeamsSourcePipelines.refresh();
        if(!verified||refreshContext()!==p||epoch!==generation||active!==owner)return;
        owner.recheck=false;
      }finally{owner.checking=false;}
    }
    try{await recover(Number(p.id));}catch(e){}
    if(refreshContext()!==p||epoch!==generation||token()!==scope)return;
    void layout();
    // Paused pipelines may retain trusted read-only views; discovery cannot start code.
    if(isPipeline(p)&&S.sourcePipelineWorkspace?.data?.runtime?.status!=='running')return;
    // Discovery can initialize a program to enumerate its pages. A changed
    // process hint must not restart it behind an unresolved or failed page.
    // Explicit opening/retry still performs the original complete discovery.
    if(!force&&(opening||active?.loading||active?.reopenRequired))return;
    if(reading===epoch||!force&&Date.now()-lastRead<4000)return;
    reading=epoch;lastRead=Date.now();
    try{
      // This token only suppresses idle metadata rereads. Opening a menu and
      // every actual mount/tool still use the original complete verification.
      let observed='';
      if(isPipeline(p)||items.some(item=>item.mcp)){
        const hint=await employeeMCPRequest({chat:Number(p.id),pipeline:isPipeline(p),scope:_employeeBusinessScopeSequence,deviceScope:S.localLibrary?.cache_scope||S.account.device_data_scope},null,true);
        if(refreshContext()!==p||epoch!==generation||token()!==scope)return;
        if(hint.schema!=='runteams.mcp-observation/1'||hint.chat_id!==Number(p.id)||hint.owner!==(isPipeline(p)?'pipeline':'employee')||typeof hint.version!=='string')throw Error('工作引用已变化。');
        observed=hint.version;
        // Known menu entries refresh on change or deliberate opening. Idle
        // pages do not rebuild full assets on a timer; an empty menu keeps a
        // bounded probe so a newly provided page can acquire an entry point.
        if(!force&&(!readError||active?.reopenRequired)&&observed===discoveryVersion&&(items.length||Date.now()-lastDiscovery<30000))return;
      }
      const result=await call({action:'discover',workspace_id:workspace(),chat_id:Number(p.id)});
      if(refreshContext()!==p||epoch!==generation||token()!==scope)return;
      if(!Array.isArray(result.items))throw Error('工作内容暂时无法核对');
      if(!active?.reopenRequired)readError='';discoveryVersion=observed;lastDiscovery=Date.now();
      if(active?.readUnavailable){active.readUnavailable=false;lastFrame='';}
      const discovered=result.items.map(item=>({...item,mcp:result.authority==='device-owned-mcp-work'}));
      const changed=JSON.stringify(items)!==JSON.stringify(discovered);items=discovered;
      if(active&&!active.empty&&!items.some(i=>i.installation_id===active.installation&&i.views.some(v=>v.id===active.view))){const old=active;active=employeePanel(p)?emptyPanel(p):null;void release(old);repaint();}
      else if(changed)repaint();
      const choices=items.flatMap(work=>work.views||[]);
      if(!choices.length&&active?.empty&&!active.reopenRequired&&visibleWork()){hide();repaint();}
      if(active?.empty&&!active.reopenRequired&&visibleWork()&&choices.length===1&&!opening){const work=items.find(w=>w.views.includes(choices[0]));await open(work,choices[0]);}
      void layout();
    }catch(e){if(refreshContext()===p&&epoch===generation&&token()===scope){
      readError=e.message||'工作内容暂时无法核对';items=[];
      // An unavailable read says nothing about the author's unsaved document.
      // Keep its instance hidden until the original discovery verifies it again.
      // Context changes, verified removal and native revocation still release it.
      if(active?.id){active.readUnavailable=true;lastFrame='';void layout();}
      else if(!active?.reopenRequired)active=employeePanel(p)?emptyPanel(p):null;
      repaint();
    }}
    finally{if(reading===epoch)reading=null;}
  }
  function controls(panel){
    if(!panel||panel.loading||panel.error||!employeePanel(panel)&&String(panel.id)!==String(chat))return '';
    const views=items.flatMap(w=>w.views),employee=RunTeamsEmployeeDirectory.forPanel(panel);
    if(!views.length&&!readError&&!active?.id)return '';
    const history=employee?.record;
    if(history?.history_only&&!views.length)return '';
    return `<button type="button" class="conversation-header-action creator-work-trigger creator-work-toggle${visibleWork()?' on':''}" aria-label="工作台" ${views.length>1?'aria-haspopup="menu"':''} aria-expanded="${!!visibleWork()}" aria-pressed="${!!visibleWork()}" onclick="RunTeamsCreatorWork.showPanel(event)" ${opening?'disabled':''}>${ICON('briefcase')}<span>工作台</span></button>`;
  }
  async function showPanel(event){
    // DOM events release currentTarget after the first await. Keep the trigger
    // and resolve its replacement if a verified refresh repaints the header.
    event={currentTarget:event?.currentTarget};
    const p=refreshContext(),identity=token();if(!p||opening)return;
    if(bridge()&&(isPipeline(p)||items.some(item=>item.mcp))){await sync(true);if(context()!==p||token()!==identity)return;}
    const views=items.flatMap(work=>work.views||[]);
    if(isPipeline(p)&&views.length>1)return menu(event);
    if(visibleWork())return togglePanel();
    if(active?.id&&Number(active.chat)===Number(p.id)){if(!visibleWork())return reveal();return togglePanel();}
    if(views.length>1)return menu(event);
    if(views.length===1){const work=items.find(item=>item.views.includes(views[0]));return open(work,views[0]);}
    if(bridge()){lastRead=0;await sync();if(context()!==p||token()!==identity)return;}
    if(readError){active=emptyPanel(p);selectDetailWorkspace({type:'creator-work',id:p.id});repaint();return;}
    if(items.some(work=>work.views?.length))return menu(event);
    return;
  }
  function menu(event){
    const choices=[];for(const work of items)for(const view of work.views)choices.push({label:view.title||'工作内容',icon:'briefcase',fn:()=>active?.installation===work.installation_id&&active?.view===view.id?togglePanel():open(work,view)});
    if(choices.length===1)return choices[0].fn();
    const anchor=event.currentTarget?.isConnected===false?document.querySelector('.creator-work-trigger'):event.currentTarget;
    if(anchor)popMenu(anchor,choices,'railItem');
  }
  function sidebarChoices(){
    const p=context();if(!p||isPipeline(p)||String(p.id)!==String(chat)||!bridge())return [];
    return items.flatMap(work=>work.views.map(view=>({installation_id:work.installation_id,view:view.id,chat_id:Number(p.id),title:String(view.title||'工作内容').slice(0,120)})));
  }
  function pinCurrent(){const row=sidebarChoices().find(row=>row.installation_id===active?.installation&&row.view===active?.view);if(row)return RunTeamsSidebarViews.pin(row);}
  async function openShortcut(row,current){
    const p=refreshContext();if(!bridge())throw Error('当前窗口无法打开工作界面');
    if(!p||Number(p.id)!==row.chat_id||!current())return;
    const epoch=generation,result=checked(await call({action:'discover',workspace_id:workspace(),chat_id:Number(p.id)}));
    if(epoch!==generation||!current())return;
    const work=result.items?.find(item=>item.installation_id===row.installation_id),view=work?.views.find(view=>view.id===row.view);
    if(!work||!view)throw Error('此界面已不可用，可从常用移除入口');
    return open({...work,mcp:result.authority==='device-owned-mcp-work'},view);
  }
  function frame(){const node=document.getElementById('creator_work_viewport');if(!node)return null;const r=node.getBoundingClientRect();return r.width>=1&&r.height>=1&&r.x>=0&&r.y>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1?{x:Math.max(0,r.x),y:Math.max(0,r.y),width:Math.min(r.width,innerWidth-r.x),height:Math.min(r.height,innerHeight-r.y)}:null;}
  async function open(work,view){
    const p=refreshContext();if(!p||opening)return;
    if(get(p.id))return toast('请先核对上一条消息的发送状态','info');
    const epoch=generation;opening=true;const previous=active;const retention=isPipeline(p)?{pipelineWindow:RunTeamsSourcePipelines.key(p.context.source_pipeline_workspace),slotKey:scope+':'+String(S.localLibrary?.cache_scope||S.account?.device_data_scope||'')+':'+workContext,slotScope:scope+':'+String(S.localLibrary?.cache_scope||S.account?.device_data_scope||'')}:{};active={...retention,title:view.title||'工作内容',chat:Number(p.id),mcp:!!work.mcp,installation:work.installation_id,view:view.id,loading:true};
    const openingEntry=active;selectDetailWorkspace({type:'creator-work',id:p.id});const selection=S.sel,sequence=_detailOpenSequence;
    const currentIntent=()=>S.sel===selection&&sequence===_detailOpenSequence;repaint();
    try{
      await release(previous);let rect=frame();
      // Native author views can suppress the platform's animation callbacks.
      // Layout readiness is bounded independently of those paint callbacks.
      for(let n=0;!rect&&n<30&&epoch===generation&&currentIntent();n++){await new Promise(resolve=>setTimeout(resolve,16));rect=frame();}
      if(!currentIntent())return;
      if(!rect)throw Error('当前窗口没有足够空间显示工作内容');
      const result=await call({action:'open',workspace_id:workspace(),chat_id:Number(p.id),installation_id:work.installation_id,view:view.id,input:{},operation_key:uid(),frame:rect});
      if(result.mounted!==true)throw Error('工作内容尚未打开，请重新核对');
      const mounted={...retention,id:result.id,chat:Number(p.id),title:view.title||'工作内容',mcp:!!work.mcp,installation:work.installation_id,view:view.id,viewport:rect};
      if(epoch!==generation||scope!==token()||!currentIntent()){
        // The mount may complete after its window was hidden while no id was
        // available. Revoke visibility before retaining its live page.
        try{await call({action:'visibility',id:mounted.id,chat_id:mounted.chat,visible:false});}
        catch(error){await release(mounted);throw error;}
        const cached=pipelineSlots.get(retention.slotKey);
        if(cached?.active===openingEntry&&cached.active.slotScope===token()+':'+String(S.localLibrary?.cache_scope||S.account?.device_data_scope||''))cached.active=mounted;
        else if(active===openingEntry&&isPipeline(context())&&retention.slotScope===token()+':'+String(S.localLibrary?.cache_scope||S.account?.device_data_scope||'')){active=mounted;lastFrame='';repaint();void layout();}
        else await release(mounted);
        return;
      }
      active=mounted;readError='';lastFrame='';repaint();
    }catch(e){
      const message=e.message||'工作台没有打开',cached=pipelineSlots.get(retention.slotKey);
      if(cached?.active===openingEntry){cached.active={...retention,...emptyPanel(p),reopenRequired:true};cached.readError=message;}
      if(epoch===generation||active===openingEntry){readError=message;active=employeePanel(p)?{...retention,...emptyPanel(p),reopenRequired:true}:null;repaint();}
    }
    finally{
      // An intent can end before native dispatch. Keep no loading placeholder
      // after this operation has settled, including in its retained window.
      const cached=pipelineSlots.get(retention.slotKey);
      if(cached?.active===openingEntry)cached.active={...retention,...emptyPanel(p)};
      if(active===openingEntry)active={...retention,...emptyPanel(p)};
      if(epoch===generation){opening=false;repaint();}
    }
  }
  // Suspension retains the mounted page; only the coordinator changes visibility.
  function suspend(){if(!active)return;displayRevision++;lastFrame='';if(active.id)void call({action:'visibility',id:active.id,chat_id:active.chat,visible:false}).catch(()=>{});}
  function hide(){if(S.sel?.type==='creator-work')selectDetailWorkspace(null);else suspend();}
  function reveal(){const p=refreshContext();if(!p||!employeePanel(p))return;if(!active)active=emptyPanel(p);selectDetailWorkspace({type:'creator-work',id:p.id});displayRevision++;lastFrame='';repaint();void layout();}
  function togglePanel(){if(!active)return;if(visibleWork()){closeDetailWorkspace();document.querySelector('.creator-work-toggle')?.focus();}else{reveal();if(active.display?.mode!=='full')header?.collapseButton.focus({preventScroll:true});}}
  async function close(){const old=active;if(old&&get(old.chat))return toast('请先核对上一条消息的发送状态','info');hide();active=null;await release(old);repaint();}
  async function retryPanel(){lastRead=0;readError='';if(active?.reopenRequired)active.reopenRequired=false;await sync(true);repaint();}
  function emptyContent(){
    if(readError)return `<div class="creator-work-placeholder">${RunTeamsLoadFailure.markup({variant:'local',title:'工作内容暂时无法读取',retry:'RunTeamsCreatorWork.retryPanel()'})}</div>`;
    if(items.some(work=>work.views?.length))return `<div class="creator-work-placeholder"><button type="button" class="btn" onclick="RunTeamsCreatorWork.menu(event)">查看工作内容</button></div>`;
    return '<div class="creator-work-placeholder-note">这名员工没有工作台页面。</div>';
  }
  function drawer(){return visibleWork()?`<aside class="drawer right-detail-drawer creator-work-drawer" data-rt-ui aria-label="${esc(active.title)}"><div id="creator_work_header" class="creator-work-header"></div><div id="creator_work_viewport" class="creator-work-viewport" aria-busy="${!!active.loading}">${active.loading?RunTeamsSkeletons.region('detail'):active.empty||active.readUnavailable?emptyContent():''}</div></aside>`:'';}
  function decorate(){
    const node=document.getElementById('creator_work_header'),kit=window.RunTeamsUIComponents;
    document.getElementById('rgBody')?.classList.toggle('creator-work-full',!!visibleWork()&&!active.readUnavailable&&active.display?.mode==='full');
    if(headerOwner!==active){header?.dispose();header=null;headerRevision=null;headerOwner=active;}
    if(!node||!kit)return;
    node.hidden=!active?.readUnavailable&&active?.display?.mode==='full';
    if(!header){header=RunTeamsEmployeeDrawerHeader.create({onCollapse:togglePanel,kind:'work'});headerRevision=null;}
    if(node.firstChild!==header.element)node.replaceChildren(header.element);
    const data=active?.display?.header,revision=data?.revision||'';
    if(revision===headerRevision)return;
    const owner=active,epoch=owner.displayEpoch;
    header.setExtras({text:'',actions:[...(data?.actions||[]).map(action=>({...action,onPress:()=>{
      if(active!==owner||owner.displayEpoch!==epoch||owner.display?.header?.revision!==revision)return;
      void call({action:'header-action',id:owner.id,chat_id:owner.chat,epoch,revision,key:action.id}).catch(()=>toast('此操作已失效，请重新打开工作内容','info'));
    }})),...(owner.mcp||context()?.kind==='general'&&context()?.identity?.local_mcp?[{id:'@platform-manage',label:'本机功能',onPress:()=>isPipeline(context())?RunTeamsSourcePipelines.managePrograms(header?.element):employeeMCPOpen(null,header?.element)}]:[]),...(owner.empty||isPipeline(context())?[]:[{id:'@platform-pin',label:'固定到常用',onPress:pinCurrent}])]});
    headerRevision=revision;
  }
  // Called only in the trusted platform document by the native mounted host.
  // Author display data is plain text/descriptors; it supplies no DOM or URL.
  function applyDisplay(id,epoch,state,expires){
    const retained=[...pipelineSlots.values()].find(saved=>saved.active.id===id&&saved.active.slotScope===token()+':'+String(S.localLibrary?.cache_scope||S.account?.device_data_scope||''));
    const entry=active?.id===id&&context()?active:retained?.active;
    if(!entry||scope!==token()||Date.now()>=expires||!window.RunTeamsUIComponents)throw Error('display_unavailable');
    if(entry.displayEpoch&&entry.displayEpoch!==epoch)throw Error('display_stale');
    entry.displayEpoch=epoch;entry.display=state;
    if(entry!==active){if(!entry.viewport)throw Error('display_unavailable');return entry.viewport;}
    displayRevision++;lastFrame='';decorate();const rect=visibleWork()?frame():entry.viewport;if(!rect)throw Error('display_unavailable');entry.viewport=rect;return rect;

  }
  function clearDisplay(id,epoch,closed=false){
    if(active?.id!==id){
      for(const [key,saved] of pipelineSlots)if(saved.active.id===id&&(!saved.active.displayEpoch||saved.active.displayEpoch===epoch)){
        if(closed){const old=saved.active;saved.active=closedPanel(old);saved.readError='工作内容已关闭，请重新打开';void release(old);}else{saved.active.display=null;saved.active.displayEpoch=null;}break;
      }
      return;
    }
    if(active.displayEpoch&&active.displayEpoch!==epoch)return;
    active.displayEpoch=null;active.display=null;displayRevision++;lastFrame='';
    header?.dispose();header=null;headerRevision=null;
    if(closed){const old=active;readError='工作内容已关闭，请重新打开';active=employeePanel(context())?closedPanel(old):null;void release(old);}
    repaint();decorate();void layout();
  }
  async function layout(){
    decorate();
    if(layoutBusy){layoutQueued=true;return;}
    if(!active?.id)return;
    const revision=displayRevision,current=active,rect=visibleWork()&&!active.recheck&&!active.readUnavailable?frame():null;if(!rect){if(lastFrame!=='hidden'){lastFrame='hidden';void call({action:'visibility',id:current.id,chat_id:current.chat,visible:false}).catch(()=>{});}return;}
    const blocked=!!document.querySelector('#modalHost,#settingsWorkspace,#popmenu,[role="dialog"],#railSearchHost');
    const preference=document.documentElement.dataset.theme;
    const theme=preference==='dark'||(preference!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';
    const signature=JSON.stringify([rect,blocked,theme]);if(signature===lastFrame)return;
    layoutBusy=true;let stage='theme';
    const outdated=()=>active!==current||current.recheck||current.readUnavailable||revision!==displayRevision||JSON.stringify(frame())!==JSON.stringify(rect);
    try{
      await call({action:'theme',id:current.id,chat_id:current.chat,theme});
      if(outdated()){layoutQueued=true;return;}
      if(!blocked){
        stage='frame';await call({action:'frame',id:current.id,chat_id:current.chat,frame:rect});frameRetries=0;
        if(outdated()){layoutQueued=true;return;}
      }
      stage='visibility';await call({action:'visibility',id:current.id,chat_id:current.chat,visible:!blocked});
      if(!outdated())lastFrame=signature;else layoutQueued=true;
    }catch(e){
      if(active===current){
        if(stage==='frame'&&frameRetries++<3){
          // Native window bounds can change before WebKit delivers resize. Hide
          // until a fresh bounded frame is accepted; never reopen the document.
          lastFrame='';void call({action:'visibility',id:current.id,chat_id:current.chat,visible:false}).catch(()=>{});
          requestAnimationFrame(()=>void layout());
        }else if(revision!==displayRevision){layoutQueued=true;}
        else{active=null;lastFrame='';void release(current);repaint();}
      }
    }finally{layoutBusy=false;if(layoutQueued){layoutQueued=false;void layout();}}
  }

  async function recover(id,force=false){
    if(!id||!needsRecovery(id))return;
    const k=key(id),old=recovery.get(k);if(get(id))return;
    if(old?.promise)return old.promise;if(old?.ready&&!force)return;
    const identity=token(),panel=S.conversationPanel,entry={ready:false,error:false};
    recovery.set(k,entry);
    entry.promise=(async()=>{
      try{
        const value=checked(await api(`/api/chat/${id}/creator-recovery`));
        if(identity!==token()||S.conversationPanel!==panel||Number(panel?.id)!==id)return;
        if(!['none','not_claimed','unknown','completed','cancelled','failed'].includes(value.state)||value.dispatch_permitted!==false)throw Error('原消息状态暂时无法核对');
        if(value.state==='none'){entry.ready=true;return;}
        if(!value.creator_message||!value.input)throw Error('原消息引用暂时无法核对');
        if(['completed','cancelled','failed'].includes(value.state)){
          const saved=checked(await api(`/api/chat/${id}`));
          if(identity!==token()||S.conversationPanel!==panel||panel.busy)return;
          if(!saved.messages?.some(m=>m.id===value.creator_message.message_id)||!saved.messages?.some(m=>m.id===value.assistant_message_id))throw Error('原回复暂时无法核对');
          panel.messages=saved.messages.map(storedConversationMessage);entry.ready=true;repaint();return;
        }
        pending.set(k,{scope:identity,input:value.input,key:value.creator_message.operation_key,work:null,chat:id,
          message:value.creator_message,phase:value.state==='not_claimed'?'dispatch_ready':'dispatch_unknown',recovered:true});
        entry.ready=true;repaint();
      }catch(e){entry.error=true;repaint();throw e;}
      finally{entry.promise=null;}
    })();
    return entry.promise;
  }
  async function beforeSend(id){
    if(!id||!needsRecovery(id))return true;
    try{await recover(Number(id));}catch(e){toast('原消息状态暂时无法核对，请稍后重试','info');return false;}
    if(get(id)?.recovered){toast('请先核对上一条消息，或继续处理原消息','info');return false;}
    return true;
  }
  function pendingMarkup(id){
    const p=get(id),r=recovery.get(key(id));
    if(!p&&!r?.promise&&!r?.error)return '';
    const ready=p?.recovered&&p.phase==='dispatch_ready',label=p?(ready?'上一条消息已保存，尚未开始处理':p.phase==='dispatch_unknown'?'上一条消息的处理状态待核对':'上一条消息的发送状态待核对'):r.error?'原消息状态暂时无法核对':'正在核对原消息状态';
    return `<div class="creator-send-pending" role="status"><span>${label}</span><button type="button" class="btn ghost sm" onclick="RunTeamsCreatorWork.retry()" ${!p&&r?.promise?'disabled':''}>${ready?'继续处理原消息':'核对状态'}</button></div>`;
  }
  async function retry(){
    const p=get(chat),panel=S.conversationPanel;
    if(!p&&panel?.id===chat&&!panel.busy){try{await recover(Number(chat),true);repaint();}catch(e){toast(e.message||'原消息状态暂时无法核对','info');}return;}
    if((p?.phase==='dispatch_unknown'||p?.recovered)&&panel?.id===chat&&!panel.busy){
      // The composer is already cleared after accepted. Recover the original
      // dispatch independently of any new draft; never start it again.
      const identity=token();panel.busy=true;repaint();
      try{
        p.resuming=true;await send(`/api/chat/${chat}/stream`,p.input,()=>{});
        const saved=checked(await api(`/api/chat/${p.chat}`));
        if(identity!==token()||S.conversationPanel!==panel)return;
        panel.messages=(saved.messages||[]).map(storedConversationMessage);
        panel.draft=saved.draft||panel.draft;panel.status=saved.status||panel.status;
      }catch(e){if(identity===token())toast(e.message||'处理状态仍待核对','info');}
      finally{p.resuming=false;panel.busy=false;if(identity===token()&&S.conversationPanel===panel)repaint();}
      return;
    }
    if(panel?.id===chat&&!panel.busy)return sendConversationPanel();
    if(S.chatId===chat&&!S.chatBusy)return sendChat();
  }
  function changed(p){
    // Hint the original mounted work, never a newly selected chat/work. Author
    // code reads current cloud state; completion text is not a data source.
    if(p.scope===token()&&chat===p.chat&&active?.id===p.work)
      void call({action:'context-changed',id:p.work,chat_id:p.chat}).catch(()=>{});
  }
  async function send(path,input,onEvent){
    const id=Number(path.match(/\/api\/chat\/(\d+)\/stream$/)?.[1]);let p=get(id);
    const sendingScope=token();
    if(!p&&needsRecovery(id)&&!recovery.get(key(id))?.ready){
      await recover(id);
      if(sendingScope!==token())throw error({scope:sendingScope},'已离开原账号，原消息状态需要核对。');
      p=get(id);
    }
    if(p?.recovered&&!p.resuming)throw error(p,'请先核对上一条消息，或继续处理原消息。');
    if(isPipeline(S.conversationPanel)||S.conversationPanel?.context?.creator_local_source_id)return streamApi(path,input,onEvent);
    const panel=context(),employee=RunTeamsEmployeeDirectory.forPanel(panel)?.record||panel?.employee_binding;
    if(active?.mcp||mcpEmployee(employee)||employeePanel(panel)&&(!active||active.empty))return streamApi(path,input,onEvent);
    const headless=!active&&bridge()&&Number(panel?.id)===id&&folderEmployee(employee);
    if(!p&&!active&&!headless)return streamApi(path,input,onEvent);
    if(!p&&!headless&&(!active?.id||active.chat!==id||active.loading))throw Error('工作内容尚未就绪，请稍后发送');
    const normalized={...input};delete normalized.ui_test_state;
    if(p&&JSON.stringify(p.input)!==JSON.stringify(normalized))throw error(p,'请保留原消息内容，先核对上一条消息的状态。');
    if(!p){p={scope:token(),input:normalized,key:uid(),work:headless?null:active.id,chat:id,phase:'stage_new'};pending.set(key(id),p);}
    const check=()=>{if(p.scope!==token()||chat!==id)throw error(p,'已离开原对话，原消息状态需要核对。');};
    try{
      check();let stage;
      if(p.phase==='stage_new'){
        p.phase='stage_unknown';
        stage=checked(await api(`/api/chat/${id}/creator-input`,'POST',{operation_key:p.key,input:p.input}));check();
      }else if(p.phase==='stage_unknown'){stage=checked(await api(`/api/chat/${id}/creator-input?operation_key=${encodeURIComponent(p.key)}`));check();}
      if(stage){if(!stage.input_ref)throw error(p);p.ref=stage.input_ref;p.phase='native_new';}
      if(p.cancelRequested&&p.phase==='native_new'){pending.delete(key(id));throw Error('已停止发送，草稿已保留。');}
      let receipt;
      if(p.phase==='native_new'){
        if(p.work&&active?.id!==p.work)throw error(p);p.phase='native_unknown';
        receipt=p.work?await call({action:'submit',id:p.work,chat_id:id,operation_key:p.key,input_ref:p.ref}):checked(await api(`/api/chat/${id}/creator-employee-message`,'POST',{operation_key:p.key,input_ref:p.ref}));check();
      }else if(p.phase==='native_unknown'){receipt=p.work?await call({action:'receipt',id:p.work,chat_id:id,operation_key:p.key}):checked(await api(`/api/chat/${id}/creator-employee-message?operation_key=${encodeURIComponent(p.key)}`));check();}
      if(receipt){
        if(receipt.state==='rejected'){pending.delete(key(id));throw Error('工作内容已变化，请核对后重新发送。');}
        if(receipt.state!=='confirmed'||!receipt.creator_message)throw error(p);
        p.message=receipt.creator_message;p.phase='dispatch_ready';
      }
      if(p.phase==='dispatch_unknown'){
        const state=checked(await api(`/api/chat/${id}/creator-turn?message_id=${p.message.message_id}&business_epoch=${encodeURIComponent(p.message.business_epoch)}`));check();
        if(!['completed','cancelled','failed'].includes(state.state))throw error(p,'上一条消息的处理状态还无法确认，请勿重复发送。');
        const saved=checked(await api(`/api/chat/${id}`));check();const user=saved.messages?.find(m=>m.id===p.message.message_id),reply=saved.messages?.find(m=>m.id===state.assistant_message_id);
        if(!user||!reply)throw error(p);onEvent({type:'accepted',message_id:user.id,attachments:user.attachments||[],capabilities:user.capabilities||[]});
        const delivery={};for(const name of ['incomplete','system_notice','option_question','skill_draft','run_cards','options','pending','plan','local_references','available_local_references','health','employee_bot_release','context_refs'])if(reply.metadata?.[name]!==undefined)delivery[name]=reply.metadata[name];
        if(state.state==='cancelled')onEvent({type:'cancelled'});else onEvent({...delivery,type:'result',failed:state.state==='failed',message_id:reply.id,reply:reply.text||'',applied:reply.applied||[]});pending.delete(key(id));changed(p);return;
      }
      if(p.phase!=='dispatch_ready')throw error(p);
      const saved=checked(await api(`/api/chat/${id}`));check();const user=saved.messages?.find(m=>m.id===p.message.message_id);if(!user)throw error(p);
      onEvent({type:'accepted',message_id:user.id,attachments:user.attachments||[],capabilities:user.capabilities||[]});
      if(p.cancelRequested){onEvent({type:'cancelled'});pending.delete(key(id));return;}
      p.phase='dispatch_unknown';let terminal=false;
      await streamApi(path,{creator_message:p.message},event=>{check();if(event.type==='accepted'){if(event.message_id!==p.message.message_id)throw error(p);return;}onEvent(event);if(['result','cancelled'].includes(event.type))terminal=true;});
      if(!terminal)throw error(p);pending.delete(key(id));changed(p);
    }catch(e){
      if(e.creatorRejected&&['stage_unknown','native_unknown'].includes(p.phase)){
        pending.delete(key(id));
        if(p.scope===token()&&typeof refreshCoreTeam==='function')void refreshCoreTeam().then(repaint).catch(()=>{});
      }
      if(pending.get(key(id))===p){if(e.creatorPending)throw e;throw error(p,e.message||undefined);}throw e;
    }
  }
  const visibleWork=()=>active&&S.sel?.type==='creator-work'&&String(S.sel.id)===String(active.chat)&&String(active.chat)===String(context()?.id)?active:null;
  function closeWindow(windowKey){
    if(active?.pipelineWindow===windowKey){const old=active;active=null;void release(old);}
    for(const [key,saved] of pipelineSlots)if(saved.active.pipelineWindow===windowKey){pipelineSlots.delete(key);void release(saved.active);}
  }
  window.RunTeamsCreatorWork={closeWindow,hide,suspend,reveal,retryPanel,applyDisplay,clearDisplay,togglePanel,sync,controls,showPanel,menu,open,close,drawer,layout,pendingMarkup,retry,send,beforeSend,beforeRender:refreshContext,sidebarChoices,pinCurrent,openShortcut,
    current:visibleWork,
    hasPending:id=>!!get(id),pendingInput:id=>get(id)?.input,
    requestStop:id=>{const p=get(id);if(!p||p.phase==='dispatch_unknown')return false;p.cancelRequested=true;return true;}};
  window.addEventListener('runteams-ui-ready',()=>void layout());
  window.addEventListener('resize',()=>{displayRevision++;lastFrame='';void layout();});
  new MutationObserver(()=>void layout()).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>void layout());
  window.addEventListener('scroll',()=>void layout(),true);
  window.addEventListener('pagehide',()=>{const old=active;active=null;void release(old);for(const saved of pipelineSlots.values())void release(saved.active);pipelineSlots.clear();});
  setInterval(()=>{void sync();},2000);
  new MutationObserver(()=>void layout()).observe(document.documentElement,{childList:true,subtree:true});
})();
