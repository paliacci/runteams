# Shared UI and host composition

The local application owns its core and shared UI. A separate distribution can
reuse these renderers by registering host services before first paint. The shared
UI does not identify a distribution or carry an account, billing, marketplace or
update implementation that a local build merely hides.

## Ownership

Keep common settings, controls, conversation rendering, employee windows,
documents and pipelines here. Each host owns its session validation, extra
settings, navigation, route descriptors, specialized pages, provider protocols,
styles and illustrations. The local build reads only files in this repository.

`web/ui/host.js` declares the ports. The local entry in
`frontend/community/application.js` connects the actual library transport and
settings transactions. Other hosts supply their own entry; they cannot be
enabled by changing a front-end version flag.

| Port | Contract |
| --- | --- |
| `session` | Current scope, cache identity, display identity and receipt validation |
| `settings` | Extra panels, navigation and acknowledged preference reads/writes |
| `routes` | Extra route interpretation and navigation handlers |
| `pages` | Extra first-paint pages, loading shapes and empty/error presentation |
| `shell` | Navigation descriptors, footer and window presentation |
| `resources` / `assets` | Host resource adapters and optional detail views |
| `workspace` | Host storage and restored-window state |
| `lifecycle` / `sidebar` | Boot, rendering and attention projections |

The HTML has explicit host-prelude and host-components slots. It names only
shared assets. Hosts compose their inputs through these slots; they do not rewrite
function bodies, copy the shared application, or strip hidden business code from
a local release.

## Settings and identity

Settings navigation is derived from panels that actually exist. Unknown panel
names, including inherited object properties, resolve to general settings.
Preference operations use one registered provider and require an exact success
receipt. A response from a retired scope cannot restore that scope's settings.

The session port describes presentation and partitioning. It grants no access.
Library checks and every host's authoritative backend checks remain required.
Stateful operations must retain the original scope/generation checks and retry
semantics when moved between owners.

## Boundary checks

Run `python -B -m runteams_core.devtools.check_ui_boundary` for all UI source,
including files absent from the HTTP manifest. The same checker runs during wheel
construction. CI independently inspects the built wheel and tests host isolation,
registered panels, stale reads and confirmed writes.

The check rejects known private implementation symbols, account-provider access,
commercial route literals and edition switches. It supplements code review;
pattern checks cannot prove the absence of every possible future implementation.

Portable asset schemas retain their published names, including historical
`marketplace` names used by the SDK compiler. Model vendors' plugin catalogs and
subscription labels describe users' local tools. These are shared interoperability
contracts, not product-account or paid-access implementations, and must not be
removed by a blanket keyword filter.

Public Git history remains public. Moving an implementation into a private owner
does not make previously published revisions confidential. Client code delivered
with any distribution is also inspectable; secrets and authoritative service
policy belong on the server.

Return to [architecture](architecture.md).
