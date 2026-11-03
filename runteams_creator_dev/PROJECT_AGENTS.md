# Employee SDK project

For employee source, UI, testing or packaging work, read
`.agents/skills/runteams-creator/SKILL.md`. It is the shared workflow for all agents.

- Change author files in `source/`; keep SDK/tool bytes and their locks intact.
- Run the checks relevant to changed behavior. For visible UI changes, launch
  the actual preview, operate the affected states, inspect screenshots, correct
  issues and recheck. A screenshot file or passing build alone is not acceptance.
- If rendering or a required check is unavailable, report the unverified scope.
  Never claim a check was performed from code inspection alone.
- Local fixtures do not prove platform permissions, durable data or publication.
  Use the platform's authorized import, preview and publishing flows for those.

No screenshot is required for a change with no visible UI effect. Keep detailed
verification evidence separate from the brief user-facing result.
