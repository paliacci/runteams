/** JSON and fixed-contract checks. No I/O, credentials, retries or author schemas. */
export class RunTeamsError extends Error {
  constructor(code, {retry = 'never', outcome = 'not-sent', operationKey, cause} = {}) {
    super(code); this.name = 'RunTeamsError'; this.code = code;
    this.retry = retry; this.outcome = outcome;
    if (operationKey !== undefined) this.operationKey = operationKey;
    if (cause !== undefined) this.cause = cause;
  }
}
export const retries = ['never', 'read', 'reconcile', 'reauthorize'];
export function jsonCopy(value, limit = 16384, maxDepth = 32) {
  const seen = new Set(); let count = 0;
  function visit(item, depth) {
    if (++count > 4096 || depth > maxDepth) throw new RunTeamsError('sdk_json_budget');
    if (item === null || typeof item === 'boolean' || typeof item === 'string') return JSON.stringify(item);
    if (typeof item === 'number' && Number.isFinite(item) && (!Number.isInteger(item) || Number.isSafeInteger(item))) return JSON.stringify(item);
    if (typeof item !== 'object' || seen.has(item)) throw new RunTeamsError('sdk_invalid_json');
    const proto = Object.getPrototypeOf(item);
    if (!Array.isArray(item) && proto !== Object.prototype && proto !== null) throw new RunTeamsError('sdk_invalid_json');
    if (Object.getOwnPropertySymbols(item).length) throw new RunTeamsError('sdk_invalid_json');
    seen.add(item);
    const descriptors = Object.getOwnPropertyDescriptors(item), parts = [];
    if (Array.isArray(item)) {
      if (Object.keys(descriptors).length !== item.length + 1) throw new RunTeamsError('sdk_invalid_json');
      for (let i = 0; i < item.length; i++) {
        const d = descriptors[i];
        if (!d || !d.enumerable || !('value' in d)) throw new RunTeamsError('sdk_invalid_json');
        parts.push(visit(d.value, depth + 1));
      }
    } else {
      for (const [key, d] of Object.entries(descriptors)) {
        if (['__proto__', 'prototype', 'constructor'].includes(key) || !d.enumerable || !('value' in d)) throw new RunTeamsError('sdk_invalid_json');
        parts.push(JSON.stringify(key) + ':' + visit(d.value, depth + 1));
      }
    }
    seen.delete(item);
    return Array.isArray(item) ? '[' + parts.join(',') + ']' : '{' + parts.join(',') + '}';
  }
  // Encode only inspected own values. Never invoke inherited or array toJSON.
  const raw = visit(value, 0);
  if (new TextEncoder().encode(raw).length > limit) throw new RunTeamsError('sdk_json_budget');
  return JSON.parse(raw);
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
export function matches(schema, value) {
  if (schema.anyOf) return schema.anyOf.some(s => matches(s, value));
  if (schema.const !== undefined && value !== schema.const) return false;
  if (schema.enum && !schema.enum.includes(value)) return false;
  const types = Array.isArray(schema.type) ? schema.type : schema.type ? [schema.type] : [];
  if (types.length && !types.some(t => t === 'null' ? value === null : t === 'array' ? Array.isArray(value) : t === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value) : t === 'integer' ? Number.isSafeInteger(value) : typeof value === t)) return false;
  if (typeof value === 'string') {
    const length = Array.from(value).length;
    if (schema.minLength !== undefined && length < schema.minLength || schema.maxLength !== undefined && length > schema.maxLength) return false;
    if (schema.pattern && !(new RegExp(schema.pattern, 'u')).test(value)) return false;
  }
  if (typeof value === 'number' && (schema.minimum !== undefined && value < schema.minimum || schema.maximum !== undefined && value > schema.maximum)) return false;
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems || schema.maxItems !== undefined && value.length > schema.maxItems) return false;
    if (schema.uniqueItems && new Set(value.map(canonical)).size !== value.length) return false;
    if (schema.items && !value.every(v => matches(schema.items, v))) return false;
  } else if (value !== null && typeof value === 'object') {
    if (schema.maxProperties !== undefined && Object.keys(value).length > schema.maxProperties) return false;
    if ((schema.required || []).some(k => !Object.hasOwn(value, k))) return false;
    for (const [key, item] of Object.entries(value)) {
      if (Object.hasOwn(schema.properties || {}, key)) {
        if (!matches(schema.properties[key], item)) return false;
      } else if (schema.additionalProperties === false) return false;
      else if (typeof schema.additionalProperties === 'object' && !matches(schema.additionalProperties, item)) return false;
    }
  }
  return true;
}
export function parameters(schemas, method, value, profile) {
  const frame = profile === 'view' ? {schema: 'runteams.ui-context/2', id: 4096, method, params: value} : {abi: 'runteams.sdk/1', id: 4096, method, params: value};
  const copy = jsonCopy(frame, profile === 'view' ? 20000 : 16384, profile === 'view' ? 16 : 32).params;
  if (!Object.hasOwn(schemas, method) || !matches(schemas[method], copy)) throw new RunTeamsError('sdk_invalid_params');
  return copy;
}
export function hostFailure(error, write, key) {
  // Even a broken transport error object must not make a dispatched write
  // look unsubmitted. Keep the original cause for explicit diagnostics.
  let code, hint;
  try { code = error?.code; hint = error?.retry; } catch { /* Keep conservative outcome. */ }
  const retry = retries.includes(hint) ? hint : write ? 'reconcile' : 'read';
  return new RunTeamsError(typeof code === 'string' ? code : 'sdk_transport_failed',
    {retry, outcome: write ? 'unknown' : 'unavailable', operationKey: key, cause: error});
}
