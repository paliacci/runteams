/* Figma 793:114249. Reading failures share one recovery surface; no business data
 * or authorization decisions are cached here. A retry runs only its caller. */
(function(global){
'use strict';
const esc=value=>String(value??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const active=new Map(),last=new Map();
const refresh='<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20 11a8 8 0 1 0-2.5 6.2M20 4v7h-7"/></svg>';
const spinner='<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="8" stroke-dasharray="35 16"/></svg>';
const info='<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9"/><path d="M12 8v5m0 3v.1"/></svg>';
let getScope=()=>'';
const scope=()=>String(getScope());
const token=key=>scope()+'|'+key;
const keyOf=o=>String(o.key||o.retry||o.title||'read');
function button(options={}){
 const key=keyOf(options),busy=!!options.busy||active.has(token(key)),local=options.variant==='local',label=options.label||(local?'重试':'重新加载');
 const action=String(options.retry||'');if(!action)return '';
 return `<button type="button" class="rt-failure-retry${local?' rt-failure-retry--secondary':''}${label.length>(local?3:4)?' rt-failure-retry--wide':''}${options.compact?' rt-failure-retry--compact':''}${options.buttonClassName?' '+esc(options.buttonClassName):''}" data-read-scope="${esc(scope())}" data-read-retry="${esc(key)}" data-read-label="${esc(label)}" data-read-aria-label="${esc(options.ariaLabel||label)}" aria-label="${esc(busy?'加载中':options.ariaLabel||label)}" ${busy?'disabled aria-busy="true"':''} onclick="RunTeamsLoadFailure.retry(this,event,() => (${esc(action)}))"><span class="rt-failure-retry-icon" aria-hidden="true">${busy?spinner:refresh}</span><span class="rt-failure-retry-label">${esc(busy?'加载中':label)}</span></button>`;
}
function markup(options={}){
 const cacheKey=token(keyOf(options));if(!options.busy){last.set(cacheKey,{...options});if(last.size>200)last.delete(last.keys().next().value);}
 const variant=['page','modal','local'].includes(options.variant)?options.variant:'page',key=keyOf(options),title=String(options.title||'内容暂时无法加载');
 const note=options.note||'';
 const art=variant==='local'?`<span class="rt-failure-info">${info}</span>`:`<div class="rt-failure-art">${ART}</div>`;
 return `<div class="rt-load-failure rt-load-failure--${variant}${options.compact?' rt-load-failure--compact':''}${options.className?' '+esc(options.className):''}" data-load-failure="${variant}" data-read-state="${esc(key)}" role="alert">${art}<div class="rt-failure-copy"><b>${esc(title)}</b>${note?`<p>${esc(note)}</p>`:''}</div>${button({...options,key,variant})}</div>`;
}
function showBusy(button,busy){
 if(!button?.isConnected)return;button.disabled=busy;button.setAttribute('aria-busy',String(busy));
 const label=busy?'加载中':button.dataset.readLabel;button.setAttribute('aria-label',busy?label:button.dataset.readAriaLabel||label);
 const icon=button.querySelector('.rt-failure-retry-icon');if(icon)icon.innerHTML=busy?spinner:refresh;
 const text=button.querySelector('.rt-failure-retry-label');if(text)text.textContent=label;
}
async function retry(button,event,action){
 event?.preventDefault();event?.stopPropagation();const key=button?.dataset.readRetry||'',id=token(key);if(button?.disabled||active.has(id)||button?.dataset.readScope!==undefined&&button.dataset.readScope!==scope())return;
 const focus=global.document?.activeElement===button,oldScope=scope();active.set(id,true);showBusy(button,true);
 try{return await action();}finally{
  active.delete(id);if(scope()===oldScope){const matches=Array.from(global.document?.querySelectorAll?.('[data-read-retry]')||[]).filter(n=>n.dataset.readRetry===key);matches.forEach(n=>showBusy(n,false));
   const restore=()=>{if(!focus||scope()!==oldScope)return;const candidates=Array.from(global.document?.querySelectorAll?.('[data-read-retry]')||[]).filter(n=>n.dataset.readRetry===key),target=candidates.find(n=>n.dataset.readLabel===button.dataset.readLabel)||candidates[0];if(target&&(!global.document.activeElement||global.document.activeElement===global.document.body||global.document.activeElement===button))target.focus({preventScroll:true});};
   // React and host pages may replace the button in the final render.
   if(global.requestAnimationFrame)global.requestAnimationFrame(restore);else restore();
  }
 }
}
const ART="<svg aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"280\" height=\"184\" viewBox=\"0 0 280 184\"><g transform=\"translate(0 0) scale(1.0)\" aria-hidden=\"true\"><ellipse cx=\"140\" cy=\"98\" rx=\"94\" ry=\"65\" fill=\"var(--accent-subtle)\" opacity=\".55\"/><ellipse cx=\"141\" cy=\"166\" rx=\"78\" ry=\"5\" fill=\"var(--border-control)\" opacity=\".10\"/><g transform=\"rotate(-8 124 89)\"><rect x=\"74\" y=\"32\" width=\"104\" height=\"119\" rx=\"10\" fill=\"var(--surface-subtle)\" stroke=\"var(--avatar-blue)\" stroke-width=\"1.4\" /><path d=\"M89 49h20m-20 15h57\" fill=\"none\" stroke=\"var(--avatar-blue)\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" opacity=\".22\"/></g><g transform=\"rotate(5 145 101)\"><rect x=\"85\" y=\"45\" width=\"113\" height=\"112\" rx=\"10\" fill=\"var(--surface)\" stroke=\"var(--avatar-blue)\" stroke-width=\"1.6\" /><path d=\"M86 68h111\" fill=\"none\" stroke=\"var(--border-default)\" stroke-width=\"1\" stroke-linecap=\"round\" stroke-linejoin=\"round\" /><circle cx=\"97\" cy=\"57\" r=\"2\" fill=\"var(--avatar-blue)\" opacity=\".45\"/><circle cx=\"105\" cy=\"57\" r=\"2\" fill=\"var(--avatar-blue)\" opacity=\".25\"/><rect x=\"101\" y=\"84\" width=\"26\" height=\"25\" rx=\"6\" fill=\"var(--editor-palette-bg-blue)\" stroke=\"none\" stroke-width=\"1\" /><path d=\"M137 89h42m-42 10h29M102 124h75m-75 11h53\" fill=\"none\" stroke=\"var(--avatar-blue)\" stroke-width=\"2.7\" stroke-linecap=\"round\" stroke-linejoin=\"round\" opacity=\".25\"/></g><circle cx=\"207\" cy=\"120\" r=\"29\" fill=\"var(--editor-palette-bg-blue)\" stroke=\"var(--avatar-blue)\" stroke-width=\"1.5\"/><circle cx=\"207\" cy=\"120\" r=\"22\" fill=\"var(--surface)\"/><g transform=\"translate(194 107) scale(1.0833333333333333)\"><path d=\"M20 11a8 8 0 1 0-2.5 6.2M20 4v7h-7\" fill=\"none\" stroke=\"var(--avatar-blue)\" stroke-width=\"1.65\" stroke-linecap=\"round\" stroke-linejoin=\"round\" /></g><path d=\"M52 90v10m-5-5h10M227 40v8m-4-4h8\" fill=\"none\" stroke=\"var(--avatar-blue)\" stroke-width=\"1.4\" stroke-linecap=\"round\" stroke-linejoin=\"round\" opacity=\".7\"/><circle cx=\"61\" cy=\"133\" r=\"3\" fill=\"var(--editor-palette-bg-blue)\"/><circle cx=\"224\" cy=\"72\" r=\"2.5\" fill=\"var(--avatar-blue)\" opacity=\".3\"/></g></svg>";
function pending(key){const id=token(String(key)),options=last.get(id);return active.has(id)&&options?markup({...options,busy:true}):'';}
global.RunTeamsLoadFailure={markup,button,retry,pending,connect:readScope=>{getScope=readScope;},isPending:key=>active.has(token(String(key)))};
})(typeof window==='undefined'?globalThis:window);
