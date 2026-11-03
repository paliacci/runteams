import {useEffect} from 'react';
import {send} from './host-bridge.js';

// Navigate the rendered document without changing its blocks, selection or undo history.
export function connectOutline(paper,{publish=send,listen=window}={}){
 let targets=new Map(),headings=[],sequence=0,previous='',scheduled=0,disposed=false;
 const identities=new WeakMap();
 const sync=()=>{
  scheduled=0;if(disposed||!paper.isConnected)return;
  targets=new Map();headings=[];
  for(const node of paper.querySelectorAll('h1,h2,h3,.widget-title-input')){
   if(node===paper.firstElementChild)continue;
   const text=String(node.matches('.widget-title-input')?node.value:node.textContent).replace(/\s+/g,' ').trim();if(!text)continue;
   const block=node.closest('.bn-block[data-id]');
   if(!identities.has(node))identities.set(node,'heading-'+(++sequence));
   const id=block?.dataset.id||identities.get(node);if(targets.has(id))continue;
   targets.set(id,node);headings.push({id,text:text.slice(0,500),level:node.matches('.widget-title-input')?2:Number(node.tagName.slice(1))});
  }
  const root=document.scrollingElement||document.documentElement;
  let active_id='';const atBottom=root.scrollHeight>root.clientHeight&&root.scrollTop+root.clientHeight>=root.scrollHeight-4;
  for(const item of headings){const rect=targets.get(item.id).getBoundingClientRect();if(rect.height>0&&rect.top<=(atBottom?window.innerHeight:72))active_id=item.id;}
  const title=paper.querySelector('.title-input');const name=(title?.value||paper.querySelector(':scope>h1')?.textContent||'文档').trim();
  const next=JSON.stringify({name,items:headings,active_id});if(next!==previous){previous=next;publish('outline',JSON.parse(next));}
 };
 const schedule=()=>{if(!scheduled)scheduled=requestAnimationFrame(sync);};
 const observer=new MutationObserver(schedule);observer.observe(paper,{childList:true,subtree:true,characterData:true});
 const resized=new ResizeObserver(schedule);resized.observe(paper);
 const jump=event=>{
  const data=event.data;if(event.source!==parent||event.origin!==location.origin||data?.channel!=='runteams-rich-document/1'||data.token!==location.hash.slice(1)||data.type!=='outline-jump')return;
  sync();const node=data.id?targets.get(data.id):paper;if(!node)return;
  const root=document.scrollingElement||document.documentElement;
  const top=data.id?root.scrollTop+node.getBoundingClientRect().top-32:0;
  window.scrollTo({top:Math.max(0,top),behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  schedule();
 };
 paper.addEventListener('input',schedule);window.addEventListener('scroll',schedule,true);window.addEventListener('resize',schedule);listen.addEventListener('message',jump);sync();
 return()=>{disposed=true;if(scheduled)cancelAnimationFrame(scheduled);observer.disconnect();resized.disconnect();paper.removeEventListener('input',schedule);window.removeEventListener('scroll',schedule,true);window.removeEventListener('resize',schedule);listen.removeEventListener('message',jump);};
}
export function useDocumentOutline(enabled){
 useEffect(()=>{if(enabled){const paper=document.querySelector('.paper');if(paper)return connectOutline(paper);}},[enabled]);
}
