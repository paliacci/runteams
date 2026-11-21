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
parameter shapes. Availability and permissions remain host/server decisions.
connection.http is
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

### 员工 MCP 运行时

在员工自己的 Node MCP 工具中调用 `createRuntime(globalThis.runteamsRuntimeHost)`。用 `rt.application.status({application: 'composio:gmail'})` 查看员工当前选中的连接，用 `rt.application.call({application, tool, arguments, operation_key})` 通过同一连接调用工具。应用连接在员工设置中管理。状态返回不透明的 `binding_key`，可用于按账号区分业务数据。调用未知时沿用原操作键核对，避免重复执行。

声明在员工配置 `managed_resources` 中的集合可通过 `rt.data.query` 分页读取，并用 `rt.data.mutate` 原子批量写入。新建使用 `base_revision: null`，更新使用查询得到的版本。若 `result.ok` 为 false，重新读取后处理版本冲突。当前本机实现支持顺序分页、创建及更新，拒绝非空过滤与删除请求。工作台、对话和定时任务以同一个员工身份及兼容的集合声明读写数据。

应用调用的 SDK 响应上限为 4 MiB。上游若返回的数据超过限制，可缩小读取范围。集合写入每批最多 100 条、96 KiB，单条记录最多 64 KiB。

应用调用和数据写入只在已受理的 MCP 工具调用内可用。未声明原生凭据的工作台工具可同时用 `annotations.readOnlyHint: true` 和 `_meta["runteams/employeeSdkReadOnly"]: true` 免除逐次确认，宿主将这类调用限制为查询本机员工数据和查看应用连接状态。其余工作台工具使用原有确认。无论工具注解，首次运行本机程序均须获得运行授权。
