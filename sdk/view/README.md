# runteams-view 0.1.0 — developer preview

Async SDK for RunTeams custom Web views. Zero runtime dependencies. Bind the
current document's host bridge explicitly; there is no implicit fixture fallback.

```js
import {createViewClient, newOperationKey} from 'runteams-view';
const view = createViewClient(window.runteamsUI);
const key = newOperationKey(); // persist with input through your host's recovery flow
const reply = await view.operation.invoke({
  operation: 'save-quote', input: { /* declared operation input */ },
  objects: [], operation_key: key,
});
if (!reply.ok) throw Error(reply.error.code);
if (reply.result.receipt.state === 'completed' && reply.result.receipt.result) {
  console.log(reply.result.receipt.result.data);
}
// Dispose when this view/document/account binding is invalidated.
window.addEventListener('pagehide', () => view.dispose(), {once: true});
```

Supported groups are context.read/select/update, draft.set/discard, and
operation.invoke. Each call also checks bridge.methods. view.open, data access,
authoring, Chat sending and approval are not public methods of this package.
Context draft changes are not business saves. Context and object revisions use
safe integers; collection revisions in the runtime SDK are strings.

Use newOperationKey() or operationKey(text). UI keys must start with a lower-case
letter and use at most 64 lower-case letters, digits or hyphens. A raw UUID can
start with a digit and is not always valid. Input is checked against types and
validators generated from the same frozen ui-v2 schema.

Host replies preserve their success/error branches and unknown error codes.
Local preflight failures reject with RunTeamsError and outcome `not-sent`.
Timeout, disposal, transport errors and invalid responses after a possible
write reject with outcome `unknown` and the original operationKey. Closing a
client only stops local waiting; it does not roll back the platform operation.
Late results never resolve disposed/timed-out calls. No write is retried.

Default timeout is 30 seconds, configurable from 1 ms to 5 minutes. AbortSignal
invalidates the complete binding. The caller must bind a new client after a
document or identity change. The trusted native bridge remains responsible for
real account/epoch/permission checks. Client checks cannot grant authorization.

The SDK does not persist pending intents or implement receipt recovery itself.
Type parameters describe application output; runtime output validation remains
the platform's declared schema. Private local package, not registry-published.
