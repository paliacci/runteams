/* Shared settings and model-channel UI. Official account/business behavior is composed by the official entry.
 * Classic script: functions retain their existing names and access the host's S/helpers at call time.
 * Do not run initialization here; do not redeclare S, api, ICON, esc, render or shared controls. */

/* module-function:refreshChannelUsage */
async function refreshChannelUsage(force=false){
  const context=workspaceAccountCacheToken(),mutation=S.channelMutationVersion||0,
   previousAvailability=JSON.stringify(S.channels.map(c=>[String(c.id),modelChannelAvailable(c)]));
  S.channelUsageLoading=true;RunTeamsHost.settings.usage();if(document.getElementById("channel_list")||document.getElementById("model_channel_guide_list"))renderChannels(false);
  try{const result=await modelChannelData().usage(force);if(!result||context!==workspaceAccountCacheToken()||mutation!==(S.channelMutationVersion||0))return S.channelUsage;
   if(result.error)throw Error(result.error);if(S.channelUsage===result)return result;
   S.channelUsage=result;S.channelUsageUpdatedAt=Date.now();applyChannelUsageAvailability(previousAvailability);return result;
  }catch(error){if(context===workspaceAccountCacheToken()&&mutation===(S.channelMutationVersion||0)){S.channelUsage={channels:[],error:error.message||''};S.channelUsageUpdatedAt=Date.now();}return S.channelUsage;}
  finally{if(context===workspaceAccountCacheToken()){S.channelUsageLoading=false;RunTeamsHost.settings.usage();if(document.getElementById("channel_list")||document.getElementById("model_channel_guide_list"))renderChannels(false);}}
}

/* module-function:refreshAccountPanel */
function refreshAccountPanel(){if(document.getElementById('settingsWorkspace')){accountSettingsPaint();accountSettingsLoadTab();accountSettingsReadPreferences();}}

/* Google Identity official logo, preserved as an offline brand asset.
 * Source: https://developers.google.com/static/identity/images/g-logo.png
 * Intrinsic brand colors are image pixels, not UI color overrides. */


/* module-function:settingsNavButton */

function settingsNavButton(tab,icon,label,labelKey=tab==='about'?'about.title':''){return `<button type="button" class="${S.settingsTab===tab?'on':''}" data-settings-tab="${tab}" aria-current="${S.settingsTab===tab?'page':'false'}" onclick="switchSettingsTab('${tab}')">${ICON(icon)}<span${labelKey?` data-app-i18n="${esc(labelKey)}"`:''}>${label}</span></button>`;}

/* module-function:settingsPageHead */
function settingsPageHead(title,detail=''){return `<header class="settings-page-head"><h2 tabindex="-1">${title}</h2>${detail?`<p>${detail}</p>`:''}</header>`;}

/* module-function:settingsSectionHead */
function settingsSectionHead(title,detail='',action=''){return `<div class="settings-section-title-row"><span><h3>${title}</h3>${detail?`<small>${detail}</small>`:''}</span>${action}</div>`;}

/* module-function:settingsError */
function settingsError(title,detail,message,retry){return `${settingsPageHead(title,detail)}${RunTeamsLoadFailure.markup({variant:'modal',title:title+'暂时无法加载',error:message,retry})}`;}

/* module-function:formatSettingsTime */
function formatSettingsTime(value){if(!value)return '尚未同步';const raw=String(value).trim(),normalized=/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)?raw:(raw.includes('T')?raw+'Z':raw.replace(' ','T')+'Z'),date=new Date(normalized);return Number.isNaN(date.getTime())?'尚未同步':date.toLocaleString([],{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}

/* module-function:appearanceOption */
function appearanceOption(value,label){const mini='<i class="preview-rail"></i><i class="preview-card one"></i><i class="preview-card two"></i>';return `<button class="appearance-option ${S.account.theme===value?'on':''}" data-theme-value="${value}" aria-pressed="${S.account.theme===value?'true':'false'}" onclick="setAccountTheme('${value}')"><span class="appearance-preview ${value}" aria-hidden="true">${value==='system'?`<span class="preview-half light">${mini}</span><span class="preview-half dark">${mini}</span>`:mini}</span><span><b>${label}</b></span><i class="appearance-radio">${ICON('check')}</i></button>`;}

/* module-function:accountLanguageItems */
function accountLanguageItems(){return [{value:'zh-CN',label:'简体中文'},{value:'en',label:'English'}];}

/* module-function:accountLanguageValue */
function accountLanguageValue(){
 if(globalThis.RunTeamsLocale)return RunTeamsLocale.language;
 try{const value=localStorage.getItem('runteams_language_preference');if(accountLanguageItems().some(item=>item.value===value))return value;}catch(error){}
 const browser=globalThis.navigator;
 for(const language of browser?.languages?.length?browser.languages:[browser?.language||'']){
  if(/^zh(?:-|$)/i.test(language))return 'zh-CN';
  if(/^en(?:-|$)/i.test(language))return 'en';
 }
 return 'en';
}

/* module-function:accountLanguageControl */
function accountLanguageControl(){return csel('accountLanguage',accountLanguageItems(),accountLanguageValue(),value=>{
  const previous=accountLanguageValue();
  if(!accountLanguageItems().some(item=>item.value===value))return;
  if(globalThis.RunTeamsLocale){
   const result=RunTeamsLocale.setPreference(value);
   document.getElementById('accountLanguage')?.focus({preventScroll:true});
   const report=saved=>{if(!saved&&RunTeamsLocale.preference===value)toast('当前语言已切换，但未能保存在本机。','err','language.saveFailed');};
   if(result.nativeSave)void result.nativeSave.then(report);else report(result.persisted);
   return;
  }
  try{localStorage.setItem('runteams_language_preference',value);}catch(error){updateCsel('accountLanguage',accountLanguageItems(),previous);toast('无法保存语言选项，请重试','err');}
},{menuVariant:'settingsSelect',menuAlign:'right'}).replace('data-menu-trigger="field"','data-menu-trigger="field" data-app-i18n-aria-label="language.title" aria-label="语言" aria-describedby="accountLanguageHint" onkeydown="accountLanguageKey(event)"').replace('onclick="cselOpen(', 'onclick="accountLanguageOpen(');}

/* module-function:accountLanguageOpen */
function accountLanguageOpen(event,id){cselOpen(event,id);const menu=document.getElementById('popmenu');if(!menu||_popAnchor!==event.currentTarget)return;menu.setAttribute('role','menu');menu.setAttribute('aria-label',globalThis.RunTeamsLocale?.t('language.title',{},'语言')??'语言');menu.querySelectorAll('a[data-i]').forEach(link=>{link.setAttribute('role','menuitemradio');link.setAttribute('aria-checked',String(link.classList.contains('selected')));});}

/* module-function:accountLanguageKey */
function accountLanguageKey(event){if(event.isComposing)return;const open=_popAnchor===event.currentTarget&&document.getElementById('popmenu');if(open&&event.key==='Escape'){event.preventDefault();event.stopPropagation();closePop();event.currentTarget.focus();}else if(open&&event.key==='Tab'){closePop();}else if(!open&&(event.key==='ArrowDown'||event.key==='ArrowUp')){event.preventDefault();accountLanguageOpen(event,'accountLanguage');}}

// Repaint this settings surface only; conversation drafts and authored content stay in place.
globalThis.RunTeamsLocale?.onChange(()=>{if(S.settingsTab==='general'&&document.getElementById('settingsWorkspace'))accountSettingsPaint();else if(document.getElementById('accountLanguage'))updateCsel('accountLanguage',accountLanguageItems(),accountLanguageValue());});

/* module-function:generalSettingsPanel */
function generalSettingsPanel(){
 const prefs=accountSettingsPrefs(),ready=accountSettingsEditable(),native=S.nativeSettings,nativeDisabled=!native||S.nativeSettingsLoading||S.nativeSettingsSaving||!!S.nativeSettingsError,display=accountDeviceDisplayPrefs();
 const text=(key,fallback)=>globalThis.RunTeamsLocale?.t(key,{},fallback)??fallback;
 const label=(key,fallback)=>`<span data-app-i18n="${key}">${esc(text(key,fallback))}</span>`;
 return `${settingsPageHead(text('general.title','通用'))}${accountSettingsNotice()}${accountNativeSettingsNotice()}${accountGeneralDisplayNotice()}${accountSettingsGroup(label('language.title','语言'),accountSettingsRow(label('language.interface','界面语言'),accountLanguageControl(),label('language.deviceOnly','界面语言仅保存在此设备。'),'accountLanguageHint'))}${accountSettingsGroup(label('general.interaction','输入与交互'),accountSettingsRow(label('general.send_mode','发送方式'),accountSettingsSelect('send_mode',[{value:'enter',label:text('general.enter','Enter 发送')},{value:'meta-enter',label:text('general.metaEnter','⌘Enter 发送')}],prefs.send_mode,!ready))+accountSettingsRow(label('general.allow_supplement','运行中允许补充要求'),accountSettingsSwitch('allow_supplement',prefs.allow_supplement,!ready),label('general.supplementHint','关闭后，新消息加入队列，当前回复结束后依次发送。')))}${accountSettingsGroup(label('general.runtime','启动与运行'),accountSettingsRow(label('general.launch_at_login','登录电脑时启动'),accountSettingsSwitch('launch_at_login',native?.launch_at_login,nativeDisabled),accountNativeSettingsBridge()?'':label('general.desktopOnly','在桌面应用中设置。'))+accountSettingsRow(label('general.restore_windows','启动时恢复上次窗口'),accountSettingsSwitch('restore_windows',display.restore_windows,!!S.appearanceDisplayReadFailed||!!S.appearanceSaveFailures?.restore_windows?.readOnly),label('general.deviceOnly','仅在这台电脑保存'))+accountSettingsRow(label('general.prevent_sleep','任务运行时防止自动休眠'),accountSettingsSwitch('prevent_sleep',native?.prevent_sleep,nativeDisabled),accountNativeSettingsBridge()?'':label('general.desktopOnly','在桌面应用中设置。'))+accountSettingsRow(label('general.close_action','关闭窗口后'),accountSettingsSelect('close_action',[{value:'background',label:text('general.background','继续后台运行')},{value:'quit',label:text('general.quit','退出应用')}],native?.close_action||'quit',nativeDisabled),label('general.quitHint','退出应用或电脑休眠后，本机停止执行。')))}${globalThis.RunTeamsBackups?.markup()||''}${globalThis.RunTeamsLibraryContinuation?.markup()||''}`;
}

/* module-function:accountGeneralDisplayNotice */
function accountGeneralDisplayNotice(){
 const failed=S.appearanceDisplayReadFailed,failure=S.appearanceSaveFailures?.restore_windows;if(!failed&&!failure)return '';
 const [key,message]=failure?.readOnly?['restoreSaveUnknown','窗口恢复设置保存结果待确认。']:
  failed?['restoreReadFailed','窗口恢复设置暂时无法读取，请重新读取后再修改。']:['restoreSaveFailed','窗口恢复设置未能保存。'];
 const reread=failed||failure?.readOnly;
 return `<div class="settings-inline-error" role="alert"><span data-app-i18n="general.${key}">${message}</span><button class="btn" data-app-i18n="general.${reread?'reread':'retry'}" onclick="accountGeneralRetryDisplay()">${reread?'重新读取':'重试'}</button></div>`;
}

/* module-function:accountGeneralRetryDisplay */
function accountGeneralRetryDisplay(){
 const failure=S.appearanceSaveFailures?.restore_windows;
 if(S.appearanceDisplayReadFailed||failure?.readOnly){accountDeviceDisplayPrefs();if(!S.appearanceDisplayReadFailed&&failure?.readOnly)delete S.appearanceSaveFailures.restore_windows;accountSettingsPaint();return;}
 if(failure)accountSaveDisplaySetting('restore_windows',failure.value);
}

/* module-function:normalizeSettingsTab */
function settingsPanels(){return {general:generalSettingsPanel,appearance:accountAppearanceSettings,notifications:accountNotificationSettings,channels:modelChannelsSettingsPanel,tools:accountToolsSettings,about:accountAboutSettings,...RunTeamsHost.settings.panels};}
function normalizeSettingsTab(tab){const panels=settingsPanels();return Object.hasOwn(panels,tab)&&typeof panels[tab]==='function'?tab:'general';}

/* module-function:settingsPanel */
function settingsChannelContents(loading=false,idPrefix="settingsChannel"){
 const cards=channelCardsMarkup(loading,idPrefix);
 const refreshing=S.channelSettingsRefreshing,cached=!!(cards&&S.channels?.length);
 const status=refreshing?`<div class="settings-preferences-loading" role="status">${cached?modelChannelText('listRefreshing','正在刷新渠道状态…'):modelChannelText('listLoading','正在读取渠道状态…')}</div>`:'';
 const failed=RunTeamsModelChannels.definitionError(S)||S.channelSettingsError;
 const failure=failed?`<div class="settings-inline-error" role="alert"><span>${cached?modelChannelText('listStale','无法刷新渠道状态，仍显示上次读取的信息。'):modelChannelText('listFailed','暂时无法读取渠道状态。')}</span><button type="button" class="btn" data-channel-list-retry data-app-i18n="modelChannel.reload" onclick="accountRefreshChannels(this)">重新读取</button></div>`:'';
 if(cards)return cards+(status||failure);
 if(status||S.environmentLoading)return status||'<div class="settings-preferences-loading" role="status" data-app-i18n="modelChannel.listLoading">正在读取渠道状态…</div>';
 return failure||'<div class="empty" data-app-i18n="modelChannel.listEmpty">暂无可用的模型渠道</div>';
}
function channelListMarkup(id='channel_list',{appearance='grouped'}={}){return `<div class="settings-channels channel-list${appearance==='plain'?' channel-list-plain':''}" id="${esc(id)}" tabindex="-1" role="group" aria-label="渠道账户" data-app-i18n-aria-label="modelChannel.accounts">${settingsChannelContents(false,id==='channel_list'?'settingsChannel':'guideChannel')}</div>`;}
function modelChannelsSettingsPanel(){return `${settingsPageHead(modelChannelText('settings','模型渠道'))}${accountSettingsGroup(modelChannelText('accounts','渠道账户'),channelListMarkup(),'','settingsChannelConnections')}${accountSettingsGroup(modelChannelText('defaults','新对话默认设置'),(RunTeamsHost.session.ready(S)?accountSettingsNotice():RunTeamsHost.settings.notice()||'')+accountModelDefaults(),'','settingsModelDefaults')}`;}
function settingsPanel(){return settingsPanels()[normalizeSettingsTab(S.settingsTab)]();}


/* module-function:openSettingsPage */
function openSettingsPage(tab,options={}){
 if(RunTeamsHost.settings.guard())return;
 RunTeamsHost.settings.closeMenu();closePop();
 const existing=document.getElementById('settingsWorkspace');
 if(!existing){S.settingsReturnFocus=options.returnFocus||document.activeElement;S.settingsScroll={};if(document.getElementById('modalHost'))closeModal();}
 const nextTab=normalizeSettingsTab(tab||'general');
 if(existing){switchSettingsTab(nextTab,{route:options.route});return;}
 S.settingsTab=nextTab;
 const root=document.createElement('section');root.id='settingsWorkspace';root.className='account-settings-page';root.setAttribute('aria-label','设置');root.dataset.appI18nAriaLabel='shell.settingsTitle';const returnUrl=new URL(location.href);returnUrl.searchParams.delete('settings');RunTeamsHost.settings.cleanRoute?.(returnUrl);root._returnRoute=returnUrl.pathname+returnUrl.search+returnUrl.hash;root._hasWorkspace=!!document.getElementById('rgMid')&&!S.booting;
 root.innerHTML=`${RunTeamsShell.settingsToolbar(ICON)}<aside class="settings-sidebar"><div class="settings-sidebar-title" data-app-i18n="shell.settingsTitle">设置</div><nav aria-label="设置分类" data-app-i18n-aria-label="shell.settingsSections">${accountSettingsNavigation()}</nav></aside><section class="settings-main"><main class="account-panel" id="settingsPanel">${settingsPanel()}</main></section>`;
 globalThis.RunTeamsLocale?.apply(root);
 document.body.appendChild(root);document.getElementById('app')?.setAttribute('inert','');
 if(options.route!==false)accountSettingsSetRoute(S.settingsTab,false);
 RunTeamsShell.syncHistoryControls();accountSettingsLoadTab();accountSettingsReadPreferences();accountReadNativeSettings();
 root.querySelector('.settings-page-head h2')?.focus({preventScroll:true});
}

/* module-function:switchSettingsTab */
function switchSettingsTab(tab,options={}){
 RunTeamsHost.settings.capture();const panel=document.getElementById('settingsPanel');S.settingsScroll=S.settingsScroll||{};
 if(panel)S.settingsScroll[S.settingsTab]=panel.scrollTop;
 S.settingsTab=normalizeSettingsTab(tab);closePop();if(document.querySelector('[data-settings-extension-dialog],[data-settings-tools-resource]'))closeChildDialog();
 document.querySelectorAll('[data-settings-tab]').forEach(button=>{const current=button.dataset.settingsTab===S.settingsTab;button.classList.toggle('on',current);button.setAttribute('aria-current',current?'page':'false');});
 if(panel){panel.innerHTML=settingsPanel();globalThis.RunTeamsLocale?.apply(panel);panel.scrollTop=S.settingsScroll[S.settingsTab]||0;RunTeamsHost.settings.restore();}
 if(options.route!==false)accountSettingsSetRoute(S.settingsTab,true);
 accountSettingsLoadTab();
}

/* module-function:setAccountTheme */
function setAccountTheme(value){if(!['light','dark','system'].includes(value))return;S.account.theme=value;applyAccountTheme(value);saveAccountPrefs();if(typeof accountAppearanceSaveNotice==='function')accountAppearanceSaveNotice();document.querySelectorAll('[data-theme-value]').forEach(button=>{const selected=button.dataset.themeValue===value;button.classList.toggle('on',selected);button.setAttribute('aria-pressed',selected?'true':'false');});}
// Account-local helpers; all durable application state stays on the host S.


if(typeof window!=='undefined')window.addEventListener?.('keydown',accountSettingsExtensionDocumentKeydown,true);


// Organization management uses the existing dialog, field, button and menu controls.
function settingsContext(){return workspaceAccountCacheToken();}


/* module-function:accountSettingsWorkspace */
function accountSettingsNavigation(){
 const common=[['应用',[['general','settings','通用','general.title'],['appearance','moon','外观','settingsNav.appearance'],['notifications','bell','通知','settingsNav.notifications']]],['模型与工具',[['channels','plug','模型渠道','settingsNav.channels'],['tools','package','技能与工具','settingsNav.tools']]],['支持',[['about','info','关于']]]];
 const groupKeys={'应用':'settingsNav.app','模型与工具':'settingsNav.modelsAndTools','支持':'settingsNav.support'};
 const groups=RunTeamsHost.settings.navigation(common);
 return groups.map(([title,items,titleKey=groupKeys[title]])=>[title,items.filter(item=>typeof settingsPanels()[item[0]]==='function'),titleKey]).filter(([,items])=>items.length).map(([title,items,titleKey])=>`<div class="settings-nav-group"><div class="settings-nav-label"${titleKey?` data-app-i18n="${esc(titleKey)}"`:''}>${title}</div>${items.map(item=>settingsNavButton(...item)).join('')}</div>`).join('');
}
function accountSettingsSetRoute(tab,replace){const url=new URL(location.href);url.searchParams.set('settings',tab);RunTeamsHost.settings.updateRoute(url,tab);const target=url.pathname+url.search+url.hash;if(target!==location.pathname+location.search+location.hash){history[replace?'replaceState':'pushState']({...history.state},'',target);if(!replace)RunTeamsShell.recordNavigation(false);}RunTeamsShell.syncHistoryControls();}
function accountSettingsRestoreRoute(){RunTeamsHost.settings.restoreRoute();const tab=new URLSearchParams(location.search).get('settings');if(tab){const normalized=normalizeSettingsTab(tab);if(normalized!==tab)accountSettingsSetRoute(normalized,true);openSettingsPage(normalized,{route:false});return true;}const root=document.getElementById('settingsWorkspace'),restore=!!root?._hasWorkspace&&root._returnRoute===location.pathname+location.search+location.hash;accountSettingsUnmount();return restore;}
function accountSettingsUnmount(){if(document.querySelector('[data-settings-extension-dialog],[data-settings-tools-resource]'))closeChildDialog();const root=document.getElementById('settingsWorkspace');if(!root)return;closePop();S.settingsScroll=S.settingsScroll||{};S.settingsScroll[S.settingsTab]=document.getElementById('settingsPanel')?.scrollTop||0;root.remove();document.getElementById('app')?.removeAttribute('inert');S.settingsReturnFocus?.focus?.();S.settingsReturnFocus=null;clearAgentSetupContinuation();}
function accountSettingsClose(){accountSettingsUnmount();const url=new URL(location.href);url.searchParams.delete('settings');RunTeamsHost.settings.cleanRoute?.(url);history.replaceState(history.state,'',url.pathname+url.search+url.hash);RunTeamsShell.syncHistoryControls();}
function accountSettingsPaint(){
 const panel=document.getElementById('settingsPanel');if(!panel||!document.getElementById('settingsWorkspace'))return;
 RunTeamsHost.settings.capture();const scroll=panel.scrollTop,active=document.activeElement,id=panel.contains(active)?active.id:'',action=panel.contains(active)?active.getAttribute('onclick'):null;
 const focus=id||((!active||active===document.body)?panel._settingsFocusId:'');
 const pending=S.settingsPreferencePending||S.nativeSettingsSaving||S.nativeSettingsLoading;
 panel._settingsFocusId=pending?(id||panel._settingsFocusId):'';
 const html=settingsPanel();
 if(!accountSettingsPatchControls(panel,html)){
  panel.innerHTML=html;
  globalThis.RunTeamsLocale?.apply(panel);
 }
 panel.scrollTop=scroll;RunTeamsHost.settings.restore();
 if(focus)document.getElementById(focus)?.focus({preventScroll:true});
 else if(action)[...panel.querySelectorAll('button')].find(button=>button.getAttribute('onclick')===action)?.focus({preventScroll:true});
 RunTeamsHost.settings.paint(S.settingsTab);
}
/* module-function:accountSettingsPatchControls */
function accountSettingsPatchControls(panel,html){
 if(S.settingsTab==='tools')return accountToolsPatch(panel,html);
 if(S.settingsTab==='channels'){const next=panel.cloneNode(false);next.innerHTML=html;RunTeamsLocale.apply(next);accountChannelReconcile(panel,next);return true;}
 if(!['general','notifications'].includes(S.settingsTab))return false;
 const next=panel.cloneNode(false);next.innerHTML=html;globalThis.RunTeamsLocale?.apply?.(next);
 const previous=panel.cloneNode(true),selector='button.settings-switch,button.csel';
 const current=[...panel.querySelectorAll(selector)],updated=[...next.querySelectorAll(selector)];
 if(!current.length||current.length!==updated.length||current.some((node,index)=>node.id!==updated[index].id))return false;
 // Only reconcile controls when everything around them is unchanged. Errors,
 // language changes and structural changes still use the normal page render.
 for(const root of [previous,next])for(const node of root.querySelectorAll(selector))node.replaceWith(document.createComment(node.id));
 if(previous.innerHTML!==next.innerHTML)return false;
 current.forEach((node,index)=>{
  const value=updated[index];accountSettingsKeepPendingAppearance(node,value);
  for(const attribute of [...node.attributes])if(!value.hasAttribute(attribute.name))node.removeAttribute(attribute.name);
  for(const attribute of value.attributes)if(node.getAttribute(attribute.name)!==attribute.value)node.setAttribute(attribute.name,attribute.value);
  const label=node.querySelector('.cv'),newLabel=value.querySelector('.cv');
  if(label&&newLabel&&label.textContent!==newLabel.textContent)label.textContent=newLabel.textContent;
 });
 return true;
}
/* module-function:accountSettingsKeepPendingAppearance */
function accountSettingsKeepPendingAppearance(node,value){
 const key=node.id.replace(/^settings_/,''),native=['launch_at_login','prevent_sleep','close_action'].includes(key);
 const personal=['send_mode','allow_supplement','notification_timing','confirmation','information','failure','completion','sound','default_model','default_effort'].includes(key);
 const pending=native?!!S.nativeSettings&&!S.nativeSettingsError&&(S.nativeSettingsSaving||S.nativeSettingsLoading):personal&&RunTeamsHost.session.ready(S)&&S.settingsPreferencesState==='ready'&&S.settingsPreferencePending&&!S.settingsPreferenceError&&!S.settingsPreferenceRetry?.readOnly;
 if(!pending||!value.hasAttribute('disabled')||node.hasAttribute('disabled'))return;
 // Keep the existing appearance and keyboard focus. The original save guards
 // and dropdown configuration still reject input until the acknowledgement.
 value.removeAttribute('disabled');value.setAttribute('aria-disabled','true');value.setAttribute('data-settings-pending','true');
}

/* module-function:accountSettingsGroup */
function accountSettingsGroup(title,rows,action='',id=''){return `<section class="settings-section"${id?` id="${id}"`:''}>${settingsSectionHead(title,'',action)}<div class="settings-row-group">${rows}</div></section>`;}
function accountSettingsControlSkeleton(kind='select',label='设置',labelKey=''){
 return `<span class="skeleton-block settings-control-skeleton settings-control-skeleton-${kind}" data-settings-skeleton role="status" aria-busy="true" aria-label="正在读取${esc(label)}"${labelKey?` data-app-i18n-aria-label="${esc(labelKey)}"`:''} inert></span>`;
}
function accountSettingsFieldSkeleton(key,kind){

 const native=['launch_at_login','prevent_sleep','close_action'].includes(key),personal=['send_mode','allow_supplement','notification_timing','confirmation','information','failure','completion','sound','default_model','default_effort'].includes(key);
 const pending=native?typeof accountNativeSettingsBridge==='function'&&!!accountNativeSettingsBridge()&&!S.nativeSettings&&(S.nativeSettingsLoading||!S.nativeSettingsError):personal&&RunTeamsHost.session.ready(S)&&!S.settingsPreferences&&!['ready','error'].includes(S.settingsPreferencesState);
 const label=({send_mode:'发送方式',allow_supplement:'补充要求设置',launch_at_login:'启动设置',prevent_sleep:'休眠设置',close_action:'关闭窗口设置',notification_timing:'提醒时机',confirmation:'确认提醒',information:'信息提醒',failure:'失败提醒',completion:'完成提醒',sound:'提示音',default_model:'默认模型',default_effort:'默认思考强度'})[key]||'设置';
 const labelKey=({default_model:'modelChannel.defaultModelLoading',default_effort:'modelChannel.defaultReasoningLoading',
  send_mode:'general.sendModeLoading',allow_supplement:'general.supplementLoading',launch_at_login:'general.launchLoading',
  prevent_sleep:'general.sleepLoading',close_action:'general.closeLoading',
  notification_timing:'notifications.timingLoading',confirmation:'notifications.confirmationLoading',
  information:'notifications.informationLoading',failure:'notifications.failureLoading',
  completion:'notifications.completionLoading',sound:'notifications.soundLoading'})[key];
 return pending?accountSettingsControlSkeleton(kind,label,labelKey):'';
}
function accountSettingsRow(label,control='',detail='',detailId=''){return `<div class="settings-row"><div class="settings-row-copy"><b>${label}</b>${detail?`<small${detailId?` id="${detailId}"`:''}>${detail}</small>`:''}</div>${control?`<div class="settings-row-control">${control}</div>`:''}</div>`;}
function accountSettingsSwitch(key,value,disabled=false){const skeleton=accountSettingsFieldSkeleton(key,'switch');if(skeleton)return skeleton;const busy=['launch_at_login','prevent_sleep'].includes(key)?S.nativeSettingsSaving&&S.nativeSettingsRetry?.key===key:S.settingsPreferencePending&&S.settingsPreferenceRetry?.key===key;return `<button id="settings_${key}" type="button" role="switch" aria-busy="${!!busy}" aria-label="${esc(globalThis.RunTeamsLocale?.t('general.'+key,{},accountSettingsLabels()[key]||key)??accountSettingsLabels()[key]??key)}" aria-checked="${!!value}" class="settings-switch" ${disabled?'disabled':''} onclick="accountSettingsToggle('${key}')"><span></span></button>`;}
function accountSettingsLabels(){return {send_mode:'发送方式',allow_supplement:'运行中允许补充要求',restore_windows:'启动时恢复上次窗口',launch_at_login:'登录电脑时启动',prevent_sleep:'任务运行时防止自动休眠',confirmation:'需要确认',information:'需要补充信息',failure:'工作失败',completion:'工作完成',sound:'播放提示音'};}
function accountSettingsSelect(key,items,value,disabled=false){const skeleton=accountSettingsFieldSkeleton(key,'select');if(skeleton)return skeleton;const labelKey=({default_model:'defaultModel',default_effort:'defaultReasoning'})[key],busy=labelKey&&S.settingsPreferencePending&&S.settingsPreferenceRetry?.key===key;return csel('settings_'+key,items,value,next=>accountSettingsSave(key,next),{disabled,menuVariant:'settingsSelect',menuAlign:'right'}).replace('aria-haspopup="menu"',`${key==='send_mode'?`title="${value==='meta-enter'?'Enter 换行':'Shift+Enter 换行'}" data-app-i18n-title="general.${value==='meta-enter'?'enterNewline':'shiftEnterNewline'}" `:''}aria-label="${esc((['send_mode','close_action'].includes(key)?globalThis.RunTeamsLocale?.t('general.'+key,{},accountSettingsLabels()[key]||'关闭窗口后'):null)||accountSettingsLabels()[key]||({interface_font_size:'界面字号',code_font_size:'代码字号',default_model:'默认模型',default_effort:'默认思考强度',notification_timing:'提醒时机',close_action:'关闭窗口后'}[key])||key)}" ${labelKey?modelChannelAttrs(labelKey,null,'-aria-label'):''}${busy?' aria-busy="true"':''} aria-haspopup="menu" onkeydown="accountSettingsSelectKey(event,'settings_${key}')"`);}
function accountSettingsSelectKey(event,id){if(event.isComposing)return;if(document.getElementById('popmenu')&&_popAnchor===event.currentTarget)return;if(['ArrowDown','ArrowUp','Enter',' '].includes(event.key)&&!event.currentTarget.disabled){event.preventDefault();event.stopPropagation();cselOpen(event,id);}}
function accountSettingsPrefs(){return {send_mode:'enter',allow_supplement:true,notification_timing:'background',confirmation:true,information:true,failure:true,completion:true,sound:true,...S.settingsPreferences};}
function accountSettingsEditable(){return !!(RunTeamsHost.session.ready(S))&&S.settingsPreferencesState==='ready'&&!S.settingsPreferencePending&&!S.settingsPreferenceRetry?.readOnly;}
async function accountGeneralReload(button,checking=false){
 const context=settingsContext(),focused=document.activeElement===button;
 const field=checking?S.settingsPreferenceRetry?.key:'send_mode';
 if(checking)await accountSettingsRetrySave(true);
 else await accountSettingsReadPreferences(true);
 if(!focused)return;
 requestAnimationFrame(()=>{
  if(S.settingsTab!=='general'||context!==settingsContext()||document.activeElement!==document.body)return;
  const panel=document.getElementById('settingsPanel');
  const target=panel?.querySelector('[data-general-account-reload]')||document.getElementById('settings_'+field);
  target?.focus({preventScroll:true});
 });
}
function accountSettingsNotice(){
 const general=S.settingsTab==='general',notifications=S.settingsTab==='notifications',channels=S.settingsTab==='channels';
 if(!S.localLibrary&&!RunTeamsHost.session.ready(S))return RunTeamsHost.settings.notice()||'';
 if(channels){
  if(S.settingsPreferencesState==='error')return `<div class="settings-inline-error" role="alert">${modelChannelText('defaultsReadFailed','暂时无法读取新对话默认设置。请重新加载后再修改。')}<button class="btn" data-app-i18n="modelChannel.reload" onclick="accountSettingsReadPreferences(true)">重新读取</button></div>`;
  if(S.settingsPreferenceError){
   const message=S.settingsPreferenceRetry?.readOnly?modelChannelText('defaultsSaveUnknown','暂时无法确认是否已保存。请重新加载，核对当前设置。'):modelChannelText('defaultsSaveFailed','未能保存。仍使用上次确认的设置，请重新加载后再修改。');
   return `<div class="settings-inline-error" role="alert">${message}<button class="btn" data-app-i18n="modelChannel.reload" onclick="accountSettingsRetrySave(true)">重新读取</button></div>`;
  }
  return '';
 }
 if(general){
  if(S.settingsPreferencesState==='error')return '<div class="settings-inline-error" role="alert"><span><span data-app-i18n="general.accountReadFailed">账户设置暂时无法读取</span><br><span data-app-i18n="general.accountReadHint">请重新加载后，再修改发送方式和补充要求。</span></span><button class="btn" data-app-i18n="general.reload" data-general-account-reload onclick="accountGeneralReload(this)">重新加载</button></div>';
  if(S.settingsPreferenceError){
   const unknown=!!S.settingsPreferenceRetry?.readOnly;
   return `<div class="settings-inline-error" role="alert"><span data-app-i18n="general.${unknown?'accountSaveUnknown':'accountSaveFailed'}">${unknown?'账户设置保存结果待确认。请重新加载，核对设置是否已更新。':'设置未能保存，仍使用上次确认的值。'}</span><button class="btn" data-app-i18n="general.${unknown?'reload':'retry'}" ${unknown?'data-general-account-reload onclick="accountGeneralReload(this,true)"':'onclick="accountSettingsRetrySave()"'}>${unknown?'重新加载':'重试'}</button></div>`;
  }
  return '';
 }
 if(notifications){
  if(S.settingsPreferencesState==='error')return '<div class="settings-inline-error" role="alert"><span data-app-i18n="notifications.preferencesReadFailed">暂时无法读取提醒设置。请重新加载后再修改。</span><button class="btn" data-app-i18n="general.reload" onclick="accountSettingsReadPreferences(true)">重新加载</button></div>';
  if(S.settingsPreferenceError){
   const unknown=!!S.settingsPreferenceRetry?.readOnly;
   return `<div class="settings-inline-error" role="alert"><span data-app-i18n="notifications.${unknown?'preferencesSaveUnknown':'preferencesSaveFailed'}">${unknown?'请重新加载，确认提醒设置是否已保存。':'未能保存提醒设置。仍使用上次保存的设置。'}</span><button class="btn" data-app-i18n="general.${unknown?'reload':'retry'}" onclick="accountSettingsRetrySave()">${unknown?'重新加载':'重试'}</button></div>`;
  }
  return '';
 }
 if(S.settingsPreferencesState==='error')return `<div class="settings-inline-error" role="alert"><span>设置暂时无法读取</span><button class="btn" onclick="accountSettingsReadPreferences(true)">重新加载</button></div>`;
 if(S.settingsPreferenceError){const unknown=!!S.settingsPreferenceRetry?.readOnly,message=esc(S.settingsPreferenceError);return `<div class="settings-inline-error" role="alert"><span>${message}</span><button class="btn" onclick="accountSettingsRetrySave()">${unknown?'重新加载':'重试'}</button></div>`;}
 if(S.settingsPreferencesState!=='ready')return '';
 // The disabled control communicates a pending save without moving the page.
 return '';
}
/* module-function:accountSettingsReadPreferences */
async function accountSettingsReadPreferences(force=false){
 if(!S.localLibrary&&!RunTeamsHost.session.ready(S))return;const context=settingsContext();if(S.settingsPreferencesRead?.context===context)return S.settingsPreferencesRead.promise;if(!force&&S.settingsPreferencesState==='ready')return;
 const read={context};S.settingsPreferencesRead=read;S.settingsPreferencesState='loading';accountSettingsPaint();
 read.promise=(async()=>{try{const result=await RunTeamsHost.settings.read();if(context!==settingsContext()||S.settingsPreferencesRead!==read)return;if(result.error||(!result.settings||typeof result.settings!=='object'||Array.isArray(result.settings)))throw Error('设置读取失败');const value=result.settings;if(!value||typeof value!=='object'||Array.isArray(value))throw Error('设置格式无效');S.settingsPreferences=value;S.settingsPreferencesState='ready';accountSettingsSyncInteraction();}catch(error){if(context===settingsContext()&&S.settingsPreferencesRead===read)S.settingsPreferencesState='error';}finally{if(S.settingsPreferencesRead===read)S.settingsPreferencesRead=null;if(context===settingsContext()){accountSettingsStartRuntimeMonitor();accountSettingsPaint();}}})();return read.promise;
}

function accountSettingsToggle(key){if(['launch_at_login','prevent_sleep'].includes(key)){accountSaveNativeSetting(key,!S.nativeSettings?.[key]);return;}const device=key==='restore_windows';accountSettingsSave(key,!(device?accountDeviceDisplayPrefs()[key]:accountSettingsPrefs()[key]));}
async function accountSettingsSave(key,value){
 if(key==='close_action'){await accountSaveNativeSetting(key,value);return;}
 if(['interface_font_size','code_font_size','restore_windows'].includes(key)){if(key==='restore_windows'&&S.appearanceSaveFailures?.restore_windows?.readOnly)return;accountSaveDisplaySetting(key,value);return;}
 if(!accountSettingsEditable())return;const context=settingsContext(),previous=accountSettingsPrefs(),next={...previous,[key]:value};
 if(key==='default_model'&&value){const [channel,model]=String(value).split('::'),c=S.channels.find(item=>String(item.id)===channel);if(!c||!modelChannelAvailable(c)||!channelCatalog(c).models.some(item=>item.value===model))return;next.default_effort=defaultEffort(c,model);}
 if(key==='default_effort'){const [id,model]=String(previous.default_model||'').split('::'),channel=S.channels.find(c=>String(c.id)===id),item=channel&&channelCatalog(channel).models.find(row=>row.value===model);if(!channel||!modelChannelAvailable(channel)||!item||!((item.efforts||[]).length?(item.efforts||[]).includes(value):value===''))return;}
 const patch={[key]:value};if(key==='default_model')patch.default_effort=value?next.default_effort:'';
 S.settingsPreferencePending=true;S.settingsPreferenceError='';S.settingsPreferenceRetry={key,value};accountSettingsPaint();
 try{const result=await RunTeamsHost.settings.save(patch);if(context!==settingsContext())return;if(result.error)throw Object.assign(Error(result.error),{code:result.code});if(result.ok!==true||!result.settings||typeof result.settings!=='object'||Array.isArray(result.settings)||Object.entries(patch).some(([field,expected])=>result.settings[field]!==expected))throw Error('设置未能保存');S.settingsPreferences=result.settings;S.settingsPreferenceRetry=null;accountSettingsSyncInteraction();if(['notification_timing','confirmation','information','failure','completion','sound'].includes(key)&&typeof accountNotifyPreferencesChanged==='function')accountNotifyPreferencesChanged();}
 catch(error){if(context===settingsContext()){if(error.code==='mutation_outcome_unknown'){S.settingsPreferenceRetry={key,value,patch,readOnly:true};S.settingsPreferenceError='保存结果尚未确认，请重新读取。';}else S.settingsPreferenceError='设置未能保存，仍使用上次确认的值。';}}
 finally{if(context===settingsContext()){S.settingsPreferencePending=false;accountSettingsPaint();}}
}
function accountSettingsSyncInteraction(){if(typeof conversationSyncSendState==='function')for(const surface of ['chat','panel','skills'])conversationSyncSendState(surface);}
function accountNativeSettingsNotice(){
 const general=S.settingsTab==='general';
 if(general&&accountNativeSettingsBridge()){
  if(S.nativeSettingsLoading&&!S.nativeSettings)return '';
  if(S.nativeSettingsLoading||S.nativeSettingsSaving)return '';
 }
 const error=S.nativeSettingsError||S.nativeSettings?.runtime_error;if(!error)return '';
 if(general){
  const unknown=error==='本机设置未能保存，请重试。',readFailed=error==='本机设置暂时无法读取',runtime=!!S.nativeSettings?.runtime_error&&!S.nativeSettingsError;
  if(unknown||readFailed||runtime){
   const title=unknown?'本机运行设置保存结果待确认':readFailed?'本机运行设置暂时无法读取':'本机运行状态暂时无法确认',note=unknown?'请先重新读取，核对设置是否已更新。':readFailed?'请重新读取后，再修改启动、休眠和关闭窗口选项。':'防止自动休眠可能未生效，请重新读取。';
   const key=unknown?'nativeSaveUnknown':readFailed?'nativeReadFailed':'runtimeUnknown';
   return `<div class="settings-inline-error" role="alert"><span><span data-app-i18n="general.${key}">${title}</span><br><span data-app-i18n="general.${key}Hint">${note}</span></span><button class="btn" data-app-i18n="general.reread" onclick="accountReadNativeSettings()">重新读取</button></div>`;
  }
 }
 return `<div class="settings-inline-error" role="alert">${esc(error)} <button class="btn" onclick="accountRetryNativeSetting()">重试</button></div>`;
}
function accountRetryNativeSetting(){if(S.nativeSettingsError)return accountReadNativeSettings();const retry=S.nativeSettingsRetry;if(retry)return accountSaveNativeSetting(retry.key,retry.value);return accountReadNativeSettings();}
async function accountSettingsRetrySave(forceRead=false){const pending=S.settingsPreferenceRetry;if(!pending)return;if(!pending.readOnly&&!forceRead){accountSettingsSave(pending.key,pending.value);return;}const context=settingsContext();await accountSettingsReadPreferences(true);if(context!==settingsContext())return;if(S.settingsPreferencesState==='ready'&&(S.settingsTab==='general'||!pending.readOnly||Object.entries(pending.patch||{[pending.key]:pending.value}).every(([key,value])=>S.settingsPreferences?.[key]===value))){S.settingsPreferenceError='';S.settingsPreferenceRetry=null;accountNotifyPreferencesChanged();}else S.settingsPreferenceError='保存结果尚未确认，请稍后重新读取。';accountSettingsPaint();}
function accountDeviceDisplayPrefs(){let value={};S.appearanceDisplayReadFailed=false;try{value=JSON.parse(localStorage.getItem('runteams_device_display_v1')||'{}')||{};}catch(error){S.appearanceDisplayReadFailed=true;}return {interface_font_size:[12,13,14,16,18].includes(value.interface_font_size)?value.interface_font_size:14,code_font_size:[11,12,13,14,16,18].includes(value.code_font_size)?value.code_font_size:13,restore_windows:value.restore_windows!==false};}
function accountApplyDisplayPrefs(){const prefs=accountDeviceDisplayPrefs();if(S.appearanceDisplayReadFailed)return;document.documentElement.style.setProperty('--interface-font-size',prefs.interface_font_size+'px');document.documentElement.style.setProperty('--interface-font-scale',String(prefs.interface_font_size/14));document.documentElement.style.setProperty('--code-font-size',prefs.code_font_size+'px');}
function accountSaveDisplaySetting(key,value){
 const allowed={interface_font_size:[12,13,14,16,18],code_font_size:[11,12,13,14,16,18],restore_windows:[true,false]};
 if(!allowed[key]?.includes(value))return;
 const previous=accountDeviceDisplayPrefs();if(S.appearanceDisplayReadFailed){accountSettingsPaint();return;}
 const next={...previous,[key]:value};let written=false;
 try{localStorage.setItem('runteams_device_display_v1',JSON.stringify(next));written=true;const saved=accountDeviceDisplayPrefs();if(S.appearanceDisplayReadFailed||saved[key]!==value)throw Error('设置未确认');if(S.appearanceSaveFailures)delete S.appearanceSaveFailures[key];accountApplyDisplayPrefs();}
 catch(error){S.appearanceSaveFailures={...S.appearanceSaveFailures,[key]:{value,readOnly:written,message:key==='restore_windows'?(written?'窗口恢复设置保存结果待确认。':'窗口恢复设置未能保存。'):(written?'字号保存结果待确认。请核对当前字号后再修改。':'字号未能保存。请重新选择字号。')}};if(key==='restore_windows')toast(S.appearanceSaveFailures[key].message,'err',written?'general.restoreSaveUnknown':'general.restoreSaveFailed');}
 accountSettingsPaint();
}
function accountAppearanceLabel(key,fallback){return `<span data-app-i18n="${key}">${esc(globalThis.RunTeamsLocale?.t(key,{},fallback)??fallback)}</span>`;}
function accountAppearanceNotice(){
 const failures=Object.entries(S.appearanceSaveFailures||{}),readFailed=S.appearanceDisplayReadFailed;
 if(!readFailed&&!failures.length)return '';
 const copy=readFailed?[['appearance.fontReadFailed','暂时无法读取字号。'],['appearance.fontReadHint','请重新读取后再调整。']]:failures.map(([field,item])=>{
  if(field==='theme')return item.readOnly?['appearance.themeSaveUnknown','主题已应用。请重新读取，确认是否已保存。']:['appearance.themeSaveFailed','主题已应用，但未能保存。'];
  if(field==='restore_windows')return [item.readOnly?'general.restoreSaveUnknown':'general.restoreSaveFailed',item.message];
  return item.readOnly?['appearance.fontSaveUnknown','请重新读取，确认字号是否已保存。']:['appearance.fontSaveFailed','未能保存字号。'];
 });
 const reload=readFailed||failures.some(([,item])=>item.readOnly),action=reload?accountAppearanceLabel('general.reread','重新读取'):accountAppearanceLabel('appearance.retry','重试');
 const messages=[...new Set(copy.map(([key,fallback])=>accountAppearanceLabel(key,fallback)))].join(readFailed?'<br>':' ');
 return `<div class="settings-inline-error" role="alert"><span>${messages}</span><button class="btn" onclick="accountAppearanceRetry()">${action}</button></div>`;
}
function accountAppearanceSaveNotice(){const node=document.getElementById('appearanceSaveNotice');if(node)node.innerHTML=accountAppearanceNotice();}
function accountAppearanceRetry(){
 const failures=Object.entries({...S.appearanceSaveFailures});
 if(S.appearanceDisplayReadFailed||failures.some(([,item])=>item.readOnly)){
  const saved=accountDeviceDisplayPrefs();
  if(!S.appearanceDisplayReadFailed){for(const [key,item]of failures){if(!item.readOnly)continue;let confirmed=false;if(key==='theme'){try{confirmed=localStorage.getItem('runteams_device_theme')===item.value;}catch(error){}}else confirmed=saved[key]===item.value;if(confirmed)delete S.appearanceSaveFailures[key];}accountApplyDisplayPrefs();}
  accountSettingsPaint();return;
 }
 for(const [key,item]of failures){if(key==='theme')setAccountTheme(item.value);else accountSaveDisplaySetting(key,item.value);}
}
function accountSyncDeviceAppearance(event){
 if(event.storageArea&&event.storageArea!==localStorage)return;
 if(event.key===null||event.key==='runteams_device_theme'){S.account.theme=loadAccountPrefs().theme;if(S.appearanceSaveFailures)delete S.appearanceSaveFailures.theme;applyAccountTheme(S.account.theme);}
 if(event.key===null||event.key==='runteams_device_display_v1'){if(S.appearanceSaveFailures)for(const key of ['interface_font_size','code_font_size','restore_windows'])delete S.appearanceSaveFailures[key];accountApplyDisplayPrefs();}
 if(event.key===null||['runteams_device_theme','runteams_device_display_v1'].includes(event.key))accountSettingsPaint();
}
function accountAppearanceSettings(){
 const prefs=accountDeviceDisplayPrefs(),label=accountAppearanceLabel;
 const fontRow=(key,title,values)=>{
  const name='appearance.'+key,items=values.map(value=>({value,label:value+' px'}));
  const control=accountSettingsSelect(key,items,prefs[key],!!S.appearanceDisplayReadFailed).replace('aria-label="','data-app-i18n-aria-label="'+name+'" aria-label="');
  return accountSettingsRow(label(name,title),control);
 };
 return `${settingsPageHead(label('settingsNav.appearance','外观'))}<div id="appearanceSaveNotice" aria-live="polite">${accountAppearanceNotice()}</div><section class="settings-section">${settingsSectionHead(label('appearance.theme','主题'))}<div class="appearance-options">${appearanceOption('system',label('appearance.system','跟随系统'))}${appearanceOption('light',label('appearance.light','浅色'))}${appearanceOption('dark',label('appearance.dark','深色'))}</div></section>${accountSettingsGroup(label('appearance.text','文字'),fontRow('interface_font_size','界面字号',[12,13,14,16,18])+fontRow('code_font_size','代码字号',[11,12,13,14,16,18]))}`;
}
function accountNotificationSettings(){
 const prefs=accountSettingsPrefs(),native=!!accountNativeSettingsBridge(),permission=native?S.nativeSettings?.notification_permission:typeof Notification!=='undefined'?Notification.permission:'unavailable',unsupported=permission==='unavailable',permissionUnknown=!!S.notificationPermissionError&&S.notificationPermissionRetry==='read',permissionUnreadable=native&&(!!S.nativeSettingsError||!!S.nativeSettingsLoading||!['default','granted','denied'].includes(permission)),off=unsupported||permissionUnreadable||permissionUnknown||!accountSettingsEditable()||prefs.notification_timing==='never';
 const label=(key,text)=>`<span data-app-i18n="notifications.${key}">${esc(text)}</span>`;
 const controlLabel=(html,key)=>html.replace(/<button\b/,`<button data-app-i18n-aria-label="notifications.${key}"`);
 const rows=[['confirmation','需要确认'],['information','需要补充信息'],['failure','工作失败'],['completion','工作完成']].map(([key,text])=>accountSettingsRow(label(key,text),controlLabel(accountSettingsSwitch(key,prefs[key],off),key))).join('');
 const openSettings=`<button type="button" class="btn" data-notification-settings data-app-i18n="notifications.openSettings" onclick="accountSettingsOpenNotificationSystem()">打开系统设置</button>`;
 let error='',reload=false,loadingKey='systemLoading',loadingText='正在读取系统通知权限…';
 if(S.notificationPermissionError){
  const key=permissionUnknown?'permissionUnknown':S.notificationPermissionRetry==='settings'?'openSettingsFailed':native?'deliveryFailed':'browserPermissionHint';
  error=label(key,S.notificationPermissionError);reload=permissionUnknown||key==='deliveryFailed';
 }else if(native&&!S.nativeSettingsLoading&&S.nativeSettingsError){
  error=label('permissionReadFailed','无法读取系统通知权限。');reload=true;
 }else if((!native||permission==='granted')&&(S.nativeSettings?.notification_error||S.notificationDeliveryError)){
  const failure=S.nativeSettings?.notification_error;
  error=failure==='read'?label('alertsReadFailed','无法读取工作提醒。'):
   failure==='delivery'?label('alertsSendFailed','无法发送工作提醒。'):
   label('deliveryFailed','暂时无法显示工作提醒。');
  reload=true;loadingKey='alertsChecking';loadingText='正在检查工作提醒…';
 }
 const systemTitle=label('system','系统通知');
 let system='';
 if(unsupported)system=`<p class="settings-footnote">${label('unsupported','当前环境不支持桌面通知。')}</p>`;
 else if(native&&(S.nativeSettingsLoading||!S.nativeSettingsError)&&!['default','granted','denied'].includes(permission)&&(!permissionUnknown||S.nativeSettingsLoading))system=accountSettingsGroup(systemTitle,accountSettingsRow(accountSettingsControlSkeleton('line','系统通知状态','notifications.systemLoading'),accountSettingsControlSkeleton('select','系统通知操作','notifications.systemLoading')));
 else if(!permissionUnreadable){
  if(permission==='granted')system=accountSettingsGroup(systemTitle,accountSettingsRow(label('granted','系统通知已允许'),native?openSettings:''));
  else if(permission==='denied')system=accountSettingsGroup(systemTitle,accountSettingsRow(label('denied','系统通知未获允许'),native?openSettings:'',native?label('systemPermissionHint','请在系统设置中允许 RunTeams 发送通知。'):label('browserPermissionHint','请在浏览器的网站设置中允许通知。')));
  else {
   const request=S.notificationPermissionPending?label('requesting','正在请求通知权限…'):label('allow','允许通知');
   const button=`<button type="button" class="btn" data-notification-permission onclick="accountSettingsNotificationPermission()" aria-busy="${!!S.notificationPermissionPending}" ${S.notificationPermissionPending||permissionUnknown?'disabled':''}>${request}</button>`;
   system=accountSettingsGroup(systemTitle,accountSettingsRow(label('allowDesktop','允许桌面通知'),button+(native&&S.notificationPermissionError?openSettings:''),label('allowHint','允许 RunTeams 显示工作提醒。')));
  }
 }
 const timings=[{value:'always',label:'始终提醒',labelKey:'notifications.always'},{value:'background',label:'仅应用在后台时',labelKey:'notifications.background'},{value:'never',label:'不提醒',labelKey:'notifications.never'}];
 const timing=controlLabel(accountSettingsSelect('notification_timing',timings,prefs.notification_timing,unsupported||permissionUnreadable||permissionUnknown||!accountSettingsEditable()),'timing');
 const sound=controlLabel(accountSettingsSwitch('sound',prefs.sound,off),'sound');
 const note=prefs.notification_timing==='never'?label('offHint','桌面提醒已关闭，提示音也会关闭。'):permission==='granted'?label('focusHint','通知显示和提示音取决于系统通知和专注模式设置。'):'';
 const reloading=reload&&S.nativeSettingsLoading;
 const notice=error?`<div class="settings-inline-error" role="alert">${error}<button type="button" class="btn" data-notification-retry data-app-i18n="${reloading?'notifications.'+loadingKey:reload?'notifications.checkAgain':'general.retry'}" onclick="accountSettingsRetryNotifications()" ${reloading?'disabled aria-busy="true"':''}>${reloading?loadingText:reload?'重新检查':'重试'}</button></div>`:'';
 return `${settingsPageHead('<span data-app-i18n="settingsNav.notifications">通知</span>')}${accountSettingsNotice()}${notice}${system}${accountSettingsGroup(label('desktop','桌面提醒'),accountSettingsRow(label('timing','提醒时机'),timing))}${accountSettingsGroup(label('work','工作提醒'),rows)}${accountSettingsGroup(label('sounds','声音'),accountSettingsRow(label('sound','播放提示音'),sound))}${note?`<p class="settings-footnote">${note}</p>`:''}`;
}
function accountFocusNotificationState(){
 if(S.settingsTab!=='notifications'||document.activeElement!==document.body)return;
 const panel=document.getElementById('settingsPanel');
 const target=panel?.querySelector('[data-notification-retry]:not(:disabled)')||panel?.querySelector('[data-notification-settings], [data-notification-permission]:not(:disabled)')||panel?.querySelector('.settings-page-head h2');
 target?.focus({preventScroll:true});
}
async function accountSettingsNotificationPermission(){
 if(S.notificationPermissionPending||S.notificationPermissionRetry==='read')return;
 const focused=document.activeElement?.hasAttribute?.('data-notification-permission');
 S.notificationPermissionPending=true;S.notificationPermissionError='';S.notificationPermissionRetry='';accountSettingsPaint();
 try{if(accountNativeSettingsBridge()){const result=await accountNativeSettingsBridge().postMessage({action:'permission'});if(!['granted','denied'].includes(result?.notification_permission)||typeof result.prevent_sleep!=='boolean'||typeof result.launch_at_login!=='boolean'||!['background','quit'].includes(result.close_action))throw Error('通知权限未确认');S.nativeSettings=result;}else if(typeof Notification!=='undefined')await Notification.requestPermission();else throw Error('不支持通知');}
 catch(error){S.notificationPermissionError='通知权限待确认，请重新读取系统通知权限后再设置。';S.notificationPermissionRetry='read';}
 finally{S.notificationPermissionPending=false;accountSettingsPaint();if(focused)accountFocusNotificationState();}
}
async function accountSettingsOpenNotificationSystem(){
 S.notificationPermissionError='';S.notificationPermissionRetry='';try{const bridge=accountNativeSettingsBridge();if(!bridge){S.notificationPermissionError='请在浏览器的网站设置中允许通知。';return;}const result=await bridge.postMessage({action:'notification_settings'});if(result?.ok!==true)throw Error('系统设置未打开');}catch(error){S.notificationPermissionError='未能打开系统通知设置，请从系统设置中打开 RunTeams 的通知选项。';S.notificationPermissionRetry='settings';}finally{accountSettingsPaint();}
}
async function accountSettingsRetryNotifications(){
 const focused=document.activeElement?.hasAttribute?.('data-notification-retry');
 try{
  if(S.notificationPermissionRetry==='read'){
   if(accountNativeSettingsBridge())await accountReadNativeSettings();
   else if(typeof Notification!=='undefined'&&['default','granted','denied'].includes(Notification.permission)){
    S.notificationPermissionError='';S.notificationPermissionRetry='';accountSettingsPaint();
   }
   return;
  }
  if(S.notificationPermissionRetry==='permission'){await accountSettingsNotificationPermission();return;}
  if(S.notificationPermissionRetry==='settings'){await accountSettingsOpenNotificationSystem();return;}
  if(S.nativeSettingsError&&!S.notificationPermissionError){await accountReadNativeSettings();return;}
  S.notificationPermissionError='';
  await accountReadNativeSettings();
  accountNotifyPreferencesChanged();
  if(!accountNativeSettingsBridge())RunTeamsHost.lifecycle.pollNotifications();
  accountSettingsPaint();
 }finally{if(focused)accountFocusNotificationState();}
}
function accountNotifyPreferencesChanged(clear=false){const bridge=accountNativeSettingsBridge();if(bridge)bridge.postMessage({action:'notifications_changed',clear}).catch(()=>{S.notificationPermissionError='工作提醒暂时不可用，请重新读取服务状态。';accountSettingsPaint();});}




function accountModelDefaults(){
 const modelLabel=modelChannelText('defaultModel','默认模型'),reasoningLabel=modelChannelText('defaultReasoning','默认思考强度');
 if(!S.modelCatalogReady&&(S.modelCatalogLoading||!S.modelCatalogError)){
  const skeleton=(key,label)=>`<span class="skeleton-block channel-default-skeleton" role="status" aria-label="${label}"${modelChannelAttrs(key,null,'-aria-label')} aria-busy="true"></span>`;
  return accountSettingsRow(modelLabel,skeleton('defaultModelLoading','正在读取默认模型…'))+accountSettingsRow(reasoningLabel,skeleton('defaultReasoningLoading','正在读取默认思考强度…'));
 }
 const prefs=accountSettingsPrefs(),channels=(S.channels||[]).filter(modelChannelAvailable);
 const items=channels.flatMap(channel=>(channelCatalog(channel).models||[]).map(model=>({value:String(channel.id)+'::'+model.value,label:model.display_name||model.value})));
 const value=prefs.default_model||'',channel=channels.find(item=>String(item.id)===value.split('::')[0]),model=value.split('::')[1],known=items.some(item=>item.value===value);
 const choices=[...(value&&!known?[{value,label:'当前默认模型不可用',labelKey:'modelChannel.defaultUnavailable',disabled:true}]:[]),{value:'',label:'旗舰模型（自动）',labelKey:'modelChannel.automatic'},...items];
 const selectable=RunTeamsModelChannels.hasSelectableModels(S),disabled=!accountSettingsEditable()||S.modelCatalogLoading||!S.modelCatalogReady||!!S.modelCatalogError&&!selectable;
 let notice='';
 if(S.modelCatalogError){
  const message=selectable?modelChannelText('partialModels','暂时无法读取部分渠道的模型列表。'):modelChannelText('modelsFailed','暂时无法读取可用模型。请重新读取后再选择。');
  notice=`<div class="settings-inline-error" role="alert">${message}<button class="btn" data-app-i18n="modelChannel.reload" onclick="refreshModelCatalog(true).catch(()=>{})">重新读取</button></div>`;
 }else if(S.modelCatalogReady&&channels.length&&!items.length){
  notice='<div class="settings-inline-error" role="status"><span data-app-i18n="modelChannel.modelsEmpty">暂无可用模型。请检查渠道登录状态和模型权限。</span><button class="btn" data-app-i18n="modelChannel.checkAgain" onclick="accountRefreshChannels()">重新检测</button></div>';
 }
 const hint=value&&!known?modelChannelText('defaultUnavailableHint','连接对应渠道，或选择其他模型。'):items.length||channels.length||S.modelCatalogLoading||S.modelCatalogError||S.environmentLoading||S.channelSettingsRefreshing?'':modelChannelText('defaultConnectHint','连接渠道后即可查看可用模型。');
 const effortChoices=channel&&known?effortItems(channel,model,prefs.default_effort,true):[{value:'',label:'模型默认'}];
 const efforts=effortChoices.map(item=>({...item,labelKey:Object.hasOwn(EFFORT_LABELS,item.value)?'runtimeSelector.level.'+item.value:item.value?undefined:'runtimeSelector.defaultEffort'}));
 return notice+accountSettingsRow(modelLabel,accountSettingsSelect('default_model',choices,value,disabled),hint)+accountSettingsRow(reasoningLabel,accountSettingsSelect('default_effort',efforts,channel&&known?normalizedEffort(channel,model,prefs.default_effort):'',disabled||!channel||!known));
}
function accountSettingsExtensionSource(item,env=S.settingsExtensions){return (env?.channels||[]).find(row=>String(row.id)===String(item.channel_id))||S.channels?.find(row=>String(row.id)===String(item.channel_id))||{};}
function accountSettingsExtensionProvider(item,env=S.settingsExtensions){return item.provider||accountSettingsExtensionSource(item,env).provider||'';}
function accountSettingsExtensionStatus(item,key,env=S.settingsExtensions){
 if(item._settingsStale)return '未更新';if(item.error||item.read_state==='error')return '读取失败';if(item.enabled===false||item.enabled===0||item.status==='disabled')return '已停用';
 const auth=String(item.auth_status||'').toLowerCase(),status=String(item.status||'').toLowerCase();
 if(item.authenticated===false||['required','error','not_logged_in','unauthorized','login_required','unauthenticated'].includes(auth)||status==='login_required')return '需要登录';
 const source=accountSettingsExtensionSource(item,env);if(!source.id)return '来源待确认';if(source.ready!==true)return '渠道不可用';
 if(['error','failed','disconnected'].includes(status)||item.connected===false)return key==='mcp_servers'?'未连接':'加载失败';if(status==='pending_approval')return '待授权';
 return key==='skills'?'可用':key==='plugins'?(item.enabled===true?'已启用':'已安装'):item.connected===true||['connected','ready'].includes(status)?'已连接':'已配置';
}
function toolsAttrs(key,vars,attribute=''){return ` data-app-i18n${attribute}="settingsTools.${key}"${vars?` data-app-i18n-vars="${esc(JSON.stringify(vars))}"`:''}`;}
function toolsCopy(key,text,vars){return `<span${toolsAttrs(key,vars)}>${esc(text)}</span>`;}
function toolsStatusCopy(status){const key=({'未更新':'stale','读取失败':'readFailed','已停用':'disabled','需要登录':'signInRequired','来源待确认':'unknownSource','渠道不可用':'channelUnavailable','未连接':'notConnected','加载失败':'loadFailed','待授权':'permissionRequired','可用':'available','已启用':'enabled','已安装':'installed','已连接':'connected','已配置':'configured','待安装':'notInstalled'})[status];return key?toolsCopy(key,status):esc(status);}
/* module-function:accountToolsSettings */
function accountToolsView(){
 const context=settingsContext();if(S.settingsToolsView?.context!==context)S.settingsToolsView={context,tab:'plugins',catalog:false,queries:{},limit:50};return S.settingsToolsView;
}
function accountToolsCategories(){return [['plugins','插件'],['mcp_servers','MCP'],['skills','技能']];}
function accountToolsKey(){const view=accountToolsView();return view.catalog?'available_plugins':view.tab;}
function accountToolsRows(){
 const key=accountToolsKey(),view=accountToolsView(),query=String(view.queries[key]||'').trim().toLocaleLowerCase();
 return (S.settingsExtensions?.[key]||[]).map((item,index)=>({item,index})).filter(({item})=>!query||[item.display_name,item.name,item.id,item.description,item.channel_name,item.provider,item.marketplace].some(value=>String(value||'').toLocaleLowerCase().includes(query)));
}
function accountToolsStatus(){
 const key=accountToolsKey(),sourceKey=key==='available_plugins'?'plugins':key,env=S.settingsExtensions;
 return {loading:S.settingsExtensionsState==='loading',error:S.settingsExtensionsState==='error',failed:(env?.channels||[]).some(channel=>['error','partial'].includes(channel.read_states?.[sourceKey]))};
}
function accountToolsNotice(){
 const {loading,error,failed}=accountToolsStatus(),env=S.settingsExtensions;
 if(loading)return env?`<div class="settings-tools-notice" role="status">${toolsCopy('inventoryRefreshing','正在刷新工具清单…')}</div>`:'';
 if(error||failed){
  const [key,copy]=error?(env?.[accountToolsKey()]?.length?['inventoryStale','清单未更新，仍显示上次读取的内容。']:['inventoryFailed','暂时无法读取工具清单。']):['inventoryPartial','部分来源暂时无法读取。请重新读取后再管理。'];
  return `<div class="settings-tools-notice settings-inline-error" role="alert">${toolsCopy(key,copy)}<button type="button" class="btn" data-tools-list-retry${toolsAttrs('reload')} onclick="accountToolsReload(this)">重新读取</button></div>`;
 }
 if(env?.channels?.some(channel=>!channel.ready))return `<div class="settings-tools-notice">${toolsCopy('channelsUnavailable','部分模型渠道暂不可用。相关工具状态待确认。')}<button class="btn"${toolsAttrs('checkChannels')} onclick="openSettingsPage(&quot;channels&quot;)">检查模型渠道</button></div>`;
 return '';
}
function accountToolsTabs(){
 const view=accountToolsView(),env=S.settingsExtensions;
 return accountToolsCategories().map(([key,label])=>`<button type="button" id="toolsTab_${key}" role="tab" aria-selected="${view.tab===key}" aria-controls="settingsToolsList" tabindex="${view.tab===key?'0':'-1'}" onclick="accountToolsSelect('${key}')" onkeydown="accountToolsTabKey(event,'${key}')">${toolsCopy(key,label)}${env?`<small>${(env[key]||[]).length}</small>`:''}</button>`).join('');
}
function accountToolsIcon(item,key){
 const parent=key==='skills'&&(S.settingsExtensions?.plugins||[]).find(row=>String(row.channel_id)===String(item.channel_id)&&row.id===item.plugin_id),url=item.icon_url||parent?.icon_url||'';
 return /^\/api\/environment\/plugin-icon\/[a-f0-9]{24}$/.test(url)?`<img src="${esc(url)}" alt="" loading="lazy" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span hidden>${ICON(key==='mcp_servers'?'plug':'package')}</span>`:ICON(key==='mcp_servers'?'plug':'package');
}
function accountToolsSkeleton(key){
 const bone=kind=>`<span class="skeleton-block tools-skeleton-${kind}"></span>`,actions=(key==='skills'?bone('scope'):'')+(key==='mcp_servers'?bone('gear'):'')+(key==='available_plugins'?'':bone('switch'))+(key==='mcp_servers'?'':bone('arrow'));
 const rows=Array.from({length:4},()=>key==='mcp_servers'?`<div class="tools-mcp-row"><div class="tools-mcp-name">${bone('title')}${bone('logo')}</div><div class="settings-tool-actions">${actions}</div></div>`:`<div class="settings-tool-row ${key==='skills'?'settings-skill-row':''}"><div class="settings-tool-identity">${bone('icon')}<span class="settings-tool-copy">${bone('title')}${bone('description')}</span></div><div class="settings-tool-actions">${actions}</div></div>`).join('');
 return `<span class="sr-only" role="status"${toolsAttrs('loading')}>正在读取工具清单…</span><div data-settings-skeleton data-skeleton-list aria-hidden="true" inert>${key==='mcp_servers'?`<section class="tools-section"><h3>${bone('title')}</h3><div class="tools-row-group">${rows}</div></section>`:rows}</div>`;
}
function accountToolsList(){
 const view=accountToolsView(),key=accountToolsKey(),env=S.settingsExtensions,{loading,error,failed}=accountToolsStatus();
 if(!env)return loading?accountToolsSkeleton(key):'';
 const rows=accountToolsRows(),query=String(view.queries[key]||'').trim();
 if(!rows.length){
  if(error||failed||loading&&S.settingsExtensionsConfirmedScope!==S.settingsExtensionsScope)return '';
  const [empty,heading]=query?['noMatches','未找到匹配项']:({available_plugins:['catalogEmpty','暂无可用插件'],plugins:['pluginsEmpty','暂无插件'],skills:['skillsEmpty','暂无技能'],mcp_servers:['mcpEmpty','暂无 MCP 连接']})[key];
  const hint=query?toolsCopy('searchHint','试试其他名称、简介或来源。'):key==='available_plugins'?(env.channels?.some(channel=>channel.ready)?toolsCopy('catalogEmptyConnected','已连接的 Agent 暂无可用插件。'):toolsCopy('catalogEmptyHint','连接模型渠道后，即可查看对应 Agent 提供的插件。')):key==='plugins'&&RunTeamsHost.settings.localToolImport?toolsCopy('pluginsEmptyHint','选择本地插件文件夹并导入。'):'';
  const action=query?`<button class="btn"${toolsAttrs('clearSearch')} onclick="accountToolsClearSearch()">清除搜索</button>`:key==='plugins'&&RunTeamsHost.settings.localToolImport?`<button class="btn"${toolsAttrs('browse')} onclick="accountToolsBrowseFolder(this)">浏览文件夹</button>`:'';
  return `<div class="settings-tools-empty"><h3>${toolsCopy(empty,heading)}</h3>${hint?`<p>${hint}</p>`:''}${action}</div>`;
 }
 const shown=rows.slice(0,view.limit),html=key==='mcp_servers'?accountToolsMcpGroups(shown):shown.map(({item,index})=>accountToolsRow(item,key,index)).join('');
 const count=rows.length,results=query?toolsCopy(count===1?'oneResult':'results','找到 '+count+' 项',{count}):'';
 return html+(count>view.limit?`<button class="btn settings-tools-more"${toolsAttrs('showMore')} onclick="accountToolsMore()">显示更多</button>`:'')+`<span class="settings-tools-results" role="status">${results}</span>`;
}
function accountToolsSettings(){
 const view=accountToolsView();if(view.detail)return accountToolsDetailPage(view.detail);
 const key=accountToolsKey(),label=accountToolsCategories().find(row=>row[0]===view.tab)?.[1]||'插件',query=view.queries[key]||'';
 const searchKey=key==='available_plugins'?'search_plugins':'search_'+key,search='搜索'+(view.catalog?'插件':label);
 const title=view.catalog?toolsCopy('catalog','插件目录'):`<span data-app-i18n="settingsNav.tools">技能与工具</span>`;
 const browse=view.catalog?`<button class="btn"${toolsAttrs('installedPlugins')} onclick="accountToolsCatalog(false)">返回已安装</button>`:RunTeamsHost.settings.localToolImport?`<button class="btn"${toolsAttrs('browse')} onclick="accountToolsBrowseFolder(this)">浏览文件夹</button>`:'';
 return `<div class="settings-tools" data-tools-view="${view.catalog?'catalog':view.tab}"><div class="settings-tools-heading">${settingsPageHead(title,view.catalog?toolsCopy('catalogHint','来自已连接 Agent 的可用插件'):'')}<div class="settings-tools-heading-actions">${browse}<button type="button" id="settingsToolsAdd" class="btn pri" data-menu-trigger="primary" aria-haspopup="menu" onclick="accountToolsAddMenu(this)">${toolsCopy('add','添加')} ${ICON('chev')}</button></div></div><div class="settings-tools-toolbar">${view.catalog?`<span class="settings-tools-catalog-label"${toolsAttrs('availablePlugins')}>可用插件</span>`:`<div class="settings-tools-tabs" role="tablist" aria-label="工具分类"${toolsAttrs('categories',null,'-aria-label')}>${accountToolsTabs()}</div>`}<label class="settings-tools-search rt-search-field rt-search-field--compact">${ICON('search')}<input id="settingsToolsSearch" type="search" value="${esc(query)}" placeholder="${search}" aria-label="${search}"${toolsAttrs(searchKey,null,'-placeholder')}${toolsAttrs(searchKey,null,'-aria-label')} oninput="accountToolsSearch(this.value)" onkeydown="if(event.key==='Escape'&&!event.isComposing){event.stopPropagation();accountToolsClearSearch()}"></label></div><div id="settingsToolsNotice">${accountToolsNotice()}</div><div id="settingsToolsList" role="tabpanel" aria-busy="${S.settingsExtensionsState==='loading'}" ${view.catalog?`aria-label="插件目录"${toolsAttrs('catalog',null,'-aria-label')}`:`aria-labelledby="toolsTab_${view.tab}"`}>${accountToolsList()}</div></div>`;
}
function accountToolsSelect(key){if(!accountToolsCategories().some(row=>row[0]===key))return;const view=accountToolsView();view.tab=key;view.catalog=false;view.detail=null;view.limit=50;accountSettingsPaint();document.getElementById('settingsPanel').scrollTop=0;document.getElementById('toolsTab_'+key)?.focus({preventScroll:true});}
function accountToolsTabKey(event,key){if(event.isComposing||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const keys=accountToolsCategories().map(row=>row[0]),index=keys.indexOf(key);accountToolsSelect(keys[event.key==='Home'?0:event.key==='End'?keys.length-1:(index+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length]);}
function accountToolsCatalog(show){const view=accountToolsView();view.catalog=show;view.detail=null;view.limit=50;accountSettingsPaint();document.getElementById('settingsPanel').scrollTop=0;document.getElementById('settingsToolsSearch')?.focus({preventScroll:true});}
function accountToolsSearch(value){const view=accountToolsView();view.queries[accountToolsKey()]=String(value);view.limit=50;const list=document.getElementById('settingsToolsList');if(list)list.innerHTML=accountToolsList();}
function accountToolsClearSearch(){const input=document.getElementById('settingsToolsSearch');if(input){input.value='';accountToolsSearch('');input.focus();}}
function accountToolsMore(){const view=accountToolsView(),list=document.getElementById('settingsToolsList');view.limit+=50;if(list)list.innerHTML=accountToolsList();}
function accountToolsPatch(panel,html){
 const current=panel.querySelector('.settings-tools');if(!current)return false;const next=panel.cloneNode(false);next.innerHTML=html;globalThis.RunTeamsLocale?.apply(next);const tools=next.querySelector('.settings-tools');if(!tools)return false;if(current.dataset.toolsDetail||tools.dataset.toolsDetail)return current.outerHTML===tools.outerHTML;if(tools.dataset.toolsView!==current.dataset.toolsView)return false;
 for(const selector of ['.settings-tools-tabs','#settingsToolsNotice','#settingsToolsList']){const a=current.querySelector(selector),b=tools.querySelector(selector);if(a&&b){if(a.innerHTML!==b.innerHTML)a.innerHTML=b.innerHTML;if(b.hasAttribute('aria-busy'))a.setAttribute('aria-busy',b.getAttribute('aria-busy'));}}return true;
}
async function accountToolsBrowseFolder(button){
 if(!RunTeamsHost.settings.localToolImport||S.settingsToolsPicking)return;
 const context=settingsContext(),focused=document.activeElement===button;S.settingsToolsPicking=true;
 if(button){button.disabled=true;button.setAttribute('aria-busy','true');}
 try{
  const picked=await api('/api/environment/local/pick','POST',{});
  if(context!==settingsContext()||picked.cancelled)return;
  if(picked.error||!picked.token||!picked.channels?.length||!['plugin','skill'].includes(picked.kind)){
   toast('无法导入此文件夹。请选择技能或插件的根文件夹，再确认对应渠道已连接。','err','settingsTools.folderInvalid');
   return;
  }
  const detail={key:'local-import',context,token:(S.settingsExtensionDialogSequence||0)+1,picked};S.settingsExtensionDialogSequence=detail.token;S.settingsExtensionDetail=detail;
  const skill=picked.kind==='skill',title=skill?'导入技能':'导入插件',titleKey=skill?'importSkill':'importPlugin';
  const targets=picked.channels.map(row=>`<option value="${esc(row.id)}">${esc(row.name)}</option>`).join('');
  const host=openChildDialog({manageFocus:true,className:'settings-extension-dialog',title,titleKey:'settingsTools.'+titleKey,closeLabelKey:'settingsTools.close',attrs:`role="dialog" aria-modal="true" aria-label="${title}"${toolsAttrs(titleKey,null,'-aria-label')} data-settings-extension-dialog="${detail.token}" onkeydown="accountSettingsExtensionKeydown(event)"`,
   body:`<p>${esc(picked.name)}</p><label class="tools-import-target">${toolsCopy('importTo','导入到')}<span class="tools-import-control"><select id="toolsImportChannel">${targets}</select>${ICON('chev')}</span></label><p id="toolsImportStatus" role="status" tabindex="-1"></p><details id="toolsImportError" hidden><summary>${toolsCopy('details','详情')}</summary><p></p></details>`,
   footer:`<button class="btn"${toolsAttrs('cancel')} onclick="closeChildDialog()">取消</button><button id="toolsImportConfirm" class="btn pri"${toolsAttrs('import')} onclick="accountToolsImportFolder(${detail.token})">导入</button>`});
  if(host&&focused&&button?.isConnected)host._returnFocus=button;
 }catch(error){if(context===settingsContext())toast('无法打开文件夹。请重试。','err','settingsTools.folderOpenFailed');}
 finally{S.settingsToolsPicking=false;if(button?.isConnected){button.disabled=false;button.removeAttribute('aria-busy');if(focused&&document.activeElement===document.body)button.focus({preventScroll:true});}}
}
async function accountToolsImportFolder(token){
 const detail=accountSettingsExtensionDialogCurrent(token);if(!detail||detail.submitted)return;
 detail.submitted=true;
 const channel=document.getElementById('toolsImportChannel'),button=document.getElementById('toolsImportConfirm'),status=document.getElementById('toolsImportStatus');
 const setStatus=(key,text)=>{status.textContent=text;status.setAttribute('data-app-i18n','settingsTools.'+key);globalThis.RunTeamsLocale?.apply(status);};
 const focused=document.activeElement===button;
 button.disabled=true;channel.disabled=true;setStatus('importing','正在导入…');
 if(focused)status.focus({preventScroll:true});
 try{
  const result=await api('/api/environment/local/import','POST',{token:detail.picked.token,channel_id:channel.value});
  if(detail.context!==settingsContext())return;
  if(result?.error)throw Object.assign(Error(result.error),{code:result.code});
  if(result?.ok!==true||result.kind!==detail.picked.kind||typeof result.name!=='string'||!result.name)throw Object.assign(Error(),{code:'mutation_outcome_unknown'});
  S.channelMutationVersion=(S.channelMutationVersion||0)+1;
  const view=accountToolsView();view.catalog=false;view.detail=null;view.tab=result.kind==='skill'?'skills':'plugins';view.queries[view.tab]='';
  if(accountSettingsExtensionDialogCurrent(token))closeChildDialog();
  await accountReadSettingsExtensions(true);
  if(detail.context===settingsContext())toast('已导入 '+result.name,'ok','settingsTools.imported',{name:result.name});
 }catch(error){
  if(!accountSettingsExtensionDialogCurrent(token))return;
  const unknown=error.code==='mutation_outcome_unknown';
  setStatus(unknown?'importUnknown':'importFailed',unknown?'暂时无法确认导入结果。请关闭弹窗并重新读取清单。':'未能完成导入。请关闭弹窗并重新读取清单后再试。');
  const diagnostics=document.getElementById('toolsImportError');
  if(error.message&&diagnostics){diagnostics.querySelector('p').textContent=error.message;diagnostics.hidden=false;}
  button.textContent='已提交';button.setAttribute('data-app-i18n','settingsTools.submitted');
 }
}
function accountToolsAddMenu(anchor){
 openMenu(anchor,[{label:'浏览插件目录',labelKey:'settingsTools.browseCatalog',fn:()=>accountToolsCatalog(true)},{label:'添加 MCP',labelKey:'settingsTools.addMcp',fn:()=>accountToolsAddGuide('mcp')},{label:'添加技能',labelKey:'settingsTools.addSkill',fn:()=>accountToolsAddGuide('skills')},{divider:true},{label:'重新读取',labelKey:'settingsTools.reload',fn:()=>accountReadSettingsExtensions(true)}],{variant:'settingsSelect',align:'right'});
 const menu=document.getElementById('popmenu');
 menu?.querySelectorAll('[role="menuitemradio"]').forEach(item=>{item.setAttribute('role','menuitem');item.removeAttribute('aria-checked');});
}
function accountToolsAddGuide(kind){
 const detail={key:'guide',context:settingsContext(),token:(S.settingsExtensionDialogSequence||0)+1,commands:[]};S.settingsExtensionDialogSequence=detail.token;S.settingsExtensionDetail=detail;
 const sources=(S.settingsExtensions?.channels||[]).filter(row=>row.ready&&['codex','claude-code'].includes(row.provider));
 if(kind==='mcp')detail.commands=sources.map(row=>({label:row.name||providerDefinition(row.provider)?.label||row.provider,command:accountExtensionShellArgument(row.runtime?.executable||(row.provider==='codex'?'codex':'claude'))+' mcp add --help'}));
 const skill=kind==='skills',title=skill?'添加技能':'添加 MCP 连接',titleKey=skill?'addSkill':'addMcp';
 const body=skill?`<p>${toolsCopy('addSkillHint','将技能放入来源 Agent 的技能目录，然后重新读取。')}</p><p>${toolsCopy('addSkillDiscovery','Agent 会自动发现原生技能。插件附带的技能可通过插件目录添加。')}</p>`:`<p>${toolsCopy('addMcpHint','在对应 Agent 中添加 MCP 连接，然后重新读取。')}</p>`;
 const commands=detail.commands.map((command,index)=>`<p>${esc(command.label)} <button class="btn"${toolsAttrs('copyCommand')} onclick="accountCopySettingsExtensionCommand(${detail.token},${index})">复制命令</button></p><code class="install-command">${esc(command.command)}</code>`).join('');
 const hint=sources.length?'':`<p>${toolsCopy('connectFirst','请先连接模型渠道。')}</p>`;
 openChildDialog({manageFocus:true,className:'settings-extension-dialog',title,titleKey:'settingsTools.'+titleKey,closeLabelKey:'settingsTools.close',attrs:`role="dialog" aria-modal="true" aria-label="${title}"${toolsAttrs(titleKey,null,'-aria-label')} data-settings-extension-dialog="${detail.token}" onkeydown="accountSettingsExtensionKeydown(event)"`,body:body+commands+hint+'<p id="settingsExtensionCopyStatus" role="status"></p>',footer:`<button class="btn"${toolsAttrs('reload')} onclick="closeChildDialog();accountReadSettingsExtensions(true)">重新读取</button><button class="btn"${toolsAttrs('done')} onclick="closeChildDialog()">完成</button>`});
}
function accountToolsReadonlyState(item,key){
 const status=accountSettingsExtensionStatus(item,key),known=typeof item.enabled==='boolean'&&!item._settingsStale&&S.settingsExtensionsState==='ready'&&!['来源待确认','读取失败','未更新','渠道不可用'].includes(status);
 const name=item.display_name||item.name||item.id||'';
 return known?`<span class="tools-state-control" title="启停由来源 Agent 管理"${toolsAttrs('managed',null,'-title')}><button type="button" class="settings-switch tools-readonly-switch" role="switch" aria-label="${esc(name)}：${item.enabled?'已启用':'已停用'}，由来源 Agent 管理"${toolsAttrs(item.enabled?'managedEnabled':'managedDisabled',{name},'-aria-label')} aria-checked="${item.enabled}" disabled><span></span></button></span>`:`<span class="settings-extension-status">${toolsStatusCopy(status)}</span>`;
}
function accountToolsSourceLogo(item){
 const provider=accountSettingsExtensionProvider(item),source=item.channel_name||accountSettingsExtensionSource(item).name,icon=providerBrandIcon(provider);
 return `<span class="tools-source-logo" role="img" aria-label="${esc(source||'来源待确认')}" title="${esc(source||'来源待确认')}"${source?'':toolsAttrs('unknownSource',null,'-aria-label')+toolsAttrs('unknownSource',null,'-title')}>${icon||ICON('plug')}</span>`;
}
function accountToolsRow(item,key,index){
 const name=item.display_name||item.name||item.id,source=item.channel_name||accountSettingsExtensionSource(item).name,skill=key==='skills';
 const origin=({personal:['personal','个人'],system:['system','系统'],project:['project','项目'],plugin:['plugins','插件']})[item.source||item.scope],action=`accountSettingsExtensionDetail('${key}',${index})`;
 const vars={name:name||'',source:source||''},label=name?(source?'viewWithSource':'viewNamed'):'details';
 const detailKey=skill?'skillDetails':'details';
 return `<div class="settings-tool-row ${skill?'settings-skill-row':''}"><button type="button" class="settings-tool-identity" aria-label="查看 ${esc(name||'详情')}"${toolsAttrs(label,vars,'-aria-label')} onclick="${action}"><span class="settings-tool-icon" aria-hidden="true">${accountToolsIcon(item,key)}</span><span class="settings-tool-copy"><span class="settings-tool-name">${name?esc(name):toolsCopy('unnamed','未命名工具')}${accountToolsSourceLogo(item)}</span><span class="settings-tool-description">${item.description?esc(item.description):toolsCopy('noDescription','暂无简介')}</span></span></button><div class="settings-tool-actions">${skill&&origin?`<span class="settings-extension-status">${toolsCopy(...origin)}</span>`:''}${skill||key==='plugins'?accountToolsReadonlyState(item,key):''}<button type="button" class="tools-icon-button" aria-label="查看 ${esc(name||'详情')}" title="${skill?'技能详情':'详情'}"${toolsAttrs(name?'detailsNamed':'details',vars,'-aria-label')}${toolsAttrs(detailKey,null,'-title')} onclick="${action}">${ICON('chev')}</button></div></div>`;
}
function accountToolsMcpGroups(rows){
 const group=(title,items)=>items.length?`<section class="tools-section"><h3>${title}</h3><div class="tools-row-group">${items.map(({item,index})=>{
  const name=item.name||item.id||'';
  return `<div class="tools-mcp-row"><button type="button" class="tools-mcp-name" onclick="accountSettingsExtensionDetail('mcp_servers',${index})"><span>${esc(name)}</span>${accountToolsSourceLogo(item)}</button><div class="settings-tool-actions"><button type="button" class="tools-icon-button" aria-label="查看 ${esc(name)} MCP 配置"${toolsAttrs('mcpConfiguration',{name},'-aria-label')} onclick="accountSettingsExtensionDetail('mcp_servers',${index})">${ICON('settings')}</button>${accountToolsReadonlyState(item,'mcp_servers')}</div></div>`;
 }).join('')}</div></section>`:'';
 return group(toolsCopy('servers','服务器'),rows.filter(({item})=>!item.plugin_id))+group(toolsCopy('fromPlugins','来自插件'),rows.filter(({item})=>item.plugin_id));
}
function accountToolsBack(){const view=accountToolsView(),detail=view.detail;view.detail=null;accountSettingsPaint();const panel=document.getElementById('settingsPanel');if(panel){panel.scrollTop=view.listScroll||0;const index=S.settingsExtensions?.[detail?.key]?.findIndex(item=>accountSettingsExtensionIdentity(item)===detail.identity),action=`accountSettingsExtensionDetail('${detail?.key}',${index})`;[...panel.querySelectorAll('button')].find(button=>button.getAttribute('onclick')===action)?.focus({preventScroll:true});}}
function accountToolsSafeLink(url,label,key){
 try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return '';return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer"${key?toolsAttrs(key):''}>${esc(label||u.href)}</a>`;}catch{return '';}
}
function accountToolsDetailPage(detail){
 const item=S.settingsExtensions?.[detail.key]?.find(row=>accountSettingsExtensionIdentity(row)===detail.identity),mcp=detail.key==='mcp_servers',name=item?.display_name||item?.name||item?.id;
 const displayName=name?esc(name):toolsCopy('toolDetails','工具详情');
 const back=mcp?toolsCopy('mcp_servers','MCP'):detail.key==='available_plugins'?toolsCopy('catalog','插件目录'):toolsCopy('plugins','插件');
 const breadcrumb=`<div class="tools-breadcrumb"><button type="button" class="settings-tools-back" onclick="accountToolsBack()">${back}</button>${ICON('chev')}<span>${displayName}</span></div>`;
 if(!item)return `<div class="settings-tools" data-tools-detail="true">${breadcrumb}<div class="settings-tools-empty">${toolsCopy('toolGone','此工具已不在当前清单中。')}</div></div>`;
 const source=accountSettingsExtensionSource(item),status=['error','loading'].includes(S.settingsExtensionsState)||item._settingsStale?'未更新':detail.key==='available_plugins'?'待安装':accountSettingsExtensionStatus(item,detail.key);
 const facts=rows=>`<div class="tools-row-group tools-facts">${rows.filter(([,value])=>value).map(([label,value])=>`<div class="tools-fact-row"><dt>${label}</dt><dd>${value}</dd></div>`).join('')}</div>`;
 const skills=(S.settingsExtensions?.skills||[]).map((skill,index)=>({skill,index})).filter(({skill})=>String(skill.channel_id)===String(item.channel_id)&&skill.plugin_id===item.id);
 const skillRows=skills.map(({skill,index})=>`<div class="tools-contained-skill"><button type="button" class="settings-tool-identity" onclick="accountSettingsExtensionDetail('skills',${index})"><span class="settings-tool-copy"><span class="settings-tool-name">${esc(skill.name)}</span><span class="settings-tool-description">${skill.description?esc(skill.description):toolsCopy('noDescription','暂无简介')}</span></span></button>${accountToolsReadonlyState(skill,'skills')}<button type="button" class="tools-icon-button" aria-label="查看 ${esc(skill.name)}"${toolsAttrs('detailsNamed',{name:skill.name},'-aria-label')} onclick="accountSettingsExtensionDetail('skills',${index})">${ICON('chev')}</button></div>`).join('');
 const sourceName=item.channel_name||source.name;
 const about=[[toolsCopy('channel','渠道'),sourceName?esc(sourceName):toolsCopy('unknownSource','来源待确认')],[toolsCopy('status','状态'),toolsStatusCopy(status)]];
 if(mcp)about.push([toolsCopy('transport','连接类型'),item.transport?esc(item.transport):toolsCopy('notProvided','未提供')]);
 else about.push([toolsCopy('category','类别'),esc(item.category||'')],[toolsCopy('developer','开发者'),esc(item.developer_name||'')],[toolsCopy('version','版本'),esc(item.version||'')],[toolsCopy('website','网站'),accountToolsSafeLink(item.homepage_url)],[toolsCopy('privacy','隐私政策'),accountToolsSafeLink(item.privacy_policy_url,'查看隐私政策','viewPrivacy')],[toolsCopy('terms','服务条款'),accountToolsSafeLink(item.terms_url,'查看服务条款','viewTerms')]);
 return `<div class="settings-tools tools-detail-page" data-tools-detail="true">${breadcrumb}<div class="tools-detail-content"><div class="tools-detail-hero">${mcp?'':`<span class="settings-tool-icon tools-hero-icon">${accountToolsIcon(item,detail.key)}</span>`}<div class="tools-detail-title"><h2>${displayName}${mcp?' MCP':''}</h2><p>${item.description?esc(item.description):toolsCopy('noDescription','暂无简介')}</p></div><div class="tools-detail-actions">${!mcp&&item.homepage_url?accountToolsSafeLink(item.homepage_url,'访问网站','visitWebsite'):''}<button class="btn"${toolsAttrs('management')} onclick="accountToolsManageCurrent()">管理方式</button></div></div>${!mcp&&skills.length?`<section class="tools-section"><h3>${toolsCopy('skills','技能')}</h3><div class="tools-row-group">${skillRows}</div></section>`:''}<section class="tools-section"><h3>${mcp?toolsCopy('connectionSettings','连接配置'):toolsCopy('about','关于')}</h3>${facts(about)}</section>${mcp?`<p class="settings-footnote tools-config-note">${toolsCopy('mcpConfigHint','请在对应 Agent 中查看或修改完整配置。')}</p>`:''}${accountToolsNotice()}</div></div>`;
}
function accountToolsManageCurrent(){const page=accountToolsView().detail;if(!page)return;const detail={...page,context:settingsContext(),token:(S.settingsExtensionDialogSequence||0)+1};S.settingsExtensionDialogSequence=detail.token;S.settingsExtensionDetail=detail;accountPaintSettingsExtensionDetail(detail);}
function accountToolsMarkdownSkeleton(){
 return `<span class="sr-only" role="status" data-app-i18n="settingsTools.loadingSkill">正在读取技能正文…</span><div class="tools-markdown-skeleton" data-settings-skeleton aria-hidden="true" inert>${Array.from({length:6},()=>'<span class="skeleton-block"></span>').join('')}</div>`;
}
function accountToolsSkillDialog(detail){
 const item=S.settingsExtensions?.skills?.find(row=>accountSettingsExtensionIdentity(row)===detail.identity);if(!item)return;
 const parent=item.plugin_id&&(S.settingsExtensions.plugins||[]).find(row=>String(row.channel_id)===String(item.channel_id)&&row.id===item.plugin_id);detail.resource=parent;detail.commands=[];
 const name=item.display_name||item.name||item.id,available=RunTeamsHost.settings.toolResources&&parent?.has_resources&&!item._settingsStale&&S.settingsExtensionsState==='ready';
 const origin=({personal:['personal','个人'],system:['system','系统'],project:['project','项目'],plugin:['fromPlugins','来自插件']})[item.source];
 const source=[esc(item.channel_name||''),origin?toolsCopy(...origin):''].filter(Boolean).join(' / ');
 const empty=`<div class="tools-skill-unavailable"><p>${toolsCopy('skillBodyUnavailable','技能正文暂不可用')}</p><small>${toolsCopy('skillBodyHint','你仍可查看技能名称和简介。')}</small></div>`;
 openChildDialog({manageFocus:true,className:'settings-extension-dialog tools-skill-dialog',title:name,
  headerHtml:`<span class="settings-tool-icon tools-skill-hero-icon">${accountToolsIcon(item,'skills')}</span><div class="tools-skill-header-actions">${accountToolsReadonlyState(item,'skills')}<button type="button" class="tools-icon-button" aria-label="技能操作"${toolsAttrs('skillActions',null,'-aria-label')} aria-haspopup="menu" onclick="accountToolsSkillMenu(this,${detail.token})">${ICON('more')}</button><button type="button" class="x modal-x" aria-label="关闭技能详情"${toolsAttrs('closeSkill',null,'-aria-label')} onclick="closeChildDialog()">${ICON('x')}</button></div>`,
  attrs:`role="dialog" aria-modal="true" aria-labelledby="settingsSkillTitle" data-settings-extension-dialog="${detail.token}" onkeydown="accountSettingsExtensionKeydown(event)"`,
  body:`<div class="tools-skill-intro"><h2 id="settingsSkillTitle">${esc(name)} ${toolsCopy('skill','技能')}</h2><p>${item.description?esc(item.description):toolsCopy('noDescription','暂无简介')}</p>${source?`<small>${source}</small>`:''}</div><div id="settingsSkillMarkdown" class="tools-skill-markdown doc-reader-prose" aria-busy="${!!available}">${available?accountToolsMarkdownSkeleton():empty}</div><p id="settingsExtensionCopyStatus" class="settings-footnote" role="status"></p>`});
 if(available)accountToolsLoadSkillMarkdown(detail.token);
}
async function accountToolsLoadSkillMarkdown(token){
 const detail=accountSettingsExtensionDialogCurrent(token);if(!detail||detail.key!=='skills')return;const item=S.settingsExtensions?.skills?.find(row=>accountSettingsExtensionIdentity(row)===detail.identity),parent=detail.resource;if(!item||!parent?.has_resources)return;
 const sequence=(detail.readSequence||0)+1;detail.readSequence=sequence;const mutation=S.channelMutationVersion||0;
 const current=()=>detail.readSequence===sequence&&mutation===(S.channelMutationVersion||0)&&accountSettingsExtensionDialogCurrent(token)===detail&&S.settingsExtensions?.skills?.some(row=>accountSettingsExtensionIdentity(row)===detail.identity);
 const host=document.getElementById('settingsSkillMarkdown');if(!host)return;host.setAttribute('aria-busy','true');host.innerHTML=accountToolsMarkdownSkeleton();
 try{const payload=await installedPluginResourcePayload(item.channel_id,parent.id);if(!current())return;const prefix=String(item.plugin_id)+':',folder=String(item.id).startsWith(prefix)?String(item.id).slice(prefix.length):'',path=`/skills/${folder}/SKILL.md`;if(!folder||!Object.hasOwn(payload.files,path))throw Error('missing skill resource');const file=await payload.loadFile(path.slice(1));if(!current()||!host.isConnected)return;if(typeof file?.code!=='string')throw Error('not text');detail.markdown=file.code;const body=file.code.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/,'');const template=document.createElement('template');template.innerHTML=renderMarkdown(body);template.content.querySelectorAll('img').forEach(image=>image.remove());template.content.querySelectorAll('a').forEach(link=>{const href=link.getAttribute('href')||'';if(/^https?:\/\//i.test(href)){link.target='_blank';link.rel='noopener noreferrer';}else{link.replaceWith(...link.childNodes);}});host.replaceChildren(template.content);}
 catch(error){if(current()&&host.isConnected)host.innerHTML=`<div class="tools-skill-unavailable" role="alert"><p>${toolsCopy('skillLoadFailed','暂时无法读取技能正文。')}</p><button class="btn"${toolsAttrs('reload')} onclick="accountToolsLoadSkillMarkdown(${token})">重新读取</button></div>`;}
 finally{if(current()&&host.isConnected)host.setAttribute('aria-busy','false');}
}
function accountToolsSkillMenu(anchor,token){const detail=accountSettingsExtensionDialogCurrent(token);if(!detail)return;openMenu(anchor,[{label:'复制 Markdown',labelKey:'settingsTools.copyMarkdown',disabled:typeof detail.markdown!=='string',fn:()=>accountToolsCopyMarkdown(token)}],{variant:'settingsSelect'});const menu=document.getElementById('popmenu'),item=menu?.querySelector('[role="menuitemradio"]');item?.setAttribute('role','menuitem');item?.removeAttribute('aria-checked');menu?.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing){event.preventDefault();event.stopPropagation();closePop();}});}
async function accountToolsCopyMarkdown(token){
 const detail=accountSettingsExtensionDialogCurrent(token);
 if(typeof detail?.markdown!=='string')return;
 let key='markdownCopied',text='Markdown 已复制';
 try{await navigator.clipboard.writeText(detail.markdown);}
 catch{key='markdownCopyFailed';text='无法复制 Markdown。请手动选择正文并复制。';}
 if(accountSettingsExtensionDialogCurrent(token)!==detail)return;
 const status=document.getElementById('settingsExtensionCopyStatus');if(!status)return;
 status.textContent=text;status.setAttribute('data-app-i18n','settingsTools.'+key);
 globalThis.RunTeamsLocale?.apply(status);
}
function accountMergeSettingsExtensions(result,previous){
 const merged={...result};for(const key of ['skills','plugins','mcp_servers','available_plugins']){merged[key]=(result[key]||[]).map(item=>({...item}));for(const channel of result.channels||[]){if(!['error','partial'].includes(channel.read_states?.[key==='available_plugins'?'plugins':key]))continue;for(const old of previous?.[key]||[]){if(String(old.channel_id)!==String(channel.id))continue;const same=merged[key].some(item=>String(item.channel_id)===String(old.channel_id)&&String(item.id||item.name)===String(old.id||old.name));if(!same)merged[key].push({...old,_settingsStale:true});}}}return merged;
}
function accountFilterSettingsExtensions(value,selection){
 if(!value)return value;const ids=new Set(selection.split(',').filter(Boolean)),result={...value};
 for(const key of ['channels','skills','plugins','mcp_servers','available_plugins','issues'])result[key]=(value[key]||[]).filter(row=>ids.has(String(key==='channels'?row.id:row.channel_id)));
 return result;
}
async function accountToolsReload(button){
 const focused=document.activeElement===button,context=settingsContext();
 await accountReadSettingsExtensions(true);
 if(focused&&context===settingsContext()&&S.settingsTab==='tools'&&document.activeElement===document.body){
  const panel=document.getElementById('settingsPanel');
  (panel?.querySelector('[data-tools-list-retry]')||panel?.querySelector('#settingsToolsSearch'))?.focus({preventScroll:true});
 }
}
async function accountReadSettingsExtensions(force=false){
 const context=settingsContext(),mutation=S.channelMutationVersion||0,selection=environmentConnectedChannelIds().join(','),scope=modelChannelData().identity('extensions');if(S.settingsExtensionsRead?.scope===scope)return S.settingsExtensionsRead.promise;if(!force&&S.settingsExtensionsScope===scope&&['ready','error'].includes(S.settingsExtensionsState))return S.settingsExtensionsState==='ready';
 const read={context,mutation,selection,scope};S.settingsExtensionsRead=read;S.settingsExtensionsScope=scope;S.settingsExtensions=accountFilterSettingsExtensions(S.settingsExtensions,selection);S.settingsExtensionsState='loading';accountSettingsPaint();
 read.promise=(async()=>{try{const result=await modelChannelData().extensions(force);if(!result){if(S.settingsExtensionsRead===read){S.settingsExtensionsState='error';S.settingsExtensionsScope='';}return false;}if(context!==settingsContext()||S.settingsExtensionsRead!==read)return false;if(result.error)throw Error(result.error);if(read.mutation!==(S.channelMutationVersion||0))throw Error('渠道已改变，请重新读取');const confirmedSelection=environmentConnectedChannelIds().join(',');S.settingsExtensions=accountMergeSettingsExtensions(accountFilterSettingsExtensions(result,confirmedSelection),S.settingsExtensions);S.settingsExtensionsScope=modelChannelData().identity('extensions');S.settingsExtensionsState='ready';S.settingsExtensionsConfirmedScope=S.settingsExtensionsScope;return true;}catch(error){if(context===settingsContext()&&S.settingsExtensionsRead===read)S.settingsExtensionsState='error';return false;}finally{if(S.settingsExtensionsRead===read)S.settingsExtensionsRead=null;if(context===settingsContext())accountSettingsPaint();}})();return read.promise;
}
function accountExtensionShellArgument(value){return "'"+String(value).replaceAll("'","'\"'\"'")+"'";}
function accountSettingsExtensionCommands(item,key){
 const source=accountSettingsExtensionSource(item),provider=accountSettingsExtensionProvider(item),exe=source.runtime?.executable||({codex:'codex','claude-code':'claude'}[provider]);if(!exe||!['codex','claude-code'].includes(provider)||key==='skills'||item._settingsStale||['error','loading'].includes(S.settingsExtensionsState))return [];
 const binary=accountExtensionShellArgument(exe),id=accountExtensionShellArgument(item.id||item.name||'');if(!item.id&&!item.name)return [];
 if(key==='available_plugins'&&(source.ready!==true||source.read_states?.plugins!=='ready'))return [];
 if(key==='available_plugins')return [{label:'安装插件',labelKey:'installPlugin',command:binary+' plugin '+(provider==='codex'?'add':'install')+' -- '+id},{label:'查看管理方式',labelKey:'viewManagement',command:binary+' plugin --help'}];
 if(key==='plugins')return [{label:'查看管理方式',labelKey:'viewManagement',command:binary+' plugin --help'},...(provider==='claude-code'?[{label:item.enabled===false?'启用插件':'停用插件',labelKey:item.enabled===false?'enablePlugin':'disablePlugin',command:binary+' plugin '+(item.enabled===false?'enable':'disable')+' -- '+id}]:[]),{label:'卸载插件',labelKey:'removePlugin',command:binary+' plugin '+(provider==='codex'?'remove':'uninstall')+' -- '+id}];
 return [{label:'查看连接配置',labelKey:'viewConnection',command:binary+' mcp get -- '+id},...(accountSettingsExtensionStatus(item,key)==='需要登录'?[{label:'登录此连接',labelKey:'signInConnection',command:binary+' mcp login -- '+id}]:[]),{label:'查看管理方式',labelKey:'viewManagement',command:binary+' mcp --help'}];
}
function accountSettingsExtensionIdentity(item){return JSON.stringify([String(item.channel_id),String(item.id||item.name),String(item.plugin_id||'')]);}
function accountSettingsExtensionDetail(key,index){
 const item=S.settingsExtensions?.[key]?.[index];if(!item)return;if(key!=='skills'){const view=accountToolsView();view.listScroll=document.getElementById('settingsPanel')?.scrollTop||0;view.detail={key,identity:accountSettingsExtensionIdentity(item)};accountSettingsPaint();document.getElementById('settingsPanel').scrollTop=0;document.querySelector('.settings-tools-back')?.focus({preventScroll:true});return;}const detail={key,identity:accountSettingsExtensionIdentity(item),context:settingsContext(),token:(S.settingsExtensionDialogSequence||0)+1};S.settingsExtensionDialogSequence=detail.token;S.settingsExtensionDetail=detail;accountPaintSettingsExtensionDetail(detail);
}
function accountPaintSettingsExtensionDetail(detail){
 if(S.settingsExtensionDetail!==detail||detail.context!==settingsContext())return;
 if(detail.key==='skills'){accountToolsSkillDialog(detail);return;}
 const item=S.settingsExtensions?.[detail.key]?.find(row=>accountSettingsExtensionIdentity(row)===detail.identity),source=item&&accountSettingsExtensionSource(item),name=item?.display_name||item?.name||item?.id;
 const stale=item&&(['error','loading'].includes(S.settingsExtensionsState)||item._settingsStale);
 const status=item&&(stale?'未更新':detail.key==='available_plugins'?'待安装':accountSettingsExtensionStatus(item,detail.key));
 const commands=item?accountSettingsExtensionCommands(item,detail.key):[];detail.commands=commands;
 const parent=item?.plugin_id&&(S.settingsExtensions?.plugins||[]).find(row=>String(row.channel_id)===String(item.channel_id)&&row.id===item.plugin_id);detail.resource=detail.key==='plugins'?item:parent;
 const channel=item&&(item.channel_name||source?.name||providerDefinition(accountSettingsExtensionProvider(item))?.label);
 const version=item?.version?toolsCopy('versionValue','版本 '+item.version,{version:item.version}):'';
 const facts=item?[esc(channel||''),toolsStatusCopy(status),version].filter(Boolean):[];
 const instruction=detail.key==='mcp_servers'&&status==='需要登录'?toolsCopy('signInAgent','在对应 Agent 中登录，然后重新读取。'):toolsCopy('runCommand','在对应 Agent 的终端中运行命令，然后重新读取。');
 const commandRows=commands.map((command,index)=>`<p>${toolsCopy(command.labelKey,command.label)} <button class="btn"${toolsAttrs('copyCommand')} onclick="accountCopySettingsExtensionCommand(${detail.token},${index})">复制命令</button></p><code class="install-command">${esc(command.command)}</code>`).join('');
 const content=!item?`<p>${toolsCopy('toolGone','此工具已不在当前清单中。')}</p>`:`<p>${item.description?esc(item.description):toolsCopy('noDescription','暂无简介')}</p>${facts.map(value=>'<p class="settings-footnote">'+value+'</p>').join('')}${stale?`<p class="settings-inline-error" role="alert">${toolsCopy('managementStale','清单未更新。请重新读取后再管理。')}</p>`:''}${commands.length?'<p>'+instruction+'</p>':''}${commandRows}`;
 const title=name||'工具详情',loading=S.settingsExtensionsState==='loading';
 const host=openChildDialog({manageFocus:true,className:'settings-extension-dialog',title,titleKey:name?undefined:'settingsTools.toolDetails',closeLabelKey:'settingsTools.close',
  attrs:`role="dialog" aria-modal="true" aria-label="${esc(title)}"${name?'':toolsAttrs('toolDetails',null,'-aria-label')} onkeydown="accountSettingsExtensionKeydown(event)" data-settings-extension-dialog="${detail.token}"`,
  body:content+'<p id="settingsExtensionCopyStatus" class="settings-footnote" role="status"></p>',
  footer:`${RunTeamsHost.settings.toolResources&&detail.resource?.has_resources&&!stale?`<button class="btn"${toolsAttrs('openResources')} onclick="accountSettingsExtensionResources(${detail.token})">打开资源</button>`:''}<button class="btn"${toolsAttrs(loading?'loading':'reload')} onclick="accountRecheckSettingsExtension(${detail.token})" ${loading?'disabled aria-busy="true"':''}>${loading?'正在读取…':'重新读取'}</button><button class="btn"${toolsAttrs('close')} onclick="closeChildDialog()">关闭</button>`});
 if(host){const anchor=document.querySelector('.tools-detail-actions button')||document.querySelector('.settings-sidebar [data-settings-tab="tools"]');if(anchor)host._returnFocus=anchor;}
}
function accountSettingsExtensionKeydown(event){if(event.key==='Escape'&&!event.isComposing){event.preventDefault();event.stopPropagation();if(document.getElementById('popmenu'))closePop();else closeChildDialog();}}
function accountSettingsExtensionDocumentKeydown(event){if(document.querySelector('[data-settings-extension-dialog]'))accountSettingsExtensionKeydown(event);}
function accountSettingsExtensionDialogCurrent(token){const detail=S.settingsExtensionDetail;return detail?.token===token&&detail.context===settingsContext()&&!!document.querySelector('[data-settings-extension-dialog="'+token+'"]')?detail:null;}
async function accountCopySettingsExtensionCommand(token,index){
 const detail=accountSettingsExtensionDialogCurrent(token),command=detail?.commands?.[index]?.command;
 if(!command)return;
 let key='commandCopied',message='命令已复制';
 try{await navigator.clipboard.writeText(command);}
 catch{key='commandCopyFailed';message='无法复制命令。请手动选择并复制。';}
 if(!accountSettingsExtensionDialogCurrent(token))return;
 const status=document.getElementById('settingsExtensionCopyStatus');if(!status)return;
 status.textContent=message;
 status.setAttribute?.('data-app-i18n','settingsTools.'+key);
 globalThis.RunTeamsLocale?.apply(status);
}
async function accountRecheckSettingsExtension(token){const detail=accountSettingsExtensionDialogCurrent(token);if(!detail)return;const pending=accountReadSettingsExtensions(true);accountPaintSettingsExtensionDetail(detail);await pending;if(accountSettingsExtensionDialogCurrent(token))accountPaintSettingsExtensionDetail(detail);}
function accountSettingsExtensionResources(token){const detail=accountSettingsExtensionDialogCurrent(token),item=detail?.resource;if(!RunTeamsHost.settings.toolResources||!item?.has_resources)return;S.environment=S.settingsExtensions;openInstalledPluginResources(item.channel_id,item.id);document.querySelector('.core-package-resources-modal')?.setAttribute('data-settings-tools-resource','');}

function accountSettingsLink(label,path){return `<a class="settings-row settings-link" href="https://runteams.ai${path}" target="_blank" rel="noopener noreferrer"><b>${label}</b>${ICON('chev')}</a>`;}


function accountSettingsReadAppInfo(){
 if(S.settingsAppInfoRead)return S.settingsAppInfoRead;
 S.settingsAppInfoRead=(async()=>{
  try{
   const value=await api('/api/app-info'),version=displayAppVersion(value?.version);
   if(value&&!value.error&&version)S.appInfo={...value,version};
  }catch{}
  finally{
   S.settingsAppInfoRead=null;S.settingsAppInfoReadOnce=true;
   if(S.settingsTab==='about')accountSettingsPaint();
  }
 })();
 if(S.settingsTab==='about'&&S.settingsAppInfoReadOnce&&!S.appInfo?.version)accountSettingsPaint();
 return S.settingsAppInfoRead;
}
async function accountSettingsRetryAppInfo(button){
 const focused=document.activeElement===button;
 await accountSettingsReadAppInfo();
 if(focused&&S.settingsTab==='about'&&document.activeElement===document.body){
  (document.getElementById('settingsAboutVersionRetry')||document.getElementById('settingsAboutVersionStatus'))?.focus({preventScroll:true});
 }
}
function accountSettingsLoadTab(){const tab=S.settingsTab;if(tab==='about')accountSettingsReadAppInfo();if(tab==='channels')refreshSettingsChannels();if(tab==='tools')accountReadSettingsExtensions();RunTeamsHost.settings.load(tab);}
function accountNativeSettingsBridge(){return window.webkit?.messageHandlers?.runteamsSettings;}
function accountNativeNotificationStatus(value){if(!value||!['default','granted','denied'].includes(value.notification_permission)||typeof value.notification_alerts!=='boolean'||typeof value.notification_sound!=='boolean')return;S.nativeSettings={...S.nativeSettings,...value};if(['granted','denied'].includes(value.notification_permission)&&S.notificationPermissionRetry!=='settings'){S.notificationPermissionError='';S.notificationPermissionRetry='';}if(S.settingsTab==='notifications')accountSettingsPaint();}
async function accountReadNativeSettings(){const bridge=accountNativeSettingsBridge();if(!bridge||S.nativeSettingsLoading||S.nativeSettingsSaving)return;S.nativeSettingsLoading=true;accountSettingsPaint();try{const value=await bridge.postMessage({action:'get',workspace:RunTeamsHost.session.workspace(S)});if(!value||typeof value.prevent_sleep!=='boolean'||typeof value.launch_at_login!=='boolean'||!['background','quit'].includes(value.close_action))throw Error('本机设置未确认');S.nativeSettings=value;S.nativeSettingsError='';S.nativeSettingsRetry=null;if(['default','granted','denied'].includes(value.notification_permission)&&S.notificationPermissionRetry!=='settings'){S.notificationPermissionError='';S.notificationPermissionRetry='';}}catch(error){S.nativeSettingsError='本机设置暂时无法读取';}finally{S.nativeSettingsLoading=false;accountSettingsStartRuntimeMonitor();accountSettingsPaint();}}
async function accountSaveNativeSetting(key,value){const bridge=accountNativeSettingsBridge();if(!bridge||S.nativeSettingsSaving||S.nativeSettingsLoading||S.nativeSettingsError)return;S.nativeSettingsSaving=true;S.nativeSettingsError='';S.nativeSettingsRetry={key,value};accountSettingsPaint();try{const result=await bridge.postMessage({action:'set',key,value});if(!result||typeof result.prevent_sleep!=='boolean'||typeof result.launch_at_login!=='boolean'||!['background','quit'].includes(result.close_action)||result[key]!==value)throw Error('设置未确认');S.nativeSettings=result;S.nativeSettingsRetry=null;}catch(error){S.nativeSettingsError='本机设置未能保存，请重试。';}finally{S.nativeSettingsSaving=false;accountSettingsStartRuntimeMonitor();accountSettingsPaint();}}
function accountSettingsStartRuntimeMonitor(){if(accountNativeSettingsBridge()){RunTeamsHost.lifecycle.notificationsReady?.();return;}if(S.settingsRuntimeTimer)return;S.settingsRuntimeTimer=setInterval(RunTeamsHost.lifecycle.pollNotifications,5000);RunTeamsHost.lifecycle.pollNotifications();}



function accountSettingsChannelInstall(id,mode='install'){
 const channel=S.channels.find(row=>Number(row.id)===Number(id));if(!channel)return;
 const update=mode==='update',name=channel.provider_label||channel.name,guide=channel.provider==='codex'?'https://developers.openai.com/codex/cli/':'https://code.claude.com/docs/en/setup';
 const instructions=update?modelChannelText('updateHelp','按官方说明，使用原来的安装方式更新 CLI。完成后返回这里检查版本和连接。'):modelChannelText('installHelp','按官方说明安装并登录，再返回这里检查连接。');
 const link=update?modelChannelText('updateInstructions','查看更新说明'):modelChannelText('installInstructions','查看安装说明');
 const title=update?`更新 ${name} CLI`:`安装并登录 ${name}`,titleKey=update?'updateTitle':'installTitle';
 openChildDialog({manageFocus:true,className:'channel-instructions-dialog',title,titleKey:'modelChannel.'+titleKey,titleVars:{name},closeLabelKey:'modelChannel.close',attrs:`role="dialog" aria-modal="true" aria-label="${esc(title)}"${modelChannelAttrs(titleKey,{name},'-aria-label')}`,body:`<p>${instructions}</p><a class="btn" href="${guide}" target="_blank" rel="noopener noreferrer">${link}</a>`,footer:`<button class="btn" data-app-i18n="modelChannel.close" onclick="closeChildDialog()">关闭</button><button class="btn" data-app-i18n="modelChannel.checkAgain" onclick="closeChildDialog();checkChannelLogin(${Number(id)})">重新检测</button>`});
}

function accountRefreshModelDefaults(){const region=document.querySelector('#settingsModelDefaults .settings-row-group');if(region){const next=region.cloneNode(false);next.innerHTML=accountSettingsNotice()+accountModelDefaults();RunTeamsLocale.apply(next);accountChannelReconcile(region,next);}}

function accountChannelDiagnostic(label,detail,id,kind='status'){
 if(!detail)return `<span>${esc(label)}</span>`;
 return `<details class="channel-diagnostic" data-channel-detail="${esc(String(id)+'-'+kind)}"><summary>${esc(label)}${ICON('chev')}</summary><p>${esc(detail)}</p></details>`;
}




if(typeof window!=='undefined')window.addEventListener?.('focus',()=>{if(S.settingsTab==='notifications'&&document.getElementById('settingsWorkspace'))accountReadNativeSettings();});

/* module-function:accountChannelConnected */
function accountChannelConnected(channel){return modelChannelAvailable(channel);}

/* module-function:accountChannelIdentity */
function accountChannelIdentity(channel){const parts=String(channel?.probe?.account||'').split(/\s*[·\u2002]\s*/).map(value=>value.trim()).filter(Boolean);return {email:parts[0]||'',plan:parts.slice(1).join(' ')};}

/* module-function:accountChannelMenu */
function accountChannelMenu(event,id){
 event.preventDefault();event.stopPropagation();const channel=S.channels.find(row=>Number(row.id)===Number(id)),anchor=event.currentTarget;
 if(!channel||anchor.disabled||channel.probe?.status==='missing')return;
 const connected=accountChannelConnected(channel),identity=accountChannelIdentity(channel),context=settingsContext(),current=()=>context===settingsContext()&&S.channels.includes(channel);
 const items=[];
 if(connected){if(identity.email||identity.plan){items.push({head:true,account:true,label:identity.email,plan:identity.plan},{divider:true});}items.push({label:'断开连接',labelKey:'modelChannel.disconnect',icon:'unlink',danger:true,fn:()=>{if(current()&&channel.enabled)removeChannel(id);}});}
 items.push({label:'更新 CLI',labelKey:'modelChannel.update',icon:'refresh',fn:()=>{if(current())accountSettingsChannelInstall(id,'update');}});
 openMenu(anchor,items,{variant:'channelAccount',align:'right'});
 const menu=document.getElementById('popmenu');if(menu?.classList.contains('channel-account-menu')){menu.dataset.channelId=String(channel.id);menu.dataset.identity=JSON.stringify([connected,identity]);const name=agentChannelLabel(channel);menu.setAttribute('aria-label',`“${name}”的更多操作`);menu.dataset.appI18nAriaLabel='modelChannel.more';menu.dataset.appI18nVars=JSON.stringify({name});(event.type==='keydown'?menu.querySelector('a[data-i]'):menu)?.focus({preventScroll:true});}
}

/* module-function:accountChannelMenuKey */
function accountChannelMenuKey(event,id){if(event.isComposing||event.currentTarget.disabled||!['ArrowDown','ArrowUp','Enter',' '].includes(event.key))return;if(document.getElementById('popmenu')&&_popAnchor===event.currentTarget)return;accountChannelMenu(event,id);}

/* module-function:accountConnectChannel */
async function accountConnectChannel(id){
 const channel=S.channels.find(row=>Number(row.id)===Number(id));if(!channel||channel.connecting||channel.removing||channel.loginProbeBusy)return;
 if(channel.removeUnknown){await removeChannel(id);return;}
 if(channel.statusReadError){await checkChannelLogin(id);return;}
 if(channel.loginPending){accountChannelLoginHelp(id);return;}
 await connectChannel(id);
}

/* module-function:accountChannelLoginHelp */
function accountChannelLoginHelp(id){
 const channel=S.channels.find(row=>Number(row.id)===Number(id));if(!channel?.loginPending)return;
 const name=agentChannelLabel(channel);
 openChildDialog({manageFocus:true,className:'channel-login-dialog',title:'登录 '+name,titleKey:'modelChannel.signInTitle',titleVars:{name},closeLabelKey:'modelChannel.close',attrs:`role="dialog" aria-modal="true" aria-label="${esc('登录 '+name)}"${modelChannelAttrs('signInTitle',{name},'-aria-label')} data-channel-login="${Number(id)}"`,body:`<p data-app-i18n="modelChannel.signInHelp">在终端登录。返回 RunTeams 后会自动检测。</p><div class="channel-login-command"><code>${esc(channel.login_command||'')}</code><button type="button" class="btn" data-app-i18n="modelChannel.copyCommand" onclick="copyChannelLoginCommand(${Number(id)})">复制命令</button></div>`,footer:`<button class="btn" data-app-i18n="modelChannel.close" onclick="closeChildDialog()">关闭</button><button class="btn" data-app-i18n="modelChannel.checkAgain" onclick="closeChildDialog();checkChannelLogin(${Number(id)})">重新检测</button>`});
}

/* module-function:accountChannelReconcile */
function accountChannelReconcile(current,next){
 if(current.nodeType!==next.nodeType||current.nodeName!==next.nodeName){current.replaceWith(next.cloneNode(true));return;}
 if(current.nodeType===Node.TEXT_NODE){if(current.data!==next.data)current.data=next.data;return;}
 if(current.nodeType!==Node.ELEMENT_NODE)return;
 if(current.matches('#settings_default_model,#settings_default_effort'))accountSettingsKeepPendingAppearance(current,next);
 const open=current===_popAnchor&&!!document.querySelector('.channel-account-menu,.settings-select-menu');
 for(const a of [...current.attributes])if(!next.hasAttribute(a.name)&&!(open&&['aria-expanded','data-menu-open'].includes(a.name)))current.removeAttribute(a.name);
 for(const a of next.attributes)if(!(open&&['aria-expanded','data-menu-open'].includes(a.name))&&current.getAttribute(a.name)!==a.value)current.setAttribute(a.name,a.value);
 const key=node=>node.nodeType===Node.ELEMENT_NODE?(node.id||node.getAttribute('data-channel-id')):'';
 for(let i=0;i<next.childNodes.length;i++){const wanted=next.childNodes[i];let node=current.childNodes[i],id=key(wanted);
  if(id&&key(node||{})!==id){const existing=[...current.childNodes].find(n=>key(n)===id);if(existing){current.insertBefore(existing,node||null);node=existing;}else{current.insertBefore(wanted.cloneNode(true),node||null);continue;}}
  if(node)accountChannelReconcile(node,wanted);else current.appendChild(wanted.cloneNode(true));
 }
 while(current.childNodes.length>next.childNodes.length)current.lastChild.remove();
}

function accountAboutVersionGroup(update=''){
 const version=S.appInfo?.version,unavailable=!version&&S.settingsAppInfoReadOnce&&!S.settingsAppInfoRead;
 const detail=version?aboutCopy('version',`版本 ${version}`,{version}):
  unavailable?aboutCopy('versionUnavailable','暂时无法读取版本'):aboutCopy('versionReading','正在读取版本…');
 const status=`<span id="settingsAboutVersionStatus" role="status" tabindex="-1">${detail}</span>`;
 const retry=unavailable?`<div class="settings-row"><button type="button" class="btn" id="settingsAboutVersionRetry" onclick="accountSettingsRetryAppInfo(this)">${aboutCopy('retryVersion','重新读取版本')}</button></div>`:'';
 return accountSettingsGroup(aboutCopy('versionGroup','应用版本'),accountSettingsRow('RunTeams.ai',update,status)+retry);
}
function accountAboutSettings(){
 return `${settingsPageHead(aboutCopy('title','关于'))}${accountAboutVersionGroup()}${accountSettingsGroup(aboutCopy('legal','法律与隐私'),accountSettingsLink(aboutCopy('privacy','隐私政策'),'/privacy')+accountSettingsLink(aboutCopy('terms','服务条款'),'/terms'))}`;
}
function aboutCopy(key,label,vars){
 return `<span data-app-i18n="about.${key}"${vars?` data-app-i18n-vars="${esc(JSON.stringify(vars))}"`:''}>${esc(label)}</span>`;
}

function accountWorkspaceReadOnly(){return RunTeamsHost.session.readOnly(S);}
