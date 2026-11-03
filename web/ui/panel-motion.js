/* Shared panel lifecycle: rendering remains synchronous; motion never owns state. */
(function (global) {
  'use strict';
  const panels = {rail:'#rgRail', right:'#rgDrawer > .drawer', resources:'.skills-author-resources'};
  const regions = {main:'#rgMid', head:'#rgPipelineHead', tabs:'#rgWorkspaceTabs', conversation:'.skills-author-conversation'};
  const running = new Set(), exits = new Map(), owners = new WeakMap();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const bounds = node => {
    if (!node) return null;
    const r=node.getBoundingClientRect();
    return {x:r.x,y:r.y,width:r.width,height:r.height};
  };
  const visible = node => !!node && getComputedStyle(node).visibility !== 'hidden' &&
    node.getBoundingClientRect().width > 1 && node.getBoundingClientRect().height > 1;

  function cancel() {
    for (const job of running) job.animation.cancel();
    running.clear();
    for (const exit of exits.values()) exit.layer.remove();
    exits.clear();
  }

  function snapshot(node) {
    const copy=node.cloneNode(true);
    for (const n of [copy,...copy.querySelectorAll('[id]')]) n.removeAttribute('id');
    const original=[node,...node.querySelectorAll('*')], clones=[copy,...copy.querySelectorAll('*')];
    // Match scroll containers by their DOM position before sanitizing active embeds.
    for (let i=0;i<Math.min(original.length,clones.length);i++) {
      clones[i].scrollTop=original[i].scrollTop;clones[i].scrollLeft=original[i].scrollLeft;
    }
    // Exiting visuals must not start embedded applications or accept input.
    for (const n of copy.querySelectorAll('script,iframe,object,embed')) n.remove();
    copy.inert=true;copy.setAttribute('aria-hidden','true');
    return copy;
  }

  function capture(root, targets = {}) {
    const body=root?.querySelector('.product-shell');
    if (!body || reduced.matches) return null;
    const workspace=body.querySelector('.workspace-tab.on')?.dataset.workspaceKey || '';
    const result={body,workspace,panels:{},regions:{}};
    for (const [key,selector] of Object.entries(panels)) {
      const node=body.querySelector(selector), shown=visible(node);
      result.panels[key]={shown,rect:shown?bounds(node):null,
        copy:shown&&targets[key]===false?snapshot(node):null};
    }
    for (const [key,selector] of Object.entries(regions)) result.regions[key]=bounds(body.querySelector(selector));
    return result;
  }

  function timing(body) {
    const style=getComputedStyle(body), raw=style.getPropertyValue('--panel-motion-duration').trim();
    const duration=parseFloat(raw)*(raw.endsWith('ms')?1:1000);
    return {duration:Number.isFinite(duration)?duration:200,
      easing:style.getPropertyValue('--panel-motion-ease').trim()||'cubic-bezier(.2,.8,.2,1)',fill:'both'};
  }

  function play(node, frames, options, id, done) {
    if (typeof node.animate !== 'function') {done?.();return;}
    const animation=node.animate(frames,options);animation.id='runteams-panel:'+id;
    const job={node,animation};running.add(job);owners.set(node,job);node.dataset.panelMotion=id;
    const clean=()=>{running.delete(job);if(owners.get(node)===job){owners.delete(node);delete node.dataset.panelMotion;}done?.();};
    animation.onfinish=()=>{animation.cancel();clean();};
    animation.oncancel=clean;
  }

  function leave(old, key, options) {
    if (!old.copy) return;
    const layer=document.createElement('div');
    layer.className='product-shell ui-panel-motion-layer';layer.inert=true;layer.setAttribute('aria-hidden','true');
    const {x,y,width,height}=old.rect;
    Object.assign(layer.style,{left:x+'px',top:y+'px',width:width+'px',height:height+'px'});
    Object.assign(old.copy.style,{width:width+'px',height:height+'px',maxWidth:'none',visibility:'visible',animation:'none'});
    layer.appendChild(old.copy);document.body.appendChild(layer);exits.set(key,{layer});
    play(layer,[{transform:'translateX(0)'},{transform:`translateX(${key==='rail'?-width:width}px)`}],options,key+':close',()=>{
      layer.remove();if(exits.get(key)?.layer===layer)exits.delete(key);
    });
  }

  function finish(previous, root) {
    if (!previous) {if(reduced.matches)cancel();return;}
    const body=root?.querySelector('.product-shell');
    const workspace=body?.querySelector('.workspace-tab.on')?.dataset.workspaceKey || '';
    if (!body || workspace!==previous.workspace || body.classList.contains('workspace-switching') ||
        body.classList.contains('conversation-focus') || reduced.matches ||
        document.body.classList.contains('rail-resizing') || document.body.classList.contains('detail-resizing')) {cancel();return;}
    const current={}, changed=[];
    for (const [key,selector] of Object.entries(panels)) {
      const node=body.querySelector(selector), shown=visible(node);
      current[key]={node,shown,rect:shown?bounds(node):null};
      if(shown!==previous.panels[key].shown)changed.push(key);
    }
    if (!changed.length) return;
    // Capture a running exit before cancellation so a rapid reopen reverses smoothly.
    const reversals=new Map([...exits].map(([key,value])=>[key,bounds(value.layer)]));
    cancel();
    const options=timing(body);
    if(options.duration<=0)return;
    const mainAfter=bounds(body.querySelector(regions.main)), mainBefore=previous.regions.main;
    const movingMain=mainAfter&&mainBefore&&(Math.abs(mainAfter.x-mainBefore.x)>.5||Math.abs(mainAfter.width-mainBefore.width)>.5);
    for(const [key,selector] of Object.entries(regions)) {
      // Children already follow their parent's width/position during rail changes.
      if(key==='conversation'&&movingMain)continue;
      const node=body.querySelector(selector), before=previous.regions[key], after=bounds(node);
      if(!node||!before||!after||!before.width||!after.width)continue;
      const dx=before.x-after.x;
      if(Math.abs(dx)<.5&&Math.abs(before.width-after.width)<.5)continue;
      const from={transform:`translateX(${dx}px)`,width:before.width+'px'};
      const to={transform:'translateX(0)',width:after.width+'px'};
      if(key==='conversation') {
        Object.assign(from,{flexGrow:0,flexShrink:0,flexBasis:before.width+'px'});
        Object.assign(to,{flexGrow:0,flexShrink:0,flexBasis:after.width+'px'});
      }
      play(node,[from,to],options,key+':layout');
    }
    for(const key of changed) {
      const next=current[key];
      if(next.shown) {
        const offset=reversals.has(key)?reversals.get(key).x-next.rect.x:(key==='rail'?-next.rect.width:next.rect.width);
        const conversation=key==='resources'?body.querySelector(regions.conversation):null;
        const reveal=conversation&&getComputedStyle(conversation).visibility==='hidden';
        const savedVisibility=conversation?.style.visibility||'';
        if(reveal)conversation.style.visibility='visible';
        play(next.node,[{transform:`translateX(${offset}px)`},{transform:'translateX(0)'}],options,key+':open',()=>{
          if(reveal)conversation.style.visibility=savedVisibility;
        });
      } else leave(previous.panels[key],key,options);
    }
  }

  reduced.addEventListener('change',()=>{if(reduced.matches)cancel();});
  global.RunTeamsPanelMotion=Object.freeze({capture,finish,cancel});
})(window);
