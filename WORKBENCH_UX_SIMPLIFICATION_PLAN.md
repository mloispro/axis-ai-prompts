# Workbench — Playwright UI Audit Harness Plan (and Fix Backlog)

Purpose: make Playwright tests act like a repeatable “UI inspector” for the web workbench—able to drive the app into meaningful states, capture screenshots, verify key behaviors, and generate a concrete list of UX/UI bugs + workflow inefficiencies.

Scope: web workbench only (`tools/workbench-web/`). No prompt content work and no production app work.

---

## Current status (shipped)

The audit harness + suite structure is implemented.

- Test structure:
  - `tools/workbench-web/e2e/helpers/workbenchTest.js`
  - `tools/workbench-web/e2e/specs/*.spec.js` (multiple specs; see list below)
  - `tools/workbench-web/e2e/global-teardown.js`
- Config:
  - `tools/workbench-web/playwright.config.js` uses `workers: 1` (Windows stability) and global teardown
- Artifact capture:
  - Standard diagnostics + screenshots on failure
  - Optional audit-mode screenshots on success via `E2E_AUDIT=1`

Manual visual sweep (2026-03-06): reviewed audit screenshots for preview mode, AI editor, and compare modal; no new UI quirks found beyond the fixed P0–P2 items below.

This plan now focuses on: (1) expanding the state matrix + assertions, and (2) tracking real UI fixes found via the audit artifacts.

---

## What we’re doing (concept)

Treat Playwright as two things at once:

1) Regression tests (binary pass/fail for core behaviors)
2) An audit tool (recording screenshots/snapshots/logs across states so humans can quickly spot problems)

The harness should answer:

- Can we reproduce state X quickly and deterministically?
- What does state X look like (screenshot)?
- Are there console errors, failing network requests, or missing UI affordances?
- Is the workflow efficient, clear, and reversible?

---

## Outputs / artifacts (what the harness produces)

### Always-on capture (per test)

- Screenshots for key states (stable naming so diffs are easy)
- Console + pageerror log captured and attached to failures (optionally saved on success)
- Network failures summarized (4xx/5xx + request URL)

### Optional “audit run” output

- Playwright HTML report with embedded attachments
- Deterministic screenshot set in report artifacts (useful for manual UI review)

---

## How we “see the UI” now

There are two reliable ways to visually inspect UI states:

1) Run the E2E suite in audit mode to generate named screenshots.
  - `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test --reporter=line,html`
2) Open the Playwright HTML report and/or directly inspect `tools/workbench-web/playwright-report/data/*.png`.

This makes “find quirks” repeatable: if you can name the state, you can re-render it and capture it.

---

## State matrix (the core of the audit)

We need a deliberate list of states that represent meaningful UX transitions, not just clicks.

### Axes

- App: `rizzchatai` (start here; can generalize later)
- Mode: opener / app chat / reg chat
- History depth: base only, +1 draft, +many drafts (e.g., 6–10)
- Viewing mode: live (latest), preview base, preview older draft
- Compare modal: closed, open on base, open on a draft
- Error states: expected errors (e.g., delete base disabled) and unexpected errors (should be surfaced in UI)

### Minimum required states to capture

1. Fresh load (no preview UI; latest is live)
2. After creating 1 draft (pill list shows v1)
3. After creating N drafts (pill colors cycle; no layout breaks)
4. Preview base (version bar visible; diff overlay visible)
5. Preview an older draft (version bar hue matches pill)
6. Compare modal open (base vs current)
7. Compare modal open + delete version (delete button behavior, pill removed)
8. Undo behavior (if present in UI; confirm semantics + messaging)
9. Deep scroll + switch WIP pills (ensure interaction + scroll behavior stays sane)

---

## Assertions (what “working correctly” means)

### Functional invariants

- No unexpected JS errors on load and during common flows
- Version pills reflect server state (create draft → new pill; delete draft → pill disappears)
- Preview mode is clearly labeled and reversible
- Compare modal shows correct left/right panes for the selected pill
- Buttons are correctly enabled/disabled (especially destructive actions)

### UX workflow invariants

- The current (latest) state should not feel like a preview
- Users should never lose their place due to a modal closing before errors are shown
- All critical actions provide a clear confirmation or error message in the visible surface

### Layout / affordance checks

- No overlaps (version bar vs diff overlay; modals vs content)
- Version pills remain identifiable when active (hue preserved)
- Keyboard basics: tab order reaches all controls; modal traps focus (if implemented)

---

## Test suite structure (expanded + nicer organization)

Current suite layout (implemented):

- `tools/workbench-web/e2e/helpers/workbenchTest.js`
  - shared `test` fixture + diagnostics capture + audit helpers
- `tools/workbench-web/e2e/specs/`
  - `01_bootstrap.spec.js`
  - `02_dry_run_suite.spec.js`
  - `03_ai_editor.spec.js`
  - `04_compare_modal.spec.js`
  - `05_version_pill_preview.spec.js`
  - `06_responsive_layout.spec.js`
  - `07_multi_draft_hues.spec.js`
  - `08_mode_switching_pills.spec.js`
  - `09_publish_eligibility.spec.js`
  - `10_pill_scroll_switching.spec.js`

This layout is the baseline. Any new “state capture” should be:
- one helper (if reusable)
- one new screenshot name (stable)
- one new assertion (if the state reveals a bug class we can lock down)

---

## “Audit run” mode (screenshots-first)

Add a convention where some specs are tagged as audit-focused:

- Run subset (fast): core assertions only
- Run audit (slower): assertions + screenshots for every state (plus any best-effort extra artifacts)

Status (2026-03-06): ✅ implemented

- Audit-focused specs are tagged with `@audit` in the test title.
- Audit mode writes stable artifacts to `tools/workbench-web/out/audit/` and generates a checklist.

Audit commands:

- Full suite + audit artifacts: `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test --reporter=line,html`
- Audit subset only: `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test -g "@audit" --reporter=line,html`

Outputs:

- Checklist: `tools/workbench-web/out/audit/audit-findings.md`
- Artifacts: `tools/workbench-web/out/audit/audit_*.png` (+ optional `audit_*.a11y.*`)

Conceptually, audit mode should:

- capture screenshots even when tests pass
- surface a findings checklist at the end (even if it’s just a markdown template filled with links to artifacts)

---

## Using Playwright MCP (optional, but powerful)

Playwright MCP can complement the test suite by enabling a semi-autonomous exploratory pass:

- drive the UI through the state matrix
- take screenshots
- record console/network anomalies
- propose new deterministic Playwright assertions/specs when it finds a repeatable issue

Constraint: the MCP pass should generate candidate findings; anything it reports should be converted into a deterministic Playwright spec + assertion for long-term regression coverage.

---

## Triage process (how the harness turns into real improvements)

For each captured state, triage in three buckets:

- Bug: broken behavior, missing feedback, data loss risk
- UX workflow inefficiency: extra steps, unclear semantics, confusing state labels
- UI/layout: overlap, contrast, spacing, alignment, inconsistent affordances

Each finding should include:

- State name (from the matrix)
- Screenshot link (artifact)
- Repro steps (should map to the test)
- Proposed fix (smallest change)
- How we’ll assert it (new/updated Playwright expectation)

---

## Acceptance criteria for the harness (when we implement it)

This is now implemented; the acceptance criteria evolve into “keep it reliable while we add more states.”

- One command runs a deterministic audit: `cd tools/workbench-web && npx playwright test --reporter=line`
- Audit mode captures screenshots for key states even on success: `E2E_AUDIT=1`
- Failures include attached console + network summaries
- Suite resets state between specs (no cross-test bleed)

---

## Fix backlog (from audit artifacts)

This is the actionable list of UI/UX issues discovered via the audit harness. Each item includes what to fix and how to verify it stays fixed.

### P0 — Preview mode layout overlap

Symptom:
- In preview mode (version pill preview), the system “Previewing: vN …” bar/overlay visually overlaps the top header/controls area.

Why it matters:
- Obscures controls and makes the preview state feel broken/unclear.

Proposed fix (smallest change first):
- Ensure the preview/version bar is in normal document flow above the textarea (not overlaid on top of the header row).
- Confirm z-index layering matches intent: the preview bar close button remains clickable, and the diff overlay does not block the header.

Status: ✅ fixed

Verification:
- Playwright regression asserts overlay starts below version bar.
- E2E audit screenshot `audit_preview_mode_visible.png` shows no overlap.

### P1 — Compare modal destructive action clarity

Symptom:
- “Delete version” affordance can be confusing when no saved versions exist, or when selection state is unclear.

Status: ✅ fixed

Fix:
- Compare modal `Delete version` is disabled until a saved version is selected/rendered; selection resets on open/close.

Verification:
- Playwright asserts enabled/disabled behavior in compare modal.

### P2 — Diff overlay pointer/interactions

Symptom:
- Diff overlay and/or preview UI could unintentionally intercept clicks meant for primary controls.

Status: ✅ fixed (guarded by regression checks)

Fix:
- Ensure the diff overlay does not block primary controls outside the overlay region.

Verification:
- Playwright preview-mode spec opens the compare modal while the overlay is visible.

---

### P0 — WIP overlay blocks primary “click prompt to edit” affordance

Symptom:
- When default WIP highlighting is visible (sys diff overlay shown on top of the textarea), the overlay can intercept clicks.
- This makes “click prompt to edit” unreliable, even though the UI hint says “click prompt or AI Edit”.

Why it matters:
- It makes the editor feel broken/unresponsive and forces users to hunt for the button.

Proposed fix:
- Ensure the default WIP overlay does not block the textarea’s primary interaction.
- Implementation options (pick smallest that preserves intended interactivity):
  - Make default WIP overlay `pointer-events: none` (recommended if overlay is purely decorative), OR
  - Forward overlay clicks to the same handler as the textarea (open the AI modal), while preserving selection/scroll.

Verification:
- Add/keep a regression check: with drafts present and default WIP highlighting visible, clicking in the prompt surface opens the AI modal.
- Audit screenshots to review: `audit_pill_scroll_*_bottom.png` (deep-scrolled state).

---

### P0 — Async highlight render can race when switching pills quickly

Symptom:
- Clicking v3 → v2 → v1 quickly can produce laggy or incorrect overlay state if snapshot fetch + highlight render completes out of order.

Why it matters:
- Users lose trust: the active pill may not match the visible attribution/highlight.

Proposed fix:
- Add a render generation token (or abort controller) so only the most recent highlight request can update the overlay.
- Discard stale async completions.

Verification:
- Add a Playwright “rapid pill switching” regression:
  - Rapidly click several pills and assert the final visible state (active pill + preview/liveness + overlay classes) matches the last click.

---

### P0 — Preview overlay shows red deletions + “duplicate” lines for some versions (v2)

Symptom:
- When previewing certain pills (observed: v2), the overlay includes deletion ops styled as `dl-del` (red).
- When a line is modified, the overlay can show both the old (deleted) line and the new (added) line, which reads like duplicated text in the system prompt.
- This also breaks the “preview should match pill hue” expectation (v2 preview should feel amber; red text is misleading).

Root cause:
- Preview mode overlay is currently rendered from a base→snapshot line diff that includes `del` ops.
- Those `del` ops do not exist in the previewed snapshot text, so showing them in an overlay that sits on top of the textarea both:
  - introduces visually duplicated content, and
  - risks scroll/line alignment confusion.

Proposed fix:
- In preview-mode overlay rendering, do not render deletion ops as visible lines.
  - Minimum change: treat `del` ops as “skip” (omit) so only context + additions are shown.
  - Optional follow-up: if we need deletion visibility, show it only in the compare modal (where side-by-side makes sense), not on top of the textarea.
- Ensure preview-mode overlay uses only hue-styled additions (`dl-add-hue-{n}`) and neutral context (`dl-ctx`) so the visual language matches the active pill.

Verification:
- Add/extend a Playwright regression that previews v2 and asserts:
  - No `dl-del` spans are present in the sys overlay while previewing.
  - Overlay line count stays aligned with the preview textarea content (no “extra” deletion-only lines).
- Audit screenshots to review: `audit_pill_scroll_preview_v2_bottom.png`.

---

### P1 — Switching WIP pills while deep-scrolled is disorienting

Symptom:
- If the user scrolls far down and switches pills, scrollTop stays the same but the underlying content changes.
- This can feel like the viewport “teleports” to unrelated content, or appears to not change at all if edits are elsewhere.

Why it matters:
- This is a high-frequency workflow when reviewing changes across multiple WIP versions.

Proposed fix (choose one explicitly):
- Option A (simplest): reset scroll to top on any pill switch (preview enter/exit and WIP switches).
- Option B (more advanced): preserve scroll only when the target text is comparable; otherwise clamp scroll and show a subtle “jumped” hint.

Verification:
- Add audit screenshots for:
  - latest WIP bottom,
  - preview v2 bottom,
  - back to latest WIP bottom,
  and confirm the behavior is consistent with the chosen option.

---

### P1 — Default WIP highlighting mode lacks a clear state label

Symptom:
- Preview mode has a visible “Previewing: …” version bar.
- Default WIP highlighting has no equivalent indicator, so users can’t easily tell whether they’re in preview or just seeing latest-WIP attribution.

Why it matters:
- Contributes to confusion when switching pills and while deep-scrolled.

Proposed fix:
- Add a lightweight, clearly non-preview indicator for default WIP highlighting (e.g. “WIP highlighted (latest)” in the label row).
- Must not look like preview mode (no “close to exit preview” semantics unless explicitly added).

Verification:
- Add a Playwright assertion: with drafts present and not previewing, the WIP indicator is visible; when previewing, the preview bar is visible instead.

---

### P2 — Highlight readability: large added blocks become noisy

Symptom:
- When the overlay highlights many contiguous lines, it becomes zebra-striped, which is hard to scan.

Why it matters:
- The feature meant to improve review can reduce readability.

Proposed fix:
- Reduce highlight visual weight:
  - prefer a left gutter marker, thin border, or block-level grouping instead of full-row fills.

Verification:
- Audit screenshot of a long added block remains readable (no high-contrast striping dominating the text).

---

## Next steps

State-matrix expansion is now implemented (2026-03-06):

- Multi-draft hue cycling + preview-bar hue consistency: `tools/workbench-web/e2e/specs/07_multi_draft_hues.spec.js`
- Mode switching (history pills filter by mode): `tools/workbench-web/e2e/specs/08_mode_switching_pills.spec.js`
- Publish eligibility (disabled until a clean suite run): `tools/workbench-web/e2e/specs/09_publish_eligibility.spec.js`

Keep running audit passes:
- `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test --reporter=line,html`

---

## Archive (shipped work)

This file previously contained a detailed issue-by-issue implementation plan that was fully shipped on 2026-03-06 (with 6/6 Playwright tests passing at the time). It was removed to keep this document forward-looking and to avoid mixing completed implementation notes with the next-phase audit harness plan.
