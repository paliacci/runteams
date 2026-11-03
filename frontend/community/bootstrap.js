/* Account-free composition of the canonical business UI, without its own markup. */
import {LocalClient} from './client.js';
import {NativeCloseGuard} from './native.js';
const client=new LocalClient({fetcher:globalThis.fetch.bind(globalThis),request:globalThis.RunTeamsRequests.request});
if(document.documentElement?.hasAttribute('data-native'))document.documentElement.classList.add('runteams-native-macos');
let connected,revision=0,operation=null,pending=0,host,closing=false;
async function connect(){
 if(!connected)connected=client.connect().then(value=>{window.RunTeamsLocalIdentity=Object.freeze({...value,kind:'library',name:'本机资料库'});return value;}).catch(error=>{connected=null;throw error;});
 return connected;
}
export async function request(path,method='GET',body,options={}){
 await connect();
 if(closing)throw Error('窗口正在关闭。');
 const writing=!globalThis.RunTeamsRequests.isRead(path,method||'GET');if(writing)pending++;
 try{
  if(path.startsWith('/api/backups')&&method==='POST'&&globalThis.RunTeamsWorkState?.pending)await RunTeamsWorkState.flush();
  return await client.request(path,method||'GET',body,options);
 }
 finally{if(writing)pending--;}
}
export async function stream(path,body,onEvent){
 await connect();if(closing)throw Error('窗口正在关闭。');pending++;
 try{return await client.stream(path,body,onEvent);}
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
  S.localLibrary=identity;S.activeOrganization='';S.accountSessionReady=true;S.accountSessionError='';
  host.restoreWorkspace();
  const route=host.route(),deferRoutePaint=!new URL(location.href).searchParams.has('settings')&&!['home','chat-new'].includes(route.kind);
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
  await models;host.normalize();paint();
  if(!new URL(location.href).searchParams.has('settings')){const route=host.route();if(route.kind==='docs'&&!route.documentId)await host.openDocuments();else if(route.kind==='trash')await host.openTrash();else if(!['home','chat-new'].includes(route.kind))await host.openRoute();}
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
 const hasDraft=value=>Boolean(value?.input?.trim()||value?.attachments?.length||value?.capabilities?.length||value?.queue);
 return {pending:Boolean(configuration?.pending||globalThis.RunTeamsWorkState?.pendingSave&&!globalThis.RunTeamsWorkState?.saveRejected||source?.saving||source?.pending||source?.buildSending||source?.build?.latest?.state==='running'||pending||operation||S?.conversationPanel?.busy||S?.settingsPreferencePending||globalThis.RunTeamsBackups?.pending||['saving','error'].includes(S?.docReader?.saveStatus)),dirty:!!configuration?.dirty||!!globalThis.RunTeamsWorkState?.saveRejected||!!source?.editing||Object.values(S?.conversationPanelDrafts||{}).some(hasDraft)};
},()=>{closing=true;document.body?.setAttribute('inert','');});
window.RunTeamsLocalDesktop=Object.freeze({checkClose:discard=>closeGuard.checkClose(discard),prepareClose:discard=>closeGuard.prepareClose(discard)});
