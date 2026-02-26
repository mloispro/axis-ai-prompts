# Prompt Workbench Plan (Simple, Slick, No-Regressions)

Last updated: 2026-02-25
Status: Plan only (no code changes in this phase)
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
8) (Ship) Land the change in this repo so the Android app’s raw URL updates.

## Web UI workflow (today, as built)
What you can do right now in the local web workbench (good for one-off testing, not regression-proof yet):

1) Select App + Mode + Model, optionally toggle “Dry run”.
2) Edit “System prompt (for selected mode)”.
3) Optionally edit “User prompt template (for selected mode)”.
  - This is saved into a local candidate bundle at `tools/workbench-web/state/candidates/<appId>.json` (gitignored).
4) Paste a one-off “User prompt” (runtime test input).
5) Click “Run” to call the API and see output + tokens + cost.

Important current limitation:
- The “Run” action currently executes ONLY the two runtime textareas you see (systemPrompt + userPrompt). It does not yet render the per-mode user template, does not yet compose a structured input object, and does not yet run fixture suites from the UI.

Fixture suite note:
- The backend already has an A/B suite endpoint (`/api/run/ab`) that runs fixtures and writes an HTML report, but the UI does not expose it yet.

## Canonical data contract (v1)
Per run, the workbench should operate on a structured input object (regardless of whether the source is a fixture or paste-in text):

### Fields
- `mode`: `opener | app_chat | reg_chat`
- `profile_text`: string (opener only)
- `chat_transcript`: string (app_chat/reg_chat)
- `tie_in`: string (optional)
- `user_instructions`: string (optional)

### Key decision: user instructions are appended separately
User instructions are NOT embedded into the user template by default.
Instead, after rendering the per-mode user template, the workbench appends a separate block:

If `user_instructions` is blank → append nothing.

Else append:

```

User-added instructions:
<user_instructions>
```

Rationale:
- Keeps canonical templates stable and comparable.
- Lets prompt engineers experiment quickly without rewriting templates.
- Preserves a clear audit trail in preview + manifests.

## Message composition algorithm
Given a prompt bundle for an app (candidate) and a structured input:

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

4) Append user-added instructions block (if present).

5) Preview and run:
- show the exact system text
- show the exact composed user text
- run the model

Reality check (why this is in the plan): the algorithm above is the target behavior. The current web UI does not yet perform this composition end-to-end.

## Workbench UX plan (web)
Single page. No tabs needed.

### Baseline vs candidate (make this explicit in the UI)
- **Baseline**: what the shipping app is expected to use today (usually `prompts/<appId>.json`, optionally a remote raw GitHub URL).
- **Candidate**: your local draft edits (stored under `tools/workbench-web/state/candidates/<appId>.json`, gitignored).
- What you “ship” is a normal repo diff to `prompts/<appId>.json` (candidate → commit/merge). The `state/` candidate files are just local drafts.

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
  - opener: `profile_text`, `tie_in`, `user_instructions`
  - app_chat/reg_chat: `chat_transcript`, `tie_in`, `user_instructions`

### Preview panel (non-negotiable)
Always show:
- the exact system prompt text used
- the exact composed user message text used (rendered template + appended instructions)

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

## Workbench UX plan (CLI)
Keep the CLI as the “batch engine” reference.
Later: add `user_instructions` to `.json` fixtures and implement the same append rule as web.

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
3) Workbench calls a reasoning-capable model (ChatGPT latest thinking via Responses API).
4) Model returns ONLY the updated text for that key (or a minimal patch).
5) Workbench shows diff and requires explicit Apply.
6) On apply: auto-run suite and show regression summary.

### Guardrails for AI editing
- The model may only modify the selected key. No other keys.
- Must preserve style constraints (no new formatting conventions unless requested).
- Must not introduce secrets, PII, or external URLs.
- Must keep “Output format” constraints consistent (e.g., no quotes if system forbids).
- Must not silently broaden scope (no extra pages/features).

### Suggested prompt for the editor model (conceptual)
Inputs provided to the model:
- target key name
- current text
- change request
- known constraints (mode-specific)

Outputs required:
- updated text only OR minimal patch
- short rationale
- self-check list: confirms constraints maintained

## Milestones
### M0 — Contract + plan (this document)
- Define structured input object
- Lock append rule for `user_instructions`
- Define AI edit workflow + guardrails

### M1 — Web: batch run (fastest value)
- “Run suite” for mode (default action) backed by the existing `/api/run/ab` endpoint
- Simple results table + link to the HTML report

### M2 — Web: structured input + composed preview (least confusion)
- Fixture picker (default: ALL fixtures) + optional fixture dropdown for “Run single”
- Variable editors + always-on preview
- Render the per-mode user template into a composed user message (template + tie-in + appended user instructions)
- Ensure “Run single/suite” uses the candidate bundle’s selected mode `*System` + rendered `*User`
- Persist state locally per app

### M3 — AI prompt editor (safe)
- Target selector (one key)
- Change request field
- Diff preview + explicit Apply
- Apply triggers auto suite run

### M4 — Unify engine logic (avoid drift)
- Shared module for prompt loading + rendering + flags used by CLI and web

## Open questions
- Do we need a “strict output” toggle (extra guardrails) for opener/app_chat? (Maybe)

## MVP acceptance criteria (so we know we’re done)
- You can pick app+mode and run ALL fixtures (suite-by-default).
- Preview always shows the exact System + exact composed User that will be run.
- Editing system/user templates affects what is composed + run (candidate bundle is used for runs).
- `user_instructions` are appended only when non-blank (never silently embedded into templates).
- You can request an AI-assisted edit to ONE key, see a diff, apply it, and it automatically re-runs the suite.
- The final artifact is a normal repo change to `prompts/<appId>.json` that can be merged so the Android app (fetching from GitHub) picks it up.
