// Presentation only: infer widths without changing stored values or column identities.
export function webLink(value){
 if(typeof value!=='string'||!/^https?:\/\//i.test(value))return null;
 try{const url=new URL(value);if(!['http:','https:'].includes(url.protocol))return null;return {href:url.href,label:url.hostname.replace(/^www\./,''),full:value};}catch{return null;}
}
const textWidth=text=>[...String(text)].reduce((sum,c)=>sum+(c.codePointAt(0)>255?13:7),0);
export function tableLayout(model,editable=false){
 const widths=model.columns.map(column=>{
  const values=model.rows.slice(0,100).map(row=>row[column.id]).filter(v=>v!==null&&v!==undefined&&v!=='');
  const header=Math.min(220,textWidth(column.name)+(editable?48:24));
  let width=144;
  if(column.type==='number')width=88;
  else if(values.length&&values.every(v=>webLink(v)))width=184;
  else if(values.length&&values.every(v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(v)))width=values.some(v=>v.length>10)?196:128;
  else{const longest=Math.max(0,...values.map(v=>typeof v==='object'?220:textWidth(v)));width=longest>260?216:longest>160?192:144;}
  return Math.max(header,width);
 });
 return {widths,width:Math.max(320,widths.reduce((sum,w)=>sum+w,0)+(editable?36:0))};
}
