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
node check.mjs
node host-check.mjs
node autosave-check.mjs
node data-model-check.mjs
node reply-check.mjs
```

The build publishes assets under `web/rich-document/dist` and replaces the entry only after assets exist. Old hashed assets stay available for open readers. A new frame under an old host asks the user to refresh before editing; it never silently mixes incompatible save protocols. The shared chat renderer is still built from its existing, unchanged source; laboratory boot, fixtures, browser-local storage and test banners are not shipped.

Backend checks include `tests.test_rich_documents`, `tests.test_rich_document_assets`, `tests.test_work_reports`, `tests.test_device_work_retention`, and the document window checks and `tests.test_document_engine_retirement`. DOM checks use actual React/BlockNote with geometry stubs; real browser evidence is recorded separately. Current verification and scoped recovery patch: `design/evidence/document-lab-integration-20261030/`.

Only the local source service was updated. No cloud deployment, installer rebuild, employee/model execution, original report rewrite or automatic migration of laboratory test copies was performed.

The standalone product detail view reuses the existing host-owned document header and settings menu. `header_in_host` suppresses the duplicate frame toolbar; validated `header-action` messages export the live complete document or retry saving. Embedded reports retain no page header. The lab/unhosted frame toolbar remains available.

The host-owned left outline reuses the existing document navigation styles and local collapse preference. `outline.js` observes rendered headings and named data blocks, publishes bounded metadata only, and navigates only to known targets on trusted `outline-jump` messages. Scrolling updates the active entry without replacing navigation buttons. It never changes document blocks or selection; embedded reports have no outline. Narrow views overlay the panel and collapse it after choosing a section.
