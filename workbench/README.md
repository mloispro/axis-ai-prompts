# ai-prompts workbench (local)

Local-only web UI for iterating on prompt content stored in this same repo.

## Quick start (Windows)
1) Copy env file (gitignored):
- `workbench/.env.local.example` → `workbench/.env.local`
- Put your `OPENAI_API_KEY=...`

2) Launch:
- Double-click: `workbench/run.bat`

3) Open browser:
- It auto-opens to `http://127.0.0.1:<port>/`

## How it works
- Baseline: the canonical prompt file under `prompts/<appId>.json`
- Candidate: a local draft file `workbench/state/candidates/<appId>.json` updated from the UI (gitignored)
- Fixtures: `fixtures/<appId>/<mode>/*.txt`
- Outputs: `workbench/out/<timestamp>/...` (gitignored)

## Safety
- This repo is public. Don’t put secrets/PII in prompts or fixtures.
- API key lives only in `workbench/.env.local` (gitignored).

