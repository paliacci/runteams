# Complete employee folders

Read machine contracts through `runteams_creator_source`: `schema` supplies
employee/pipeline/skill sources; `reference` supplies project, dependencies,
models, views, ui_request, ui_snapshot, connection, sdk_methods and sdk_types.
These are the installed validator/SDK bytes, without a repository dependency.

Keep the root project key and dependency lock root identical. Every employee's
skill_dirs contains complete standard skills (SKILL.md, runteams.json and all
referenced scripts/references/assets). Work declarations belong in runteams.json.
Use no external skill revision IDs or platform business module dependencies.
No pipeline is required for an employee. Compile freezes the entire exact tree.

## Business programs and cloud data

Declare each operation in project.json, with exact input/output JSON schema
paths, JS handler, allowed actors, effect and optional connection. The handler
exports `function run(input, rt, context)`. It runs synchronously in signed Wasm;
it has no browser, filesystem, network, environment or credential access. Imports
must resolve to files bundled in the exact source tree/dependency closure.
The host supplies rt; do not import or manufacture a transport. Negotiate the
required SDK capabilities before using them. `data.query` and write-effect
`data.mutate` are implemented; connection methods require an actual configured,
authorized connection. The existence of other frozen SDK methods does not make
them available. Missing capabilities fail; never fake successful business data.

Register collections in data/models.json (models reference) or ui/views.json.
project.json.data_models lists their schema files. A collection/type maps to one
schema consistently. Query returns `{items:[{id,revision,value}],next_cursor}`;
revision is a string. Mutate uses an original operation_key and a mutations array
with id, base_revision (null only for a new object) and value. The returned SDK
receipt state must be `confirmed` before reporting a saved result. Derive stable
child keys from context.operation_key. A conflict requires a fresh read and a
user decision, never an overwrite. Unknown effects require original receipt
reconciliation; never silently repeat them with a new key.

## Custom work views

ui/views.json registers named views, models and operations. View capabilities
must explicitly include only needed generic calls. The desktop isolates the
view in its own native web host. Its sole product bridge is
`await window.runteamsUI.call(method, params)`; available methods are listed in
`window.runteamsUI.methods`. The returned value is an envelope: check `ok`, then
read `result`; errors are not successful data. Do not use platform globals,
direct fetch to private APIs, cookies or credentials. In an ordinary browser
without this bridge show a clear host-required state, without fabricated data.

Read exact parameter shapes in ui_request. `context.read` returns result with
context_ref, context_revision, selected, focus, data and objects. Each object has
a UI reference (type/id/integer revision), data, and deleted state. These UI ids
are opaque; they differ from business collection object IDs. Use returned refs
unchanged for context.select and operation.invoke.objects. context.select uses
base_context, objects and focus; context.update uses base_context and data.
These update the working context, not business records.

`operation.invoke` uses operation, input, objects and an original operation_key.
Its reply is `{ok:true,result:{receipt}}` or `{ok:false,error:{code,retry}}`.
An executed host operation has `receipt.state === "completed"`; its validated
handler output is `receipt.result.data` (wrapped as business-data). Pending or
unknown host receipts are not completed operations. This is distinct from the
data SDK's inner mutation receipt: inside Wasm, `rt.data.mutate` confirms its
write with `state === "confirmed"`. Do not test a host operation for "confirmed"
or treat its result wrapper as the handler output. A handler may itself return
a business `state`; interpret that only after checking the outer host receipt.
Use a read
operation to list current collection records and a write operation for saves;
UI code never directly calls the data SDK. An operation result is business data,
not platform authority. Keep IDs/revisions from actual reads when editing.
`draft.set` prepares operation/input for Chat; it does not execute or send Chat.
Only the trusted composer sends. Refresh on `runteams:context-changed` and offer
an explicit refresh action. Show errors, saving, unknown and revoked states.

Keep Chat central. A work view should make the current result inspectable and
editable with a small set of useful controls. Avoid process logs or developer
contracts in user-facing views. Author source permissions default to author;
public_files opens only the explicitly listed assets to renters for reading.

Check and compile the current source revision. Neither proves successful work,
publication, installation or rental. Those require the product's own actions
and actual execution with current authorization.
