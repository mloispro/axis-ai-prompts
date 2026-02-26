# ai-prompts workbench (local)

Local-only web UI for iterating on prompt content stored in this same repo.

## Quick start (Windows)
1) Copy env file (gitignored):
- `tools/workbench-web/.env.local.example` → `tools/workbench-web/.env.local`
- Put your `OPENAI_API_KEY=...`

2) Launch:
- Double-click: `run.bat` (repo root), or `tools/workbench-web/run.bat`

3) Open browser:
- It auto-opens to `http://127.0.0.1:<port>/`

## How it works
- Baseline: the canonical prompt file under `prompts/<appId>.json`
- Candidate: a local draft file `tools/workbench-web/state/candidates/<appId>.json` updated from the UI (gitignored)
- Fixtures: `fixtures/<appId>/<mode>/*.txt`
- Outputs: `tools/workbench-web/out/<timestamp>/...` (gitignored)

## Safety
- This repo is public. Don’t put secrets/PII in prompts or fixtures.
- API key lives only in `tools/workbench-web/.env.local` (gitignored).

## Playwright e2e (no API key required)
The Playwright tests start the server automatically and run in `dry-run` mode (no OpenAI calls).

From `tools/workbench-web/`:
- One command (recommended): `powershell -NoProfile -ExecutionPolicy Bypass -File .\e2e.ps1`

Or via npm:
- Setup once: `npm run e2e:setup`
- Run tests: `npm run e2e`

