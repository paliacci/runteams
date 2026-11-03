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
export type ViewOperationKey = string & {readonly __viewOperationKey: unique symbol};
export function operationKey(value: string): ViewOperationKey;
export function newOperationKey(): ViewOperationKey;
export type Method = keyof Parameters;
export interface ViewBridge {
  readonly methods: readonly string[];
  call(method: string, params: JsonObject): unknown;
}
export type Reply<T> = {ok: true; result: T} | {ok: false; error: {code: string; retry: Retry}};
export type ObjectReference = Parameters['context.select']['objects'][number];
export interface OperationReceipt<T extends JsonValue = JsonValue> {
  /** Preserve unknown future states; only completed establishes completion. */
  state: string; operation_key: string;
  result?: {data: T; [key: string]: JsonValue};
  [key: string]: JsonValue | undefined;
}
export interface ViewClient {
  readonly version: '0.1.0'; readonly methods: readonly Method[];
  readonly context: {
    read(): Promise<Reply<JsonObject>>;
    select(params: Parameters['context.select']): Promise<Reply<JsonObject>>;
    update(params: Parameters['context.update']): Promise<Reply<JsonObject>>;
  };
  readonly draft: {
    set(params: Parameters['draft.set']): Promise<Reply<JsonObject>>;
    discard(): Promise<Reply<JsonObject>>;
  };
  readonly operation: {
    invoke<T extends JsonValue = JsonValue>(params: Omit<Parameters['operation.invoke'], 'operation_key'> & {operation_key: ViewOperationKey}): Promise<Reply<{receipt: OperationReceipt<T>}>>;
  };
  /** Cancels local waiting; never claims a dispatched business effect rolled back. */
  dispose(): void;
}
export function createViewClient(bridge: ViewBridge, options?: {timeoutMs?: number; signal?: AbortSignal}): ViewClient;
