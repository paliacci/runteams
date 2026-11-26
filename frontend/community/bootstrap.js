/* Account-free composition of the canonical business UI, without its own markup. */
import {LocalClient} from './client.js';
import {NativeCloseGuard, windowsSettingsBridge} from './native.js';
const client=new LocalClient({fetcher:globalThis.fetch.bind(globalThis),request:globalThis.RunTeamsRequests.request});
if(document.documentElement?.hasAttribute('data-native'))document.documentElement.classList.add('runteams-native-macos');
let languageSync=Promise.resolve();
function syncLanguage(){
 const language=globalThis.RunTeamsLocale?.language;if(!language)return Promise.resolve();
 const policy={communication_language:language};
 languageSync=languageSync.catch(()=>{}).then(()=>request('/api/language-preference','POST',policy));
 return languageSync;
}
globalThis.RunTeamsLocale?.onChange(()=>{syncLanguage().catch(error=>console.error('Language preference could not be saved',error));});
let connected,revision=0,operation=null,pending=0,host,closing=false;
const desktopSettings=windowsSettingsBridge(window.chrome?.webview);
let alertCursor=null,readingAlerts=false;
function alertError(value){
 const state=host?.state;
 if(state&&state.notificationDeliveryError!==value){
  state.notificationDeliveryError=value;
  if(state.settingsTab==='notifications')globalThis.accountSettingsPaint?.();
 }
}
async function openWorkAlert(item,scope){
 if(closing||client.generation!==scope)return;
 try{
  await desktopSettings.postMessage({action:'notifications-activate'});
  if(closing||client.generation!==scope)return;
  if(document.getElementById('settingsWorkspace'))globalThis.accountSettingsClose?.();
  if(item.reference){
   const board=globalThis.RunTeamsSourcePipelines;
   if(!board.pageRoute(item.reference))await board.readCatalog();
   const route=board.pageRoute(item.reference);
   if(!route||client.generation!==scope)throw Error();
   await board.openFromLink(route+'?results=1&delivery=workflow-'+item.workflow_id);
  }else if(item.chat_id)await globalThis.openConversationSession(item.chat_id,'general');
 }catch{globalThis.toast?.('无法打开这条提醒。','err','notifications.openFailed');}
}
export async function pollWorkAlerts(foreground){
 const state=host?.state;
 if(!desktopSettings||closing||!state?.localLibrary||readingAlerts)return;
 if(foreground===undefined)foreground=document.hasFocus();
 if(globalThis.Notification?.permission!=='granted'||state.settingsPreferences?.notification_timing==='never'){
  alertCursor=null;return;
 }
 if(state.settingsPreferencesState!=='ready'||state.settingsPreferencePending)return;
 const scope=client.generation;
 readingAlerts=true;
 try{
  const after=alertCursor?.scope===scope?'?after='+alertCursor.id:'';
  const result=await request('/api/work-alerts'+after);
  if(closing||client.generation!==scope)return;
  alertCursor={scope,id:result.cursor};
  const prefs=state.settingsPreferences||{};
  if(Notification.permission!=='granted'||prefs.notification_timing==='never')return;
  const labels={confirmation:['titleConfirmation','需要确认'],information:['titleInformation','需要补充信息'],
   failure:['titleFailure','工作失败'],completion:['titleCompletion','工作完成']};
  for(const item of result.items){
   if(prefs[item.category]===false||foreground&&prefs.notification_timing!=='always')continue;
   const [key,fallback]=labels[item.category],locale=globalThis.RunTeamsLocale;
   const note=new Notification(locale?.t('notifications.'+key,{},fallback)||fallback,{
    body:locale?.t('notifications.openDetails',{},'打开 RunTeams 查看详情。')||'打开 RunTeams 查看详情。',
    silent:prefs.sound===false,tag:'runteams-work-'+item.workflow_id});
   note.onclick=()=>{note.close();void openWorkAlert(item,scope);};
   note.onerror=()=>alertError('delivery');
  }
  if(state.notificationDeliveryError==='read')alertError('');
 }catch{alertError('read');}
 finally{readingAlerts=false;}
}
window.chrome?.webview?.addEventListener?.('message',event=>{
 if(event.data?.kind==='work-alerts')void pollWorkAlerts(event.data.foreground);
 if(event.data?.kind==='work-alert-delivery')alertError(event.data.ok?'':'delivery');
});
let workspaceScope=null,lastWorkspace=null,workspaceSaveError=false;
let boardStorage=null;
async function loadDesktopBoards(scope){
 const response=await desktopSettings.postMessage({action:'workspace-boards-read',...scope});
 const saved=new Map(Object.entries(response.boards)),edits=new Map();
 return {
  getItem:key=>edits.get(key)?.value??saved.get(key)??null,
  async setItem(key,value){
   if(closing)throw Error('窗口正在关闭。');
   const edit={value};
   edits.set(key,edit);pending++;
   try{
    const result=await desktopSettings.postMessage({action:'workspace-board-write',...scope,key,value});
    if(result.saved!==true)throw Error('无法保存看板显示设置。');
    saved.set(key,value);
   }finally{
    if(edits.get(key)===edit)edits.delete(key);
    pending--;
   }
  }
 };
}
async function saveDesktopWorkspace(raw){
 if(!workspaceScope||closing||raw===lastWorkspace)return;
 lastWorkspace=raw;pending++;
 try{
  const result=await desktopSettings.postMessage({action:'workspace-write',...workspaceScope,value:raw});
  if(result.saved!==true)throw Error('工作窗口未能保存。');
  if(lastWorkspace===raw)workspaceSaveError=false;
 }catch(error){
  if(lastWorkspace===raw){lastWorkspace=null;workspaceSaveError=true;}
  console.error('Windows workspace could not be saved',error);
 }finally{pending--;}
}
async function saveDesktopPreference(key,value){
 if(closing)throw Error('窗口正在关闭。');
 pending++;
 try{
  const saved=await desktopSettings.postMessage({action:'set',key,value});
  const confirmed=key==='language'?saved.language:saved.appearance?.[key];
  if(confirmed!==value)throw Error('本机设置未确认');
  return true;
 }finally{pending--;}
}
async function connect(){
 if(!connected)connected=client.connect().then(value=>{window.RunTeamsLocalIdentity=Object.freeze({...value,kind:'library',name:'本机资料库'});return value;}).catch(error=>{connected=null;throw error;});
 return connected;
}
export async function request(path,method='GET',body,options={}){
 await connect();
 if(closing)throw Error('窗口正在关闭。');
 if(method==='POST'&&path!=='/api/language-preference')await languageSync.catch(()=>syncLanguage());
 const writing=!globalThis.RunTeamsRequests.isRead(path,method||'GET');if(writing)pending++;
 try{
  if(path.startsWith('/api/backups')&&method==='POST'&&globalThis.RunTeamsWorkState?.pending)await RunTeamsWorkState.flush();
  return await client.request(path,method||'GET',body,options);
 }
 finally{if(writing)pending--;}
}
export async function stream(path,body,onEvent,options){
 await connect();if(closing)throw Error('窗口正在关闭。');
 if(options?.observe)return client.stream(path,body,onEvent,options);
 pending++;
 try{return await client.stream(path,body,onEvent,options);}
 finally{pending--;}
}
export async function uploadBackup(file,operationId){
 await connect();if(closing)throw Error('窗口正在关闭。');pending++;
 try{return await client.uploadBackup(file,operationId);}finally{pending--;}
}
export async function readSettings(){
 if(operation)await commitSettings();
 const result=await request('/api/settings');
 if(result.library_id!==client.libraryId||!Number.isSafeInteger(result.revision)||!result.settings||typeof result.settings!=='object')throw Error('本机设置回执无效。');
 revision=result.revision;return result;
}
async function commitSettings(){
 const original=operation;
 try{
  const result=await request('/api/settings','POST',original);
  if(result.library_id!==client.libraryId||result.operation_id!==original.operation_id||result.revision!==original.expected_revision+1||result.ok!==true)throw Error('本机设置回执无效。');
  operation=null;revision=result.revision;return result;
 }catch(error){
  if([400,404,409,413,415].includes(error.status))operation=null;
  if(operation)error.code='mutation_outcome_unknown';
  throw error;
 }
}
export async function saveSettings(patch){
 if(operation)throw Object.assign(Error('请先确认原设置的保存结果。'),{code:'mutation_outcome_unknown'});
 operation={patch:JSON.parse(JSON.stringify(patch)),expected_revision:revision,operation_id:crypto.randomUUID()};
 return commitSettings();
}
export async function boot(value){
 host=value;const {state:S}=host;
 try{
  const identity=await connect();
  let savedWindows,loadedScope=null;
  if(desktopSettings){
   const locale=globalThis.RunTeamsLocale,initial=locale?.preference;
   try{
    const saved=await desktopSettings.postMessage({action:'get'});
    host.restoreAppearance(saved.appearance);
    if(locale&&locale.preference===initial){
     if(saved.language&&saved.language!==initial)locale.restorePreference(saved.language);
     else if(saved.language==null&&['en','zh-CN'].includes(initial))await saveDesktopPreference('language',initial);
    }
   }
   catch{S.nativeSettingsError='本机设置暂时无法读取';}
   const scope={library:identity.library_id,generation:identity.generation};
   boardStorage=null;
   try{boardStorage=await loadDesktopBoards(scope);}
   catch(error){
    console.error('Windows board preferences could not be read',error);
    // Retry the read before allowing an edit to replace unknown saved preferences.
    boardStorage={getItem:()=>null,async setItem(){
     boardStorage=await loadDesktopBoards(scope);
     throw Error('看板显示设置已重新读取。请重试。');
    }};
   }
   try{
    const saved=await desktopSettings.postMessage({action:'workspace-read',...scope});
    savedWindows=saved.windows;loadedScope=scope;
   }catch(error){console.error('Windows workspace could not be read',error);}
  }
  await syncLanguage();
  S.localLibrary=identity;S.accountSessionReady=true;S.accountSessionError='';
  host.restoreWorkspace(savedWindows);
  lastWorkspace=savedWindows;workspaceScope=loadedScope;
  const startupLocation=location.href;
  const route=host.route(),deferRoutePaint=!new URL(startupLocation).searchParams.has('settings')&&!['home','chat-new'].includes(route.kind);
  S.settingsPreferencesState='loading';
  Object.assign(S,{surface:'team',railMode:'assistant',railNavTab:S.railNavTab==='bots'?'bots':'team',booting:deferRoutePaint,bootRoute:route,bootError:null,
   workspaceStartup:null,navigationLoading:false,navigationError:'',
   coreTeamLoading:false,coreTeamError:'',
   modelCatalogReady:false,modelCatalog:[],channels:[],providerCatalog:[]});
  // Shared native observations decide readiness; a library is never a cloud login.
  S.workspaceStartup={pending:false,accountPending:false,channelsPending:true,channelsError:''};
  const paint=()=>{if(!deferRoutePaint)host.render();};
  S.conversationPanel=host.newConversation(route.purpose);
  host.restoreDraft(S.conversationPanel);S.workspaceStartup.panel=S.conversationPanel;
  S.appInfo=await request('/api/app-info');
  await host.loadChats({identityOnly:true});
  paint();
  const models=host.loadModels().then(result=>{if(!result||result.error)throw Error(result?.error||'模型目录未能读取。');if(result.catalog?.channels){S.modelCatalog=result.catalog.channels;S.modelCatalogReady=true;}host.normalize();}).catch(error=>{if(S.workspaceStartup)S.workspaceStartup.channelsError=error.message;}).finally(()=>{if(S.workspaceStartup)S.workspaceStartup.channelsPending=false;paint();});
  await Promise.allSettled([host.loadEmployees(),host.loadPipelines()]).then(results=>{if(results[0].status==='rejected')S.coreTeamError=results[0].reason.message;});
  await host.loadChats({identityReady:true}).catch(error=>{S.chatDirectoryError=error.message;});
  try{const prefs=await readSettings();S.settingsPreferences=prefs.settings;S.settingsPreferencesState='ready';}
  catch(error){S.settingsPreferencesState='error';}
  void pollWorkAlerts();
  await models;host.normalize();paint();
  // Interactive startup surfaces can navigate while the model catalog is pending.
  if(deferRoutePaint&&location.href===startupLocation){
   if(route.kind==='docs'&&!route.documentId)await host.openDocuments();
   else if(route.kind==='trash')await host.openTrash();
   else await host.openRoute();
  }
  // Background directory/model reads may render too. Keep the URL shell until
  // the original route loader has committed its page, then publish it once.
  if(deferRoutePaint){S.booting=false;host.render();}
  host.restoreSettings();
 }catch(error){S.booting=true;S.bootError=error.message;host.render();throw error;}
}
const closeGuard=new NativeCloseGuard(()=>{
 host?.captureDraft();
 globalThis.RunTeamsCreatorAuthor?.capture();
 const S=host?.state;
 const source=globalThis.RunTeamsCreatorAuthor?.current();
 const configuration=globalThis.RunTeamsEmployeeConfiguration?.closeState();
 const hasDraft=value=>Boolean(value?.input?.trim()||value?.attachments?.length||value?.capabilities?.length||value?.queue||value?.missingAttachments);
 const hasUnconfirmedDraft=Object.values(S?.conversationPanelsByChat||{}).some(panel=>hasDraft(panel.localTurnRecovery?.draft));
 return {pending:Boolean(configuration?.pending||globalThis.RunTeamsWorkState?.pendingSave&&!globalThis.RunTeamsWorkState?.saveRejected||source?.saving||source?.pending||source?.buildSending||source?.build?.latest?.state==='running'||pending||operation||S?.conversationPanel?.busy||S?.settingsPreferencePending||globalThis.RunTeamsBackups?.pending||['saving','error'].includes(S?.docReader?.saveStatus)),dirty:workspaceSaveError||!!configuration?.dirty||!!globalThis.RunTeamsWorkState?.saveRejected||!!source?.editing||hasUnconfirmedDraft||Object.values(S?.conversationPanelDrafts||{}).some(draft=>hasDraft(draft)||hasDraft(draft.localTurnRecovery?.draft))};
},()=>{closing=true;document.body?.setAttribute('inert','');});
window.RunTeamsLocalDesktop=Object.freeze({settings:desktopSettings,boardStorage:()=>boardStorage,saveAppearance:desktopSettings?saveDesktopPreference:null,
 saveLanguage:desktopSettings?value=>saveDesktopPreference('language',value):null,saveWorkspace:desktopSettings?saveDesktopWorkspace:null,
 checkClose:discard=>closeGuard.checkClose(discard),prepareClose:discard=>closeGuard.prepareClose(discard)});
