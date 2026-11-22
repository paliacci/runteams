import {useDocumentOutline} from './outline.js';
import React,{createContext,useContext,useEffect,useMemo,useRef,useState} from 'react';
import {CompactEditorMenus} from './compact-menus.jsx';
import {createAutosave} from './autosave.js';
import {BlockNoteSchema,defaultBlockSpecs,defaultInlineContentSpecs} from '@blocknote/core';
import {extendedBlocks,blockReference} from './extended-blocks.jsx';
import {EditorTools} from './editor-tools.jsx';
import {registerEditor,locateBlock,walkBlocks} from './editor-context.js';
import {handleFragmentPaste,exportRecord} from './fragments.js';
import {request} from './host-bridge.js';
import {en,zh} from '@blocknote/core/locales';
import {EditorLanguage,useCopy,useEditorError} from './editor-locale.js';
import {createReactBlockSpec,useCreateBlockNote} from '@blocknote/react';
import {BlockNoteView} from '@blocknote/shadcn';
import {Streamdown,defaultUrlTransform} from 'streamdown';
import {useReactTable,getCoreRowModel,getSortedRowModel,getFilteredRowModel,flexRender} from '@tanstack/react-table';
import {readModel,fromRows} from './data-model.js';
import {tableLayout,webLink} from './data-layout.js';
import {VisualData,DataSurface,CompactLink} from './visual-data.jsx';
import {Download,History,ArrowLeft,ChevronDown,Plus,Undo2,Redo2,Pencil,Search} from 'lucide-react';
import '@blocknote/shadcn/style.css';
import '../../../web/ui/tokens.css';
import './style.css';

const Context=createContext(null),SCHEMA='runteams.rich-document/1';
const send=(type,value={})=>window.parent.postMessage({channel:'runteams-rich-document/1',token:window.location.hash.slice(1),type,...value},window.location.origin);
const transformURL=value=>/^runteams:\/\/document\/[1-9][0-9]*(?:#[a-zA-Z0-9._:-]+)?$/.test(value)?value:defaultUrlTransform(value);
function Markdown({text,imageUrls}){return <Streamdown mode="static" urlTransform={transformURL} components={{img:({node,...props})=><img {...props} src={imageUrls?.[props.src]||props.src} referrerPolicy="no-referrer"/>}}>{text}</Streamdown>;}
function FieldValue({value}){
 if(typeof value==='string'&&/^https?:\/\//.test(value)){try{const url=new URL(value);return <a href={url.href} title={value} target="_blank" rel="noopener noreferrer">{url.hostname} ↗</a>;}catch{}}
 return <span>{primitive(value)}</span>;
}
const primitive=value=>value==null?'—':typeof value==='object'?JSON.stringify(value):String(value);
function JsonTree({value,name,depth=0}){
 const copy=useCopy();
 name??=copy('数据','Data');
 const [open,setOpen]=useState(depth<1),[limit,setLimit]=useState(50);
 if(value===null||typeof value!=='object')return <div className="json-value"><span>{name}</span><code>{primitive(value)}</code></div>;
 const entries=Object.entries(value);return <details className="json-tree" open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary>{name}<small>{Array.isArray(value)?copy(`${entries.length} 项`,`${entries.length} items`):copy(`${entries.length} 个字段`,`${entries.length} fields`)}</small></summary>{open&&<div>{entries.slice(0,limit).map(([key,v])=><JsonTree key={key} value={v} name={key} depth={depth+1}/>)}{entries.length>limit&&<button onClick={()=>setLimit(limit+50)}>{copy("再显示 50 项","Show 50 More")}</button>}</div>}</details>;
}
function compact(value){if(typeof value==='string'&&/^https?:\/\//.test(value)){try{return new URL(value).hostname+' ↗';}catch{}}return primitive(value);}
function DataTable({rows=[]}){
 const copy=useCopy();
 const [filter,setFilter]=useState(''),[sorting,setSorting]=useState([]),[page,setPage]=useState(0),[selected,setSelected]=useState(null),[searchOpen,setSearchOpen]=useState(false);
 const keys=useMemo(()=>[...new Set(rows.flatMap(Object.keys))].slice(0,30),[rows]);
 const columns=useMemo(()=>keys.map(key=>({accessorKey:key,id:key,accessorFn:row=>primitive(row[key]),header:key,sortingFn:(a,b,id)=>typeof a.original[id]==='number'&&typeof b.original[id]==='number'?a.original[id]-b.original[id]:primitive(a.original[id]).localeCompare(primitive(b.original[id]),undefined,{numeric:true}),cell:info=><span title={primitive(info.row.original[key])}>{compact(info.row.original[key])}</span>})),[keys]);
 const table=useReactTable({data:rows,columns,state:{globalFilter:filter,sorting},onGlobalFilterChange:setFilter,onSortingChange:setSorting,getCoreRowModel:getCoreRowModel(),getSortedRowModel:getSortedRowModel(),getFilteredRowModel:getFilteredRowModel()});
 const layout=useMemo(()=>{const model=fromRows(rows);return tableLayout({...model,columns:model.columns.filter(c=>keys.includes(c.id))});},[rows,keys]);
 const filtered=table.getRowModel().rows,visible=filtered.slice(page*15,page*15+15);
 return <DataSurface layoutWidth={layout.width} onLeave={()=>{if(!filter)setSearchOpen(false);}} actions={rows.length>15?<button aria-label={copy("搜索表格","Search Table")} title={copy("搜索表格","Search Table")} aria-expanded={searchOpen} onClick={()=>setSearchOpen(filter?true:!searchOpen)}><Search size={15}/></button>:null}><section className="table-widget">{searchOpen&&<div className="data-toolbar"><input aria-label={copy("搜索表格","Search Table")} type="search" placeholder={copy("搜索表格","Search Table")} value={filter} onChange={e=>{setFilter(e.target.value);setPage(0);}}/></div>}<div className="table-scroll"><table style={{minWidth:layout.width,tableLayout:'fixed'}}><colgroup>{layout.widths.map((width,i)=><col key={keys[i]} style={{width}}/>)}</colgroup><thead>{table.getHeaderGroups().map(g=><tr key={g.id}>{g.headers.map(h=><th key={h.id} aria-sort={h.column.getIsSorted()==='asc'?'ascending':h.column.getIsSorted()==='desc'?'descending':'none'}><button onClick={h.column.getToggleSortingHandler()}>{flexRender(h.column.columnDef.header,h.getContext())}{h.column.getIsSorted()==='asc'?' ↑':h.column.getIsSorted()==='desc'?' ↓':''}</button></th>)}</tr>)}</thead><tbody>{visible.map(row=><tr key={row.id}>{row.getVisibleCells().map(cell=><td key={cell.id}>{webLink(row.original[cell.column.id])?<CompactLink value={row.original[cell.column.id]}/>:<button className="cell" aria-label={copy(`查看记录：${primitive(row.original[keys[0]])}`,`View record: ${primitive(row.original[keys[0]])}`)} onClick={()=>setSelected(selected===row.original?null:row.original)}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</button>}</td>)}</tr>)}</tbody></table></div>{!filtered.length&&<p className="muted">{copy("没有匹配的记录。","No matching records.")}</p>}{filtered.length>15&&<div className="pagination"><span>{copy(`第 ${page+1} / ${Math.ceil(filtered.length/15)} 页`,`Page ${page+1} of ${Math.ceil(filtered.length/15)}`)}</span><button disabled={page===0} onClick={()=>setPage(page-1)}>{copy("上一页","Previous Page")}</button><button disabled={(page+1)*15>=filtered.length} onClick={()=>setPage(page+1)}>{copy("下一页","Next Page")}</button></div>}{selected&&<div className="record-detail"><header><b>{copy("记录详情","Record Details")}</b><button onClick={()=>setSelected(null)}>{copy("收起","Collapse")}</button></header><dl className="record-fields">{Object.entries(selected).map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value&&typeof value==='object'?<JsonTree value={value} name={key}/>:<FieldValue value={value}/>}</dd></div>)}</dl></div>}</section></DataSurface>;
}
function SourceData({value}){
 const copy=useCopy();
 if(Array.isArray(value)&&value.length===1&&value[0]&&typeof value[0]==='object')return <JsonTree value={value[0]} name={copy("记录","Record")}/>;
 if(Array.isArray(value)&&value.length&&value.every(row=>row&&typeof row==='object'&&!Array.isArray(row)))return <DataTable rows={value}/>;
 return <JsonTree value={value}/>;
}
function AutoText({value,...props}){
 const ref=useRef(null);
 useEffect(()=>{const node=ref.current;if(!node)return;const fit=()=>{node.style.height='auto';node.style.height=node.scrollHeight+'px';};fit();let width=node.clientWidth;const observer=new ResizeObserver(()=>{if(node.clientWidth!==width){width=node.clientWidth;fit();}});observer.observe(node);return()=>observer.disconnect();},[]);
 useEffect(()=>{const node=ref.current;if(node){node.style.height='auto';node.style.height=node.scrollHeight+'px';}},[value]);
 return <textarea {...props} rows={1} ref={ref} value={value}/>;
}
function Metric({block,editor,editable,source}){
 const copy=useCopy();
 const value=useRef(null),props=block.props;
 const width=Math.max(3,[...props.value].reduce((sum,c)=>sum+(c.codePointAt(0)<128?1:2),0)+1);
 return <DataSurface source={source} actions={editable?<button aria-label={copy("编辑指标","Edit Metric")} title={copy("编辑指标","Edit Metric")} onClick={()=>value.current?.focus()}><Pencil size={15}/></button>:null}>{editable?<div className="metric metric-inline"><input ref={value} style={{width:width+'ch'}} aria-label={copy("指标数值","Metric Value")} value={props.value} onChange={e=>editor.updateBlock(block.id,{props:{value:e.target.value}})}/><AutoText aria-label={copy("指标名称","Metric Name")} value={props.label} onChange={e=>editor.updateBlock(block.id,{props:{label:e.target.value}})}/></div>:<div className="metric"><strong>{props.value}</strong><span>{props.label}</span></div>}</DataSurface>;
}
function Widget({block,editor}){
 const copy=useCopy();
 const {sources,editing}=useContext(Context),props=block.props,source=sources[props.source];
 const [rawOpen,setRawOpen]=useState(false);
 let content;
 if(block.type==='markdown')content=<Markdown text={props.text||''}/>;
 if(block.type==='metric')content=<Metric block={block} editor={editor} editable={editing} source={source}/>;
 if(block.type==='jsonData')content=source?<DataSurface source={source}><details className="source-disclosure" onToggle={e=>setRawOpen(e.currentTarget.open)}><summary>{copy("查看原始数据","View Raw Data")}</summary><SourceData value={source.data}/></details></DataSurface>:<p>{copy("数据快照不可用。","The data snapshot is unavailable.")}</p>;
 if(['dataTable','barChart'].includes(block.type))content=<VisualData block={block} editor={editor} source={source} editable={editing} detail={value=><JsonTree value={value}/>}/>;
 let width=block.type==='barChart'?1000:0;
 if(block.type==='dataTable'){try{width=tableLayout(readModel(props.data,source?.data),editing).width;}catch{/* Error stays with the data renderer. */}}
 if(block.type==='jsonData'&&rawOpen&&Array.isArray(source?.data)&&source.data.length>1){try{width=tableLayout(fromRows(source.data)).width;}catch{/* Object trees keep their normal width. */}}
 return <div className={`rich-widget widget-${block.type}${width?' data-layout':''}`} style={width?{'--data-width':width+'px'}:undefined} contentEditable={false}>{editing&&block.type!=='markdown'&&block.type!=='metric'?<AutoText className="widget-title-input" aria-label={copy("内容块标题","Block Title")} placeholder={copy("标题","Title")} value={props.title||''} onChange={e=>editor.updateBlock(block.id,{props:{title:e.target.value}})}/>:props.title&&<h2>{props.title}</h2>}{block.type==='markdown'&&editing?<textarea className="markdown-fallback" aria-label={copy("Markdown 正文","Markdown Content")} value={props.text||''} onChange={e=>editor.updateBlock(block.id,{props:{text:e.target.value}})}/>:content}</div>;
}
const spec=(type,propSchema)=>createReactBlockSpec({type,propSchema,content:'none'},{render:Widget})();
const schema=BlockNoteSchema.create({inlineContentSpecs:{...defaultInlineContentSpecs,blockReference},blockSpecs:{...extendedBlocks,...Object.fromEntries(Object.entries(defaultBlockSpecs).filter(([t])=>['paragraph','heading','bulletListItem','numberedListItem','checkListItem','toggleListItem','quote','codeBlock','table','divider'].includes(t))),
 markdown:spec('markdown',{text:{default:''}}),dataTable:spec('dataTable',{source:{default:''},title:{default:''},data:{default:''},dataKey:{default:''}}),barChart:spec('barChart',{source:{default:''},title:{default:''},x:{default:''},y:{default:''},data:{default:''},chartType:{default:'bar'},unit:{default:''},dataKey:{default:''}}),jsonData:spec('jsonData',{source:{default:''},title:{default:''}}),metric:spec('metric',{label:{default:''},value:{default:''}})}});
function exportJSON(title,value){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=title+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function RichEditor({doc,record,embedded,theme,onReady}){
 const copy=useCopy(),errorCopy=useEditorError();
 const editing=!!doc.editable&&!embedded;
 useDocumentOutline(!embedded&&doc.outline_enabled===true);
 const language=useContext(EditorLanguage);
 const dictionaryLanguage=useRef(language);
 dictionaryLanguage.current=language;
 const dictionary=useMemo(()=>{
  const selected=()=>dictionaryLanguage.current==='en'?en:zh;
  const descriptors=Object.fromEntries(Object.keys(zh).map(key=>[key,{enumerable:true,get:()=>selected()[key]}]));
  descriptors.formatting_toolbar.get=()=>{
   const toolbar=selected().formatting_toolbar;
   return {...toolbar,code:{...toolbar.code,tooltip:dictionaryLanguage.current==='en'?'Inline Code':'行内代码'}};
  };
  return Object.defineProperties({},descriptors);
 },[]);
 const editor=useCreateBlockNote({schema,dictionary,initialContent:record.blocks,placeholders:{default:'',emptyDocument:''},pasteHandler:handleFragmentPaste},[]);
 const normalized=useRef(false);
 // Normalize once before mounting the view, equally for readers and editors.
 if(!normalized.current){normalized.current=true;const reserved=new Set();walkBlocks(editor.document,b=>reserved.add(b.id));for(const block of [...editor.document])if(block.type==='markdown'){try{const parsed=editor.tryParseMarkdownToBlocks(block.props.text);if(parsed.length){const identify=(items,path=[])=>items.forEach((item,index)=>{const position=[...path,index];if(!path.length&&!index)item.id=block.id;else{let id=block.id+':text:'+position.join('-');while(reserved.has(id))id+='-n';item.id=id;reserved.add(id);}if(item.children?.length)identify(item.children,position);});identify(parsed);editor.replaceBlocks([block.id],parsed);}}catch{/* Retain unsupported content verbatim. */}}}
 const [title,setTitle]=useState(doc.name),[state,setState]=useState('saved'),[error,setError]=useState(''),[insertOpen,setInsertOpen]=useState(false);
 const titleRef=useRef(doc.name),saver=useRef(null),sourcesRef=useRef(record.sources),active=useRef(true);
 const [sources,setSources]=useState(record.sources),[tool,setTool]=useState(null),[featureError,setFeatureError]=useState(''),[exportError,setExportError]=useState('');
 const current=()=>({name:titleRef.current,document:{schema:SCHEMA,blocks:editor.document,sources:sourcesRef.current}});
 useEffect(()=>{
  saver.current=createAutosave({revision:doc.revision,initial:current(),write:value=>send('save',value),status:(value,message='')=>{setState(value);setError(message);},clean:dirty=>send('dirty',{dirty})});
  const listener=e=>{if(e.source!==parent||e.origin!==location.origin||e.data?.channel!=='runteams-rich-document/1'||e.data.token!==location.hash.slice(1))return;if(e.data.type==='save-request'){if(e.data.flush_id)saver.current.before(()=>send('flushed',{flush_id:e.data.flush_id,ok:true}));else saver.current.flush();}if(e.data.type==='saved')saver.current.acknowledge(e.data);if(e.data.type==='header-action'){if(e.data.action==='export')void exportDocument();if(e.data.action==='retry-save'&&editing)saver.current.retry();}};
  const keydown=e=>{if(editing&&(e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='s'){e.preventDefault();saver.current.flush();}};
  const openBlock=e=>saver.current.before(()=>send('open-block',{document_id:e.detail.documentId,block_id:e.detail.blockId}));
  window.addEventListener('runteams-open-block',openBlock);window.addEventListener('message',listener);window.addEventListener('keydown',keydown);send('dirty',{dirty:false});
  return()=>{active.current=false;saver.current.dispose();window.removeEventListener('runteams-open-block',openBlock);window.removeEventListener('message',listener);window.removeEventListener('keydown',keydown);};
 },[]);
 useEffect(()=>{onReady?.(editor);},[editor,onReady]);
 const changed=()=>{if(editing)saver.current?.update(current());};
 registerEditor(editor,{documentId:doc.id,documentURL:doc.document_url,resourcesAvailable:doc.resources_available!==false,editing,isActive:()=>active.current,getSources:()=>sourcesRef.current,setSources:value=>{sourcesRef.current=value;setSources(value);},changed,report:setFeatureError,navigate:(documentId,blockId)=>saver.current.before(()=>send('open-block',{document_id:documentId,block_id:blockId})),openTool:(kind,id,options={})=>setTool({kind,id,selection:editor.prosemirrorState.selection.toJSON(),...options})});
 useEffect(()=>{if(!doc.initial_block)return;const frame=requestAnimationFrame(()=>{if(!locateBlock(editor,doc.initial_block))setFeatureError('linked-block-missing');});return()=>cancelAnimationFrame(frame);},[]);
 const exportDocument=async()=>{
  setExportError('');
  try{await request('export-download',{name:titleRef.current,document:await exportRecord(editor,current().document)});}
  catch(error){setExportError(error.code==='export-too-large'?'too-large':'failed');}
 };
 const exportErrorCopy=exportError==='too-large'
  ?copy('文档太大，无法导出。请单独下载附件。','The document is too large to export. Download its attachments separately.')
  :copy('无法导出文档。请重试。','Couldn’t export the document. Try again.');
 const navigate=type=>saver.current.before(()=>send(type));
 const saveErrorCopy=error==='请填写文档名称。'?copy('请输入文档名称。','Enter a document name.'):
  error==='尚未确认保存结果，请重试确认。'?copy('尚未确认是否保存。请重试保存。','Saving hasn’t been confirmed. Try saving again.'):
  copy('无法保存更改。请重试保存，或导出当前内容。','Couldn’t save your changes. Try saving again or export this copy.');
 const insert=type=>{const selected=editor.getTextCursorPosition().block;const props=['dataTable','barChart'].includes(type)?{title:'',dataKey:crypto.randomUUID(),data:JSON.stringify({columns:[{id:'name',name:copy('名称','Name'),type:'text'},{id:'value',name:copy('数值','Value'),type:'number'}],rows:[{name:'',value:null}]}),...(type==='barChart'?{x:'name',y:'value'}:{})}:undefined;editor.insertBlocks([{type,...(props?{props}:{content:[]})}],selected.id,'after');setInsertOpen(false);};
 return <Context.Provider value={{sources,editing}}><div className={embedded?'embedded':'document-app'}>{!embedded&&!doc.header_in_host&&<header className="toolbar"><button onClick={()=>navigate('back')} aria-label={copy("返回文档列表","Back to Documents")}><ArrowLeft size={16}/>{copy("文档","Documents")}</button><div className="toolbar-right">{editing&&<><span className="save-state" role="status">{state==='saving'?copy('正在保存…','Saving…'):state==='pending'?copy('等待保存','Waiting to Save'):state==='error'?copy('未保存','Unsaved'):copy('已保存','Saved')}</span><button aria-label={copy("撤销","Undo")} title={copy("撤销","Undo")} onClick={()=>editor.undo()}><Undo2 size={15}/></button><button aria-label={copy("重做","Redo")} title={copy("重做","Redo")} onClick={()=>editor.redo()}><Redo2 size={15}/></button><div className="insert"><button onClick={()=>setInsertOpen(!insertOpen)} aria-label={copy("插入内容","Insert Content")} aria-expanded={insertOpen}><Plus size={15}/><ChevronDown size={12}/></button>{insertOpen&&<div className="insert-menu">{[['paragraph',copy('文字段落','Paragraph')],['heading',copy('标题','Heading')],['bulletListItem',copy('项目列表','Bulleted List')],['table',copy('普通表格','Table')],['dataTable',copy('数据表格','Data Table')],['barChart',copy('图表','Chart')]].map(([t,label])=><button key={t} onMouseDown={e=>e.preventDefault()} onClick={()=>insert(t)}>{label}</button>)}</div>}</div></>}<button onClick={exportDocument} aria-label={copy("导出文档","Export Document")} title={copy("导出文档","Export Document")}><Download size={15}/></button><button onClick={()=>navigate('versions')} aria-label={copy("历史版本","Version History")} title={copy("历史版本","Version History")}><History size={15}/></button></div></header>}{error&&<div className="save-error" role="alert">{saveErrorCopy}<button onClick={()=>saver.current.retry()}>{copy('重试保存','Retry Save')}</button><button onClick={exportDocument}>{copy('导出当前内容','Export This Copy')}</button></div>}<>{(exportError||featureError)&&<div role="alert" className="rt-feature-error"><span>{exportError?exportErrorCopy:featureError==='linked-block-missing'?copy('找不到链接对应的内容，可能已被删除。','Couldn’t find the linked block. It may have been deleted.'):errorCopy(featureError)}</span><button aria-label={copy('关闭操作提示','Dismiss Message')} onClick={()=>{setExportError('');setFeatureError('');}}>×</button></div>}</><main className="paper">{editing?<AutoText className="title-input" aria-label={copy('文档名称','Document Name')} maxLength={200} value={title} onChange={e=>{titleRef.current=e.target.value;setTitle(e.target.value);changed();}}/>:<h1>{title}</h1>}<BlockNoteView editor={editor} editable={editing} theme={theme} onChange={changed} sideMenu={false} formattingToolbar={false} slashMenu={false}>{editing&&<CompactEditorMenus/>}</BlockNoteView></main>{editing&&tool&&<EditorTools key={tool.kind+tool.id} editor={editor} tool={tool} onClose={()=>setTool(null)}/>}</div></Context.Provider>;
}
function FilePreview({doc,embedded}){
 const copy=useCopy();
 useDocumentOutline(!embedded&&doc.outline_enabled===true);
 let content;
 if(doc.content_model==='json'||doc.path?.endsWith('.json')){try{const value=JSON.parse(doc.content);content=<>{Array.isArray(value)&&value.every(v=>v&&typeof v==='object'&&!Array.isArray(v))?<DataTable rows={value}/>:<JsonTree value={value}/>}</>;}catch{content=<pre>{doc.content}</pre>;}}
 else content=<Markdown text={doc.content||''} />;
 return <div className={embedded?'embedded':'document-app'}>{!embedded&&!doc.header_in_host&&<header className="toolbar"><button onClick={()=>send('back')}><ArrowLeft size={16}/>{copy("文档","Documents")}</button><div className="toolbar-right"><button onClick={()=>send('versions')}><History size={15}/>{copy("历史版本","Version History")}</button></div></header>}<main className="paper"><h1>{doc.name}</h1>{content}</main></div>;
}
export function DocumentApp({payload,onReady}){
 const copy=useCopy();
 const {doc,embedded=false,theme='light'}=payload;
 let record;
 if(doc.content_model==='rich-document'){try{record=JSON.parse(doc.content);if(record.schema!==SCHEMA||!Array.isArray(record.blocks))throw Error();}catch{return <div role="alert" className="save-error">{copy("文档内容暂时无法显示。原内容已保留，请重新打开。","Couldn’t display the document. Your content is saved. Reopen the document to try again.")}</div>;}}
 return record?<RichEditor doc={doc} record={record} embedded={embedded} theme={theme} onReady={onReady}/>:<FilePreview doc={doc} embedded={embedded}/>;
}
