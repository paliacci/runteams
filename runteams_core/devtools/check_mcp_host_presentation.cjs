// Build-time MCP protocol probe of trusted platform resources, never author code.
// The engineering host acknowledges layout only; it grants no business access.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
let mode='panel',events={},messages=[],requests=[],listeners=[];
const child={postMessage(message){messages.push(message);}};
const frame={style:{},setAttribute(){},contentWindow:child};
const host={version:'0.1.0',kind:'platform',capabilities:['presentation','drawer-header'],getSnapshot:()=>({theme:'dark',presentation:{mode,viewId:mode==='full'?'mcp-workbench':null}}),subscribe:fn=>{listeners.push(fn);return()=>{};},onAction:()=>()=>{},request:async(method,params)=>{requests.push({method,params});mode=params.mode;listeners.forEach(fn=>fn());return{mode,viewId:params.viewId};}};
const window={runteamsHost:host,runteamsUI:{methods:['mcp.tools.call']},innerWidth:400,innerHeight:600,addEventListener:(name,fn)=>(events[name]??=[]).push(fn),removeEventListener(){}};
window.parent=window;
const c={window,document:{getElementById:()=>({textContent:JSON.stringify({title:'Engineering host feature probe',tools:[],input:{}})}),createElement:()=>frame,body:{replaceChildren(){},append(){}}},console:{debug(){},log(){},warn(){},error(){}},crypto:webcrypto,URL,URLSearchParams,TextEncoder,TextDecoder,AbortController,AbortSignal,performance, setTimeout,clearTimeout,setInterval,clearInterval,MessageChannel};
(async()=>{
 await vm.runInNewContext('(async()=>{'+fs.readFileSync(process.argv[2],'utf8')+'})()',c,{filename:process.argv[2],timeout:1000});
 assert.equal(typeof window.runteamsMCPClose?.prepare,'function','MCP host must provide its standard teardown close barrier');
 await assert.rejects(window.runteamsMCPClose.prepare(),/mcp_app_not_initialized/);
 async function send(id,method,params){for(const fn of events.message||[])fn({source:child,data:{jsonrpc:'2.0',id,method,params}});for(let n=0;n<100&&!messages.some(x=>x.id===id);n++)await new Promise(r=>setTimeout(r,10));return messages.find(x=>x.id===id);}
 const init=await send(1,'ui/initialize',{protocolVersion:'2026-01-26',appInfo:{name:'engineering-probe',version:'1.0.0'},appCapabilities:{}});
 for(const fn of events.message||[])fn({source:child,data:{jsonrpc:'2.0',method:'ui/notifications/initialized',params:{}}});
 await new Promise(r=>setTimeout(r,0));
 const full=await send(2,'ui/request-display-mode',{mode:'fullscreen'});
 const inline=await send(3,'ui/request-display-mode',{mode:'inline'});
 assert(!init?.error,'MCP initialization failed');
 assert(init?.result?.hostContext?.availableDisplayModes?.includes('inline')&&init.result.hostContext.availableDisplayModes.includes('fullscreen'),'MCP host must advertise both inline and fullscreen');
 assert.equal(full?.result?.mode,'fullscreen');assert.equal(inline?.result?.mode,'inline');assert.equal(requests.length,2);assert.equal(requests[0].method,'present');assert.equal(requests[0].params.mode,'full');assert.equal(requests[1].method,'present');assert.equal(requests[1].params.mode,'panel');assert.equal(requests[1].params.viewId,null);
 const teardownMessages=()=>messages.filter(x=>x.method==='ui/resource-teardown');
 async function waitTeardown(count){for(let n=0;n<100&&teardownMessages().length<count;n++)await new Promise(r=>setTimeout(r,1));assert.equal(teardownMessages().length,count);return teardownMessages().at(-1);}
 function replyTeardown(request,body){for(const fn of events.message||[])fn({source:child,data:{jsonrpc:'2.0',id:request.id,...body}});}
 const denied=window.runteamsMCPClose.prepare(),denial=assert.rejects(denied,e=>e.code===-32603);
 const first=await waitTeardown(1);assert.notEqual(frame.inert,true);
 replyTeardown(first,{error:{code:-32603,message:'Explicit engineering unsaved-content refusal'}});await denial;
 assert.notEqual(frame.inert,true);window.runteamsMCPClose.cancel();
 const clean=window.runteamsMCPClose.prepare(),same=window.runteamsMCPClose.prepare();
 const second=await waitTeardown(2);assert.notEqual(frame.inert,true);replyTeardown(second,{result:{}});
 assert.equal(await clean,'ready');assert.equal(await same,'ready');assert.equal(frame.inert,true);
 window.runteamsMCPClose.cancel();assert.equal(frame.inert,false);
 const uncertain=window.runteamsMCPClose.prepare(),lost=assert.rejects(uncertain);
 await waitTeardown(3);for(const fn of events.pagehide||[])fn();await lost;
 window.runteamsMCPClose.cancel();await assert.rejects(window.runteamsMCPClose.prepare());
 assert.equal(teardownMessages().length,3,'An uncertain teardown must never be resent by another Quit');
 console.log(JSON.stringify({host_display_modes:init.result.hostContext.availableDisplayModes,expanded:full.result.mode,returned:inline.result.mode,presentation_requests:2,standard_teardown_requests:3,dirty_refusal_preserved:true,concurrent_quit_shares_request:true,acknowledged_only_freeze_and_cancel:true,uncertain_cleanup_not_reissued:true,engineering_host_ack_fixture:true}));
})().catch(e=>{console.error(e);process.exitCode=1;});
