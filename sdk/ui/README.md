# RunTeams UI Kit · Module presentation

`runteams-ui@0.1.0` is a private local development package. It delivers one generic module pattern: collapsible panel content → full workspace → return. It contains no calendar, mail or other business model.

## Delivered and deferred

- Shared Section and full-workspace components, two-mode composition with one live content node.
- Independent presentation client and a working standalone preview adapter.
- Generated light/dark foundations from `design/ui-tokens.json`; same component source available to platform consumers in `packages/ui-components/`.
- Public top drawer-toolbar template with a fixed collapse control and optional custom text/actions, including updates and cleanup. Use it directly in standalone hosts; the native platform mounts this same component for `createHostControls(...).setHeader(...)`.
- Native platform source now supplies optional display metadata and theme updates through `window.runteamsHost`; the UI Kit binds them with `connectHostTheme`. This passed a real native WebView/SDK/Wasm engineering test with fixture authority and data. The installed application has not been updated.
- **Native presentation and header-extension source bridges are integrated and fixture-tested; installed-app and real-account acceptance remain pending.** The frozen business `ui-v2` bridge is unchanged. No platform deployment or full component migration is claimed.

## Platform theme binding

```js
import {connectHostTheme} from 'runteams-ui';
const binding = connectHostTheme(window.runteamsHost);
// On document teardown:
binding.dispose();
```

The separate display host has `version: '0.1.0'`, `kind: 'platform'`,
`getSnapshot()` returning `{theme: 'light' | 'dark'}`, and `subscribe(listener)`
returning an unsubscribe function. It carries no account data, business permissions or
business success. Optional display capabilities are advertised separately. The platform sends its resolved device theme; switching theme
does not reload the view or replace application state. Calling this function is
optional for authors with a deliberate custom theme. Invalid/missing hosts fail
explicitly. Existing standalone previews need no display host.

The 0.1.4-dev starter renders work content inside the platform host, without the
preview banner or a duplicate drawer toolbar. It uses `createHostControls` when
the native host advertises display capabilities; older hosts receive a Section
without an unsupported open-full action. Standalone
preview retains its panel/full example. Old frozen source packages are unchanged.

## Integrated employee starter

The 0.1.2-dev creator toolkit includes this package with `runteams-runtime` and `runteams-view`, all pinned as private local 0.1.0 packages. UI's earlier prerelease suffix was removed to match the existing exact three-part dependency contract; this is not a public production-release claim. The default employee fixture demonstrates UI Kit → view client → actual Wasm runtime → explicit temporary data. `ui/shell.ts` is application composition, `ui/app.ts` owns business calls, and `ui/app.css` uses shared tokens. Component source remains generic.

The public root CSS entry files forward to generated `dist/` styles. They work with both package-export resolution and the creator builder's vendored directory aliases, without a second stylesheet implementation.

## Run outside the repository

Unpack the provided npm archive. In its `package` directory run:

```sh
python3 -m http.server 8863 --bind 127.0.0.1
```

Open `http://127.0.0.1:8863/examples/module/`. The example loads only package-relative files, requires no registry, CDN, platform CSS or business account. A system font fallback is used if the named platform font is unavailable; no font is downloaded. Refresh resets ephemeral example edits.

For a bundled application, install the local archive with an exact lockfile:

```js
import {createModuleTemplate, createPresentationClient} from 'runteams-ui';
import 'runteams-ui/theme.css';
import 'runteams-ui/styles.css';
```

Apply `data-rt-ui` to the owned root and optionally `data-theme="light"` or `"dark"`. Without explicit theme it follows system preference. CSS is scoped to this root and component classes. It is not a security boundary against arbitrary host CSS; isolate untrusted/custom views as required by the existing platform architecture.

## Drawer-header toolbar

The drawer header means the **top toolbar containing the collapse button**, not the employee title/description below it. `createDrawerHeader({onCollapse, extras})` provides a fixed 38px toolbar with a persistent 28px collapse control on the left, optional text in the middle and actions on the right. Employee identity/description remains a separate composition below the toolbar.

```js
import {createDrawerHeader} from 'runteams-ui';
const header = createDrawerHeader({
  onCollapse: () => hideDrawerAndFocusReopenControl(),
  extras: {
    text: '8 items',
    actions: [{id: 'help', label: 'Help', onPress: () => showHelp()}]
  }
});
container.prepend(header.element);
header.setExtras({text: 'Updated context'}); // Replaces all extras.
header.setExtras(); // Clears extras; the toolbar and collapse control remain.
// On unmount: header.dispose(); header.element.remove();
```

Actions require a stable unique `id`, non-empty `label`, `onPress(event)` and optional boolean `disabled`. Text and labels are plain text. The shared toolbar height and collapse position never depend on extensions. Long text/labels ellipsize with full text in native titles; excess actions scroll horizontally within their region and remain keyboard reachable. Prefer short context and one or two actions; put lengthy content in the drawer body. Extension updates cannot remove or replace the collapse control or change its callback.

Updates validate completely before applying; unchanged action IDs retain their nodes and keyboard focus. Removing/disabling a focused custom action moves focus to the collapse control. `dispose()` detaches all callbacks, disables controls and ignores later updates. The host owns collapse/reopen visibility, focus restoration, and preserving content/drafts; the template only dispatches `onCollapse`. The example implements this host flow without destroying the drawer.

The caller owns asynchronous work, disabled/loading state and visible error/retry content; catch rejected work in your callback and update extras explicitly. No business call, success claim or automatic retry is made by the template. Do not mount a duplicate toolbar if a production host already supplies it. In the native platform, use `createHostControls(host).setHeader(...)` instead of mounting this toolbar yourself.

The earlier unreleased `createPanelHeader` experiment customized the employee introduction by mistake. It is replaced by `createDrawerHeader` in this local development package, not maintained as a second header API.

## Components and templates

`createSection({title, summary, content, expanded, onOpenFull})` returns the element, state and controls. Its title button toggles the body; the sibling full-view button never toggles the section. Without `onOpenFull` no expansion action is shown. `content` accepts arbitrary caller-owned DOM, not only lists. Strings are rendered as text.

`createFullView({title, employeeName, onReturn})` provides the shared full-workspace header: an icon return control, an employee → current-module breadcrumb, and a separate large page title underneath. `title` fills both current-module breadcrumb and page title. `employeeName` is supplied by the host/caller; when omitted no employee is invented. With `onReturn`, the employee breadcrumb returns to the same drawer, sharing the icon control’s action; otherwise it is plain text. The template also provides a scrollable body. This means a platform work area, not OS/browser Fullscreen API.

`createModuleTemplate({title, employeeName, summary, content, expanded, onRequestMode})` combines both. Mount `section.element` in the drawer and `full.element` in the work area, then use:

- `setMode('panel' | 'full')` after host acknowledgement.
- `setPending(boolean)` while requesting a transition.
- `setError(message)` for a failure visible even when the section is folded.
- `dispose()` to detach component listeners; the caller owns node removal and business state cleanup.

The same content node moves between presentation containers, retaining values, selection and internal scroll. `content.dataset.presentation` changes so caller layouts can respond. Panel expanded state is independent and preserved. Input caret is restored for a focused editor; explicit open/return actions place focus on the full heading/original trigger. This same-document template is suitable for the standalone host. Native platform controls resize the same isolated WebView; do not assume a DOM node can move between isolated documents. If a renderer is remounted, the application must persist/reconstruct its own selection and draft state.

## Presentation interface

`createPresentationClient(adapter, {timeoutMs?})` exposes:

- `openFull(viewId)` → Promise of acknowledged state.
- `returnToPanel()` → Promise of acknowledged state.
- `getSnapshot()` and `subscribe(listener)` → current `{mode, viewId, pending, error}`. Read initial snapshot explicitly; subscriptions report subsequent updates.
- `dispose()` cancels pending waits and removes subscribers.

The adapter has `version: '0.1.0'` and `transition({mode, viewId}, {signal})`. It must acknowledge exactly the requested target after completion and honor cancellation. It must not apply late transitions after abort. The client validates replies, rejects duplicate in-flight requests, limits waiting and ignores late replies after disposal/timeout. Timeout is not proof a noncompliant host rolled back; a production adapter must reconcile host state before enabling retries. The preview adapter is synchronous and has no external effects.

This first version opens one full view at a time; return before switching to another module. A module registry, arbitrary URLs, business context serialization, title mutation and drawer-header actions are not part of this interface. The full-view template’s static `employeeName`/`title` inputs do not expose a drawer-header mutation API. A view ID is a local view identity, never an authorization grant. No business actions are triggered by presentation changes.

See `examples/module/preview.js` for host composition and error handling. It keeps shell visibility/outer drawer scroll in the host, content/drafts in the application and visual components independent of the SDK client. External code may implement custom UI and use the same client without these templates.

## Agent usage

1. Prefer the module template for panel/full presentation. Use a Section alone when full view is unnecessary.
2. Supply your own content and state. Use the current shared tokens rather than a new palette.
3. Bind presentation actions to the host adapter; do not invent business bridge methods.
4. Verify fold/open/return, selection, filters, draft, scroll, keyboard focus, long title, narrow container and dark theme. Keep only one live view accessible.
5. Use `createDrawerHeader` once at the top of a standalone drawer, and `setExtras` for custom text/actions. Keep its collapse control and shared toolbar layout. Do not add duplicate identity or an independent close control inside module content; in the native platform, use `createHostControls(...).setHeader(...)`.

## Build and validation

From repository root:

```sh
python3 runteams_official/devtools/build_ui_tokens.py --check
python3 sdk/ui/build.py
node --test sdk/ui/tests/presentation.test.mjs
python3 runteams_official/devtools/check_ui_contract.py
```

In the preview, expand “交互检查” and run component checks. Generated `dist/` is a byte-for-byte distribution copy of the shared implementation and foundation; never edit it. `build-manifest.json` records sources and hashes. The repository's existing platform token output is preserved; adopting these components in production is a separate integration step.

## Native platform controls

The source-integrated platform hosts advertise `runteamsHost.capabilities` containing `presentation` and `drawer-header`. Desktop uses the native host; browser development uses the same page and SDK through the local service’s browser host. Business calls continue through the same work owner and permissions. The installed app is not upgraded by this package.

```js
import {connectHostTheme, createHostControls} from 'runteams-ui';
const theme = connectHostTheme(window.runteamsHost);
const controls = createHostControls(window.runteamsHost);
await controls.setHeader({text:'当前工作', actions:[
  {id:'help', label:'说明', onPress:() => showHelp()}
]});
const off = controls.subscribe(state => {
  module.setPending(state.pending);
  module.setMode(state.mode);
});
await controls.openFull('my-module');
await controls.returnToPanel();
// Before replacing the controller in the same document:
off(); await controls.dispose(); theme.dispose();
```

`createHostControls` provides the presentation client methods plus asynchronous `setHeader`/`dispose`. One controller owns a host document. Native completion and its 2-second deadline own acknowledgement; do not wrap this in an optimistic adapter or an automatic retry. It resizes the same isolated native WebView, never transfers a DOM node between frames. The module template still handles content layout and focus inside that document. The platform keeps the conversation header reachable; collapsing/reopening retains the work document, input and scroll.

Header updates replace all extras, accept at most 256 characters of plain text and 8 actions with unique 1–64 character identifier keys and labels up to 80 characters. Prefer one or two short actions. Callbacks stay in the author document; only descriptors cross the bridge. The platform uses the same `createDrawerHeader` implementation and retains its collapse control and its own pin action. Actions carry a document epoch and header revision; removed, disabled or old actions are rejected. Navigation clears old extras. No HTML, arbitrary URL, credential or business operation is accepted through this bridge.

Normal transitions preserve the document. A cancelled or unconfirmed native layout closes the work view and clears its platform presentation instead of leaving a late transition live. Unsaved page-only state can be lost on this failure path; applications that require recoverable drafts must use their authorized business draft contract. Opening again is explicit. This display protocol never claims a business write succeeded and does not participate in the Chat business sequence.

`python3 sdk/ui/build.py` now emits both SDK distribution and platform component files from `packages/ui-components`; `--check` detects drift. The platform theme adapter maps `--rt-*` to existing global tokens. The external SDK carries its locked generated palette. No second hand-maintained palette or component implementation is introduced.
