# Third-party runtime notices

## Agent Python runtime (2026-10-27)

Work-environment version checks use `packaging==26.3` in the application backend,
not in the immutable Agent Python base. Desktop packaging includes its complete
distribution metadata and license texts with `--copy-metadata packaging`.
Upstream: https://packaging.pypa.io/en/stable/specifiers.html

RunTeams provisions relocatable CPython 3.12.14 from Astral's Python Standalone
Builds release 20260924. The exact install-only archive and matching full archive
are pinned by platform, size and SHA-256 in `contracts/agent-python.lock.json`.
The full archive supplies `PYTHON.json` and its complete `licenses/` directory;
only these notices accompany the install-only payload, not the build artifacts.
Keep `agent-python/licenses`, `UPSTREAM-PYTHON.json`, the CPython `LICENSE.txt`
and all pip dependency license files intact when distributing the application.
The runtime is signed before its application manifest is sealed. No runtime
download or host Python modification occurs on end-user launch.

Upstream: https://github.com/astral-sh/python-build-standalone/releases/tag/20260924
Distribution metadata: https://docs.astral.sh/python-build-standalone/distributions/

## Local MCP Apps development candidate (2026-10-24)

The local sdk/mcp-host implementation bundles the official MCP client/core/server
2.4.0 (Apache-2.0) and MCP Apps 2.0.3 (MIT), with their exact transitive closure
in `sdk/mcp-host/package-lock.json`. Its builder retains runtime dependency
license texts in `THIRD_PARTY_NOTICES.txt`; this file and linked legal comments
must accompany the platform resources. Node 24.22.1 darwin-arm64 is sourced from
the official archive with its fixed SHA-256 in `node-runtime.json`; preserve the
archive's complete LICENSE as `NODE-LICENSE`. Other platforms and formal desktop
distribution/signing remain unverified. This candidate does not update the
installed app or replace the existing release with a formally delivered employee.

Sources: [MCP SDK](https://github.com/modelcontextprotocol/typescript-sdk),
[MCP Apps](https://github.com/modelcontextprotocol/ext-apps),
[Node distribution checksums](https://nodejs.org/dist/v24.22.1/SHASUMS256.txt).

## Document editor

Documents use the shared React / BlockNote editor and the product's account-scoped
artifact files and immutable revisions. No separate document kernel, Pandoc,
upstream editor, corresponding-source companion or runtime download is included.
The locked frontend dependencies and their license notices still belong in releases.

## Rich document reader and editor (2026-10-29, local source integration)

The new content surface uses BlockNote core/react/shadcn 0.56.0 (MPL-2.0), React/ReactDOM 19.2.0 (MIT), Streamdown 2.7.1 (Apache-2.0), TanStack React Table 8.21.3 (MIT), Recharts 3.10.1 (MIT), Lucide React 1.64.0 (ISC), and KaTeX 0.19.1 (MIT). Exact dependency versions and transitive dependencies are locked in `frontend/rich-document/package-lock.json`. Upstream packages remain unmodified.

Sources: https://github.com/TypeCellOS/BlockNote ; https://github.com/vercel/streamdown ; https://github.com/TanStack/table ; https://github.com/recharts/recharts ; https://github.com/lucide-icons/lucide ; https://github.com/facebook/react .

Only built static assets belong in `web/rich-document/dist`; development dependencies remain outside the packaged web directory. This task updates local source only. The locked dependency license texts are retained in licenses/DEPENDENCIES.txt; complete the native packaging checks before distributing an installer; no installer or release was produced here. The retired upstream editor is no longer part of new distributions.

## Source release licensing and retained notices

The root source-available license applies only to covered RunTeams-authored
material. Independently licensed components remain under their own terms.
sdk/runtime, sdk/view and sdk/ui retain their Apache-2.0 licenses. Vendored
Anthropic skills retain their upstream licenses and per-skill NOTICE.txt files;
font licenses remain alongside their binaries. Marked, DOMPurify and KaTeX
retain their vendored license texts. Bottts SVG metadata identifies Pablo Stanley
and its permission for personal and commercial use; retain that metadata.
Provider marks identify third-party services; the RunTeams license grants no
rights in those marks and implies no endorsement.

The committed rich-document bundles include unmodified MPL-2.0 libraries.
web/rich-document/licenses/DEPENDENCIES.txt contains their notices together with
the remaining locked frontend dependency notices. The exact source package
archives and integrity values in frontend/rich-document/package-lock.json are
the corresponding unmodified source distribution locations; retain this source
availability information with redistributions. No MPL-covered files are
relicensed by the RunTeams license. See THIRD_PARTY_INVENTORY.json for the
versioned source inventory.

PDF attachments use pypdfium2==5.14.0 (Apache-2.0 / BSD-3-Clause wrapper plus
PDFium and its own dependency licenses). PyMuPDF is not a product dependency.
Retain the complete pypdfium2 and pypdfium2_raw license directories and Python
distribution metadata when packaging binaries, in addition to the licenses of
all other actual Python/Node dependencies. Source publication does not certify
unbuilt native installers or their future license inventories.

Sources: https://github.com/pypdfium2-team/pypdfium2 ;
https://www.dicebear.com/styles/bottts/ ;
https://github.com/TypeCellOS/BlockNote ; https://www.mozilla.org/MPL/2.0/ .


The resource viewer uses the existing read-only Sandpack/CodeMirror UI. Its build
excludes the unused Sandpack node client and Nodebox implementation, which have
separate commercial restrictions. The build metafile rejects Nodebox inputs;
no replacement runtime is provided. The product only uses the original vanilla
viewer with autorun disabled. Locked resource-viewer dependency notices are in
web/vendor/licenses/RESOURCE_VIEWER_DEPENDENCIES.txt and linked legal comments
are in web/vendor/resource-viewer.js.LEGAL.txt. Hanken Grotesk's OFL-1.1 notice
is retained at web/fonts/hanken-grotesk-LICENSE.txt.
