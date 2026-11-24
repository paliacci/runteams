const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {create}=require('../web/ui/employee-avatar-live.js');
const registry=require('../web/ui/employee-avatars.js');

class Events{
 constructor(){this.listeners=new Map();}
 addEventListener(name,handler){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(handler);}
 removeEventListener(name,handler){this.listeners.get(name)?.delete(handler);}
 emit(name,event={}){for(const handler of this.listeners.get(name)||[])handler(event);}
 count(){return [...this.listeners.values()].reduce((sum,set)=>sum+set.size,0);}
}
function portrait(){
 const parts=()=>Array.from({length:2},()=>({attrs:{},setAttribute(key,value){this.attrs[key]=value;}}));
 return {dataset:{},isConnected:true,eyes:parts(),pupils:parts(),rect:{left:20,top:20,width:24,height:24},
  getBoundingClientRect(){return this.rect;},querySelectorAll(selector){return selector==='.id-eye'?this.eyes:this.pupils;}};
}
function fixture(){
 const win=new Events(),doc=new Events(),reduced=new Events(),fine=new Events();
 const frames=new Map(),timers=new Map();let now=100,nextId=0,focused=true,current=portrait(),intersection;
 reduced.matches=false;fine.matches=true;doc.hidden=false;doc.hasFocus=()=>focused;
 doc.querySelector=selector=>{assert.equal(selector,'#conversation_worker_avatar > svg[data-live-employee-avatar]');return current;};
 Object.assign(win,{matchMedia:query=>query.includes('reduced')?reduced:fine,performance:{now:()=>now},
  requestAnimationFrame:fn=>{frames.set(++nextId,fn);return nextId;},cancelAnimationFrame:id=>frames.delete(id),
  // Browser timer delays are whole milliseconds, even when blink jitter is fractional.
  setTimeout:(fn,delay)=>{timers.set(++nextId,{fn,due:now+Math.trunc(delay)});return nextId;},clearTimeout:id=>timers.delete(id),
  IntersectionObserver:class{constructor(fn){intersection=fn;}observe(){}disconnect(){}}});
 const controller=create(win,doc);
 return {win,doc,reduced,fine,frames,timers,controller,get node(){return current;},
  frame(delta=16){now+=delta;const pending=[...frames.values()];frames.clear();for(const fn of pending)fn(now);},
  settle(){for(let count=0;frames.size&&count<100;count++)this.frame(16);assert.equal(frames.size,0);},
  blink(){const [id,timer]=[...timers][0];timers.delete(id);now=timer.due;timer.fn();},
  intersect(value){intersection([{target:current,isIntersecting:value}]);},
  focus(value){focused=value;win.emit(value?'focus':'blur');},
  replace(value){current=value;},};
}

test('only the chat header embeds approved artwork; lists, picker and uploads stay images',()=>{
 const html=fs.readFileSync('web/index.html','utf8'),body=html.match(/^function workerAvatarMarkup\([^\n]+/m)[0];
 const context={RunTeamsEmployeeAvatars:registry,DEFAULT_EMPLOYEE_AVATAR:registry.defaultAvatar,workerAvatarSrc:registry.src,esc:String,ICON:()=>''};
 vm.runInNewContext(body,context);
 const worker={avatar:registry.defaultAvatar};
 const chat=context.workerAvatarMarkup(worker,{id:'conversation_worker_avatar',editor:true});
 assert.match(chat,/<button/);assert.match(chat,/openWorkerAvatarPicker/);assert.match(chat,/data-live-employee-avatar/);
 assert.match(context.workerAvatarMarkup(worker),/<img/);assert.doesNotMatch(context.workerAvatarMarkup(worker),/data-live-employee-avatar/);
 assert.doesNotMatch(context.workerAvatarMarkup(worker,{id:'worker_avatar'}),/data-live-employee-avatar/);
 assert.doesNotMatch(html.match(/panel.innerHTML=`<div class="worker-avatar-grid">[^\n]+/)[0],/<svg/);
 const custom=context.workerAvatarMarkup({avatar:'art/custom.png',avatar_src:'data:image/png;base64,AAAA'},{id:'conversation_worker_avatar'});
 assert.match(custom,/<img/);assert.doesNotMatch(custom,/data-live-employee-avatar/);
 assert.match(html,/RunTeamsEmployeeAvatarLive.sync\(\)/);
});

test('all owned presets have stable inline artwork, independent local IDs and hidden decorative semantics',()=>{
 const catalog=JSON.parse(fs.readFileSync('web/worker-avatars/presets.json'));
 for(const item of catalog.presets){
  const ref='preset:colleague:'+item.id,markup=registry.liveMarkup(ref);
  assert.equal(markup,registry.liveMarkup(ref));assert.match(markup,/aria-hidden="true"/);assert.match(markup,/focusable="false"/);
  assert.equal((markup.match(/class="id-eye"/g)||[]).length,2);assert.equal((markup.match(/class="id-pupil"/g)||[]).length,2);
  assert.match(markup,/id="rt-chat-avatar-/);assert.match(markup,/url\(#rt-chat-avatar-/);
  assert.doesNotMatch(markup,/<script|<animate|<title|onload=|https?:\/\/(?!www.w3.org\/2000\/svg)/);
 }
 assert.equal(registry.liveMarkup('art/custom.svg',{avatar_src:'data:image/svg+xml;base64,AAAA'}),'');
 assert.equal(registry.liveMarkup('preset:bottts:nova'),registry.liveMarkup(registry.defaultAvatar));
});

test('one idle timeout, no idle frame loop and no duplicate work after repeated renders',()=>{
 const f=fixture();f.controller.sync();for(let i=0;i<100;i++)f.controller.sync();
 assert.equal(f.node.dataset.liveState,'running');assert.equal(f.timers.size,1);assert.equal(f.frames.size,0);
 f.controller.destroy();assert.equal(f.timers.size,0);
});

test('natural blink closes and reopens both eyes then returns to an idle timeout',()=>{
 const f=fixture();f.controller.sync();f.blink();f.frame(81);
 assert.ok(f.node.eyes.every(eye=>eye.attrs.transform==='scale(1 0.040)'));
 f.controller.sync();f.frame(140);
 assert.ok(f.node.eyes.every(eye=>eye.attrs.transform==='scale(1 1.000)'));
 assert.equal(f.frames.size,0);assert.equal(f.timers.size,1);f.controller.destroy();
});

test('mouse gaze is bounded, settles without idle frames and recenters on leaving',()=>{
 const f=fixture();f.controller.sync();f.win.emit('pointermove',{pointerType:'mouse',clientX:9000,clientY:-9000});f.settle();
 assert.ok(f.node.pupils.every(pupil=>pupil.attrs.transform==='translate(0.900 -0.600)'));
 f.doc.emit('pointerleave');f.settle();assert.ok(f.node.pupils.every(pupil=>pupil.attrs.transform==='translate(0.000 0.000)'));
 f.controller.destroy();
});

test('coarse pointers and touch do not move the pupils',()=>{
 const f=fixture();f.controller.sync();
 f.win.emit('pointermove',{pointerType:'touch',clientX:900,clientY:700});assert.equal(f.frames.size,0);
 f.fine.matches=false;f.win.emit('pointermove',{pointerType:'mouse',clientX:900,clientY:700});assert.equal(f.frames.size,0);
 f.controller.destroy();
});

test('reduced motion, hidden documents, unfocused windows and offscreen portraits pause and reset',()=>{
 const f=fixture();f.controller.sync();f.win.emit('pointermove',{pointerType:'mouse',clientX:900,clientY:700});f.frame(16);
 f.reduced.matches=true;f.reduced.emit('change');assert.equal(f.timers.size,0);assert.equal(f.frames.size,0);
 assert.ok(f.node.pupils.every(pupil=>pupil.attrs.transform==='translate(0.000 0.000)'));
 f.reduced.matches=false;f.reduced.emit('change');assert.equal(f.timers.size,1);
 f.doc.hidden=true;f.doc.emit('visibilitychange');assert.equal(f.timers.size,0);
 f.doc.hidden=false;f.doc.emit('visibilitychange');assert.equal(f.timers.size,1);
 f.focus(false);assert.equal(f.timers.size,0);f.focus(true);assert.equal(f.timers.size,1);
 f.intersect(false);assert.equal(f.timers.size,0);f.intersect(true);assert.equal(f.timers.size,1);
 f.controller.destroy();
});

test('employee switches and disconnected markup cancel old frames and timers',()=>{
 const f=fixture();f.controller.sync();f.blink();const prior=f.node;prior.isConnected=false;
 const next=portrait();f.replace(next);f.controller.sync();assert.equal(f.frames.size,0);assert.equal(f.timers.size,1);
 f.blink();f.frame(80);assert.equal(next.eyes[0].attrs.transform,'scale(1 0.040)');
 assert.equal(prior.eyes[0].attrs.transform,'scale(1 1.000)');
 f.replace(null);f.controller.sync();assert.equal(f.timers.size,0);assert.equal(f.frames.size,0);f.controller.destroy();
});

test('scope changes, page hiding and destruction leave no scheduled work or retained listeners',()=>{
 const f=fixture();f.controller.sync();f.win.emit('runteams:business-scope-changed');assert.equal(f.timers.size,0);
 f.controller.sync();assert.equal(f.timers.size,1);f.win.emit('pagehide');assert.equal(f.timers.size,0);
 f.win.emit('pageshow');assert.equal(f.timers.size,1);f.controller.destroy();
 assert.equal(f.win.count()+f.doc.count()+f.reduced.count()+f.fine.count(),0);
 f.controller.sync();assert.equal(f.timers.size,0);assert.equal(f.frames.size,0);
});
