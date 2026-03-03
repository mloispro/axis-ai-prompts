"""
One-shot componentizer for workbench static files.
Run this to split the monolithic index.html into:
  static/css/workbench.css
  static/js/workbench.js
  static/index.html  (new playground layout)

Safe to re-run; creates/overwrites the three output files.
"""

import re, os, textwrap

ROOT = os.path.join(os.path.dirname(__file__), "static")
SRC = os.path.join(ROOT, "index.html")

with open(SRC, encoding="utf-8") as f:
    src = f.read()

# ── 1. Extract CSS ──────────────────────────────────────────────────────────
css_m = re.search(r"<style>(.*?)</style>", src, re.DOTALL)
assert css_m, "Could not find <style> block"
css_body = css_m.group(1)

# ── 2. Extract JS ───────────────────────────────────────────────────────────
js_m = re.search(r"<script>(.*?)</script>", src, re.DOTALL)
assert js_m, "Could not find <script> block"
js_body = js_m.group(1)

# ── 3. Patch JS ─────────────────────────────────────────────────────────────

# 3a. clearAiProposal — hide diff wrap, use innerHTML for diff el
OLD_CLEAR = """\
    function clearAiProposal() {
      aiLastProposal = null;
      document.getElementById('aiDiff').textContent = '';
      document.getElementById('aiNotes').textContent = '';
      document.getElementById('aiError').textContent = '';
      document.getElementById('aiApplyBtn').disabled = true;
    }"""
NEW_CLEAR = """\
    function clearAiProposal() {
      aiLastProposal = null;
      const diffEl = document.getElementById('aiDiff');
      if (diffEl) diffEl.innerHTML = '';
      const wrapEl = document.getElementById('aiDiffWrap');
      if (wrapEl) wrapEl.style.display = 'none';
      document.getElementById('aiError').textContent = '';
      document.getElementById('aiApplyBtn').disabled = true;
    }"""
assert OLD_CLEAR in js_body, "clearAiProposal pattern not found"
js_body = js_body.replace(OLD_CLEAR, NEW_CLEAR, 1)

# 3b. aiPropose — use renderColoredDiff + show diffWrap
OLD_PROPOSE_DIFF = """\
      document.getElementById('aiDiff').textContent = res.diff || '';
      document.getElementById('aiNotes').textContent = aiNotesFromProposal(proposal);"""
NEW_PROPOSE_DIFF = """\
      renderColoredDiff(res.diff || '', document.getElementById('aiDiff'));
      document.getElementById('aiDiffWrap').style.display = '';
      const _notesEl = document.getElementById('aiNotes');
      if (_notesEl) _notesEl.textContent = aiNotesFromProposal(proposal);"""
assert OLD_PROPOSE_DIFF in js_body, "aiPropose diff lines not found"
js_body = js_body.replace(OLD_PROPOSE_DIFF, NEW_PROPOSE_DIFF, 1)

# 3c. onDraftSelected — route to aiDiffAdv / aiNotesAdv
OLD_DRAFT_CLEAR = """\
      document.getElementById('aiDiff').textContent = '';
        document.getElementById('aiNotes').textContent = 'No edit snapshot selected.';"""
NEW_DRAFT_CLEAR = """\
      document.getElementById('aiDiffAdv').textContent = '';
        document.getElementById('aiNotesAdv').textContent = 'No edit snapshot selected.';"""

# Try exact, then normalised whitespace version
if OLD_DRAFT_CLEAR in js_body:
    js_body = js_body.replace(OLD_DRAFT_CLEAR, NEW_DRAFT_CLEAR, 1)
else:
    # Looser: find the two-line block inside the if (!id) guard
    js_body = js_body.replace(
        "document.getElementById('aiDiff').textContent = '';\n        document.getElementById('aiNotes').textContent = 'No edit snapshot selected.';",
        "document.getElementById('aiDiffAdv').textContent = '';\n        document.getElementById('aiNotesAdv').textContent = 'No edit snapshot selected.';",
        1,
    )

OLD_DRAFT_DIFF = "        document.getElementById('aiDiff').textContent = d.diff || '';"
NEW_DRAFT_DIFF = (
    "        document.getElementById('aiDiffAdv').textContent = d.diff || '';"
)
assert (
    OLD_DRAFT_DIFF in js_body
), f"onDraftSelected aiDiff line not found\n---\n{OLD_DRAFT_DIFF}\n---"
js_body = js_body.replace(OLD_DRAFT_DIFF, NEW_DRAFT_DIFF, 1)

OLD_DRAFT_NOTES = (
    "        document.getElementById('aiNotes').textContent = notes.join('\\n');"
)
NEW_DRAFT_NOTES = (
    "        document.getElementById('aiNotesAdv').textContent = notes.join('\\n');"
)
assert OLD_DRAFT_NOTES in js_body, "onDraftSelected aiNotes line not found"
js_body = js_body.replace(OLD_DRAFT_NOTES, NEW_DRAFT_NOTES, 1)

# 3d. Update existing aiTargetKey listener to also sync pills
OLD_TARGET_KEY_LISTENER = """\
    document.getElementById('aiTargetKey').addEventListener('change', () => {
      clearAiProposal();
      onDraftSelected().catch(e => {
        document.getElementById('aiError').textContent = e.message;
      });
    });"""
NEW_TARGET_KEY_LISTENER = """\
    document.getElementById('aiTargetKey').addEventListener('change', () => {
      const _mode = document.getElementById('modeSelect').value;
      const _sysKey = MODE_TO_PROMPT_KEY[_mode] || '';
      const _isSys = document.getElementById('aiTargetKey').value === _sysKey;
      document.getElementById('aiTargetSysBtn').classList.toggle('active', _isSys);
      document.getElementById('aiTargetUserBtn').classList.toggle('active', !_isSys);
      clearAiProposal();
      onDraftSelected().catch(e => {
        document.getElementById('aiError').textContent = e.message;
      });
    });"""
assert OLD_TARGET_KEY_LISTENER in js_body, "aiTargetKey listener not found"
js_body = js_body.replace(OLD_TARGET_KEY_LISTENER, NEW_TARGET_KEY_LISTENER, 1)

# 3e. Inject new functions + listeners before loadApps() call at bottom
NEW_FUNCTIONS = """\
    // ── Colored diff renderer ──────────────────────────────────────────────
    function renderColoredDiff(rawText, targetEl) {
      if (!targetEl) return;
      targetEl.innerHTML = '';
      for (const line of rawText.split('\\n')) {
        const span = document.createElement('span');
        span.textContent = line;
        if      (line.startsWith('+') && !line.startsWith('+++')) span.className = 'dl-add';
        else if (line.startsWith('-') && !line.startsWith('---')) span.className = 'dl-del';
        else if (line.startsWith('@@'))                            span.className = 'dl-hdr';
        else                                                        span.className = 'dl-ctx';
        targetEl.appendChild(span);
        targetEl.appendChild(document.createTextNode('\\n'));
      }
    }

    // ── AI target pill toggle ─────────────────────────────────────────────
    function setAiTarget(which) {
      document.getElementById('aiTargetSysBtn').classList.toggle('active', which === 'sys');
      document.getElementById('aiTargetUserBtn').classList.toggle('active', which === 'user');
      const mode = document.getElementById('modeSelect').value;
      const sysKey  = MODE_TO_PROMPT_KEY[mode]        || 'openerSystem';
      const userKey = MODE_TO_USER_TEMPLATE_KEY[mode] || 'openerUser';
      const targetKey = which === 'sys' ? sysKey : userKey;
      const sel = document.getElementById('aiTargetKey');
      if ([...sel.options].some(o => o.value === targetKey)) {
        sel.value = targetKey;
        clearAiProposal();
        onDraftSelected().catch(() => {});
      }
    }

"""

NEW_LISTENERS = """\
    // ── AI improve bar listeners ──────────────────────────────────────────
    document.getElementById('aiTargetSysBtn').addEventListener('click', () => setAiTarget('sys'));
    document.getElementById('aiTargetUserBtn').addEventListener('click', () => setAiTarget('user'));
    document.getElementById('aiDiscardBtn').addEventListener('click', () => {
      clearAiProposal();
      document.getElementById('aiEditStatus').textContent = '';
    });
    document.getElementById('aiChangeRequest').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        aiPropose().catch(err => {
          document.getElementById('aiEditStatus').textContent = 'Error';
          document.getElementById('aiError').textContent = err.message;
        });
      }
    });

"""

LOAD_APPS_LINE = "    loadApps().catch(e => {"
assert LOAD_APPS_LINE in js_body, "loadApps() line not found"
js_body = js_body.replace(
    LOAD_APPS_LINE, NEW_FUNCTIONS + NEW_LISTENERS + LOAD_APPS_LINE, 1
)

# ── 4. Write CSS ─────────────────────────────────────────────────────────────
css_dir = os.path.join(ROOT, "css")
os.makedirs(css_dir, exist_ok=True)
css_path = os.path.join(css_dir, "workbench.css")
with open(css_path, "w", encoding="utf-8") as f:
    f.write(css_body.strip() + "\n")
print(f"CSS written: {css_path}")

# ── 5. Write JS ──────────────────────────────────────────────────────────────
js_dir = os.path.join(ROOT, "js")
os.makedirs(js_dir, exist_ok=True)
js_path = os.path.join(js_dir, "workbench.js")
with open(js_path, "w", encoding="utf-8") as f:
    f.write(js_body.strip() + "\n")
print(f"JS  written: {js_path}")

# ── 6. Write new index.html ──────────────────────────────────────────────────
NEW_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Prompt Workbench</title>
  <link rel="stylesheet" href="/css/workbench.css" />
</head>

<body>

  <!-- ── Top Bar ── -->
  <div class="topbar">
    <span class="topbar-title">Prompt Workbench</span>
    <span class="topbar-sep">|</span>
    <div>
      <label>App</label>
      <select id="appSelect"></select>
    </div>
    <div>
      <label>Mode</label>
      <select id="modeSelect"></select>
    </div>
    <div>
      <label>Model</label>
      <select id="modelSelect" style="min-width:240px"></select>
      <div class="muted">Costs show input / cached input / output ($ / 1M tokens).</div>
    </div>
    <div class="check-row" style="padding-bottom:1px;">
      <input id="dryRun" type="checkbox" />
      <span class="muted">Dry run</span>
    </div>
    <div class="flex-1"></div>
    <span id="aiEditStatus" class="muted"></span>
  </div>

  <!-- ── Main playground ── -->
  <div class="playground">

    <!-- LEFT: Editor Panel -->
    <div class="editor-panel">
      <div class="editor-body">

        <!-- System Prompt -->
        <div>
          <div class="section-label">System Prompt</div>
          <textarea id="systemPrompt" placeholder="System prompt\u2026" style="min-height:260px"></textarea>
        </div>

        <!-- User Template -->
        <div>
          <div class="section-label">User Template</div>
          <textarea id="userTemplate" placeholder="User prompt template\u2026" style="min-height:100px"></textarea>
        </div>

        <!-- AI Improve bar -->
        <div>
          <div class="section-label">Ask AI to improve</div>
          <div class="ai-bar">
            <div class="ai-bar-row">
              <input class="ai-bar-input" id="aiChangeRequest" type="text"
                placeholder="E.g., make it warmer but keep it concise\u2026 (Enter to run)" />
              <div class="ai-target-pills">
                <button class="pill-btn active" id="aiTargetSysBtn" type="button" title="Improve system prompt">Sys</button>
                <button class="pill-btn" id="aiTargetUserBtn" type="button" title="Improve user template">User</button>
              </div>
              <button class="ai-run-btn" id="aiProposeBtn" type="button" title="Propose improvement">&#9654;</button>
            </div>
            <div id="aiDiffWrap" style="display:none;">
              <div class="diff-area" id="aiDiff"></div>
              <div class="ai-action-row">
                <button class="btn btn-sm" id="aiApplyBtn" type="button" disabled>Apply</button>
                <button class="btn btn-ghost btn-sm" id="aiDiscardBtn" type="button">Discard</button>
                <span class="ai-status flex-1" id="aiAppliedInfo"></span>
                <span class="ai-err" id="aiError"></span>
              </div>
            </div>
          </div>
          <pre id="aiNotes" style="display:none"></pre>
          <select id="aiTargetKey" style="display:none"></select>
        </div>

      </div><!-- .editor-body -->

      <div class="editor-footer">
        <button class="btn btn-ghost btn-sm" id="aiUndoBtn" type="button">Undo</button>
        <button class="btn btn-ghost btn-sm" id="aiResetBtn" type="button">Reset</button>
        <div class="flex-1"></div>
        <button class="btn btn-sm" id="promoteBtn" type="button" disabled>Publish to repo</button>
        <span id="promoteStatus" class="muted"></span>
      </div>
    </div><!-- .editor-panel -->

    <!-- RIGHT: Run Panel -->
    <div class="run-panel">
      <div class="run-header">
        <div>
          <label>Fixture</label>
          <select id="fixtureSelect"></select>
        </div>
        <div>
          <label>Max</label>
          <input id="maxFixturesInput" type="number" min="0" value="0" style="width:64px"
            title="Max fixtures (0 = all)" />
        </div>
        <button class="btn" id="runSuiteBtn" type="button">Run</button>
        <span id="status" class="muted"></span>
      </div>
      <div class="run-results">
        <div id="results" class="muted">Run a fixture to see output.</div>
      </div>
    </div><!-- .run-panel -->

  </div><!-- .playground -->

  <!-- ── Advanced accordion ── -->
  <div class="advanced-wrap">
    <details class="adv">
      <summary>Advanced</summary>
      <div class="adv-body">

        <!-- Edit History -->
        <div>
          <div class="adv-section-title">Edit History</div>
          <div class="adv-row">
            <div>
              <label>Snapshot</label>
              <select id="draftSelect" style="width:100%"></select>
              <div id="draftMeta" class="muted" style="margin-top:4px;"></div>
            </div>
            <div>
              <label>Actions</label>
              <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button class="btn btn-ghost btn-sm" id="draftRefreshBtn" type="button">Refresh</button>
                <button class="btn btn-ghost btn-sm" id="draftRestoreBtn" type="button" disabled>Restore snapshot</button>
              </div>
            </div>
            <div>
              <label>Logs</label>
              <div class="muted">
                <a href="/api/logs?tail=200" target="_blank" rel="noopener">View server logs</a><br />
                trace: <span id="lastTraceId" style="font-family:monospace;font-size:11px;"></span>
              </div>
            </div>
          </div>
          <div style="height:10px"></div>
          <div class="adv-row2">
            <div>
              <div class="adv-section-title">Diff</div>
              <pre id="aiDiffAdv" style="min-height:60px;"></pre>
            </div>
            <div>
              <div class="adv-section-title">Notes</div>
              <pre id="aiNotesAdv" style="min-height:60px;"></pre>
            </div>
          </div>
        </div>

        <!-- Preview -->
        <div>
          <div class="adv-section-title">
            Preview
            <span id="previewStatus" class="muted"
              style="font-size:11px;font-weight:400;text-transform:none;letter-spacing:0;"></span>
          </div>
          <div class="adv-row2">
            <div>
              <div class="col-label">Baseline</div>
              <div class="muted" style="margin-bottom:2px;">System</div>
              <pre id="baselinePreviewSystem" style="min-height:40px;"></pre>
              <div class="muted" style="margin:6px 0 2px;">User</div>
              <pre id="baselinePreviewUser" style="min-height:40px;"></pre>
            </div>
            <div>
              <div class="col-label">Candidate</div>
              <div class="muted" style="margin-bottom:2px;">System</div>
              <pre id="candidatePreviewSystem" style="min-height:40px;"></pre>
              <div class="muted" style="margin:6px 0 2px;">User</div>
              <pre id="candidatePreviewUser" style="min-height:40px;"></pre>
            </div>
          </div>
        </div>

        <!-- Bundle metadata -->
        <div>
          <div class="adv-section-title">Bundle metadata</div>
          <div class="adv-row">
            <div>
              <label>updatedAt (UTC ISO)</label>
              <input id="updatedAtInput" type="text" style="width:100%" />
            </div>
            <div>
              <label>ttlSeconds</label>
              <input id="ttlSecondsInput" type="number" min="1" max="31536000" value="3600" style="width:100%" />
            </div>
            <div>
              <label>version</label>
              <input id="versionInput" type="number" min="1" max="999" value="1" style="width:100%" />
            </div>
          </div>
          <div style="height:10px"></div>
          <label>Candidate JSON</label>
          <div style="display:flex; gap:8px; align-items:center; margin:4px 0 6px;">
            <button class="btn btn-ghost btn-sm" id="formatJsonBtn" type="button">Format</button>
            <button class="btn btn-ghost btn-sm" id="validateJsonBtn" type="button">Validate</button>
            <span id="jsonStatus" class="muted"></span>
          </div>
          <textarea id="candidateJson" style="min-height:180px; font-size:12px;"></textarea>
          <div id="jsonError" class="err" style="margin-top:4px;"></div>
        </div>

        <!-- Ad-hoc tune run -->
        <div>
          <div class="adv-section-title">Ad-hoc tune run</div>
          <div class="muted" style="margin-bottom:6px;">
            Runs current system prompt with a hand-written user message (no fixtures).
          </div>
          <textarea id="userPrompt" placeholder="Write a user message here\u2026" style="min-height:80px;"></textarea>
          <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
            <button class="btn btn-ghost btn-sm" id="runTuneBtn" type="button">Run tune</button>
            <span id="tuneStatus" class="muted"></span>
          </div>
        </div>

      </div><!-- .adv-body -->
    </details>
  </div><!-- .advanced-wrap -->

  <script src="/js/workbench.js"></script>
</body>
</html>
"""

html_path = os.path.join(ROOT, "index.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(NEW_HTML)
print(f"HTML written: {html_path}")
print("\nAll done.")
