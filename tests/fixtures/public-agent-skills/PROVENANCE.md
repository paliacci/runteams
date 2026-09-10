# Public Agent Skill regression fixture

- Upstream: https://github.com/anthropics/skills/tree/3b3fad96af16a10759d930941b4520ba0c40edae/skills/brand-guidelines
- Commit: `3b3fad96af16a10759d930941b4520ba0c40edae`
- Retrieved: 2026-08-23
- License: Apache License 2.0 (bundled unchanged as `LICENSE.txt`)
- Upstream `SKILL.md` SHA-256: `1120b3769e2985cefb3d25be981b1f914abeba57ae079b83c20c666c164fa9fe`
- Upstream `LICENSE.txt` SHA-256: `bc6b3af2f331cbc7fb0da1344efb2cbe5877a31498b4d70dbc7000f3405a1362`
- Fixture `LICENSE.txt` SHA-256: `14099b9c79d031b9d4b32c736a4e20f2b941f52dd79500532d62d26dd716110c`
- Expected RunTeams tree digest: `0338e6d90b753754016f122e57244a19195763b6fcc2453188eef31da1f5578e`

The fixture is one real public Agent Skill. `SKILL.md` is byte-identical; the bundled
license text only normalizes the missing final newline. Keep the pinned copy deterministic;
test newer upstream revisions separately before replacing it.
