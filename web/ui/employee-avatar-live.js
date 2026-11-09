/* One active chat portrait. Lists, pickers and portable image bytes stay static. */
(function(global){
 'use strict';
 function create(win,doc){
  const reduced=win.matchMedia('(prefers-reduced-motion: reduce)'),fine=win.matchMedia('(pointer: fine)');
  let node=null,eyes=[],pupils=[],frame=0,timer=0,blink=null,last=0,x=0,y=0,tx=0,ty=0;
  let running=false,inView=true,pageVisible=true,destroyed=false;
  const removals=[],clock=()=>win.performance.now(),clamp=value=>Math.max(-1,Math.min(1,value));
  const observer=win.IntersectionObserver?new win.IntersectionObserver(entries=>{
   for(const entry of entries)if(entry.target===node){inView=entry.isIntersecting;refresh();}
  }):null;
  function listen(target,event,handler,options){target.addEventListener(event,handler,options);removals.push(()=>target.removeEventListener(event,handler,options));}
  function paint(open){
   for(const eye of eyes)eye.setAttribute('transform',`scale(1 ${open.toFixed(3)})`);
   for(const pupil of pupils)pupil.setAttribute('transform',`translate(${(x*.9).toFixed(3)} ${(y*.6).toFixed(3)})`);
  }
  function eligible(){
   if(!node?.isConnected||!pageVisible||doc.hidden||reduced.matches||!inView||!doc.hasFocus())return false;
   const rect=node.getBoundingClientRect();return rect.width>0&&rect.height>0;
  }
  function stop(){
   if(frame)win.cancelAnimationFrame(frame);if(timer)win.clearTimeout(timer);
   frame=timer=0;blink=null;running=false;x=y=tx=ty=0;
   if(node){paint(1);node.dataset.liveState='paused';}
  }
  function requestFrame(){if(!frame&&running)frame=win.requestAnimationFrame(tick);}
  function scheduleBlink(){
   if(timer||!running)return;
   timer=win.setTimeout(()=>{
    timer=0;if(!eligible()){stop();return;}
    blink=clock();last=blink;requestFrame();
   },3200+Math.random()*3600);
  }
  function tick(now){
   frame=0;if(!eligible()){stop();return;}
   const amount=1-Math.exp(-Math.max(1,Math.min(64,now-last))/65);last=now;
   x+=(tx-x)*amount;y+=(ty-y)*amount;
   if(Math.abs(tx-x)<.005)x=tx;if(Math.abs(ty-y)<.005)y=ty;
   let open=1;
   if(blink!==null){
    const elapsed=now-blink;
    if(elapsed<80)open=1-.96*Math.sin(Math.max(0,elapsed)/80*Math.PI/2);
    else if(elapsed<100)open=.04;
    else if(elapsed<220)open=.04+.96*Math.sin((elapsed-100)/120*Math.PI/2);
    else{blink=null;scheduleBlink();}
   }
   paint(open);
   if(blink!==null||x!==tx||y!==ty)requestFrame();
  }
  function refresh(){
   if(!eligible()){stop();return;}
   if(running)return;
   running=true;node.dataset.liveState='running';last=clock();scheduleBlink();
  }
  function unmount(){stop();observer?.disconnect();node=null;eyes=[];pupils=[];inView=true;}
  function sync(){
   if(destroyed)return;
   const next=doc.querySelector('#conversation_worker_avatar > svg[data-live-employee-avatar]');
   if(next!==node){
    unmount();node=next;
    if(node){eyes=[...node.querySelectorAll('.id-eye')];pupils=[...node.querySelectorAll('.id-pupil')];observer?.observe(node);paint(1);}
   }
   refresh();
  }
  function center(){tx=ty=0;if(running&&(x||y)){last=clock();requestFrame();}}
  listen(win,'pointermove',event=>{
   if(!running||!fine.matches||event.pointerType&&event.pointerType!=='mouse'&&event.pointerType!=='pen')return;
   if(!eligible()){stop();return;}
   const rect=node.getBoundingClientRect();
   tx=clamp((event.clientX-rect.left-rect.width/2)/180);ty=clamp((event.clientY-rect.top-rect.height/2)/160);
   last=clock();requestFrame();
  },{passive:true});
  listen(doc,'pointerleave',center);listen(win,'pointercancel',center);
  listen(doc,'visibilitychange',refresh);listen(win,'blur',stop);listen(win,'focus',refresh);
  listen(reduced,'change',refresh);listen(fine,'change',()=>{center();refresh();});
  listen(win,'runteams:business-scope-changed',unmount);
  listen(win,'pagehide',()=>{pageVisible=false;stop();});
  listen(win,'pageshow',()=>{pageVisible=true;sync();});
  function destroy(){unmount();destroyed=true;for(const remove of removals)remove();}
  return Object.freeze({sync,destroy});
 }
 if(typeof module==='object'&&module.exports)module.exports={create};
 else global.RunTeamsEmployeeAvatarLive=create(global,global.document);
})(typeof window==='undefined'?globalThis:window);
