# RunTeams public source

This repository owns the local application, shared business UI, public SDK and
their build/development tools. It is the canonical checkout for new changes in
these areas. Do not read product code or assets from the retired combined
workspace or the private official repository.

RunTeams-authored product code uses LICENSE. The SDK package exceptions and
third-party licenses are documented in docs/legal/LICENSING.md. Preserve upstream notices.
Do not describe the restricted product license as OSI-approved open source.

Reuse the existing UI and local business implementations. The local edition has
no RunTeams account, Supabase, subscription, marketplace or automatic updater.
Keep one owning implementation and update callers directly; do not add old-path
aliases, forwarding modules or compatibility entry points.

Use Python 3.12. Run runteams_core.devtools.ci for source/build/install/SDK checks;
run runteams_core.devtools.ci_devkit on macOS ARM64 for the developer-kit mainline.
Neither check is authorization to run real models, employee work or deployments.

Repository layout and maintenance rules are in docs/architecture.md and docs/development.md. Run the tracked-file hygiene check before committing; keep experiment logs, local profiles and one-time repair scripts outside Git. Generated static UI resources and deterministic test inputs remain maintained source artifacts.

All runtime Python modules belong under runteams_core; use qualified package imports. requirements/ owns dependency lists and docs/legal/ owns explanatory licensing and inventories. The root contains project/build metadata, not business modules.

Core domains are documented in docs/core-domains.md and declared in tooling/core-domains.json. The package root owns only its public types. Import implementations from their actual business packages; do not add module re-exports, sys.modules aliases or root-level business files. Update worker/compilation source paths and manifests when moving code.
