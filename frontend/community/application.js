/* UI composition only. Server-side library/account checks remain authoritative. */
(function(global){
 'use strict';
 const edition=document.querySelector('meta[name="runteams-edition"]')?.content||'official';
 if(!['official','community'].includes(edition))throw Error('Unknown application edition');
 let local;
 const module=()=>local??=import('/community/bootstrap.js');
 global.RunTeamsApplication=Object.freeze({edition,
  has:capability=>edition==='official'||!['account','subscription','market','organization','devices','support','analytics'].includes(capability),
  settingsAllowed:tab=>edition==='official'||!['devices','organization','subscription','wallet','help'].includes(tab),
  get identity(){return global.RunTeamsLocalIdentity||null;},
  boot:host=>module().then(value=>value.boot(host)),
  request:(...args)=>module().then(value=>value.request(...args)),
  stream:(...args)=>module().then(value=>value.stream(...args)),
  uploadBackup:(...args)=>module().then(value=>value.uploadBackup(...args)),
  readSettings:()=>module().then(value=>value.readSettings()),
  saveSettings:patch=>module().then(value=>value.saveSettings(patch))
 });
})(window);
