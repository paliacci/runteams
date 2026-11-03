// Native synchronous host for the existing SDK createRuntime(host) API.
// Only an opaque per-program RPC capability enters this process, never bearer values.
'use strict';
const {spawnSync}=require('node:child_process');
if(require.main===module){
 let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',value=>{raw+=value;if(raw.length>32768)process.exit(2)});
 process.stdin.on('end',()=>{try{
  const {endpoint,capability,frame}=JSON.parse(raw),url=new URL(endpoint);
  if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||url.pathname!=='/protocol')throw Error('invalid_host');
  const body=JSON.stringify(frame),request=require('node:http').request(url,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+capability,'Content-Length':Buffer.byteLength(body)}},response=>{
   let body='';response.on('data',value=>{body+=value;if(body.length>65536)response.destroy()});response.on('end',()=>process.stdout.write(body));response.on('error',()=>process.exit(2));
  });request.setTimeout(25000,()=>request.destroy());request.on('error',()=>process.exit(2));request.end(body);
 }catch{process.exit(2)}});
}else{
 const endpoint=process.env.RUNTEAMS_CONNECTION_HOST,capability=process.env.RUNTEAMS_CONNECTION_CAPABILITY;
 delete process.env.RUNTEAMS_CONNECTION_HOST;delete process.env.RUNTEAMS_CONNECTION_CAPABILITY;
 if(!endpoint||!capability)throw Error('native_connection_host_missing');
 let sequence=0;
 function invoke(method,params){
  const frame={jsonrpc:'2.0',id:++sequence,method,params};
  const child=spawnSync(process.execPath,[__filename],{input:JSON.stringify({endpoint,capability,frame}),encoding:'utf8',timeout:30000,maxBuffer:128*1024});
  if(child.error||child.status!==0)throw Object.assign(Error('sdk_transport_failed'),{code:'sdk_transport_failed',retry:'reconcile'});
  let value;try{const reply=JSON.parse(child.stdout);if(reply.id!==frame.id||reply.error)throw Error();value=reply.result;if(value.id!==frame.id||value.abi!=='runteams.sdk/1')throw Error()}catch{throw Object.assign(Error('sdk_invalid_reply'),{code:'sdk_invalid_reply',retry:'reconcile'})}
  if(!value.ok)throw Object.assign(Error(value.error.code),{code:value.error.code,retry:value.error.retry});
  return value.result;
 }
 const host=Object.freeze({version:'1.0.0',negotiate:required=>invoke('system.negotiate',{sdk:'1.0.0',required}),connection:Object.freeze({http:params=>invoke('connection.http',params)})});
 Object.defineProperty(globalThis,'runteamsRuntimeHost',{value:host,writable:false,configurable:false});
}
