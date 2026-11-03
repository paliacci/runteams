# Contributing

Issues and pull requests are welcome. Start with a concrete problem, an expected result and the smallest reproducible example. For substantial architecture changes, open an issue before changing module boundaries.

## Development

Use Python 3.12 and the commands in the [development guide](docs/development.md). The [architecture guide](docs/architecture.md) identifies each maintained source area. Keep local business behavior, shared UI and SDK in this repository; official account, marketplace and cloud implementation belongs in its own repository.

Keep changes focused. Update direct callers when moving code and update generated resources, manifests and tool inventories together. Do not introduce forwarding modules for retired paths. Add or run the tests that demonstrate the changed behavior; record the actual commands and results in the pull request. Run the documented CI entry after committing the reviewed source so its wheel can be reproduced.

Repository checks reject tracked installation directories, local profiles, credentials and personal-machine paths. Store screenshots, experiment logs and one-time build outputs outside Git. Keep deterministic fixtures that are consumed by maintained tests.

## Licensing

By intentionally submitting code for inclusion, you confirm that you have the right to submit it and identify all third-party material and licenses. A pull request alone is not a copyright assignment or permission to relicense third-party code. Contributions requiring additional rights for the official distribution will only be merged after a separate explicit agreement. See [LICENSING.md](LICENSING.md).

## Security

Do not include personal documents, model keys, account tokens or local databases in issues, commits or logs. Report sensitive vulnerabilities through the channel in [SECURITY.md](SECURITY.md).
