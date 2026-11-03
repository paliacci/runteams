// Generated from the frozen v1/methods.json.
export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
export interface JsonObject { [key: string]: JsonValue; }
export interface Parameters {
  "system.negotiate": { "sdk": "1.0.0"; "required": Array<string> };
  "data.query": { "collection": string; "limit": number; "cursor"?: string | null; "filter"?: JsonObject };
  "data.mutate": { "collection": string; "mutations": Array<{ "id": string; "base_revision": string | null; "value": JsonObject | null }>; "operation_key": string };
  "connection.http": { "connection": string; "endpoint": string; "path_params"?: {[key: string]: string}; "query"?: {[key: string]: string | number | boolean}; "body"?: JsonObject | null; "operation_key"?: string };
}
