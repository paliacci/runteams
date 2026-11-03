// Generated from the frozen ui-v2/request.schema.json.
export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
export interface JsonObject { [key: string]: JsonValue; }
export interface Parameters {
  "context.read": Record<string, never>;
  "context.select": { "base_context": number; "objects": Array<{ "type": string; "id": string; "revision": number }>; "focus": { "type": string; "id": string; "revision": number } | null };
  "context.update": { "base_context": number; "data": JsonObject };
  "draft.set": { "operation": string; "input": JsonObject };
  "draft.discard": Record<string, never>;
  "operation.invoke": { "operation": string; "input": JsonObject; "objects": Array<{ "type": string; "id": string; "revision": number }>; "operation_key": string };
}
