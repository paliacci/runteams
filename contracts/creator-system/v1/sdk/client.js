/* RunTeams SDK 1.0.0. JSON transport only; no ambient I/O or credentials. */
function createRunTeamsSDK(transport) {
  if (typeof transport !== 'function') throw new TypeError('transport_required');
  const abi = 'runteams.sdk/1', maxBytes = 16384;
  let sequence = 0;
  function encode(value) {
    const visited = new Set();
    function check(v, depth) {
      if (depth > 32) throw new TypeError('json_depth_limit');
      if (v === null || typeof v === 'string' || typeof v === 'boolean') return;
      if (typeof v === 'number' && Number.isFinite(v) && (!Number.isInteger(v) || Number.isSafeInteger(v))) return;
      if (typeof v !== 'object' || visited.has(v)) throw new TypeError('invalid_json');
      const tag = Object.prototype.toString.call(v);
      if (tag !== '[object Object]' && tag !== '[object Array]') throw new TypeError('invalid_json');
      visited.add(v);
      if (Array.isArray(v)) { for (let i=0; i<v.length; i++) { if (!(i in v)) throw new TypeError('invalid_json'); check(v[i],depth+1); } }
      else for (const key of Object.keys(v)) { if (['__proto__','prototype','constructor'].includes(key)) throw new TypeError('invalid_json'); check(v[key],depth+1); }
      visited.delete(v);
    }
    check(value,0);
    const json = JSON.stringify(value);
    if (new TextEncoder().encode(json).length > maxBytes) throw new TypeError('frame_limit');
    return json;
  }
  function call(method, params) {
    const id = ++sequence;
    const request = JSON.parse(encode({abi,id,method,params}));
    const reply = transport(request);
    // Validate before handing any value to application code. Authorization and
    // per-method schemas remain the trusted host's responsibility.
    encode(reply);
    const keys = Object.keys(reply).sort().join(',');
    if (reply.abi !== abi || reply.id !== id || typeof reply.ok !== 'boolean' ||
        keys !== (reply.ok ? 'abi,id,ok,result' : 'abi,error,id,ok')) throw new Error('invalid_reply');
    if (!reply.ok) {
      if (!reply.error || Object.keys(reply.error).sort().join(',') !== 'code,retry' ||
          typeof reply.error.code !== 'string' || !['never','read','reconcile','reauthorize'].includes(reply.error.retry)) throw new Error('invalid_reply');
      const error = new Error(reply.error.code); error.code=reply.error.code; error.retry=reply.error.retry; throw error;
    }
    return reply.result;
  }
  const bind = method => params => call(method,params);
  return Object.freeze({version:'1.0.0',
    negotiate: required => call('system.negotiate',{sdk:'1.0.0',required}),
    source:Object.freeze({list:bind('source.list'),read:bind('source.read'),write:bind('source.write'),beginUpload:bind('source.beginUpload'),uploadChunk:bind('source.uploadChunk'),finishUpload:bind('source.finishUpload')}),
    data:Object.freeze({query:bind('data.query'),mutate:bind('data.mutate')}),
    connection:Object.freeze({status:bind('connection.status'),request:bind('connection.request'),http:bind('connection.http')}),
    operation:Object.freeze({invoke:bind('operation.invoke'),receipt:bind('operation.receipt')}),
    work:Object.freeze({dispatch:bind('work.dispatch'),status:bind('work.status')}),
    events:Object.freeze({poll:bind('events.poll')}),
    host:Object.freeze({openResult:bind('host.openResult'),requestDecision:bind('host.requestDecision')})});
}
