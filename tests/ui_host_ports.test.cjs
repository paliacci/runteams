/* Real shared renderers with independent host adapters and deterministic IO. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
function context(){
 const c={console,URL,URLSearchParams,Set,Map,Promise,Date,Object,location:new URL('http://fixture/'),
  document:{querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>null},addEventListener(){},
  S:{localLibrary:{library_id:'library',generation:1},account:{theme:'light'},settingsTab:'general',settingsPreferencesState:'ready',settingsPreferences:{}},
  ICON:()=>'',esc:String,workspaceAccountCacheToken(){return c.RunTeamsHost.session.cacheToken(c.S);}};
 c.window=c;c.globalThis=c;vm.createContext(c);
 for(const name of ['web/ui/host.js','web/modules/account.js'])vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),c,{filename:name});
 c.accountSettingsPaint=()=>{};c.accountSettingsStartRuntimeMonitor=()=>{};c.accountSettingsSyncInteraction=()=>{};
 return c;
}
(async()=>{
 const local=context();
 assert.equal(local.normalizeSettingsTab('constructor'),'general');assert.equal(local.normalizeSettingsTab('__proto__'),'general');
 assert.equal(local.normalizeSettingsTab('unregistered'),'general');
 let reads=0,writes=0;
 local.RunTeamsHost.configure({settings:{read:async()=>{reads++;return {settings:{send_mode:'meta-enter'}};},save:async patch=>{writes++;return {ok:true,settings:patch};}}});
 await local.accountSettingsReadPreferences(true);await local.accountSettingsSave('allow_supplement',false);
 assert.equal(reads,1);assert.equal(writes,1);assert.equal(local.S.settingsPreferences.allow_supplement,false);
 const extension=context();
 extension.RunTeamsHost.configure({settings:{panels:{notes:()=>'<p>Notes</p>'},navigation:groups=>[...groups,['Extensions',[['notes','info','Notes']]]]}});
 assert.equal(extension.normalizeSettingsTab('notes'),'notes');extension.S.settingsTab='notes';assert.equal(extension.settingsPanel(),'<p>Notes</p>');
 assert.match(extension.accountSettingsNavigation(),/Notes/);assert.equal(local.normalizeSettingsTab('notes'),'general');
 assert.throws(()=>extension.RunTeamsHost.configure({settings:{navigation:()=>[]}}),/Duplicate/);
 assert.throws(()=>extension.RunTeamsHost.configure({unknown:{}}),/Invalid/);
 const atomic=context(),original=atomic.RunTeamsHost.settings.notice;
 assert.throws(()=>atomic.RunTeamsHost.configure({settings:{notice:()=> 'changed'},unknown:{}}),/Invalid/);
 assert.equal(atomic.RunTeamsHost.settings.notice,original);
 // A slow read from another library cannot overwrite the current settings.
 let finish;const stale=context();stale.RunTeamsHost.configure({settings:{read:()=>new Promise(resolve=>finish=resolve)}});
 const pending=stale.accountSettingsReadPreferences(true);stale.S.localLibrary={library_id:'different',generation:2};stale.S.settingsPreferences={allow_supplement:false};finish({settings:{send_mode:'stale'}});await pending;
 assert.equal(stale.S.settingsPreferences.allow_supplement,false);assert.equal(stale.S.settingsPreferences.send_mode,undefined);
 // A save without an exact acknowledgement must retain the confirmed settings.
 const rejected=context();rejected.S.settingsPreferences={allow_supplement:true};rejected.RunTeamsHost.configure({settings:{save:async()=>({ok:true,settings:{allow_supplement:true}})}});
 await rejected.accountSettingsSave('allow_supplement',false);assert.equal(rejected.S.settingsPreferences.allow_supplement,true);assert.match(rejected.S.settingsPreferenceError,/未能保存/);
 console.log('PASS host ports: local IO, registered panels, unknown/prototype routes, adapter isolation, stale reads and confirmed writes');
})().catch(error=>{console.error(error);process.exitCode=1});
