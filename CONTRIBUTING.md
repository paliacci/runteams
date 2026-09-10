# Contributing to RunTeams

Thank you for helping make RunTeams a reliable, local-first home for agent teams.

## Before you start

1. Search open and closed issues before opening a new one.
2. For a large feature or architectural change, open a discussion issue first.
3. Read [`ARCHITECTURE.md`](ARCHITECTURE.md) and the relevant contract under [`contracts/`](contracts/).
4. Keep changes focused. A pull request should have one clear purpose.

## Development setup

```bash
git clone https://github.com/paliacci/runteams.git
cd runteams
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m unittest discover -s tests -p 'test_*.py'
```

Install and authenticate the agent CLI needed for the area you are working on. Do not commit credentials, local databases, transcripts, generated bundles, or personal workspace data.

## Branches and pull requests

- `main` is the stable integration branch.
- Create a short-lived branch from `main`, for example `fix/recovery-timeout` or `docs/adapter-guide`.
- Keep commits small and explain behavior changes in the commit message.
- Open a pull request early when feedback would help; draft PRs are welcome.
- Fill out the pull request template and describe testing, compatibility impact, and any contract changes.
- CI must pass before merge. Maintainers may request a second review for changes to protocols, credentials, persistence, or release behavior.
- Prefer squash merging to keep `main` readable. Maintainers handle the final merge.

## What makes a good PR

- It solves one user-facing or maintenance problem.
- It includes tests or a clear reason a test is not useful.
- It updates documentation and versioned contracts when behavior changes.
- It preserves local-first operation and does not silently send user data to a service.
- It contains no secrets or generated personal data.

## Commit style

Use an imperative subject under 72 characters when practical:

```text
Persist approval decisions across restart
Document Codex adapter setup
```

## Review culture

Reviews should be specific, kind, and focused on the code and its user impact. A maintainer may ask for a smaller PR or a design issue before reviewing implementation details. See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for our community standards.
