# User Prompts Plan (RizzChatAI)

Last updated: 2026-02-26
Status: Implemented in repo (prompt JSON + workbench CLI). Android integration pending.
Owner: repo `axis-ai-prompts`

## Goal
Move hardcoded per-mode **user prompt** strings (currently assembled in the Android app) into canonical templates in this repo, similar to existing **system prompts**.

This enables:
- prompt iteration without app rebuild
- consistent prompt behavior across clients
- A/B testing in the workbench

## Non-goals (for this phase)
- No Android code changes yet
- No new UX in the workbench-web

## Current state (baseline)
- System prompts live in `prompts/rizzchatai.json` under:
  - `prompts.openerSystem`
  - `prompts.appChatSystem`
  - `prompts.regChatSystem`
- Workbench CLI (`tools/workbench-cli/workbench.py`) currently selects ONLY system prompts and sends fixtures as the **user** message.

## Target state
Add canonical user templates per mode (additive, backwards compatible):
- `prompts.openerUser`
- `prompts.appChatUser`
- `prompts.regChatUser`

These templates will be rendered with runtime variables.

## Variable contract (v1)
Templates will support these variables:
- `{{tie_in}}`:
  - user-provided “must tie in something about …” topic
  - may be blank; when blank, the tie-in instruction must be omitted by the renderer
- `{{tie_in_block}}`:
  - derived variable computed by the renderer
  - either an empty string, or a 1–2 line instruction that references `{{tie_in}}`
- `{{profile_text}}`:
  - profile OCR / parsed profile text (from `ProfileAnalyzer.analyzeProfileImage`)
- `{{chat_transcript}}`:
  - sanitized transcript text (from `TextSanitizer.sanitizeChatTranscript`)

Notes:
- Prefer plain text instructions (avoid Markdown like `**...**`) to reduce formatting leakage.
- Keep constraints/tone rules in *system* prompts; keep *user* prompts mostly data + task framing.

## Template mapping from Android code (what we have today)
### Opener (profile)
Android today (summary):
- Provides `profileText`
- Adds constraints like “use their name”, “don’t mention job/school”, “short”, “no pickup lines”
- Adds tie-in instruction based on dialog prompt

Plan:
- Keep constraints in `openerSystem` (already present).
- User template should provide:
  - `profile_text`
  - optional tie-in instruction
  - single task framing: “Write the opener to send.”

### App Chat (dating app chat)
Android today (summary):
- Provides cleaned transcript
- Adds “Assistant must tie in something about: <tie_in>”

Plan:
- User template should provide:
  - `chat_transcript`
  - optional tie-in instruction
  - single task framing: “Write the next message to send.”

### Reg Chat (friends/family/work)
Android today (summary):
- Same structure as App Chat, but allows longer output and different system rules

Plan:
- Same `chat_transcript` + optional tie-in + “next message” framing.

## Fixtures plan (for later implementation)
Today: fixtures are `.txt` files that become the exact user prompt.

Target: introduce structured fixtures (keep `.txt` as legacy):
- `fixtures/rizzchatai/opener/*.json`:
  - `{ "profile_text": "...", "tie_in": "..." }`
- `fixtures/rizzchatai/app_chat/*.json`:
  - `{ "chat_transcript": "...", "tie_in": "..." }`
- `fixtures/rizzchatai/reg_chat/*.json`:
  - `{ "chat_transcript": "...", "tie_in": "..." }`

Workbench later renders:
- system = `*System`
- user = render `*User` with fixture variables

## Milestones
### M0 — Plan + template draft (doc-only)
- [x] Add this plan file
- [x] Draft `openerUser/appChatUser/regChatUser` templates (in plan first, then JSON)

### M1 — Prompt JSON update (repo data)
- [x] Add `openerUser/appChatUser/regChatUser` to `prompts/rizzchatai.json`
- [x] Update `updatedAt`
- [x] Keep existing system keys untouched

### M2 — Workbench CLI support
- [x] Extend `workbench.py` to select user template per mode
- [x] Add simple template rendering (variable substitution)
- [x] Add `.json` fixture support for variable injection
- [x] Keep `.txt` fixtures working as “already-rendered user prompt”

### M3 — Validation
- [x] Add a few `.json` fixtures mirroring existing `.txt`
- [x] Run `python .\tools\workbench-cli\workbench.py selftest`
- [x] Run dry-run passes for `opener`, `app_chat`, `reg_chat` (no `OPENAI_API_KEY` required)

## Decisions
- Canonical source location: **A) this repo is source of truth** (confirmed)
- Renderer behavior: omit tie-in clause when `tie_in` is blank (TBD exact syntax)

## Next step
Draft the initial text of `openerUser`, `appChatUser`, `regChatUser` templates (v1) aligned to current Android behavior.

## Draft templates (v1)

### `prompts.openerUser`
Use when mode is `opener`.

```
Dating profile text:
{{profile_text}}

{{tie_in_block}}

Write the next message to send as an opener.
Output only the opener text.
```

### `prompts.appChatUser`
Use when mode is `app_chat`.

```
Chat transcript:
{{chat_transcript}}

{{tie_in_block}}

Write the next message to send.
Output only the message text.
```

### `prompts.regChatUser`
Use when mode is `reg_chat`.

```
Chat transcript:
{{chat_transcript}}

{{tie_in_block}}

Write the next message to send.
Output only the message text.
```

### `tie_in_block` renderer rule
- If `tie_in` is blank/whitespace: `tie_in_block = ""`
- Else:

```
Naturally work in this topic if possible: {{tie_in}}
```
