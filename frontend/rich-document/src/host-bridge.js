// The frame renders content; the product host owns authorization and persistence.
const channel='runteams-rich-document/1',pending=new Map();
export const send=(type,value={})=>parent.postMessage({channel,token:location.hash.slice(1),type,...value},location.origin);
export function request(operation,value={}){
 const request_id=crypto.randomUUID();
 return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(request_id);reject(Error('操作结果尚未确认，请保留当前内容后重试。'));},60000);pending.set(request_id,{resolve,reject,timer});send('resource',{operation,request_id,...value});});
}
window.addEventListener('message',event=>{
 const data=event.data;if(event.source!==parent||event.origin!==location.origin||data?.channel!==channel||data.token!==location.hash.slice(1)||data.type!=='resource-result')return;
 const item=pending.get(data.request_id);if(!item)return;pending.delete(data.request_id);clearTimeout(item.timer);if(data.error)item.reject(Error(data.error));else item.resolve(data.result);
});
