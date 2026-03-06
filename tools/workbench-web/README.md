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

VS Code (C#-style F5 debugging, fixed port, breakpoints reliable):
- Run and Debug → **🐞 Workbench: Debug (fixed 7540)** (runs `uvicorn` without `--reload` on `http://127.0.0.1:7540`)
- If `7540` is already in use, the pre-launch check fails loudly so you don’t debug the wrong process.

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
- `POST /api/edit/reset` — **also wipes history entirely** (not just candidate)

## Edit history (local snapshots)
Each time you click **Apply**, the server stores a local-only snapshot so you can browse/diff/restore prior candidate states.

Where it lives:
- Drafts + undo snapshots: `tools/workbench-web/state/history/<appId>.json` (gitignored)

API endpoints:
- `GET /api/drafts` (lists edit snapshots + includes latest suite clean/not-clean status)
- `GET /api/drafts/diff` (returns snapshot text + unified diff for a specific draft id)
- `POST /api/drafts/restore` (restores a selected snapshot into the candidate file)
- `POST /api/drafts/delete` (deletes one draft by id — removes the draft **and** its paired undo snapshot, then restores candidate to the previous version; or base if it was the only version)

History model invariants:
- `api/edit/apply` always pushes two entries in order: `{ kind: "undo" }` then `{ kind: "draft" }` — always adjacent/paired.
- `api/edit/undo` pops only the most recent `kind:"undo"` entry (does not touch draft entries).
- `api/edit/reset` **wipes the entire history file** (`[]`). There is no "reset snapshot" preserved.
- `api/drafts/delete` removes the targeted draft AND its immediately-preceding undo snapshot.

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

## Version pill preview (diff overlay)

Clicking any version pill on the main screen enters **preview mode**:
- A colored header bar (`#sysVersionBar`) appears above the textarea, styled in the pill's hue.
- A diff overlay (`#sysPromptDiffOverlay`) is rendered over the textarea showing added/removed lines
  vs the canonical base — using `dl-add-hue-{n}` / `dl-del` / `dl-ctx` spans.
- Click the `×` in the version bar, or re-click the same pill, to exit preview mode.
- The base pill shows the base text without a diff overlay.

## Playwright e2e (no API key required)
The Playwright tests start the server automatically and run in `dry-run` mode (no OpenAI calls).

From `tools/workbench-web/`:
- One command (recommended): `powershell -NoProfile -ExecutionPolicy Bypass -File .\e2e.ps1`

Or via npm:
- Setup once: `npm run e2e:setup`
- Run tests: `npm run e2e`

After a test run the history file is cleared — this is expected.
Always re-run after editing `server.py`, `workbench.js`, `workbench.css`, or `index.html`.

## Playwright UI audit mode (screenshots on success)

Generate audit artifacts (screenshots even when tests pass):
- `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test --reporter=line,html`

Run only the audit-focused subset (tests tagged with `@audit`):
- `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test -g "@audit" --reporter=line,html`

Where outputs go:
- Checklist: `tools/workbench-web/out/audit/audit-findings.md`
- Stable artifacts: `tools/workbench-web/out/audit/audit_*.png`
- Playwright report UI: `cd tools/workbench-web && npx playwright show-report playwright-report`

## Keeping `out/` from growing forever

`tools/workbench-web/out/` is gitignored, but it can grow large on disk because the engine writes one timestamped folder per run.

By default, the workbench auto-prunes old run folders after each suite run (safe default: keep last 10 runs).

You can disable or tune this via env vars:
- `WORKBENCH_OUT_AUTOPRUNE=0` (disable)
- `WORKBENCH_OUT_KEEP_LAST=10`
- `WORKBENCH_OUT_KEEP_DAYS=0`

Recommended: if you ever want to prune manually (same defaults as auto-prune):

- Preview what would be deleted:
  - `cd tools/workbench-web && powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prune-out.ps1 -WhatIf`
- Actually delete old runs:
  - `cd tools/workbench-web && npm run out:prune`

Optional knobs:
- Keep fewer runs: `... -File .\scripts\prune-out.ps1 -KeepLast 15`
- Keep fewer days: `... -File .\scripts\prune-out.ps1 -KeepDays 7`
- Also prune trace files: `... -File .\scripts\prune-out.ps1 -PruneTraces`

