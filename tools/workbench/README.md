# Prompt Workbench (Desktop)

This folder contains a Python CLI that calls OpenAI directly so you can iterate on prompts quickly without rebuilding the Android app.

## Setup (PowerShell)

Set your API key in the environment (do not commit keys):

```powershell
$env:OPENAI_API_KEY = "<your key>"
```

## Basic usage

Run a mode across fixtures using the prompts file:

```powershell
cd C:\Projects\AndroidStudioProjects\ai-prompts
python .\tools\workbench\workbench.py run --app rizzchatai --mode opener
```

A/B compare two prompt files (or two apps) across the same fixtures:

```powershell
python .\tools\workbench\workbench.py ab --promptsA .\prompts\rizzchatai.json --promptsB .\prompts\rizzchatai.json --mode opener
```

## Fixtures

Place fixture files under:
- `fixtures/<appId>/opener/*.txt`
- `fixtures/<appId>/app_chat/*.txt`
- `fixtures/<appId>/reg_chat/*.txt`

Legacy layout is also supported:
- `fixtures/opener/*.txt`
- `fixtures/app_chat/*.txt`
- `fixtures/reg_chat/*.txt`

Each fixture is the exact text sent as the **user** message.

## Outputs

Outputs go to `out/<timestamp>/...`.
- `out/<runId>/manifest.json`
- `out/<runId>/<fixtureName>.txt`

## Safety

- Reads `OPENAI_API_KEY` from environment.
- Never writes keys to disk.

## Planned features (v1):
- Run a mode (opener/app_chat/reg_chat) across all fixtures
- Save outputs to `out/` with a run manifest
- A/B compare two prompt variants

## Secrets
- Do **not** store API keys in this repo.
- The CLI should read `OPENAI_API_KEY` from environment.
