# ai-prompts workbench (local)

Local-only web UI for iterating on prompt content stored in this same repo.

## Consumer model
- The canonical prompts live in `prompts/<appId>.json` and are intended to be consumed by a **separate app** (e.g., an Android client that fetches the JSON from public GitHub).
- This web workbench is a **local iteration tool** to edit candidates and run fixture-driven checks before you ship prompt changes.

## Quick start (Windows)
1) Copy env file (gitignored):
- `tools/workbench-web/.env.local.example` → `tools/workbench-web/.env.local`
- Put your `OPENAI_API_KEY=...`

2) Launch:
- Double-click: `run.bat` (repo root), or `tools/workbench-web/run.bat`

VS Code (easy Play/Restart + auto-reload):
- Run and Debug → **Workbench Web (run site)** (uses `run.bat dev`, which runs `uvicorn --reload`)

Restart / stop (handy during development):
- Restart: `run.bat restart`
- Stop: `run.bat stop`

Foreground dev server (auto-reloads on code changes):
- `run.bat dev` (or `run.bat dev 8787`)
- Server-only: `run.bat dev 8787 noopen`

3) Open browser:
- It auto-opens to `http://127.0.0.1:<port>/`

## How it works
- Baseline / “repo prompts” (canonical): the repo-tracked prompt file under `prompts/<appId>.json`
- Candidate: your local working copy at `tools/workbench-web/state/candidates/<appId>.json` updated from the UI (gitignored)
- Fixtures: `fixtures/<appId>/<mode>/*.txt`
- Outputs: `tools/workbench-web/out/<timestamp>/...` (gitignored)

## AI Prompt Editor (diff-first)
The UI includes an **AI Prompt Editor** section that proposes edits to exactly one prompt key at a time.

Workflow:
1) Choose a `targetKey` (e.g. `openerSystem`, `openerUser`, etc.).
2) Enter a change request.
3) Click **Propose edit** → the server returns a structured proposal + unified diff.
4) Click **Apply** → the candidate bundle is updated and the fixture suite auto-runs.
5) Use **Undo** to restore the previous candidate snapshot (including undoing a Reset), or **Reset** to return to canonical.

Guardrails enforced on apply:
- No external URLs (`http://` / `https://`).
- Must preserve the exact set of `{{placeholders}}` already present in the prompt text.
- Must not be empty and must materially change the prompt.

Local state:
- Candidate: `tools/workbench-web/state/candidates/<appId>.json`
- Undo history: `tools/workbench-web/state/history/<appId>.json` (bounded stack)

API endpoints (used by the UI):
- `POST /api/edit/propose` (supports `dryRun: true` to avoid OpenAI calls)
- `POST /api/edit/apply`
- `POST /api/edit/undo`
- `POST /api/edit/reset`

## Edit history (local snapshots)
Each time you click **Apply**, the server stores a local-only snapshot so you can browse/diff/restore prior candidate states.

Where it lives:
- Drafts + undo snapshots: `tools/workbench-web/state/history/<appId>.json` (gitignored)

API endpoints:
- `GET /api/drafts` (lists edit snapshots + includes latest suite clean/not-clean status)
- `GET /api/drafts/diff` (unified diff for a key vs previous edit snapshot)
- `POST /api/drafts/restore` (restores a selected snapshot into the candidate file)

Notes:
- Undo operations use undo snapshots and ignore draft entries, so the draft shelf won’t break Undo semantics.

## Promote to canonical (ship step)
When you’re satisfied with a candidate, use **Publish to repo prompts** to write it into the repo-tracked prompt bundle:
- Writes candidate → `prompts/<appId>.json`
- Updates `updatedAt`
- Clears local draft history (after promotion, git is the version history)

Guardrail:
- By default promotion is blocked unless the latest suite run is “clean”.

API endpoint:
- `POST /api/promote`

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

