import {RunTeamsError, jsonCopy, parameters, retries, hostFailure} from './internal/guards.js';
import {requests} from './internal/requests.js';
export {RunTeamsError};
export const sdkVersion = '0.1.0';
const methods = Object.keys(requests);

export function operationKey(value) {
  if (typeof value !== 'string' || value.length > 64 || !/^[a-z]/.test(value) || /[^a-z0-9-]/.test(value)) throw new RunTeamsError('sdk_invalid_operation_key');
  return value;
}
export function newOperationKey() {
  if (!globalThis.crypto || typeof globalThis.crypto.randomUUID !== 'function') throw new RunTeamsError('sdk_random_unavailable');
  return operationKey('op-' + globalThis.crypto.randomUUID());
}

/** One document binding. No automatic write retries or simulated fallback. */
export function createViewClient(bridge, {timeoutMs = 30000, signal} = {}) {
  if (!bridge || typeof bridge.call !== 'function' || !Array.isArray(bridge.methods)) throw new RunTeamsError('sdk_host_unavailable');
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 300000) throw new RunTeamsError('sdk_invalid_timeout');
  let closed = false;
  const pending = new Set();
  function dispose() {
    if (closed) return;
    closed = true;
    signal?.removeEventListener('abort', dispose);
    for (const cancel of [...pending]) cancel();
  }
  signal?.addEventListener('abort', dispose, {once: true});
  if (signal?.aborted) dispose();
  function call(method, input = {}) {
    let params;
    try {
      if (closed) throw new RunTeamsError('sdk_client_closed');
      params = parameters(requests, method, input, 'view');
      if (!bridge.methods.includes(method)) throw new RunTeamsError('sdk_capability_unavailable');
    } catch (error) { return Promise.reject(error); }
    const write = method !== 'context.read', key = params.operation_key;
    return new Promise((resolve, reject) => {
      let settled = false, dispatched = false;
      function finish(fn, value) {
        if (settled) return;
        settled = true; clearTimeout(timer); pending.delete(cancel); fn(value);
      }
      function interrupted(code) {
        return new RunTeamsError(code, {retry: dispatched && write ? 'reconcile' : 'read',
          outcome: dispatched && write ? 'unknown' : dispatched ? 'unavailable' : 'not-sent', operationKey: key});
      }
      const cancel = () => finish(reject, interrupted('sdk_client_closed'));
      const timer = setTimeout(() => finish(reject, interrupted('sdk_timeout')), timeoutMs);
      pending.add(cancel);
      let answer;
      try { dispatched = true; answer = bridge.call(method, params); }
      catch (error) { finish(reject, hostFailure(error, write, key)); return; }
      Promise.resolve(answer).then(raw => {
        if (settled) return;
        try {
          const reply = jsonCopy(raw, 131072, 32);
          if (!reply || typeof reply.ok !== 'boolean') throw Error('envelope');
          if (reply.ok) {
            if (!Object.hasOwn(reply, 'result') || Object.hasOwn(reply, 'error') || !reply.result || typeof reply.result !== 'object' || Array.isArray(reply.result)) throw Error('envelope');
            if (method === 'operation.invoke') {
              const receipt = reply.result?.receipt;
              if (!receipt || typeof receipt.state !== 'string' || receipt.operation_key !== key) throw Error('receipt');
              if (receipt.state === 'completed' && (!receipt.result || !Object.hasOwn(receipt.result, 'data'))) throw Error('completed receipt');
            }
          } else if (!reply.error || typeof reply.error.code !== 'string' || !retries.includes(reply.error.retry) || Object.hasOwn(reply, 'result')) throw Error('error');
          finish(resolve, reply);
          if (!reply.ok && (reply.error.retry === 'reauthorize' || reply.error.code === 'ui_stale_epoch')) dispose();
        } catch (cause) {
          finish(reject, new RunTeamsError('sdk_invalid_reply', {retry: write ? 'reconcile' : 'read', outcome: write ? 'unknown' : 'unavailable', operationKey: key, cause}));
        }
      }, error => finish(reject, hostFailure(error, write, key)));
    });
  }
  return Object.freeze({version: sdkVersion,
    get methods() { return Object.freeze(closed ? [] : methods.filter(m => bridge.methods.includes(m))); },
    context: Object.freeze({read: () => call('context.read'), select: p => call('context.select', p), update: p => call('context.update', p)}),
    draft: Object.freeze({set: p => call('draft.set', p), discard: () => call('draft.discard')}),
    operation: Object.freeze({invoke: p => call('operation.invoke', p)}), dispose});
}
