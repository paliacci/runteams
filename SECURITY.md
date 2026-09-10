# Security Policy

## Supported versions

RunTeams is in public beta. Security fixes are applied to the latest `main` release line first.

## Reporting a vulnerability

Please do not open a public issue for an unpatched vulnerability. Email `security@runteams.ai` with:

- a short description and affected component;
- reproduction steps or a minimal proof of concept;
- affected versions or commit;
- the potential impact.

We will acknowledge a report as soon as practical, keep the report private while a fix is prepared, and credit the reporter unless they prefer to remain anonymous.

## Local data and credentials

RunTeams is local-first, but extensions and connected agent runtimes can access the files and tools that the user grants them. Never include credentials, tokens, private workspace files, or production data in an issue, pull request, fixture, or log attachment.
