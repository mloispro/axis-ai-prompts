# Workbench Web — UX Audit Rubric

This rubric is designed to be used with the Playwright audit harness screenshots so purely-visual UX regressions (readability/layout drift, confusing workflows, missing affordances, broken states) are caught consistently.

## Ownership (this repo)

There are no human reviewers for this workbench.

- The "reviewer" is GitHub Copilot (the coding agent).
- For any UI/UX change request, Copilot should run the audit, review the screenshots using this rubric, apply fixes, and re-run the audit to verify.

Use it with:

```bash
cd tools/workbench-web && E2E_AUDIT=1 npx playwright test -g "@audit" --reporter=line,html
```

Then review:
- Checklist: `tools/workbench-web/out/audit/audit-findings.md`
- Screenshots: `tools/workbench-web/out/audit/audit_*.png`

## How to review (fast)

For each checklist item / screenshot state:
- Spend **30–90 seconds**.
- If anything fails the rubric below, mark the item as **Bug**, **UI/layout**, or **UX workflow inefficiency** and jot 1–2 lines of what’s wrong and what “good” looks like.

## Scoring rule (simple)

Pass a state only if all are true:
- **Readable**: no clipped/truncated key text; no “mystery meat” controls; no critical instruction hidden.
- **Operable**: primary next action is visible and looks clickable; disabled/enabled states make sense.
- **Explained**: status/error text is visible and near the action that caused it.

## Rubric checks

### A) Readability / layout
Check these visually:
- **Hierarchy**: primary action stands out; secondary actions don’t compete.
- **Alignment**: labels, inputs, and buttons line up; no “off by a few px” rows.
- **Density**: no cramped clusters; spacing feels intentional.
- **Truncation**: no clipped headings, pill labels, button text, status/error messages.
- **Wrapping**: long content wraps without breaking layout (esp. diff panes, prompts).
- **Placeholder dependence**: placeholders should not be the only way users learn what an input is.

### B) Workflow optimization
Ask “what do I do next?”
- **Obvious next step**: in this state, a user can predict the next click.
- **Unnecessary steps**: avoid repeated modal open/close, redundant toggles, or required scrolling for status.
- **Feedback latency**: UI clearly shows progress (Working/Done/Failed) without ambiguity.
- **State persistence**: after actions (apply/delete/reset), UI returns to a sensible stable state.

### C) UI/UX enhancements & fixes
Focus on state correctness:
- **Disabled/enabled**: buttons enabled only when safe; disabled buttons have an obvious reason.
- **Error placement**: errors are visible, not off-screen, and not only in console.
- **Overlays**: bars/overlays do not hide controls; close buttons are clickable.
- **Modal usability**: modal content is readable, scrollable, and not clipped.
- **Responsive**: narrow layout still supports the key path without overlap.

## State-specific prompts (mapped to existing screenshots)

Use these prompts when scanning each state.

### `fresh_load`
- Can you identify the main editor areas and the “run” area immediately?
- Are all section headers readable and not crowded?

### `ai_editor_ready` / `ai_editor_after_propose` / `after_apply_creates_version`
- Is the “make a change then run/apply” flow obvious?
- Are diff + apply/discard controls visible without scrolling?
- Is status text readable and close to the interaction?

### `compare_modal_open` / `compare_modal_open_before_delete`
- Both panes visible and readable?
- No clipped text; delete/reset actions clearly separated from compare navigation.

### `before_preview_click` / `preview_mode_visible` / `preview_mode_dismissed`
- Preview bar visibly indicates mode and has a clear exit control.
- Diff overlay doesn’t hide essential controls; close remains clickable.

### `mode_*_pills`
- Version pills are clearly scoped to the selected mode.
- Pill labels are readable; no overlap/wrapping disasters.

### `multi_draft_hue_cycle_ready` / `multi_draft_preview_hue_matches`
- Hue meaning is consistent; no hue reads as “error/deleted”.
- Active/selected state is obvious.

### `responsive_wide` / `responsive_narrow`
- Wide: layout uses space well; no awkward dead zones.
- Narrow: key controls remain accessible; no overlapping panels; no hidden “critical” actions.

### `publish_disabled_before_suite` / `suite_done_before_publish` / `publish_enabled_after_clean_suite`
- Publish eligibility is understandable from the UI state (not requiring reading logs).
- Disabled publish looks intentionally disabled (not broken).

## Promotion rule (turn findings into automation)

When a finding is:
- high impact,
- objective enough to encode (visibility, enabled/disabled, dimensions, “in viewport”), and
- likely to regress,

…promote it into an E2E assertion in the relevant `@audit` spec.

This keeps screenshots for broad fuzziness, while assertions prevent repeats.
