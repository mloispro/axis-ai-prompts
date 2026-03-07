---
description: "Use when: fixing UI issues, finding UI quirks, UI/UX improvements, or working in tools/workbench-web. Establishes the deterministic Playwright audit loop and artifact review workflow."
applyTo: "tools/workbench-web/**"
---

# Workbench UI audit loop (deterministic)

## Golden path (always follow)

1) **Run the workbench**
- Prefer VS Code task: `Workbench: Start`
- Default URL: `http://127.0.0.1:7540/`

2) **Generate audit artifacts (screenshots even on success)**
- `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test --reporter=line,html`

Optional: run only the audit-focused subset (faster to review screenshots):
- `cd tools/workbench-web && E2E_AUDIT=1 npx playwright test -g "@audit" --reporter=line,html`

3) **Inspect what the UI looks like**
- Report UI: `cd tools/workbench-web && npx playwright show-report playwright-report`
- Raw screenshots: `tools/workbench-web/playwright-report/data/*.png`

Stable audit outputs (recommended for quick review + sharing paths):
- Checklist: `tools/workbench-web/out/audit/audit-findings.md`
- Artifacts: `tools/workbench-web/out/audit/audit_*.png` and `tools/workbench-web/out/audit/audit_*.a11y.*`

Notes:
- The `data/*.png` files are content-addressed; use the report UI to map *which* PNG corresponds to which test/state.
- Prefer the simplest inspection path:
	- open screenshots from the VS Code file explorer, or
	- open the Playwright report UI and click into the attachment.
- Avoid relying on internal/experimental chat tool IDs in docs; available tool names can differ across VS Code/Copilot builds.

4) **Turn a quirk into a durable fix**
- Make the smallest CSS/JS/HTML change that addresses the root cause.
- Add or tighten a Playwright assertion + named screenshot in the spec covering that state.
- Re-run the same audit command and confirm the state is fixed.

Rubric for consistent review:
- `tools/workbench-web/UX_AUDIT_RUBRIC.md`

Ownership note (this repo): there are no separate human reviewers; GitHub Copilot is expected to run this audit loop and apply fixes.

## Guardrails

- Public repo: never add secrets/PII; keys must stay in environment vars only.
- After editing `tools/workbench-web/static/**` or `tools/workbench-web/server.py`: rerun E2E.
- Keep diffs minimal; do not add new UI features when addressing a quirk.

## When MCP is useful

- Use Playwright MCP only for exploratory repro.
- Any finding must be converted into a deterministic E2E state + screenshot + assertion.
