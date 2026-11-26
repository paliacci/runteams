const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.resolve(__dirname,'../web/ui/rich-documents.js'),'utf8');
async function download(doc,filename='check.json'){
 let saved;
 const anchor={click(){},remove(){}};
 const context={window:{addEventListener(){}},deviceWorkPath:path=>path,documentsBinding:()=>1,
  fetch:async()=>new Response(JSON.stringify(doc),{headers:{'Content-Type':'application/json','Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent(filename)}}),
  RunTeamsHost:{session:{headers:()=>({})}},S:{},RunTeamsLocale:{onChange(){}},MutationObserver:class{observe(){}},Blob,TextEncoder,atob,setTimeout(){},
  URL:{createObjectURL(blob){saved=blob;return 'blob:test';}},document:{createElement:()=>anchor,body:{appendChild(){}}},
  toast(){throw Error('Download failed');}};
 vm.runInNewContext(source,context);
 await context.window.RunTeamsRichDocuments.downloadDelivery(12);
 return {saved,name:anchor.download};
}
test('handoff download preserves actions, the evidence URL and actual table values',async()=>{
 const {saved,name}=await download({schema:'runteams.rich-document/1',sources:{},blocks:[
  {type:'markdown',props:{text:'# 修复清单'}},{type:'checkListItem',props:{checked:false},content:[{type:'link',href:'https://example.test/pricing',content:[{text:'修定价'}]}]},
  {type:'dataTable',props:{data:JSON.stringify({columns:[{id:'views',name:'展示'}],rows:[{views:0}]})}}]});
 assert.equal(name,'check.md');
 assert.match(await saved.text(),/# 修复清单\n\n- \[ \] \[修定价\]\(<https:\/\/example.test\/pricing>\)[\s\S]*\| 展示 \|[\s\S]*\| 0 \|/);
});
test('embedded evidence travels with Markdown as actual archive members',async()=>{
 const id='a'.repeat(64);
 const label='图?.png';
 const {saved,name}=await download({schema:'runteams.rich-document/1',sources:{},
  blocks:[{type:'image',props:{assetId:id,name:label}}],
  assets:{[id]:{name:label,data:'data:image/png;base64,AQID'}}},'AUX.md.json');
 assert.equal(name,'_AUX.zip');
 const zip=Buffer.from(await saved.arrayBuffer());
 const end=zip.length-22;assert.equal(zip.readUInt32LE(end),0x06054b50);assert.equal(zip.readUInt16LE(end+10),2);
 const entries=new Map();
 for(let pos=0;zip.readUInt32LE(pos)===0x04034b50;){
  const start=pos+30+zip.readUInt16LE(pos+26),end=start+zip.readUInt32LE(pos+18);
  entries.set(zip.toString('utf8',pos+30,start),zip.subarray(start,end));pos=end;
 }
 assert.ok(entries.get('_AUX.md').toString().includes(`![图?.png](assets/${id}/%E5%9B%BE_.png)`));
 assert.deepEqual(entries.get('assets/'+id+'/图_.png'),Buffer.from([1,2,3]));
});
test('handoff preserves Unicode when truncating an attachment name',async()=>{
 const id='b'.repeat(64),long='a'.repeat(155)+'📄'+'b'.repeat(8)+'.txt';
 const {saved,name}=await download({schema:'runteams.rich-document/1',sources:{},
  blocks:[{type:'file',props:{assetId:id,name:long}}],
  assets:{[id]:{name:long,data:'data:text/plain;base64,WA=='}}},'COM¹.json');
 assert.equal(name,'_COM¹.zip');
 const zip=Buffer.from(await saved.arrayBuffer());
 assert.ok(zip.includes(Buffer.from('assets/'+id+'/'+'a'.repeat(155)+'.txt)')));
});
