import React,{useMemo,useState,useSyncExternalStore} from 'react';
import {createRoot} from 'react-dom/client';
import {useReactTable,getCoreRowModel,getSortedRowModel,flexRender} from '@tanstack/react-table';
import {BarChart,Bar,XAxis,YAxis,Tooltip,ResponsiveContainer,CartesianGrid} from 'recharts';
import './reply-content.css';

const copy=(key,fallback,vars)=>window.RunTeamsLocale?.t('replyContent.'+key,vars,fallback)??fallback;
const subscribe=callback=>window.RunTeamsLocale?.onChange(callback)??(()=>{});
const readLanguage=()=>window.RunTeamsLocale?.language??'zh-CN';
function Table({data,language,rows=data.rows}){
 const display=useMemo(()=>{
  const numbers=new Intl.NumberFormat(language);
  return value=>value==null?'—':typeof value==='number'?numbers.format(value):String(value);
 },[language]);
 const [query,setQuery]=useState(''),[sorting,setSorting]=useState([]),[page,setPage]=useState(0),[selected,setSelected]=useState(null);
 const filtered=useMemo(()=>rows.filter(row=>data.columns.some(c=>display(row[c.key]).toLowerCase().includes(query.toLowerCase()))),[rows,query,data.columns,display]);
 const columns=useMemo(()=>data.columns.map(c=>({id:c.key,accessorFn:row=>row[c.key],header:c.label,cell:info=>display(info.getValue()),sortUndefined:'last'})),[data.columns,display]);
 const table=useReactTable({data:filtered,columns,state:{sorting},onSortingChange:next=>{setSorting(next);setPage(0);},getCoreRowModel:getCoreRowModel(),getSortedRowModel:getSortedRowModel()});
 const count=Math.max(1,Math.ceil(filtered.length/5)),current=Math.min(page,count-1),shown=table.getRowModel().rows.slice(current*5,current*5+5);
 return <><div className="reply-table-tools"><span>{query||rows.length!==data.rows.length?copy('filteredCount',`${filtered.length} / ${data.rows.length} 条`,{count:filtered.length,total:data.rows.length}):copy(filtered.length===1?'oneRecord':'recordCount',`${filtered.length} 条`,{count:filtered.length})}</span><input type="search" aria-label={copy('searchNamed',`搜索${data.title}`,{title:data.title})} placeholder={copy('search','搜索表格')} value={query} onChange={e=>{setQuery(e.target.value);setPage(0);setSelected(null);}}/></div>
 <div className="reply-table-scroll" role="region" aria-label={copy('scrollableTable',`${data.title}，可横向滚动`,{title:data.title})} tabIndex={0}><table><thead>{table.getHeaderGroups().map(group=><tr key={group.id}>{group.headers.map(header=><th key={header.id} aria-sort={header.column.getIsSorted()==='asc'?'ascending':header.column.getIsSorted()==='desc'?'descending':'none'}><button onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header,header.getContext())}<span aria-hidden="true">{header.column.getIsSorted()==='asc'?' ↑':header.column.getIsSorted()==='desc'?' ↓':' ↕'}</span></button></th>)}</tr>)}</thead><tbody>{shown.map(row=><tr key={row.id}>{row.getVisibleCells().map((cell,i)=><td key={cell.id} className={data.columns[i].format==='number'?'numeric':''}>{i===0?<button className="reply-record-link" onClick={()=>setSelected(selected===row.original?null:row.original)} aria-expanded={selected===row.original}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</button>:flexRender(cell.column.columnDef.cell,cell.getContext())}</td>)}</tr>)}</tbody></table></div>
 {!filtered.length&&<p className="reply-empty" role="status">{copy('empty','没有符合条件的记录。请试试其他关键词或筛选条件。')}</p>}
 {count>1&&<div className="reply-pagination"><span>{copy('page',`第 ${current+1} / ${count} 页`,{page:current+1,total:count})}</span><button disabled={current===0} onClick={()=>{setPage(current-1);setSelected(null);}}>{copy('previous','上一页')}</button><button disabled={current===count-1} onClick={()=>{setPage(current+1);setSelected(null);}}>{copy('next','下一页')}</button></div>}
 {selected&&filtered.includes(selected)&&<div className="reply-record"><div><strong>{copy('recordDetails','记录详情')}</strong><button onClick={()=>setSelected(null)}>{copy('collapse','收起')}</button></div><dl>{data.columns.map(c=><React.Fragment key={c.key}><dt>{c.label}</dt><dd>{display(selected[c.key])}</dd></React.Fragment>)}</dl></div>}</>;
}
function Chart({data,language}){
 const [metric,setMetric]=useState(data.metrics[0]),label=data.columns.find(c=>c.key===metric)?.label;
 return <><div className="reply-segments" role="group" aria-label={copy('chartMetrics','图表指标')}>{data.metrics.map(key=><button key={key} aria-pressed={key===metric} onClick={()=>setMetric(key)}>{data.columns.find(c=>c.key===key)?.label}</button>)}</div><div className="reply-chart" role="img" aria-label={copy('chartLabel',`${data.title}，当前指标：${label}`,{title:data.title,metric:label})}><ResponsiveContainer width="100%" height={230}><BarChart data={data.rows} layout="vertical" margin={{top:8,right:16,left:0,bottom:4}} accessibilityLayer><CartesianGrid stroke="var(--border-default)" horizontal={false}/><XAxis type="number" tick={{fill:'var(--text-secondary)',fontSize:12}} axisLine={false} tickLine={false}/><YAxis type="category" dataKey={data.x} width={112} interval={0} tick={{fill:'var(--text-secondary)',fontSize:12}} axisLine={false} tickLine={false}/><Tooltip cursor={{fill:'var(--surface-hover)'}} contentStyle={{background:'var(--surface)',color:'var(--text-primary)',border:'1px solid var(--border-default)',borderRadius:8}}/><Bar dataKey={metric} name={label} fill="var(--accent-default)" radius={[0,4,4,0]} maxBarSize={48} isAnimationActive={false}/></BarChart></ResponsiveContainer></div><details className="reply-chart-data"><summary>{copy('chartData','查看图表数据')}</summary><Table data={data} language={language}/></details></>;
}
function Explorer({data,language}){
 const [category,setCategory]=useState(''),[minimum,setMinimum]=useState(0);
 const categories=[...new Set(data.rows.map(r=>String(r[data.category]??'')))].filter(Boolean);
 const maximum=Math.max(1,...data.rows.map(r=>Number(r[data.threshold])||0)),label=data.columns.find(c=>c.key===data.threshold)?.label;
 const rows=useMemo(()=>data.rows.filter(row=>(!category||String(row[data.category])===category)&&Number(row[data.threshold])>=minimum),[data,category,minimum]);
 return <><div className="reply-segments" role="group" aria-label={copy('categories','筛选分类')}><button aria-pressed={!category} onClick={()=>setCategory('')}>{copy('all','全部')}</button>{categories.slice(0,12).map(value=><button key={value} aria-pressed={category===value} onClick={()=>setCategory(value)}>{value}</button>)}</div><label className="reply-range"><span>{copy('minimumLabel',`${label}至少`,{label})} <strong>{minimum}</strong></span><input type="range" aria-label={copy('minimum',`${label}最低值`,{label})} min={0} max={maximum} step={1} value={minimum} onChange={e=>setMinimum(Number(e.target.value))}/><button type="button" onClick={()=>{setCategory('');setMinimum(0);}}>{copy('reset','重置')}</button></label><Table data={data} language={language} rows={rows}/></>;
}
class Boundary extends React.Component{state={error:false};static getDerivedStateFromError(){return {error:true};}render(){return this.state.error?<p role="alert">{this.props.errorCopy}</p>:this.props.children;}}
export function ReplyView({data}){
 const language=useSyncExternalStore(subscribe,readLanguage,readLanguage);
 const errorCopy=copy('renderFailed','无法显示此内容。原始消息仍保留在对话中。请重新打开对话。');
 return <Boundary errorCopy={errorCopy}><section className="reply-content" aria-label={data.title}><header><h3>{data.title}</h3>{data.caption&&<p>{data.caption}</p>}</header>{data.type==='table'?<Table data={data} language={language}/>:data.type==='chart'?<Chart data={data} language={language}/>:<Explorer data={data} language={language}/>}</section></Boundary>;}
export function mount(node,data){const root=createRoot(node);root.render(<ReplyView data={data}/>);return root;}
