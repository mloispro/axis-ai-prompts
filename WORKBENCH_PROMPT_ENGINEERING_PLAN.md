# Prompt Workbench Plan (Simple, Slick, No-Regressions)

Last updated: 2026-03-02
Status: As-built notes + forward plan + active UI redesign (Playground)
Repo: axis-ai-prompts (public — no secrets/PII)

## Why this plan exists
The current workbench is hard to use for prompt engineering because it’s missing the core loop:

Edit prompt → see exact messages → run the fixture suite → spot regressions fast.

In the real app, the user message is composed from:
- screen-scrape payload (profile text or chat transcript)
- optional user-entered instructions
- canonical per-mode user template (opener/app_chat/reg_chat)

So the workbench needs to make that composition explicit, previewable, and batch-runnable.

## Goals
- One-screen workflow that a prompt engineer can use in minutes.
- Reproducible inputs: same fixture + prompts → same composed messages.
- Edit both system + user templates per mode.
- Default to running the fixture suite (not one-off tests).
- AI-assisted edits that are diff-first and guarded (no surprise changes).

## Optimization priorities (v1)
This plan optimizes for all three simultaneously:

1) Fastest iteration
- Default action is “Run suite” (batch) with an optional max-fixtures cap for quick cycles.
- A clear “Run single” path exists for tight loops on one fixture.
- Preview is always-on and shows the exact composed messages before you spend tokens.

2) Least confusion
- The UI makes “Baseline vs Candidate” explicit.
- The UI makes “Fixture-driven runs” vs “Ad-hoc debug runs” explicit.
- The thing you run is the thing you preview (no hidden composition, no silent template bypass).

3) Easiest implementation
- Reuse existing server capabilities wherever possible (especially `/api/run/ab`).
- Keep MVP to one screen and one mental model (fixture-first composition).
- Defer nice-to-haves (fancy diff UI, dashboards, deep filtering) until after the golden path is rock-solid.

## Non-goals (for this phase)
- No changes to the separate Android consumer app (it lives elsewhere).
- No hosted service; everything remains local.
- No extra pages, dashboards, or complicated tooling.

## Consumer model (important)
The RizzChatAI Android app is a separate codebase.
It:
- fetches the prompt bundle JSON from this public GitHub repo (e.g. a raw URL to `prompts/rizzchatai.json`)
- injects runtime inputs (profile/chat scrape + optional user instructions)
- calls ChatGPT

Therefore the workbench must optimize for:
- editing the canonical JSON prompt bundle in this repo
- validating changes against fixtures (no regressions)
- producing a publishable change (PR/merge) so the Android consumer picks it up

## Golden path (the only flow that matters)
1) Pick app + mode.
2) Pick a fixture set (default: all fixtures for that app+mode).
3) Choose ONE thing to edit (dropdown): a single prompt key (system or user template).
4) Make the change (manual edit OR AI-assisted “Propose change”).
5) Preview the exact system + composed user message.
6) Apply (with diff preview).
7) Auto-run the fixture suite and show a compact regression table.
8) (Ship) Promote the local draft to the git-tracked canonical file and land the repo diff so the Android app’s raw URL updates.

## 3-minute walkthrough (how a prompt dev actually uses this)
1) Open the web workbench, select `App` + `Mode`, keep fixtures = ALL.
2) Skim the always-on preview for 1–2 fixtures to confirm you’re editing the right mode.
  - If the fixture is `.txt`, that text is the final user message.
  - If the fixture is `.json`, the user message is rendered from the user template.
3) Edit ONE thing (system or user template) in the candidate editor (local draft).
4) Run “Run suite” and scan the table for errors + unexpected flags.
5) Click through to the HTML report when something looks off (diffs + full outputs).
6) Optional: use the AI editor to propose a change, then Apply (diff-first) and re-run.
7) When satisfied: Promote to canonical (writes `prompts/<appId>.json` + updates `updatedAt`).

## Web UI workflow (today, as built)
What you can do right now in the local web workbench (fixture-first regression loop):

1) Select App + Mode + Model, optionally toggle “Dry run”.
2) Select fixtures (default: ALL fixtures for that app+mode).
  - Optional: select a single fixture for “Run single”.
  - Optional: cap with “Max fixtures” for fast cycles.
3) Candidate edits:
  - Edit “System prompt (for selected mode)”.
  - Edit “User prompt template (for selected mode)”.
  - These are saved into a local candidate bundle at `tools/workbench-web/state/candidates/<appId>.json` (gitignored).
4) Preview (always-on): see the exact composed Baseline vs Candidate messages BEFORE running.
  - Preview renders through a no-network compose endpoint (no model call).
5) Run:
  - “Run suite” runs Baseline vs Candidate A/B over the fixture set and returns a compact summary plus the rendered inputs per fixture.
  - “Run single” targets a single fixture.
6) Advanced (debug-only): a separate ad-hoc section exists for one-off runtime textareas.

Notes:
- The thing you run is the thing you preview (no hidden composition).
- The suite runner is exposed via the web UI and backed by the existing A/B engine.

## Canonical data contract (v1)
Per run, the workbench should operate on fixture-driven inputs. Today (as built) there are two fixture “contracts”:

### Fixture contracts (as built)
- `.txt` fixtures: already-composed user messages (no template rendering; the file contents are the final user message).
- `.json` fixtures: structured inputs rendered through the per-mode user template.
  - Supported keys:
    - `profile_text` (opener)
    - `chat_transcript` (app_chat/reg_chat)
    - `tie_in` (optional)
  - Optional escape hatch:
    - `user_prompt` (string): if present and non-blank, it overrides rendering and is treated as the final user message.

### Future extension (planned)
We may add `user_instructions` as a structured field later.
If/when we do, the intended behavior is:
- render the per-mode user template first
- then append a separate “User-added instructions” block only when non-blank

This is intentionally not in the “as-built” contract yet, so engineers don’t assume it exists in regression runs.

## Message composition algorithm
Given a prompt bundle for an app (candidate) and a fixture input:

1) Select system prompt key:
- opener → `prompts.openerSystem`
- app_chat → `prompts.appChatSystem`
- reg_chat → `prompts.regChatSystem`

2) Select user template key:
- opener → `prompts.openerUser`
- app_chat → `prompts.appChatUser`
- reg_chat → `prompts.regChatUser`

3) Render the user template with variables:
- `{{profile_text}}` (opener)
- `{{chat_transcript}}` (app_chat/reg_chat)
- `{{tie_in_block}}` (derived)

`tie_in_block` rule:
- if `tie_in` is blank: `""`
- else: `Naturally work in this topic if possible: <tie_in>`

4) Render rules (as built):
- `.txt` fixtures bypass rendering entirely (the file is the final user text).
- `.json` fixtures render using the variables above (unless `user_prompt` override is present).
- After rendering, collapse excessive blank lines and normalize line endings.

5) Preview and run:
- show the exact system text
- show the exact composed user text
- run the model

Contract note: the algorithm above is the expected behavior and should remain the single source of truth for composition (so CLI and web do not drift).

## Workbench UX plan (web)
Single page. No tabs needed.

### Baseline vs candidate (make this explicit in the UI)
- **Baseline**: what the shipping app is expected to use today (usually `prompts/<appId>.json`, optionally a remote raw GitHub URL).
- **Candidate**: your local draft edits (stored under `tools/workbench-web/state/candidates/<appId>.json`, gitignored).
- What you “ship” is a normal repo diff to `prompts/<appId>.json` (candidate → commit/merge). The `state/` candidate files are just local drafts.

Terminology note (important for versioning UX):
- **Draft**: local-only edits that are NOT yet part of git history (candidate bundle + local history).
- **Repo prompts** (canonical): repo-tracked `prompts/<appId>.json` that will be pushed to GitHub.
- **Git history**: once promoted to canonical and committed, version history belongs in git (not the workbench).

### Layout (one screen, optimized)
- Top row: App | Mode | Model | Dry run
- Prompt editors (candidate bundle): System prompt editor + User template editor (for selected mode)
- Inputs (fixture-first): fixture picker (default ALL) + max-fixtures cap + structured fields
- Preview (always-on, read-only): exact System + exact composed User message
- Actions: Run suite (primary) | Run single (secondary)
- Results: regression table + link to full report

### MVP controls (keep it minimal)
- Fixture selection:
  - Default: ALL fixtures for app+mode.
  - Optional: a single “Fixture” dropdown for “Run single”.
  - Optional: “Max fixtures” numeric input (0 = all) to speed up iteration.
- Ad-hoc debug:
  - A collapsed “Ad-hoc test” section may exist, but it is explicitly labeled as debug-only and not part of regression coverage.

### One-screen workflow rules (what makes it “optimal”)
1) **Fixture-first by default**: the default action is always “Run suite” on ALL fixtures for the selected app+mode.
2) **Always compose**: the thing you run must be the same thing you preview (no hidden composition).
3) **Ad-hoc runs are debug-only**: allow a collapsed “Ad-hoc test” input box, but it must be visually labeled as not regression coverage.
4) **Candidate bundle is the source for runs**: “Run single/suite” uses the candidate bundle’s selected mode `*System` + rendered `*User` (not manual textarea strings).
5) **Diff-first apply**: any AI-assisted edit shows a diff, and nothing changes until Apply.

### Inputs panel (make the app reality obvious)
- Fixture source:
  - select fixture from `fixtures/<app>/<mode>/` (default: ALL)
  - or “Paste screen scrape” (profile/chat)
- Structured fields:
  - opener: `profile_text`, `tie_in`
  - app_chat/reg_chat: `chat_transcript`, `tie_in`

Future (planned): add `user_instructions` as a structured field, appended as a separate block after template rendering.

### Preview panel (non-negotiable)
Always show:
- the exact system prompt text used
- the exact composed user message text used (raw `.txt` fixture OR rendered `.json` through the user template)

### Run (batch-first)
- Primary button: “Run suite” (all fixtures for app+mode)
- Secondary button: “Run single” (only selected fixture)

Implementation note:
- The web UI should back “Run suite” with the existing `/api/run/ab` endpoint (it already runs fixtures and writes an HTML report). The UX goal is simply to surface it cleanly.

Easiest-implementation note:
- If MVP needs to ship quickly, implement “Run suite” first (ALL fixtures). Add “Run single” second (by selecting one fixture) once fixture listing is available.

### Publish mindset (keep it simple)
This repo is the source of truth. The “output” of prompt engineering is:
- a clean diff in this repo (typically `prompts/rizzchatai.json`)
- validated by running the fixture suite

So the workbench should make it easy to:
- see exactly what changed (diff)
- re-run the suite after every apply
- copy/share the exact raw candidate bundle (optional convenience)

### Results (what prompt engineers need)
Show a compact table:
- Fixture name
- Output (collapsed, expandable)
- Flags (quotes, coffee, AI mention, etc.)
- Output length / token usage / cost
- Optional: “diff vs baseline” later (not required for MVP)

### Flag semantics (as built)
The suite currently computes lightweight heuristic flags per output (not a formal pass/fail gate). Examples include:
- `mentions_ai`, `contains_quotes`, `contains_colon`, `contains_dash`, `mentions_coffee`, `too_many_lines_for_opener`, `empty_output`

Design intent:
- treat flags as “inspection hints” rather than absolute failures
- keep the list small and mode-aware
- consider later promoting a subset to “hard” failures if the team wants automated gating

## Workbench UX plan (CLI)
Keep the CLI as the “batch engine” reference.
Later (optional): add `user_instructions` to `.json` fixtures and implement the append rule consistently in both web + CLI renderers.

## AI-assisted prompt editing (core feature)
Prompt engineers should be able to say:
- “Make opener less try-hard, keep 1 line max.”
- “Remove any mention of hookups.”
- “Make app_chat close faster when there’s strong interest.”

…and have the workbench propose a careful edit.

### UX (keep it dead simple)
- Dropdown: “What are you changing?”
  - `openerSystem | openerUser | appChatSystem | appChatUser | regChatSystem | regChatUser`
- Text box: “What do you want to change?”
- Button: “Propose change” (AI)
- UI shows: before/after diff
- Button: “Apply + run suite”

### Proposed workflow (diff-first)
1) Engineer selects ONE target key.
2) Engineer types a change request.
3) Workbench calls a reasoning-capable model via the Responses API.
4) Model returns a STRICT structured JSON object (schema-validated) containing ONLY the updated text for that key.
5) Workbench shows diff and requires explicit Apply.
6) On apply: auto-run suite and show regression summary.

### Guardrails for AI editing
- The model may only modify the selected key. No other keys.
- Must preserve style constraints (no new formatting conventions unless requested).
- Must not introduce secrets, PII, or external URLs.
- Must keep “Output format” constraints consistent (e.g., no quotes if system forbids).
- Must not silently broaden scope (no extra pages/features).

Additional guardrails (template safety):
- Must preserve required template variables for that key (e.g. `{{profile_text}}`, `{{chat_transcript}}`, `{{tie_in_block}}`), and MUST NOT introduce new `{{...}}` placeholders.
- Must not delete or materially weaken any safety/consent/boundary constraints already present in the prompt.

### AI editor API contract (Responses API + Structured Outputs)
Use Structured Outputs (JSON Schema) so the model returns UI-consumable output with strict adherence.

Key Responses API notes:
- Use `instructions` for the internal editor instruction set.
- Use `text.format` for Structured Outputs in Responses (not `response_format`).
- Set `store: false` for local iteration unless you explicitly need server-side state.

#### Request shape (conceptual)
Provide the model ONLY what it needs:
- `targetKey` (one of the allowed keys)
- `currentText` (the existing value for that key)
- `changeRequest` (engineer intent)
- `constraints` (mode-specific + repo constraints)

Recommended settings:
- Low-ish temperature for stability.
- No tools (`tools: []`) and force `tool_choice: "none"`.
- `store: false`.

Operational hardening (optional but recommended):
- Pin the editor model to a specific snapshot for consistency (avoid silent behavior drift).
- Make temperature explicit and low (favor deterministic edits).
- If/when this moves beyond local-only use, set `safety_identifier` (stable, non-PII; hash a user ID/email) and consider `prompt_cache_key` for caching behavior.

#### Strict JSON schema (v1)
All fields are required, and `additionalProperties: false` everywhere.

```json
{
  "name": "prompt_edit_v1",
  "strict": true,
  "schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "status": { "type": "string", "enum": ["ok", "refused", "error"] },
      "targetKey": { "type": "string", "minLength": 1 },
      "updatedText": { "type": "string" },
      "rationale": { "type": "string" },
      "warnings": {
        "type": "array",
        "items": { "type": "string" }
      },
      "selfCheck": { "type": "boolean" },
      "refusalReason": { "type": "string" }
    },
    "required": [
      "status",
      "targetKey",
      "updatedText",
      "rationale",
      "warnings",
      "selfCheck",
      "refusalReason"
    ]
  }
}
```

Refusal handling:
- If `status == "refused"`, `updatedText` MUST equal the original `currentText` (no changes), and `refusalReason` explains why.
- The UI should also handle the non-schema refusal edge-case (if the API returns a refusal instead of JSON).

UI rule for refusals (so it’s ironclad):
- If refused, disable Apply and surface `refusalReason` prominently.

### “Ironclad” internal editor instruction set (v1)
This is the internal `instructions` string sent to the editor model.

```text
You are an expert prompt engineer working on a PUBLIC prompt catalog.

Task:
- You will edit EXACTLY ONE prompt field (the selected targetKey) by rewriting its text.

Hard rules:
- Modify only the selected targetKey.
- Output MUST be valid JSON matching the provided schema. No markdown. No extra keys.
- Do NOT add secrets, personal data, or external URLs.
- Do NOT broaden scope (no new features, no UI changes, no extra policies).
- Preserve existing safety/boundary/consent constraints in the currentText; you may strengthen them, but must not weaken or remove them.

Template safety rules (critical):
- Preserve all existing {{...}} placeholders found in currentText.
- Do NOT introduce any new {{...}} placeholders.

Quality rules:
- Keep changes minimal and targeted to the changeRequest.
- Maintain the original writing style unless the changeRequest asks otherwise.

If you cannot comply with the changeRequest while obeying the rules, set status=refused, keep updatedText identical to currentText, and explain in refusalReason.
```

### Apply-time validation (workbench-side)
Even with Structured Outputs, validate before applying:
- `targetKey` must exactly match the requested key.
- If `status == "refused"`, do not apply.
- If `selfCheck == false`, do not apply.
- Ensure `updatedText` contains all placeholders that existed in `currentText` and contains no new `{{...}}` placeholders.
- Optionally: run a quick “compiles” check (e.g., no unbalanced braces) before enabling Apply.

## Undo / Reset (non-negotiable for safe iteration)
Undo/reset are local-only operations on the candidate bundle.

### Edit history (local, unsaved) — AS BUILT
Problem we solved:
- The history dropdown was confusing because it mixed “real edits” with suite runs.

As-built behavior:
- The UI shows an **Edit history** list that includes **only snapshots created by Apply** (reason: `apply:<targetKey>`).
- Suite runs are **not** shown as “versions” in that list; instead the UI shows a separate **latest suite: clean / not clean** status line.
- On load/refresh, if there are any edit snapshots, the UI auto-selects the newest snapshot so **Diff/Notes populate immediately**.

Storage (as built):
- Local snapshots live in `tools/workbench-web/state/history/<appId>.json` (gitignored) and include a `kind` field:
  - `kind="undo"`: undo stack snapshots (used by Undo)
  - `kind="draft"`: post-Apply edit snapshots (shown in Edit history)
  - `kind="suite"`: suite run snapshots (used for publish gating + latest suite status)

Clean definition (as built):
- “clean” is computed from the latest suite snapshot and is used to enable/disable publishing.
- Minimum gates:
  - suite completed (`status == ok`)
  - candidate has no `empty_output`
  - (mode-aware) opener also blocks on `too_many_lines_for_opener`

Lifecycle:
- Local history is cleared when publishing to repo prompts, because from that point forward git is the version history.

### Undo last apply
- Persist a small history stack under `tools/workbench-web/state/` (recommended default), and also keep the in-memory stack for immediate UX.
- “Undo” restores the previous candidate bundle text for the last edited key and re-runs compose preview.
- Undo should NOT delete fixture outputs; it simply changes what will be run next.

### Reset to baseline
- “Reset” discards the local candidate bundle and reloads from the baseline bundle (normally `prompts/<appId>.json`).
- Reset requires confirmation (because it’s destructive to local draft state).
- After reset: preview updates immediately; next run uses baseline-as-candidate (no diff).

### Promote draft to canonical (ship step) — NEW UX PLAN
Problem:
- “Apply” updates the local candidate bundle, but shipping requires updating the repo-tracked `prompts/<appId>.json`.

Goal:
- Add an explicit “Publish to repo prompts” action:
  - Writes candidate → `prompts/<appId>.json`
  - Updates `updatedAt` in that canonical file
  - Clears local draft versions/history because git now tracks versions
  - Leaves the workbench in a clean state where candidate == baseline (no diff)

Guardrails:
- Requires confirmation.
- Should be disabled unless the latest suite run is “clean” (configurable, but recommended).
- Must never write secrets/PII.

### Editor call inputs/outputs (concrete)
Inputs provided to the model (as a single user message payload):
- `targetKey`
- `currentText`
- `changeRequest`
- `constraints` (repo + mode constraints + template var requirements)

Outputs required:
- Strict JSON matching the schema, including:
  - `updatedText` (the only proposed new value for the selected key)
  - `rationale`, `warnings`, and `selfCheck`

## Milestones
### M0 — Contract + plan (this document)
- Define fixture contracts (.txt = raw user prompt, .json = structured render w/ `user_prompt` override)
- Define future `user_instructions` append rule (planned)
- Define AI edit workflow + guardrails

### M1 — Web: batch run (fastest value) (DONE)
- “Run suite” for mode (default action) backed by the existing `/api/run/ab` endpoint
- Simple results table + link to the HTML report

### M2 — Web: structured input + composed preview (least confusion) (DONE)
- Fixture picker (default: ALL fixtures) + optional fixture dropdown for “Run single”
- Variable editors + always-on preview
- Render `.json` fixtures through the per-mode user template (with tie-in) and preview baseline vs candidate
- Ensure “Run single/suite” uses the candidate bundle’s selected mode `*System` + rendered `*User`
- Persist state locally per app

### M3 — AI prompt editor (safe) (DONE)
- Target selector (one key)
- Change request field
- Diff preview + explicit Apply
- Apply triggers auto suite run

### M3.5 — Draft versions shelf (local, unsaved)
 (DONE)
- Store snapshots with `kind` and keep **Edit history = Apply snapshots only**
- Show latest suite clean/not-clean status separately (suite snapshots are not versions)
- Auto-select newest edit snapshot so Diff/Notes populate on launch

### M3.6 — Promote to canonical (ship)
 (DONE)
- Button to write candidate to `prompts/<appId>.json`
- Confirmation + require latest suite run to be clean (recommended default)
- Clear local history on success

### M3.7 — Playground UI redesign (IN PROGRESS)
See "Playground UI design (M3.7)" section below for full spec.

Key goals:
- Replace three-column complex layout with two-column OpenAI-Playground-style layout.
- Move inline AI improve bar directly below the prompt editors (no separate card).
- Collapse all non-critical controls into an Advanced accordion.

### M4 — Unify engine logic (avoid drift)
- Shared module for prompt loading + rendering + flags used by CLI and web

## Playground UI design (M3.7)

### Rationale
The previous 3-column flex layout was too busy. Every control was visible at once, making the page hard to scan. The new design prioritizes one mental model: **edit on the left, run on the right**, everything else hidden until needed.

Reference: OpenAI Chat Playground (clean two-column, textarea dominant, controls minimal).

### Layout (two-column split)

```
┌─ topbar (sticky) ─────────────────────────────────────────────────┐
│  Prompt Workbench | App ▾ | Mode ▾ | Model ▾ | □ Dry run  status │
└───────────────────────────────────────────────────────────────────┘
┌─ editor-panel (45%) ─────────┬─ run-panel (55%) ──────────────────┐
│ SYSTEM PROMPT                │ Fixture ▾  Max [0]  [Run]  status  │
│ ┌──────────────────────────┐ │                                     │
│ │ textarea                 │ │  results (scrollable)               │
│ └──────────────────────────┘ │                                     │
│ USER TEMPLATE                │                                     │
│ ┌──────────────────────────┐ │                                     │
│ │ textarea                 │                                     │
│ └──────────────────────────┘ │                                     │
│ ASK AI TO IMPROVE            │                                     │
│ ┌────────────────┬Sys│User┬▶┐│                                     │
│ │ input          │   │    │ ││                                     │
│ └────────────────┴───┴────┴─┘│                                     │
│ [diff area – hidden until AI]│                                     │
│ [Apply] [Discard]            │                                     │
├──────────────────────────────┴─────────────────────────────────────┤
│ [Undo] [Reset]                          [Publish to repo] status   │
└────────────────────────────────────────────────────────────────────┘
▶ Advanced ──────────────────────────────────────────────────────────
  Edit History | Diff/Notes | Preview | Bundle metadata | JSON | Tune
```

### Editor panel (left, 45%)
- **System Prompt** — large textarea, `id="systemPrompt"`, `min-height: 260px`
- **User Template** — textarea, `id="userTemplate"`, `min-height: 100px`
- **AI Improve bar** — inline bar anchored below the editors:
  - Text input `id="aiChangeRequest"` — placeholder "E.g., make it warmer… (Enter to run)"
  - **Sys / User pill toggle** — `id="aiTargetSysBtn"` / `id="aiTargetUserBtn"` — selects which textarea the AI edits
  - Run button `id="aiProposeBtn"` (▶)
  - `id="aiDiffWrap"` — hidden until a proposal arrives; contains:
    - `<div class="diff-area" id="aiDiff">` — colored inline diff
    - Action row: `[Apply id=aiApplyBtn]` `[Discard id=aiDiscardBtn]` `span#aiAppliedInfo` `span#aiError`
  - `<pre id="aiNotes">` — hidden (used for compatibility; notes surface in Advanced)
  - `<select id="aiTargetKey">` — hidden select (still drives server call; pills sync it)
- **Footer** — `[Undo]` `[Reset]` spacer `[Publish to repo]` `span#promoteStatus`

### Run panel (right, 55%)
- **Header strip**: `select#fixtureSelect` | `input#maxFixturesInput` | `button#runSuiteBtn` | `span#status`
- **Results area**: `div#results` (scrollable, no fixed height cap; result cards expand inline)

### Advanced accordion (collapsed by default)
Contains everything that was previously "above the fold" but rarely needed during iteration:

| Sub-section | Elements |
|---|---|
| Edit History | `draftSelect`, `draftMeta`, `draftRefreshBtn`, `draftRestoreBtn`, `lastTraceId` (+ logs link) |
| Diff / Notes (history) | `pre#aiDiffAdv`, `pre#aiNotesAdv` — replacing old `aiDiff`/`aiNotes` for snapshot diffs |
| Preview | `previewStatus`, `baselinePreviewSystem/User`, `candidatePreviewSystem/User` |
| Bundle metadata | `updatedAtInput`, `ttlSecondsInput`, `versionInput` |
| JSON editor | `formatJsonBtn`, `validateJsonBtn`, `candidateJson`, `jsonStatus`, `jsonError` |
| Ad-hoc tune | `userPrompt`, `runTuneBtn`, `tuneStatus` |

### AI improve bar UX rules
1. **Sys pill active by default** — maps to the mode's `*System` key.
2. **User pill** — maps to the mode's `*User` key.
3. **Enter key** triggers propose (no need to click ▶).
4. **Diff renders inline with color** — `+` lines green, `-` lines red, `@@` headers blue.
5. **Apply is disabled until proposal is `status=ok` and `selfCheck=true`**.
6. **Discard** calls `clearAiProposal()` and hides `aiDiffWrap`.
7. **Changing the input text** disables Apply immediately (stale proposal guard).
8. **Pill buttons stay in sync** with the hidden `aiTargetKey` select (and vice versa).

### Colored diff rendering
New function `renderColoredDiff(rawText, targetEl)` replaces `textContent` assignment:
- Splits diff text on `\n`
- For each line: creates a `<span>` with class `dl-add` / `dl-del` / `dl-hdr` / `dl-ctx`
- Never uses `innerHTML` with user data (createElement + textContent only)

### JS changes required (for `workbench.js`)

**New functions:**
```javascript
function renderColoredDiff(rawText, targetEl) { /* span per line, classList by prefix */ }
function setAiTarget(which)                    { /* sync pills + hidden aiTargetKey select */ }
```

**Modified functions:**
- `clearAiProposal()` → also sets `aiDiffWrap.style.display = 'none'` and clears `aiDiff.innerHTML`
- `aiPropose()` → calls `renderColoredDiff()` and sets `aiDiffWrap.style.display = ''`
- `onDraftSelected()` → writes to `aiDiffAdv` / `aiNotesAdv` (not `aiDiff` / `aiNotes`)

**New event listeners:**
- `aiTargetSysBtn` → `setAiTarget('sys')`
- `aiTargetUserBtn` → `setAiTarget('user')`
- `aiDiscardBtn` → `clearAiProposal()`; clear `aiEditStatus`
- `aiChangeRequest` keydown Enter → `aiPropose()`
- `aiTargetKey` change → sync pills; `clearAiProposal()`; `onDraftSelected()`

### File structure after componentization

```
tools/workbench-web/static/
  index.html          ← HTML shell only (~200 lines); links to css + js
  css/
    workbench.css     ← all styles extracted from <style> block
  js/
    workbench.js      ← all JS extracted + new functions added
```

Benefits:
- Each file is independently editable without scrolling 1300 lines
- CSS changes don't risk corrupting JS (no giant monolith)
- JS can be searched/edited with grep without noise from HTML/CSS
- `index.html` now purely describes structure (easy to reason about layout)

---

## Open questions
- Do we need a “strict output” toggle (extra guardrails) for opener/app_chat? (Maybe)

## MVP acceptance criteria (so we know we’re done)
- You can pick app+mode and run ALL fixtures (suite-by-default).
- Preview always shows the exact System + exact composed User that will be run.
- Editing system/user templates affects what is composed + run (candidate bundle is used for runs).
- Fixture rendering behaves deterministically:
  - `.txt` fixtures are treated as already-composed user messages
  - `.json` fixtures render through the per-mode user template (or `user_prompt` override)
- You can request an AI-assisted edit to ONE key, see a diff, apply it, and it automatically re-runs the suite.
- You can undo the last applied edit and reset candidate back to baseline.
- The final artifact is a normal repo change to `prompts/<appId>.json` that can be merged so the Android app (fetching from GitHub) picks it up.
