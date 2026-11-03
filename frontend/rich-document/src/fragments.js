import {editorContext,walkBlocks,blockLabel,separateHistory} from './editor-context.js';
import {packAsset,unpackAsset} from './asset-store.js';
import {request} from './host-bridge.js';
export const fragmentSchema='runteams.block-fragment/1';
const clone=value=>JSON.parse(JSON.stringify(value));
export async function captureFragment(editor,blocks){
 const context=editorContext(editor),sources=Object.create(null),assets=Object.create(null),ids=new Set();
 walkBlocks(blocks,b=>{if(b.props?.source){const value=context.getSources()[b.props.source];if(!value)throw Error('数据来源缺失，未复制不完整的内容。');sources[b.props.source]=clone(value);}if(b.props?.assetId)ids.add(b.props.assetId);});
 await Promise.all([...ids].map(async id=>assets[id]=await packAsset(id)));
 return {schema:fragmentSchema,documentId:String(context.documentId),blocks:clone(blocks),sources,assets};
}
export function validateFragment(fragment,editor){
 if(fragment?.schema!==fragmentSchema||!Array.isArray(fragment.blocks)||!fragment.blocks.length||!fragment.sources||!fragment.assets)throw Error('内容格式不完整。');
 let count=0;walkBlocks(fragment.blocks,b=>{if(++count>1000||!editor.schema.blockSchema[b.type])throw Error('包含当前编辑器不支持的内容。');if(b.props?.source&&!Object.hasOwn(fragment.sources,b.props.source))throw Error('数据来源缺失。');if(b.props?.assetId&&!Object.hasOwn(fragment.assets,b.props.assetId))throw Error('附件缺失。');});return fragment;
}
export function cloneFragment(fragment,destinationSources,documentId){
 const blocks=clone(fragment.blocks),sources=clone(fragment.sources),blockIds=new Map(),sourceIds=new Map(),dataKeys=new Map();
 walkBlocks(blocks,b=>{if(b.id)blockIds.set(b.id,crypto.randomUUID());});
 for(const key of Object.keys(sources)){let next=key;if(Object.hasOwn(destinationSources,key)&&JSON.stringify(destinationSources[key])!==JSON.stringify(sources[key]))next=crypto.randomUUID();sourceIds.set(key,next);}
 const remapReference=props=>{if((!props.documentId||props.documentId===String(fragment.documentId??documentId))&&blockIds.has(props.blockId)){props.blockId=blockIds.get(props.blockId);props.documentId=String(documentId);}};
 walkBlocks(blocks,b=>{if(b.id)b.id=blockIds.get(b.id);if(b.props?.source)b.props.source=sourceIds.get(b.props.source);if(b.props?.dataKey){if(!dataKeys.has(b.props.dataKey))dataKeys.set(b.props.dataKey,crypto.randomUUID());b.props.dataKey=dataKeys.get(b.props.dataKey);}if(b.type==='reference')remapReference(b.props);if(Array.isArray(b.content))for(const inline of b.content)if(inline.type==='blockReference')remapReference(inline.props);});
 return {blocks,sources:Object.fromEntries(Object.entries(sources).map(([key,value])=>[sourceIds.get(key),value]))};
}
export async function insertFragment(editor,fragment,anchorId){
 validateFragment(fragment,editor);const context=editorContext(editor);if(!editor.isEditable||!editor.getBlock(anchorId)||context.isActive?.()===false)throw Error('插入位置已变化，请重新选择。');
 const assetIds=new Map();
 await Promise.all(Object.entries(fragment.assets).map(async([id,asset])=>{const saved=await unpackAsset(null,asset);assetIds.set(id,saved.id);}));
 if(!editor.isEditable||!editor.getBlock(anchorId)||context.isActive?.()===false)throw Error('插入位置已变化，请重新选择。');
 const next=cloneFragment(fragment,context.getSources(),context.documentId),previous=context.getSources();walkBlocks(next.blocks,b=>{if(b.props?.assetId)b.props.assetId=assetIds.get(b.props.assetId);});context.setSources({...previous,...next.sources});
 try{separateHistory(editor);editor.insertBlocks(next.blocks,anchorId,'after');separateHistory(editor);context.changed();return next.blocks;}catch(error){context.setSources(previous);throw error;}
}
function textFor(block,sources){
 let text=blockLabel(block);if(block.type==='metric')text=block.props.value+' '+block.props.label;
 if(block.type==='jsonData')text+='\n'+JSON.stringify(sources[block.props.source]?.data,null,2);
 if(['dataTable','barChart'].includes(block.type)){let value;try{value=block.props.data?JSON.parse(block.props.data):sources[block.props.source]?.data;}catch{}text+='\n'+JSON.stringify(value,null,2);}
 if(block.type==='table')text=block.content.rows.map(row=>row.cells.map(cell=>Array.isArray(cell)?cell.map(n=>n.text||'').join(''):cell?.content?.map(n=>n.text||'').join('')||String(cell||'')).join('\t')).join('\n');
 if(Array.isArray(block.content))text=block.content.map(n=>n.text||n.props?.label||n.content?.map?.(x=>x.text||'').join('')||'').join('');
 return text+(block.children?.length?'\n'+block.children.map(b=>textFor(b,sources)).join('\n'):'');
}
export function clipboardPayload(fragment){
 const json=JSON.stringify(fragment),bytes=new TextEncoder().encode(json),chunks=[];for(let i=0;i<bytes.length;i+=8192)chunks.push(String.fromCharCode(...bytes.subarray(i,i+8192)));const encoded=btoa(chunks.join(''));
 const text=fragment.blocks.map(b=>textFor(b,fragment.sources)).join('\n'),escape=value=>value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
 return {text,html:`<div data-runteams-fragment="${encoded}"><pre>${escape(text)}</pre></div>`};
}
export async function writeFragment(fragment){
 const {text,html}=clipboardPayload(fragment);
 if(!navigator.clipboard?.write||typeof ClipboardItem==='undefined')throw Error('当前浏览器无法复制完整内容，请使用导出文档。');
 await navigator.clipboard.write([new ClipboardItem({'text/plain':new Blob([text],{type:'text/plain'}),'text/html':new Blob([html],{type:'text/html'})})]);
}
export async function copyBlock(editor,id,cut=false){
 const block=editor.getBlock(id);if(!block||!editor.isEditable)throw Error('当前内容已变化，请重新选择。');const snapshot=JSON.stringify(block),fragment=await captureFragment(editor,[block]);await writeFragment(fragment);
 if(cut){if(!editor.isEditable||editorContext(editor).isActive?.()===false||JSON.stringify(editor.getBlock(id))!==snapshot)throw Error('内容已复制，但原内容已变化，因此没有剪切。');separateHistory(editor);editor.removeBlocks([id]);separateHistory(editor);}
}
export function readClipboardFragment(html){
 if(!html)return null;if(html.length>64*1024*1024)throw Error('复制的内容过大，请使用导出文档。');const root=new DOMParser().parseFromString(html,'text/html'),encoded=root.querySelector('[data-runteams-fragment]')?.getAttribute('data-runteams-fragment');
 if(!encoded)return null;try{return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(encoded),c=>c.charCodeAt(0))));}catch{throw Error('复制的内容不完整，请重新复制。');}
}
export function handleFragmentPaste({event,editor}){
 let fragment;try{fragment=readClipboardFragment(event.clipboardData?.getData('text/html'));}catch(error){editorContext(editor).report(error.message);return true;}
 if(!fragment)return undefined;const anchor=editor.getTextCursorPosition().block.id;
 insertFragment(editor,fragment,anchor).catch(error=>editorContext(editor).report(error.message));return true;
}
export async function exportRecord(editor,record){const fragment=await captureFragment(editor,record.blocks);return {...record,assets:fragment.assets};}
export async function readTemplates(){return (await request('templates-read')).templates;}
export async function readTemplate(id){return (await request('template-read',{id})).fragment;}
export async function saveTemplate(name,fragment){return request('template-save',{name,fragment});}
