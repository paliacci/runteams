import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {DocumentApp} from './main.jsx';
import {EditorLanguage} from './editor-locale.js';
import {send} from './host-bridge.js';
export function Host(){
 const [payload,setPayload]=useState(null);
 const [language,setLanguage]=useState('zh-CN');
 const english=language==='en';
 useEffect(()=>{
  const listener=event=>{const data=event.data;if(event.source!==parent||event.origin!==location.origin||data?.channel!=='runteams-rich-document/1'||data.token!==location.hash.slice(1))return;
   if(data.type==='theme'){document.documentElement.dataset.theme=data.theme;setPayload(previous=>previous?{...previous,theme:data.theme}:previous);}
   if(data.type==='language'||data.type==='open'){
    const next=(data.type==='open'?data.payload.language:data.language)==='en'?'en':'zh-CN';
    setLanguage(next);document.documentElement.lang=next;document.title=next==='en'?'Document':'文档';
   }
   if(data.type==='open'){setPayload(data.payload);document.documentElement.dataset.theme=data.payload.theme||'light';}
  };
  window.addEventListener('message',listener);send('ready',{protocol:2,render_ack:true});
  const links=event=>{const link=event.target.closest?.('a[href]');if(!link)return;const href=link.getAttribute('href')||'';if(href.startsWith('#'))return;if(href.startsWith('blob:')&&link.dataset.documentAssetDownload==='true')return;
   let url;try{url=new URL(href,location.origin);}catch{return;}
   const internal=/^runteams:\/\/document\//.test(href)||url.origin===location.origin;
   if(!internal&&['http:','https:','mailto:'].includes(url.protocol)){if(link.closest('.bn-inline-content')&&!link.closest('[contenteditable="false"]')&&link.closest('.bn-editor[contenteditable="true"]')&&!event.metaKey&&!event.ctrlKey){event.preventDefault();return;}link.target='_blank';link.rel='noopener noreferrer';return;}
   event.preventDefault();send('link',{href});
  };
  document.addEventListener('click',links,true);const size=new ResizeObserver(()=>send('height',{height:document.body.scrollHeight}));size.observe(document.body);
  return()=>{window.removeEventListener('message',listener);document.removeEventListener('click',links,true);size.disconnect();};
 },[]);
 useEffect(()=>{if(payload?.doc?.host_protocol===2)send('rendered');},[payload?.doc]);
 if(payload&&payload.doc?.host_protocol!==2)return <div className="loading" role="status"><p>{english?'Refresh the app to open this document.':'请刷新应用后再打开文档。'}</p><button type="button" className="primary" onClick={()=>parent.location.reload()}>{english?'Refresh App':'刷新应用'}</button></div>;
 return payload?<EditorLanguage.Provider value={language}><DocumentApp payload={payload}/></EditorLanguage.Provider>:<div className="loading" role="status">{english?'Opening document…':'正在打开文档…'}</div>;
}
if(document.getElementById('root'))createRoot(document.getElementById('root')).render(<Host/>);
