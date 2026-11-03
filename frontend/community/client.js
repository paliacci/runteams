// One library connection and one operation identity per user save.
export class LocalAPIError extends Error {
  constructor(code, status = 0, details = {}) { super(code); this.code = details.code||code; this.status = status; this.fields=details.fields; this.message_persisted=details.message_persisted; this.agent_started=details.agent_started; }
}

export class LocalClient {
  constructor({fetcher, request}) {
    if (typeof fetcher !== 'function' || typeof request !== 'function') throw new TypeError('Shared local transport is required');
    this.fetcher = fetcher; this.transport = request;
    this.libraryId = null; this.generation = null; this.reconnecting = null;
  }
  async raw(path, method = 'GET', body, scoped = true, options = {}) {
    if (method === 'POST' && body === undefined) body = {};
    const headers = {};
    if (scoped && this.libraryId) {headers['X-RunTeams-Library'] = this.libraryId;headers['X-RunTeams-Library-Generation'] = this.generation;}
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await this.transport(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin', redirect: 'error', device:true, readDiagnostics:false,
      invalidates:new URL(path,'http://localhost').pathname!=='/api/settings',
      readGroup:options.readGroup,readSequence:options.readSequence,readPriority:options.readPriority,
      readCurrent:options.readCurrent??(path==='/api/chats?device=1'&&method==='GET')}, JSON.stringify([this.libraryId,this.generation]));
    let value;
    try { value = JSON.parse(response.text); } catch { throw new LocalAPIError('invalid_response'); }
    if (response.status < 200 || response.status >= 300) throw new LocalAPIError(value.error || 'request_failed', response.status,value);
    return value;
  }
  async stream(path, body, onEvent) {
    const payload = {...body, operation_id: crypto.randomUUID()};
    let accepted = false, terminal = false;
    const deliver = event => { if (event.type === 'accepted') accepted = true; if (['result','cancelled','error'].includes(event.type)) terminal = true; onEvent(event); };
    const send = () => this.fetcher(path, {method:'POST', headers:{'Content-Type':'application/json','X-RunTeams-Library':this.libraryId,'X-RunTeams-Library-Generation':this.generation},
      body:JSON.stringify(payload), credentials:'same-origin', cache:'no-store', redirect:'error'});
    try {
      let response = await send();
      if (response.status === 401) { await this.reconnect(); response = await send(); }
      if (!response.ok) { let value={};try{value=await response.json();}catch{} throw new LocalAPIError(value.error||'对话没有开始，请重试。',response.status,value); }
      if (!response.body) throw new LocalAPIError('浏览器无法接收实时回复。');
      const reader=response.body.getReader(), decoder=new TextDecoder();let buffer='';
      try {
        while (true) {
          const part=await reader.read();buffer+=decoder.decode(part.value||new Uint8Array(),{stream:!part.done});
          const lines=buffer.split('\n');buffer=lines.pop()||'';
          for(const line of lines)if(line.trim())deliver(JSON.parse(line));
          if(part.done)break;
        }
        if(buffer.trim())deliver(JSON.parse(buffer));
      } finally { await reader.cancel().catch(()=>{}); }
      if(!terminal)throw new LocalAPIError('连接中断，请重新打开对话确认回复。');
    } catch(error) {
      // An explicit rejection preceded acceptance. No automatic model retry.
      if(!accepted && [400,403,404,409,413,415,422].includes(error.status))throw error;
      const chatPath=path.replace(/\/stream$/,'');
      try {
        for(let attempt=0;attempt<600;attempt++){
          const saved=await this.request(chatPath), messages=saved.messages||[];
          const user=messages.find(m=>m.role==='user'&&m.metadata?.local_turn_id===payload.operation_id);
          const reply=messages.find(m=>m.role==='bot'&&m.metadata?.local_turn_id===payload.operation_id);
          if(user&&!accepted)deliver({type:'accepted',message_id:user.id,operation_id:payload.operation_id,attachments:user.attachments||[],capabilities:user.capabilities||[]});
          if(reply){deliver({type:'result',message_id:reply.id,reply:reply.text,applied:reply.applied||[],run_cards:reply.metadata?.run_cards||[],device_page_ids:saved.device_page_ids||[],failed:!!reply.metadata?.failed,incomplete:!!reply.metadata?.stopped,...(saved.context?.creator_local_source_id?{session:saved}:{})});return;}
          if(!user&&!saved.active_turn?.active)throw Object.assign(error,{confirmedAbsent:true});
          if(!user||!saved.active_turn?.active)break;
          // Observe the existing accepted worker; never resubmit a model call.
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
        if(!accepted)error.localPending=true;
      } catch(recoveryError) { if(recoveryError.confirmedAbsent)throw recoveryError; if(!accepted)error.localPending=true; }
      throw error;
    }
  }
  async uploadBackup(file, operationId) {
    const response=await this.fetcher('/api/backups/import',{method:'POST',headers:{'Content-Type':'application/zip','X-RunTeams-Library':this.libraryId,'X-RunTeams-Library-Generation':this.generation,'X-RunTeams-Operation':operationId},body:file,credentials:'same-origin',cache:'no-store',redirect:'error'});
    let value;try{value=await response.json();}catch{throw new LocalAPIError('上传结果尚未确认，请重试。');}
    if(!response.ok)throw new LocalAPIError(value.error||'备份文件未能读取。',response.status);
    return value;
  }
  async connect() {
    const value = await this.raw('/api/library', 'GET', undefined, false);
    if (value.storage_kind !== 'local' || typeof value.library_id !== 'string' || typeof value.generation !== 'string' || !value.generation) throw new LocalAPIError('invalid_response');
    if (this.libraryId && this.libraryId !== value.library_id || this.generation && this.generation !== value.generation) throw new LocalAPIError('library_scope_changed', 403);
    this.libraryId = value.library_id;this.generation=value.generation;
    return value;
  }
  async reconnect() {
    if (!this.reconnecting) this.reconnecting = (async () => {
      const response = await this.fetcher('/', {credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
      if (!response.ok) throw new LocalAPIError('connection_failed', response.status);
      await this.connect();
    })().finally(() => { this.reconnecting = null; });
    return this.reconnecting;
  }
  async request(path, method = 'GET', body, options = {}) {
    try { return await this.raw(path, method, body, true, options); }
    catch (error) {
      if (error.status !== 401) throw error;
      await this.reconnect();
      return this.raw(path, method, body, true, options);
    }
  }
}

export class PendingWrite {
  constructor(client) { this.client = client; this.operation = null; }
  prepare(path, body) {
    if (this.operation) throw new Error('A save still needs confirmation');
    this.operation = {path, body: JSON.parse(JSON.stringify({...body, operation_id: crypto.randomUUID()}))};
  }
  async send() {
    if (!this.operation) throw new Error('No save to confirm');
    const operation = this.operation;
    try {
      const result = await this.client.request(operation.path, 'POST', operation.body);
      if (result.operation_id !== operation.body.operation_id || result.reference?.library_id !== this.client.libraryId || result.reference?.schema !== 'runteams.local-asset/1' || (operation.body.kind && result.reference.kind !== operation.body.kind) || !/^[a-f0-9]{64}$/.test(result.sha256) || (operation.body.reference && ['schema','id','kind','library_id'].some(key => result.reference[key] !== operation.body.reference[key])) || !Number.isSafeInteger(result.revision) || result.revision < 1) throw new LocalAPIError('invalid_receipt');
      this.operation = null;
      return {receipt: result, body: operation.body};
    } catch (error) {
      // Explicit rejection is final; network/server errors keep the same operation.
      if ([400, 404, 409, 413, 415].includes(error.status)) this.operation = null;
      throw error;
    }
  }
}
