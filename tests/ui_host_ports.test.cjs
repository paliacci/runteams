/* Real shared renderers with independent host adapters and deterministic IO. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
function context(platform){
 const c={console,URL,URLSearchParams,Set,Map,Promise,Date,Object,navigator:{platform},location:new URL('http://fixture/'),
  document:{querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>null},addEventListener(){},matchMedia:()=>({addEventListener(){}}),
  S:{localLibrary:{library_id:'library',generation:1},account:{theme:'light'},settingsTab:'general',settingsPreferencesState:'ready',settingsPreferences:{}},
  ICON:()=>'',esc:String,workspaceAccountCacheToken(){return c.RunTeamsHost.session.cacheToken(c.S);}};
 c.window=c;c.globalThis=c;vm.createContext(c);
 for(const name of ['web/ui/host.js','web/ui/shell.js','web/modules/account.js'])vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),c,{filename:name});
 c.accountSettingsPaint=()=>{};c.accountSettingsStartRuntimeMonitor=()=>{};c.accountSettingsSyncInteraction=()=>{};
 return c;
}
(async()=>{
 const local=context('Win32');
 assert.deepEqual({...local.RunTeamsShell.commandShortcut('N')},{label:'Ctrl+N',aria:'Control+N'});
 const tabActions=[];
 const tabButtons=['documents','plan','task'].map(key=>({
  focus(){tabActions.push(['focus',key]);},
  click(){tabActions.push(['click',key]);}
 }));
 const tabList={querySelectorAll:()=>tabButtons};
 function pressTabKey(key,target,modifiers={}){
  local.RunTeamsShell.moveWindowTab({key,target,currentTarget:tabList,
   preventDefault(){tabActions.push('handled');},...modifiers});
 }
 for(const [key,origin,destination] of [['ArrowRight',2,0],['ArrowLeft',0,2],['Home',1,0],['End',1,2]]){
  pressTabKey(key,tabButtons[origin]);
  const expected=['documents','plan','task'][destination];
  assert.deepEqual(tabActions.splice(0),['handled',['focus',expected],['click',expected]]);
 }
 pressTabKey('ArrowLeft',tabButtons[1],{altKey:true});
 pressTabKey('Home',{}); // A descendant close button has its own keyboard behavior.
 assert.deepEqual(tabActions,[]);
 assert.deepEqual({...context('MacIntel').RunTeamsShell.commandShortcut('N')},{label:'⌘N',aria:'Meta+N'});
 assert.equal(local.accountExtensionCommand('codex','mcp add --help'),"& 'codex' mcp add --help");
 assert.equal(local.accountExtensionCommand("/opt/O'Brien/claude",'plugin install',"a'b"),"'/opt/O'\"'\"'Brien/claude' plugin install -- 'a'\"'\"'b'");
 local.navigator={platform:'MacIntel'};
 assert.equal(local.accountExtensionCommand("C:\\QA Tools\\O'Brien.exe",'plugin remove','组‘’‚‛'),"& 'C:\\QA Tools\\O''Brien.exe' plugin remove -- '组'‘'’'‚'‛'");
 assert.equal(local.accountExtensionCommand('codex','plugin --help'),"'codex' plugin --help");
 const initial=local.RunTeamsHost.session.headers(local.S);
 local.S.localLibrary.generation=2;
 assert.equal(initial['X-RunTeams-Library-Generation'],1);
 assert.equal(local.RunTeamsHost.session.preloadScope(),'');
 let call;local.api=(...args)=>{call=args;return {ok:true};};
 assert.equal((await local.RunTeamsHost.session.workAuthorization('/work',{action:'save'})).ok,true);
 assert.deepEqual(call,['/work','POST',{action:'save'}]);
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
 const emptyEntry=context();emptyEntry.RunTeamsHost.configure({shell:{entry:()=>''}});
 assert.equal(emptyEntry.RunTeamsShell.accountEntry({icon:()=>''}),'');
 assert.match(local.RunTeamsShell.accountEntry({icon:()=>''}),/rail-settings-entry/);
 // A slow read from another library cannot overwrite the current settings.
 let finish;const stale=context();stale.RunTeamsHost.configure({settings:{read:()=>new Promise(resolve=>finish=resolve)}});
 const pending=stale.accountSettingsReadPreferences(true);stale.S.localLibrary={library_id:'different',generation:2};stale.S.settingsPreferences={allow_supplement:false};finish({settings:{send_mode:'stale'}});await pending;
 assert.equal(stale.S.settingsPreferences.allow_supplement,false);assert.equal(stale.S.settingsPreferences.send_mode,undefined);
 // A save without an exact acknowledgement must retain the confirmed settings.
 const rejected=context();rejected.S.settingsPreferences={allow_supplement:true};rejected.RunTeamsHost.configure({settings:{save:async()=>({ok:true,settings:{allow_supplement:true}})}});
 await rejected.accountSettingsSave('allow_supplement',false);assert.equal(rejected.S.settingsPreferences.allow_supplement,true);assert.match(rejected.S.settingsPreferenceError,/未能保存/);
 console.log('PASS host ports: local IO, registered panels, unknown/prototype routes, adapter isolation, stale reads and confirmed writes');
})().catch(error=>{console.error(error);process.exitCode=1});
