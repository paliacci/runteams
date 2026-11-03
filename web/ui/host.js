/* Host composition. Renderers depend on these ports, never on a distribution. */
(function(global){
 'use strict';
 const empty=()=>'',nothing=()=>{},no=()=>false;
 const ports={
  lifecycle:{blocked:no,initial:no,initialize:nothing,initialState:()=>({}),beforeRender:no,afterRender:nothing,startMonitor:nothing,pollNotifications:nothing},
  session:{ready:state=>!!state.localLibrary,workspace:empty,
   cacheToken:state=>JSON.stringify([state.localLibrary?.library_id||'',state.localLibrary?.generation||0]),
   actor:state=>state.localLibrary?.library_id||'',epoch:state=>state.localLibrary?.generation||0,deviceScope:()=>'',issuer:()=>'',
   libraryId:state=>state.localLibrary?.library_id||'',headers:state=>({'X-RunTeams-Library':state.localLibrary?.library_id||'','X-RunTeams-Library-Generation':state.localLibrary?.generation||0}),
   acceptsReceipt:(state,value)=>value.library_id===state.localLibrary?.library_id,
   displayScope:state=>state.localLibrary?.library_id?JSON.stringify(['library',state.localLibrary.library_id]):null,
   activityIdentity:()=>'',activityKey:()=>'',displayName:()=>'',sourceReady:state=>!!state.localLibrary,
   storageScope:state=>JSON.stringify(['library',state.localLibrary?.library_id||'']),readOnly:no},
  settings:{panels:Object.create(null),navigation:groups=>groups,guard:no,closeMenu:nothing,capture:nothing,restore:nothing,paint:nothing,load:nothing,notice:empty,usage:nothing,restoreRoute:nothing,updateRoute:nothing},
  shell:{navigation:()=>[],shortcuts:empty,entry:null,windowDisplay:()=>null,windowKey:()=>undefined,routeQuery:()=>[],snapshot:()=>({}),restore:nothing},
  pages:{normalize:()=>null,render:()=>null,title:()=>null,error:()=>null},
  routes:{preview:()=>null,resolve:()=>null,apply:async()=>false,restored:async()=>false,independent:no},
  resources:{tree:()=>null,detail:()=>null,origin:empty,publication:empty},
  assets:{remember:nothing,reset:nothing},
  workspace:{savedScope:()=>undefined,savedWindows:()=>undefined,storage:()=>null,reset:nothing},
  sidebar:{context:()=>({signedIn:false}),authority:nothing,authorityFailed:nothing},
 };
 const configured=new Set();
 function configure(contributions){
  const pending=[];
  for(const [group,values] of Object.entries(contributions)){
   if(!Object.hasOwn(ports,group)||!values||typeof values!=='object'||Array.isArray(values))throw Error('Invalid host contribution: '+group);
   for(const [key,value] of Object.entries(values)){
    const name=group+'.'+key;
    if(['__proto__','prototype','constructor'].includes(key))throw Error('Invalid host contribution: '+name);
    if(configured.has(name))throw Error('Duplicate host contribution: '+name);
    pending.push({group,key,value,name});
   }
  }
  for(const {group,key,value,name} of pending){configured.add(name);ports[group][key]=value;}
 }
 global.RunTeamsHost=Object.freeze({...ports,configure});
})(window);
