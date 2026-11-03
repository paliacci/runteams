/** Stable 1.0.0 contract. Available host capabilities must be negotiated. */
type JSONValue = null | boolean | number | string | JSONValue[] | {[key:string]:JSONValue};
type Params = {[key:string]:JSONValue};
type Retry = 'never'|'read'|'reconcile'|'reauthorize';
interface SDKRequest {abi:'runteams.sdk/1'; id:number; method:string; params:Params}
type SDKReply = {abi:'runteams.sdk/1'; id:number; ok:true; result:JSONValue} | {abi:'runteams.sdk/1'; id:number; ok:false; error:{code:string;retry:Retry}};
interface Receipt {state:'pending'|'confirmed'|'unknown'|'canceled'|'failed'; operation_key:string; release_digest:string; result?:JSONValue}
interface RunTeamsSDK {
 readonly version:'1.0.0';
 negotiate(required:string[]):{sdk:'1.0.0';capabilities:string[]};
 source:{list(p:{cursor?:string|null}):JSONValue;read(p:{path:string}):JSONValue;write(p:{path:string;base_revision:string;operation_key:string}&({content_base64:string;blob_ref?:never}|{blob_ref:string;content_base64?:never})):Receipt;beginUpload(p:{size:number;sha256:string}):{upload_ref:string};uploadChunk(p:{upload_ref:string;offset:number;content_base64:string}):{offset:number};finishUpload(p:{upload_ref:string;operation_key:string}):{blob_ref:string}};
 data:{query(p:{collection:string;limit:number;cursor?:string|null;filter?:Params}):JSONValue;mutate(p:{collection:string;mutations:{id:string;base_revision:string|null;value:Params|null}[];operation_key:string}):Receipt};
 connection:{status(p:{connection:string}):{state:'ready'|'authorization_required'|'unavailable'};request(p:{connection:string}):{request_ref:string};http(p:{connection:string;endpoint:string;path_params?:{[key:string]:string};query?:{[key:string]:string|number|boolean};body?:Params|null;operation_key?:string}):{status:number;body:JSONValue}};
 operation:{invoke(p:{operation:string;payload:Params;operation_key?:string}):JSONValue;receipt(p:{operation:string;operation_key:string}):Receipt};
 work:{dispatch(p:{employee_ref:string;skill_key:string;parameters:Params;operation_key:string}):Receipt;status(p:{run_ref:string}):JSONValue};
 events:{poll(p:{cursor?:string|null;limit:number}):{events:JSONValue[];cursor:string}};
 host:{openResult(p:{result_ref:string}):JSONValue;requestDecision(p:{decision_ref:string}):JSONValue};
}
declare function createRunTeamsSDK(transport:(request:SDKRequest)=>SDKReply):RunTeamsSDK;

export {createRunTeamsSDK};
export type {JSONValue,Params,Retry,SDKRequest,SDKReply,Receipt,RunTeamsSDK};
