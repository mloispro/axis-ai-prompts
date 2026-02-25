# ai-prompts

A personal, public prompts repo intended to be **readable by anyone** but **writable only by you**.

## Structure (organized by app)
- `prompts/<appId>.json` — canonical prompt files consumed by apps (stable paths)
- `fixtures/<appId>/<mode>/*.txt` — sample user inputs for iterating (optional)
- `index.json` — optional app discovery metadata (used by the web workbench)
- `workbench/` — optional local web UI + engine (runs on your computer)
- `tools/workbench/` — optional desktop CLI workbench (runs on your computer)

## Web workbench (Windows)
1) Copy:
- `workbench/.env.local.example` → `workbench/.env.local`
- Set `OPENAI_API_KEY=...`

2) Run:
- Double-click `run.bat` (repo root), OR
- Double-click `workbench/run.bat`

## Safety
- This repository is public. Don’t commit secrets or PII.
- Never commit API keys.

