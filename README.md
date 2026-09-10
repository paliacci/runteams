# RunTeams.ai

**Open-source, local-first orchestration for the AI agents you already use.**

RunTeams connects authenticated Claude Code, Codex, and other agent runtimes into durable teams. Define roles, compose pipelines, hand work between agents, pause for human approval, and resume from a persisted local run state.

RunTeams does not provide a model, resell tokens, or reduce a capable agent to a text-only API. It coordinates the runtimes, tools, permissions, artifacts, and handoffs that make agent work repeatable.

> **Early release:** RunTeams Desktop is in public beta. The repository contains the open-source local core; the official website may offer signed builds, compatibility maintenance, and optional Pro services.

## Why RunTeams

- **Use your existing agent access.** Connect official agent CLIs and reuse their login, subscription, tools, and permissions.
- **Model work as a team.** Give each AI employee a role, capabilities, deliverables, and completion criteria.
- **Compose real workflows.** Support sequential, parallel, branching, retry, handoff, and human approval steps.
- **Keep runs durable.** Persist tasks, employee runs, events, artifacts, and snapshots so work can resume after a restart.
- **Make delivery auditable.** Keep results, files, failures, and approval requests tied to an explicit source of truth.
- **Stay local by default.** Credentials, workspaces, run control, and full run data remain on the user's computer.

## Open core and Pro

The local core is designed to be useful on its own. It includes local creation, execution, inspection, and export of teams and workflows. The official Pro distribution may add signed releases, stable update channels, long-term compatibility work, an iPhone/iPad companion, encrypted Relay, push notifications, and remote approvals.

The paid capabilities share the same core protocol, data model, and run facts. The mobile companion and hosted cross-device services are intentionally outside this repository; their contracts live in [`contracts/`](contracts/).

## Requirements

To execute agent work, install and sign in to at least one supported official runtime, such as Claude Code or Codex CLI. RunTeams uses that runtime's existing subscription and quotas; it does not require a separate RunTeams model account.

The local core does not require a RunTeams business server. Model calls remain subject to each provider's subscription, quota, and data policies.

## Run from source

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Install and authenticate the agent CLIs you want to use before starting RunTeams. See [`desktop/README.md`](desktop/README.md) for desktop window and local data details.

## Build the macOS desktop app

```bash
bash desktop/build.sh
open desktop/RunTeams.app
```

External distribution requires Apple Developer signing, notarization, and an architecture-specific release pipeline.

## Test

The repository uses Python's standard `unittest` runner:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run the core suite locally before opening a pull request. The project keeps this command explicit so contributors can use it in their preferred CI provider.

## Repository layout

| Path | Purpose |
| --- | --- |
| `runteams_core/` | Core packages, employees, pipelines, tasks, workflows, and persistence |
| `app.py` | Local desktop service and HTTP shell |
| `runner.py` | Agent CLI lifecycle, cancellation, timeouts, and streaming output |
| `adapter_claude.py` / `adapter_codex.py` | Official agent runtime adapters |
| `core_protocol_mcp.py` | MCP entry point for employee workflows |
| `contracts/` | Versioned mobile, work-item, result, and encrypted-envelope contracts |
| `desktop/` | macOS native window and packaging scripts |
| `web/` | Desktop product interface assets |
| `tests/` | Protocol, recovery, runtime, and product behavior tests |

Read [`ARCHITECTURE.md`](ARCHITECTURE.md) for domain boundaries and data contracts. [`ROADMAP.md`](ROADMAP.md) describes the direction of the project.

## Design principles

1. Connect complete agent runtimes instead of calling a bare model API.
2. Preserve each agent's native tools, skills, permissions, and subscription model.
3. Standardize cross-agent roles, work items, handoffs, control points, and audit facts.
4. Keep local operation independent from a cloud service; treat cross-device services as optional control planes.
5. Let Free and Pro share the same core protocol, data model, and run facts.
6. Charge for natural extensions of the core instead of restricting export or creating artificial failures.

## Contributing

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md), search existing issues, and open a discussion issue before a large architectural change. Small, focused pull requests are easiest to review.

Please preserve the project boundaries: do not add a bare-model API path, write credentials into run snapshots or logs, or make a cloud service required for local core execution.

## Security

Do not publish credentials, personal data, workspace contents, or unpatched security details in an issue. Follow [`SECURITY.md`](SECURITY.md) for private reporting.

## License

The core is released under the [Apache License 2.0](LICENSE). Third-party dependencies and example assets remain under their respective licenses.

## Links

- Website: [runteams.ai](https://runteams.ai)
- Source: [github.com/paliacci/runteams](https://github.com/paliacci/runteams)
