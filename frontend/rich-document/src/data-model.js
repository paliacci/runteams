export const clone=value=>JSON.parse(JSON.stringify(value));
export function fromRows(rows=[]){
 if(!Array.isArray(rows)||!rows.every(row=>row&&typeof row==='object'&&!Array.isArray(row)))throw Error('这份数据无法作为表格打开，原始内容仍保留。');
 const keys=[...new Set(rows.flatMap(Object.keys))];
 return {columns:keys.map(id=>({id,name:id,type:rows.some(row=>typeof row[id]==='number')&&rows.every(row=>row[id]==null||typeof row[id]==='number')?'number':'text'})),rows:clone(rows)};
}
export function readModel(data,rows){
 if(!data)return fromRows(rows||[]);
 const model=JSON.parse(data);
 if(model.invalidCells!==undefined&&(!Array.isArray(model.invalidCells)||!model.invalidCells.every(cell=>Number.isInteger(cell.row)&&cell.row>=0&&cell.row<model.rows?.length&&typeof cell.id==='string'&&typeof cell.text==='string')))throw Error('编辑副本中的待修正数据无法读取，原始内容仍保留。');
 if(!Array.isArray(model.columns)||!Array.isArray(model.rows)||!model.columns.every(c=>typeof c.id==='string'&&typeof c.name==='string'&&['text','number'].includes(c.type))||new Set(model.columns.map(c=>c.id)).size!==model.columns.length||!model.rows.every(r=>r&&typeof r==='object'&&!Array.isArray(r)))throw Error('编辑副本暂时无法读取，原始内容仍保留。');
 return model;
}
export function changeCell(model,row,id,text){
 const column=model.columns.find(c=>c.id===id);if(!column||!model.rows[row])throw Error('单元格已发生变化，请重新选择。');
 let value=text;
 if(column.type==='number'){value=text.trim()===''?null:Number(text);if(value!==null&&!Number.isFinite(value))throw Error('请输入有效数字。');}
 const next=clone(model);next.rows[row][id]=value;next.invalidCells=(next.invalidCells||[]).filter(cell=>cell.row!==row||cell.id!==id);return next;
}
export function editCell(model,row,id,text){
 try{return changeCell(model,row,id,text);}catch(error){
  if(model.columns.find(c=>c.id===id)?.type!=='number'||!model.rows[row])throw error;
  return {...model,invalidCells:[...(model.invalidCells||[]).filter(cell=>cell.row!==row||cell.id!==id),{row,id,text}]};
 }
}
export function deleteRow(model,row){return {...model,rows:model.rows.filter((_,i)=>i!==row),invalidCells:(model.invalidCells||[]).filter(cell=>cell.row!==row).map(cell=>({...cell,row:cell.row>row?cell.row-1:cell.row}))};}
export function renameColumn(model,id,name){
 name=name.trim();if(!name)throw Error('列名不能为空。');if(model.columns.some(c=>c.id!==id&&c.name===name))throw Error('已有同名列，请换一个名称。');
 return {...model,columns:model.columns.map(c=>c.id===id?{...c,name}:c)};
}
export function addColumn(model,name,type='text'){
 name=name.trim();if(!name||model.columns.some(c=>c.name===name))throw Error('请填写不重复的列名。');
 const id='column-'+crypto.randomUUID();return {...model,columns:[...model.columns,{id,name,type}],rows:model.rows.map(r=>({...r,[id]:type==='number'?null:''}))};
}
export function removeColumn(model,id){
 if(model.columns.length<=1)throw Error('请至少保留一列。');
 return {...model,columns:model.columns.filter(c=>c.id!==id),rows:model.rows.map(r=>{const next={...r};delete next[id];return next;}),invalidCells:(model.invalidCells||[]).filter(cell=>cell.id!==id)};
}
export function moveColumn(model,id,offset){
 const columns=[...model.columns],index=columns.findIndex(c=>c.id===id),to=index+offset;
 if(to<0||to>=columns.length)return model;
 [columns[index],columns[to]]=[columns[to],columns[index]];return {...model,columns};
}
export function chartData(model,x,y){
 return model.rows.map((row,index)=>({category:row[x]==null?'':String(row[x]),value:!(model.invalidCells||[]).some(cell=>cell.row===index&&cell.id===y)&&typeof row[y]==='number'&&Number.isFinite(row[y])?row[y]:null}));
}
export function updateLinkedData(editor,block,model){
 const flatten=blocks=>blocks.flatMap(b=>[b,...flatten(b.children||[])]);
 const data=JSON.stringify(model),related=flatten(editor.document).filter(other=>['dataTable','barChart'].includes(other.type)&&(block.props.source?other.props.source===block.props.source:block.props.dataKey?other.props.dataKey===block.props.dataKey:other.id===block.id));
 editor.transact(()=>{for(const other of related)editor.updateBlock(other.id,{props:{data}});});
}
