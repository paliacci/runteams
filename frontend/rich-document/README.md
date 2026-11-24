# Shared document editor

The independent document laboratory has been integrated into the local product on 2026-10-30. New rich documents and eligible employee reports use the same content surface. Reading and editing are one view; the external document kernel and original editor have been removed. Historical test documents are not migrated.

- The product host (`web/ui/rich-documents.js`) owns account authority, document routes, versions, saving, attachments, templates and downloads. The React frame has no direct business API client. Frame messages check origin, source, token, current document and account; replies from a previous account/page are discarded.
- The renderer uses BlockNote 0.56.0 and the verified compact horizontal/vertical menus. Tables, linked charts, metrics, references, callouts, formulas, local images/videos/files and basic two-column layout are editable. Reading shows content; editing controls appear on hover/focus. Slash commands are disabled. Link underline and heavy blue focus decoration are removed; tooltip labels and shortcuts share a row. Inline code and code blocks are distinct; both are functional.
- The existing artifact identity and immutable revision chain remain authoritative. `runteams_core/documents/rich_documents.py` validates the expanded content model, including typed table edits and incomplete numeric drafts. Raw `sources` snapshots remain separate from edits. Body limits remain 2 MB, 500 blocks, 5,000 rows. Device-work schema 4 removes the retired private editor mapping; the artifact/revision/identity tables remain unchanged.
- Automatic saving correlates request IDs and expected revisions, retains edits made while saving and exposes failures. Window navigation waits for the final client flush, rather than the first HTTP acknowledgement. Retries preserve exact-content idempotency. Opening/normalizing a document does not create a revision; generated Markdown block identities are stable across reopening.
- Personal document attachments are immutable, document-bound files in the account-scoped work store (`artifacts/rich-assets`). Each file is at most 20 MB. They are included by the existing work-store backup; saved revision metadata retains their references, and permanent document cleanup removes unreferenced files. Uncommitted upload remnants can remain on disk; they are not exposed as independent documents. Browser databases are not the authoritative copy.
- Personal block templates live in the same backed-up work-store tree (`artifacts/rich-templates`), with an atomic metadata index and full fragments. They retain child blocks, data, references and attachment bytes. The browser only requests template metadata until a template is inserted. Duplicate names are rejected. Template/library size is bounded; historical test template and attachment libraries are not imported.
- Clipboard copies carry complete blocks, source snapshots and attachment payloads. Paste remaps block/data identities; copied table/chart pairs remain linked to each other while independent from originals. Cut deletes only after clipboard success and a stale-content check. Native undo remains available. Host-owned downloads handle both attachments and full JSON export, including binary payloads.
- Markdown/JSON attachments remain readable through the shared renderer. All new authored documents and employee reports use the rich content model; no old editor action or native kernel fallback exists. Organization/cloud attachment and template writes are not enabled by these personal device endpoints; their menu entries are disabled in that scope. Basic two-column editing has no drag resizing or multi-column manager.

## Build and verify

From this directory:

```sh
npm ci --ignore-scripts
npm run build
npm test
```

The build publishes assets under `web/rich-document/dist` and replaces the entry after its assets exist. Old hashed assets stay available for open readers. The final build step uses Python 3.12 to register the published files with the local edition's HTTP server. A new frame under an old host asks the user to refresh before editing. Laboratory boot, fixtures, browser-local storage and test banners stay in the laboratory.

The [desktop package check](../../tests/check_packaged_document.py) creates a document through the packaged local server and reads it back. The DOM checks above run React and BlockNote with geometry stubs.

Only the local source service was updated. No cloud deployment, installer rebuild, employee/model execution, original report rewrite or automatic migration of laboratory test copies was performed.

The standalone product detail view reuses the existing host-owned document header and settings menu. `header_in_host` suppresses the duplicate frame toolbar; validated `header-action` messages export the live complete document or retry saving. Embedded reports retain no page header. The lab/unhosted frame toolbar remains available.

The host-owned left outline reuses the existing document navigation styles and local collapse preference. `outline.js` observes rendered headings and named data blocks, publishes bounded metadata only, and navigates only to known targets on trusted `outline-jump` messages. Scrolling updates the active entry without replacing navigation buttons. It never changes document blocks or selection; embedded reports have no outline. Narrow views overlay the panel and collapse it after choosing a section.


## Bound reply display

The reply entry reuses Table/Chart/Explorer from `src/reply-components.jsx`. json-render adds a bounded v2 catalog (`src/reply-catalog.js`), local state bindings, Messages and Detail; the existing `runteams-view` parser and employee reply skill own delivery. `web/ui/reply-spec.js` owns validation and data paths; it does not choose components. Provider fixtures contain only raw synthetic data.

Open `/?preview=json-render` for four editable raw-data fixtures. Choose an existing connected model and click AI generation: the page uses the shared conversation creation/stream transport and renders the returned spec in place. The model chooses catalog components and field mappings; original data is bound locally without being rewritten. Invalid model output is shown as an error with the raw reply available; there is no local selector or fallback template. Stop/recover uses the original conversation, including after a tab reload, without silently starting another request. Test conversations remain in existing history. No additional cloud backend or model SDK is used.

Run `node reply-check.mjs` and `node json-render-check.mjs` from this directory. The latter checks arbitrary data shapes, bindings, rejected actions, real rendering and stale-data updates. New components must be added to both the catalog and the bounded contract, with documentation in the existing employee skill.
