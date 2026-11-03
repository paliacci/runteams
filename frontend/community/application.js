/* Account-free application entry; the shared UI knows only host ports. */
(function(global){
 'use strict';
 let local;const module=()=>local??=import('/community/bootstrap.js');
 const application=Object.freeze({
  get identity(){return global.RunTeamsLocalIdentity||null;},
  boot:host=>module().then(value=>value.boot(host)),request:(...args)=>module().then(value=>value.request(...args)),
  stream:(...args)=>module().then(value=>value.stream(...args)),uploadBackup:(...args)=>module().then(value=>value.uploadBackup(...args)),
  readSettings:()=>module().then(value=>value.readSettings()),saveSettings:patch=>module().then(value=>value.saveSettings(patch))
 });
 global.RunTeamsApplication=application;
 global.RunTeamsHost.configure({lifecycle:{boot:(_options,host)=>application.boot(host),request:application.request,stream:application.stream},
  settings:{read:application.readSettings,save:application.saveSettings}});
})(window);
