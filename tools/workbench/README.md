# Prompt Workbench (Desktop)

This folder will contain the Python CLI that calls OpenAI directly so you can iterate on prompts quickly without rebuilding the Android app.

Planned features (v1):
- Run a mode (opener/app_chat/reg_chat) across all fixtures
- Save outputs to `out/` with a run manifest
- A/B compare two prompt variants

Secrets
- Do **not** store API keys in this repo.
- The CLI should read `OPENAI_API_KEY` from environment.

