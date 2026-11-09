/* Employee and pipeline headers share the same status presentation and lifecycle. */
(() => {
 'use strict';
 const phases={
  needs_approval:[1,'需要处理','bell','notification-v3'],
  needs_human:[1,'需要处理','bell','notification-v3'],
  blocked:[2,'暂无法继续','alert'],
  interrupted:[2,'暂无法继续','alert'],
  failed:[2,'运行失败','x'],
  running:[3,'正在处理'],
  ready:[4,'等待开始','clock','clock'],
  waiting_retry:[4,'等待重试','refresh','refresh'],
 };
 const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
 const interval=6000;
 let active=null,player=null,motionContainer=null;

 function indicator(state){
  if(state==='running'){
   const dots=[3,8,13].flatMap(y=>[3,8,13].map(x=>`<circle cx="${x}" cy="${y}" r="1.65"/>`)).join('');
   return `<svg class="header-status-indicator" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">${dots}</svg>`;
  }
  const icon=state==='paused'?'pause':phases[state]?.[2],motion=phases[state]?.[3];
  return icon?`<span class="header-status-indicator" aria-hidden="true"${motion?` data-status-motion="${motion}"`:''}>${ICON(icon)}</span>`:'';
 }

 function markup(owner,items,{employee=false,previous=null}={}){
  const signature=employee?JSON.stringify(items):'';
  if(previous?.dataset.statusSignature===signature)return '';
  const attrs=employee?` data-employee-work-status="${esc(owner)}" data-status-signature="${esc(signature)}"`:'';
  if(!items.length)return employee?`<span hidden${attrs}></span>`:'';
  const slides=items.map(({id,state,text,label=text,labelKey,textKey,labelVars={name:text},action},index)=>{
   const vars=esc(JSON.stringify(labelVars));
   const titleKey=labelKey?` data-app-i18n-title="${esc(labelKey)}" data-app-i18n-aria-label="${esc(labelKey)}" data-app-i18n-vars="${vars}"`:'';
   const content=`<span class="header-status-text"${textKey?` data-app-i18n="${esc(textKey)}" data-app-i18n-vars="${vars}"`:''}>${esc(text)}</span>${indicator(state)}`;
   const current=index===0,tag=action?'button':'span';
   return `<${tag} class="header-status-slide${current?' is-current':''}" data-status-id="${esc(id||'')}"${state?` data-task-state="${esc(state)}"`:''} title="${esc(label)}"${action||labelKey?` aria-label="${esc(label)}"`:''}${titleKey}${employee&&!id?' role="status"':''}${action?` type="button" onclick="${esc(action)}"`:''}${current?'':` aria-hidden="true"${action?' tabindex="-1"':''}`}>${content}</${tag}>`;
  }).join('');
  return `<span class="header-status"${attrs}><span class="header-status-carousel" data-status-owner="${esc(owner)}">${slides}</span></span>`;
 }

 function updateMotion(){
  if(!player?.isLoaded)return;
  if(reducedMotion.matches)player.goToAndStop(0,true);
  else player.play();
 }
 reducedMotion.addEventListener('change',updateMotion);

 function playIndicator(slide){
  player?.destroy();
  player=null;
  motionContainer?.parentElement?.classList.remove('has-motion');
  motionContainer?.remove();
  motionContainer=null;
  const icon=slide?.querySelector('[data-status-motion]');
  const animationData=window.RunTeamsPipelineStatusMotion?.[icon?.dataset.statusMotion];
  if(!animationData||!window.lottie)return;
  const container=document.createElement('span');
  container.className='header-status-motion';
  icon.append(container);
  motionContainer=container;
  player=window.lottie.loadAnimation({container,renderer:'svg',loop:true,autoplay:false,animationData:structuredClone(animationData)});
  player.addEventListener('DOMLoaded',()=>{
   if(motionContainer!==container)return;
   icon.classList.add('has-motion');
   updateMotion();
  });
 }

 function show(state,index,animate=false){
  const {carousel,slides}=state;
  const outgoing=carousel.querySelector('.is-current'),incoming=slides[index];
  carousel.querySelector('.is-leaving')?.classList.remove('is-leaving');
  if(outgoing&&outgoing!==incoming){
   outgoing.classList.remove('is-current','is-entering');
   outgoing.classList.toggle('is-leaving',animate);
   outgoing.setAttribute('aria-hidden','true');
   if(outgoing.matches('button'))outgoing.tabIndex=-1;
  }
  incoming.classList.add('is-current');
  incoming.classList.toggle('is-entering',animate);
  incoming.removeAttribute('aria-hidden');
  if(incoming.matches('button'))incoming.removeAttribute('tabindex');
  state.index=index;
  playIndicator(incoming);
 }

 function reset(){
  if(active)clearInterval(active.timer);
  active=null;
  playIndicator(null);
 }

 function rotate(state){
  const {carousel,slides,index}=state;
  if(!carousel.isConnected){reset();return;}
  if(document.hidden||!carousel.getClientRects().length||carousel.matches(':hover,:focus-within'))return;
  show(state,(index+1)%slides.length,!reducedMotion.matches);
 }

 function sync(){
  const carousel=document.querySelector('#rgPipelineHead .header-status-carousel, #rgMid .conversation-panel-header .header-status-carousel');
  if(carousel===active?.carousel)return;
  if(!carousel){if(active)reset();return;}
  const owner=carousel.dataset.statusOwner;
  if(active?.owner!==owner)reset();
  const remembered=active?.slides[active.index]?.dataset.statusId;
  const slides=[...carousel.children];
  const state=active||{owner,timer:null};
  Object.assign(state,{carousel,slides});
  active=state;
  const finishTransition=event=>{
   if(event.animationName!=='header-status-in'||event.target!==slides[state.index])return;
   event.target.classList.remove('is-entering');
   carousel.querySelector('.is-leaving')?.classList.remove('is-leaving');
  };
  carousel.addEventListener('animationend',finishTransition);
  carousel.addEventListener('animationcancel',finishTransition);
  show(state,Math.max(0,slides.findIndex(slide=>slide.dataset.statusId===remembered)));
  if(slides.length>1)state.timer??=setInterval(()=>rotate(state),interval);
  else if(state.timer!==null){clearInterval(state.timer);state.timer=null;}
 }

 window.RunTeamsHeaderStatus=Object.freeze({phases,markup,sync,reset});
 window.addEventListener('runteams:business-scope-will-change',reset);
})();
