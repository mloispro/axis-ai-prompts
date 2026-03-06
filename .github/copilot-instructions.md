# Copilot instructions (axis-ai-prompts)

## What this repo is
- This is a **public prompt catalog**: canonical prompt JSON lives in `prompts/<appId>.json`.
- Treat everything here as public: **never add secrets/PII** (API keys must not be committed).

## Consumer model (important)
- This repo is **not** the production app.
- A **separate consumer app** (e.g., Android) may fetch `prompts/<appId>.json` from public GitHub and then inject runtime inputs before calling the model.
- The workbenches under `tools/` are for local iteration + regression checking against `fixtures/`.

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
- Entry: `tools/workbench-web/server.py` (FastAPI + Uvicorn, default port **7540**).
- Local draft candidates are stored under `tools/workbench-web/state/` (gitignored).
- Outputs are written under `tools/workbench-web/out/` (gitignored).

#### Web workbench — key API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/candidate-prompts` | Returns current candidate JSON |
| `POST` | `/api/edit/propose` | AI proposal (supports `dryRun: true`) |
| `POST` | `/api/edit/apply`   | Writes proposal to candidate; pushes undo+draft to history |
| `POST` | `/api/edit/undo`    | Pops most recent undo snapshot; restores candidate |
| `POST` | `/api/edit/reset`   | Resets candidate to canonical base AND **wipes history entirely** (`_write_history(appId, [])`) |
| `GET`  | `/api/drafts`       | Lists `kind:"draft"` entries for the version shelf |
| `GET`  | `/api/drafts/diff`  | Returns snapshot text + diff for a specific draft id |
| `POST` | `/api/drafts/restore` | Restores a draft snapshot into the candidate |
| `POST` | `/api/drafts/delete`  | **Deletes one draft by id** — removes the draft entry + its paired undo snapshot, restores candidate to previous version or base |
| `POST` | `/api/promote`      | Writes candidate → `prompts/<appId>.json` (publish step) |

#### Web workbench — history model invariants

- History is a flat JSON list in `state/history/<appId>.json`.
- `api/edit/apply` always pushes two entries in order: `{ kind: "undo", ... }` then `{ kind: "draft", ... }`.
  They are always adjacent — the undo snapshot **immediately precedes** its paired draft.
- `api/edit/undo` pops the most recent `kind:"undo"` entry (does NOT touch `kind:"draft"` entries).
- `api/edit/reset` **wipes the entire history file** (writes `[]`). There is no "reset snapshot."
- `api/drafts/delete` removes both the targeted draft AND its immediately-preceding undo snapshot.
- The version shelf (`#versionPills`) shows only `kind:"draft"` entries filtered by current mode.

#### Web workbench — frontend UI patterns

**Version pills** (`#versionPills`):
- Each pill gets class `vp-hue-{n}` where `n = (versionNum - 1) % 8`.
- Clicking a pill calls `onPillClick` → `enterPreviewMode(id, label, text, hue)`.
- Re-clicking the active pill calls `exitPreviewMode()`.
- Base pill (`__base__`) always present, uses green (hue index 8 in `HUE_STYLES`).

**Preview mode** (`enterPreviewMode` / `exitPreviewMode`):
- Shows `#sysVersionBar` — a colored strip in normal flow ABOVE the textarea (not overlaid).
- Also populates `#sysPromptDiffOverlay` with a line diff (`dl-add-hue-{n}` / `dl-del` / `dl-ctx` spans)
  so diff highlights are visible directly on the main screen.
- `exitPreviewMode` hides version bar and clears the diff overlay (`hideSysDiffOverlay()`).
- `.sys-version-bar.visible` has `z-index: 6`; the overlay has `z-index: 5` — bar must sit above to keep close button clickable.

**Compare modal** (`#compareModal`):
- Contains `#compareModalPills` (version switcher), `#compareModalError` (inline error row),
  side-by-side `#compareBaseText` / `#compareCurrentText` panes.
- `selectComparePill(id, versionObj, knownText, versionNum)` renders diffs into both panes.
- Delete button uses `aiDeleteVersion(draftId)` — button stays enabled until server confirms.
- `selectedComparePillId` (module-level `let`) tracks which pill is active.

**Hue palette** (8 versioned colors + 1 base):
These are defined in **three places — keep in sync when changing**:
1. `.version-pill.vp-hue-{n}` + `.version-pill.vp-hue-{n}.active` rules — `workbench.css`
2. `.dl-add-hue-{n}` highlight rules — `workbench.css`
3. `HUE_STYLES[]` array — `workbench.js`

Current palette (index → name → background / text):
- 0 cyan   `#ecfeff` / `#0e7490`
- 1 amber  `#fffbeb` / `#b45309`
- 2 violet `#f5f3ff` / `#7c3aed`
- 3 sky    `#f0f9ff` / `#0369a1`
- 4 teal   `#f0fdfa` / `#0f766e`
- 5 fuchsia`#fdf4ff` / `#a21caf`
- 6 orange `#fff7ed` / `#c2410c`
- 7 indigo `#eef2ff` / `#3730a3`
- 8 green  `#f0fdf4` / `#166534` (base pill only)

**No red pills:** hue-0 was intentionally changed from rose/red to cyan — red reads as "error/deleted," which
misleads users. Do not reintroduce a red or pink hue into the cycle.

#### Web workbench — e2e tests

- Tests live in `tools/workbench-web/e2e/specs/*.spec.js` with shared harness in `tools/workbench-web/e2e/helpers/workbenchTest.js`.
- Run from `tools/workbench-web/`: `npx playwright test --reporter=line`
- Tests use `dryRun: true` — no OpenAI API key required.
- The suite includes a self-sufficient preview-mode spec that creates its own draft via dry-run apply, tests preview-bar behavior, then resets.
- After running tests the history file may be cleared; that is expected and intentional.
- Always run tests after editing `server.py`, `workbench.js`, `workbench.css`, or `index.html`.

Stability note (Windows): the workbench mutates local state files (candidate/history). The Playwright config uses `workers: 1` to avoid file-lock contention when running split specs.

#### Web workbench — UI audit workflow (how to “see the UI”)

Use Playwright E2E as a deterministic “UI camera”:

1) Ensure the web workbench is running (default: `http://127.0.0.1:7540/`).
  - Prefer VS Code task: `Workbench: Start`
2) Run an audit pass that captures screenshots even when tests pass:
  - `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test --reporter=line,html`
3) Review artifacts:
  - HTML report UI: `cd tools/workbench-web && npx playwright show-report playwright-report`
  - Raw attachments: `tools/workbench-web/playwright-report/data/*.png`

Turn a visual finding into a durable fix:
- Add/adjust the smallest code/CSS change that addresses the root cause.
- Add a Playwright assertion in the spec that produces the screenshot for that state.
- Re-run the same audit command and confirm the screenshot/state is corrected.

## Common dev commands (Windows)
- Run workbench selftest (no API calls):
  - `python .\\tools\\workbench-cli\\workbench.py selftest`
- Run opener fixtures for an app (requires `OPENAI_API_KEY`):
  - `python .\\tools\\workbench-cli\\workbench.py run --app rizzchatai --mode opener`

## Change guidance
- Keep prompt edits **data-only** (JSON content) unless you’re explicitly fixing the workbench CLI.
- If you change prompt schema expectations, update `tools/workbench-cli/workbench.py` and `tools/workbench-cli/README.md` together.
