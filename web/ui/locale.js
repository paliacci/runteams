/* Desktop language foundation: device preference, keyed messages and opt-in DOM.
 * No requests, route changes, document reloads or translation of authored content.
 * The public website has its own independent language preference and catalogs. */
(() => {
 'use strict';
 const storageKey='runteams_language_preference',fallback='zh-CN';
 const valid=value=>['system','zh-CN','en'].includes(value);
 const catalogs=Object.create(null),listeners=new Set();
 const has=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
 function loadPreference(){try{const value=localStorage.getItem(storageKey);return valid(value)?value:'system';}catch{return 'system';}}
 function resolve(value){
  if(value!=='system')return value;
  for(const language of navigator.languages?.length?navigator.languages:[navigator.language||'']){
   if(/^zh(?:-|$)/i.test(language))return 'zh-CN';
   if(/^en(?:-|$)/i.test(language))return 'en';
  }
  return 'en';
 }
 let preference=loadPreference(),language=resolve(preference);
 function register(locale,messages){
  if(!['zh-CN','en'].includes(locale)||!messages||typeof messages!=='object'||Array.isArray(messages))throw new TypeError('Invalid locale catalog');
  const target=catalogs[locale]||(catalogs[locale]=Object.create(null));
  for(const [key,value]of Object.entries(messages)){if(typeof value!=='string')throw new TypeError('Locale messages must be strings');target[key]=value;}
  if(document.readyState!=='loading')apply(document);
 }
 function messageLocale(key){return has(catalogs[language]||{},key)?language:has(catalogs[fallback]||{},key)?fallback:null;}
 function t(key,parameters={},defaultText=key){
  const locale=messageLocale(key),value=locale?catalogs[locale][key]:defaultText;
  return String(value).replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g,(token,name)=>has(parameters,name)&&['string','number'].includes(typeof parameters[name])?String(parameters[name]):token);
 }
 const targets={'data-app-i18n':null,'data-app-i18n-title':'title','data-app-i18n-aria-label':'aria-label','data-app-i18n-placeholder':'placeholder','data-app-i18n-data-placeholder':'data-placeholder'};
 const selector=Object.keys(targets).map(key=>'['+key+']').join(',');
 function apply(root){
  if(!root)return;
  const nodes=[...(root.matches?.(selector)?[root]:[]),...(root.querySelectorAll?.(selector)||[])];
  for(const node of nodes){
   if(node.closest('[translate="no"],[data-app-i18n-ignore]'))continue;
   let parameters={};
   try{const value=JSON.parse(node.getAttribute('data-app-i18n-vars')||'{}');if(value&&typeof value==='object'&&!Array.isArray(value))parameters=value;}catch{}
   for(const [marker,attribute]of Object.entries(targets)){
    const key=node.getAttribute(marker);if(!key||!messageLocale(key))continue;
    const value=t(key,parameters);
    if(attribute){if(node.getAttribute(attribute)!==value)node.setAttribute(attribute,value);}
    else if(!node.matches('input,textarea,[contenteditable]')){
     // Text-only opt-in labels: replacing a label never replaces a control or
     // its event handlers. Never put this marker on a mixed-content container.
     if(node.textContent!==value)node.textContent=value;
     node.lang=messageLocale(key);
    }
   }
  }
 }
 function publish(previous,source){
  document.documentElement.dataset.appLanguage=language;
  document.documentElement.dataset.appLanguagePreference=preference;
  // Most pages still use their approved Chinese source copy during rollout.
  // Their document language stays truthful; opted-in labels declare their own.
  apply(document);
  const detail=Object.freeze({preference,language,previousLanguage:previous,source});
  for(const listener of listeners)try{listener(detail);}catch(error){console.error('Language listener failed',error);}
  window.dispatchEvent(new CustomEvent('runteams:languagechange',{detail}));
 }
 function setPreference(value){
  if(!valid(value))throw new RangeError('Unsupported language preference');
  let persisted=true;try{localStorage.setItem(storageKey,value);persisted=localStorage.getItem(storageKey)===value;}catch{persisted=false;}
  const previous=language;preference=value;language=resolve(value);publish(previous,'selection');
  return Object.freeze({preference,language,persisted});
 }
 function sync(source){const previous=language;preference=loadPreference();language=resolve(preference);publish(previous,source);}
 const api={storageKey,fallback,t,register,apply,messageLocale,setPreference,
  get preference(){return preference;},get language(){return language;},
  onChange(listener){if(typeof listener!=='function')throw new TypeError('Expected a language listener');listeners.add(listener);return()=>listeners.delete(listener);},
  formatNumber(value,options){return new Intl.NumberFormat(language,options).format(value);},
  formatDate(value,options){return new Intl.DateTimeFormat(language,options).format(value);}
 };
 window.RunTeamsLocale=Object.freeze(api);
 for(const [locale,messages]of Object.entries(globalThis.RUNTEAMS_LOCALES||{}))register(locale,messages);
 document.documentElement.dataset.appLanguage=language;
 document.documentElement.dataset.appLanguagePreference=preference;
 window.addEventListener('storage',event=>{if(event.key===storageKey||event.key===null)sync('storage');});
 window.addEventListener('languagechange',()=>{if(preference==='system'){const previous=language;language=resolve(preference);publish(previous,'system');}});
 function start(){
  apply(document);
  const observer=new MutationObserver(records=>{
   for(const record of records)if(record.type==='attributes')apply(record.target);else for(const node of record.addedNodes)if(node.nodeType===1)apply(node);
  });
  observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:[...Object.keys(targets),'data-app-i18n-vars']});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
