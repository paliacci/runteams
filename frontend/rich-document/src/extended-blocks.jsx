import React,{useEffect,useState} from 'react';
import {createReactBlockSpec,createReactInlineContentSpec} from '@blocknote/react';
import {defaultProps} from '@blocknote/core';
import {Info,Image as ImageIcon,Paperclip,Download,Pencil,Link2} from 'lucide-react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import {editorContext,blockLabel,locateBlock} from './editor-context.js';
import {readAsset,downloadAsset} from './asset-store.js';
import './editor-tools.css';

function ReferenceView({props,editor}){
 const [,update]=useState(0);useEffect(()=>editor.onChange(()=>update(n=>n+1)),[editor]);
 const context=editorContext(editor),same=!props.documentId||props.documentId===String(context?.documentId),target=same?editor.getBlock(props.blockId):null;
 const label=target?blockLabel(target):props.label||'块引用',missing=same&&!target;
 const open=()=>{if(same){if(!locateBlock(editor,props.blockId))context?.report('引用的内容已删除。');}else context?.navigate(props.documentId,props.blockId);};
 return <button type="button" contentEditable={false} className="rt-reference" onClick={open} disabled={missing} title={missing?'引用的内容已删除':same?'跳转到引用内容':'打开引用的文档'}><Link2 size={13}/><span>{label}</span>{missing&&<small>已删除</small>}</button>;
}
const referenceProps={documentId:{default:''},blockId:{default:''},label:{default:''}};
export const blockReference=createReactInlineContentSpec({type:'blockReference',propSchema:referenceProps,content:'none'},{render:({inlineContent,editor})=><ReferenceView props={inlineContent.props} editor={editor}/>});
export const reference=createReactBlockSpec({type:'reference',propSchema:referenceProps,content:'none'},{render:({block,editor})=><div className="rt-reference-block"><ReferenceView props={block.props} editor={editor}/></div>})();
export const callout=createReactBlockSpec({type:'callout',propSchema:{...defaultProps},content:'inline'},{render:({contentRef})=><aside className="rt-callout"><Info size={18} contentEditable={false}/><div ref={contentRef} className="rt-callout-content"/></aside>})();
function MathBlock({block,editor}){
 let html='',error='';if(block.props.formula)try{html=katex.renderToString(block.props.formula,{displayMode:true,throwOnError:true,trust:false,strict:'error',maxExpand:500,maxSize:20});}catch{error='公式语法有误，请编辑后重试。';}
 const editing=editorContext(editor)?.editing;
 return <div className="rt-math" contentEditable={false}>{block.props.formula?<>{error?<p role="alert">{error}</p>:<div dangerouslySetInnerHTML={{__html:html}}/>}{editing&&<button className="rt-block-edit" aria-label="编辑公式" title="编辑公式" onClick={e=>editorContext(editor).openTool('math',block.id,{edit:true,rect:e.currentTarget.getBoundingClientRect()})}><Pencil size={14}/></button>}</>:editing?<button onClick={e=>editorContext(editor).openTool('math',block.id,{edit:true,rect:e.currentTarget.getBoundingClientRect()})}>输入公式</button>:<span className="muted">空公式</span>}</div>;
}
export const math=createReactBlockSpec({type:'math',propSchema:{formula:{default:''}},content:'none'},{render:MathBlock})();
function AssetBlock({block,editor}){
 const {assetId,name}=block.props,[url,setURL]=useState(''),[error,setError]=useState('');const context=editorContext(editor),editing=context?.editing;
 useEffect(()=>{let active=true,local='';setURL('');setError('');if(assetId)readAsset(assetId).then(asset=>{if(active){local=URL.createObjectURL(asset.blob);setURL(local);}}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;if(local)URL.revokeObjectURL(local);};},[assetId]);
 const choose=e=>context.openTool(block.type==='image'?'image':'file',block.id,{edit:true,rect:e.currentTarget.getBoundingClientRect()});
 return <figure className={`rt-asset rt-asset-${block.type}`} contentEditable={false}>{assetId?<>{error?<p role="alert">{error}</p>:url?block.type==='image'?<img src={url} alt={name}/>:block.type==='video'?<video src={url} controls preload="metadata" aria-label={name}/>:<button className="rt-attachment" onClick={()=>downloadAsset(assetId).catch(e=>context?.report(e.message))}><Paperclip size={18}/><span>{name}</span><Download size={15}/></button>:<span className="muted">正在读取附件…</span>}{block.type!=='file'&&name&&<figcaption>{name}</figcaption>}{editing&&<button className="rt-block-edit" aria-label="更换附件" title="更换附件" onClick={choose}><Pencil size={14}/></button>}</>:editing?<button onClick={choose}>{block.type==='image'?<ImageIcon size={17}/>:<Paperclip size={17}/>}选择{block.type==='image'?'图片':'文件'}</button>:<span className="muted">附件为空</span>}</figure>;
}
const assetSpec=type=>createReactBlockSpec({type,propSchema:{assetId:{default:''},name:{default:''},mime:{default:''}},content:'none'},{render:AssetBlock})();
export const image=assetSpec('image'),file=assetSpec('file'),video=assetSpec('video');
export const columns=createReactBlockSpec({type:'columns',propSchema:{},content:'none'},{experimental_keyboard:{childrenCanOutdent:false,emptyChildEnter:'stay'},render:()=> <div className="rt-columns-anchor" contentEditable={false}><span>分栏</span></div>})();
export const column=createReactBlockSpec({type:'column',propSchema:{},content:'none'},{meta:{draggable:false,selectable:false},experimental_keyboard:{childrenCanOutdent:false,emptyChildEnter:'stay'},render:()=> <span className="rt-column-anchor" contentEditable={false}/>})();
export const extendedBlocks={callout,reference,math,image,file,video,columns,column};
