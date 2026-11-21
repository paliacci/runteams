/* UI-only orchestration over the existing conversation transport; no model SDK. */
globalThis.RunTeamsReplyGeneration=(()=>{
 const parse=text=>{
  if(typeof text!=='string'||text.length>150000)throw Error('模型输出为空或过长，请调整数据后重试。');
  const candidates=[];try{candidates.push(JSON.parse(text.trim()));}catch{}
  if(!candidates.length)for(const match of text.matchAll(/```(?:json|runteams-view)\s*\n([\s\S]*?)\n```/g)){try{candidates.push(JSON.parse(match[1]));}catch{}}
  const specs=candidates.map(v=>v?.spec??v).filter(v=>v&&typeof v.root==='string'&&v.elements&&typeof v.elements==='object');
  if(specs.length!==1)throw Error('模型没有返回唯一的有效展示描述。可以查看原始输出后重试。');return specs[0];
 };
 function create({request,stream,validate,parseOutput=parse,onChange=()=>{},onOutput=()=>{},persist=()=>{}}){
  let run=null;const emit=(phase,message)=>onChange({phase,message,run});
  function finish(result){
   const owner=run;persist(null);run=null;
   if(owner.stopping||result?.incomplete){emit('stopped','生成已停止。');return;}
   onOutput(String(result?.reply||''));
   if(result?.failed)throw Error(result.reply||'模型生成失败，请检查当前渠道后重试。');
   const value={version:2,title:owner.title,data:owner.data,spec:parseOutput(result?.reply)};validate(value);emit('complete','AI 已生成展示描述。');return value;
  }
  async function generate({data,title,prompt,config}){
   if(run)throw Error('上一轮尚未结束，请先停止或核对状态。');
   // Validate a snapshot without choosing a presentation for the model.
   const snapshot=JSON.parse(JSON.stringify(data));validate({version:2,title,data:snapshot,spec:{root:'input',elements:{input:{type:'Detail',props:{title,value:{$state:'/data'}},children:[]}}}});
   run={data:snapshot,title,config,id:null,accepted:false,stopping:false};emit('starting','正在准备模型调用…');onOutput('');const owner=run;let result=null,terminal=false,finishing=false;
   try{
    const created=await request('/api/conversations','POST',{kind:'general',...config,extensions_enabled:false,context:{context_type:'general',intent:'general',ambient_disabled:true}});
    if(created?.error||!created?.session?.id)throw Error(created?.error||'未能创建测试会话。');run.id=created.session.id;persist(run);
    if(run.stopping){persist(null);run=null;emit('stopped','生成已停止。');return;}
    emit('running','正在等待 AI 选择组件并生成展示描述…');
    await stream(`/api/chat/${run.id}/stream`,{message:prompt,attachments:[],capabilities:[]},event=>{
     if(run!==owner)return;
     if(event.type==='accepted'){run.accepted=true;run.messageId=event.message_id;persist(run);if(run.stopping)void stop();}
     else if(event.type==='agent_event'){const kind=event.event?.kind;emit(run.stopping?'stopping':'running',run.stopping?'正在停止生成…':kind==='tool_call'?'AI 正在处理数据…':'AI 正在生成展示描述…');}
     else if(event.type==='result'){result=event;terminal=true;}
     else if(event.type==='cancelled'){result={incomplete:true};terminal=true;}
     else if(event.type==='error'){terminal=true;throw Error(event.message||'模型调用失败。');}
    });
    if(run!==owner)return;
    if(!terminal)throw Error('连接中断，需核对本轮生成状态。');finishing=true;return finish(result);
   }catch(error){
    if(run!==owner&&!finishing)return;
    if(!run||terminal||!run.id||!run.accepted&&[400,403,404,409,413,415,422].includes(error.status)){persist(null);run=null;emit('error',error.message);}
    else{persist(run);emit('uncertain','连接中断，本轮可能仍在生成。请核对状态，避免重复调用。');}
    throw error;
   }
  }
  async function stop(){if(!run)return;run.stopping=true;persist(run);emit('stopping','正在停止生成…');if(run.id){const result=await request(`/api/chat/${run.id}/cancel`,'POST',{});if(result?.error){emit('uncertain',result.error);throw Error(result.error);}}}
  async function recover(saved){
   if(!run&&saved)run=saved;if(!run?.id)throw Error('没有待核对的生成任务。');emit('recovering','正在核对原生成任务…');
   try{
    const value=await request('/api/chat/'+run.id);if(value?.error)throw Error(value.error);
    const messages=value.messages||[],last=[...messages].reverse().find(m=>m.role==='bot'||m.role==='assistant');
    if(last)return finish({reply:last.text??last.content??'',failed:last.metadata?.failed,incomplete:last.metadata?.stopped});
    const active=await request(`/api/chat/${run.id}/interaction`);if(active?.error)throw Error(active.error);
    if(active.active===false){persist(null);run=null;emit('stopped','原生成任务已结束，未取得完整展示结果。可以重新生成。');return;}
    emit('uncertain','原生成任务仍在运行，可稍后核对或停止。');
   }catch(error){if(run)emit('uncertain','暂时无法核对原任务：'+error.message);else emit('error',error.message);throw error;}
  }
  return {generate,stop,recover,get pending(){return run!==null;}};
 }
 return {parse,create};
})();
