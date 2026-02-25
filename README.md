# ai-prompts

A personal, public prompts repo intended to be **readable by anyone** but **writable only by you** (no collaborators).

This repo is designed to support multiple apps. Each app has its own prompt file under `prompts/`.

## Quick start (structure)

- `prompts/`
  - One JSON file per app (recommended)
- `fixtures/`
  - Optional prompt workbench fixtures (sample inputs), ideally scoped per app:
    - `fixtures/<appId>/<mode>/*.txt`
- `tools/`
  - Optional desktop workbench scripts

## Hosting (free)

Use GitHub raw content URLs, e.g.

`https://raw.githubusercontent.com/<you>/ai-prompts/main/prompts/rizzchatai.json`

## Security notes

- Prompts here are **public**. Don’t store secrets or private user data.
- Never commit API keys.

## Suggested hardening (GitHub settings)

- Don’t add collaborators.
- Add branch protection on `main` and **restrict who can push** to only you.


