# runteams-runtime 0.1.0 — developer preview

Synchronous SDK for RunTeams JS/TS business helpers. Zero runtime dependencies.
Use the host-injected runtime; no credentials, network client, authoring API or
UI dependencies are provided. Package version 0.1.0 wraps frozen SDK ABI 1.0.0.

```js
import {createRuntime, operationKey} from 'runteams-runtime';
export function run(input, host, context) {
  const rt = createRuntime(host);
  const receipt = rt.data.mutate({
    collection: 'quote',
    mutations: [{id: input.id, base_revision: input.revision, value: input.value}],
    operation_key: operationKey(context.operation_key + ':save'),
  });
  if (receipt.state !== 'confirmed') throw Error('write_unconfirmed');
  return rt.data.query({collection: 'quote', limit: 100});
}
```

The SDK negotiates before a capability's first call and checks the exact frozen
parameter shapes. Only data.query, data.mutate and connection.http are exposed;
availability and permissions remain host/server decisions. connection.http is
conservatively treated as potentially writing because endpoint effects belong
to the trusted host. No unsupported capability is replaced with local data.

Records have string revisions. Runtime operation keys allow 1–128 characters;
UI keys use a different contract. Type parameters describe application data;
they are not runtime validation of that data. The platform validates the declared
model and operation schemas.

RunTeamsError retains code, retry, outcome and operationKey. Transport failure or
invalid replies after a dispatched write have outcome `unknown`. Never retry
with a fresh key or claim a rollback. The SDK has no automatic retries and no
new receipt-query endpoint; recovery must use the platform's existing flow.

Install the supplied local .tgz using npm with `--ignore-scripts`; this package
is private and has not been published to a registry. The current v1 dependency
lock supports unscoped names only. Exact vendored bytes and their digest belong
in the project's dependency lock. Do not edit frozen platform contracts.
