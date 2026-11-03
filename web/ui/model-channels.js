/* Model-channel data boundary. Pages render this state; they do not infer
 * connection from quota, replace explicit models, or call provider reads.
 * Display snapshots are not execution authority: the Python boundary validates
 * the exact model again before a session is created or a turn is dispatched. */
(function(root,factory){const value=factory();if(typeof module==='object'&&module.exports)module.exports=value;root.RunTeamsModelChannels=value;})(globalThis.window&&typeof globalThis.window==='object'?globalThis.window:globalThis,function(){
 'use strict';
 const clients=new WeakMap(),snapshots=new WeakMap(),readStatuses=new WeakMap(),same=(a,b)=>String(a)===String(b);
 const rowFor=(rows,id,key='channel_id')=>(rows||[]).find(row=>same(row[key],id));
 const denied=value=>value?.code==='authentication_failed';
 const blocked=new Set(['disabled','missing','incompatible','login_required','not_connected','disconnected']);
 function verifiedUsage(value){const remaining=value?.remaining_percent;return value?.status==='ready'&&remaining!==null&&remaining!==undefined&&typeof remaining!=='boolean'&&String(remaining).trim()!==''&&Number.isFinite(Number(remaining))&&Number(remaining)>=0&&Number(remaining)<=100;}
 function effectiveVerification(channel,observation,usage){return channel?.provider!=='claude-code'||observation?.connection_verified===true||observation?.connection_verified!==false&&verifiedUsage(usage);}
 function currentObservation(state,value,allowUnmarked=true){const read=value&&snapshots.get(value);return read?read.state===state&&read.context===contextSignature(state,read.scope()):allowUnmarked;}
 function nativeReady(channel,usage=null){const probe=channel?.probe;return !!channel?.enabled&&probe?.status==='ready'&&probe.installed!==false&&probe.authenticated!==false&&probe.compatible!==false&&probe.connection_verified!==false&&effectiveVerification(channel,probe,usage);}
 function connection(state,channel){
  if(!channel)return {known:true,ready:false};
  if(!channel.enabled||channel.statusReadError||channel.loginPending||channel.removeUnknown||channel.removing)return {known:true,ready:false};
  const usage=currentObservation(state,state.channelUsage)?rowFor(state.channelUsage?.channels,channel.id):null,
   probe=currentObservation(state,channel.probe)?channel.probe:null,
   environment=currentObservation(state,state.environment,false)?rowFor(state.environment?.channels,channel.id,'id'):null,
   catalog=state.modelCatalogReady&&currentObservation(state,state.modelCatalog)&&rowFor(state.modelCatalog,channel.id);
  if([usage,probe,environment?.runtime,catalog].some(denied))return {known:true,ready:false};
  if(probe?.compatible===false||probe?.installed===false||probe?.authenticated===false||probe?.connection_verified===false||catalog?.connection_verified===false)return {known:true,ready:false};
  if(catalog&&blocked.has(catalog.status))return {known:true,ready:false};
  if(probe?.status&&probe.status!=='unknown')return {known:true,ready:nativeReady(channel,usage)};
  if(environment){const runtime=environment.runtime||{};return {known:true,ready:runtime.compatible!==false&&runtime.authenticated!==false&&runtime.installed!==false&&runtime.connection_verified!==false&&!!environment.ready&&environment.status==='ready'&&effectiveVerification(channel,runtime,usage)};}
  if(catalog?.status==='ready')return {known:true,ready:effectiveVerification(channel,catalog,usage)};
  return {known:false,ready:false};
 }
 function connected(state,channel){const result=connection(state,channel);return result.known&&result.ready;}
 function connectedIds(state){return (state.channels||[]).filter(channel=>connected(state,channel)).map(channel=>String(channel.id)).sort();}
 function rows(state){
  const definitions=state.providerCatalog||[],channels=state.channels||[];
  if(!definitions.length)return channels;
  return definitions.map(provider=>channels.find(channel=>channel.provider===provider.id)||{provider:provider.id,provider_label:provider.label,_settingsPlaceholder:true});
 }
 function usage(state,id){return currentObservation(state,state.channelUsage)?rowFor(state.channelUsage?.channels,id)||null:null;}
 function readState(state,kind){const value=readStatuses.get(state)?.get(kind);return value&&currentObservation(state,value,false)?value:null;}
 function definitionError(state){const value=readState(state,'channels');return value?.status==='error'?value.error:'';}
 function presentation(state,channel){
  const probe=currentObservation(state,channel.probe)?channel.probe:null,
   checking=!!(channel.connecting||channel.removing||(channel.loginStatusPending??channel.loginProbeBusy)),
   failed=!checking&&!state.channelSettingsRefreshing&&!!(channel.statusReadError||definitionError(state)),
   observed=!!probe?.status&&probe.status!=='unknown',
   installationKnown=!!probe&&(typeof probe.installed==='boolean'||!!probe.version||observed&&['ready','missing','incompatible','login_required','not_connected','disabled'].includes(probe.status)),
   idleDisabled=!channel._settingsPlaceholder&&[false,0].includes(channel.enabled),
   installationPending=!installationKnown&&!idleDisabled&&!failed,
   connectionPending=installationPending||!failed&&(checking||!channel._settingsPlaceholder&&!connection(state,channel).known&&!idleDisabled),
   value=usage(state,channel.id),usageObserved=currentObservation(state,state.channelUsage)&&!!state.channelUsage,usageRead=readState(state,'usage');
  return {installationPending,connectionPending,usagePending:usageRead?usageRead.status==='loading':!!state.channelUsageLoading||!value&&!usageObserved,usage:value,failed};
 }
 function extensionsReady(state,environment){
  const read=environment&&snapshots.get(environment);
  return !!read&&read.state===state&&read.identity===signature(state,read.scope())&&connectedIds(state).every(id=>rowFor(environment.channels,id,'id')?.read_states?.plugins==='ready');
 }
 function applyChannel(state,channel,record){
   const observation=value=>JSON.stringify([value.enabled,value.probe?.status,value.probe?.code,value.probe?.authenticated,value.probe?.compatible,value.probe?.installed,value.probe?.connection_verified,value.probe?.account]);
  const before=observation(channel),changedProfile=['provider','executable','config_dir'].some(key=>record[key]!==undefined&&record[key]!==channel[key]);Object.assign(channel,record);
  if(changedProfile&&!record.probe){delete channel.probe;delete channel.capabilities;}
  if(before!==observation(channel))state.channelStatusVersion=(state.channelStatusVersion||0)+1;
  const receipt=record.probe&&snapshots.get(record.probe);if(receipt)snapshots.set(channel.probe,{...receipt,context:contextSignature(state,receipt.scope())});
 }
 function catalog(state,channel){
  if(!currentObservation(state,state.modelCatalog))return {source:'unavailable',status:'unknown',models:[]};
  const row=channel&&rowFor(state.modelCatalog,channel.id);
  if(!row)return {source:'unavailable',status:'unknown',models:[]};
  const usable=!row.error&&(!row.status||row.status==='ready')&&Array.isArray(row.models);
  return usable?row:{...row,models:[]};
 }
 function automaticModel(catalog){return (catalog.models||[]).some(model=>model.value===catalog.automatic_model)?catalog.automatic_model:'';}
 function hasSelectableModels(state){return (state.channels||[]).some(channel=>connected(state,channel)&&catalog(state,channel).models.length);}
 function selectionIssue(state,id,model,options={}){
  let channel=id!=null?(state.channels||[]).find(row=>same(row.id,id)):null;
  if(!channel&&options.provider)channel=(state.channels||[]).find(row=>row.provider===options.provider);
  const provider=channel?.provider||options.provider||'';
  if(!connected(state,channel))return {reason:'channel',channel,provider};
  if(options.requireModel===false)return null;
  const row=catalog(state,channel);
  if(!state.modelCatalogReady||row.status==='unknown'||row.status==='error'||row.error)return {reason:'catalog',channel,provider,model};
  if(!model||!row.models.some(item=>same(item.value,model)))return {reason:'model',channel,provider,model};
  return null;
 }
 function displayScope(state){return globalThis.RunTeamsHost.session.displayScope(state);}
 function definitionsKey(channels){return JSON.stringify((channels||[]).map(c=>[String(c.id),c.provider,!!c.enabled,c.executable||'',c.config_dir||'']).sort((a,b)=>a[0].localeCompare(b[0])));}
 function displaySnapshot(state,channels){
  const scope=displayScope(state);if(!scope)return null;
  const previous=state.modelDisplaySnapshot,definitions=definitionsKey(state.channels);
  if(previous?.scope===scope&&previous.definitions===definitions){const ids=new Set((channels||[]).map(row=>String(row.channel_id)));channels=[...(channels||[]),...previous.channels.filter(row=>!ids.has(String(row.channel_id)))];}
  const prefs=state.settingsPreferences||{},choice=String(prefs.default_model||'').split('::'),row=(channels||[]).find(r=>same(r.channel_id,choice[0])&&r.models?.some(m=>m.value===choice[1]))||(channels||[]).find(r=>r.status==='ready'&&r.models?.some(m=>m.value===r.automatic_model));
  const names={...(previous?.scope===scope?previous.names:{})};for(const item of channels||[])for(const model of item.models||[])names[item.channel_id+'::'+model.value]=model.display_name||model.value;
  const requested=choice[0]&&choice[1]?{channel_id:choice[0],model:choice[1],reasoning_effort:prefs.default_effort||'high'}:previous?.scope===scope&&previous.definitions===definitions?previous.selection:null;
  return {scope,definitions,channels:JSON.parse(JSON.stringify(channels||[])),names,selection:requested||(row?{channel_id:row.channel_id,model:row.automatic_model,reasoning_effort:prefs.default_effort||'high'}:null)};
 }
 function restoreDisplay(state,value){state.modelDisplaySnapshot=value?.scope&&value.scope===displayScope(state)&&Array.isArray(value.channels)?value:null;return !!state.modelDisplaySnapshot;}
 function composer(state,cfg){
  const saved=state.modelDisplaySnapshot,scope=displayScope(state),cached=saved?.scope===scope&&(!state.channelDefinitionsScope||state.channelDefinitionsScope!==scope||saved.definitions===definitionsKey(state.channels))?saved:null;
  const choice=cfg.model?cfg:!cfg.id&&!cfg.employee_binding&&cfg.context?.context_type!=='worker'?cached?.selection:null;
  if(!choice?.model)return {selected:false,loading:!state.modelCatalogReady||state.settingsPreferencesState!=='ready'&&state.settingsPreferencesState!=='error'};
  const channel=(state.channels||[]).find(c=>same(c.id,choice.channel_id)),row=state.modelCatalogReady&&currentObservation(state,state.modelCatalog)?rowFor(state.modelCatalog,choice.channel_id):null,
   old=rowFor(cached?.channels,choice.channel_id),model=row?.models?.find(m=>same(m.value,choice.model))||old?.models?.find(m=>same(m.value,choice.model)),known=connection(state,channel);
  const probe=channel?.probe,values=[probe,row,usage(state,choice.channel_id)],hardDenied=channel&&!channel.enabled||values.some(value=>value&&(denied(value)||blocked.has(value.status)||['installed','authenticated','compatible','connection_verified'].some(key=>value[key]===false))),
   readFailed=channel?.statusReadError||probe?.status==='error'||row?.status==='error'||!!row?.error;
  let status='pending';
  if(hardDenied||!channel&&state.channelDefinitionsScope===scope)status='disconnected';
  else if(readFailed)status='error';
  else if(channel&&known.known&&!known.ready)status='disconnected';
  else if(row&&!row.error&&(!row.status||row.status==='ready')&&Array.isArray(row.models))status=row.models.some(m=>same(m.value,choice.model))?'ready':'removed';
  const failed=status==='error'||!!row?.refresh_error||state.modelCatalogReadState==='error';
  return {selected:true,status,displayOnly:status==='pending',label:(model?.display_name||cached?.names?.[choice.channel_id+'::'+choice.model]||choice.model)+(status==='disconnected'?'（未连接）':status==='removed'?'（不可用）':''),effort:choice.reasoning_effort||'',model,failed};
 }
 function syncEnvironment(state,environment){
  if(!Array.isArray(environment?.channels)||!currentObservation(state,environment,false))return;
  const scoped=(rows,id)=>(rows||[]).filter(row=>same(row.channel_id,id));
  for(const row of environment.channels){
   const channel=(state.channels||[]).find(value=>same(value.id,row.id));if(!channel||channel.connecting||channel.removing)continue;
   const runtime=row.runtime||{},previous=channel.probe||{};
   // Optional display reads cannot wash away an explicit rejection.
   if(denied(previous)&&!denied(runtime)&&runtime.authenticated!==true)continue;
   channel.probe={status:row.status||'unknown',installed:!!runtime.installed,authenticated:!!runtime.authenticated,
    connection_verified:runtime.connection_verified,
    compatible:runtime.compatible===undefined?previous.compatible:runtime.compatible,
    code:runtime.code||'',http_status:runtime.http_status,version:runtime.version||'',account:runtime.account||'',detail:runtime.detail||''};
   snapshots.set(channel.probe,snapshots.get(environment));
   channel.capabilities={...(channel.capabilities||{}),checked_at:environment.checked_at,status:row.status,runtime,
    plugins:scoped(environment.plugins,row.id),available_plugins:scoped(environment.available_plugins,row.id),skills:scoped(environment.skills,row.id),mcp_servers:scoped(environment.mcp_servers,row.id),diagnostics:row.diagnostics||[]};
  }
 }
 function applyUsage(state){
  if(!currentObservation(state,state.channelUsage))return false;
  let changed=false;
  for(const usage of state.channelUsage?.channels||[]){
   const channel=(state.channels||[]).find(row=>same(row.id,usage.channel_id));if(!channel)continue;
   const previous=channel.probe||{},failure=denied(usage),recovery=verifiedUsage(usage)&&(denied(previous)||previous.code==='connection_unverified');
   if(!failure&&!recovery)continue;
   if(recovery&&(!channel.enabled||previous.installed===false||previous.compatible===false||['missing','incompatible','disabled'].includes(previous.status)))continue;
   const next={...previous,status:failure?'login_required':'ready',authenticated:!failure,
    connection_verified:failure?false:channel.provider==='claude-code'?true:previous.connection_verified,
    code:failure?'authentication_failed':'',http_status:failure?usage.http_status:null,detail:failure?usage.detail:''};
   changed=changed||JSON.stringify(previous)!==JSON.stringify(next);channel.probe=next;
   const provenance=snapshots.get(state.channelUsage)||snapshots.get(previous);if(provenance)snapshots.set(next,provenance);
   const row=rowFor(state.environment?.channels,channel.id,'id');
   if(row){row.status=next.status;row.ready=connected(state,channel);row.runtime={...(row.runtime||{}),...next};}
  }
  if(changed)state.channelStatusVersion=(state.channelStatusVersion||0)+1;
  return changed;
 }
 function contextSignature(state,scope){return JSON.stringify([scope,state.channelMutationVersion||0,
  (state.channels||[]).map(channel=>[channel.id,channel.provider,channel.enabled,channel.executable||'',channel.config_dir||'',channel.changeSequence||0])]);}
 function signature(state,scope){return JSON.stringify([contextSignature(state,scope),state.channelStatusVersion||0]);}
 function validate(kind,value){
  if(value?.error)return value;
  const records=(rows,key)=>Array.isArray(rows)&&rows.every(row=>row&&typeof row==='object'&&row[key]!=null);
  if(!value||typeof value!=='object')throw Error('模型渠道返回的数据无效。');
  if(kind==='capabilities'){
   if(value.channel_id==null||!records(value.items,'channel_id')||value.items.some(row=>!same(row.channel_id,value.channel_id)||typeof row._installed!=='boolean'||!String(row.id||row.name||'').trim())||value.next_cursor!==null&&typeof value.next_cursor!=='string')throw Error('技能分页数据无效。');
   return value;
  }
  if(kind==='resources'){
   if(!Array.isArray(value.files)||value.files.some(file=>!file||typeof file.path!=='string'))throw Error('插件资源清单无效。');
   return value;
  }
  if(kind==='resource')return value;
  if(kind.startsWith('probe:')){
   if(!value.channel||!same(value.channel.id,kind.slice(6))||![true,false,0,1].includes(value.channel.enabled)||!value.channel.probe?.status)throw Error('渠道状态未能确认，请重新检测。');
  }else if(!records(value.channels,['status','channels','extensions'].includes(kind)?'id':'channel_id'))throw Error('模型渠道清单无效。');
  if(kind==='models'&&value.channels.some(row=>!Array.isArray(row.models)||row.models.some(model=>!model||typeof model.value!=='string'||!model.value.trim())||new Set(row.models.map(model=>model.value)).size!==row.models.length))throw Error('模型目录数据无效。');
  if(kind==='extensions'&&(['plugins','skills','mcp_servers'].some(key=>!records(value[key],'channel_id'))||value.available_plugins!==undefined&&!records(value.available_plugins,'channel_id')))throw Error('扩展清单无效。');
  return value;
 }
 function create(state,request,getScope){
  const flights=new Map();let usageCache=null;
  const stamp=value=>{if(value&&typeof value==='object')snapshots.set(value,{state,identity:signature(state,getScope()),context:contextSignature(state,getScope()),scope:getScope});return value;};
  // Native observations can finish independently. A sibling probe must not
  // invalidate this channel's receipt; a newer rejection of the same channel
  // must still retire an older success. Aggregate reads retry against new facts.
  function facts(kind){
   if(kind==='channels')return '';
   const rows=kind.startsWith('probe:')?(state.channels||[]).filter(row=>same(row.id,kind.slice(6))):state.channels||[];
   return JSON.stringify(rows.map(row=>[row.id,row.probe?.status,row.probe?.code,row.probe?.installed,row.probe?.authenticated,row.probe?.compatible,row.probe?.connection_verified,row.probe?.account]));
  }
  function read(kind,path,options={}){
   const context=contextSignature(state,getScope()),identity=signature(state,getScope()),selection=['extensions','resources','resource','capabilities'].includes(kind)?connectedIds(state).join(','):null,
    key=JSON.stringify([kind,path,identity,selection]);
   if(flights.has(key))return flights.get(key);
   let statuses=readStatuses.get(state);if(!statuses){statuses=new Map();readStatuses.set(state,statuses);}
   const status=stamp({status:'loading',error:''});statuses.set(kind,status);
   const pending=(async()=>{
    try{
     for(let attempt=0;attempt<3;attempt++){
      const observed=facts(kind),value=await request(path,options);
      if(context!==contextSignature(state,getScope())||selection!==null&&selection!==connectedIds(state).join(',')){status.status='superseded';return null;}
      if(observed!==facts(kind))continue;
      const result=validate(kind,value);
      status.status=result.error?'error':'ready';status.error=result.error||'';
      if(!result.error){stamp(result);if(kind==='models')stamp(result.channels);if(kind.startsWith('probe:'))stamp(result.channel.probe);}
      return result;
     }
     throw Error('渠道状态正在变化，请重新读取。');
    }catch(error){status.status='error';status.error=error.message||'读取失败';throw error;}
   })().finally(()=>{if(flights.get(key)===pending)flights.delete(key);});
   flights.set(key,pending);return pending;
  }
  async function action(name,id){
   const account=getScope(),channel=(state.channels||[]).find(row=>same(row.id,id)),sequence=channel?.changeSequence;
   // Writes are never coalesced or replayed. Their original UI operation owns
   // recovery; only safe reads share a flight.
   const value=await request('/api/channel/'+Number(id)+'/'+name,{method:'POST'});
   if(account!==getScope()||!(state.channels||[]).includes(channel)||sequence!==channel?.changeSequence)return null;
   if(value?.error)return value;
   if(!value?.channel||!same(value.channel.id,id)||![true,false,0,1].includes(value.channel.enabled)||name==='connect'&&!value.channel.probe?.status)throw Object.assign(Error('渠道操作结果尚未确认，请重新检测。'),{code:'mutation_outcome_unknown'});
   stamp(value.channel.probe);return value;
  }
  const query=(path,params)=>path+(params.toString()?'?'+params.toString():'');
  async function configuration(includeModels=true,options={}){
   const definitions=await read('channels','/api/channels');if(!definitions||definitions.error)return definitions;
   state.channels=definitions.channels.map(record=>{const previous=(state.channels||[]).find(row=>same(row.id,record.id));if(!previous)return record;applyChannel(state,previous,record);return previous;});
   state.providerCatalog=definitions.providers||[];
   state.channelDefinitionsScope=displayScope(state);
   if(includeModels&&options.progressive){
    const context=contextSignature(state,getScope());
    if(!state.channels.length){state.modelCatalog=stamp([]);state.modelCatalogReady=true;options.onCatalog?.({channels:state.modelCatalog});}
    const pending=(state.channels||[]).map(async channel=>{
     let result;
     try{result=await read('models','/api/model-catalog?channel_ids='+encodeURIComponent(channel.id)+(options.force?'&refresh=1':''));if(!result)return;if(result.error)throw Error(result.error);if(result.channels.length!==1||!same(result.channels[0].channel_id,channel.id))throw Error('模型目录与所选渠道不一致');}
     catch(error){result={channels:[{channel_id:channel.id,status:'error',models:[],error:error.message}]};}
     if(context!==contextSignature(state,getScope()))return;
     const previous=currentObservation(state,state.modelCatalog,false)?state.modelCatalog:[],incoming=result.channels.map(row=>{
      const old=rowFor(previous,row.channel_id);
      return row.status==='error'&&!denied(row)&&old?.status==='ready'?{...old,refresh_error:row.error||'模型目录暂时无法更新'}:row;
     }),ids=new Set(incoming.map(row=>String(row.channel_id)));
     state.modelCatalog=stamp([...previous.filter(row=>!ids.has(String(row.channel_id))&&(state.channels||[]).some(c=>same(c.id,row.channel_id))),...incoming]);
     state.modelCatalogReady=true;state.modelCatalogReadState='ready';
     options.onCatalog?.({channels:state.modelCatalog,revalidating:result.revalidating});
     if(result.revalidating){
      const fresh=await read('models','/api/model-catalog?channel_ids='+encodeURIComponent(channel.id)+'&wait=1').catch(()=>null);
      if((!fresh||fresh.error)&&context===contextSignature(state,getScope())){state.modelCatalog=stamp(state.modelCatalog.map(row=>same(row.channel_id,channel.id)?{...row,refresh_error:'模型目录暂时无法更新'}:row));options.onCatalog?.({channels:state.modelCatalog});}
      if(fresh&&!fresh.error&&context===contextSignature(state,getScope())){
       state.modelCatalog=stamp([...state.modelCatalog.filter(row=>!same(row.channel_id,channel.id)),...fresh.channels]);options.onCatalog?.({channels:state.modelCatalog});
      }
     }
    });
    await Promise.all(pending);
    return context===contextSignature(state,getScope())?{channels:state.channels,providers:state.providerCatalog,catalog:{channels:state.modelCatalog||[]}}:null;
   }
   // Model observations must be scoped to the confirmed configuration, not
   // stamped against an old/empty channel list fetched in parallel at boot.
   const models=includeModels?await read('models','/api/model-catalog'):null;
   if(includeModels&&!models)return null;
   return {channels:state.channels,providers:state.providerCatalog,catalog:models};
  }
  async function extensions(force){
   const context=contextSignature(state,getScope());
   for(let attempt=0;attempt<2;attempt++){
    if((state.channels||[]).some(channel=>channel.enabled&&!connection(state,channel).known)){
     const status=await read('status','/api/environment');
     if(context!==contextSignature(state,getScope()))return null;
     if(!status)continue;if(status.error)return status;syncEnvironment(state,status);
     if((state.channels||[]).some(channel=>channel.enabled&&!connection(state,channel).known))throw Error('渠道状态尚未确认，请重新检测。');
    }
    const params=new URLSearchParams({channel_ids:connectedIds(state).join(',')});if(force)params.set('refresh','1');
    const value=await read('extensions',query('/api/environment',params));
    if(value||context!==contextSignature(state,getScope()))return value;
    // A concurrent read may have established connection facts while this safe
    // inventory read was pending. Retry once against those facts, never writes.
   }
   return null;
  }
  return Object.freeze({
   invalidate:()=>{state.channelMutationVersion=(state.channelMutationVersion||0)+1;},
   identity:kind=>JSON.stringify([signature(state,getScope()),kind==='extensions'?connectedIds(state):null]),
   channels:()=>read('channels','/api/channels'),
   configuration,
   status:force=>read('status',force?'/api/environment?refresh=1':'/api/environment'),
   models:(force,options={})=>read('models','/api/model-catalog'+(force?'?refresh=1':options.wait?'?wait=1':'')),
   usage:force=>{const identity=signature(state,getScope());if(!force&&usageCache?.identity===identity&&Date.now()-usageCache.at<60000)return Promise.resolve(usageCache.value);return read('usage','/api/channel-usage').then(value=>{if(value&&!value.error&&currentObservation(state,value,false))usageCache={identity:snapshots.get(value).identity,at:Date.now(),value};return value;});},
   resources:(id,plugin)=>connectedIds(state).includes(String(id))?read('resources','/api/environment/plugin-resources?channel_id='+Number(id)+'&plugin_id='+encodeURIComponent(plugin)):Promise.reject(Error('模型渠道尚未连接。')),
   resourceFile:(token,path)=>read('resource','/api/environment/plugin-resource/'+encodeURIComponent(token)+'?path='+encodeURIComponent(path)),
   capabilityPage:async(id,{after='',query:search='',limit=40,chatId=null}={})=>{
    const context=contextSignature(state,getScope());
    const channel=(state.channels||[]).find(row=>same(row.id,id));
    if(!channel)throw Error('请先选择模型渠道。');
    if(!connection(state,channel).known){const status=await read('status','/api/environment');if(!status||context!==contextSignature(state,getScope()))return null;if(status.error)return status;syncEnvironment(state,status);}
    if(!connectedIds(state).includes(String(id)))throw Error('模型渠道尚未连接。');
    const params=new URLSearchParams({channel_id:String(id),limit:String(limit),q:search});if(after)params.set('after',after);if(state.localLibrary&&chatId&&chatId!=='new')params.set('chat_id',String(chatId));
    const value=await read('capabilities',query('/api/environment/capabilities',params));
    if(value&&!value.error&&!same(value.channel_id,id))throw Error('技能分页渠道不一致。');
    return value;
   },
   extensions,
   probe:id=>read('probe:'+id,'/api/channel/'+Number(id)+'/probe',{method:'POST'}),
   connect:id=>action('connect',id),disconnect:id=>action('remove',id),
  });
 }
 function client(state,request,getScope){let value=clients.get(state);if(!value){value=create(state,request,getScope);clients.set(state,value);}return value;}
 return Object.freeze({displayScope,displaySnapshot,restoreDisplay,composer,connection,nativeReady,connected,connectedIds,rows,usage,readState,definitionError,presentation,currentObservation,extensionsReady,catalog,automaticModel,hasSelectableModels,selectionIssue,syncEnvironment,applyUsage,applyChannel,validate,create,client});
});
