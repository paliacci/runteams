/* Per-device read receipts contain message IDs only. Runtime/message facts stay authoritative. */
(function(root,factory){const value=factory(root);if(typeof module==='object'&&module.exports)module.exports=value;root.RunTeamsChatActivity=value;})(typeof window==='object'?window:globalThis,function(root){
 'use strict';
 const clients=new WeakMap(),number=value=>Number.isSafeInteger(Number(value))&&Number(value)>0?Number(value):0;
 function identity(state){const account=state.account||{};return account.signed_in&&account.user_id?JSON.stringify([account.auth_issuer||'',account.user_id,account.device_data_scope||'',state.activeOrganization||'']):'';}
 function context(state){return JSON.stringify([identity(state),state.accountReadEpoch||0]);}
 function key(state){const scope=identity(state);return scope&&/^[a-f0-9]{64}$/.test(state.account?.device_data_scope||'')?'runteams.device.chat-read.v1:'+encodeURIComponent(scope):'';}
 function stored(storageKey){try{const value=storageKey&&JSON.parse(root.localStorage?.getItem(storageKey)||'null');if(value?.version!==1||!value.read||typeof value.read!=='object'||Array.isArray(value.read))return new Map();return new Map(Object.entries(value.read).filter(([id,seen])=>number(id)&&Number.isSafeInteger(seen)&&seen>=0).map(([id,seen])=>[String(number(id)),seen]));}catch(error){return new Map();}}
 function client(state){const scope=context(state);let value=clients.get(state);if(!value||value.scope!==scope){value={scope,key:key(state),read:stored(key(state)),panels:new Map(),interactions:new Map(),reads:new Map()};clients.set(state,value);}return value;}
 function save(value){if(!value.key)return;try{for(const [id,seen] of stored(value.key))value.read.set(id,Math.max(seen,value.read.get(id)||0));root.localStorage?.setItem(value.key,JSON.stringify({version:1,read:Object.fromEntries(value.read)}));}catch(error){}}
 function lastReply(panel){
  let last=null;
  for(const message of panel?.messages||[]){if(!['bot','assistant'].includes(message.role)||message.streaming||message.ephemeral||!number(message.id))continue;if(!last||number(message.id)>last.id){const metadata=message.metadata||{},trace=message.trace||metadata.trace||{},notice=message.systemNotice||metadata.system_notice||{};last={id:number(message.id),completed:!message.stopped&&!metadata.stopped&&!message.failed&&!metadata.failed&&!metadata.incomplete&&!trace.failed&&!trace.cancelled&&trace.complete!==false&&!['error','stopped'].includes(notice.kind)};}}
  return last;
 }
 function facts(value,row){
  const panels=value.panels.get(String(number(row.id)))||[],reply={id:number(row.last_bot_message_id),completed:row.last_bot_message_completed===true};
  for(const panel of panels){const local=lastReply(panel);if(local&&(local.id>reply.id||local.id===reply.id&&typeof row.last_bot_message_completed!=='boolean'))Object.assign(reply,local);}
  const localRunning=panels.some(panel=>panel.busy&&(!(lastReply(panel)?.id)||panel.messages?.some(message=>message.streaming)));
  const terminal=reply.completed&&reply.id&&number(row.last_message_id)&&reply.id>=number(row.last_message_id);
  const live=panels.map(panel=>[...(panel.messages||[])].reverse().find(message=>message.streaming&&message.trace?.requests?.length)).find(Boolean);
  const interaction=value.interactions.get(String(number(row.id))),waiting=live?live.trace.requests.some(request=>request.status==='pending'):(typeof row.awaiting_user_input==='boolean'?row.awaiting_user_input:!!row.awaiting_reply&&interaction?.message===number(row.last_message_id)&&interaction.waiting)&&!terminal;
  return {reply,waiting,running:localRunning||!!row.awaiting_reply&&!terminal};
 }
 function sync(state,rows,panels=[],visible=null){
  const value=client(state);value.panels=new Map();
  if(!identity(state))return;
  for(const panel of new Set(panels)){const id=number(panel?.id);if(!id)continue;const list=value.panels.get(String(id))||[];list.push(panel);value.panels.set(String(id),list);}
  let changed=false;
  for(const row of rows||[]){const id=String(number(row.id));if(id==='0'||value.read.has(id))continue;value.read.set(id,facts(value,row).reply.id);changed=true;}
  // A selected row is not proof of reading: only the reply actually loaded in the visible chat counts.
  const seen=lastReply(visible);if(visible&&number(visible.id)&&seen&&seen.id>(value.read.get(String(number(visible.id)))||0)){value.read.set(String(number(visible.id)),seen.id);changed=true;}
  if(changed)save(value);
 }
 function started(state,id,expected=context(state)){
  if(expected!==context(state)||!identity(state)||!number(id))return false;
  const value=client(state),identifier=String(number(id));if(!value.read.has(identifier)){const row=(state.chats||[]).find(item=>number(item.id)===number(id));value.read.set(identifier,number(row?.last_bot_message_id));save(value);}return true;
 }
 function status(state,row){const value=client(state);if(!identity(state))return '';const fact=facts(value,row);if(fact.waiting)return 'waiting';if(fact.running)return 'running';return fact.reply.completed&&fact.reply.id>(value.read.get(String(number(row.id)))??fact.reply.id)?'unread':'';}
 function markup(state,row){const kind=status(state,row);if(kind==='waiting')return '<span class="rail-chat-pending" title="待用户处理">待用户处理</span>';return kind?`<span class="rail-chat-status ${kind}" role="img" aria-label="${kind==='running'?'正在回复':'有未读回复'}" title="${kind==='running'?'正在回复':'有未读回复'}"></span>`:'';}
 function needsRefresh(state,id,panel){const row=(state.chats||[]).find(item=>number(item.id)===number(id));return !!(row&&panel&&!panel.busy&&(facts(client(state),row).waiting||number(row.last_bot_message_id)>(lastReply(panel)?.id||0)));}
 async function refreshWaiting(state,read){
  if(!identity(state))return false;
  const value=client(state),scope=context(state),rows=(state.chats||[]).filter(row=>number(row.id)&&row.awaiting_reply===true&&typeof row.awaiting_user_input!=='boolean');
  const eligible=new Set(rows.map(row=>String(number(row.id))));let changed=false,index=0;
  for(const id of value.interactions.keys())if(!eligible.has(id)){value.interactions.delete(id);changed=true;}
  // Older running services expose questions through their existing read-only interaction route.
  await Promise.all(Array.from({length:Math.min(3,rows.length)},async()=>{while(index<rows.length&&scope===context(state)){
   const row=rows[index++],id=String(number(row.id)),message=number(row.last_message_id),key=JSON.stringify([id,message]);let pending=value.reads.get(key);
   if(!pending){pending=Promise.resolve().then(()=>scope===context(state)?read(`/api/chat/${id}/interaction`):null).catch(()=>null).finally(()=>{if(value.reads.get(key)===pending)value.reads.delete(key);});value.reads.set(key,pending);}
   const result=await pending,current=(state.chats||[]).find(item=>number(item.id)===number(row.id));
   if(scope!==context(state)||!current||current.awaiting_reply!==true||typeof current.awaiting_user_input==='boolean'||number(current.last_message_id)!==message||!result||result.error||typeof result.active!=='boolean'||!Array.isArray(result.requests))continue;
   const waiting=result.active&&result.requests.some(request=>request?.status==='pending'),prior=value.interactions.get(id);
   if(!prior||prior.message!==message||prior.waiting!==waiting){value.interactions.set(id,{message,waiting});changed=true;}
  }}));
  return changed&&scope===context(state);
 }
 function storageChanged(state,event){const value=client(state);if(!value.key||event.key!==value.key)return false;value.read=stored(value.key);return true;}
 return Object.freeze({context,sync,started,status,markup,needsRefresh,refreshWaiting,storageChanged});
});
