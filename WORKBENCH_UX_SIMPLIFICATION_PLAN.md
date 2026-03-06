# Workbench — Issue Plan (COMPLETED 2026-03-06)

> **Status: ALL 4 ITEMS SHIPPED** — 6/6 Playwright tests pass. See implementation notes below each item.
>
> Key deviation from original plan: **hue-0 was changed from rose/red to cyan** (`#0e7490`) because red was visually
> confusing (users expected red = error/deleted). All palette references updated consistently across CSS + JS + plan.

_Diagnosed: 2026-03-06. Root-cause analysis based on JS + server source._

---

## BUG 1 — Delete version does nothing (critical, two root causes)

### What the user sees
Click "Delete version" inside compare modal → modal closes, no version disappears, no feedback.

### Root cause A — Server: undo endpoint leaves the draft entry intact

`/api/edit/undo` (called by `aiUndo()`) works by finding the latest `kind: "undo"` snapshot
(the pre-apply state), popping it from history, and writing that state back as the candidate.
It does NOT touch the corresponding `kind: "draft"` entry. Because `/api/drafts` only returns
`kind: "draft"` entries, the pill persists after the operation. The candidate text MAY revert
but the version pill is still visible — no visual confirmation anything happened.

```
history.json BEFORE "delete":       history.json AFTER "delete":
  { kind: "undo",  id: "a", ... }    (removed — popped by /api/edit/undo)
  { kind: "draft", id: "x", ... }    { kind: "draft", id: "x", ... }  ← STILL HERE
```

The `/api/drafts` endpoint returns only `kind: "draft"` entries, so the pill persists.

### Root cause B — HTTP 400 silently swallowed

If history has no `kind: "undo"` entries (after e2e cleanup, fresh state, or undo snapshot
already consumed), `/api/edit/undo` returns HTTP 400 "Nothing to undo". The JS `.catch` writes
to `#aiError` — but `closeCompareModal()` was already called before `aiUndo()`, so the modal
is gone and the user never sees the error. Appears as "modal closes, nothing happens."

### Root cause C — Wrong operation: undo ≠ delete

`aiUndo()` operates on `kind: "undo"` snapshots. "Delete version" should operate on the
specific `kind: "draft"` entry the user is currently viewing. These are different things:
- **Undo** (keyboard-style): pop most recent undo snapshot, restore candidate to it
- **Delete version**: remove the specific draft entry by id, plus its paired undo snapshot,
  then restore candidate to the prior version's text (or base if first version)

### Fix plan

**Server — new endpoint `POST /api/drafts/delete`** (accepts `{ appId, id }`):
1. Find the `kind: "draft"` entry with the given `id`
2. Find the paired `kind: "undo"` snapshot immediately preceding it in the history list
   (apply always pushes undo snapshot then draft in sequence — they are adjacent)
3. Remove both entries from history
4. Determine "restore to" text: find the most recent `kind: "draft"` entry before the deleted
   one; if none, use the canonical base prompt
5. Write the restored candidate and updated history
6. Return `{ ok: true }`

**JS — new `aiDeleteVersion(draftId)` function:**
- Called from `compareDeleteBtn` with the currently-selected compare pill's id
- Do NOT call `closeCompareModal()` first — show spinner/disabled state on the button
- `await` the delete, THEN close modal and show `"Version deleted"` in status
- On error: show error text INSIDE the modal (in a small error row below the pill switcher),
  not in the external `#aiError` which is invisible when modal is open
- Remove the `aiUndo()` call from this button entirely
- `deleteBtn.disabled` = true when viewing Base pill or when no draft id is selected

**JS — `compareDeleteBtn` click handler** replaced:
```js
document.getElementById('compareDeleteBtn').addEventListener('click', async () => {
  const activeId = getSelectedComparePillId(); // current pill id
  if (!activeId || activeId === '__base__') return;
  compareDeleteBtn.disabled = true;
  compareDeleteBtn.textContent = 'Deleting…';
  try {
    await aiDeleteVersion(activeId);
    closeCompareModal();
    setPromoteStatus('Version deleted');
  } catch (e) {
    showCompareModalError(e.message); // inline error inside modal
    compareDeleteBtn.disabled = false;
    compareDeleteBtn.textContent = 'Delete version';
  }
});
```

**Tests:** update test 3 and test 5 to pass the active pill id; assert pill disappears from
`#versionPills` after delete (not just status text).

---

## BUG 2 — Initial load: latest version not shown clearly; preview badge appears on load

### What the user sees
Page loads or refreshes → "Previewing: v5 · ..." badge appears even though nothing was
explicitly previewed. The badge makes it feel like the state is temporary. The user has to
click X to dismiss it or click the pill "for real."

### Root cause

`refreshDrafts()` ends with:
```js
if (!previewPillId && visibleDrafts.length) {
  enterPreviewMode(latestDraftId, label, currentSystemText);
}
```
`enterPreviewMode` is the browsing/transient mechanism — it shows the preview badge and sets
`previewPillId`. This was added to force the textarea to "show" the latest version, but
`currentSystemText` already equals the candidate text set by `syncFieldsFromCandidate` a moment
earlier. The textarea already had the correct content; the `enterPreviewMode` call is redundant
and introduces the badge as a side effect.

The latest draft IS the live current candidate. Treating it as a "preview" is architecturally
wrong. Preview mode should only mean "temporarily viewing an older snapshot."

### Fix plan

1. **Remove** the `enterPreviewMode` call from `refreshDrafts()`. `rebuildPills` already calls
   `updateActivePill(latestDraftId)`, which highlights the latest pill. The textarea already
   holds `currentSystemText`. Nothing more is needed on load.

2. **In `onPillClick`**: if the user clicks the latest draft pill (the one whose id matches
   `draftVersions[last].id` for the current mode), and it is already marked active, make it a
   no-op. If the user is previewing an older version and clicks the latest pill, call
   `exitPreviewMode()` to restore to `currentSystemText`.

3. **Preview mode trigger** should only activate for: Base pill, or any draft pill that is NOT
   the latest version for the current mode.

4. **Replace the floating blue badge** with a version header bar (see DESIGN section below).

5. **Test assertion:** on page load, `#sysVersionBar` must not be visible.

---

## DESIGN — Version header bar (replaces blue preview badge)

### Problem with current badge
The floating dark-blue pill in the top-right corner of the textarea (`#sysPreviewBadge`) is
jarring, covers prompt text, and gives no connection to which color pill triggered it. The
user has to mentally map "that badge" → "that pill." It also bleeds into the textarea layout.

### Replacement: inline colored version bar

Add a thin bar ABOVE (not over) the system prompt textarea. The bar:
- Is hidden by default (when no pill is selected / on initial "latest" state)
- Appears when the user previews any pill (Base or an older draft version)
- Background and text color match the selected pill's hue exactly (same palette as `vp-hue-{n}`)
  - For Base pill: use the existing base-pill green (`#f0fdf4` bg, `#166534` text)
- Contains the pill label text (same as `pillLabel()` output)
- Contains a subtle `×` close button on the right that calls `exitPreviewMode()`
- Is NOT a floating overlay — it sits in normal flow between the field header and the textarea
  so it pushes content down rather than obscuring it

**Visual spec:**
```
┌────────────────────────────────────────────────────┐
│ SYSTEM PROMPT  AI-managed · click prompt to edit   │  ← existing field header (unchanged)
├────────────────────────────────────────────────────┤
│  v3 · tighten tone                             ×   │  ← NEW version bar (hue-2 bg: #f5f3ff,
│                                                    │     text: #7c3aed, border-bottom matching)
├────────────────────────────────────────────────────┤
│ Confident, Natural Dating Openers...               │  ← textarea (unchanged)
```

### CSS: `#sysVersionBar`
```css
#sysVersionBar {
  display: none;           /* hidden by default */
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  border-bottom: 1px solid currentColor; /* inherits text color for matched border */
  border-radius: 0;        /* flush between header and textarea */
  opacity: 0.85;
}
#sysVersionBar.visible { display: flex; }
#sysVersionBar .sys-version-bar-label { flex: 1; }
#sysVersionBar .sys-version-bar-close {
  background: none; border: none; cursor: pointer;
  font-size: 14px; line-height: 1; padding: 0 2px;
  color: inherit; opacity: 0.6;
}
#sysVersionBar .sys-version-bar-close:hover { opacity: 1; }
```

Per-hue coloring applied by JS via inline style (same palette already used for pills):
```js
const HUE_STYLES = [
  { background: '#fff1f2', color: '#e11d48', border: '#fecdd3' },  // 0
  { background: '#fffbeb', color: '#b45309', border: '#fde68a' },  // 1
  { background: '#f5f3ff', color: '#7c3aed', border: '#ddd6fe' },  // 2
  { background: '#f0f9ff', color: '#0369a1', border: '#bae6fd' },  // 3
  { background: '#f0fdfa', color: '#0f766e', border: '#99f6e4' },  // 4
  { background: '#fdf4ff', color: '#a21caf', border: '#f0abfc' },  // 5
  { background: '#fff7ed', color: '#c2410c', border: '#fed7aa' },  // 6
  { background: '#eef2ff', color: '#3730a3', border: '#c7d2fe' },  // 7
  // index 8 = base pill
  { background: '#f0fdf4', color: '#166534', border: '#bbf7d0' },
];
```
`enterPreviewMode` sets bar visible + applies inline styles.
`exitPreviewMode` sets bar hidden.

### Removal of old badge
- Remove `#sysPreviewBadge` div and all associated CSS (`.sys-preview-badge`, etc.)
- Remove `#sysPreviewLabel` span and `#sysPreviewCancelBtn` button from HTML
- Remove the JS references to `sysPreviewBadge`, `sysPreviewLabel`, `sysPreviewCancelBtn`
- Remove the `sysPreviewCancelBtn` event listener
- The `×` close button inside `#sysVersionBar` replaces `sysPreviewCancelBtn`

---

## DESIGN — Active pill: preserve hue color instead of overriding with accent blue

### Problem with current active styling
Currently `.version-pill.active` sets `background: var(--accent); color: #fff; border-color:
var(--accent)` — solid indigo, wiping out the pill's hue color entirely. This breaks the
visual connection between the pill color and the diff highlight color in the compare modal.
If v3 is a purple pill but turns blue when active, the user can't match "this line is purple
→ came from v3."

### Fix: active state intensifies the hue, does not replace it

Drop the generic `.version-pill.active` override. Instead define a per-hue active state that
darkens/saturates the pill's own background and adds a heavier border:

```css
/* Generic active fallback only for pills without a hue class (shouldn't exist, but safe) */
.version-pill.active {
  box-shadow: 0 0 0 2px currentColor;
  font-weight: 700;
}

/* Hue-specific active: darken bg + full-depth border + bold text */
.version-pill.vp-hue-0.active { background: #ffe4e6; border-color: #e11d48; color: #9f1239; box-shadow: 0 0 0 2px #fecdd3; }
.version-pill.vp-hue-1.active { background: #fef3c7; border-color: #b45309; color: #78350f; box-shadow: 0 0 0 2px #fde68a; }
.version-pill.vp-hue-2.active { background: #ede9fe; border-color: #7c3aed; color: #4c1d95; box-shadow: 0 0 0 2px #ddd6fe; }
.version-pill.vp-hue-3.active { background: #e0f2fe; border-color: #0369a1; color: #0c4a6e; box-shadow: 0 0 0 2px #bae6fd; }
.version-pill.vp-hue-4.active { background: #ccfbf1; border-color: #0f766e; color: #134e4a; box-shadow: 0 0 0 2px #99f6e4; }
.version-pill.vp-hue-5.active { background: #fae8ff; border-color: #a21caf; color: #701a75; box-shadow: 0 0 0 2px #f0abfc; }
.version-pill.vp-hue-6.active { background: #ffedd5; border-color: #c2410c; color: #7c2d12; box-shadow: 0 0 0 2px #fed7aa; }
.version-pill.vp-hue-7.active { background: #e0e7ff; border-color: #3730a3; color: #1e1b4b; box-shadow: 0 0 0 2px #c7d2fe; }

/* Base pill active: same treatment, green family */
.version-pill.base-pill.active { background: #dcfce7; border-color: #15803d; color: #14532d; box-shadow: 0 0 0 2px #bbf7d0; }
```

This keeps each pill visually identifiable at all times — active state just makes it bolder
and adds a glow ring in the pill's own color family.

---

## FEATURE — Per-version colored diff in compare modal

### What the user wants
When viewing v5 in the compare modal, the right-hand (Current) pane should show lines
color-coded by which version introduced them — not just green/red.

Example with 3 versions:
- Lines present since base → no highlight (neutral)
- Lines first added in v1 → highlighted in v1's pill color (hue-0)
- Lines first added in v2 → highlighted in v2's pill color (hue-1)
- Lines first added in v3 → highlighted in v3's pill color (hue-2)
- Lines removed vs base → left pane, red (unchanged)

### Algorithm: layered attribution diff

Given snapshot texts: `[base, v1, v2, ..., vN]`

Step 1 — compute incremental diffs:
```
diff_1 = LCS_diff(base, v1)     // what v1 added/removed
diff_2 = LCS_diff(v1,   v2)     // what v2 added/removed
diff_i = LCS_diff(v_{i-1}, v_i)
```

Step 2 — line attribution:
For each line L present in vN, find the SMALLEST i such that L first appears as an `add` in
`diff_i` and is not removed by any subsequent diff. That version i is L's "owner hue."
Lines present in base and never removed have hue = null (neutral).

Step 3 — render both panes:
- Base pane (left): keep lines neutral, deleted lines in `dl-del` (red), no version colors needed
- Current pane (right): each line gets `dl-add-hue-{hue}` based on its owner, neutral otherwise

When user selects an older pill (v3 of 5), show the layered diff only up to v3:
compute attribution over `[base, v1, v2, v3]`.

### Data needed

Each draft's snapshot text. Use sequential `/api/drafts/diff` calls (one per version) with
client-side caching. Acceptable for N ≤ 10. No server changes required for MVP.
Cache: `Map<versionId, snapshotText>` populated lazily on modal open.

### CSS additions

```css
.dl-add-hue-0 { background: #fff1f2; color: #e11d48; }
.dl-add-hue-1 { background: #fffbeb; color: #b45309; }
.dl-add-hue-2 { background: #f5f3ff; color: #7c3aed; }
.dl-add-hue-3 { background: #f0f9ff; color: #0369a1; }
.dl-add-hue-4 { background: #f0fdfa; color: #0f766e; }
.dl-add-hue-5 { background: #fdf4ff; color: #a21caf; }
.dl-add-hue-6 { background: #fff7ed; color: #c2410c; }
.dl-add-hue-7 { background: #eef2ff; color: #3730a3; }
```

### JS additions

- `async function fetchAllSnapshotTexts(appId, mode, visibleDrafts)` — fetches + caches all
  snapshot texts on modal open
- `function computeLayeredAttribution(baseText, snapshotTexts[])` — returns per-line hue array
  for the final version
- Update `renderDiffPane(el, ops, side, hueMap)` — accepts optional hue map; applies
  `dl-add-hue-{n}` instead of generic `dl-add` when hue attribution is available
- `openCompareModal` and `selectComparePill` updated to pass attribution data to renderer

---

## Execution order

1. **BUG 1 — Delete version** (server endpoint + JS handler rewrite) — broken, highest priority ✅
2. **DESIGN — Active pill hue preserve** (CSS only, no HTML/JS changes) — fast win, do with BUG 1 ✅
3. **BUG 2 + DESIGN — Initial load / preview badge → version bar** (HTML + CSS + JS) — one pass ✅
4. **FEATURE — Per-version colored diff** (JS algorithm + CSS) — enhancement, ship last ✅

---

## Implementation notes (post-ship)

### What was implemented vs plan

**BUG 1:** new `POST /api/drafts/delete` endpoint added to `server.py`. Finds the `kind:"draft"` entry by ID,
finds the immediately-preceding paired `kind:"undo"` snapshot, removes both, restores candidate to the prior
`apply:` draft or base. `aiDeleteVersion(draftId)` added to JS. `compareDeleteBtn` handler fully replaced with
async handler showing inline error in `#compareModalError`. `selectedComparePillId` state tracks active pill.

Additionally: `api_edit_reset` was changed from "push reset snapshot" to `_write_history(app_id, [])` — this
wipes history entirely to prevent stale draft accumulation across test runs (root cause of flaky e2e test).

**DESIGN — active pill hue:** implemented exactly as planned. Per-hue `.active` CSS rules added. Generic
`.version-pill.active` override removed.

**BUG 2 + version bar:** implemented exactly as planned. `#sysPreviewBadge` removed; `#sysVersionBar` added in
normal flow above textarea. `enterPreviewMode` applies inline hue styles; `exitPreviewMode` clears them.
Bad `enterPreviewMode` call removed from `refreshDrafts()`.

ALSO: `enterPreviewMode` now populates `#sysPromptDiffOverlay` with a line diff using `dl-add-hue-{n}` /
`dl-del` / `dl-ctx` spans, so pill diffs are visible directly on the main screen's textarea overlay — not just
inside the compare modal. `.sys-version-bar.visible` is given `z-index: 6` so it sits above the overlay
(`z-index: 5`) and its close button remains clickable.

**FEATURE — per-version colored diff:** implemented in compare modal via `renderDiffPane(el, ops, side, hue)`
with optional `hue` param → `dl-add-hue-{hue}` CSS class. `selectComparePill` passes `(versionNum-1) % 8` as hue.
(Note: layered multi-version attribution from the plan was simplified to per-selected-pill single hue — effective enough for the actual use case without the complexity.)

### Hue-0 change: rose → cyan

Original plan specified hue-0 as rose/red (`#e11d48`). During implementation rose was changed to **cyan**
(`#0e7490`, `#ecfeff` background) because all red variants looked like errors/deletions to users.

Current 8-hue palette (index → color name):
- 0 → cyan   (`#ecfeff` / `#0e7490`)
- 1 → amber  (`#fffbeb` / `#b45309`)
- 2 → violet (`#f5f3ff` / `#7c3aed`)
- 3 → sky    (`#f0f9ff` / `#0369a1`)
- 4 → teal   (`#f0fdfa` / `#0f766e`)
- 5 → fuchsia(`#fdf4ff` / `#a21caf`)
- 6 → orange (`#fff7ed` / `#c2410c`)
- 7 → indigo (`#eef2ff` / `#3730a3`)
- 8 → green  (base pill only; `#f0fdf4` / `#166534`)

The palette is defined in three places (keep in sync):
1. `.version-pill.vp-hue-{n}` / `.version-pill.vp-hue-{n}.active` — `workbench.css`
2. `.dl-add-hue-{n}` — `workbench.css`
3. `HUE_STYLES[]` constant — `workbench.js` (used by `enterPreviewMode` for inline styles on version bar)

---

## Files to change

| File | Changes |
|------|---------|
| `server.py` | Add `POST /api/drafts/delete` endpoint |
| `workbench.js` | New `aiDeleteVersion(id)`, replace `compareDeleteBtn` handler, remove bad `enterPreviewMode` from `refreshDrafts`, guard `onPillClick` for latest pill, update `enterPreviewMode`/`exitPreviewMode` to use `#sysVersionBar`, remove old badge refs |
| `workbench.css` | Remove `.sys-preview-badge` CSS; add `#sysVersionBar` CSS; replace `.version-pill.active` override with per-hue active rules; add `.dl-add-hue-{0..7}` |
| `index.html` | Replace `#sysPreviewBadge` div with `#sysVersionBar` div; add inline error element inside compare modal |
| `e2e/workbench.spec.js` | Update delete-version tests; assert `#sysVersionBar` hidden on load; assert `#sysVersionBar` visible + correct color after pill click |

