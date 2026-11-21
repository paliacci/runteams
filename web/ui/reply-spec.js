/* Shared, provider-independent contract for bounded json-render reply snapshots. */
globalThis.RunTeamsReplySpec=(()=>{
 'use strict';
 const forbidden=new Set(['__proto__','prototype','constructor']);
 const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
 const scalar=v=>v===null||['string','number','boolean'].includes(typeof v);
 const fail=message=>{throw Error(message);};
 const maxBytes=95000;
 const encoder=new TextEncoder();
 const tooLong=(value,max)=>value.length>max&&Array.from(value).length>max;
 const unpairedSurrogate=/[\uD800-\uDFFF]/u;
 function keys(value,allowed){if(!object(value)||Object.keys(value).some(k=>!allowed.includes(k)))fail('包含不支持的展示字段');}
 function text(v,max=120){if(typeof v!=='string'||!v.trim()||tooLong(v,max))fail('展示文字格式不正确');}
 function pointer(path){if(typeof path!=='string'||tooLong(path,500)||path!==''&&!path.startsWith('/')||/~(?![01])/u.test(path))fail('数据路径格式不正确');const parts=path===''?[]:path.slice(1).split('/').map(p=>p.replaceAll('~1','/').replaceAll('~0','~'));if(parts.some(p=>forbidden.has(p)))fail('数据路径不可访问');return parts;}
 function get(value,path){
  for(const part of pointer(path)){
   if(value===null||typeof value!=='object'||Array.isArray(value)&&!/^(0|[1-9][0-9]*)$/.test(part)||!Object.hasOwn(value,part))return undefined;
   value=value[part];
  }
  return value;
 }
 function bounded(value,depth=0,budget={count:0}){
  if(++budget.count>15000||depth>16)fail('数据过大或层级过深');
  if(typeof value==='string'&&(tooLong(value,20000)||unpairedSurrogate.test(value))||typeof value==='number'&&!Number.isFinite(value))fail('数据值超出限制');
  if(value===undefined||typeof value==='function')fail('数据不是有效 JSON');
  if(value&&typeof value==='object'){
   if(Object.keys(value).some(k=>forbidden.has(k)||unpairedSurrogate.test(k)))fail('数据含不可访问字段');
   for(const v of Object.values(value))bounded(v,depth+1,budget);
  }
 }
 function binding(value,data){keys(value,['$state']);if(typeof value.$state!=='string'||!/^\/data(?:\/|$)/.test(value.$state))fail('只能引用本条消息的数据');const result=get({data},value.$state);if(result===undefined)fail('引用的数据路径不存在');return result;}
 function columns(cols,items){if(!Array.isArray(cols)||!cols.length||cols.length>12)fail('需要 1–12 列');const names=new Set();for(const col of cols){keys(col,['key','label','path','format']);if(typeof col.key!=='string'||!/^[a-zA-Z][\w-]{0,49}$/.test(col.key)||forbidden.has(col.key)||names.has(col.key))fail('列标识无效');names.add(col.key);text(col.label,80);pointer(col.path);if(!['text','number',undefined].includes(col.format))fail('列格式无效');for(const item of items){const v=get(item,col.path);if(v!==undefined&&(!scalar(v)||typeof v==='string'&&tooLong(v,2000)||col.format==='number'&&v!==null&&typeof v!=='number'))fail('列引用的值与格式不一致');}}}
 function validate(value){
  keys(value,['version','title','data','spec']);if(value.version!==2)fail('不支持的展示版本');text(value.title);if(!Object.hasOwn(value,'data'))fail('缺少原始数据');bounded(value);if(encoder.encode(JSON.stringify(value)).length>maxBytes)fail('展示数据超过容量，请缩小范围');
  keys(value.spec,['root','elements']);const {root,elements}=value.spec;if(!object(elements)||!Object.keys(elements).length||Object.keys(elements).length>24||typeof root!=='string'||!Object.hasOwn(elements,root))fail('展示结构无效');
  const visited=new Set();function visit(id,depth){if(depth>6||visited.has(id)||!Object.hasOwn(elements,id))fail('展示结构循环、重复或缺失');visited.add(id);const e=elements[id];keys(e,['type','props','children']);if(!Array.isArray(e.children)||e.children.length>12)fail('子组件格式无效');const p=e.props;
   if(e.type==='Stack'){keys(p,[]);}else{
    if(e.children.length)fail('仅 Stack 支持子组件');
    if(e.type==='Detail'){keys(p,['title','value']);text(p.title);binding(p.value,value.data);}
    else if(['Table','Chart','Messages'].includes(e.type)){
     keys(p,e.type==='Messages'?['title','items','headline','body','meta']:e.type==='Chart'?['title','items','columns','x','metrics']:['title','items','columns']);text(p.title);const items=binding(p.items,value.data);if(!Array.isArray(items)||items.length>500||items.some(v=>!object(v)))fail('需要最多 500 条对象记录');
     if(e.type==='Messages'){pointer(p.headline);pointer(p.body);if(!Array.isArray(p.meta)||p.meta.length>3)fail('消息元信息格式无效');p.meta.forEach(pointer);for(const row of items)for(const path of [p.headline,p.body,...p.meta]){const v=get(row,path);if(v!==undefined&&!scalar(v))fail('消息字段必须为文本或数值');}}
     else{columns(p.columns,items);if(e.type==='Chart'&&(!p.columns.some(c=>c.key===p.x)||!Array.isArray(p.metrics)||!p.metrics.length||p.metrics.length>4||new Set(p.metrics).size!==p.metrics.length||p.metrics.some(k=>!p.columns.some(c=>c.key===k&&c.format==='number'))))fail('图表字段无效');}
    }else fail('不支持的展示组件');
   }for(const child of e.children){if(typeof child!=='string')fail('组件引用无效');visit(child,depth+1);}
  }visit(root,0);if(visited.size!==Object.keys(elements).length)fail('展示含未使用的组件');return value;
 }
 function project(items,cols){return items.map(item=>Object.fromEntries(cols.map(col=>[col.key,get(item,col.path)??null])));}
 function plain(value){validate(value);const blocks=[value.title];for(const e of Object.values(value.spec.elements)){const p=e.props;if(e.type==='Stack')continue;blocks.push(p.title);if(e.type==='Detail')blocks.push(JSON.stringify(binding(p.value,value.data),null,2));else{const items=binding(p.items,value.data);if(e.type==='Messages')blocks.push(...items.map(row=>[p.headline,p.body,...p.meta].map(path=>get(row,path)??'').join('\n')));else blocks.push(p.columns.map(c=>c.label).join('\t'),...project(items,p.columns).map(row=>p.columns.map(c=>row[c.key]??'—').join('\t')));}}return blocks.join('\n');}
 return {validate,get,binding,project,plain};
})();
