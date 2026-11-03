/* Platform transport only. Both hosts use CreatorWork's existing lifecycle. */
(()=>{
  'use strict';
  const native=()=>window.webkit?.messageHandlers?.runteamsCreatorWork;
  const works=new Map();let client=null,registration=null,identity=null,disposed=false;
  const account=()=>workspaceAccountCacheToken(),workspace=()=>String(S.activeOrganization||'');
  async function http(value,own=client){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),value.action==='message'?120000:30000);
    try{
    const response=await fetch('/api/work-host',{method:'POST',headers:{'Content-Type':'application/json','X-RunTeams-Work-Host':'1','X-RunTeams-Workspace':workspace()},
      body:JSON.stringify({...value,...(own?{client:own}:{})}),signal:controller.signal,keepalive:value.action==='detach'});
    const result=await response.json();if(!response.ok||result.error)throw Error(result.error||'工作界面暂时不可用');return result;
    }finally{clearTimeout(timeout);}
  }
  async function connect(){
    const current=account();if(identity!==current){clear();client=null;registration=null;identity=current;}
    if(disposed)throw Error('工作窗口已关闭');
    if(client)return client;
    if(!registration){const expected=identity;registration=http({action:'register'},null).then(result=>{
      if(expected!==account()||disposed){void http({action:'detach'},result.client).catch(()=>{});throw Error('工作界面已切换');}
      client=result.client;return client;
    }).finally(()=>{if(identity===expected)registration=null;});}
    return registration;
  }
  function send(work,value){work.node.contentWindow?.postMessage({channel:'runteams.work/1',id:work.id,epoch:work.epoch,...value},work.origin);}
  function valid(work){return works.get(work.id)===work&&identity===account()&&!disposed;}
  function destroy(work,closed=false){
    work.node.remove();work.readyReject?.(Error('工作界面已关闭'));work.fence?.reject(Error('工作界面已关闭'));works.delete(work.id);
    window.RunTeamsCreatorWork?.clearDisplay(work.id,work.epoch,closed);
  }
  function clear(closed=false){for(const work of [...works.values()])destroy(work,closed);}
  function bound(work){return {id:work.id,chat_id:work.chat,epoch:work.epoch};}
  function place(work,rect){
    if(!rect||!['x','y','width','height'].every(k=>Number.isFinite(rect[k]))||rect.x<0||rect.y<0||rect.width<1||rect.height<1||rect.x+rect.width>innerWidth+1||rect.y+rect.height>innerHeight+1)throw Error('工作界面尺寸无效');
    Object.assign(work.node.style,{left:rect.x+'px',top:rect.y+'px',width:rect.width+'px',height:rect.height+'px'});
  }
  async function display(work,value){
    const p=value.params;
    if(!p||typeof p!=='object'||Array.isArray(p)||typeof p.ticket!=='string'||!/^[0-9a-f-]{36}$/i.test(p.ticket))throw Error('ui_display_invalid');
    if(value.method==='cancel'){if(work.displayTicket===p.ticket)throw Error('ui_display_cancelled');return {cancelled:true};}
    if(work.displayTicket)throw Error('ui_display_busy');
    let next={...work.display};
    if(value.method==='present'&&Object.keys(p).sort().join(',')==='mode,ticket,viewId'&&['panel','full'].includes(p.mode)&&
      (p.mode==='panel'?p.viewId===null:typeof p.viewId==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(p.viewId))){next={...next,mode:p.mode,viewId:p.viewId};}
    else if(value.method==='header'&&Object.keys(p).sort().join(',')==='actions,text,ticket'&&typeof p.text==='string'&&[...p.text].length<=256&&Array.isArray(p.actions)&&p.actions.length<=8){
      const ids=new Set();for(const action of p.actions){
        if(!action||Object.keys(action).sort().join(',')!=='disabled,id,label'||typeof action.id!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(action.id)||ids.has(action.id)||typeof action.label!=='string'||!action.label.trim()||[...action.label].length>80||typeof action.disabled!=='boolean')throw Error('ui_display_invalid');ids.add(action.id);
      }
      next.header={revision:p.ticket,text:p.text,actions:p.actions};
    }else throw Error('ui_display_invalid');
    work.displayTicket=p.ticket;
    try{
      const expires=Date.now()+1800;
      let rect;
      while(valid(work)&&Date.now()<expires){
        try{rect=RunTeamsCreatorWork.applyDisplay(work.id,work.epoch,next,expires);break;}
        catch(error){if(error.message!=='display_unavailable')throw error;await new Promise(requestAnimationFrame);}
      }
      if(!valid(work)||!rect)throw Error('ui_display_stale');
      place(work,rect);work.display=next;
      const presentation={mode:next.mode,viewId:next.viewId};send(work,{kind:'presentation',presentation});return presentation;
    }finally{work.displayTicket=null;}
  }
  window.addEventListener('message',event=>{
    const value=event.data,work=works.get(value?.id);
    if(!work||!valid(work)||event.source!==work.node.contentWindow||event.origin!==work.origin||value.channel!=='runteams.work/1')return;
    if(value.kind==='ready'){
      const epoch=value.epoch;if(typeof epoch!=='string'||work.attaching===epoch)return;work.attaching=epoch;
      void (async()=>{
        await work.tail;if(!valid(work)||work.unknown||work.blocked)throw Error('工作界面状态尚未确认');
        const result=await http({action:'authority',id:work.id,chat_id:work.chat,epoch});
        if(!valid(work)||work.attaching!==epoch||result.authorized!==true)throw Error('工作界面已失效');
        if(work.epoch!==epoch){
          RunTeamsCreatorWork.clearDisplay(work.id,work.epoch);work.epoch=epoch;work.sequence=0;
          work.display={mode:'panel',viewId:null,header:{revision:'',text:'',actions:[]}};
        }
        work.readyResolve();send(work,{kind:'attached'});send(work,{kind:'environment',theme:work.theme});
      })().catch(error=>{if(work.readyReject)work.readyReject(error);else void close(work,true);});return;
    }
    if(value.epoch!==work.epoch)return;
    if(value.kind==='fenced'){
      if(work.fence?.ticket===value.ticket&&Number.isSafeInteger(value.sequence)&&value.sequence===work.sequence){work.blocked='frozen';work.fence.resolve(value.sequence);}
      else work.fence?.reject(Error('工作内容未完成同步'));return;
    }
    if(!['rpc','display'].includes(value.kind)||!Number.isSafeInteger(value.serial)||value.serial<1)return;
    const reply=(result,error)=>{if(valid(work)&&work.epoch===value.epoch)send(work,{kind:'reply',requestKind:value.kind,serial:value.serial,result,error});};
    if(value.kind==='display'){
      void display(work,value).then(result=>reply(result)).catch(error=>{reply(null,error.message);if(error.message!=='ui_display_busy')void close(work);});return;
    }
    if(work.blocked==='frozen'||value.serial!==work.sequence+1||work.queued>=4||!work.methods.includes(value.method)){reply(null,'ui_call_unavailable');return;}
    work.sequence=value.serial;work.queued++;
    work.tail=work.tail.then(async()=>{
      if(!valid(work)||work.unknown)throw Error('ui_reply_unknown');
      const result=await http({action:'message',...bound(work),sequence:value.serial,method:value.method,params:value.params});reply(result);
    }).catch(error=>{work.unknown=true;reply(null,error.message);}).finally(()=>{work.queued--;});
  });
  async function close(work,closed=false){
    destroy(work,closed);try{await http({action:'unmount',id:work.id,chat_id:work.chat});}catch{}
  }
  async function fence(work){
    if(work.blocked||work.unknown)throw Error('工作内容的状态尚未确认');work.blocked='preparing';
    const ticket=crypto.randomUUID();let timer;
    try{
      const sequence=await new Promise((resolve,reject)=>{work.fence={ticket,resolve,reject};timer=setTimeout(()=>reject(Error('工作内容未完成同步')),2000);send(work,{kind:'fence',ticket});});
      await work.tail;if(!valid(work)||work.unknown||sequence!==work.sequence)throw Error('工作内容未完成同步');return sequence;
    }catch(error){work.unknown=true;throw error;}finally{clearTimeout(timer);work.fence=null;}
  }
  async function call(value){
    if(native())return native().postMessage(value);
    await connect();
    if(value.action==='discover')return http(value);
    if(value.action==='open'){
      const {frame,...request}=value,result=await http(request);
      if(identity!==account())throw Error('工作界面已切换');
      const url=new URL(result.url);if(url.protocol!=='http:'||url.hostname!=='127.0.0.1')throw Error('工作界面地址无效');
      const node=document.createElement('iframe');node.title='工作';node.setAttribute('sandbox','allow-scripts allow-same-origin');node.referrerPolicy='no-referrer';
      Object.assign(node.style,{position:'fixed',border:'0',display:'none',zIndex:'8',background:'var(--panel)'});
      const work={...result,chat:result.chat_id,origin:url.origin,node,sequence:0,queued:0,tail:Promise.resolve(),theme:document.documentElement.dataset.theme==='dark'?'dark':'light',display:{mode:'panel',viewId:null,header:{revision:'',text:'',actions:[]}}};
      works.set(work.id,work);let timer;
      try{
        const ready=new Promise((resolve,reject)=>{work.readyResolve=resolve;work.readyReject=reject;timer=setTimeout(()=>reject(Error('工作界面加载超时')),15000);});
        place(work,frame);node.src=result.url;document.body.append(node);await ready;
        return {mounted:true,id:work.id,chat_id:work.chat};
      }catch(error){await close(work);throw error;}finally{clearTimeout(timer);work.readyReject=null;}
    }
    if(value.action==='detach'){clear();const own=client;client=null;return http({action:'detach'},own);}
    const work=works.get(value.id);if(!work||work.chat!==value.chat_id)throw Error('工作界面已失效');
    if(value.action==='unmount'){await close(work);return {mounted:false,id:work.id};}
    if(value.action==='frame'){place(work,value.frame);return {mounted:true};}
    if(value.action==='visibility'){work.node.style.display=value.visible?'block':'none';return {mounted:true};}
    if(value.action==='theme'){work.theme=value.theme;send(work,{kind:'environment',theme:work.theme});return {mounted:true};}
    if(value.action==='header-action'){
      const header=work.display.header,action=header.actions.find(action=>action.id===value.key);
      if(value.epoch!==work.epoch||value.revision!==header.revision||!action||action.disabled)throw Error('ui_action_stale');
      send(work,{kind:'action',action:{id:action.id,revision:header.revision}});return {delivered:true};
    }
    if(value.action==='context-changed')return http({action:'authority',...bound(work)});
    if(value.action==='submit'||value.action==='receipt'){
      const sequence=value.action==='submit'?await fence(work):null;
      const result=await http({...value,...bound(work),...(sequence===null?{}:{sequence})});
      if(['confirmed','rejected'].includes(result.state)){work.blocked=false;send(work,{kind:'release-fence'});}return result;
    }
    throw Error('工作界面请求无效');
  }
  setInterval(()=>{if(client&&!native())void http({action:'heartbeat'}).catch(()=>{clear(true);client=null;});},10000);
  window.addEventListener('pagehide',()=>{disposed=true;clear();if(client)void http({action:'detach'}).catch(()=>{});});
  window.RunTeamsWorkHost=Object.freeze({postMessage:call});
})();
