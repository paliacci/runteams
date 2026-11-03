/* Original work UI recovery state lives with its actual device/library owner. */
(()=>{
 'use strict';
 const kinds=['pipeline-admission','pipeline-control','pipeline-create','pipeline-settings','pipeline-flow','employee-schedule-operation'];
 const token=()=>`${_workspaceBusinessGeneration}:${workspaceAccountCacheToken()}`;
 const path='/api/device/work/source-pipelines/ui-state-';
 let active=null;
 const state=()=>{const scope=token();if(!active||active.scope!==scope)active={scope,ready:false,values:new Map(),versions:new Map(),queue:[],reading:null,draining:null,error:null};return active;};
 const current=s=>s===active&&s.scope===token();
 function key(value){
  const kind=typeof value==='string'&&kinds.find(kind=>{const prefix='runteams.'+kind+':'+workspaceDeviceStorageScope();return value===prefix||value.startsWith(prefix+':');});
  if(!kind)throw Error('工作界面保存位置无效。');
  return kind+value.slice(('runteams.'+kind+':'+workspaceDeviceStorageScope()).length);
 }
 async function connect(){
  const s=state();if(s.ready)return;if(s.reading)return s.reading;
  s.reading=(async()=>{
   const result=await api(path+'read','POST',{});if(!current(s))throw Error('资料库已改变，请重新打开。');
   if(result.error)throw Error(result.error);
   if(result.schema!=='runteams.work-ui-state-list/1'||!result.items||typeof result.items!=='object'||Array.isArray(result.items))throw Error('原操作界面资料未能核对。');
   const versions=new Map(),values=new Map();
   for(const [k,row] of Object.entries(result.items)){
    if(!kinds.includes(k.split(':',1)[0])||!Number.isSafeInteger(row.revision)||row.revision<1||row.value!==null&&typeof row.value!=='string')throw Error('原操作界面资料无效。');
    versions.set(k,row.revision);if(row.value!==null)values.set(k,row.value);
   }
   s.versions=versions;s.values=values;s.ready=true;s.error=null;
  })().finally(()=>{s.reading=null;});return s.reading;
 }
 function getItem(value){const s=state();return s.ready?s.values.get(key(value))??null:null;}
 function change(value,raw){
  const s=state();if(!s.ready)throw Error('原操作尚未载入，请重新打开。');
  const k=key(value);if(raw!==null){JSON.parse(raw);s.values.set(k,raw);}else s.values.delete(k);
  s.queue.push({key:k,value:raw,operation_id:crypto.randomUUID()});
  queueMicrotask(()=>{if(current(s))void flush().catch(()=>{});});
 }
 async function flush(){
  const s=state();await connect();if(!current(s))throw Error('资料库已改变，请重新打开。');if(s.draining)return s.draining;
  s.draining=(async()=>{
   while(s.queue.length){
    if(!current(s))throw Error('工作区已改变，原界面保存已停止。');
    const row=s.queue[0];row.expected_revision??=s.versions.get(row.key)||0;
    const result=await api(path+'save','POST',{...row});
    if(!current(s))throw Error('工作区已改变，旧回执不会应用到当前页面。');
    if(result.error)throw Object.assign(Error(result.error),{code:result.code});
    if(result.operation_id!==row.operation_id||result.revision!==row.expected_revision+1)throw Error('界面保存回执待核对。');
    s.versions.set(row.key,result.revision);s.queue.shift();s.error=null;
   }
  })().catch(error=>{s.error=error;throw error;}).finally(()=>{s.draining=null;});return s.draining;
 }
 window.RunTeamsWorkState=Object.freeze({connect,getItem,setItem:(k,v)=>change(k,v),removeItem:k=>change(k,null),flush,
  get ready(){return state().ready;},get pending(){const s=state();return !!(s.queue.length||s.reading||s.draining);},
  get pendingSave(){const s=state();return !!(s.queue.length||s.draining);},
  // A confirmed rejected save stays queued and blocks business sends; native quit can explicitly discard this unsaved draft.
  get saveRejected(){const s=state();return !!s.queue.length&&!s.draining&&(s.error?.code==='work_ui_state_conflict'||[400,409,413,415].includes(s.error?.status));},get error(){return state().error;}});
})();
