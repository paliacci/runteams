/* Injected at document start into the entry page, never the nested MCP app. */
(()=>{
  'use strict';
  const config=null/*__HOST_CONFIG__*/;
  if(window.parent===window)return;
  const requests=new Map(),listeners=new Set(),actions=new Set();
  let sequence=0,displaySequence=0,frozen=false,attach;
  const attached=new Promise(resolve=>{attach=resolve;});
  let snapshot=Object.freeze({theme:'light',presentation:Object.freeze({mode:'panel',viewId:null})});
  const post=value=>parent.postMessage({channel:'runteams.work/1',id:config.id,epoch:config.epoch,...value},config.parent);
  const request=(kind,method,params={})=>{
    if(frozen&&kind==='rpc')return Promise.reject(Error('ui_chat_pending'));
    if(requests.size>=4)return Promise.reject(Error('ui_busy'));
    const serial=kind==='rpc'?++sequence:++displaySequence,key=kind+':'+serial;
    return new Promise((resolve,reject)=>{
      // An expired RPC is unknown, never retried. Freeze subsequent SDK writes.
      const timer=setTimeout(()=>{requests.delete(key);if(kind==='rpc')frozen=true;reject(Error('ui_reply_unknown'));},kind==='rpc'?120000:2500);
      requests.set(key,{resolve,reject,timer});void attached.then(()=>post({kind,serial,method,params}));
    });
  };
  window.addEventListener('message',event=>{
    const value=event.data;
    if(event.source!==parent||event.origin!==config.parent||value?.channel!=='runteams.work/1'||value.id!==config.id||value.epoch!==config.epoch)return;
    if(value.kind==='attached'){attach();
    }else if(value.kind==='reply'){
      const key=value.requestKind+':'+value.serial,own=requests.get(key);if(!own)return;
      requests.delete(key);clearTimeout(own.timer);value.error?own.reject(Error(value.error)):own.resolve(value.result);
    }else if(value.kind==='environment'){
      if(!['light','dark'].includes(value.theme))return;
      snapshot=Object.freeze({...snapshot,theme:value.theme});for(const listener of listeners){try{listener();}catch{}}
    }else if(value.kind==='presentation'){
      snapshot=Object.freeze({...snapshot,presentation:Object.freeze(value.presentation)});for(const listener of listeners){try{listener();}catch{}}
    }else if(value.kind==='action'){
      for(const listener of actions){try{listener(value.action);}catch{}}
    }else if(value.kind==='fence'){
      frozen=true;post({kind:'fenced',ticket:value.ticket,sequence});
    }else if(value.kind==='release-fence'){frozen=false;}
  });
  Object.defineProperty(window,'runteamsUI',{value:Object.freeze({methods:Object.freeze(config.methods),call:(method,params={})=>request('rpc',method,params)}),writable:false,configurable:false});
  Object.defineProperty(window,'runteamsHost',{value:Object.freeze({version:'0.1.0',kind:'platform',
    capabilities:Object.freeze(['presentation','drawer-header']),getSnapshot:()=>snapshot,
    request:(method,params={})=>request('display',method,params),
    subscribe(listener){if(typeof listener!=='function')throw TypeError('listener');listeners.add(listener);return()=>listeners.delete(listener);},
    onAction(listener){if(typeof listener!=='function')throw TypeError('listener');actions.add(listener);return()=>actions.delete(listener);}
  }),writable:false,configurable:false});
  post({kind:'ready'});
})();
