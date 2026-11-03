import {request} from './host-bridge.js';
function dataURL(blob){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('附件读取失败。'));reader.readAsDataURL(blob);});}
export async function saveAsset(file){
 if(!file.size||file.size>20*1024*1024)throw Error('请选择不超过20 MB的非空文件。');
 return request('asset-upload',{file:{name:file.name||'附件',type:file.type||'application/octet-stream',data:await dataURL(file)}});
}
export async function packAsset(id){const {name,type,data}=await request('asset-read',{id});return {name,type,data};}
export async function readAsset(id){
 const value=await packAsset(id),raw=atob(value.data.split(',')[1]);return {...value,blob:new Blob([Uint8Array.from(raw,c=>c.charCodeAt(0))],{type:value.type})};
}
export async function unpackAsset(_id,asset){return request('asset-upload',{file:asset});}
export async function downloadAsset(id){return request('asset-download',{id});}
