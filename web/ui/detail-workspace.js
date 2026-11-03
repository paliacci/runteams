/* One selection owns the right drawer. Modules retain their own data and mounts. */
(function(root){
  'use strict';
  function create(host){
    const owners=new WeakMap();
    let revision=0;
    const selection=()=>host.read();
    const valid=value=>!value||owners.has(value)&&owners.get(value)===host.context();
    if(selection())owners.set(selection(),host.context());
    function select(next,reason='select'){
      const previous=selection();
      if(valid(previous))host.capture?.(previous);
      host.leave(previous,next,reason);
      host.write(next||null);
      if(next)owners.set(next,host.context());
      revision++;
      host.changed?.(reason);
      return next||null;
    }
    // A read may replace content only while its exact selection still owns the
    // drawer. Updating content does not count as a new navigation intent.
    function update(next,expected=selection()){
      if(!expected||selection()!==expected||!valid(expected)||next?.type!==expected.type||next.id!==expected.id||next.key!==expected.key)return false;
      host.write(next);owners.set(next,owners.get(expected));return true;
    }
    function reconcile(){
      if(selection()&&!valid(selection()))select(null,'context');
    }
    function restore(value){
      return select(valid(value)?value:null,'restore');
    }
    function close(){
      reconcile();
      if(host.guard(()=>close()))return false;
      select(host.returnTo?.(selection())||null,'close');
      return true;
    }
    function resolve(){reconcile();return selection()?host.resolve(selection()):null;}
    function ticket(){
      const value=selection(),epoch=revision,context=host.context();
      return ()=>revision===epoch&&selection()===value&&host.context()===context;
    }
    const capture=()=>{if(valid(selection()))host.capture?.(selection());};
    return {select,update,close,restore,reconcile,resolve,ticket,capture,guard:action=>host.guard(action)};
  }
  const api={create};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.RunTeamsDetailWorkspace=api;
})(globalThis);
