import type {Parameters, JsonObject, JsonValue} from './internal/requests.js';
export type {Parameters, JsonObject, JsonValue};
export type Retry = 'never' | 'read' | 'reconcile' | 'reauthorize';
export class RunTeamsError extends Error {
  constructor(code: string, options?: {retry?: Retry; outcome?: 'not-sent' | 'unknown' | 'unavailable'; operationKey?: string; cause?: unknown});
  readonly code: string; readonly retry: Retry;
  readonly outcome: 'not-sent' | 'unknown' | 'unavailable';
  readonly operationKey?: string; readonly cause?: unknown;
}
export const sdkVersion: '0.1.0';
export type RuntimeOperationKey = string & {readonly __runtimeOperationKey: unique symbol};
export function operationKey(value: string): RuntimeOperationKey;
export interface RuntimeHost {
  readonly version: '1.0.0';
  negotiate(required: string[]): unknown;
  data: {query(params: Parameters['data.query']): unknown; mutate(params: Parameters['data.mutate']): unknown};
  connection?: {http(params: Parameters['connection.http']): unknown};
}
export interface RecordValue<T extends JsonObject = JsonObject> {id: string; revision: string; value: T;}
export interface DataPage<T extends JsonObject = JsonObject> {items: RecordValue<T>[]; next_cursor: string | null;}
export interface MutationReceipt {
  state: 'pending' | 'confirmed' | 'unknown' | 'canceled' | 'failed';
  operation_key: string; release_digest: string; result?: JsonValue;
}
export interface Runtime {
  readonly version: '0.1.0'; readonly capabilities: readonly string[];
  negotiate(required?: string[]): {readonly sdk: '1.0.0'; readonly capabilities: readonly string[]};
  readonly data: {
    query<T extends JsonObject = JsonObject>(params: Parameters['data.query']): DataPage<T>;
    mutate(params: Omit<Parameters['data.mutate'], 'operation_key'> & {operation_key: RuntimeOperationKey}): MutationReceipt;
  };
  readonly connection: {http(params: Parameters['connection.http']): {status: number; body: JsonValue}};
}
export function createRuntime(host: RuntimeHost): Runtime;
