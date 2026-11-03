/* Shared transport scheduling. Business authority and cache validation remain on the host. */
(function(global){
  'use strict';
  const flights=new Map(),pendingJobs=new Set(),groups=new Map(),orders=new Map(),metrics=[],pages=[];
  // Slow CLI/runtime discovery has its own bounded capacity. It must not
  // occupy the slots needed to display the user's current cloud content.
  const pools={foreground:{limit:4,running:0,queue:[]},runtime:{limit:2,running:0,queue:[]},background:{limit:1,running:0,queue:[]}};
  // These POST endpoints only read a verified workspace or its original receipt.
  // Commands and endpoints that also accept mutations keep the write barrier.
  const pipelineReads=new Set(['ui-state-read','catalog','workspace','creation-choices','settings','history','records','state','contract','work','operation','control-operation','edit-operation','flow-operation'].map(action=>'/api/device/work/source-pipelines/'+action));
  function isRead(path,method='GET'){
    return method==='GET'||method==='POST'&&(
      /^\/api\/assets\/read\/[a-z-]+$/.test(path)||pipelineReads.has(path)||
      /^\/api\/pipeline-work\/(?:contract|operation|control-operation|schedule-operation)$/.test(path));
  }
  let version=0,deviceVersion=0;
  const now=()=>global.performance?.now?.()??Date.now();
  function pump(pool){while(pool.running<pool.limit&&pool.queue.length){const job=pool.queue.shift();pool.running++;job.execute().finally(()=>{pool.running--;pump(pool);});}}
  function reset(){version++;deviceVersion++;flights.clear();for(const job of pendingJobs)job.cancel();groups.clear();orders.clear();}
  function lane(path,options){
    if(/^\/api\/(?:model-catalog|channels|environment|channel-usage|app-info|app-update)(?:\/|$)/.test(path)||/^\/api\/channel\/\d+\/capabilities$/.test(path))return 'runtime';
    return options.readPriority==='background'?'background':'foreground';
  }
  const diagnosticPaths=new Set(['/api/employee-directory','/api/chats','/api/assets/read/session','/api/assets/read/employee-catalog','/api/assets/read/pipeline-catalog']);
  const diagnosticCode=value=>typeof value==='string'&&/^[A-Za-z0-9_.-]{0,64}$/.test(value)?value:'unclassified';
  function reportDiagnostic(row){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),3000);
    try{
      Promise.resolve(global.fetch('/api/diagnostics/navigation-read',{method:'POST',headers:{'Content-Type':'application/json','X-RunTeams-Diagnostic':'1'},body:JSON.stringify(row),signal:controller.signal,keepalive:true}))
        .catch(()=>{}).finally(()=>clearTimeout(timer));
    }catch(error){clearTimeout(timer);}
  }
  async function request(path,options={},scope=''){
    const method=options.method||'GET',read=isRead(path,method);
    const url=new URL(path,'http://localhost');url.searchParams.sort();
    // Preferences and read-only runtime probes do not invalidate unrelated reads.
    if(!read&&options.invalidates!==false&&!/^\/api\/channel\/\d+\/probe$/.test(url.pathname)){if(options.device)deviceVersion++;else version++;flights.clear();}
    const key=[options.device?'device':'cloud',options.device?deviceVersion:version,scope,url.pathname+url.search,read&&method==='POST'?options.body||'':'',options.readCurrent?'current':'snapshot'].join('|');
    const group=read&&options.readGroup?scope+':'+options.readGroup:'',order=Number(options.readSequence)||0;
    if(group){if((orders.get(group)??-1)>order)throw Object.assign(new Error('请求已更新。'),{code:'request_superseded'});orders.set(group,order);if(orders.size>64)orders.delete(orders.keys().next().value);}
    const poolName=lane(url.pathname,options),pool=pools[poolName];
    if(read&&flights.has(key)){
      // A foreground consumer may join a queued background refresh. Promote
      // that one shared read instead of leaving the visible page behind it.
      if(poolName==='foreground')for(const waiting of pools.background.queue){if(waiting.key===key){pools.background.queue.splice(pools.background.queue.indexOf(waiting),1);pool.queue.push(waiting);pump(pool);break;}}
      return flights.get(key);
    }
    let cancelled=false,expired=false,executing=false,rejectWaiting=null,status=0,queueMs=0;
    const observed=read&&options.readDiagnostics!==false&&diagnosticPaths.has(url.pathname);
    const requestId=observed?(global.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)):'';
    let responseCode='',responseOutcome='ok';
    const controller=new AbortController();
    const timeout=()=>Object.assign(new Error(read?'读取超时或已取消，请重试。':'操作结果尚未确认，请重新读取后再试。'),{code:read?'read_timeout':'mutation_outcome_unknown'});
    const superseded=()=>Object.assign(new Error('请求已更新，请重试。'),{code:'request_superseded'});
    const job={key,order,cancel(){cancelled=true;controller.abort();if(!executing&&rejectWaiting){removeQueued();rejectWaiting(superseded());}}};
    function removeQueued(){for(const item of Object.values(pools)){const index=item.queue.indexOf(job);if(index>=0)item.queue.splice(index,1);}}
    pendingJobs.add(job);
    if(group){const previous=groups.get(group);if(previous)previous.cancel();groups.set(group,job);}
    const started=now();let generation=options.device?deviceVersion:version,attempts=0;
    // The deadline covers both queueing and transport, not thirty seconds
    // on the wire in addition to an unbounded wait for a slot.
    const timer=setTimeout(()=>{expired=true;controller.abort();if(!executing&&rejectWaiting){removeQueued();rejectWaiting(timeout());}},read?30000:120000);
    const run=async()=>{
      // Only opted-in directory reads follow ordinary writes. Scope resets
      // and superseding search jobs still cancel, and writes are never replayed.
      for(;;){
      if(expired)throw timeout();
      if(cancelled)throw superseded();
      if(read&&generation!==(options.device?deviceVersion:version)){
        if(!options.readCurrent)throw superseded();
        generation=options.device?deviceVersion:version;
      }
      if(!executing)queueMs=Math.round(now()-started);
      executing=true;
      attempts++;
      const {readGroup,readSequence,readPriority,readCurrent,readDiagnostics,device,invalidates,...fetchOptions}=options;
      try{const response=await global.fetch(path,{...fetchOptions,...(observed?{headers:{...fetchOptions.headers,'X-RunTeams-Read-Id':requestId}}:{}),signal:controller.signal,cache:'no-store'});status=response.status;
        const text=await response.text();
        if(expired)throw timeout();
        if(read&&cancelled)throw superseded();
        if(read&&generation!==(options.device?deviceVersion:version)){
          if(options.readCurrent)continue;
          throw Object.assign(new Error('请求已更新，请重新读取。'),{code:'request_superseded'});
        }
        if(observed){
          responseOutcome=status>=400?'http_error':'ok';
          try{const data=JSON.parse(text);responseCode=diagnosticCode(data?.code||'');if(data?.error)responseOutcome='http_error';}
          catch(error){responseOutcome='invalid_json';responseCode='invalid_json';}
        }
        return {status,text};
      }catch(error){if(error.name==='AbortError')throw read&&cancelled?superseded():timeout();throw error;}
      }
    };
    const pending=read&&!options.device?new Promise((resolve,reject)=>{rejectWaiting=reject;job.execute=async()=>{try{resolve(await run());}catch(error){reject(error);}};pool.queue.push(job);pump(pool);}):run();
    if(read)flights.set(key,pending);
    let errorCode='';
    try{return await pending;}catch(error){errorCode=diagnosticCode(error.code||(error.name==='TypeError'?'network_error':error.name)||'request_failed');throw error;}
    finally{
      clearTimeout(timer);pendingJobs.delete(job);if(flights.get(key)===pending)flights.delete(key);if(group&&groups.get(group)===job)groups.delete(group);
      const duration=Math.round(now()-started),queued=executing?queueMs:duration;
      const outcome=errorCode?(errorCode==='request_superseded'?'cancelled':errorCode==='read_timeout'?'timeout':errorCode==='network_error'?'network_error':'failed'):responseOutcome==='ok'&&attempts>1?'refreshed':responseOutcome;
      metrics.push({path:url.pathname,method,status,ms:duration,queue_ms:queued,pool:options.device?'device':poolName,attempts,error_code:errorCode||responseCode,outcome,request_id:requestId});if(metrics.length>200)metrics.shift();
      if(observed&&(outcome!=='ok'||attempts>1))reportDiagnostic({request_id:requestId,path:url.pathname,method,http_status:status,outcome,error_code:errorCode||responseCode,duration_ms:duration,queue_ms:queued,attempts});
    }
  }
  function isFreshConversation(route,value){
    if(route?.kind!=='chat-new')return false;
    const target=new URL(global.RunTeamsRoutes?.unmount?.(value)||value,global.location?.origin||'http://localhost');
    return /^\/chats\/new\/?$/.test(target.pathname)&&[...target.searchParams].every(([key,value])=>key==='chat'&&value==='new');
  }
  function bootPlan(route,rail){
    const kind=route?.kind||'home',board=['home','core-pipeline','core-employee-run'].includes(kind);
    const navigation=board||rail?.mode==='assistant'||['bot','chat','chat-new','core-pipeline-new'].includes(kind)||kind==='extensions'&&!!route.employeeId;
    return {board,navigation,channels:navigation||kind==='extensions'};
  }
  global.addEventListener?.('runteams:business-scope-will-change',reset);
  function startPage(route){return {path:route?.kind||String(route||'workspace'),started:now()};}
  function finishPage(token,status){const value={path:token.path,status,ms:Math.round(now()-token.started)};pages.push(value);global.RunTeamsAnalytics?.pageLoad?.(value.path,value.status,value.ms);if(pages.length>100)pages.shift();const root=global.document?.documentElement;if(root){root.dataset.pageLoadMs=String(value.ms);root.dataset.pageLoadStatus=status;root.dataset.pageLoadKind=token.path;}}
  const observedRequest=(path,options={},scope='')=>global.RunTeamsAnalyticsAuth?global.RunTeamsAnalyticsAuth.transport(path,options,()=>request(path,options,scope)):request(path,options,scope);
  global.RunTeamsRequests={request:observedRequest,isRead,reset,bootPlan,isFreshConversation,startPage,finishPage,metrics:()=>metrics.map(item=>({...item})),pages:()=>pages.map(item=>({...item}))};
})(window);
