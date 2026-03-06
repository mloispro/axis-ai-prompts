# ai-prompts

A personal, public prompts repo intended to be **readable by anyone** but **writable only by you**.

## Consumer model (source of truth)
- `prompts/<appId>.json` is the canonical prompt bundle.
- **Apps consume these prompt files directly** (for example: a separate Android app can fetch the JSON from public GitHub and then inject runtime inputs before calling the model).
- The workbenches in `tools/` are **local developer utilities** for editing/iterating and running fixture suites to prevent regressions; they are not the production app.

## Structure (organized by app)
- `prompts/<appId>.json` — canonical prompt files consumed by apps (stable paths)
- `fixtures/<appId>/<mode>/*.txt` — sample user inputs for iterating (optional)
- `index.json` — optional app discovery metadata (used by the web workbench)
- `tools/workbench-web/` — optional local web UI + engine (runs on your computer)
- `tools/workbench-cli/` — optional desktop CLI workbench (runs on your computer)

## Web workbench (Windows)
1) Copy:
- `tools/workbench-web/.env.local.example` → `tools/workbench-web/.env.local`
- Set `OPENAI_API_KEY=...`

2) Run:
- Double-click `run.bat` (repo root), OR
- Double-click `tools/workbench-web/run.bat`

## UI audit loop (finding + fixing UI issues)

Use Playwright E2E as a deterministic “UI camera” to reproduce states and capture screenshots.

1) Start the workbench (default: `http://127.0.0.1:7540/`).
2) Run an audit pass (captures screenshots even when tests pass):
```bash
cd tools/workbench-web && E2E_AUDIT=1 npx playwright test --reporter=line,html
```
3) Review artifacts:
- Report UI:
```bash
cd tools/workbench-web && npx playwright show-report playwright-report
```
- Raw screenshots: `tools/workbench-web/playwright-report/data/*.png`

Tip: for deterministic “see the UI” review, open the PNG artifacts directly (VS Code file explorer or the Playwright report UI). If you want feedback in chat, attach the screenshot image.

Turn a visual finding into a durable fix:
- Make the smallest CSS/JS/HTML change that fixes the root cause.
- Add/tighten a Playwright assertion in the spec that reproduces the state.
- Re-run the audit command and confirm the screenshot/state is corrected.

Note: the Playwright suite uses `dryRun: true` and does not require `OPENAI_API_KEY`.

## Safety
- This repository is public. Don’t commit secrets or PII.
- Never commit API keys.

