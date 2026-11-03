import {RunTeamsError, jsonCopy, parameters, hostFailure} from './internal/guards.js';
import {requests} from './internal/requests.js';
export {RunTeamsError};
export const sdkVersion = '0.1.0';

export function operationKey(value) {
  if (typeof value !== 'string' || !value.length || Array.from(value).length > 128) throw new RunTeamsError('sdk_invalid_operation_key');
  return value;
}

/** Adapt the injected synchronous runtime. Does not create a network client. */
export function createRuntime(host) {
  if (!host || host.version !== '1.0.0' || typeof host.negotiate !== 'function') throw new RunTeamsError('sdk_runtime_unavailable');
  let available = Object.freeze([]);
  function negotiate(required = []) {
    const params = parameters(requests, 'system.negotiate', {sdk: '1.0.0', required}, 'runtime');
    let result;
    try { result = host.negotiate(params.required); }
    catch (error) { throw hostFailure(error, false); }
    if (!result || result.sdk !== '1.0.0' || !Array.isArray(result.capabilities) || !result.capabilities.every(v => typeof v === 'string')) throw new RunTeamsError('sdk_invalid_reply');
    const copied = jsonCopy(result);
    if (required.some(m => !copied.capabilities.includes(m))) throw new RunTeamsError('sdk_capability_unavailable');
    available = Object.freeze(copied.capabilities.filter(m => ['data.query', 'data.mutate', 'connection.http'].includes(m)));
    return Object.freeze({sdk: '1.0.0', capabilities: available});
  }
  function call(method, input) {
    const params = parameters(requests, method, input, 'runtime');
    const [group, name] = method.split('.');
    if (typeof host[group]?.[name] !== 'function') throw new RunTeamsError('sdk_capability_unavailable');
    if (!available.includes(method)) negotiate([method]);
    const write = method !== 'data.query';
    let result;
    try { result = host[group][name](params); }
    catch (error) { throw hostFailure(error, write, params.operation_key); }
    try {
      const copied = jsonCopy(result);
      if (method === 'data.query' && (!Array.isArray(copied?.items) || !(copied.next_cursor === null || typeof copied.next_cursor === 'string') || !copied.items.every(r => r && typeof r.id === 'string' && typeof r.revision === 'string' && r.value !== null && typeof r.value === 'object' && !Array.isArray(r.value)))) throw Error('query shape');
      if (method === 'data.mutate' && (!copied || !['pending', 'confirmed', 'unknown', 'canceled', 'failed'].includes(copied.state) || copied.operation_key !== params.operation_key || typeof copied.release_digest !== 'string')) throw Error('receipt shape');
      if (method === 'connection.http' && (!copied || !Number.isSafeInteger(copied.status) || !Object.hasOwn(copied, 'body'))) throw Error('http shape');
      return copied;
    } catch (cause) {
      throw new RunTeamsError('sdk_invalid_reply', {retry: write ? 'reconcile' : 'read', outcome: write ? 'unknown' : 'unavailable', operationKey: params.operation_key, cause});
    }
  }
  return Object.freeze({version: sdkVersion, negotiate,
    get capabilities() { return available; },
    data: Object.freeze({query: p => call('data.query', p), mutate: p => call('data.mutate', p)}),
    connection: Object.freeze({http: p => call('connection.http', p)})});
}
