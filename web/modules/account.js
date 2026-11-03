/* Shared settings and model-channel UI. Official account/business behavior is composed by the official entry.
 * Classic script: functions retain their existing names and access the host's S/helpers at call time.
 * Do not run initialization here; do not redeclare S, api, ICON, esc, render or shared controls. */

/* module-function:refreshChannelUsage */
async function refreshChannelUsage(force=false){
  const context=workspaceAccountCacheToken(),mutation=S.channelMutationVersion||0,
   previousAvailability=JSON.stringify(S.channels.map(c=>[String(c.id),modelChannelAvailable(c)]));
  S.channelUsageLoading=true;globalThis.RunTeamsOfficialUI?.renderUsage();if(document.getElementById("channel_list")||document.getElementById("model_channel_guide_list"))renderChannels(false);
  try{const result=await modelChannelData().usage(force);if(!result||context!==workspaceAccountCacheToken()||mutation!==(S.channelMutationVersion||0))return S.channelUsage;
   if(result.error)throw Error(result.error);if(S.channelUsage===result)return result;
   S.channelUsage=result;S.channelUsageUpdatedAt=Date.now();applyChannelUsageAvailability(previousAvailability);return result;
  }catch(error){if(context===workspaceAccountCacheToken()&&mutation===(S.channelMutationVersion||0)){S.channelUsage={channels:[],error:error.message||''};S.channelUsageUpdatedAt=Date.now();}return S.channelUsage;}
  finally{if(context===workspaceAccountCacheToken()){S.channelUsageLoading=false;globalThis.RunTeamsOfficialUI?.renderUsage();if(document.getElementById("channel_list")||document.getElementById("model_channel_guide_list"))renderChannels(false);}}
}

/* module-function:refreshAccountPanel */
function refreshAccountPanel(){if(document.getElementById('settingsWorkspace')){accountSettingsPaint();accountSettingsLoadTab();accountSettingsReadPreferences();}}

/* Google Identity official logo, preserved as an offline brand asset.
 * Source: https://developers.google.com/static/identity/images/g-logo.png
 * Intrinsic brand colors are image pixels, not UI color overrides. */


/* module-function:settingsNavButton */

function settingsNavButton(tab,icon,label){return `<button type="button" class="${S.settingsTab===tab?'on':''}" data-settings-tab="${tab}" aria-current="${S.settingsTab===tab?'page':'false'}" onclick="switchSettingsTab('${tab}')">${ICON(icon)}<span>${label}</span></button>`;}

/* module-function:settingsPageHead */
function settingsPageHead(title,detail=''){return `<header class="settings-page-head"><h2 tabindex="-1">${title}</h2>${detail?`<p>${detail}</p>`:''}</header>`;}

/* module-function:settingsSectionHead */
function settingsSectionHead(title,detail='',action=''){return `<div class="settings-section-title-row"><span><h3>${title}</h3>${detail?`<small>${detail}</small>`:''}</span>${action}</div>`;}

/* module-function:settingsLoadingLine */
function settingsLoadingLine(className=''){return `<span class="skeleton-block ${className}"></span>`;}

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
  if(globalThis.RunTeamsLocale){const result=RunTeamsLocale.setPreference(value);if(!result.persisted)toast(RunTeamsLocale.t('language.saveFailed',{},'当前语言已切换，但未能保存在本机。'),'err');return;}
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
 return `${settingsPageHead(text('general.title','通用'))}${accountSettingsNotice()}${accountNativeSettingsNotice()}${accountGeneralDisplayNotice()}${accountSettingsGroup(label('language.title','语言'),accountSettingsRow(label('language.interface','界面语言'),accountLanguageControl(),label('language.fallback','未提供英文的界面将显示中文。'),'accountLanguageHint'))}${accountSettingsGroup(label('general.interaction','输入与交互'),accountSettingsRow(label('general.send_mode','发送方式'),accountSettingsSelect('send_mode',[{value:'enter',label:text('general.enter','Enter 发送')},{value:'meta-enter',label:text('general.metaEnter','⌘Enter 发送')}],prefs.send_mode,!ready))+accountSettingsRow(label('general.allow_supplement','运行中允许补充要求'),accountSettingsSwitch('allow_supplement',prefs.allow_supplement,!ready),label('general.supplementHint','关闭后，新消息加入队列，当前回复结束后依次发送。')))}${accountSettingsGroup(label('general.runtime','启动与运行'),accountSettingsRow(label('general.launch_at_login','登录电脑时启动'),accountSettingsSwitch('launch_at_login',native?.launch_at_login,nativeDisabled),accountNativeSettingsBridge()?'':label('general.desktopOnly','在桌面应用中设置。'))+accountSettingsRow(label('general.restore_windows','启动时恢复上次窗口'),accountSettingsSwitch('restore_windows',display.restore_windows,!!S.appearanceDisplayReadFailed||!!S.appearanceSaveFailures?.restore_windows?.readOnly),label('general.deviceOnly','仅在这台电脑保存'))+accountSettingsRow(label('general.prevent_sleep','任务运行时防止自动休眠'),accountSettingsSwitch('prevent_sleep',native?.prevent_sleep,nativeDisabled),accountNativeSettingsBridge()?'':label('general.desktopOnly','在桌面应用中设置。'))+accountSettingsRow(label('general.close_action','关闭窗口后'),accountSettingsSelect('close_action',[{value:'background',label:text('general.background','继续后台运行')},{value:'quit',label:text('general.quit','退出应用')}],native?.close_action||'quit',nativeDisabled),label('general.quitHint','退出应用或电脑休眠后，本机停止执行。')))}${globalThis.RunTeamsBackups?.markup()||''}${globalThis.RunTeamsLibraryContinuation?.markup()||''}`;
}

/* module-function:accountGeneralDisplayNotice */
function accountGeneralDisplayNotice(){
 const failed=S.appearanceDisplayReadFailed,failure=S.appearanceSaveFailures?.restore_windows;if(!failed&&!failure)return '';
 const message=failure?.readOnly?failure.message:failed?'窗口恢复设置暂时无法读取，请重新读取后再修改。':failure.message;
 return `<div class="settings-inline-error" role="alert"><span>${esc(message)}</span><button class="btn" onclick="accountGeneralRetryDisplay()">${failed||failure?.readOnly?'重新读取':'重试'}</button></div>`;
}

/* module-function:accountGeneralRetryDisplay */
function accountGeneralRetryDisplay(){
 const failure=S.appearanceSaveFailures?.restore_windows;
 if(S.appearanceDisplayReadFailed||failure?.readOnly){accountDeviceDisplayPrefs();if(!S.appearanceDisplayReadFailed&&failure?.readOnly)delete S.appearanceSaveFailures.restore_windows;accountSettingsPaint();return;}
 if(failure)accountSaveDisplaySetting('restore_windows',failure.value);
}

/* module-function:normalizeSettingsTab */
function normalizeSettingsTab(tab){return ['general','appearance','notifications','devices','channels','tools','organization','subscription','wallet','help','about'].includes(tab)&&(globalThis.RunTeamsApplication?.settingsAllowed(tab)!==false)&&(!['devices','organization','subscription','wallet','help'].includes(tab)||!!globalThis.RunTeamsOfficialUI?.settingsPanels?.[tab])?tab:'general';}

/* module-function:settingsPanel */
function settingsChannelContents(loading=false,idPrefix="settingsChannel"){
 const cards=channelCardsMarkup(loading,idPrefix);if(cards)return cards+(RunTeamsModelChannels.definitionError(S)?'<div class="settings-inline-error" role="alert"><span>渠道状态暂时无法读取</span><button class="btn" onclick="accountRefreshChannels()">重新读取</button></div>':'');
 if(S.environmentLoading||S.channelSettingsRefreshing)return '<div class="settings-preferences-loading" role="status">正在读取渠道状态…</div>';
 if(RunTeamsModelChannels.definitionError(S))return '<div class="settings-inline-error" role="alert"><span>渠道状态暂时无法读取</span><button class="btn" onclick="accountRefreshChannels()">重新读取</button></div>';
 return '<div class="empty">还没有可用的模型渠道</div>';
}
function channelListMarkup(id='channel_list',{appearance='grouped'}={}){return `<div class="settings-channels channel-list${appearance==='plain'?' channel-list-plain':''}" id="${esc(id)}">${settingsChannelContents(false,id==='channel_list'?'settingsChannel':'guideChannel')}</div>`;}
function modelChannelsSettingsPanel(){return `${settingsPageHead('模型渠道','')}${accountSettingsGroup('渠道账户',channelListMarkup(),'','settingsChannelConnections')}${accountSettingsGroup('新对话默认值',(S.localLibrary||S.account.signed_in?accountSettingsNotice():globalThis.RunTeamsOfficialUI?.signedOutSettingsNotice()||'')+accountModelDefaults(),'','settingsModelDefaults')}`;}
function settingsPanel(){const panels={general:generalSettingsPanel,appearance:accountAppearanceSettings,notifications:accountNotificationSettings,channels:modelChannelsSettingsPanel,tools:accountToolsSettings,about:accountAboutSettings,...globalThis.RunTeamsOfficialUI?.settingsPanels};return panels[normalizeSettingsTab(S.settingsTab)]();}


/* module-function:openSettingsPage */
function openSettingsPage(tab,options={}){
 if(globalThis.RunTeamsOfficialUI?.guardSettings())return;
 globalThis.RunTeamsOfficialUI?.closeMenu();closePop();
 const existing=document.getElementById('settingsWorkspace');
 if(!existing){S.settingsReturnFocus=options.returnFocus||document.activeElement;S.settingsScroll={};if(document.getElementById('modalHost'))closeModal();}
 const nextTab=normalizeSettingsTab(tab||'general');
 if(existing){switchSettingsTab(nextTab,{route:options.route});return;}
 S.settingsTab=nextTab;
 const root=document.createElement('section');root.id='settingsWorkspace';root.className='account-settings-page';root.setAttribute('aria-label','设置');const returnUrl=new URL(location.href);returnUrl.searchParams.delete('settings');returnUrl.searchParams.delete('subscription_list');root._returnRoute=returnUrl.pathname+returnUrl.search+returnUrl.hash;root._hasWorkspace=!!document.getElementById('rgMid')&&!S.booting;
 root.innerHTML=`${RunTeamsShell.settingsToolbar(ICON)}<aside class="settings-sidebar"><div class="settings-sidebar-title">设置</div><nav aria-label="设置分类">${accountSettingsNavigation()}</nav></aside><section class="settings-main"><main class="account-panel" id="settingsPanel">${settingsPanel()}</main></section>`;
 document.body.appendChild(root);document.getElementById('app')?.setAttribute('inert','');
 if(options.route!==false)accountSettingsSetRoute(S.settingsTab,false);
 RunTeamsShell.syncHistoryControls();accountSettingsLoadTab();accountSettingsReadPreferences();accountReadNativeSettings();
 root.querySelector('.settings-page-head h2')?.focus({preventScroll:true});
}

/* module-function:switchSettingsTab */
function switchSettingsTab(tab,options={}){
 globalThis.RunTeamsOfficialUI?.captureFinance();const panel=document.getElementById('settingsPanel');S.settingsScroll=S.settingsScroll||{};
 if(panel)S.settingsScroll[S.settingsTab]=panel.scrollTop;
 S.settingsTab=normalizeSettingsTab(tab);closePop();if(document.querySelector('[data-settings-extension-dialog],[data-settings-tools-resource]'))closeChildDialog();
 document.querySelectorAll('[data-settings-tab]').forEach(button=>{const current=button.dataset.settingsTab===S.settingsTab;button.classList.toggle('on',current);button.setAttribute('aria-current',current?'page':'false');});
 if(panel){panel.innerHTML=settingsPanel();panel.scrollTop=S.settingsScroll[S.settingsTab]||0;globalThis.RunTeamsOfficialUI?.restoreFinance();}
 if(options.route!==false)accountSettingsSetRoute(S.settingsTab,true);
 accountSettingsLoadTab();
}

/* module-function:setAccountTheme */
function setAccountTheme(value){if(!['light','dark','system'].includes(value))return;S.account.theme=value;applyAccountTheme(value);saveAccountPrefs();if(typeof accountAppearanceSaveNotice==='function')accountAppearanceSaveNotice();document.querySelectorAll('[data-theme-value]').forEach(button=>{const selected=button.dataset.themeValue===value;button.classList.toggle('on',selected);button.setAttribute('aria-pressed',selected?'true':'false');});}
// Account-local helpers; all durable application state stays on the host S.


if(typeof window!=='undefined')window.addEventListener?.('keydown',accountSettingsExtensionDocumentKeydown,true);


// Organization management uses the existing dialog, field, button and menu controls.
function accountTeamContext(){return `${S.accountReadEpoch||0}:${S.localLibrary?.library_id||S.account?.user_id||''}`;}


/* module-function:accountSettingsWorkspace */
function accountSettingsNavigation(){
 const common=[['应用',[['general','settings','通用'],['appearance','moon','外观'],['notifications','bell','通知']]],['模型与工具',[['channels','plug','模型渠道'],['tools','package','技能与工具']]],['支持',[['about','info','关于']]]];
 const groups=globalThis.RunTeamsOfficialUI?globalThis.RunTeamsOfficialUI.settingsNavigation(common):common;
 return groups.map(([title,items])=>[title,items.filter(item=>globalThis.RunTeamsApplication?.settingsAllowed(item[0])!==false)]).filter(([,items])=>items.length).map(([title,items])=>`<div class="settings-nav-group"><div class="settings-nav-label">${title}</div>${items.map(item=>settingsNavButton(...item)).join('')}</div>`).join('');
}
function accountSettingsSetRoute(tab,replace){const url=new URL(location.href);url.searchParams.set('settings',tab);if(tab==='subscription'&&S.settingsFinanceTab==='records')url.searchParams.set('subscription_list','records');else url.searchParams.delete('subscription_list');const target=url.pathname+url.search+url.hash;if(target!==location.pathname+location.search+location.hash){history[replace?'replaceState':'pushState']({...history.state},'',target);if(!replace)RunTeamsShell.recordNavigation(false);}RunTeamsShell.syncHistoryControls();}
function accountSettingsRestoreRoute(){S.settingsFinanceTab=globalThis.RunTeamsOfficialUI?.financeTab(new URLSearchParams(location.search).get('subscription_list'));const tab=new URLSearchParams(location.search).get('settings');if(tab){const normalized=normalizeSettingsTab(tab);if(normalized!==tab)accountSettingsSetRoute(normalized,true);openSettingsPage(normalized,{route:false});return true;}const root=document.getElementById('settingsWorkspace'),restore=!!root?._hasWorkspace&&root._returnRoute===location.pathname+location.search+location.hash;accountSettingsUnmount();return restore;}
function accountSettingsUnmount(){if(document.querySelector('[data-settings-extension-dialog],[data-settings-tools-resource]'))closeChildDialog();const root=document.getElementById('settingsWorkspace');if(!root)return;closePop();S.settingsScroll=S.settingsScroll||{};S.settingsScroll[S.settingsTab]=document.getElementById('settingsPanel')?.scrollTop||0;root.remove();document.getElementById('app')?.removeAttribute('inert');S.settingsReturnFocus?.focus?.();S.settingsReturnFocus=null;clearAgentSetupContinuation();}
function accountSettingsClose(){accountSettingsUnmount();const url=new URL(location.href);url.searchParams.delete('settings');url.searchParams.delete('subscription_list');history.replaceState(history.state,'',url.pathname+url.search+url.hash);RunTeamsShell.syncHistoryControls();}
function accountSettingsPaint(){
 const panel=document.getElementById('settingsPanel');if(!panel||!document.getElementById('settingsWorkspace'))return;
 globalThis.RunTeamsOfficialUI?.captureFinance();const scroll=panel.scrollTop,active=document.activeElement,id=panel.contains(active)?active.id:'',action=panel.contains(active)?active.getAttribute('onclick'):null;
 const focus=id||((!active||active===document.body)?panel._settingsFocusId:'');
 const pending=S.settingsPreferencePending||S.nativeSettingsSaving||S.nativeSettingsLoading;
 panel._settingsFocusId=pending?(id||panel._settingsFocusId):'';
 const html=settingsPanel();if(!accountSettingsPatchControls(panel,html))panel.innerHTML=html;
 panel.scrollTop=scroll;globalThis.RunTeamsOfficialUI?.restoreFinance();
 if(focus)document.getElementById(focus)?.focus({preventScroll:true});
 else if(action)[...panel.querySelectorAll('button')].find(button=>button.getAttribute('onclick')===action)?.focus({preventScroll:true});
 globalThis.RunTeamsOfficialUI?.paintSettings(S.settingsTab);
}
/* module-function:accountSettingsPatchControls */
function accountSettingsPatchControls(panel,html){
 if(S.settingsTab==='tools')return accountToolsPatch(panel,html);
 if(S.settingsTab==='channels'){const next=panel.cloneNode(false);next.innerHTML=html;accountChannelReconcile(panel,next);return true;}
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
 const personal=['send_mode','allow_supplement','notification_timing','confirmation','information','failure','completion','sound'].includes(key);
 const pending=native?!!S.nativeSettings&&!S.nativeSettingsError&&(S.nativeSettingsSaving||S.nativeSettingsLoading):personal&&S.account?.signed_in&&S.settingsPreferencesState==='ready'&&S.settingsPreferencePending&&!S.settingsPreferenceError&&!S.settingsPreferenceRetry?.readOnly;
 if(!pending||!value.hasAttribute('disabled')||node.hasAttribute('disabled'))return;
 // Keep the existing appearance and keyboard focus. The original save guards
 // and dropdown configuration still reject input until the acknowledgement.
 value.removeAttribute('disabled');value.setAttribute('aria-disabled','true');value.setAttribute('data-settings-pending','true');
}

/* module-function:accountSettingsGroup */
function accountSettingsGroup(title,rows,action='',id=''){return `<section class="settings-section"${id?` id="${id}"`:''}>${settingsSectionHead(title,'',action)}<div class="settings-row-group">${rows}</div></section>`;}
function accountSettingsControlSkeleton(kind='select',label='设置'){
 return `<span class="skeleton-block settings-control-skeleton settings-control-skeleton-${kind}" data-settings-skeleton role="status" aria-busy="true" aria-label="正在读取${esc(label)}" inert></span>`;
}
function accountSettingsFieldSkeleton(key,kind){
 if(S.settingsTab==='subscription')return '';
 const native=['launch_at_login','prevent_sleep','close_action'].includes(key),personal=['send_mode','allow_supplement','notification_timing','confirmation','information','failure','completion','sound','default_model','default_effort'].includes(key);
 const pending=native?typeof accountNativeSettingsBridge==='function'&&!!accountNativeSettingsBridge()&&!S.nativeSettings&&(S.nativeSettingsLoading||!S.nativeSettingsError):personal&&S.account?.signed_in&&!S.settingsPreferences&&!['ready','error'].includes(S.settingsPreferencesState);
 const label=({send_mode:'发送方式',allow_supplement:'补充要求设置',launch_at_login:'启动设置',prevent_sleep:'休眠设置',close_action:'关闭窗口设置',notification_timing:'提醒时机',confirmation:'确认提醒',information:'信息提醒',failure:'失败提醒',completion:'完成提醒',sound:'提示音',default_model:'默认模型',default_effort:'思考深度'})[key]||'设置';
 return pending?accountSettingsControlSkeleton(kind,label):'';
}
function accountSettingsRow(label,control='',detail='',detailId=''){return `<div class="settings-row"><div class="settings-row-copy"><b>${label}</b>${detail?`<small${detailId?` id="${detailId}"`:''}>${detail}</small>`:''}</div>${control?`<div class="settings-row-control">${control}</div>`:''}</div>`;}
function accountSettingsSwitch(key,value,disabled=false){const skeleton=accountSettingsFieldSkeleton(key,'switch');if(skeleton)return skeleton;const busy=['launch_at_login','prevent_sleep'].includes(key)?S.nativeSettingsSaving&&S.nativeSettingsRetry?.key===key:S.settingsPreferencePending&&S.settingsPreferenceRetry?.key===key;return `<button id="settings_${key}" type="button" role="switch" aria-busy="${!!busy}" aria-label="${esc(globalThis.RunTeamsLocale?.t('general.'+key,{},accountSettingsLabels()[key]||key)??accountSettingsLabels()[key]??key)}" aria-checked="${!!value}" class="settings-switch" ${disabled?'disabled':''} onclick="accountSettingsToggle('${key}')"><span></span></button>`;}
function accountSettingsLabels(){return {send_mode:'发送方式',allow_supplement:'运行中允许补充要求',restore_windows:'启动时恢复上次窗口',launch_at_login:'登录电脑时启动',prevent_sleep:'任务运行时防止自动休眠',confirmation:'需要确认',information:'需要补充信息',failure:'工作失败',completion:'工作完成',sound:'播放提示音'};}
function accountSettingsSelect(key,items,value,disabled=false){const skeleton=accountSettingsFieldSkeleton(key,'select');if(skeleton)return skeleton;return csel('settings_'+key,items,value,next=>accountSettingsSave(key,next),{disabled,menuVariant:'settingsSelect',menuAlign:'right'}).replace('aria-haspopup="menu"',`${key==='send_mode'?`title="${value==='meta-enter'?'Enter 换行':'Shift+Enter 换行'}" `:''}aria-label="${esc((['send_mode','close_action'].includes(key)?globalThis.RunTeamsLocale?.t('general.'+key,{},accountSettingsLabels()[key]||'关闭窗口后'):null)||accountSettingsLabels()[key]||({interface_font_size:'界面字号',code_font_size:'代码字号',default_model:'默认模型',default_effort:'思考深度',notification_timing:'提醒时机',close_action:'关闭窗口后'}[key])||key)}" aria-haspopup="menu" onkeydown="accountSettingsSelectKey(event,'settings_${key}')"`);}
function accountSettingsSelectKey(event,id){if(event.isComposing)return;if(document.getElementById('popmenu')&&_popAnchor===event.currentTarget)return;if(['ArrowDown','ArrowUp','Enter',' '].includes(event.key)&&!event.currentTarget.disabled){event.preventDefault();event.stopPropagation();cselOpen(event,id);}}
function accountSettingsPrefs(){return {send_mode:'enter',allow_supplement:true,notification_timing:'background',confirmation:true,information:true,failure:true,completion:true,sound:true,...S.settingsPreferences};}
function accountSettingsEditable(){return !!(S.localLibrary||S.account.signed_in)&&S.settingsPreferencesState==='ready'&&!S.settingsPreferencePending&&!S.settingsPreferenceRetry?.readOnly;}
function accountSettingsNotice(){
 const general=S.settingsTab==='general',notifications=S.settingsTab==='notifications',channels=S.settingsTab==='channels';
 if(!S.localLibrary&&!S.account.signed_in)return globalThis.RunTeamsOfficialUI?.signedOutSettingsNotice()||'';
 const subject=general?'账户设置':S.settingsTab==='notifications'?'提醒设置':S.settingsTab==='channels'?'新对话默认值':'设置';
 if(S.settingsPreferencesState==='error')return `<div class="settings-inline-error" role="alert"><span>${subject}暂时无法读取${general?'<br>请重新加载后，再修改发送方式和补充要求。':notifications||channels?'<br>请重新加载后再修改。':''}</span><button class="btn" onclick="accountSettingsReadPreferences(true)">重新加载</button></div>`;
 if(S.settingsPreferenceError){const unknown=!!S.settingsPreferenceRetry?.readOnly,message=channels?(unknown?'默认值保存结果待确认<br>请先重新加载，核对是否已更新。':'默认值未能保存<br>仍显示上次确认的值。请重新加载后再修改。'):(general||notifications)&&unknown?`${subject}保存结果待确认<br>请先重新加载，核对设置是否已更新。`:esc(notifications?S.settingsPreferenceError.replace('设置未能保存','提醒设置未能保存'):S.settingsPreferenceError);return `<div class="settings-inline-error" role="alert"><span>${message}</span><button class="btn" onclick="accountSettingsRetrySave(${channels?'true':''})">${unknown||channels?'重新加载':'重试'}</button></div>`;}
 if(S.settingsPreferencesState!=='ready')return '';
 // The disabled control communicates a pending save without moving the page.
 return '';
}
/* module-function:accountSettingsReadPreferences */
async function accountSettingsReadPreferences(force=false){
 if(!S.localLibrary&&!S.account.signed_in)return;const context=accountTeamContext();if(S.settingsPreferencesRead?.context===context)return S.settingsPreferencesRead.promise;if(!force&&S.settingsPreferencesState==='ready')return;
 const read={context};S.settingsPreferencesRead=read;S.settingsPreferencesState='loading';accountSettingsPaint();
 read.promise=(async()=>{try{const local=!!S.localLibrary,result=local?await RunTeamsApplication.readSettings():await RunTeamsOfficialUI.readSettings();if(context!==accountTeamContext()||S.settingsPreferencesRead!==read)return;if(result.error||(!result.settings||typeof result.settings!=='object'||Array.isArray(result.settings)))throw Error('设置读取失败');const value=result.settings;if(!value||typeof value!=='object'||Array.isArray(value))throw Error('设置格式无效');S.settingsPreferences=value;S.settingsPreferencesState='ready';accountSettingsSyncInteraction();}catch(error){if(context===accountTeamContext()&&S.settingsPreferencesRead===read)S.settingsPreferencesState='error';}finally{if(S.settingsPreferencesRead===read)S.settingsPreferencesRead=null;if(context===accountTeamContext()){accountSettingsStartRuntimeMonitor();accountSettingsPaint();}}})();return read.promise;
}

function accountSettingsToggle(key){if(['launch_at_login','prevent_sleep'].includes(key)){accountSaveNativeSetting(key,!S.nativeSettings?.[key]);return;}const device=key==='restore_windows';accountSettingsSave(key,!(device?accountDeviceDisplayPrefs()[key]:accountSettingsPrefs()[key]));}
async function accountSettingsSave(key,value){
 if(key==='close_action'){await accountSaveNativeSetting(key,value);return;}
 if(['interface_font_size','code_font_size','restore_windows'].includes(key)){if(key==='restore_windows'&&S.appearanceSaveFailures?.restore_windows?.readOnly)return;accountSaveDisplaySetting(key,value);return;}
 if(!accountSettingsEditable())return;const context=accountTeamContext(),previous=accountSettingsPrefs(),next={...previous,[key]:value};
 if(key==='default_model'&&value){const [channel,model]=String(value).split('::'),c=S.channels.find(item=>String(item.id)===channel);if(!c||!modelChannelAvailable(c)||!channelCatalog(c).models.some(item=>item.value===model))return;next.default_effort=defaultEffort(c,model);}
 if(key==='default_effort'){const [id,model]=String(previous.default_model||'').split('::'),channel=S.channels.find(c=>String(c.id)===id),item=channel&&channelCatalog(channel).models.find(row=>row.value===model);if(!channel||!modelChannelAvailable(channel)||!item||!((item.efforts||[]).length?(item.efforts||[]).includes(value):value===''))return;}
 const patch={[key]:value};if(key==='default_model')patch.default_effort=value?next.default_effort:'';
 S.settingsPreferencePending=true;S.settingsPreferenceError='';S.settingsPreferenceRetry={key,value};accountSettingsPaint();
 try{const result=S.localLibrary?await RunTeamsApplication.saveSettings(patch):await RunTeamsOfficialUI.saveSettings(patch);if(context!==accountTeamContext())return;if(result.error)throw Object.assign(Error(result.error),{code:result.code});if(result.ok!==true||!result.settings||typeof result.settings!=='object'||Array.isArray(result.settings)||Object.entries(patch).some(([field,expected])=>result.settings[field]!==expected))throw Error('设置未能保存');S.settingsPreferences=result.settings;S.settingsPreferenceRetry=null;accountSettingsSyncInteraction();if(['notification_timing','confirmation','information','failure','completion','sound'].includes(key)&&typeof accountNotifyPreferencesChanged==='function')accountNotifyPreferencesChanged();}
 catch(error){if(context===accountTeamContext()){if(error.code==='mutation_outcome_unknown'){S.settingsPreferenceRetry={key,value,patch,readOnly:true};S.settingsPreferenceError='保存结果尚未确认，请重新读取。';}else S.settingsPreferenceError='设置未能保存，仍使用上次确认的值。';}}
 finally{if(context===accountTeamContext()){S.settingsPreferencePending=false;accountSettingsPaint();}}
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
   return `<div class="settings-inline-error" role="alert"><span>${title}<br>${note}</span><button class="btn" onclick="accountReadNativeSettings()">重新读取</button></div>`;
  }
 }
 return `<div class="settings-inline-error" role="alert">${esc(error)} <button class="btn" onclick="accountRetryNativeSetting()">重试</button></div>`;
}
function accountRetryNativeSetting(){if(S.nativeSettingsError)return accountReadNativeSettings();const retry=S.nativeSettingsRetry;if(retry)return accountSaveNativeSetting(retry.key,retry.value);return accountReadNativeSettings();}
async function accountSettingsRetrySave(forceRead=false){const pending=S.settingsPreferenceRetry;if(!pending)return;if(!pending.readOnly&&!forceRead){accountSettingsSave(pending.key,pending.value);return;}const context=accountTeamContext();await accountSettingsReadPreferences(true);if(context!==accountTeamContext())return;if(S.settingsPreferencesState==='ready'&&(S.settingsTab==='general'||!pending.readOnly||Object.entries(pending.patch||{[pending.key]:pending.value}).every(([key,value])=>S.settingsPreferences?.[key]===value))){S.settingsPreferenceError='';S.settingsPreferenceRetry=null;accountNotifyPreferencesChanged();}else S.settingsPreferenceError='保存结果尚未确认，请稍后重新读取。';accountSettingsPaint();}
function accountDeviceDisplayPrefs(){let value={};S.appearanceDisplayReadFailed=false;try{value=JSON.parse(localStorage.getItem('runteams_device_display_v1')||'{}')||{};}catch(error){S.appearanceDisplayReadFailed=true;}return {interface_font_size:[12,13,14,16,18].includes(value.interface_font_size)?value.interface_font_size:14,code_font_size:[11,12,13,14,16,18].includes(value.code_font_size)?value.code_font_size:13,restore_windows:value.restore_windows!==false};}
function accountApplyDisplayPrefs(){const prefs=accountDeviceDisplayPrefs();if(S.appearanceDisplayReadFailed)return;document.documentElement.style.setProperty('--interface-font-size',prefs.interface_font_size+'px');document.documentElement.style.setProperty('--interface-font-scale',String(prefs.interface_font_size/14));document.documentElement.style.setProperty('--code-font-size',prefs.code_font_size+'px');}
function accountSaveDisplaySetting(key,value){
 const allowed={interface_font_size:[12,13,14,16,18],code_font_size:[11,12,13,14,16,18],restore_windows:[true,false]};
 if(!allowed[key]?.includes(value))return;
 const previous=accountDeviceDisplayPrefs();if(S.appearanceDisplayReadFailed){accountSettingsPaint();return;}
 const next={...previous,[key]:value};let written=false;
 try{localStorage.setItem('runteams_device_display_v1',JSON.stringify(next));written=true;const saved=accountDeviceDisplayPrefs();if(S.appearanceDisplayReadFailed||saved[key]!==value)throw Error('设置未确认');if(S.appearanceSaveFailures)delete S.appearanceSaveFailures[key];accountApplyDisplayPrefs();}
 catch(error){S.appearanceSaveFailures={...S.appearanceSaveFailures,[key]:{value,readOnly:written,message:key==='restore_windows'?(written?'窗口恢复设置保存结果待确认。':'窗口恢复设置未能保存。'):(written?'字号保存结果待确认。请核对当前字号后再修改。':'字号未能保存。请重新选择字号。')}};if(key==='restore_windows')toast(S.appearanceSaveFailures[key].message,'err');}
 accountSettingsPaint();
}
function accountAppearanceNotice(){if(S.appearanceDisplayReadFailed)return '<div class="settings-inline-error" role="alert"><span>字号设置暂时无法读取<br>请重新读取当前字号后再修改。</span><button class="btn" onclick="accountAppearanceRetry()">重新读取</button></div>';const failures=Object.values(S.appearanceSaveFailures||{});return failures.length?`<div class="settings-inline-error" role="alert"><span>${[...new Set(failures.map(item=>esc(item.message)))].join(' ')}</span><button class="btn" onclick="accountAppearanceRetry()">${failures.some(item=>item.readOnly)?'重新读取':'重试'}</button></div>`:'';}
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
function accountAppearanceSettings(){const prefs=accountDeviceDisplayPrefs(),sizes=values=>values.map(value=>({value,label:value+' px'}));return `${settingsPageHead('外观')}<div id="appearanceSaveNotice" aria-live="polite">${accountAppearanceNotice()}</div><section class="settings-section">${settingsSectionHead('主题')}<div class="appearance-options">${appearanceOption('system','跟随系统')}${appearanceOption('light','浅色')}${appearanceOption('dark','深色')}</div></section>${accountSettingsGroup('文字',accountSettingsRow('界面字号',accountSettingsSelect('interface_font_size',sizes([12,13,14,16,18]),prefs.interface_font_size,!!S.appearanceDisplayReadFailed))+accountSettingsRow('代码字号',accountSettingsSelect('code_font_size',sizes([11,12,13,14,16,18]),prefs.code_font_size,!!S.appearanceDisplayReadFailed)))}`;}
function accountNotificationSettings(){
 const prefs=accountSettingsPrefs(),native=!!accountNativeSettingsBridge(),permission=native?S.nativeSettings?.notification_permission:typeof Notification!=='undefined'?Notification.permission:'unavailable',unsupported=permission==='unavailable',permissionUnknown=!!S.notificationPermissionError&&S.notificationPermissionRetry==='read',permissionUnreadable=native&&(!!S.nativeSettingsError||!!S.nativeSettingsLoading||!['default','granted','denied'].includes(permission)),off=unsupported||permissionUnreadable||permissionUnknown||!accountSettingsEditable()||prefs.notification_timing==='never';
 const rows=[['confirmation','需要确认'],['information','需要补充信息'],['failure','工作失败'],['completion','工作完成']].map(([key,label])=>accountSettingsRow(label,accountSettingsSwitch(key,prefs[key],off))).join('');
 let error='',retry='accountSettingsRetryNotifications()',retryLabel='重试';
 if(S.notificationPermissionError){error=S.notificationPermissionError;if(permissionUnknown)retryLabel='重新读取';}
 else if(native&&!S.nativeSettingsLoading&&S.nativeSettingsError){error='系统通知权限暂时无法读取。请重新读取后，再设置桌面提醒。';retry='accountReadNativeSettings()';retryLabel='重新读取';}
 else if(S.nativeSettings?.notification_error||S.notificationDeliveryError){error='工作提醒暂时不可用，请重新读取服务状态。';retryLabel='重新读取';}
 let system='';
 if(unsupported)system='<p class="settings-footnote">当前环境不支持桌面通知。</p>';
 else if(native&&(S.nativeSettingsLoading||!S.nativeSettingsError)&&!['default','granted','denied'].includes(permission)&&(!permissionUnknown||S.nativeSettingsLoading))system=accountSettingsGroup('系统通知',accountSettingsRow(accountSettingsControlSkeleton('line','系统通知状态'),accountSettingsControlSkeleton('select','系统通知操作')));
 else if(permissionUnreadable&&(!!S.nativeSettingsError||!['default','granted','denied'].includes(permission)))system='';
 else if(permission==='granted')system=accountSettingsGroup('系统通知',accountSettingsRow('系统通知已允许',native?'<button class="btn" onclick="accountSettingsOpenNotificationSystem()">打开系统设置</button>':''));
 else system=accountSettingsGroup('系统通知',accountSettingsRow(permission==='denied'?'系统通知未获允许':'允许桌面通知',`<button class="btn" onclick="${permission==='denied'?'accountSettingsOpenNotificationSystem()':'accountSettingsNotificationPermission()'}" ${S.notificationPermissionPending||permissionUnknown?'disabled':''}>${S.notificationPermissionPending?'正在请求通知权限…':permission==='denied'?'打开系统设置':'允许通知'}</button>${native&&permission!=='denied'&&S.notificationPermissionError?'<button class="btn" onclick="accountSettingsOpenNotificationSystem()">打开系统设置</button>':''}`,permission==='denied'?(native?'请在系统设置中允许 RunTeams 发送通知。':'请在浏览器的网站设置中允许通知。'):'允许后，可按提醒时机接收工作提醒。'));
 return `${settingsPageHead('通知')}${accountSettingsNotice()}${error?`<div class="settings-inline-error" role="alert"><span>${esc(error)}</span><button class="btn" onclick="${retry}">${retryLabel}</button></div>`:''}${system}${accountSettingsGroup('桌面提醒',accountSettingsRow('提醒时机',accountSettingsSelect('notification_timing',[{value:'always',label:'始终提醒'},{value:'background',label:'仅应用在后台时'},{value:'never',label:'不提醒'}],prefs.notification_timing,unsupported||permissionUnreadable||permissionUnknown||!accountSettingsEditable())))}${accountSettingsGroup('工作提醒',rows)}${accountSettingsGroup('声音',accountSettingsRow('播放提示音',accountSettingsSwitch('sound',prefs.sound,off)))}${prefs.notification_timing==='never'?'<p class="settings-footnote">已关闭桌面提醒，提示音也不会播放。</p>':permission==='granted'?'<p class="settings-footnote">提醒显示和提示音仍受系统通知与专注模式控制。</p>':''}`;
}
async function accountSettingsNotificationPermission(){
 if(S.notificationPermissionPending)return;S.notificationPermissionPending=true;S.notificationPermissionError='';S.notificationPermissionRetry='';accountSettingsPaint();
 try{if(accountNativeSettingsBridge()){const result=await accountNativeSettingsBridge().postMessage({action:'permission'});if(!['granted','denied'].includes(result?.notification_permission)||typeof result.prevent_sleep!=='boolean'||typeof result.launch_at_login!=='boolean'||!['background','quit'].includes(result.close_action))throw Error('通知权限未确认');S.nativeSettings=result;}else if(typeof Notification!=='undefined')await Notification.requestPermission();else throw Error('不支持通知');}
 catch(error){S.notificationPermissionError='通知权限待确认，请重新读取系统通知权限后再设置。';S.notificationPermissionRetry='read';}
 finally{S.notificationPermissionPending=false;accountSettingsPaint();}
}
async function accountSettingsOpenNotificationSystem(){
 S.notificationPermissionError='';S.notificationPermissionRetry='';try{const bridge=accountNativeSettingsBridge();if(!bridge){S.notificationPermissionError='请在浏览器的网站设置中允许通知。';return;}const result=await bridge.postMessage({action:'notification_settings'});if(result?.ok!==true)throw Error('系统设置未打开');}catch(error){S.notificationPermissionError='未能打开系统通知设置，请从系统设置中打开 RunTeams 的通知选项。';S.notificationPermissionRetry='settings';}finally{accountSettingsPaint();}
}
function accountSettingsRetryNotifications(){if(S.notificationPermissionRetry==='read'){accountReadNativeSettings();return;}if(S.notificationPermissionRetry==='permission'){accountSettingsNotificationPermission();return;}if(S.notificationPermissionRetry==='settings'){accountSettingsOpenNotificationSystem();return;}S.notificationPermissionError='';accountReadNativeSettings();accountNotifyPreferencesChanged();if(!accountNativeSettingsBridge())accountPollWorkSettings();accountSettingsPaint();}
function accountNotifyPreferencesChanged(clear=false){const bridge=accountNativeSettingsBridge();if(bridge)bridge.postMessage({action:'notifications_changed',clear}).catch(()=>{S.notificationPermissionError='工作提醒暂时不可用，请重新读取服务状态。';accountSettingsPaint();});}
function accountNotifyNativeReady(){
 if(S.booting||!S.accountSessionReady||!S.account.signed_in||S.workspaceStartup?.pending)return;
 const context=String(S.account.user_id)+':'+(S.activeOrganization||'');if(S.notificationsReadyContext===context)return;S.notificationsReadyContext=context;
 const bridge=accountNativeSettingsBridge();bridge?.postMessage({action:'notifications_ready'}).catch(()=>{});
 try{const raw=sessionStorage.getItem('runteams_notification_target');if(raw){sessionStorage.removeItem('runteams_notification_target');accountOpenWorkNotification(JSON.parse(raw));}}catch(error){}
}
function accountOpenWorkNotification(target){
 if(S.booting||!S.accountSessionReady||S.workspaceStartup?.pending)return false;
 if(!S.account.signed_in||target?.actor!==String(S.account.user_id)){toast('这条通知属于其他账户，请切回原账户查看。','info');return true;}
 if(!['chat','workflow','automation','employee'].includes(target.kind)||!Number.isSafeInteger(target.id)||target.id<=0||typeof target.workspace!=='string')return true;
 (async()=>{try{if(target.workspace!==(S.activeOrganization||'')){await RunTeamsOfficialUI.switchWorkspace(target.workspace,{notificationTarget:target});return;}accountSettingsClose();if(target.kind==='chat')await openRailConversationSession(target.id,{forceWorkspace:true});else if(target.kind==='workflow')await workItemOpenTask(target.id,{storageScope:target.storage_scope});else if(target.kind==='automation')await openAutomationRunRecord(target.id);else if(target.kind==='employee')await openBotConversation(target.id);}catch(error){toast('这条通知暂时无法打开，请稍后重试。','err');}})();return true;
}


function accountModelDefaults(){
 if(!S.modelCatalogReady&&(S.modelCatalogLoading||!S.modelCatalogError)){
  const skeleton=label=>`<span class="skeleton-block channel-default-skeleton" role="status" aria-label="${label}" aria-busy="true"></span>`;
  return accountSettingsRow('默认模型',skeleton('正在读取默认模型'))+accountSettingsRow('思考深度',skeleton('正在读取思考深度'));
 }
 const prefs=accountSettingsPrefs(),channels=(S.channels||[]).filter(modelChannelAvailable),items=channels.flatMap(c=>(channelCatalog(c).models||[]).map(model=>({value:String(c.id)+'::'+model.value,label:model.display_name||model.value}))),value=prefs.default_model||'',channel=channels.find(c=>String(c.id)===value.split('::')[0]),model=value.split('::')[1],known=items.some(item=>item.value===value),choices=[...(value&&!known?[{value,label:'当前默认模型不可用',disabled:true}]:[]),{value:'',label:'旗舰模型'},...items];const notice=S.modelCatalogError?`<div class="settings-inline-error" role="alert"><span>${RunTeamsModelChannels.hasSelectableModels(S)?'部分渠道的模型列表暂时无法读取。':'可用模型暂时无法读取<br>请重新读取后再选择模型。'}</span><button class="btn" onclick="refreshModelCatalog(true).catch(()=>{})">重新读取</button></div>`:S.modelCatalogReady&&channels.length&&!items.length?'<div class="settings-inline-error" role="status"><span>暂无可用模型<br>请检查已连接 Agent 的登录状态与模型权限。</span><button class="btn" onclick="accountRefreshChannels()">重新检测</button></div>':'';return notice+accountSettingsRow('默认模型',accountSettingsSelect('default_model',choices,value,!accountSettingsEditable()||S.modelCatalogLoading||!S.modelCatalogReady||!!S.modelCatalogError&&!RunTeamsModelChannels.hasSelectableModels(S)),value&&!known?'连接对应 Agent 或重新选择模型。':items.length||channels.length||S.modelCatalogLoading||S.modelCatalogError||S.environmentLoading||S.channelSettingsRefreshing?'':'连接 Agent 后读取可用模型。')+accountSettingsRow('思考深度',accountSettingsSelect('default_effort',channel&&known?effortItems(channel,model,prefs.default_effort,true):[{value:'',label:'模型默认'}],channel&&known?normalizedEffort(channel,model,prefs.default_effort):'',!accountSettingsEditable()||S.modelCatalogLoading||!S.modelCatalogReady||!!S.modelCatalogError&&!RunTeamsModelChannels.hasSelectableModels(S)||!channel||!known));}
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
/* module-function:accountToolsSettings */
function accountToolsView(){
 const context=accountTeamContext();if(S.settingsToolsView?.context!==context)S.settingsToolsView={context,tab:'plugins',catalog:false,queries:{},limit:50};return S.settingsToolsView;
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
 if(loading&&!env)return '';
 if(error||failed)return `<div class="settings-tools-notice settings-inline-error" role="alert"><span>${error?(env?'清单未更新，显示上次读取的内容。':'暂时无法读取扩展清单。'):'部分来源暂时无法读取，请重新读取后再管理。'}</span><button class="btn" onclick="accountReadSettingsExtensions(true)">重新读取</button></div>`;
 if(env?.channels?.some(channel=>!channel.ready))return '<div class="settings-tools-notice"><span>部分渠道暂不可用，扩展状态尚未确认。</span><button class="btn" onclick="openSettingsPage(&quot;channels&quot;)">检查模型渠道</button></div>';
 return '';
}
function accountToolsTabs(){
 const view=accountToolsView(),env=S.settingsExtensions;
 return accountToolsCategories().map(([key,label])=>`<button type="button" id="toolsTab_${key}" role="tab" aria-selected="${view.tab===key}" aria-controls="settingsToolsList" tabindex="${view.tab===key?'0':'-1'}" onclick="accountToolsSelect('${key}')" onkeydown="accountToolsTabKey(event,'${key}')"><span>${label}</span>${env?`<small>${(env[key]||[]).length}</small>`:''}</button>`).join('');
}
function accountToolsIcon(item,key){
 const parent=key==='skills'&&(S.settingsExtensions?.plugins||[]).find(row=>String(row.channel_id)===String(item.channel_id)&&row.id===item.plugin_id),url=item.icon_url||parent?.icon_url||'';
 return /^\/api\/environment\/plugin-icon\/[a-f0-9]{24}$/.test(url)?`<img src="${esc(url)}" alt="" loading="lazy" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span hidden>${ICON(key==='mcp_servers'?'plug':'package')}</span>`:ICON(key==='mcp_servers'?'plug':'package');
}
function accountToolsSkeleton(key){
 const bone=kind=>`<span class="skeleton-block tools-skeleton-${kind}"></span>`,actions=(key==='skills'?bone('scope'):'')+(key==='mcp_servers'?bone('gear'):'')+(key==='available_plugins'?'':bone('switch'))+(key==='mcp_servers'?'':bone('arrow'));
 const rows=Array.from({length:4},()=>key==='mcp_servers'?`<div class="tools-mcp-row"><div class="tools-mcp-name">${bone('title')}${bone('logo')}</div><div class="settings-tool-actions">${actions}</div></div>`:`<div class="settings-tool-row ${key==='skills'?'settings-skill-row':''}"><div class="settings-tool-identity">${bone('icon')}<span class="settings-tool-copy">${bone('title')}${bone('description')}</span></div><div class="settings-tool-actions">${actions}</div></div>`).join('');
 return `<div data-settings-skeleton data-skeleton-list aria-busy="true" aria-label="正在读取扩展清单" inert>${key==='mcp_servers'?`<section class="tools-section"><h3>${bone('title')}</h3><div class="tools-row-group">${rows}</div></section>`:rows}</div>`;
}
function accountToolsList(){
 const view=accountToolsView(),key=accountToolsKey(),env=S.settingsExtensions,{loading,error,failed}=accountToolsStatus();
 if(!env)return loading?accountToolsSkeleton(key):'';
 const rows=accountToolsRows(),query=String(view.queries[key]||'').trim();
 if(!rows.length){if(error||failed||loading&&S.settingsExtensionsConfirmedScope!==S.settingsExtensionsScope)return '';return `<div class="settings-tools-empty"><h3>${query?'未找到匹配项':key==='available_plugins'?'暂无可用插件':key==='plugins'?'暂无插件':key==='skills'?'暂无技能':'暂无 MCP 连接'}</h3><p>${query?'试试其他名称、简介或来源。':key==='available_plugins'?'连接模型渠道后，读取对应 Agent 的插件目录。':key==='plugins'?'选择本地插件文件夹并导入。':''}</p>${query?'<button class="btn" onclick="accountToolsClearSearch()">清除搜索</button>':key==='plugins'?'<button class="btn" onclick="accountToolsBrowseFolder(this)">浏览目录</button>':''}</div>`;}
 const shown=rows.slice(0,view.limit),html=key==='mcp_servers'?accountToolsMcpGroups(shown):shown.map(({item,index})=>accountToolsRow(item,key,index)).join('');
 return html+(rows.length>view.limit?`<button class="btn settings-tools-more" onclick="accountToolsMore()">更多...</button>`:'')+`<span class="settings-tools-results" role="status">${query?'找到 '+rows.length+' 项':''}</span>`;
}
function accountToolsSettings(){
 const view=accountToolsView();if(view.detail)return accountToolsDetailPage(view.detail);const key=accountToolsKey(),label=accountToolsCategories().find(row=>row[0]===view.tab)?.[1]||'插件',query=view.queries[key]||'';
 return `<div class="settings-tools" data-tools-view="${view.catalog?'catalog':view.tab}"><div class="settings-tools-heading">${settingsPageHead(view.catalog?'插件目录':'技能与工具',view.catalog?'来自已连接 Agent 的可用插件':'')}<div class="settings-tools-heading-actions">${view.catalog?'<button class="btn" onclick="accountToolsCatalog(false)">返回已安装</button>':'<button class="btn" onclick="accountToolsBrowseFolder(this)">浏览目录</button>'}<button type="button" id="settingsToolsAdd" class="btn pri" data-menu-trigger="primary" aria-haspopup="menu" onclick="accountToolsAddMenu(this)">添加 ${ICON('chev')}</button></div></div><div class="settings-tools-toolbar">${view.catalog?'<span class="settings-tools-catalog-label">可用插件</span>':`<div class="settings-tools-tabs" role="tablist" aria-label="扩展分类">${accountToolsTabs()}</div>`}<label class="settings-tools-search rt-search-field rt-search-field--compact">${ICON('search')}<input id="settingsToolsSearch" type="search" value="${esc(query)}" placeholder="搜索${view.catalog?'插件':label}" aria-label="搜索${view.catalog?'插件':label}" oninput="accountToolsSearch(this.value)" onkeydown="if(event.key==='Escape'&&!event.isComposing){event.stopPropagation();accountToolsClearSearch()}"></label></div><div id="settingsToolsNotice">${accountToolsNotice()}</div><div id="settingsToolsList" role="tabpanel" ${view.catalog?'aria-label="插件目录"':`aria-labelledby="toolsTab_${view.tab}"`}>${accountToolsList()}</div></div>`;
}
function accountToolsSelect(key){if(!accountToolsCategories().some(row=>row[0]===key))return;const view=accountToolsView();view.tab=key;view.catalog=false;view.detail=null;view.limit=50;accountSettingsPaint();document.getElementById('settingsPanel').scrollTop=0;document.getElementById('toolsTab_'+key)?.focus({preventScroll:true});}
function accountToolsTabKey(event,key){if(event.isComposing||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const keys=accountToolsCategories().map(row=>row[0]),index=keys.indexOf(key);accountToolsSelect(keys[event.key==='Home'?0:event.key==='End'?keys.length-1:(index+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length]);}
function accountToolsCatalog(show){const view=accountToolsView();view.catalog=show;view.detail=null;view.limit=50;accountSettingsPaint();document.getElementById('settingsPanel').scrollTop=0;document.getElementById('settingsToolsSearch')?.focus({preventScroll:true});}
function accountToolsSearch(value){const view=accountToolsView();view.queries[accountToolsKey()]=String(value);view.limit=50;const list=document.getElementById('settingsToolsList');if(list)list.innerHTML=accountToolsList();}
function accountToolsClearSearch(){const input=document.getElementById('settingsToolsSearch');if(input){input.value='';accountToolsSearch('');input.focus();}}
function accountToolsMore(){const view=accountToolsView(),list=document.getElementById('settingsToolsList');view.limit+=50;if(list)list.innerHTML=accountToolsList();}
function accountToolsPatch(panel,html){
 const current=panel.querySelector('.settings-tools');if(!current)return false;const next=panel.cloneNode(false);next.innerHTML=html;const tools=next.querySelector('.settings-tools');if(!tools)return false;if(current.dataset.toolsDetail||tools.dataset.toolsDetail)return current.outerHTML===tools.outerHTML;if(tools.dataset.toolsView!==current.dataset.toolsView)return false;
 for(const selector of ['.settings-tools-tabs','#settingsToolsNotice','#settingsToolsList']){const a=current.querySelector(selector),b=tools.querySelector(selector);if(a&&b&&a.innerHTML!==b.innerHTML)a.innerHTML=b.innerHTML;}return true;
}
async function accountToolsBrowseFolder(button){
 if(S.settingsToolsPicking)return;const context=accountTeamContext();S.settingsToolsPicking=true;if(button){button.disabled=true;button.setAttribute('aria-busy','true');}
 try{const picked=await api('/api/environment/local/pick','POST',{});if(context!==accountTeamContext()||picked.cancelled)return;if(picked.error)throw Error(picked.error);if(!picked.token||!picked.channels?.length)throw Error('未找到可导入的内容。');
 const detail={key:'local-import',context,token:(S.settingsExtensionDialogSequence||0)+1,picked};S.settingsExtensionDialogSequence=detail.token;S.settingsExtensionDetail=detail;
 openChildDialog({manageFocus:true,className:'settings-extension-dialog',title:'导入'+(picked.kind==='skill'?'技能':'插件'),attrs:'role="dialog" aria-modal="true" data-settings-extension-dialog="'+detail.token+'" onkeydown="accountSettingsExtensionKeydown(event)"',body:`<p>${esc(picked.name)}</p><label class="tools-import-target">导入到<span class="tools-import-control"><select id="toolsImportChannel">${picked.channels.map(row=>`<option value="${esc(row.id)}">${esc(row.name)}</option>`).join('')}</select>${ICON('chev')}</span></label><p id="toolsImportStatus" role="status"></p>`,footer:`<button class="btn" onclick="closeChildDialog()">取消</button><button id="toolsImportConfirm" class="btn pri" onclick="accountToolsImportFolder(${detail.token})">导入</button>`});
 }catch(error){if(context===accountTeamContext())toast(error.message||'无法打开文件夹。','err');}finally{S.settingsToolsPicking=false;if(button?.isConnected){button.disabled=false;button.removeAttribute('aria-busy');}}
}
async function accountToolsImportFolder(token){
 const detail=accountSettingsExtensionDialogCurrent(token);if(!detail||detail.submitted)return;detail.submitted=true;const channel=document.getElementById('toolsImportChannel'),button=document.getElementById('toolsImportConfirm'),status=document.getElementById('toolsImportStatus');button.disabled=true;channel.disabled=true;status.textContent='正在导入…';
 try{const result=await api('/api/environment/local/import','POST',{token:detail.picked.token,channel_id:channel.value});if(result.error)throw Error(result.error);if(detail.context!==accountTeamContext())return;S.channelMutationVersion=(S.channelMutationVersion||0)+1;const view=accountToolsView();view.catalog=false;view.detail=null;view.tab=result.kind==='skill'?'skills':'plugins';view.queries[view.tab]='';if(accountSettingsExtensionDialogCurrent(token))closeChildDialog();await accountReadSettingsExtensions(true);toast('已导入 '+result.name,'ok');
 }catch(error){if(accountSettingsExtensionDialogCurrent(token)){status.textContent=error.code==='mutation_outcome_unknown'?'导入结果尚未确认，请关闭后重新读取清单。':error.message||'导入未完成，请重新读取清单。';button.textContent='已提交';}}
}
function accountToolsAddMenu(anchor){
 openMenu(anchor,[{label:'添加插件',fn:()=>accountToolsCatalog(true)},{label:'添加 MCP',fn:()=>accountToolsAddGuide('mcp')},{label:'添加技能',fn:()=>accountToolsAddGuide('skills')},{divider:true},{label:'重新读取',fn:()=>accountReadSettingsExtensions(true)}],{variant:'settingsSelect',align:'right'});
}
function accountToolsAddGuide(kind){
 const detail={key:'guide',context:accountTeamContext(),token:(S.settingsExtensionDialogSequence||0)+1,commands:[]};S.settingsExtensionDialogSequence=detail.token;S.settingsExtensionDetail=detail;
 const sources=(S.settingsExtensions?.channels||[]).filter(row=>row.ready&&['codex','claude-code'].includes(row.provider));
 if(kind==='mcp')detail.commands=sources.map(row=>({label:row.name||providerDefinition(row.provider)?.label||row.provider,command:accountExtensionShellArgument(row.runtime?.executable||(row.provider==='codex'?'codex':'claude'))+' mcp add --help'}));
 const body=kind==='skills'?'<p>将技能添加到对应 Agent 的技能目录，完成后重新读取清单。</p><p>原生技能由 Agent 自动发现；插件附带的技能可通过插件目录添加。</p>':'<p>在对应 Agent 中添加 MCP 连接，完成后重新读取清单。</p>';
 openChildDialog({manageFocus:true,className:'settings-extension-dialog',title:kind==='skills'?'添加技能':'添加 MCP',attrs:'role="dialog" aria-modal="true" data-settings-extension-dialog="'+detail.token+'" onkeydown="accountSettingsExtensionKeydown(event)"',body:body+detail.commands.map((command,index)=>`<p>${esc(command.label)} <button class="btn" onclick="accountCopySettingsExtensionCommand(${detail.token},${index})">复制命令</button></p><code class="install-command">${esc(command.command)}</code>`).join('')+(!sources.length?'<p>请先连接模型渠道。</p>':'')+'<p id="settingsExtensionCopyStatus" role="status"></p>',footer:'<button class="btn" onclick="closeChildDialog();accountReadSettingsExtensions(true)">重新读取</button><button class="btn" onclick="closeChildDialog()">完成</button>'});
}
function accountToolsReadonlyState(item,key){
 const status=accountSettingsExtensionStatus(item,key),known=typeof item.enabled==='boolean'&&!item._settingsStale&&S.settingsExtensionsState==='ready'&&!['来源待确认','读取失败','未更新','渠道未就绪'].includes(status);
 return known?`<span class="tools-state-control" title="启停由对应 Agent 管理"><button type="button" class="settings-switch tools-readonly-switch" role="switch" aria-label="${esc(item.display_name||item.name||item.id)}：${item.enabled?'已启用':'已停用'}，由对应 Agent 管理" aria-checked="${item.enabled}" disabled><span></span></button></span>`:`<span class="settings-extension-status">${esc(status)}</span>`;
}
function accountToolsSourceLogo(item){const provider=accountSettingsExtensionProvider(item),label=item.channel_name||accountSettingsExtensionSource(item).name||'来源待确认',icon=providerBrandIcon(provider);return `<span class="tools-source-logo" role="img" aria-label="${esc(label)}" title="${esc(label)}">${icon||ICON('plug')}</span>`;}
function accountToolsRow(item,key,index){
 const name=item.display_name||item.name||item.id||'扩展',source=item.channel_name||'来源待确认',skill=key==='skills';
 const origin={personal:'个人',system:'系统',project:'项目',plugin:'插件'}[item.source||item.scope]||'',action=`accountSettingsExtensionDetail('${key}',${index})`;
 return `<div class="settings-tool-row ${skill?'settings-skill-row':''}"><button type="button" class="settings-tool-identity" aria-label="查看 ${esc(name)}，${esc(source)}" onclick="${action}"><span class="settings-tool-icon" aria-hidden="true">${accountToolsIcon(item,key)}</span><span class="settings-tool-copy"><span class="settings-tool-name">${esc(name)}${accountToolsSourceLogo(item)}</span><span class="settings-tool-description">${esc(item.description||'暂无简介')}</span></span></button><div class="settings-tool-actions">${skill?`<span class="settings-extension-status">${esc(origin)}</span>${accountToolsReadonlyState(item,key)}<button type="button" class="tools-icon-button" aria-label="查看 ${esc(name)} 技能详情" title="技能详情" onclick="${action}">${ICON('chev')}</button>`:`${key==='plugins'?accountToolsReadonlyState(item,key):''}<button type="button" class="tools-icon-button" aria-label="查看 ${esc(name)} 详情" title="详情" onclick="${action}">${ICON('chev')}</button>`}</div></div>`;
}
function accountToolsMcpGroups(rows){
 const group=(title,items)=>items.length?`<section class="tools-section"><h3>${title}</h3><div class="tools-row-group">${items.map(({item,index})=>`<div class="tools-mcp-row"><button type="button" class="tools-mcp-name" onclick="accountSettingsExtensionDetail('mcp_servers',${index})"><span>${esc(item.name||item.id)}</span>${accountToolsSourceLogo(item)}</button><div class="settings-tool-actions"><button type="button" class="tools-icon-button" aria-label="查看 ${esc(item.name)} MCP 配置" onclick="accountSettingsExtensionDetail('mcp_servers',${index})">${ICON('settings')}</button>${accountToolsReadonlyState(item,'mcp_servers')}</div></div>`).join('')}</div></section>`:'';
 return group('服务器',rows.filter(({item})=>!item.plugin_id))+group('来自插件',rows.filter(({item})=>item.plugin_id));
}
function accountToolsBack(){const view=accountToolsView(),detail=view.detail;view.detail=null;accountSettingsPaint();const panel=document.getElementById('settingsPanel');if(panel){panel.scrollTop=view.listScroll||0;const index=S.settingsExtensions?.[detail?.key]?.findIndex(item=>accountSettingsExtensionIdentity(item)===detail.identity),action=`accountSettingsExtensionDetail('${detail?.key}',${index})`;[...panel.querySelectorAll('button')].find(button=>button.getAttribute('onclick')===action)?.focus({preventScroll:true});}}
function accountToolsSafeLink(url,label){try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return '';return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(label||u.href)}</a>`;}catch{return '';}}
function accountToolsDetailPage(detail){
 const item=S.settingsExtensions?.[detail.key]?.find(row=>accountSettingsExtensionIdentity(row)===detail.identity),mcp=detail.key==='mcp_servers',name=item?.display_name||item?.name||item?.id||'扩展详情';
 const breadcrumb=`<div class="tools-breadcrumb"><button type="button" class="settings-tools-back" onclick="accountToolsBack()">${mcp?'MCP 设置':'插件设置'}</button>${ICON('chev')}<span>${esc(name)}</span></div>`;
 if(!item)return `<div class="settings-tools" data-tools-detail="true">${breadcrumb}<div class="settings-tools-empty">此扩展已不在当前清单中。</div></div>`;
 const source=accountSettingsExtensionSource(item),status=['error','loading'].includes(S.settingsExtensionsState)||item._settingsStale?'未更新':detail.key==='available_plugins'?'待安装':accountSettingsExtensionStatus(item,detail.key);
 const facts=(rows)=>`<div class="tools-row-group tools-facts">${rows.filter(([label,value])=>value).map(([label,value])=>`<div class="tools-fact-row"><dt>${label}</dt><dd>${value}</dd></div>`).join('')}</div>`;
 const section=(title,body)=>`<section class="tools-section"><h3>${title}</h3>${body}</section>`;
 const skills=(S.settingsExtensions?.skills||[]).map((skill,index)=>({skill,index})).filter(({skill})=>String(skill.channel_id)===String(item.channel_id)&&skill.plugin_id===item.id);
 const skillRows=skills.map(({skill,index})=>`<div class="tools-contained-skill"><button type="button" class="settings-tool-identity" onclick="accountSettingsExtensionDetail('skills',${index})"><span class="settings-tool-copy"><span class="settings-tool-name">${esc(skill.name)}</span><span class="settings-tool-description">${esc(skill.description||'暂无简介')}</span></span></button>${accountToolsReadonlyState(skill,'skills')}<button type="button" class="tools-icon-button" aria-label="查看 ${esc(skill.name)}" onclick="accountSettingsExtensionDetail('skills',${index})">${ICON('chev')}</button></div>`).join('');
 const about=mcp?[['渠道',esc(item.channel_name||source.name||'来源待确认')],['状态',esc(status)],['连接类型',esc(item.transport||'未提供')]]:[['渠道',esc(item.channel_name||source.name||'来源待确认')],['状态',esc(status)],['类别',esc(item.category||'')],['开发者',esc(item.developer_name||'')],['版本',esc(item.version||'')],['网站',accountToolsSafeLink(item.homepage_url)],['隐私政策',accountToolsSafeLink(item.privacy_policy_url,'查看隐私政策')],['服务条款',accountToolsSafeLink(item.terms_url,'查看服务条款')]];
 return `<div class="settings-tools tools-detail-page" data-tools-detail="true">${breadcrumb}<div class="tools-detail-content"><div class="tools-detail-hero">${mcp?'':`<span class="settings-tool-icon tools-hero-icon">${accountToolsIcon(item,detail.key)}</span>`}<div class="tools-detail-title"><h2>${esc(name)}${mcp?' MCP':''}</h2><p>${esc(item.description||'')}</p></div><div class="tools-detail-actions">${!mcp&&item.homepage_url?accountToolsSafeLink(item.homepage_url,'查看详情'):''}<button class="btn" onclick="accountToolsManageCurrent()">管理方式</button></div></div>${!mcp&&skills.length?section('技能','<div class="tools-row-group">'+skillRows+'</div>'):''}${section(mcp?'连接配置':'关于',facts(about))}${mcp?'<p class="settings-footnote tools-config-note">完整配置请通过对应 Agent 查看和修改。</p>':''}${accountToolsNotice()}</div></div>`;
}
function accountToolsManageCurrent(){const page=accountToolsView().detail;if(!page)return;const detail={...page,context:accountTeamContext(),token:(S.settingsExtensionDialogSequence||0)+1};S.settingsExtensionDialogSequence=detail.token;S.settingsExtensionDetail=detail;accountPaintSettingsExtensionDetail(detail);}
function accountToolsMarkdownSkeleton(){
 return '<div class="tools-markdown-skeleton" data-settings-skeleton role="status" aria-busy="true" aria-label="正在读取技能内容" inert>'+Array.from({length:6},()=>'<span class="skeleton-block"></span>').join('')+'</div>';
}
function accountToolsSkillDialog(detail){
 const item=S.settingsExtensions?.skills?.find(row=>accountSettingsExtensionIdentity(row)===detail.identity);if(!item)return;
 const parent=item.plugin_id&&(S.settingsExtensions.plugins||[]).find(row=>String(row.channel_id)===String(item.channel_id)&&row.id===item.plugin_id);detail.resource=parent;detail.commands=[];
 const name=item.display_name||item.name||item.id,available=parent?.has_resources&&!item._settingsStale&&S.settingsExtensionsState==='ready';
 openChildDialog({manageFocus:true,className:'settings-extension-dialog tools-skill-dialog',title:name,headerHtml:`<span class="settings-tool-icon tools-skill-hero-icon">${accountToolsIcon(item,'skills')}</span><div class="tools-skill-header-actions">${accountToolsReadonlyState(item,'skills')}<button type="button" class="tools-icon-button" aria-label="技能操作" aria-haspopup="menu" onclick="accountToolsSkillMenu(this,${detail.token})">${ICON('more')}</button><button type="button" class="x modal-x" aria-label="关闭技能详情" onclick="closeChildDialog()">${ICON('x')}</button></div>`,attrs:`role="dialog" aria-modal="true" aria-labelledby="settingsSkillTitle" data-settings-extension-dialog="${detail.token}" onkeydown="accountSettingsExtensionKeydown(event)"`,body:`<div class="tools-skill-intro"><h2 id="settingsSkillTitle">${esc(name)} <span>Skill</span></h2><p>${esc(item.description||'暂无简介')}</p><small>${esc(item.channel_name||'')} / ${esc({personal:'个人',system:'系统',project:'项目',plugin:'来自插件'}[item.source]||'技能')}</small></div><div id="settingsSkillMarkdown" class="tools-skill-markdown doc-reader-prose" aria-busy="${!!available}">${available?accountToolsMarkdownSkeleton():'<div class="tools-skill-unavailable"><p>暂未提供技能正文</p><small>当前渠道清单只提供此技能的名称和简介。</small></div>'}</div><p id="settingsExtensionCopyStatus" class="settings-footnote" role="status"></p>`});
 if(available)accountToolsLoadSkillMarkdown(detail.token);
}
async function accountToolsLoadSkillMarkdown(token){
 const detail=accountSettingsExtensionDialogCurrent(token);if(!detail||detail.key!=='skills')return;const item=S.settingsExtensions?.skills?.find(row=>accountSettingsExtensionIdentity(row)===detail.identity),parent=detail.resource;if(!item||!parent?.has_resources)return;
 const sequence=(detail.readSequence||0)+1;detail.readSequence=sequence;const mutation=S.channelMutationVersion||0;
 const current=()=>detail.readSequence===sequence&&mutation===(S.channelMutationVersion||0)&&accountSettingsExtensionDialogCurrent(token)===detail&&S.settingsExtensions?.skills?.some(row=>accountSettingsExtensionIdentity(row)===detail.identity);
 const host=document.getElementById('settingsSkillMarkdown');if(!host)return;host.setAttribute('aria-busy','true');host.innerHTML=accountToolsMarkdownSkeleton();
 try{const payload=await installedPluginResourcePayload(item.channel_id,parent.id);if(!current())return;const prefix=String(item.plugin_id)+':',folder=String(item.id).startsWith(prefix)?String(item.id).slice(prefix.length):'',path=`/skills/${folder}/SKILL.md`;if(!folder||!Object.hasOwn(payload.files,path))throw Error('missing skill resource');const file=await payload.loadFile(path.slice(1));if(!current()||!host.isConnected)return;if(typeof file?.code!=='string')throw Error('not text');detail.markdown=file.code;const body=file.code.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/,'');const template=document.createElement('template');template.innerHTML=renderMarkdown(body);template.content.querySelectorAll('img').forEach(image=>image.remove());template.content.querySelectorAll('a').forEach(link=>{const href=link.getAttribute('href')||'';if(/^https?:\/\//i.test(href)){link.target='_blank';link.rel='noopener noreferrer';}else{link.replaceWith(...link.childNodes);}});host.replaceChildren(template.content);}
 catch(error){if(current()&&host.isConnected)host.innerHTML=`<div class="tools-skill-unavailable" role="alert"><p>技能内容暂时无法加载</p><button class="btn" onclick="accountToolsLoadSkillMarkdown(${token})">重新加载</button></div>`;}
 finally{if(current()&&host.isConnected)host.setAttribute('aria-busy','false');}
}
function accountToolsSkillMenu(anchor,token){const detail=accountSettingsExtensionDialogCurrent(token);if(!detail)return;openMenu(anchor,[{label:'复制 Markdown',disabled:typeof detail.markdown!=='string',fn:()=>accountToolsCopyMarkdown(token)}],{variant:'settingsSelect'});document.getElementById('popmenu')?.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing){event.preventDefault();event.stopPropagation();closePop();}});}
async function accountToolsCopyMarkdown(token){const detail=accountSettingsExtensionDialogCurrent(token);if(typeof detail?.markdown!=='string')return;try{await navigator.clipboard.writeText(detail.markdown);if(accountSettingsExtensionDialogCurrent(token)===detail)document.getElementById('settingsExtensionCopyStatus').textContent='Markdown 已复制';}catch{if(accountSettingsExtensionDialogCurrent(token)===detail)document.getElementById('settingsExtensionCopyStatus').textContent='复制失败，请选择正文后手动复制。';}}
function accountMergeSettingsExtensions(result,previous){
 const merged={...result};for(const key of ['skills','plugins','mcp_servers','available_plugins']){merged[key]=(result[key]||[]).map(item=>({...item}));for(const channel of result.channels||[]){if(!['error','partial'].includes(channel.read_states?.[key==='available_plugins'?'plugins':key]))continue;for(const old of previous?.[key]||[]){if(String(old.channel_id)!==String(channel.id))continue;const same=merged[key].some(item=>String(item.channel_id)===String(old.channel_id)&&String(item.id||item.name)===String(old.id||old.name));if(!same)merged[key].push({...old,_settingsStale:true});}}}return merged;
}
function accountFilterSettingsExtensions(value,selection){
 if(!value)return value;const ids=new Set(selection.split(',').filter(Boolean)),result={...value};
 for(const key of ['channels','skills','plugins','mcp_servers','available_plugins','issues'])result[key]=(value[key]||[]).filter(row=>ids.has(String(key==='channels'?row.id:row.channel_id)));
 return result;
}
async function accountReadSettingsExtensions(force=false){
 const context=accountTeamContext(),mutation=S.channelMutationVersion||0,selection=environmentConnectedChannelIds().join(','),scope=modelChannelData().identity('extensions');if(S.settingsExtensionsRead?.scope===scope)return S.settingsExtensionsRead.promise;if(!force&&S.settingsExtensionsScope===scope&&['ready','error'].includes(S.settingsExtensionsState))return S.settingsExtensionsState==='ready';
 const read={context,mutation,selection,scope};S.settingsExtensionsRead=read;S.settingsExtensionsScope=scope;S.settingsExtensions=accountFilterSettingsExtensions(S.settingsExtensions,selection);S.settingsExtensionsState='loading';accountSettingsPaint();
 read.promise=(async()=>{try{const result=await modelChannelData().extensions(force);if(!result){if(S.settingsExtensionsRead===read){S.settingsExtensionsState='error';S.settingsExtensionsScope='';}return false;}if(context!==accountTeamContext()||S.settingsExtensionsRead!==read)return false;if(result.error)throw Error(result.error);if(read.mutation!==(S.channelMutationVersion||0))throw Error('渠道已改变，请重新读取');const confirmedSelection=environmentConnectedChannelIds().join(',');S.settingsExtensions=accountMergeSettingsExtensions(accountFilterSettingsExtensions(result,confirmedSelection),S.settingsExtensions);S.settingsExtensionsScope=modelChannelData().identity('extensions');S.settingsExtensionsState='ready';S.settingsExtensionsConfirmedScope=S.settingsExtensionsScope;return true;}catch(error){if(context===accountTeamContext()&&S.settingsExtensionsRead===read)S.settingsExtensionsState='error';return false;}finally{if(S.settingsExtensionsRead===read)S.settingsExtensionsRead=null;if(context===accountTeamContext())accountSettingsPaint();}})();return read.promise;
}
function accountExtensionShellArgument(value){return "'"+String(value).replaceAll("'","'\"'\"'")+"'";}
function accountSettingsExtensionCommands(item,key){
 const source=accountSettingsExtensionSource(item),provider=accountSettingsExtensionProvider(item),exe=source.runtime?.executable||({codex:'codex','claude-code':'claude'}[provider]);if(!exe||!['codex','claude-code'].includes(provider)||key==='skills'||item._settingsStale||['error','loading'].includes(S.settingsExtensionsState))return [];
 const binary=accountExtensionShellArgument(exe),id=accountExtensionShellArgument(item.id||item.name||'');if(!item.id&&!item.name)return [];
 if(key==='available_plugins'&&(source.ready!==true||source.read_states?.plugins!=='ready'))return [];
 if(key==='available_plugins')return [{label:'安装插件',command:binary+' plugin '+(provider==='codex'?'add':'install')+' -- '+id},{label:'查看管理方式',command:binary+' plugin --help'}];
 if(key==='plugins')return [{label:'查看管理方式',command:binary+' plugin --help'},...(provider==='claude-code'?[{label:item.enabled===false?'启用插件':'停用插件',command:binary+' plugin '+(item.enabled===false?'enable':'disable')+' -- '+id}]:[]),{label:'卸载插件',command:binary+' plugin '+(provider==='codex'?'remove':'uninstall')+' -- '+id}];
 return [{label:'查看连接配置',command:binary+' mcp get -- '+id},...(accountSettingsExtensionStatus(item,key)==='需要登录'?[{label:'登录此连接',command:binary+' mcp login -- '+id}]:[]),{label:'查看管理方式',command:binary+' mcp --help'}];
}
function accountSettingsExtensionIdentity(item){return JSON.stringify([String(item.channel_id),String(item.id||item.name),String(item.plugin_id||'')]);}
function accountSettingsExtensionDetail(key,index){
 const item=S.settingsExtensions?.[key]?.[index];if(!item)return;if(key!=='skills'){const view=accountToolsView();view.listScroll=document.getElementById('settingsPanel')?.scrollTop||0;view.detail={key,identity:accountSettingsExtensionIdentity(item)};accountSettingsPaint();document.getElementById('settingsPanel').scrollTop=0;document.querySelector('.settings-tools-back')?.focus({preventScroll:true});return;}const detail={key,identity:accountSettingsExtensionIdentity(item),context:accountTeamContext(),token:(S.settingsExtensionDialogSequence||0)+1};S.settingsExtensionDialogSequence=detail.token;S.settingsExtensionDetail=detail;accountPaintSettingsExtensionDetail(detail);
}
function accountPaintSettingsExtensionDetail(detail){
 if(S.settingsExtensionDetail!==detail||detail.context!==accountTeamContext())return;
 if(detail.key==='skills'){accountToolsSkillDialog(detail);return;}
 const item=S.settingsExtensions?.[detail.key]?.find(row=>accountSettingsExtensionIdentity(row)===detail.identity),source=item&&accountSettingsExtensionSource(item),status=item&&(['error','loading'].includes(S.settingsExtensionsState)||item._settingsStale?'未更新':detail.key==='available_plugins'?'待安装':accountSettingsExtensionStatus(item,detail.key)),commands=item?accountSettingsExtensionCommands(item,detail.key):[];detail.commands=commands;
 const parent=item?.plugin_id&&(S.settingsExtensions?.plugins||[]).find(row=>String(row.channel_id)===String(item.channel_id)&&row.id===item.plugin_id);detail.resource=detail.key==='plugins'?item:parent;
 const origin=item?.source==='system'?'系统技能':item?.source==='project'?'项目技能':item?.source==='personal'?'个人技能':parent?'来自插件 '+(parent.display_name||parent.name||parent.id):'';
 const facts=item?[item.channel_name||source?.name||providerDefinition(accountSettingsExtensionProvider(item))?.label,status,origin,item.version?'版本 '+item.version:''].filter(Boolean):[];
 const content=!item?'<p>此扩展已不在当前清单中。</p>':`<p>${esc(item.description||'暂无简介')}</p>${facts.map(value=>'<p class="settings-footnote">'+esc(value)+'</p>').join('')}${detail.key==='skills'?'<p class="settings-footnote">原生技能由 Agent 自动发现，此处只读。</p>':''}${S.settingsExtensionsState==='error'||item._settingsStale?'<p class="settings-inline-error" role="alert">清单未更新，请重新读取后再管理。</p>':''}${commands.length?'<p>'+(detail.key==='mcp_servers'&&status==='需要登录'?'请在对应 Agent 中完成登录，然后重新读取。':'在对应 Agent 的终端中执行，完成后重新读取。')+'</p>':''}${commands.map((command,index)=>`<p>${esc(command.label)} <button class="btn" aria-label="复制${esc(command.label)}命令" onclick="accountCopySettingsExtensionCommand(${detail.token},${index})">复制命令</button></p><code class="install-command">${esc(command.command)}</code>`).join('')}`;
 const host=openChildDialog({manageFocus:true,className:'settings-extension-dialog',title:item?.display_name||item?.name||item?.id||'扩展详情',attrs:'role="dialog" aria-modal="true" onkeydown="accountSettingsExtensionKeydown(event)" data-settings-extension-dialog="'+detail.token+'"',body:content+'<p id="settingsExtensionCopyStatus" class="settings-footnote" role="status"></p>',footer:`${detail.resource?.has_resources&&!item?._settingsStale?`<button class="btn" onclick="accountSettingsExtensionResources(${detail.token})">打开资源</button>`:''}<button class="btn" onclick="accountRecheckSettingsExtension(${detail.token})" ${S.settingsExtensionsState==='loading'?'disabled':''}>重新读取</button><button class="btn" onclick="closeChildDialog()">关闭</button>`});
 if(host){const index=S.settingsExtensions?.[detail.key]?.findIndex(row=>accountSettingsExtensionIdentity(row)===detail.identity),action="accountSettingsExtensionDetail('"+detail.key+"',"+index+")",anchor=[...document.querySelectorAll('#settingsPanel button')].find(button=>button.getAttribute('onclick')===action)||document.querySelector('.settings-sidebar [data-settings-tab="tools"]');if(anchor)host._returnFocus=anchor;}
}
function accountSettingsExtensionKeydown(event){if(event.key==='Escape'&&!event.isComposing){event.preventDefault();event.stopPropagation();if(document.getElementById('popmenu'))closePop();else closeChildDialog();}}
function accountSettingsExtensionDocumentKeydown(event){if(document.querySelector('[data-settings-extension-dialog]'))accountSettingsExtensionKeydown(event);}
function accountSettingsExtensionDialogCurrent(token){const detail=S.settingsExtensionDetail;return detail?.token===token&&detail.context===accountTeamContext()&&!!document.querySelector('[data-settings-extension-dialog="'+token+'"]')?detail:null;}
async function accountCopySettingsExtensionCommand(token,index){const detail=accountSettingsExtensionDialogCurrent(token),command=detail?.commands?.[index]?.command;if(!command)return;try{await navigator.clipboard.writeText(command);if(accountSettingsExtensionDialogCurrent(token)){const status=document.getElementById('settingsExtensionCopyStatus');if(status)status.textContent='命令已复制';}}catch(error){if(accountSettingsExtensionDialogCurrent(token)){const status=document.getElementById('settingsExtensionCopyStatus');if(status)status.textContent='管理命令未能复制。请手动选择并复制原命令。';}}}
async function accountRecheckSettingsExtension(token){const detail=accountSettingsExtensionDialogCurrent(token);if(!detail)return;const pending=accountReadSettingsExtensions(true);accountPaintSettingsExtensionDetail(detail);await pending;if(accountSettingsExtensionDialogCurrent(token))accountPaintSettingsExtensionDetail(detail);}
function accountSettingsExtensionResources(token){const detail=accountSettingsExtensionDialogCurrent(token),item=detail?.resource;if(!item?.has_resources)return;S.environment=S.settingsExtensions;openInstalledPluginResources(item.channel_id,item.id);document.querySelector('.core-package-resources-modal')?.setAttribute('data-settings-tools-resource','');}

function accountSettingsLink(label,path){return `<a class="settings-row settings-link" href="https://runteams.ai${path}" target="_blank" rel="noopener noreferrer"><b>${label}</b>${ICON('chev')}</a>`;}


function accountSettingsReadAppInfo(){
 if(S.settingsAppInfoRead)return S.settingsAppInfoRead;
 S.settingsAppInfoRead=(async()=>{
  try{const value=await api('/api/app-info');if(value&&!value.error&&/^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(String(value.version||'')))S.appInfo={...value,version:displayAppVersion(value.version)};}
  catch(error){}
  finally{S.settingsAppInfoRead=null;if(S.settingsTab==='about')accountSettingsPaint();}
 })();return S.settingsAppInfoRead;
}
function accountSettingsLoadTab(){const tab=S.settingsTab;if(tab==='about')accountSettingsReadAppInfo();if(tab==='channels')refreshSettingsChannels();if(tab==='tools')accountReadSettingsExtensions();globalThis.RunTeamsOfficialUI?.loadSettingsTab(tab);}
function accountNativeSettingsBridge(){return window.webkit?.messageHandlers?.runteamsSettings;}
function accountNativeNotificationStatus(value){if(!value||!['default','granted','denied'].includes(value.notification_permission)||typeof value.notification_alerts!=='boolean'||typeof value.notification_sound!=='boolean')return;S.nativeSettings={...S.nativeSettings,...value};if(['granted','denied'].includes(value.notification_permission)){S.notificationPermissionError='';S.notificationPermissionRetry='';}if(S.settingsTab==='notifications')accountSettingsPaint();}
async function accountReadNativeSettings(){const bridge=accountNativeSettingsBridge();if(!bridge||S.nativeSettingsLoading||S.nativeSettingsSaving)return;S.nativeSettingsLoading=true;accountSettingsPaint();try{const value=await bridge.postMessage({action:'get',workspace:S.activeOrganization||''});if(!value||typeof value.prevent_sleep!=='boolean'||typeof value.launch_at_login!=='boolean'||!['background','quit'].includes(value.close_action))throw Error('本机设置未确认');S.nativeSettings=value;S.nativeSettingsError='';S.nativeSettingsRetry=null;if(['default','granted','denied'].includes(value.notification_permission)){S.notificationPermissionError='';S.notificationPermissionRetry='';}}catch(error){S.nativeSettingsError='本机设置暂时无法读取';}finally{S.nativeSettingsLoading=false;accountSettingsStartRuntimeMonitor();accountSettingsPaint();}}
async function accountSaveNativeSetting(key,value){const bridge=accountNativeSettingsBridge();if(!bridge||S.nativeSettingsSaving||S.nativeSettingsLoading||S.nativeSettingsError)return;S.nativeSettingsSaving=true;S.nativeSettingsError='';S.nativeSettingsRetry={key,value};accountSettingsPaint();try{const result=await bridge.postMessage({action:'set',key,value});if(!result||typeof result.prevent_sleep!=='boolean'||typeof result.launch_at_login!=='boolean'||!['background','quit'].includes(result.close_action)||result[key]!==value)throw Error('设置未确认');S.nativeSettings=result;S.nativeSettingsRetry=null;}catch(error){S.nativeSettingsError='本机设置未能保存，请重试。';}finally{S.nativeSettingsSaving=false;accountSettingsStartRuntimeMonitor();accountSettingsPaint();}}
function accountSettingsStartRuntimeMonitor(){if(accountNativeSettingsBridge()){accountNotifyNativeReady();return;}if(S.settingsRuntimeTimer)return;S.settingsRuntimeTimer=setInterval(accountPollWorkSettings,5000);accountPollWorkSettings();}
async function accountPollWorkSettings(){
 if(accountNativeSettingsBridge()||S.settingsRuntimeReading||!S.account.signed_in||S.settingsPreferencesState!=='ready')return;
 if(typeof Notification==='undefined'||Notification.permission!=='granted'){S.notificationCursor=null;return;}
 const context=accountTeamContext()+':'+(S.activeOrganization||'');S.settingsRuntimeReading=true;
 try{const suffix=S.notificationCursor?'?cursor='+encodeURIComponent(JSON.stringify(S.notificationCursor)):'';const value=await api('/api/desktop/notifications'+suffix);
  if(context!==accountTeamContext()+':'+(S.activeOrganization||''))return;
  if(value.error||value.schema!==1||value.actor!==String(S.account.user_id)||!value.cursor||!value.preferences||!Array.isArray(value.events))throw Error('提醒读取失败');
  const prefs=value.preferences;S.browserNotificationSeen=S.browserNotificationSeen||new Set();
  for(const event of value.events){if(S.browserNotificationSeen.has(event.id)||prefs.notification_timing==='never'||prefs.notification_timing==='background'&&!document.hidden||!prefs[event.kind])continue;
   const notification=new Notification(event.title,{body:'打开 RunTeams.ai 查看并处理。',tag:event.id,silent:!prefs.sound});notification.onclick=()=>{window.focus();accountOpenWorkNotification(event.target);notification.close();};S.browserNotificationSeen.add(event.id);
  }
  S.notificationCursor=value.cursor;S.notificationDeliveryError='';if(S.browserNotificationSeen.size>2000)S.browserNotificationSeen.clear();
 }catch(error){S.notificationDeliveryError='工作提醒暂时不可用，请重试。';}
 finally{S.settingsRuntimeReading=false;if(S.settingsTab==='notifications')accountSettingsPaint();}
}


function accountSettingsChannelInstall(id,mode='install'){
 const channel=S.channels.find(row=>Number(row.id)===Number(id));if(!channel)return;
 const update=mode==='update',name=channel.provider_label||channel.name,guide=channel.provider==='codex'?'https://developers.openai.com/codex/cli/':'https://code.claude.com/docs/en/setup';
 openChildDialog({manageFocus:true,title:(update?'更新 ':'安装并登录 ')+name+(update?' CLI':''),attrs:'role="dialog" aria-modal="true"',body:'<p>'+(update?'请按原安装方式，依照官方说明更新 CLI。完成后返回这里重新检测版本与连接。':'请按官方说明完成安装和登录，再返回这里检测。')+'</p><a class="btn" href="'+guide+'" target="_blank" rel="noopener noreferrer">查看官方'+(update?'更新':'安装')+'说明</a>',footer:`<button class="btn" onclick="closeChildDialog()">关闭</button><button class="btn" onclick="closeChildDialog();checkChannelLogin(${Number(id)})">重新检测</button>`});
}

function accountRefreshModelDefaults(){const region=document.querySelector('#settingsModelDefaults .settings-row-group');if(region){const next=region.cloneNode(false);next.innerHTML=accountSettingsNotice()+accountModelDefaults();accountChannelReconcile(region,next);}}

function accountChannelDiagnostic(label,detail,id,kind='status'){
 if(!detail)return `<span>${esc(label)}</span>`;
 return `<details class="channel-diagnostic" data-channel-detail="${esc(String(id)+'-'+kind)}"><summary>${esc(label)}${ICON('chev')}</summary><p>${esc(detail)}</p></details>`;
}

// Subscription payments use cloud receipts; no browser state grants access.


if(typeof window!=='undefined')window.addEventListener?.('focus',()=>{if(S.settingsTab==='notifications'&&document.getElementById('settingsWorkspace'))accountReadNativeSettings();});

/* module-function:accountChannelConnected */
function accountChannelConnected(channel){return modelChannelAvailable(channel);}

/* module-function:accountChannelIdentity */
function accountChannelIdentity(channel){const parts=String(channel?.probe?.account||'').split(/\s*[·\u2002]\s*/).map(value=>value.trim()).filter(Boolean);return {email:parts[0]||'',plan:parts.slice(1).join(' ')};}

/* module-function:accountChannelMenu */
function accountChannelMenu(event,id){
 event.preventDefault();event.stopPropagation();const channel=S.channels.find(row=>Number(row.id)===Number(id)),anchor=event.currentTarget;
 if(!channel||anchor.disabled||channel.probe?.status==='missing')return;
 const connected=accountChannelConnected(channel),identity=accountChannelIdentity(channel),context=accountTeamContext(),current=()=>context===accountTeamContext()&&S.channels.includes(channel);
 const items=[];
 if(connected){if(identity.email||identity.plan){items.push({head:true,account:true,label:identity.email,plan:identity.plan},{divider:true});}items.push({label:'断开',icon:'unlink',danger:true,fn:()=>{if(current()&&channel.enabled)removeChannel(id);}});}
 items.push({label:'更新 CLI',icon:'refresh',fn:()=>{if(current())accountSettingsChannelInstall(id,'update');}});
 openMenu(anchor,items,{variant:'channelAccount',align:'right'});
 const menu=document.getElementById('popmenu');if(menu?.classList.contains('channel-account-menu')){menu.dataset.channelId=String(channel.id);menu.dataset.identity=JSON.stringify([connected,identity]);menu.setAttribute('aria-label',(channel.provider_label||channel.name)+'的更多操作');(event.type==='keydown'?menu.querySelector('a[data-i]'):menu)?.focus({preventScroll:true});}
}

/* module-function:accountChannelMenuKey */
function accountChannelMenuKey(event,id){if(event.isComposing||event.currentTarget.disabled||!['ArrowDown','ArrowUp','Enter',' '].includes(event.key))return;if(document.getElementById('popmenu')&&_popAnchor===event.currentTarget)return;accountChannelMenu(event,id);}

/* module-function:accountConnectChannel */
async function accountConnectChannel(id){
 const channel=S.channels.find(row=>Number(row.id)===Number(id));if(!channel||channel.connecting||channel.removing||channel.loginProbeBusy)return;
 if(channel.removeUnknown){await removeChannel(id);return;}
 if(channel.statusReadError){await checkChannelLogin(id);if(channel.statusReadError)toast('当前连接状态暂时无法确认，请稍后重试。','err');return;}
 if(channel.loginPending){accountChannelLoginHelp(id);return;}
 await connectChannel(id);
}

/* module-function:accountChannelLoginHelp */
function accountChannelLoginHelp(id){
 const channel=S.channels.find(row=>Number(row.id)===Number(id));if(!channel?.loginPending)return;
 openChildDialog({manageFocus:true,className:'channel-login-dialog',title:'登录 '+(channel.provider_label||channel.name),attrs:'role="dialog" aria-modal="true" data-channel-login="'+Number(id)+'"',body:`<p>在终端完成登录，返回后会自动检测。</p><div class="channel-login-command"><code>${esc(channel.login_command||'')}</code><button type="button" class="btn" onclick="copyChannelLoginCommand(${Number(id)})">复制命令</button></div>`,footer:`<button class="btn" onclick="closeChildDialog()">关闭</button><button class="btn" onclick="closeChildDialog();checkChannelLogin(${Number(id)})">重新检测</button>`});
}

/* module-function:accountChannelReconcile */
function accountChannelReconcile(current,next){
 if(current.nodeType!==next.nodeType||current.nodeName!==next.nodeName){current.replaceWith(next.cloneNode(true));return;}
 if(current.nodeType===Node.TEXT_NODE){if(current.data!==next.data)current.data=next.data;return;}
 if(current.nodeType!==Node.ELEMENT_NODE)return;
 const open=current===_popAnchor&&!!document.querySelector('.channel-account-menu');
 for(const a of [...current.attributes])if(!next.hasAttribute(a.name)&&!(open&&['aria-expanded','data-menu-open'].includes(a.name)))current.removeAttribute(a.name);
 for(const a of next.attributes)if(!(open&&['aria-expanded','data-menu-open'].includes(a.name))&&current.getAttribute(a.name)!==a.value)current.setAttribute(a.name,a.value);
 const key=node=>node.nodeType===Node.ELEMENT_NODE?(node.id||node.getAttribute('data-channel-id')):'';
 for(let i=0;i<next.childNodes.length;i++){const wanted=next.childNodes[i];let node=current.childNodes[i],id=key(wanted);
  if(id&&key(node||{})!==id){const existing=[...current.childNodes].find(n=>key(n)===id);if(existing){current.insertBefore(existing,node||null);node=existing;}else{current.insertBefore(wanted.cloneNode(true),node||null);continue;}}
  if(node)accountChannelReconcile(node,wanted);else current.appendChild(wanted.cloneNode(true));
 }
 while(current.childNodes.length>next.childNodes.length)current.lastChild.remove();
}

function accountAboutSettings(){
 const version=accountSettingsGroup('应用版本',accountSettingsRow('RunTeams.ai','',`版本 ${esc(S.appInfo?.version||APP_RELEASE_VERSION)}`));
 return `${settingsPageHead('关于')}${version}${accountSettingsGroup('法律与隐私',accountSettingsLink('隐私政策','/privacy')+accountSettingsLink('服务条款','/terms'))}`;
}

function accountWorkspaceReadOnly(){const value=S.account?.active_workspace;return !!S.activeOrganization&&value?.id===S.activeOrganization&&(value.readonly===true||value.authority_unknown===true);}
