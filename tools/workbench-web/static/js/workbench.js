let currentCandidate = null;
let models = [];
let aiLastProposal = null;
let lastTraceId = '';
let draftVersions = [];
let latestSuite = null;
let latestSuiteIsClean = false;

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

async function api(path, opts) {
  const res = await fetch(path, opts);
  const trace = res.headers.get('X-Trace-Id') || '';
  if (trace) {
    lastTraceId = trace;
    const el = document.getElementById('lastTraceId');
    if (el) el.textContent = trace;
  }
  if (!res.ok) {
    const t = await res.text();
    const base = t || ('HTTP ' + res.status);
    const suffix = (trace || lastTraceId) ? `\ntrace_id=${trace || lastTraceId}` : '';
    const logs = `\nlogs=/api/logs?tail=200`;
    throw new Error(base + suffix + logs);
  }
  return res;
}

function esc(s) {
  return (s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function nowUtcIso() {
  return new Date().toISOString();
}

function parseCandidateJson(text) {
  try {
    const obj = JSON.parse(text);
    return { ok: true, obj };
  } catch (e) {
    return { ok: false, error: e?.message || String(e) };
  }
}

function candidateFromFields() {
  const base = currentCandidate && typeof currentCandidate === 'object' ? currentCandidate : {};
  const prompts = { ...(base.prompts || {}) };

  const mode = document.getElementById('modeSelect').value;
  const key = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';
  prompts[key] = document.getElementById('systemPrompt').value || '';

  const userKey = MODE_TO_USER_TEMPLATE_KEY[mode];
  if (userKey) {
    prompts[userKey] = document.getElementById('userTemplate').value || '';
  }

  const version = parseInt(document.getElementById('versionInput').value, 10) || (base.version ?? 1) || 1;
  const ttlSeconds = parseInt(document.getElementById('ttlSecondsInput').value, 10) || (base.ttlSeconds ?? 3600) || 3600;
  const updatedAt = (document.getElementById('updatedAtInput').value || '').trim() || (base.updatedAt ?? '') || nowUtcIso();

  return {
    version,
    updatedAt,
    ttlSeconds,
    prompts,
  };
}

function syncFieldsFromCandidate(cand) {
  currentCandidate = cand;

  document.getElementById('versionInput').value = String(cand?.version ?? 1);
  document.getElementById('ttlSecondsInput').value = String(cand?.ttlSeconds ?? 3600);
  document.getElementById('updatedAtInput').value = String(cand?.updatedAt ?? '');

  const p = cand?.prompts || {};
  const mode = document.getElementById('modeSelect').value;
  const key = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';
  document.getElementById('systemPrompt').value = p[key] || '';

  const userKey = MODE_TO_USER_TEMPLATE_KEY[mode];
  document.getElementById('userTemplate').value = (userKey && p[userKey]) ? p[userKey] : '';

  document.getElementById('candidateJson').value = JSON.stringify(cand, null, 2);
  document.getElementById('jsonError').textContent = '';
  document.getElementById('jsonStatus').textContent = '';

  refreshAiTargetKeys();
  clearAiProposal();
}

function clearAiProposal() {
  aiLastProposal = null;
  const diffEl = document.getElementById('aiDiff');
  if (diffEl) diffEl.innerHTML = '';
  const wrapEl = document.getElementById('aiDiffWrap');
  if (wrapEl) wrapEl.style.display = 'none';
  document.getElementById('aiError').textContent = '';
  document.getElementById('aiApplyBtn').disabled = true;
}

function refreshAiTargetKeys() {
  const sel = document.getElementById('aiTargetKey');
  const prev = sel.value;

  const keys = Object.keys((currentCandidate && currentCandidate.prompts) ? currentCandidate.prompts : {}).sort();
  sel.innerHTML = '';
  for (const k of keys) {
    const opt = document.createElement('option');
    opt.value = k;
    opt.textContent = k;
    sel.appendChild(opt);
  }

  const mode = document.getElementById('modeSelect').value;
  const defaultKey = MODE_TO_PROMPT_KEY[mode] || (keys[0] || '');

  if (prev && keys.includes(prev)) {
    sel.value = prev;
  } else if (defaultKey && keys.includes(defaultKey)) {
    sel.value = defaultKey;
  } else if (keys.length) {
    sel.value = keys[0];
  }
}

function aiNotesFromProposal(p) {
  if (!p || typeof p !== 'object') return '';
  const lines = [];
  if (typeof p.status === 'string') lines.push('status: ' + p.status);
  if (typeof p.selfCheck === 'boolean') lines.push('selfCheck: ' + String(p.selfCheck));
  if (typeof p.rationale === 'string' && p.rationale.trim()) {
    lines.push('\nRationale:\n' + p.rationale.trim());
  }
  const warnings = Array.isArray(p.warnings) ? p.warnings : [];
  if (warnings.length) {
    lines.push('\nWarnings:\n- ' + warnings.map(w => String(w)).join('\n- '));
  }
  if (typeof p.refusalReason === 'string' && p.refusalReason.trim()) {
    lines.push('\nRefusal:\n' + p.refusalReason.trim());
  }
  return lines.join('\n');
}

function setAiAppliedInfo(text) {
  const el = document.getElementById('aiAppliedInfo');
  if (!el) return;
  el.textContent = text || '';
}

function setPromoteStatus(text) {
  const el = document.getElementById('promoteStatus');
  if (!el) return;
  el.textContent = text || '';
}

function suiteLine(suite) {
  if (!suite || typeof suite !== 'object') return '';
  const runId = suite.runId ? String(suite.runId) : '';
  const ranAt = suite.ranAt ? String(suite.ranAt) : '';
  const isClean = suite.isClean === true;
  const tag = isClean ? 'clean' : 'not clean';
  const bits = [];
  if (runId) bits.push('runId=' + runId);
  if (ranAt) bits.push('at=' + ranAt);
  bits.push(tag);
  return bits.join(' | ');
}

async function refreshDrafts() {
  const appId = document.getElementById('appSelect').value;
  const sel = document.getElementById('draftSelect');
  const meta = document.getElementById('draftMeta');
  const restoreBtn = document.getElementById('draftRestoreBtn');
  const promoteBtn = document.getElementById('promoteBtn');

  if (!sel || !meta || !restoreBtn || !promoteBtn) return;

  const prevSelectedId = (sel && sel.value) ? String(sel.value) : '';

  document.getElementById('aiError').textContent = '';
  const res = await (await api('/api/drafts?appId=' + encodeURIComponent(appId))).json();
  draftVersions = res.versions || [];
  latestSuite = res.latestSuite || null;
  latestSuiteIsClean = res.latestSuiteIsClean === true;

  // Filter to only snapshots matching the current mode (opener / app_chat / reg_chat).
  const currentMode = document.getElementById('modeSelect').value;
  const modePrefix = (MODE_TO_PROMPT_KEY[currentMode] || '').replace('System', '');
  const visibleVersions = modePrefix
    ? draftVersions.filter(v => !v.targetKey || String(v.targetKey).startsWith(modePrefix))
    : draftVersions;

  sel.innerHTML = '';
  const opt0 = document.createElement('option');
  opt0.value = '';
  opt0.textContent = visibleVersions.length ? 'Select an edit…' : 'No edits yet';
  sel.appendChild(opt0);

  for (const v of visibleVersions) {
    const opt = document.createElement('option');
    opt.value = v.id || '';
    const when = v.savedAt ? String(v.savedAt) : '';
    const req = v.changeRequest ? String(v.changeRequest).trim() : '';
    const key = v.targetKey ? String(v.targetKey) : '';
    const reason = v.reason ? String(v.reason) : '';
    // Format timestamp as "Mar 2, 5:10 AM"
    let dateStr = '';
    try {
      if (when) {
        const dt = new Date(when);
        dateStr = dt.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
      }
    } catch (_) { dateStr = when.slice(0, 16); }
    // Use changeRequest as the label when available, fall back to key name
    const rawLabel = req || (key ? `Edited ${key}` : reason);
    const shortLabel = rawLabel.length > 55 ? rawLabel.slice(0, 52) + '\u2026' : rawLabel;
    opt.textContent = dateStr ? `${dateStr} \u2014 ${shortLabel}` : shortLabel;
    sel.appendChild(opt);
  }

  if (latestSuite && typeof latestSuite === 'object') {
    const suiteBits = [];
    if (latestSuite.runId) suiteBits.push('runId=' + String(latestSuite.runId));
    if (latestSuite.ranAt) suiteBits.push('at=' + String(latestSuite.ranAt));
    meta.textContent = `latest suite: ${latestSuiteIsClean ? 'clean' : 'not clean'}${suiteBits.length ? ' (' + suiteBits.join(' | ') + ')' : ''}`;
  } else {
    meta.textContent = 'latest suite: (none yet)';
  }
  restoreBtn.disabled = true;
  promoteBtn.disabled = !latestSuiteIsClean;
  setPromoteStatus('');

  // Populate Diff/Notes on launch by auto-selecting a draft.
  // Preference order: preserve prior selection → newest.
  const stillExists = prevSelectedId && visibleVersions.some(v => v && v.id === prevSelectedId);
  const toSelect = stillExists
    ? prevSelectedId
    : (visibleVersions[0] ? String(visibleVersions[0].id || '') : '');

  const canSelect = toSelect && visibleVersions.some(v => v && v.id === toSelect);
  if (canSelect) {
    sel.value = toSelect;
    await onDraftSelected();
  }
}

async function onDraftSelected() {
  const appId = document.getElementById('appSelect').value;
  const sel = document.getElementById('draftSelect');
  const restoreBtn = document.getElementById('draftRestoreBtn');
  const id = (sel && sel.value) ? String(sel.value) : '';
  restoreBtn.disabled = !id;
  document.getElementById('aiError').textContent = '';
  if (!id) {
    document.getElementById('aiDiffAdv').textContent = '';
    document.getElementById('aiNotesAdv').textContent = 'No edit snapshot selected.';
    return;
  }

  const targetKey = document.getElementById('aiTargetKey').value;
  if (!targetKey) return;

  try {
    const d = await (await api('/api/drafts/diff?appId=' + encodeURIComponent(appId) + '&id=' + encodeURIComponent(id) + '&targetKey=' + encodeURIComponent(targetKey))).json();
    document.getElementById('aiDiffAdv').textContent = d.diff || '';

    const ver = (draftVersions || []).find(x => x && x.id === id) || null;

    const PROMPT_LABELS = {
      openerSystem: 'Opener \u2014 System Prompt',
      appChatSystem: 'App Chat \u2014 System Prompt',
      regChatSystem: 'Reg Chat \u2014 System Prompt',
      openerUser: 'Opener \u2014 User Template',
      appChatUser: 'App Chat \u2014 User Template',
      regChatUser: 'Reg Chat \u2014 User Template',
    };

    const notes = [];

    // 1. What the user asked for
    const req = ver && ver.changeRequest ? String(ver.changeRequest).trim() : '';
    if (req) {
      notes.push('\u201c' + req + '\u201d');
      notes.push('');
    }

    // 2. Which prompt was changed
    const tk = ver && ver.targetKey ? String(ver.targetKey) : '';
    notes.push('Prompt: ' + (PROMPT_LABELS[tk] || tk || 'unknown'));

    // 3. When it was saved
    const savedAt = ver && ver.savedAt ? String(ver.savedAt) : '';
    if (savedAt) {
      try {
        const dt = new Date(savedAt);
        notes.push('Saved:  ' + dt.toLocaleString('en-US', {
          month: 'short', day: 'numeric', year: 'numeric',
          hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
        }));
      } catch (_) {
        notes.push('Saved:  ' + savedAt);
      }
    }

    // 4. Test result
    if (ver && ver.isClean === true) {
      notes.push('Tests:  \u2713 clean');
    } else {
      notes.push('Tests:  (not run on this snapshot)');
    }

    document.getElementById('aiNotesAdv').textContent = notes.join('\n');
  } catch (e) {
    document.getElementById('aiError').textContent = e.message || String(e);
  }
}

async function restoreDraft() {
  const sel = document.getElementById('draftSelect');
  const id = (sel && sel.value) ? String(sel.value) : '';
  if (!id) return;
  if (!confirm('Restore this snapshot into your local Candidate prompts?')) return;

  const appId = document.getElementById('appSelect').value;
  await api('/api/drafts/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId, id }),
  });

  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);
  schedulePreview();
  await refreshDrafts();
  document.getElementById('aiEditStatus').textContent = 'Restored snapshot';
}

async function promoteToCanonical() {
  if (!confirm('Publish Candidate → repo prompts file (prompts/<appId>.json) and clear local history?')) return;

  const appId = document.getElementById('appSelect').value;
  setPromoteStatus('Promoting…');
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

async function aiPropose() {
  clearAiProposal();
  setAiAppliedInfo('');
  const status = document.getElementById('aiEditStatus');

  const appId = document.getElementById('appSelect').value;
  const model = document.getElementById('modelSelect').value;
  const dryRun = !!document.getElementById('dryRun').checked;
  const targetKey = document.getElementById('aiTargetKey').value;
  const changeRequest = (document.getElementById('aiChangeRequest').value || '').trim();

  if (!targetKey) {
    document.getElementById('aiError').textContent = 'Pick a target key.';
    return;
  }
  if (!changeRequest) {
    document.getElementById('aiError').textContent = 'Enter a change request.';
    return;
  }

  // Show immediate in-bar loading feedback.
  const proposeBtn = document.getElementById('aiProposeBtn');
  const inputEl = document.getElementById('aiChangeRequest');
  const aiBar = inputEl.closest('.ai-bar');
  proposeBtn.classList.add('loading');
  proposeBtn.disabled = true;
  inputEl.disabled = true;
  if (aiBar) aiBar.classList.add('loading');

  // Open diff area immediately with pulsing placeholder.
  const diffEl = document.getElementById('aiDiff');
  const diffWrap = document.getElementById('aiDiffWrap');
  diffEl.innerHTML = '<div class="ai-thinking">Working on it…</div>';
  diffWrap.style.display = '';
  document.getElementById('aiApplyBtn').disabled = true;
  status.textContent = '';

  try {
    // Persist current editor fields so server reads the latest candidate text.
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
    const _notesEl = document.getElementById('aiNotes');
    if (_notesEl) _notesEl.textContent = aiNotesFromProposal(proposal);

    const ok = proposal && proposal.status === 'ok' && proposal.selfCheck === true;
    document.getElementById('aiApplyBtn').disabled = !ok;

    if (!ok) {
      const refusal = (proposal && typeof proposal.refusalReason === 'string') ? proposal.refusalReason.trim() : '';
      if (refusal) document.getElementById('aiError').textContent = refusal;
    }

    status.textContent = ok ? 'Ready to apply' : 'Not applyable';
  } finally {
    // Always restore the bar to interactive state.
    proposeBtn.classList.remove('loading');
    proposeBtn.disabled = false;
    inputEl.disabled = false;
    if (aiBar) aiBar.classList.remove('loading');
  }
}

async function aiApply() {
  const status = document.getElementById('aiEditStatus');
  const proposal = aiLastProposal;
  if (!proposal || proposal.status !== 'ok' || proposal.selfCheck !== true) {
    document.getElementById('aiError').textContent = 'No applyable proposal.';
    return;
  }

  status.textContent = 'Applying…';
  document.getElementById('aiError').textContent = '';

  const appId = document.getElementById('appSelect').value;
  const model = document.getElementById('modelSelect').value;
  const payload = {
    appId,
    model,
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

  const mode = document.getElementById('modeSelect').value;
  const visibleSystemKey = MODE_TO_PROMPT_KEY[mode];
  const visibleUserKey = MODE_TO_USER_TEMPLATE_KEY[mode];
  const visibleHint = (proposal.targetKey === visibleSystemKey || proposal.targetKey === visibleUserKey)
    ? ''
    : ` (note: this key is not shown in the current mode editor)`;

  const when = (applyRes && typeof applyRes.updatedAt === 'string' && applyRes.updatedAt) ? applyRes.updatedAt : (cand && cand.updatedAt ? String(cand.updatedAt) : '');
  const trace = (applyRes && typeof applyRes.traceId === 'string' && applyRes.traceId) ? applyRes.traceId : (lastTraceId || '');
  const tracePart = trace ? ` | trace_id=${trace}` : '';
  const whenPart = when ? ` at ${when}` : '';
  setAiAppliedInfo(`Applied ${proposal.targetKey}${whenPart}${tracePart} — ${verified ? 'VERIFIED' : 'NOT VERIFIED'}${visibleHint}`);

  clearAiProposal();
  schedulePreview();

  // Auto-run the suite to validate the change (dry-run aware).
  status.textContent = 'Applied; running suite…';
  await runSuite();
  status.textContent = 'Applied + suite done';
  await refreshDrafts();
}

async function aiUndo() {
  clearAiProposal();
  const status = document.getElementById('aiEditStatus');
  status.textContent = 'Undoing…';
  const appId = document.getElementById('appSelect').value;
  await api('/api/edit/undo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId }),
  });
  const cand = await (await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId))).json();
  syncFieldsFromCandidate(cand);
  schedulePreview();
  status.textContent = 'Undone';
  await refreshDrafts();
}

async function aiReset() {
  if (!confirm('Reset candidate prompts back to canonical?')) return;
  clearAiProposal();
  const status = document.getElementById('aiEditStatus');
  status.textContent = 'Resetting…';
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

function syncJsonFromFields() {
  const cand = candidateFromFields();
  document.getElementById('candidateJson').value = JSON.stringify(cand, null, 2);
  document.getElementById('jsonError').textContent = '';
  document.getElementById('jsonStatus').textContent = 'Synced from editor fields.';
  currentCandidate = cand;
  return cand;
}

function syncFieldsFromJson() {
  const text = document.getElementById('candidateJson').value;
  const parsed = parseCandidateJson(text);
  if (!parsed.ok) {
    document.getElementById('jsonError').textContent = parsed.error;
    document.getElementById('jsonStatus').textContent = 'Invalid JSON.';
    return null;
  }
  document.getElementById('jsonError').textContent = '';
  document.getElementById('jsonStatus').textContent = 'Loaded JSON into fields.';
  syncFieldsFromCandidate(parsed.obj);
  return parsed.obj;
}

function formatJson() {
  const text = document.getElementById('candidateJson').value;
  const parsed = parseCandidateJson(text);
  if (!parsed.ok) {
    document.getElementById('jsonError').textContent = parsed.error;
    document.getElementById('jsonStatus').textContent = 'Invalid JSON.';
    return;
  }
  document.getElementById('candidateJson').value = JSON.stringify(parsed.obj, null, 2);
  document.getElementById('jsonError').textContent = '';
  document.getElementById('jsonStatus').textContent = 'Formatted.';
}

function validateJson() {
  const text = document.getElementById('candidateJson').value;
  const parsed = parseCandidateJson(text);
  if (!parsed.ok) {
    document.getElementById('jsonError').textContent = parsed.error;
    document.getElementById('jsonStatus').textContent = 'Invalid JSON.';
    return false;
  }

  const obj = parsed.obj;
  const errs = [];
  if (typeof obj?.version !== 'number') errs.push('version must be a number');
  if (typeof obj?.updatedAt !== 'string' || !obj.updatedAt.trim()) errs.push('updatedAt must be a non-empty string');
  if (typeof obj?.ttlSeconds !== 'number') errs.push('ttlSeconds must be a number');
  if (typeof obj?.prompts !== 'object') errs.push('prompts must be an object');

  if (errs.length) {
    document.getElementById('jsonError').textContent = errs.join(' | ');
    document.getElementById('jsonStatus').textContent = 'Invalid schema.';
    return false;
  }

  document.getElementById('jsonError').textContent = '';
  document.getElementById('jsonStatus').textContent = 'OK.';
  return true;
}

function money(n) {
  if (n === null || n === undefined || !Number.isFinite(n)) return '';
  return '$' + n.toFixed(6);
}

function fmtRate(n) {
  if (n === null || n === undefined || !Number.isFinite(n)) return '';
  return '$' + n.toFixed(3);
}

function modelLabel(m) {
  const tag = m.isLatest ? ' (latest)' : '';
  return `${m.model}${tag} — in ${fmtRate(m.inputPer1M)} / cached ${fmtRate(m.cachedInputPer1M)} / out ${fmtRate(m.outputPer1M)}`;
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
    opt.value = m;
    opt.textContent = m;
    modeSelect.appendChild(opt);
  }

  modeSelect.addEventListener('change', () => {
    if (currentCandidate) syncFieldsFromCandidate(currentCandidate);
    loadFixtures().catch(() => { });
    refreshDrafts().catch(() => { });
  });

  const modelSelect = document.getElementById('modelSelect');
  const desired = (cfg.defaultModel || 'gpt-5-mini').trim();
  const has = [...modelSelect.options].some(o => o.value === desired);
  modelSelect.value = has ? desired : (modelSelect.options[0]?.value || desired);

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
  optAll.value = '';
  optAll.textContent = 'All fixtures';
  sel.appendChild(optAll);

  for (const fx of (res.fixtures || [])) {
    const opt = document.createElement('option');
    opt.value = fx.name || '';
    opt.textContent = fx.name + (fx.kind ? ` (${fx.kind})` : '');
    sel.appendChild(opt);
  }

  sel.onchange = () => schedulePreview();
}

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
    setPreviewText('baselinePreviewSystem', '');
    setPreviewText('baselinePreviewUser', '');
    setPreviewText('candidatePreviewSystem', '');
    setPreviewText('candidatePreviewUser', '');
    return;
  }

  status.textContent = 'Rendering…';

  const appId = document.getElementById('appSelect').value;
  const mode = document.getElementById('modeSelect').value;
  const systemPrompt = document.getElementById('systemPrompt').value || '';
  const userTemplate = document.getElementById('userTemplate').value || '';

  const payload = { appId, mode, fixture, systemPrompt, userTemplate };
  const res = await (await api('/api/compose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })).json();

  setPreviewText('baselinePreviewSystem', res?.baseline?.system || '');
  setPreviewText('baselinePreviewUser', res?.baseline?.user || '');
  setPreviewText('candidatePreviewSystem', res?.candidate?.system || '');
  setPreviewText('candidatePreviewUser', res?.candidate?.user || '');

  status.textContent = `OK: ${res?.fixture?.name || fixture}`;
}

async function runSuite() {
  const status = document.getElementById('status');
  status.textContent = 'Running suite…';

  const appId = document.getElementById('appSelect').value;
  const mode = document.getElementById('modeSelect').value;
  const model = document.getElementById('modelSelect').value;
  const dryRun = !!document.getElementById('dryRun').checked;
  const maxFixtures = parseInt(document.getElementById('maxFixturesInput').value, 10) || 0;
  const fixture = (document.getElementById('fixtureSelect').value || '').trim();

  // Ensure updatedAt is set and sync JSON from field editor.
  document.getElementById('updatedAtInput').value = nowUtcIso();
  const candidateObj = syncJsonFromFields();
  const candidateJson = JSON.stringify(candidateObj);
  await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: candidateJson });

  const payload = { appId, mode, model, dryRun, maxFixtures, baselineSource: 'local_file' };
  if (fixture) payload.fixture = fixture;

  const run = await (await api('/api/run/ab', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })).json();

  status.textContent = 'Done';
  renderSuiteResults(run);
  await refreshDrafts();
}

async function runTune() {
  const status = document.getElementById('tuneStatus');
  status.textContent = 'Running…';

  const appId = document.getElementById('appSelect').value;
  const mode = document.getElementById('modeSelect').value;
  const model = document.getElementById('modelSelect').value;
  const dryRun = !!document.getElementById('dryRun').checked;
  const systemPrompt = document.getElementById('systemPrompt').value || '';
  const userPrompt = document.getElementById('userPrompt').value || '';

  // Ensure updatedAt is set and sync JSON from field editor.
  document.getElementById('updatedAtInput').value = nowUtcIso();
  const candidateObj = syncJsonFromFields();
  const candidateJson = JSON.stringify(candidateObj);
  await api('/api/candidate-prompts?appId=' + encodeURIComponent(appId), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: candidateJson });

  const payload = { appId, mode, model, systemPrompt, userPrompt, dryRun };
  const run = await (await api('/api/run/tune', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })).json();

  status.textContent = 'Done';
  renderResults(run);
}

function renderSuiteResults(run) {
  const root = document.getElementById('results');

  const reportPath = run.reportPath || '';
  const reportLink = reportPath ? `<a href="${esc(reportPath)}" target="_blank" rel="noreferrer">ab_report.html</a>` : '';

  const items = run.items || [];
  const totals = run.totals || {};

  const totalsLine = `Tokens — live in/out: ${esc(String(totals.baselineInputTokens ?? 0))}/${esc(String(totals.baselineOutputTokens ?? 0))} &nbsp;·&nbsp; draft in/out: ${esc(String(totals.candidateInputTokens ?? 0))}/${esc(String(totals.candidateOutputTokens ?? 0))}`;

  let html = `
        <div class="muted">Report: ${reportLink || '(not available)'} &nbsp;·&nbsp; ${totalsLine}</div>
        <div style="height:10px"></div>
      `;

  for (const it of items) {
    const name = it.fixture || '';
    const inp = it.baselineInput || it.candidateInput || '';
    const bout = it.baselineOutput || '';
    const cout = it.candidateOutput || '';
    const bflags = Array.isArray(it.baselineFlags) ? it.baselineFlags.join(',') : '';
    const cflags = Array.isArray(it.candidateFlags) ? it.candidateFlags.join(',') : '';
    const berr = it.baselineError || '';
    const cerr = it.candidateError || '';

    html += `
          <details class="card ab-fixture" open>
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

function renderResults(run) {
  const root = document.getElementById('results');
  const u = run.usage || {};
  const p = run.pricing || {};
  const c = run.cost || {};

  const tokensLine = `Tokens — in/out/total/cached: ${esc(String(u.inputTokens ?? 0))} / ${esc(String(u.outputTokens ?? 0))} / ${esc(String(u.totalTokens ?? 0))} / ${esc(String(u.cachedTokens ?? 0))}`;
  const pricingLine = `Pricing ($/1M) — in ${esc(String(p.inputPer1M ?? ''))} / cached ${esc(String(p.cachedInputPer1M ?? ''))} / out ${esc(String(p.outputPer1M ?? ''))}`;
  const costLine = `Cost — input ${esc(money(c.inputUsd))} | cached ${esc(money(c.cachedInputUsd))} | output ${esc(money(c.outputUsd))} | total ${esc(money(c.totalUsd))}`;

  root.innerHTML = `
        <div class="muted">Model: ${esc(run.model || '')}<br/>${tokensLine}<br/>${pricingLine}<br/>${costLine}</div>
        <div style="height:10px"></div>
        <div><strong>OUTPUT</strong><pre>${esc(run.outputText || '')}</pre></div>
      `;
}

document.getElementById('formatJsonBtn').addEventListener('click', () => {
  formatJson();
});

document.getElementById('validateJsonBtn').addEventListener('click', () => {
  validateJson();
});

// Keep Advanced JSON and field editor in sync (best-effort).
document.getElementById('candidateJson').addEventListener('blur', () => {
  syncFieldsFromJson();
});

document.getElementById('runSuiteBtn').addEventListener('click', () => runSuite().catch(e => {
  document.getElementById('status').textContent = 'Error: ' + e.message;
}));

document.getElementById('runTuneBtn').addEventListener('click', () => runTune().catch(e => {
  document.getElementById('tuneStatus').textContent = 'Error: ' + e.message;
}));

document.getElementById('systemPrompt').addEventListener('input', () => schedulePreview());
document.getElementById('userTemplate').addEventListener('input', () => schedulePreview());

document.getElementById('aiProposeBtn').addEventListener('click', () => aiPropose().catch(e => {
  document.getElementById('aiEditStatus').textContent = 'Error';
  document.getElementById('aiError').textContent = e.message;
}));
document.getElementById('aiApplyBtn').addEventListener('click', () => aiApply().catch(e => {
  document.getElementById('aiEditStatus').textContent = 'Error';
  document.getElementById('aiError').textContent = e.message;
}));
document.getElementById('aiUndoBtn').addEventListener('click', () => aiUndo().catch(e => {
  document.getElementById('aiEditStatus').textContent = 'Error';
  document.getElementById('aiError').textContent = e.message;
}));
document.getElementById('aiResetBtn').addEventListener('click', () => aiReset().catch(e => {
  document.getElementById('aiEditStatus').textContent = 'Error';
  document.getElementById('aiError').textContent = e.message;
}));

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
});
document.getElementById('draftSelect').addEventListener('change', () => onDraftSelected().catch(e => {
  document.getElementById('aiError').textContent = e.message;
}));
document.getElementById('draftRefreshBtn').addEventListener('click', () => refreshDrafts().catch(e => {
  document.getElementById('aiError').textContent = e.message;
}));
document.getElementById('draftRestoreBtn').addEventListener('click', () => restoreDraft().catch(e => {
  document.getElementById('aiError').textContent = e.message;
}));
document.getElementById('promoteBtn').addEventListener('click', () => promoteToCanonical().catch(e => {
  setPromoteStatus('Error');
  document.getElementById('aiError').textContent = e.message;
}));
document.getElementById('aiChangeRequest').addEventListener('input', () => {
  // If user changes the request, old proposal is stale.
  document.getElementById('aiApplyBtn').disabled = true;
});

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

// ── AI target pill toggle ─────────────────────────────────────────────
function setAiTarget(which) {
  document.getElementById('aiTargetSysBtn').classList.toggle('active', which === 'sys');
  document.getElementById('aiTargetUserBtn').classList.toggle('active', which === 'user');
  const mode = document.getElementById('modeSelect').value;
  const sysKey = MODE_TO_PROMPT_KEY[mode] || 'openerSystem';
  const userKey = MODE_TO_USER_TEMPLATE_KEY[mode] || 'openerUser';
  const targetKey = which === 'sys' ? sysKey : userKey;
  const sel = document.getElementById('aiTargetKey');
  if ([...sel.options].some(o => o.value === targetKey)) {
    sel.value = targetKey;
    clearAiProposal();
    onDraftSelected().catch(() => { });
  }
}

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

loadApps().catch(e => {
  document.getElementById('status').textContent = 'Error: ' + e.message;
});
