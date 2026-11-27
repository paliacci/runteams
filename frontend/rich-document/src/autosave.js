// One in-flight revision, with edits made during saving retained for the next save.
export function createAutosave({revision,initial,write,status,clean,delay=700,timeout=10000}){
 let latest=initial,baseline=JSON.stringify(initial),pending=null,timer,watchdog,action=null,disposed=false,failed=false;
 const dirty=()=>JSON.stringify(latest)!==baseline||!!(pending&&JSON.stringify(latest)!==JSON.stringify({name:pending.name,document:pending.document}));
 const schedule=()=>{clearTimeout(timer);if(dirty()&&!pending&&!failed)timer=setTimeout(flush,delay);};
 function writePending(){
  clearTimeout(watchdog);failed=false;status('saving');
  watchdog=setTimeout(()=>{if(!disposed&&pending){failed=true;status('error','尚未确认保存结果，请重试确认。');}},timeout);
  write(pending);
 }
 function flush(){
  clearTimeout(timer);if(disposed)return;
  if(pending){if(failed)writePending();return;}
  if(!dirty()){status('saved');clean(false);const next=action;action=null;next?.();return;}
  if(!latest.name.trim()){failed=true;status('error','请填写文档名称。');return;}
  pending={...latest,request_id:crypto.randomUUID(),base_revision:revision};writePending();
 }
 return {
  update(value){latest=value;clean(dirty());if(!pending&&!failed)status(dirty()?'pending':'saved');schedule();},
  flush,
  retry(){if(disposed)return;if(pending)writePending();else flush();},
  acknowledge(reply){
   if(disposed||!pending||reply.request_id!==pending.request_id)return;
   clearTimeout(watchdog);
   if(reply.error){if(!reply.unconfirmed)pending=null;failed=true;action=null;status('error',reply.error);return;}
   revision=reply.revision;baseline=JSON.stringify({name:pending.name,document:pending.document});pending=null;failed=false;
   clean(dirty());status(dirty()?'pending':'saved');
   if(dirty()){if(action)flush();else schedule();}else{const next=action;action=null;next?.();}
  },
  before(actionToRun){action=actionToRun;flush();},
  dispose(){disposed=true;clearTimeout(timer);clearTimeout(watchdog);}
 };
}
