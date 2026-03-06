// ── State ─────────────────────────────────────────────────────────────
let currentCandidate = null;
let models = [];
let aiLastProposal = null;
let lastTraceId = '';
let draftVersions = [];
let latestSuite = null;
let latestSuiteIsClean = false;

// Text of the "Base" version for the current mode key (populated on load)
let baseSystemText = '';
// Full prompts object from the canonical baseline (cached to allow mode-switch re-derive)
let cachedBaselinePrompts = null;
// Text currently shown in the textarea (the "current" live candidate)
let currentSystemText = '';
// Which pill id is in preview mode (null = none)
let previewPillId = null;
// Which pill is currently selected in the compare modal (null = none)
let selectedComparePillId = null;

const MODE_TO_PROMPT_KEY = {
  opener: 'openerSystem',
  app_chat: 'appChatSystem',
  reg_chat: 'regChatSystem',
};

const MODE_TO_USER_TEMPLATE_KEY = {
  opener: 'openerUser',
  app_chat: 'appChatUser',
  reg_chat: 'regChatUser',
};

// Hue palette matching vp-hue-{0..7} CSS classes; index 8 = base (green).
const HUE_STYLES = [
  { background: '#ecfeff', color: '#0e7490', borderColor: '#a5f3fc' },  // 0 cyan
  { background: '#fffbeb', color: '#b45309', borderColor: '#fde68a' },  // 1 amber
  { background: '#f5f3ff', color: '#7c3aed', borderColor: '#ddd6fe' },  // 2 violet
  { background: '#f0f9ff', color: '#0369a1', borderColor: '#bae6fd' },  // 3 sky
  { background: '#f0fdfa', color: '#0f766e', borderColor: '#99f6e4' },  // 4 teal
  { background: '#fdf4ff', color: '#a21caf', borderColor: '#f0abfc' },  // 5 fuchsia
  { background: '#fff7ed', color: '#c2410c', borderColor: '#fed7aa' },  // 6 orange
  { background: '#eef2ff', color: '#3730a3', borderColor: '#c7d2fe' },  // 7 indigo
  { background: '#f0fdf4', color: '#166534', borderColor: '#bbf7d0' },  // 8 green (base)
];

// ── API helper ────────────────────────────────────────────────────────
async function api(path, opts) {
  const res = await fetch(path, opts);
  const trace = res.headers.get('X-Trace-Id') || '';
  if (trace) lastTraceId = trace;
  if (!res.ok) {
    const t = await res.text();
    const base = t || ('HTTP ' + res.status);
    const suffix = (trace || lastTraceId) ? `\ntrace_id=${trace || lastTraceId}` : '';
    throw new Error(base + suffix);
  }
  return res;
}

// ── Utility ───────────────────────────────────────────────────────────
function esc(s) {
  return (s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function nowUtcIso() {
  return new Date().toISOString();
}

function parseCandidateJson(text) {
  try { return { ok: true, obj: JSON.parse(text) }; }
  catch (e) { return { ok: false, error: e?.message || String(e) }; }
}

// ── Sync helpers ──────────────────────────────────────────────────────
function candidateFromFields() {
  const base = currentCandidate && typeof currentCandidate === 'object' ? currentCandidate : {};
  const prompts = { ...(base.prompts || {}) };

  const mode = document.getElementById('modeSelect').value;
  const key = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';
  prompts[key] = document.getElementById('systemPrompt').value || '';

  const userKey = MODE_TO_USER_TEMPLATE_KEY[mode];
  if (userKey) prompts[userKey] = document.getElementById('userTemplate').value || '';

  const version = parseInt(document.getElementById('versionInput').value, 10) || (base.version ?? 1) || 1;
  const ttlSeconds = parseInt(document.getElementById('ttlSecondsInput').value, 10) || (base.ttlSeconds ?? 3600) || 3600;
  const updatedAt = (document.getElementById('updatedAtInput').value || '').trim() || (base.updatedAt ?? '') || nowUtcIso();

  return { version, updatedAt, ttlSeconds, prompts };
}

function syncFieldsFromCandidate(cand) {
  currentCandidate = cand;

  document.getElementById('versionInput').value = String(cand?.version ?? 1);
  document.getElementById('ttlSecondsInput').value = String(cand?.ttlSeconds ?? 3600);
  document.getElementById('updatedAtInput').value = String(cand?.updatedAt ?? '');

  const p = cand?.prompts || {};
  const mode = document.getElementById('modeSelect').value;
  const key = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';

  currentSystemText = p[key] || '';
  document.getElementById('systemPrompt').value = currentSystemText;

  const userKey = MODE_TO_USER_TEMPLATE_KEY[mode];
  document.getElementById('userTemplate').value = (userKey && p[userKey]) ? p[userKey] : '';

  refreshAiTargetKeys();
  clearAiProposal();
  exitPreviewMode();
}

function syncJsonFromFields() {
  const cand = candidateFromFields();
  currentCandidate = cand;
  return cand;
}

function refreshAiTargetKeys() {
  const sel = document.getElementById('aiTargetKey');
  const keys = Object.keys((currentCandidate && currentCandidate.prompts) ? currentCandidate.prompts : {}).sort();
  sel.innerHTML = '';
  for (const k of keys) {
    const opt = document.createElement('option');
    opt.value = k; opt.textContent = k;
    sel.appendChild(opt);
  }
  // Always target the system key for the current mode
  const mode = document.getElementById('modeSelect').value;
  const defaultKey = MODE_TO_PROMPT_KEY[mode] || (keys[0] || '');
  if (defaultKey && keys.includes(defaultKey)) sel.value = defaultKey;
  else if (keys.length) sel.value = keys[0];
}

// ── AI proposal helpers ───────────────────────────────────────────────
function clearAiProposal() {
  aiLastProposal = null;
  const diffEl = document.getElementById('aiDiff');
  if (diffEl) diffEl.innerHTML = '';
  document.querySelector('.ai-bar')?.classList.remove('ai-bar--reviewing');
  document.getElementById('aiError').textContent = '';
  document.getElementById('aiApplyBtn').disabled = true;
  hideSysDiffOverlay();
}

function aiNotesFromProposal(p) {
  if (!p || typeof p !== 'object') return '';
  const lines = [];
  if (typeof p.status === 'string') lines.push('status: ' + p.status);
  if (typeof p.selfCheck === 'boolean') lines.push('selfCheck: ' + String(p.selfCheck));
  if (typeof p.rationale === 'string' && p.rationale.trim()) lines.push('\nRationale:\n' + p.rationale.trim());
  const warnings = Array.isArray(p.warnings) ? p.warnings : [];
  if (warnings.length) lines.push('\nWarnings:\n- ' + warnings.map(w => String(w)).join('\n- '));
  if (typeof p.refusalReason === 'string' && p.refusalReason.trim()) lines.push('\nRefusal:\n' + p.refusalReason.trim());
  return lines.join('\n');
}

function setAiAppliedInfo(text) {
  const el = document.getElementById('aiAppliedInfo');
  if (el) el.textContent = text || '';
}

function setPromoteStatus(text) {
  if (!text) return;
  const el = document.getElementById('aiEditStatus');
  if (el) el.textContent = text;
}

// ── Sys-prompt diff overlay ───────────────────────────────────────────
function showSysDiffOverlay(rawDiff) {
  const overlay = document.getElementById('sysPromptDiffOverlay');
  if (!overlay) return;
  overlay.innerHTML = '';
  for (const line of rawDiff.split('\n')) {
    const span = document.createElement('span');
    span.textContent = line;
    if (line.startsWith('+') && !line.startsWith('+++')) span.className = 'dl-add';
    else if (line.startsWith('-') && !line.startsWith('---')) span.className = 'dl-del';
    else if (line.startsWith('@@')) span.className = 'dl-hdr';
    else span.className = 'dl-ctx';
    overlay.appendChild(span);
    overlay.appendChild(document.createTextNode('\n'));
  }
  overlay.classList.add('visible');
}

function hideSysDiffOverlay() {
  const overlay = document.getElementById('sysPromptDiffOverlay');
  if (overlay) {
    overlay.classList.remove('visible');
    overlay.innerHTML = '';
  }
}

// ── Version pills ─────────────────────────────────────────────────────
// versionNum: 1-based creation index (1 = oldest). Pass it to include a v{n} prefix.
function pillLabel(v, versionNum) {
  const prefix = versionNum ? 'v' + versionNum + ' \u00b7 ' : '';
  const req = (v.changeRequest || '').trim();
  if (req) {
    // Shorten more when carrying a version prefix so pills don't overflow
    const maxLen = versionNum ? 16 : 22;
    const short = req.length > maxLen ? req.slice(0, maxLen - 2) + '\u2026' : req;
    return prefix + short;
  }
  const when = v.savedAt || '';
  try {
    if (when) {
      const dt = new Date(when);
      return prefix + dt.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    }
  } catch (_) { }
  return 'v' + (versionNum || v.id || '?');
}

function inferModeFromTargetKey(tk) {
  const t = String(tk || '');
  if (t.startsWith('opener')) return 'opener';
  if (t.startsWith('appChat')) return 'app_chat';
  if (t.startsWith('regChat')) return 'reg_chat';
  return '';
}

function modeForVersion(v) {
  if (!v) return '';
  const m = String(v.mode || '').trim();
  if (m) return m;
  if (v.targetKey) return inferModeFromTargetKey(v.targetKey);
  const r = String(v.reason || '');
  if (r.startsWith('apply:')) return inferModeFromTargetKey(r.slice('apply:'.length));
  return '';
}

function rebuildPills(versions) {
  const container = document.getElementById('versionPills');
  if (!container) return;
  container.innerHTML = '';

  // Base pill (always first, pinned)
  const baseBtn = document.createElement('button');
  baseBtn.type = 'button';
  baseBtn.className = 'version-pill base-pill';
  baseBtn.dataset.id = '__base__';
  baseBtn.textContent = 'Base';
  baseBtn.title = 'Original / canonical prompt';
  baseBtn.addEventListener('click', () => onPillClick('__base__', null, null));
  container.appendChild(baseBtn);

  // Draft pills: newest first (left), oldest last (right).
  // versions[0] = v1 (oldest), versions[last] = vN (newest).
  for (let i = versions.length - 1; i >= 0; i--) {
    const v = versions[i];
    const vNum = i + 1; // v1 = oldest, vN = newest
    const hue = (vNum - 1) % 8;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `version-pill vp-hue-${hue}`;
    btn.dataset.id = String(v.id || '');
    btn.dataset.versionNum = String(vNum);
    btn.textContent = pillLabel(v, vNum);
    btn.title = `v${vNum}${v.changeRequest ? ': \u201c' + v.changeRequest + '\u201d' : ''}`;
    btn.addEventListener('click', () => onPillClick(String(v.id || ''), v, vNum));
    container.appendChild(btn);
  }

  // Mark active pill = latest draft (vN) or base if none
  updateActivePill(versions.length ? String(versions[versions.length - 1].id || '') : '__base__');
}

function updateActivePill(activeId) {
  document.querySelectorAll('#versionPills .version-pill').forEach(btn => {
    const isActive = btn.dataset.id === activeId;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-pressed', String(isActive));
  });
}

async function onPillClick(id, versionObj, versionNum) {
  // Re-clicking the currently-previewed pill exits preview mode
  if (id === previewPillId) {
    exitPreviewMode();
    return;
  }

  if (id === '__base__') {
    enterPreviewMode('__base__', 'Base', baseSystemText, 8);
    return;
  }

  const appId = document.getElementById('appSelect').value;
  const mode = document.getElementById('modeSelect').value;
  const key = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';

  try {
    const d = await (await api(
      '/api/drafts/diff?appId=' + encodeURIComponent(appId) +
      '&id=' + encodeURIComponent(id) +
      '&targetKey=' + encodeURIComponent(key)
    )).json();
    const snapshotText = d.snapshotText || (versionObj && versionObj.updatedText) || '';
    const label = versionObj ? pillLabel(versionObj, versionNum) : id;
    enterPreviewMode(id, label, snapshotText, versionNum !== null && versionNum !== undefined ? (versionNum - 1) % 8 : 0);
  } catch (e) {
    document.getElementById('aiError').textContent = e.message;
  }
}

function enterPreviewMode(id, label, text, hue) {
  previewPillId = id;
  updateActivePill(id);

  document.getElementById('systemPrompt').value = text;

  // Show a colored diff in the overlay so highlights are visible on the main screen.
  // Skip for the base pill (no diff — it IS the base).
  if (id !== '__base__') {
    const ops = computeLineDiff(baseSystemText, text);
    const overlay = document.getElementById('sysPromptDiffOverlay');
    if (overlay) {
      overlay.innerHTML = '';
      for (const op of ops) {
        const s = document.createElement('span');
        if (op.type === 'del') s.className = 'dl-del';
        else if (op.type === 'add') s.className = hue !== undefined ? `dl-add-hue-${hue}` : 'dl-add';
        else s.className = 'dl-ctx';
        s.textContent = op.text;
        overlay.appendChild(s);
        overlay.appendChild(document.createTextNode('\n'));
      }
      overlay.classList.add('visible');
    }
  } else {
    hideSysDiffOverlay();
  }

  const bar = document.getElementById('sysVersionBar');
  const lbl = document.getElementById('sysVersionBarLabel');
  if (bar && lbl) {
    lbl.textContent = 'Previewing: ' + label;
    const s = HUE_STYLES[hue !== undefined && hue >= 0 && hue <= 8 ? hue : 8];
    bar.style.background = s.background;
    bar.style.color = s.color;
    bar.style.borderColor = s.borderColor;
    bar.classList.add('visible');
  }
}

function exitPreviewMode() {
  if (!previewPillId) return;
  previewPillId = null;

  document.getElementById('systemPrompt').value = currentSystemText;
  hideSysDiffOverlay();

  const bar = document.getElementById('sysVersionBar');
  if (bar) {
    bar.classList.remove('visible');
    bar.style.background = '';
    bar.style.color = '';
    bar.style.borderColor = '';
  }

  const currentMode = document.getElementById('modeSelect').value;
  const visibleDrafts = draftVersions.filter(v => { const vm = modeForVersion(v); return !vm || vm === currentMode; });
  updateActivePill(visibleDrafts.length ? String(visibleDrafts[visibleDrafts.length - 1].id || '') : '__base__');
}

async function restorePreviewedPill() {
  if (!previewPillId) return;
  if (previewPillId === '__base__') {
    await aiReset();
    return;
  }
  if (!confirm('Restore this snapshot into your local Candidate prompts?')) return;

  const appId = document.getElementById('appSelect').value;
  await api('/api/drafts/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId, id: previewPillId }),
  });

  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);
  schedulePreview();
  await refreshDrafts();
  document.getElementById('aiEditStatus').textContent = 'Restored snapshot';
}

// ── Baseline text helpers ─────────────────────────────────────────────
function refreshBaseSystemText() {
  const mode = (document.getElementById('modeSelect') || {}).value || '';
  const key = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';
  baseSystemText = (cachedBaselinePrompts && cachedBaselinePrompts[key]) ? cachedBaselinePrompts[key] : '';
}

// ── Compare modal ─────────────────────────────────────────────────────

// Line-level LCS diff. Returns ops: [{type:'keep'|'del'|'add', text}]
function computeLineDiff(oldText, newText) {
  const a = oldText.split('\n');
  const b = newText.split('\n');
  const m = a.length, n = b.length;
  // Build LCS table bottom-up
  const dp = Array.from({ length: m + 1 }, () => new Int32Array(n + 1));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  // Traceback
  const ops = [];
  let i = 0, j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) { ops.push({ type: 'keep', text: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ type: 'del', text: a[i++] }); }
    else { ops.push({ type: 'add', text: b[j++] }); }
  }
  while (i < m) ops.push({ type: 'del', text: a[i++] });
  while (j < n) ops.push({ type: 'add', text: b[j++] });
  return ops;
}

// Render one side of a side-by-side diff into el.
// side='del' → base pane (keep + del lines); side='add' → current pane (keep + add lines)
// hue: optional 0-7 index to use dl-add-hue-{n} instead of generic dl-add (per-version color)
function renderDiffPane(el, ops, side, hue) {
  el.innerHTML = '';
  for (const op of ops) {
    if (op.type !== 'keep' && op.type !== side) continue; // skip the other side's lines
    const s = document.createElement('span');
    if (op.type === 'del') s.className = 'dl-del';
    else if (op.type === 'add') s.className = hue !== undefined ? `dl-add-hue-${hue}` : 'dl-add';
    else s.className = 'dl-ctx';
    s.textContent = op.text;
    el.appendChild(s);
    el.appendChild(document.createTextNode('\n'));
  }
}

// Render a diff between base and the selected pill in the compare modal.
// knownText: pass already-loaded text to skip the API fetch (used for latest draft).
async function selectComparePill(id, versionObj, knownText, versionNum) {
  selectedComparePillId = id;
  document.querySelectorAll('#compareModalPills .version-pill').forEach(btn => {
    const isActive = btn.dataset.id === id;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-pressed', String(isActive));
  });

  // Clear any previous inline error when switching pills.
  const errEl = document.getElementById('compareModalError');
  if (errEl) errEl.textContent = '';

  let text = knownText;
  if (text === undefined) {
    const appId = document.getElementById('appSelect').value;
    const mode = document.getElementById('modeSelect').value;
    const key = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';
    const d = await (await api(
      '/api/drafts/diff?appId=' + encodeURIComponent(appId) +
      '&id=' + encodeURIComponent(id) +
      '&targetKey=' + encodeURIComponent(key)
    )).json();
    text = d.snapshotText || (versionObj && versionObj.updatedText) || '';
  }

  const label = versionObj ? pillLabel(versionObj, versionNum) : id;
  const currentColLabel = document.getElementById('compareCurrentLabel');
  if (currentColLabel) currentColLabel.textContent = 'Current \u00b7 ' + label;

  const baseEl = document.getElementById('compareBaseText');
  const currentEl = document.getElementById('compareCurrentText');
  const ops = computeLineDiff(baseSystemText, text);
  const hue = versionNum !== null && versionNum !== undefined ? (versionNum - 1) % 8 : undefined;
  renderDiffPane(baseEl, ops, 'del');
  renderDiffPane(currentEl, ops, 'add', hue);
}

function openCompareModal() {
  const currentMode = document.getElementById('modeSelect').value;
  const visibleDrafts = draftVersions.filter(v => { const vm = modeForVersion(v); return !vm || vm === currentMode; });

  // Build version pills inside the modal: newest first (left), oldest last (right).
  // visibleDrafts[0] = v1 (oldest), visibleDrafts[last] = vN (newest).
  const pillsEl = document.getElementById('compareModalPills');
  pillsEl.innerHTML = '';
  for (let i = visibleDrafts.length - 1; i >= 0; i--) {
    const v = visibleDrafts[i];
    const vNum = i + 1;
    const hue = (vNum - 1) % 8;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `version-pill vp-hue-${hue}`;
    btn.dataset.id = String(v.id || '');
    btn.dataset.versionNum = String(vNum);
    btn.textContent = pillLabel(v, vNum);
    btn.title = `v${vNum}${v.changeRequest ? ': \u201c' + v.changeRequest + '\u201d' : ''}`;
    btn.addEventListener('click', () =>
      selectComparePill(String(v.id || ''), v, undefined, vNum).catch(e => {
        document.getElementById('aiError').textContent = e.message;
      })
    );
    pillsEl.appendChild(btn);
  }

  // Sync action button states
  const deleteBtn = document.getElementById('compareDeleteBtn');
  const publishBtn = document.getElementById('comparePublishBtn');
  if (deleteBtn) deleteBtn.disabled = draftVersions.length === 0;
  if (publishBtn) {
    publishBtn.disabled = !latestSuiteIsClean;
    publishBtn.title = latestSuiteIsClean
      ? 'Publish candidate \u2192 canonical prompts file'
      : 'Run the suite first (all fixtures must pass)';
  }

  document.getElementById('compareModal').style.display = 'flex';

  // Default to latest draft = vN (use currentSystemText — no fetch needed)
  const latestDraft = visibleDrafts.length ? visibleDrafts[visibleDrafts.length - 1] : null;
  const latestVNum = visibleDrafts.length;
  if (latestDraft) {
    selectComparePill(String(latestDraft.id || ''), latestDraft, currentSystemText, latestVNum).catch(e => {
      document.getElementById('aiError').textContent = e.message;
    });
  } else {
    // No drafts: show live candidate vs base
    const currentColLabel = document.getElementById('compareCurrentLabel');
    if (currentColLabel) currentColLabel.textContent = 'Current';
    const baseEl = document.getElementById('compareBaseText');
    const currentEl = document.getElementById('compareCurrentText');
    const ops = computeLineDiff(baseSystemText, currentSystemText);
    renderDiffPane(baseEl, ops, 'del');
    renderDiffPane(currentEl, ops, 'add');
  }
}

function closeCompareModal() {
  document.getElementById('compareModal').style.display = 'none';
}

// ── Draft refresh + Publish ───────────────────────────────────────────
async function refreshDrafts() {
  const appId = document.getElementById('appSelect').value;
  document.getElementById('aiError').textContent = '';

  const res = await (await api('/api/drafts?appId=' + encodeURIComponent(appId))).json();
  draftVersions = res.versions || [];
  latestSuite = res.latestSuite || null;
  latestSuiteIsClean = res.latestSuiteIsClean === true;

  // F1: Disable delete when there is no draft history
  const deleteBtn = document.getElementById('compareDeleteBtn');
  if (deleteBtn) deleteBtn.disabled = draftVersions.length === 0;

  const currentMode = document.getElementById('modeSelect').value;
  const visibleDrafts = draftVersions.filter(v => { const vm = modeForVersion(v); return !vm || vm === currentMode; });
  rebuildPills(visibleDrafts);
}

async function promoteToCanonical() {
  if (!confirm('Publish Candidate \u2192 repo prompts file (prompts/<appId>.json) and clear local history?')) return;

  const appId = document.getElementById('appSelect').value;
  setPromoteStatus('Promoting\u2026');
  await api('/api/promote', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId, requireClean: true }),
  });

  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);
  schedulePreview();
  await refreshDrafts();
  setPromoteStatus('Done');
}

// ── AI propose / apply / undo / reset ────────────────────────────────
async function aiPropose() {
  clearAiProposal();
  setAiAppliedInfo('');
  const status = document.getElementById('aiEditStatus');

  const appId = document.getElementById('appSelect').value;
  const model = document.getElementById('modelSelect').value;
  const dryRun = !!document.getElementById('dryRun').checked;
  const mode = document.getElementById('modeSelect').value;
  const targetKey = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';
  const changeRequest = (document.getElementById('aiChangeRequest').value || '').trim();

  if (!changeRequest) {
    document.getElementById('aiError').textContent = 'Enter a change request.';
    return;
  }

  // Ensure aiTargetKey hidden select matches
  const sel = document.getElementById('aiTargetKey');
  if ([...sel.options].some(o => o.value === targetKey)) sel.value = targetKey;

  // Loading state
  const proposeBtn = document.getElementById('aiProposeBtn');
  const inputEl = document.getElementById('aiChangeRequest');
  const aiBar = inputEl.closest('.ai-bar');
  proposeBtn.classList.add('loading');
  proposeBtn.disabled = true;
  inputEl.disabled = true;
  if (aiBar) aiBar.classList.add('loading');

  // Open diff area immediately with pulsing placeholder
  const diffEl = document.getElementById('aiDiff');
  diffEl.innerHTML = '<div class="ai-thinking">Working on it\u2026</div>';
  if (aiBar) aiBar.classList.add('ai-bar--reviewing');
  document.getElementById('aiApplyBtn').disabled = true;
  status.textContent = '';

  try {
    document.getElementById('updatedAtInput').value = nowUtcIso();
    const candidateObj = syncJsonFromFields();
    await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(candidateObj),
    });

    const payload = { appId, model, dryRun, targetKey, changeRequest };
    const res = await (await api('/api/edit/propose', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();

    const proposal = res.proposal;
    aiLastProposal = proposal;

    renderColoredDiff(res.diff || '', diffEl);
    showSysDiffOverlay(res.diff || '');

    const _notesEl = document.getElementById('aiNotes');
    if (_notesEl) _notesEl.textContent = aiNotesFromProposal(proposal);

    const ok = proposal && proposal.status === 'ok' && proposal.selfCheck === true;
    document.getElementById('aiApplyBtn').disabled = !ok;

    if (!ok) {
      const refusal = (proposal && typeof proposal.refusalReason === 'string') ? proposal.refusalReason.trim() : '';
      if (refusal) document.getElementById('aiError').textContent = refusal;
    }

    status.textContent = ok ? 'Ready to apply' : 'Cannot apply';
  } finally {
    proposeBtn.classList.remove('loading');
    // W5: re-enable propose only when input has text
    proposeBtn.disabled = !(inputEl.value.trim());
    inputEl.disabled = false;
    if (aiBar) aiBar.classList.remove('loading');
    // F4: return focus to input after proposal (deferred to avoid race with DOM updates)
    setTimeout(() => inputEl.focus(), 0);
  }
}

async function aiApply() {
  const status = document.getElementById('aiEditStatus');
  const proposal = aiLastProposal;
  if (!proposal || proposal.status !== 'ok' || proposal.selfCheck !== true) {
    document.getElementById('aiError').textContent = 'No valid proposal to apply.';
    return;
  }

  status.textContent = 'Applying\u2026';
  document.getElementById('aiError').textContent = '';

  const appId = document.getElementById('appSelect').value;
  const mode = document.getElementById('modeSelect').value;
  const model = document.getElementById('modelSelect').value;
  const payload = {
    appId, mode, model,
    changeRequest: (document.getElementById('aiChangeRequest').value || '').trim(),
    notes: aiNotesFromProposal(proposal),
    targetKey: proposal.targetKey,
    updatedText: proposal.updatedText,
    selfCheck: proposal.selfCheck,
  };

  const applyRes = await (await api('/api/edit/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })).json();

  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);

  const stored = (cand && cand.prompts && typeof cand.prompts === 'object') ? cand.prompts[proposal.targetKey] : null;
  const verified = (typeof stored === 'string') && (stored === proposal.updatedText);

  const when = (applyRes && typeof applyRes.updatedAt === 'string' && applyRes.updatedAt) ? applyRes.updatedAt : (cand && cand.updatedAt ? String(cand.updatedAt) : '');
  const trace = (applyRes && typeof applyRes.traceId === 'string' && applyRes.traceId) ? applyRes.traceId : (lastTraceId || '');
  const tracePart = trace ? ` | trace_id=${trace}` : '';
  const whenPart = when ? ` at ${when}` : '';
  setAiAppliedInfo(`Applied${whenPart}${tracePart} \u2014 ${verified ? 'VERIFIED' : 'NOT VERIFIED'}`);

  clearAiProposal();
  schedulePreview();
  await refreshDrafts(); // Show new pill immediately before suite run

  status.textContent = 'Applied; running suite\u2026';
  await runSuite();
  status.textContent = 'Applied + suite done';
  await refreshDrafts(); // Refresh again after suite to update publish eligibility
}

async function aiDeleteVersion(draftId) {
  const appId = document.getElementById('appSelect').value;
  await api('/api/drafts/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId, id: draftId }),
  });
  // syncFieldsFromCandidate will call exitPreviewMode() if the deleted version was active
  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);
  schedulePreview();
  await refreshDrafts();
}

async function aiUndo() {
  clearAiProposal();
  const status = document.getElementById('aiEditStatus');
  status.textContent = 'Undoing\u2026';
  const appId = document.getElementById('appSelect').value;
  await api('/api/edit/undo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId }),
  });
  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);
  schedulePreview();
  status.textContent = 'Version deleted';
  await refreshDrafts();
}

async function aiReset() {
  if (!confirm('Remove all draft versions and reset to the base prompt? This cannot be undone.')) return;
  clearAiProposal();
  const status = document.getElementById('aiEditStatus');
  status.textContent = 'Resetting\u2026';
  const appId = document.getElementById('appSelect').value;
  await api('/api/edit/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId }),
  });
  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);
  schedulePreview();
  status.textContent = 'Reset';
  await refreshDrafts();
}

// ── Models / Apps / Fixtures ─────────────────────────────────────────
function fmtRate(n) {
  if (n === null || n === undefined || !Number.isFinite(n)) return '';
  return '$' + n.toFixed(3);
}

function modelLabel(m) {
  return m.model;
}

async function loadModels() {
  const res = await (await api('/api/models')).json();
  models = res.models || [];
  const modelSelect = document.getElementById('modelSelect');
  modelSelect.innerHTML = '';
  for (const m of models) {
    const opt = document.createElement('option');
    opt.value = m.model;
    opt.textContent = modelLabel(m);
    opt.title = `in ${fmtRate(m.inputPer1M)} / cached ${fmtRate(m.cachedInputPer1M)} / out ${fmtRate(m.outputPer1M)}`;
    modelSelect.appendChild(opt);
  }
}

async function loadApps() {
  await loadModels();
  const apps = await (await api('/api/apps')).json();
  const appSelect = document.getElementById('appSelect');
  appSelect.innerHTML = '';
  for (const a of apps) {
    const opt = document.createElement('option');
    opt.value = a.appId;
    opt.textContent = a.displayName;
    appSelect.appendChild(opt);
  }
  appSelect.addEventListener('change', () => onAppChanged());
  await onAppChanged();
}

async function onAppChanged() {
  const appId = document.getElementById('appSelect').value;
  const cfg = await (await api('/api/apps/' + encodeURIComponent(appId))).json();
  const modeSelect = document.getElementById('modeSelect');
  modeSelect.innerHTML = '';
  for (const m of cfg.modes) {
    const opt = document.createElement('option');
    opt.value = m; opt.textContent = m;
    modeSelect.appendChild(opt);
  }

  modeSelect.addEventListener('change', () => {
    if (currentCandidate) syncFieldsFromCandidate(currentCandidate);
    refreshBaseSystemText();
    loadFixtures().catch(() => { });
    refreshDrafts().catch(() => { });
  });

  const modelSelect = document.getElementById('modelSelect');
  const desired = (cfg.defaultModel || 'gpt-5-mini').trim();
  const has = [...modelSelect.options].some(o => o.value === desired);
  modelSelect.value = has ? desired : (modelSelect.options[0]?.value || desired);

  // Try to load baseline text for compare modal
  try {
    const baseRes = await (await api('/api/baselines?appId=' + encodeURIComponent(appId))).json();
    cachedBaselinePrompts = (baseRes && baseRes.prompts) ? baseRes.prompts : null;
  } catch (_) {
    cachedBaselinePrompts = null;
  }
  refreshBaseSystemText();

  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);
  await loadFixtures();
  schedulePreview();
  await refreshDrafts();
}

async function loadFixtures() {
  const appId = document.getElementById('appSelect').value;
  const mode = document.getElementById('modeSelect').value;
  const res = await (await api('/api/fixtures?appId=' + encodeURIComponent(appId) + '&mode=' + encodeURIComponent(mode))).json();
  const sel = document.getElementById('fixtureSelect');
  sel.innerHTML = '';
  const optAll = document.createElement('option');
  optAll.value = ''; optAll.textContent = 'All fixtures';
  sel.appendChild(optAll);
  for (const fx of (res.fixtures || [])) {
    const opt = document.createElement('option');
    opt.value = fx.name || '';
    opt.textContent = fx.name + (fx.kind ? ` (${fx.kind})` : '');
    sel.appendChild(opt);
  }
  sel.onchange = () => schedulePreview();
}

// ── Preview ────────────────────────────────────────────────────────────
let previewTimer = null;
function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = setTimeout(() => updatePreview().catch(() => { }), 200);
}

function setPreviewText(id, text) {
  document.getElementById(id).textContent = text || '';
}

async function updatePreview() {
  const status = document.getElementById('previewStatus');
  const fixture = (document.getElementById('fixtureSelect').value || '').trim();
  if (!fixture) {
    status.textContent = 'Select a fixture to preview.';
    ['baselinePreviewSystem', 'baselinePreviewUser', 'candidatePreviewSystem', 'candidatePreviewUser']
      .forEach(id => setPreviewText(id, ''));
    return;
  }
  status.textContent = 'Rendering\u2026';
  const appId = document.getElementById('appSelect').value;
  const mode = document.getElementById('modeSelect').value;
  const systemPrompt = document.getElementById('systemPrompt').value || '';
  const userTemplate = document.getElementById('userTemplate').value || '';

  const payload = { appId, mode, fixture, systemPrompt, userTemplate };
  const res = await (await api('/api/compose', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })).json();

  setPreviewText('baselinePreviewSystem', res?.baseline?.system || '');
  setPreviewText('baselinePreviewUser', res?.baseline?.user || '');
  setPreviewText('candidatePreviewSystem', res?.candidate?.system || '');
  setPreviewText('candidatePreviewUser', res?.candidate?.user || '');
  status.textContent = `OK: ${res?.fixture?.name || fixture}`;
}

// ── Run suite ──────────────────────────────────────────────────────────
async function runSuite() {
  const status = document.getElementById('status');
  const runBtn = document.getElementById('runSuiteBtn');
  status.textContent = 'Running suite\u2026';
  if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Running\u2026'; }

  const appId = document.getElementById('appSelect').value;
  const mode = document.getElementById('modeSelect').value;
  const model = document.getElementById('modelSelect').value;
  const dryRun = !!document.getElementById('dryRun').checked;
  const maxFixtures = parseInt(document.getElementById('maxFixturesInput').value, 10) || 0;
  const fixture = (document.getElementById('fixtureSelect').value || '').trim();

  document.getElementById('updatedAtInput').value = nowUtcIso();
  const candidateObj = syncJsonFromFields();
  await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(candidateObj),
  });

  const payload = { appId, mode, model, dryRun, maxFixtures, baselineSource: 'local_file' };
  if (fixture) payload.fixture = fixture;

  try {
    const run = await (await api('/api/run/ab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();

    status.textContent = 'Done';
    renderSuiteResults(run);
    await refreshDrafts();
  } finally {
    if (runBtn) { runBtn.disabled = false; runBtn.textContent = 'Run'; }
  }
}

// ── Result renderers ───────────────────────────────────────────────────
function renderSuiteResults(run) {
  const root = document.getElementById('results');
  const reportPath = run.reportPath || '';
  const reportLink = reportPath ? `<a href="${esc(reportPath)}" target="_blank" rel="noreferrer">ab_report.html</a>` : '';
  const items = run.items || [];
  const totals = run.totals || {};

  const totalsLine = `Tokens \u2014 live in/out: ${esc(String(totals.baselineInputTokens ?? 0))}/${esc(String(totals.baselineOutputTokens ?? 0))} &nbsp;\u00b7&nbsp; draft in/out: ${esc(String(totals.candidateInputTokens ?? 0))}/${esc(String(totals.candidateOutputTokens ?? 0))}`;

  let html = `<div class="muted">Report: ${reportLink || '(not available)'} &nbsp;\u00b7&nbsp; ${totalsLine}</div><div style="height:10px"></div>`;

  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const name = it.fixture || '';
    const inp = it.baselineInput || it.candidateInput || '';
    const bout = it.baselineOutput || '';
    const cout = it.candidateOutput || '';
    const bflags = Array.isArray(it.baselineFlags) ? it.baselineFlags.join(',') : '';
    const cflags = Array.isArray(it.candidateFlags) ? it.candidateFlags.join(',') : '';
    const berr = it.baselineError || '';
    const cerr = it.candidateError || '';
    const shouldOpen = i === 0 || !!cerr;

    html += `
      <details class="card ab-fixture"${shouldOpen ? ' open' : ''}>
        <summary><strong>${esc(name)}</strong></summary>
        <div style="height:8px"></div>
        <details class="ab-input-toggle">
          <summary>Input</summary>
          <pre class="ab-input-pre">${esc(inp)}</pre>
        </details>
        <div style="height:8px"></div>
        <div class="result-grid">
          <div>
            <div class="ab-col-label ab-col-live">Live</div>
            <div class="muted ab-flags">flags: ${esc(bflags || '(none)')}${berr ? ` | error: ${esc(berr)}` : ''}</div>
            <pre class="ab-output">${esc(bout)}</pre>
          </div>
          <div>
            <div class="ab-col-label ab-col-draft">Draft</div>
            <div class="muted ab-flags">flags: ${esc(cflags || '(none)')}${cerr ? ` | error: ${esc(cerr)}` : ''}</div>
            <pre class="ab-output">${esc(cout)}</pre>
          </div>
        </div>
      </details>
      <div style="height:8px"></div>
    `;
  }

  root.innerHTML = html;
}

// ── Colored diff renderer ──────────────────────────────────────────────
function renderColoredDiff(rawText, targetEl) {
  if (!targetEl) return;
  targetEl.innerHTML = '';
  for (const line of rawText.split('\n')) {
    const span = document.createElement('span');
    span.textContent = line;
    if (line.startsWith('+') && !line.startsWith('+++')) span.className = 'dl-add';
    else if (line.startsWith('-') && !line.startsWith('---')) span.className = 'dl-del';
    else if (line.startsWith('@@')) span.className = 'dl-hdr';
    else span.className = 'dl-ctx';
    targetEl.appendChild(span);
    targetEl.appendChild(document.createTextNode('\n'));
  }
}

// ── Event listeners ────────────────────────────────────────────────────

document.getElementById('runSuiteBtn').addEventListener('click', () =>
  runSuite().catch(e => { document.getElementById('status').textContent = 'Error: ' + e.message; })
);

document.getElementById('userTemplate').addEventListener('input', () => schedulePreview());

// Clicking read-only system prompt focuses AI input
document.getElementById('systemPrompt').addEventListener('click', () => {
  if (!previewPillId) document.getElementById('aiChangeRequest').focus();
});

document.getElementById('aiProposeBtn').addEventListener('click', () =>
  aiPropose().catch(e => {
    document.getElementById('aiEditStatus').textContent = 'Error';
    document.getElementById('aiError').textContent = e.message;
  })
);

document.getElementById('aiApplyBtn').addEventListener('click', () =>
  aiApply().catch(e => {
    document.getElementById('aiEditStatus').textContent = 'Error';
    document.getElementById('aiError').textContent = e.message;
  })
);

document.getElementById('aiDiscardBtn').addEventListener('click', () => {
  clearAiProposal();
  document.getElementById('aiEditStatus').textContent = '';
});



document.getElementById('aiChangeRequest').addEventListener('input', () => {
  document.getElementById('aiApplyBtn').disabled = true;
  // W5: keep propose button enabled only when input has text
  const val = document.getElementById('aiChangeRequest').value.trim();
  document.getElementById('aiProposeBtn').disabled = !val;
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

// Compare modal
document.getElementById('compareBaseBtn').addEventListener('click', openCompareModal);
document.getElementById('compareModalCloseBtn').addEventListener('click', closeCompareModal);
document.getElementById('compareModal').addEventListener('click', (e) => {
  if (e.target === document.getElementById('compareModal')) closeCompareModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeCompareModal(); exitPreviewMode(); }
});

// Version bar close button
document.getElementById('sysVersionBarClose').addEventListener('click', exitPreviewMode);

// Compare modal action buttons
document.getElementById('compareDeleteBtn').addEventListener('click', async () => {
  const btn = document.getElementById('compareDeleteBtn');
  if (!selectedComparePillId) return;
  btn.disabled = true;
  btn.textContent = 'Deleting\u2026';
  const errEl = document.getElementById('compareModalError');
  if (errEl) errEl.textContent = '';
  try {
    await aiDeleteVersion(selectedComparePillId);
    closeCompareModal();
    setPromoteStatus('Version deleted');
  } catch (e) {
    if (errEl) errEl.textContent = e.message;
    btn.disabled = false;
    btn.textContent = 'Delete version';
  }
});
document.getElementById('compareResetBtn').addEventListener('click', () => {
  closeCompareModal();
  aiReset().catch(e => { document.getElementById('aiError').textContent = e.message; });
});
document.getElementById('comparePublishBtn').addEventListener('click', () => {
  closeCompareModal();
  promoteToCanonical().catch(e => { document.getElementById('aiEditStatus').textContent = e.message; });
});

// ── Boot ───────────────────────────────────────────────────────────────
// W5: propose button starts disabled until user types something
document.getElementById('aiProposeBtn').disabled = true;

loadApps().catch(e => {
  document.getElementById('status').textContent = 'Error: ' + e.message;
});

