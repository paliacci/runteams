# Creator product integration

`v1/` is an exact copy of the frozen SDK 1.0.0 contract, including its historical
SPEC/status and provenance manifest. The original isolated sources are unchanged.
`ui-v2/` contains the generic view/context profiles; there is no six-slot taxonomy.
`data-v1/models.schema.json` provides optional explicit collection registration in
`data/models.json`, so business data does not depend on having a custom UI. The
same type/schema may also be referenced by `ui/views.json`; conflicting mappings
and unregistered entries in `project.json.data_models` fail compilation.

## Implemented candidate

Formal backend routes live under `/v1/business/creator/` and use the existing
authenticated actor/workspace dependency. The core/desktop adapter uses the same
business cloud; it cannot fall back to a local business database. Corresponding
core control routes live under `/api/core/creator/`.

- Complete byte trees, author-only read/edit/download, CAS edits and full-tree
  replacement, including deletion. Drafts can temporarily fail compilation.
- Persisted original-key recovery for mutations; changed requests conflict.
- Scoped, digest-verified binary uploads, exact duplicate chunk recovery, expiry
  and per-actor/workspace upload budgets. Large files download through the
  authenticated file endpoint; they are not embedded in SDK frames.
- Immutable validated **source snapshots**, always `executable: false`. These are
  not signed executable releases, marketplace publication or rental entitlements.
- Author-only data preview installations, separate namespaces, model validation,
  atomic batches, CAS/tombstones and scoped cursors. Query filters are JSON
  containment, not SQL. Objects are bounded to 16 KiB; each query page is bounded
  to 120 KiB before response framing. Unchanged key returns the original receipt.
- Trusted offline builds from a frozen source snapshot, Ed25519-signed immutable
  executable artifacts, author-only metadata/download and original-key recovery.
  `POST snapshots/{id}/build` accepts only `operation_key`; build tools and signing
  keys are backend-owned configuration. `GET releases/{id}` returns the signed
  manifest; `GET releases/{id}/artifact?path=...` returns authenticated bytes.
  `artifact_ready` describes frozen build bytes, not a marketplace publication,
  rental entitlement, installed employee or working custom view.

The backend factory accepts an explicit trusted `creator_builder` and
`creator_release_keys`. It does not accept author-submitted builds or configure a
signing key from a source folder. Missing configuration fails closed. The current
builder supports the verified macOS sandbox; a Linux/remote trusted worker and
deployment key provisioning are still pending. Compilation runs outside database
and organization locks, then the HTTP route rechecks live scope and source access
before commit. Concurrent pure builds may repeat computation; a transaction freezes
one set of bytes. A failure before commit can safely rebuild; a committed result
recovers without recompilation even if its response was lost. This rule applies to
pure offline builds, not to external business effects.

The local host coordinator now executes signed operation bytes through the cloud
execution ledger. Within an authorized author execution, the frozen SDK negotiates
`data.query` and (only for a write operation) `data.mutate`. Data mutations and SDK
sequence/reply receipts commit in the same transaction. Mutations return the actual
SDK `Receipt` shape, including the original key and release digest. Other frozen
client methods remain unavailable except the configured connection HTTP path
described below. Generic source/data HTTP
control responses keep their existing shapes; they are not SDK reply envelopes.

Migration `202610200001_creator_system.sql` is additive and restricted to private
Supabase tables. It has only been applied to disposable PostgreSQL in acceptance;
the existing Supabase project and deployed backend remain unchanged. Before
deploying, complete the migration ledger, backup/restore rehearsal, current
organization/revocation integration and runtime cutover checks.

Migration `202610210001_creator_releases.sql` adds the separate immutable artifact
store with RLS and no anonymous/authenticated access. Only disposable PostgreSQL
has been migrated. The candidate release APIs remain author-only until actual
publication/rental authorization and complete product integration have been
accepted. The data SDK available inside an executable author preview does not
advertise the remaining connection/work/event/UI capabilities.

## Author execution candidate

`POST releases/{id}/author-installations` creates a separate, executable author
preview. The earlier source/data preview stays non-executable. This does not grant
marketplace rental, employee or pipeline access. The local `CreatorHostRuntime`
requires explicitly configured helper bytes and trusted release keys; it is not yet
wired into the running app's employee tools or packaged runtime resolver.

The local coordinator requests an execution with an original operation key.
`POST installations/{id}/executions` verifies the current actor, active installation,
signed frozen release, operation input/effect and registered host. Only the first
claim returns execution bytes and permission to start. Repeated pending/unknown
claims never start a replacement process. A different host can read a matching
original claim but cannot issue its SDK calls or finish it. A live installation
allows one pending execution globally; the local scheduler also bounds its queue.

`POST executions/{id}/sdk` accepts the exact frozen frame on a private host channel.
The host credential and account token never reach the guest. Every call verifies
current scope, installation, host ownership, trust root and sequence; changed
replays fail. Read effects cannot gain mutation capability. Original sequence
replies recover without another write. Frame overflow rolls back its SDK data
transaction rather than returning a fabricated small success.

`POST executions/{id}/complete` accepts verified host reporting and validated
business output; completed means the operation ran, with output explicitly wrapped
as `business-data`. It does not promote author fields into platform approvals or
prove semantic task quality. This uses the existing trusted execution-host model;
it is not remote hardware attestation against the owner of the computer. Errors,
cancel, lost data replies and expired pending claims remain unknown. Completed and
unknown receipts are terminal; no automatic replay is allowed. Receipt reads use
`GET executions/{id}` and current authorization. Host bootstrap context exposes
only the original operation key and execution reference for stable child keys.

`POST installations/{id}/deactivate` withdraws author access, marks pending work
unknown and retains cloud data/confirmed effects. It does not erase or undo already
committed writes. Migration `202610210002_creator_execution.sql` records these facts
in private cloud tables with RLS, immutable identity/terminal receipts and a global
one-pending-per-installation constraint. It has only run in disposable PostgreSQL.
The configured connection/effect candidate is described below. Executable upgrades,
organization/rental lifecycle and the UI/chat/product flows remain unfinished.
Connections fail closed by default; deployment must explicitly enable the cloud
service and provision a matching native resolver/transport and exact grant.

## Coordinator recovery candidate

The coordinator now requires a device `RecoveryJournal`. Before a cloud claim it
atomically writes only the actor/workspace/installation/operation/original key,
input digest and optional execution reference, in a bounded private file. It stores
no input body, result, credential or authoritative success. Queued inputs are
copied before execution so later caller edits cannot change the claimed input.

`POST installations/{id}/execution-receipts` is a current-authorized read using
the operation/key/input digest; it also checks the active pinned installation and
current release trust. It supports recovery even if a process died before it could
save the cloud-issued execution ID. `CreatorHostRuntime.recover(reference)` always
uses this cloud lookup and never starts Wasm. A missing cloud record remains a
failure, not local success; any explicitly authorized retry keeps the original key.
Actor/workspace mismatch, modified references, revoked access and cloud failure
cannot return a cached result. The journal is not a permission grant or a business
database. Exact reference fields and a binding digest detect accidental/tampered
files; that digest is not an authentication signature against the device owner.

Actual new coordinator processes have been SIGKILLed before claim, after claim,
after a real SDK data commit and after a completed-result commit. Fresh processes
recover through real TCP/HTTP/PostgreSQL without replay; private helper pipes close
and owned helpers terminate. These are current formal coordinator tests, not
relabelled historical lab tests. This closes the basic local process-crash item;
it does not prove external supplier effects, UI/chat recovery, product task retry
integration, full machine power loss or distribution behavior. Those remain pending.

Implementation state and remaining work: `design/CREATOR_SYSTEM_IMPLEMENTATION.md`.

## Native connection transport foundation

`creator_connection.py` implements a trusted-host HTTPS transport from the frozen
connection descriptor. It validates declared paths/query/body/output, pins the
connection to prevalidated public DNS addresses with original-host TLS checks,
ignores proxy environment, refuses redirects, bounds response bytes and total
network time, and injects only a native credential bound to the exact descriptor,
actor/workspace/installation/release/host metadata and requested scopes. Credentials are never
accepted from guest headers. Exact/JSON-decoded credential reflections are rejected;
this does not promise detection of arbitrary encodings by a malicious supplier.

`ConnectionNotSent` means no application HTTP bytes were sent. Once HTTP sending
starts, every uncertain result is `ConnectionUnknown`, without an automatic retry.
A valid JSON result is raw business data, not a durable confirmed-effect receipt.
The configured native broker now wraps this module in committed cloud claims and
settlements. The transport alone still has no authority or cross-call deduplication.

Real isolated TLS supplier tests keep certificate/hostname verification enabled;
an explicit trusted test supervisor routes one exact test origin to its own
loopback port. Ordinary descriptor/DNS requests cannot enable that route or use
private addresses. This is transport acceptance, not real OAuth/Gmail lifecycle,
live public DNS infrastructure or every production distribution.

## Native SDK connection and external-effect candidate

Migration `202610210003_creator_connections.sql` adds private connection grants,
external-effect receipts and reserved SDK call sequences. It has only run in
disposable PostgreSQL. All bindings include actor/workspace/installation/release/
host/descriptor/scopes. Host-only `bind` accepts metadata after native authorization;
it is **not** an OAuth flow or independent provider identity/scope verification.
The existing trusted registered-host model applies, without hardware attestation.
The engineering resolver provides a synthetic native credential; actual protected
vault/consent/OAuth configuration is still required before live-provider use.

With `creator_connections_enabled=True` and an exact unexpired cloud grant, a
configured `CreatorHostRuntime` negotiates `connection.http`. The native broker
intercepts that frozen frame: private `connection-prepare` commits a first claim
and reserves its sequence, HTTPS runs outside cloud/organization locks, and private
`connection-settle` validates and commits the response plus exact SDK reply. Guest
code sees the frozen `{status,body}` response only after confirmation commits.
`connection.status`, `connection.request`, `operation.receipt` and other unimplemented
methods are not negotiated. A host without the native transport/resolver filters
the HTTP capability and rejects a required HTTP negotiation.

Only the first claim returns `send:true`; duplicate or lost-claim responses cannot
resend. Same key with changed request/release conflicts. A separate execution can
recover the same confirmed HTTP reply without a supplier call. A proven no-send
failure is `failed`; currently it allows receipt reads, not an automatic same-key
retry. Unknown/pending effects never regrant a send. Trusted supplier reconciliation
and explicit recovery decisions remain unimplemented; a guest's claimed object
match cannot promote unknown to confirmed.

Revocation/rebinding invalidates the prior grant and marks its pending effects
unknown; an already-issued external effect can still happen. A later successful
supplier response cannot manufacture authorized success after that revocation.
Installation deactivation additionally stops access, while confirmed effects/data
are retained. Pending calls block later SDK calls and false program completion;
execution expiry/cancel/error preserves unknown. Confirmed effect receipts survive
an unknown outer program result. Author business output remains `business-data`.

Private control endpoints live on author-preview installations under
`connections/{key}/bind|revoke` and executions under `connection-prepare`,
`connection-settle`, and `connection-receipts`. They are not forwarded as guest
source/data methods or exposed through the core page router. The application still
needs employee-tool/resource provisioning, protected OAuth/vault integration and
UI/chat/publish/rental flows. Default server configuration is disabled; no existing
deployment or Supabase project has been changed. Current real Wasm/TLS/cloud and
process-boundary acceptance is recorded in the formal implementation evidence.

## Web artifact closure candidate

The offline builder now compiles HTML-referenced JS/TS/JSX/TSX/CSS, inline scripts
and styles, imported images/fonts/media, and local HTML navigation into the signed
web artifact set. Exact dependency aliases resolve only declared package sources,
with full source hashes and package name/version checks. The same aliases work in
business Wasm. Compiler inputs must be UI files, explicit public assets, locked
dependency sources or trusted extracted inline entries. No author build scripts,
plugins or network run during construction. Source folders stay complete and are
never replaced with generated bundle files.

`VerifiedWebBundle` verifies release bytes and serves an immutable web-only set
with correct MIME, no-store, nosniff and restrictive CSP. A mandatory trusted
authorization callback runs on every asset request; failure never returns cached
success. It is not itself a cloud permission/lease service. The application must
still wire current actor/installation/release authorization, isolate the actual
native author WebView, bind its sender role/epoch and clear it after access loss.
Assets mount at a dedicated author origin's `/views/` root, with no platform APIs
or account cookies there. No frozen UI/context methods are advertised by this
byte-only provider.

Current limits: 500 artifacts/32 MiB; 512 KiB per HTML, 128 HTML documents, 64-link
depth, 100000 parse events and the existing build deadline. Remote resources,
import maps, inline event attributes, inline style resource URLs, workers/nested
frames, query cache-busting and arbitrary Node/native build plugins are unsupported
or rejected. Runtime-computed assets must already exist in the signed set. This
does not limit business UI categories or introduce fixed author business states.

Two different engineering works with real Decimal versions render and interact
in separate Chrome origins, including styles/images, multiple HTML pages, narrow/
wide and light/dark views, keyboard focus, per-origin JS/CSS/storage and CSP denying
cross-work network before a request reaches the other server. The browser uses a
private disposable profile with Chromium sandbox enabled. This proves current web
construction/rendering, not the native WK sender bridge, hung-UI isolation, Chat
context, current cloud UI authorization or creator/publish/rental product flows.
Those remain pending; no production surface or deployment has been changed.

## Formal native component (2026-10-21)

Current desktop/creator/CreatorWebHost.swift passes actual sender/epoch/physical-slot/deadline/revocation/hang/flood/remount probes with these signed UI artifacts. Its default UI method set is empty; the engineering context.read callback is synthetic, not a cloud/context SDK implementation. The installed application/build script does not yet load it. Current cloud UI authority, protected Chat snapshots and UI-to-business wiring remain pending. No frozen machine contract is changed.

Independent nonpersistent stores/views are tested on the recorded macOS. WKProcessPool multi-instance configuration has no isolation effect according to the current Apple SDK/documentation; no universal process allocation or memory/capacity guarantee is implied. See desktop/creator/README.md and design/evidence/creator-formal-native-ui-20261021/verification.json.

## Formal cloud UI context source (2026-10-21)

CreatorContexts implements the frozen five context/draft calls with current host/actor/workspace/installation/release/view/real saved Chat binding, CAS, epoch/sequence receipts and private immutable context snapshots. It serves only currently authorized verified web assets. Private native control APIs are separate from the frozen business SDK19 methods; there are no author credentials or Chat submission privileges. view.open/operation.invoke are not negotiated as page methods. Deployment requires explicit creator_ui_enabled (default false).

Snapshots return message_persisted=false and do not create a product Chat message. Native mounting, generic operation dispatch through the existing coordinator and actual Chat/Agent/product acceptance remain pending. The request/snapshot v2 machines and v1 business SDK are unchanged. UI aliases identify original business IDs without granting access; string data revisions remain intact and unrepresentable UI integers fail explicitly. See the current implementation/progress and creator-formal-ui-context evidence.

## 可信作者文件夹入口（2026-10-21，正式候选）

现行员工设计会话可持有平台生成的 creator_project_id 与独立创建意图。可信设计工具及文件编辑器使用同一作者源树；这些是平台源控制入口，不是作品页面的新 SDK 能力。冻结 v1、UI v2 和已协商的六方法不变。

- GET projects/{id} 返回当前修订/文件摘要和仅针对相同 source digest 的源码快照检查投影。
- POST projects/{id}/edits 的 base_revision、operation_key、changes 原子修改/删除文件；每项只能给 content_base64（null 删除）或当前作者/项目下已完成的 blob_ref。源树仍按 500 文件/32 MiB 总预算检查。允许不合法中间草稿；快照必须重新 compile_source。
- GET projects/{id}/edits?operation_key=... 只核对原回执，不提交编辑。无回执仍 unknown。
- 原 source.beginUpload/uploadChunk/finishUpload 承担较大资源；source.edit 在同一写事务复验 blob 归属、完成与期限。

每次读取/下载/回执都校验当前 workspace/actor/作者；restricted 完结身份拒绝，回执不是授权。生成的源结构快照不是 employee/pipeline 编译或市场 release。创建结果未知的产品恢复入口尚未完成，不能宣称仅靠原键重 POST 已验收完整恢复。市场发布/租用、正式源编译和旧有效员工映射继续待接。

## 完整作者来源与产品定义编译（2026-10-21）

新创作模板采用 employee-source/2：明确稳定 key、name/avatar、soul_file、skill_dirs 和可移植 runtime_requirement，不保存本机渠道或修订ID。pipeline-source/2 使用现有可移植流水线拓扑，employees 的 ref/source 明确引用同一源树中的员工文件。机器合同由 creator_definitions.author_schema 从现有 product-model/v2 与 marketplace-pipeline/v2 生成；没有第二套 work 字段。标准技能 SKILL.md/runteams.json 及所有引用的实际资源共同编译，同名技能在一个作品中必须有相同字节摘要。无 work 的标准方法可暂存，不能因此编译成可派工工作。

固定 v1/FROZEN 字节未改；已有 v1 工程/冻结执行来源仍能读取和构建，不得经新产品编译入口冒称完整定义。

POST /v1/business/creator/projects/{id}/compilations 接受 base_revision/operation_key，复用不可变快照和原离线可信构建器。生成 definitions/creator.json（target=product-model/v2），包含确切来源摘要、现有市场员工和流水线合同的可移植定义、原始技能字节及摘要。产物与 web/Wasm 同属一个签名清单，服务在提交前从冻结源码独立派生并比较，构建期间不持组织锁。构建身份包含来源/定义编译、标准技能与市场实现及机器合同摘要。

GET 同一路径加 operation_key 只核对原快照/构建回执，不编译、安装或重放写入。受限完结身份不能读取作者定义/构建回执。完整定义需要版本声明，已冻结版本不能换字节；冲突明确要求更新来源版本。当前来源摘要变化后，项目不再显示旧编译为当前有效。

可信当前创作工具新增 schema、compile、compilationReceipt；用户仍在原 Chat/完整资产编辑器中工作。compile 只冻结可移植定义及签名产物，尚不分配本机员工/流水线ID，不创建正式 runtime release、市场授权、安装或租用。实际安装时继续使用现有 compile_employee_release/MarketplaceInstaller 及同一云事务；这一步的产品接线仍未完成。作者页面的冻结 SDK、六个已有通用桥方法、执行器和消息账本保持。


### Product author installation (candidate, 2026-10-21)

POST `projects/{id}/product-installations` accepts only release_id, original operation_key and host-resolved runtime snapshots keyed by signed employee source paths. The authenticated server derives all definitions and IDs from the verified catalog, checks current author/source, serializes on the business account and atomically writes immutable product skills/releases, pinned pipeline releases, executable installation/mapping and receipt. GET of the same path with operation_key checks the original receipt without mutation; epoch, active installation and installed resources remain checked. This is author access, not marketplace entitlement. Source editing remains through the full folder. Same-version repeats reuse original IDs; different-release upgrades are explicitly unavailable until data and old-task compatibility are implemented. Migration 202610210011 is not deployed.


## 当前新创作合同：独立业务与完整随包员工（2026-10-21）

用户最新决定覆盖前文 /2 新创作入口和独立技能安装映射要求。当前 employee-source/3、pipeline-source/3、package-extension/v3、skill-revision/v3、work-unit/3、employee-release/v4；规范见 ../../design/CREATOR_EMPLOYEE_BUNDLE_CONTRACT.md。新编译 target 为 employee-bundle/v1。员工版本自带完整技能资源，安装不创建全局技能记录，运行/恢复/导出不回查外部产品技能。旧 schema 与已冻结合同只保留历史校验，不自动改写历史发布。SDK v1/FROZEN 与历史实验文件不改，官方 Runtime 扩展基线不变。
