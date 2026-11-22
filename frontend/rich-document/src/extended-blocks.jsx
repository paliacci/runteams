import {useCopy,useEditorError} from './editor-locale.js';
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
 const copy=useCopy();
 const [,update]=useState(0);useEffect(()=>editor.onChange(()=>update(n=>n+1)),[editor]);
 const context=editorContext(editor),same=!props.documentId||props.documentId===String(context?.documentId),target=same?editor.getBlock(props.blockId):null;
 const label=target?blockLabel(target):props.label||copy('块引用','Block Reference'),missing=same&&!target;
 const open=()=>{if(same){if(!locateBlock(editor,props.blockId))context?.report(copy('引用的内容已删除。','The referenced block was deleted.'));}else context?.navigate(props.documentId,props.blockId);};
 return <button type="button" contentEditable={false} className="rt-reference" onClick={open} disabled={missing} title={missing?copy('引用的内容已删除','The referenced block was deleted'):same?copy('跳转到引用内容','Go to Referenced Block'):copy('打开引用的文档','Open Referenced Document')}><Link2 size={13}/><span>{label}</span>{missing&&<small>{copy('已删除','Deleted')}</small>}</button>;
}
const referenceProps={documentId:{default:''},blockId:{default:''},label:{default:''}};
export const blockReference=createReactInlineContentSpec({type:'blockReference',propSchema:referenceProps,content:'none'},{render:({inlineContent,editor})=><ReferenceView props={inlineContent.props} editor={editor}/>});
export const reference=createReactBlockSpec({type:'reference',propSchema:referenceProps,content:'none'},{render:({block,editor})=><div className="rt-reference-block"><ReferenceView props={block.props} editor={editor}/></div>})();
export const callout=createReactBlockSpec({type:'callout',propSchema:{...defaultProps},content:'inline'},{render:({contentRef})=><aside className="rt-callout"><Info size={18} contentEditable={false}/><div ref={contentRef} className="rt-callout-content"/></aside>})();
function MathBlock({block,editor}){
 const copy=useCopy();
 let html='',error='';if(block.props.formula)try{html=katex.renderToString(block.props.formula,{displayMode:true,throwOnError:true,trust:false,strict:'error',maxExpand:500,maxSize:20});}catch{error=copy('公式语法有误，请编辑后重试。','Correct the equation syntax and try again.');}
 const editing=editorContext(editor)?.editing;
 return <div className="rt-math" contentEditable={false}>{block.props.formula?<>{error?<p role="alert">{error}</p>:<div dangerouslySetInnerHTML={{__html:html}}/>}{editing&&<button className="rt-block-edit" aria-label={copy("编辑公式","Edit Equation")} title={copy("编辑公式","Edit Equation")} onClick={e=>editorContext(editor).openTool('math',block.id,{edit:true,rect:e.currentTarget.getBoundingClientRect()})}><Pencil size={14}/></button>}</>:editing?<button onClick={e=>editorContext(editor).openTool('math',block.id,{edit:true,rect:e.currentTarget.getBoundingClientRect()})}>{copy("输入公式","Enter Equation")}</button>:<span className="muted">{copy("空公式","Empty equation")}</span>}</div>;
}
export const math=createReactBlockSpec({type:'math',propSchema:{formula:{default:''}},content:'none'},{render:MathBlock})();
function AssetBlock({block,editor}){
 const copy=useCopy(),errorCopy=useEditorError();
 const {assetId,name}=block.props,[url,setURL]=useState(''),[error,setError]=useState('');const context=editorContext(editor),editing=context?.editing;
 useEffect(()=>{let active=true,local='';setURL('');setError('');if(assetId)readAsset(assetId).then(asset=>{if(active){local=URL.createObjectURL(asset.blob);setURL(local);}}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;if(local)URL.revokeObjectURL(local);};},[assetId]);
 const choose=e=>context.openTool(block.type==='image'?'image':'file',block.id,{edit:true,rect:e.currentTarget.getBoundingClientRect()});
 return <figure className={`rt-asset rt-asset-${block.type}`} contentEditable={false}>{assetId?<>{error?<p role="alert">{errorCopy(error)}</p>:url?block.type==='image'?<img src={url} alt={name}/>:block.type==='video'?<video src={url} controls preload="metadata" aria-label={name}/>:<button className="rt-attachment" onClick={()=>downloadAsset(assetId).catch(e=>context?.report(e.message))}><Paperclip size={18}/><span>{name}</span><Download size={15}/></button>:<span className="muted">{copy("正在读取附件…","Loading attachment…")}</span>}{block.type!=='file'&&name&&<figcaption>{name}</figcaption>}{editing&&<button className="rt-block-edit" aria-label={copy("更换附件","Replace Attachment")} title={copy("更换附件","Replace Attachment")} onClick={choose}><Pencil size={14}/></button>}</>:editing?<button onClick={choose}>{block.type==='image'?<ImageIcon size={17}/>:<Paperclip size={17}/>}{block.type==='image'?copy('选择图片','Choose an Image'):copy('选择文件','Choose a File')}</button>:<span className="muted">{copy("附件为空","No attachment")}</span>}</figure>;
}
const assetSpec=type=>createReactBlockSpec({type,propSchema:{assetId:{default:''},name:{default:''},mime:{default:''}},content:'none'},{render:AssetBlock})();
export const image=assetSpec('image'),file=assetSpec('file'),video=assetSpec('video');
function ColumnsBlock(){
 const copy=useCopy();
 return <div className="rt-columns-anchor" contentEditable={false}><span>{copy('分栏','Columns')}</span></div>;
}
export const columns=createReactBlockSpec({type:'columns',propSchema:{},content:'none'},{experimental_keyboard:{childrenCanOutdent:false,emptyChildEnter:'stay'},render:ColumnsBlock})();
export const column=createReactBlockSpec({type:'column',propSchema:{},content:'none'},{meta:{draggable:false,selectable:false},experimental_keyboard:{childrenCanOutdent:false,emptyChildEnter:'stay'},render:()=> <span className="rt-column-anchor" contentEditable={false}/>})();
export const extendedBlocks={callout,reference,math,image,file,video,columns,column};
