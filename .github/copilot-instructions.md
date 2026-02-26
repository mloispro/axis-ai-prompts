# Copilot instructions (axis-ai-prompts)

## What this repo is
- This is a **public prompt catalog**: canonical prompt JSON lives in `prompts/<appId>.json`.
- Treat everything here as public: **never add secrets/PII** (API keys must not be committed).

## Prompt file conventions
- Prompt JSON is loaded by `tools/workbench-cli/workbench.py`.
- Supported schemas:
  - RizzChatAI-style modes: `prompts.{openerSystem,appChatSystem,regChatSystem}`
  - Simple single-system fallback: `prompts.system` (see `prompts/template.json`)
- When editing prompt content, also update `updatedAt` in the same file (see `prompts/rizzchatai.json`).

## Local workbenches

### Desktop CLI workbench
- Entry: `tools/workbench-cli/workbench.py` (Python).
- Fixtures live under `fixtures/<appId>/<mode>/*.txt` (preferred). Legacy `fixtures/<mode>/*.txt` is also supported.
- Outputs are written to `out/<runId>/...` for diffing/regression checks.
- Reads API key from `OPENAI_API_KEY` environment variable (never write keys to disk).

### Optional web workbench
- Entry: `tools/workbench-web/server.py` (FastAPI + Uvicorn).
- Local draft candidates are stored under `tools/workbench-web/state/` (gitignored).
- Outputs are written under `tools/workbench-web/out/` (gitignored).

## Common dev commands (Windows)
- Run workbench selftest (no API calls):
  - `python .\\tools\\workbench-cli\\workbench.py selftest`
- Run opener fixtures for an app (requires `OPENAI_API_KEY`):
  - `python .\\tools\\workbench-cli\\workbench.py run --app rizzchatai --mode opener`

## Change guidance
- Keep prompt edits **data-only** (JSON content) unless you’re explicitly fixing the workbench CLI.
- If you change prompt schema expectations, update `tools/workbench-cli/workbench.py` and `tools/workbench-cli/README.md` together.
