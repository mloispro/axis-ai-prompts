# pylint: skip-file
# flake8: noqa
# ruff: noqa
# pyright: ignore

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for _ in range(10):
        if (cur / "prompts").is_dir() and (cur / "fixtures").is_dir():
            return cur
        cur = cur.parent
    raise RuntimeError(
        "Could not locate repo root (expected folders 'prompts/' and 'fixtures/')."
    )


REPO_ROOT = _find_repo_root(Path(__file__))
WEB_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WEB_ROOT / "static"

PROMPTS_DIR = REPO_ROOT / "prompts"
OUT_DIR = WEB_ROOT / "out"
FIXTURES_DIR = REPO_ROOT / "fixtures"

LOG_DIR = OUT_DIR / "logs"
LOG_FILE = LOG_DIR / "workbench.log"


def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("workbench.web")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = RotatingFileHandler(
            str(LOG_FILE), maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s")
        fmt.converter = time.gmtime  # type: ignore[attr-defined]
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


LOG = _setup_logging()

# Candidate + optional local baseline live under tools/workbench-web/state/ for local iteration (gitignored).
STATE_DIR = WEB_ROOT / "state"
CANDIDATES_DIR = STATE_DIR / "candidates"
BASELINES_DIR = STATE_DIR / "baselines"
HISTORY_DIR = STATE_DIR / "history"


def _candidate_path(app_id: str) -> Path:
    return CANDIDATES_DIR / f"{app_id}.json"


def _baseline_path(app_id: str) -> Path:
    return BASELINES_DIR / f"{app_id}.json"


def _history_path(app_id: str) -> Path:
    return HISTORY_DIR / f"{app_id}.json"


def _ensure_state_dirs() -> None:
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _read_history(app_id: str) -> List[Dict[str, Any]]:
    p = _history_path(app_id)
    if not p.exists():
        return []
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _write_history(app_id: str, items: List[Dict[str, Any]]) -> None:
    p = _history_path(app_id)
    p.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _push_undo_snapshot(app_id: str, candidate_obj: Any, reason: str) -> None:
    """Persist a candidate snapshot for Undo.

    Stored in state/history/<appId>.json with kind='undo'.
    """

    if not isinstance(candidate_obj, dict):
        return

    items = _read_history(app_id)
    items.append(
        {
            "id": _new_id(),
            "kind": "undo",
            "savedAt": _utc_now_iso(),
            "reason": (reason or "").strip() or "snapshot",
            "candidate": candidate_obj,
        }
    )
    items = items[-50:]
    _write_history(app_id, items)


def _push_draft_version(
    app_id: str,
    candidate_obj: Any,
    *,
    kind: str = "draft",
    reason: str,
    target_key: str = "",
    model: str = "",
    change_request: str = "",
    trace_id: str = "",
    notes: str = "",
    suite: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist a bounded list of local draft versions for browsing/restoring."""

    if not isinstance(candidate_obj, dict):
        return

    entry: Dict[str, Any] = {
        "id": _new_id(),
        "kind": (kind or "draft").strip() or "draft",
        "savedAt": _utc_now_iso(),
        "reason": (reason or "").strip() or "snapshot",
        "candidate": candidate_obj,
    }
    if (target_key or "").strip():
        entry["targetKey"] = target_key.strip()
    if (model or "").strip():
        entry["model"] = model.strip()
    if (change_request or "").strip():
        entry["changeRequest"] = change_request.strip()
    if (trace_id or "").strip():
        entry["traceId"] = trace_id.strip()
    if (notes or "").strip():
        entry["notes"] = notes.strip()
    if isinstance(suite, dict) and suite:
        entry["suite"] = suite

    items = _read_history(app_id)
    items.append(entry)
    items = items[-50:]
    _write_history(app_id, items)


def _draft_entries(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("kind") or "") == "draft":
            out.append(it)
    return out


def _suite_entries(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return suite snapshots, newest-last.

    Back-compat: earlier versions stored suite runs as kind='draft' with reason='run_suite'.
    """

    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "")
        if kind == "suite":
            out.append(it)
            continue
        if kind == "draft" and str(it.get("reason") or "") == "run_suite":
            out.append(it)
            continue
    return out


def _latest_suite_entry(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    suites = _suite_entries(items)
    for it in reversed(suites):
        suite = it.get("suite") if isinstance(it, dict) else None
        if isinstance(suite, dict) and str(suite.get("runId") or ""):
            return it
    return None


def _compute_is_clean(entry: Dict[str, Any]) -> bool:
    suite = entry.get("suite") if isinstance(entry, dict) else None
    if not isinstance(suite, dict):
        return False
    if str(suite.get("status") or "") != "ok":
        return False
    flags = suite.get("flagsSummary")
    if not isinstance(flags, dict):
        return False
    empty_count = int(flags.get("empty_output") or 0)
    if empty_count > 0:
        return False
    mode = str(suite.get("mode") or "").strip()
    if mode == "opener":
        too_many = int(flags.get("too_many_lines_for_opener") or 0)
        if too_many > 0:
            return False
    return True


def _default_app_id() -> str:
    apps = _list_apps()
    if not apps:
        raise HTTPException(status_code=500, detail="No apps found")
    return str(apps[0].get("appId") or "").strip()


# Allow importing the engine module directly.
sys.path.insert(0, str(WEB_ROOT))

try:
    import engine as engine  # type: ignore
except Exception as e:  # pragma: no cover
    raise RuntimeError(f"Failed to import workbench engine: {e}")


# Optional: remote discovery of apps from an ai-prompts index.json
# In the single-repo model, default is local index.json file path.
AI_PROMPTS_INDEX_URL = os.getenv("AI_PROMPTS_INDEX_URL", "").strip()


def _fetch_json_url(url: str, timeout_s: int = 15) -> Any:
    req = urllib.request.Request(
        url, headers={"User-Agent": "ai-prompts-workbench/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _local_index_json_path() -> Path:
    return REPO_ROOT / "index.json"


def _try_list_apps_local_index() -> Optional[List[Dict[str, Any]]]:
    p = _local_index_json_path()
    if not p.exists():
        return None
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
        apps = idx.get("apps") if isinstance(idx, dict) else None
        if not isinstance(apps, list) or not apps:
            return None
        out: List[Dict[str, Any]] = []
        for a in apps:
            if not isinstance(a, dict):
                continue
            app_id = (a.get("appId") or "").strip()
            if not app_id:
                continue
            out.append(
                {
                    "appId": app_id,
                    "displayName": (a.get("displayName") or app_id).strip(),
                }
            )
        return out or None
    except Exception:
        return None


def _try_get_app_local_index(app_id: str) -> Optional[Dict[str, Any]]:
    p = _local_index_json_path()
    if not p.exists():
        return None
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
        apps = idx.get("apps") if isinstance(idx, dict) else None
        if not isinstance(apps, list):
            return None

        for a in apps:
            if not isinstance(a, dict):
                continue
            if (a.get("appId") or "").strip() != app_id:
                continue

            prompts_path = (a.get("promptsPath") or f"prompts/{app_id}.json").lstrip(
                "/"
            )
            prompts_file = REPO_ROOT / prompts_path
            default_remote_url = (a.get("defaultRemotePromptsUrl") or "").strip()
            if not default_remote_url:
                # Construct raw URL if repo info is provided in env (optional).
                # Workbench still works without this; baseline can be local file.
                pass

            modes = a.get("modes")
            if not isinstance(modes, list) or not modes:
                modes = ["opener", "app_chat", "reg_chat"]

            return {
                "appId": app_id,
                "displayName": (a.get("displayName") or app_id).strip(),
                "defaultRemotePromptsUrl": default_remote_url,
                "defaultPromptsPath": str(prompts_file),
                "promptsPath": prompts_path,
                "modes": modes,
                "defaultModel": (a.get("defaultModel") or "gpt-5-mini").strip(),
            }

        return None
    except Exception:
        return None


def _try_list_apps_remote() -> Optional[List[Dict[str, Any]]]:
    if not AI_PROMPTS_INDEX_URL:
        return None
    try:
        idx = _fetch_json_url(AI_PROMPTS_INDEX_URL)
        apps = idx.get("apps") if isinstance(idx, dict) else None
        if not isinstance(apps, list) or not apps:
            return None
        out: List[Dict[str, Any]] = []
        for a in apps:
            if not isinstance(a, dict):
                continue
            app_id = (a.get("appId") or "").strip()
            if not app_id:
                continue
            out.append(
                {
                    "appId": app_id,
                    "displayName": (a.get("displayName") or app_id).strip(),
                }
            )
        return out or None
    except Exception:
        return None


def _try_get_app_remote(app_id: str) -> Optional[Dict[str, Any]]:
    if not AI_PROMPTS_INDEX_URL:
        return None
    try:
        idx = _fetch_json_url(AI_PROMPTS_INDEX_URL)
        apps = idx.get("apps") if isinstance(idx, dict) else None
        if not isinstance(apps, list):
            return None

        for a in apps:
            if not isinstance(a, dict):
                continue
            if (a.get("appId") or "").strip() != app_id:
                continue

            prompts_path = (a.get("promptsPath") or f"prompts/{app_id}.json").lstrip(
                "/"
            )
            prompts_file = REPO_ROOT / prompts_path
            modes = a.get("modes")
            if not isinstance(modes, list) or not modes:
                modes = ["opener", "app_chat", "reg_chat"]

            return {
                "appId": app_id,
                "displayName": (a.get("displayName") or app_id).strip(),
                "defaultRemotePromptsUrl": (
                    a.get("defaultRemotePromptsUrl") or ""
                ).strip(),
                "defaultPromptsPath": str(prompts_file),
                "promptsPath": prompts_path,
                "modes": modes,
                "defaultModel": (a.get("defaultModel") or "gpt-5-mini").strip(),
            }

        return None
    except Exception:
        return None


def _list_apps() -> List[Dict[str, Any]]:
    remote = _try_list_apps_remote()
    if remote is not None:
        return remote

    local = _try_list_apps_local_index()
    if local is not None:
        return local

    # Fallback: list prompts/*.json
    apps: List[Dict[str, Any]] = []
    if PROMPTS_DIR.exists():
        for p in sorted(PROMPTS_DIR.glob("*.json")):
            apps.append({"appId": p.stem, "displayName": p.stem})
    return apps


def _get_app(app_id: str) -> Dict[str, Any]:
    remote = _try_get_app_remote(app_id)
    if remote is not None:
        return remote

    local = _try_get_app_local_index(app_id)
    if local is not None:
        return local

    p = PROMPTS_DIR / f"{app_id}.json"
    if p.exists():
        return {
            "appId": app_id,
            "displayName": app_id,
            "defaultRemotePromptsUrl": "",
            "defaultPromptsPath": str(p),
            "promptsPath": f"prompts/{app_id}.json",
            "modes": ["opener", "app_chat", "reg_chat"],
            "defaultModel": "gpt-5-mini",
        }

    raise HTTPException(status_code=404, detail="Unknown appId")


def _latest_out_dir() -> Optional[Path]:
    if not OUT_DIR.exists():
        return None
    # Only consider actual run directories created by the engine.
    # The launcher also writes logs under out/launcher/ which should be ignored.
    runs: List[Path] = []
    for p in OUT_DIR.iterdir():
        if not p.is_dir():
            continue
        if (p / "run.json").exists():
            runs.append(p)

    if runs:
        return max(runs, key=lambda p: p.stat().st_mtime)

    # Back-compat fallback: if nothing matches, return any directory.
    dirs = [p for p in OUT_DIR.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


app = FastAPI(title="Prompt Workbench Web", docs_url=None, redoc_url=None)


def _new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


@app.middleware("http")
async def add_trace_and_log(request: Request, call_next):
    trace_id = _new_trace_id()
    request.state.trace_id = trace_id
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as e:  # pragma: no cover
        ms = int((time.time() - start) * 1000)
        LOG.error(
            "http.error trace_id=%s method=%s path=%s ms=%d err=%r",
            trace_id,
            request.method,
            request.url.path,
            ms,
            str(e),
        )
        raise
    ms = int((time.time() - start) * 1000)
    LOG.info(
        "http.request trace_id=%s method=%s path=%s status=%s ms=%d",
        trace_id,
        request.method,
        request.url.path,
        getattr(response, "status_code", "?"),
        ms,
    )
    try:
        response.headers["X-Trace-Id"] = trace_id
    except Exception:
        pass
    return response


@app.get("/api/logs")
def api_logs(tail: int = 200) -> JSONResponse:
    """Return the last N lines of the workbench log.

    Local-only debugging aid so UI errors can be correlated to server traces.
    """

    tail = max(1, min(int(tail or 200), 2000))
    if not LOG_FILE.exists():
        return JSONResponse({"lines": [], "path": str(LOG_FILE)})
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return JSONResponse({"lines": lines[-tail:], "path": str(LOG_FILE)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}")


@dataclass(frozen=True)
class ModelPricing:
    model: str
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float
    is_latest: bool = False


# Prices per 1M tokens (input / cached input / output).
# Source: OpenAI Developers pricing table.
_MODEL_CATALOG: List[ModelPricing] = [
    ModelPricing(
        model="gpt-5.2",
        input_per_1m=1.75,
        cached_input_per_1m=0.175,
        output_per_1m=14.00,
        is_latest=True,
    ),
    ModelPricing(
        model="gpt-5.1",
        input_per_1m=1.25,
        cached_input_per_1m=0.125,
        output_per_1m=10.00,
        is_latest=True,
    ),
    ModelPricing(
        model="gpt-5-mini",
        input_per_1m=0.25,
        cached_input_per_1m=0.025,
        output_per_1m=2.00,
    ),
    ModelPricing(
        model="gpt-5-nano",
        input_per_1m=0.05,
        cached_input_per_1m=0.005,
        output_per_1m=0.40,
    ),
    ModelPricing(
        model="gpt-4.1",
        input_per_1m=2.00,
        cached_input_per_1m=0.50,
        output_per_1m=8.00,
    ),
    ModelPricing(
        model="gpt-4.1-mini",
        input_per_1m=0.40,
        cached_input_per_1m=0.10,
        output_per_1m=1.60,
    ),
    ModelPricing(
        model="gpt-4.1-nano",
        input_per_1m=0.10,
        cached_input_per_1m=0.025,
        output_per_1m=0.40,
    ),
    ModelPricing(
        model="gpt-4o",
        input_per_1m=2.50,
        cached_input_per_1m=1.25,
        output_per_1m=10.00,
    ),
    ModelPricing(
        model="gpt-4o-mini",
        input_per_1m=0.15,
        cached_input_per_1m=0.075,
        output_per_1m=0.60,
    ),
]


def _pick_models_for_dropdown() -> List[ModelPricing]:
    # Keep the dropdown intentionally small (4 options) and aligned to the
    # recommended workflow:
    # - default: gpt-5-mini
    # - cheapest/bulk: gpt-5-nano
    # - quality fallback: gpt-5.2
    # - additional latest option: gpt-5.1
    preferred = ["gpt-5-mini", "gpt-5-nano", "gpt-5.2", "gpt-5.1"]
    by_name = {m.model: m for m in _MODEL_CATALOG}
    out: List[ModelPricing] = []
    for name in preferred:
        m = by_name.get(name)
        if m is not None:
            out.append(m)
    # Fallback: if catalog changes, keep at least 4 entries.
    if len(out) < 4:
        for m in _MODEL_CATALOG:
            if m.model not in {x.model for x in out}:
                out.append(m)
            if len(out) >= 4:
                break
    return out[:4]


def _pricing_by_model(model: str) -> Optional[ModelPricing]:
    model = (model or "").strip()
    for m in _MODEL_CATALOG:
        if m.model == model:
            return m
    return None


def _compute_cost_usd(usage: Dict[str, Any], pricing: ModelPricing) -> Dict[str, Any]:
    def _i(key: str) -> int:
        try:
            return int(usage.get(key) or 0)
        except Exception:
            return 0

    input_tokens = _i("inputTokens")
    output_tokens = _i("outputTokens")
    cached_tokens = _i("cachedTokens")
    cached_tokens = max(0, min(cached_tokens, input_tokens))
    non_cached_in = input_tokens - cached_tokens

    in_usd = (non_cached_in / 1_000_000.0) * pricing.input_per_1m
    cached_in_usd = (cached_tokens / 1_000_000.0) * pricing.cached_input_per_1m
    out_usd = (output_tokens / 1_000_000.0) * pricing.output_per_1m
    total = in_usd + cached_in_usd + out_usd
    return {
        "inputUsd": in_usd,
        "cachedInputUsd": cached_in_usd,
        "outputUsd": out_usd,
        "totalUsd": total,
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _list_fixture_files(*, app_id: str, mode: str) -> List[Dict[str, Any]]:
    mode = (mode or "").strip()
    if mode not in ("opener", "app_chat", "reg_chat"):
        raise HTTPException(status_code=400, detail=f"Unknown mode '{mode}'.")

    app_id = (app_id or "").strip() or _default_app_id()

    searched: List[Path] = []
    mode_dir = FIXTURES_DIR / app_id / mode
    searched.append(mode_dir)
    if app_id and not mode_dir.exists():
        mode_dir = FIXTURES_DIR / mode
        searched.append(mode_dir)

    if not mode_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Missing fixtures dir. Searched: {', '.join(str(p) for p in searched)}",
        )

    files = sorted(
        [
            p
            for p in list(mode_dir.glob("*.txt")) + list(mode_dir.glob("*.json"))
            if p.is_file()
        ]
    )

    items: List[Dict[str, Any]] = []
    for p in files:
        items.append(
            {
                "name": p.stem,
                "file": p.name,
                "kind": p.suffix.lstrip(".").lower(),
            }
        )
    return items


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/css/workbench.css")
def serve_css() -> FileResponse:
    return FileResponse(
        str(STATIC_DIR / "css" / "workbench.css"), media_type="text/css"
    )


@app.get("/js/workbench.js")
def serve_js() -> FileResponse:
    return FileResponse(
        str(STATIC_DIR / "js" / "workbench.js"), media_type="application/javascript"
    )


@app.get("/api/apps")
def api_apps() -> JSONResponse:
    return JSONResponse(_list_apps())


@app.get("/api/apps/{app_id}")
def api_app(app_id: str) -> JSONResponse:
    return JSONResponse(_get_app(app_id))


@app.get("/api/models")
def api_models() -> JSONResponse:
    models = []
    for m in _pick_models_for_dropdown():
        models.append(
            {
                "model": m.model,
                "inputPer1M": m.input_per_1m,
                "cachedInputPer1M": m.cached_input_per_1m,
                "outputPer1M": m.output_per_1m,
                "isLatest": bool(m.is_latest),
            }
        )
    return JSONResponse({"models": models})


@app.get("/api/fixtures")
def api_fixtures(appId: str = "", mode: str = "") -> JSONResponse:
    app_id = (appId or "").strip() or _default_app_id()
    mode = (mode or "").strip() or "opener"
    _ = _get_app(app_id)
    fixtures = _list_fixture_files(app_id=app_id, mode=mode)
    return JSONResponse({"appId": app_id, "mode": mode, "fixtures": fixtures})


@app.post("/api/compose")
def api_compose(payload: Dict[str, Any]) -> JSONResponse:
    """Render composed messages (baseline vs candidate) for a single fixture.

    This is intentionally no-network: it only loads prompt bundles + fixture files
    and renders the user template when the fixture is structured (.json).
    """

    app_id = (payload.get("appId") or "").strip() or _default_app_id()
    mode = (payload.get("mode") or "").strip() or "opener"
    fixture = (payload.get("fixture") or "").strip()
    candidate_system_override = (payload.get("systemPrompt") or "").rstrip()
    candidate_user_template_override = (payload.get("userTemplate") or "").rstrip()

    if not fixture:
        raise HTTPException(status_code=400, detail="fixture is required")

    cfg = _get_app(app_id)

    # Baseline bundle: canonical prompts file.
    baseline_path = Path(str(cfg.get("defaultPromptsPath") or "")).resolve()
    if not baseline_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Baseline prompts file not found: {baseline_path}",
        )
    baseline_bundle = engine.load_prompts_json_from_bytes(
        baseline_path.read_bytes(), source=str(baseline_path)
    )

    # Fixture file (supports .txt + .json).
    try:
        fixture_files = engine.load_fixture_files(
            FIXTURES_DIR, mode, app_id=app_id, only_fixture=fixture
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    fx = fixture_files[0]
    fx_kind = fx.suffix.lstrip(".").lower()

    baseline_system = engine.system_prompt_for_mode(baseline_bundle, mode)
    baseline_user_template = engine.user_template_for_mode(baseline_bundle, mode)

    # Candidate: for preview, prefer the live overrides from the editor.
    candidate_system = candidate_system_override
    candidate_user_template = candidate_user_template_override

    try:
        baseline_user = engine.render_fixture_user_prompt(
            fx, mode=mode, user_template=baseline_user_template
        )
        candidate_user = engine.render_fixture_user_prompt(
            fx, mode=mode, user_template=candidate_user_template
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        {
            "appId": app_id,
            "mode": mode,
            "fixture": {"name": fx.stem, "kind": fx_kind, "file": fx.name},
            "baseline": {"system": baseline_system, "user": baseline_user},
            "candidate": {"system": candidate_system, "user": candidate_user},
        }
    )


@app.get("/api/candidate-prompts")
def api_get_candidate(appId: str = "") -> JSONResponse:
    _ensure_state_dirs()
    app_id = (appId or "").strip() or _default_app_id()
    cfg = _get_app(app_id)

    path = _candidate_path(app_id)
    if not path.exists():
        # Initialize from the canonical prompts file for this app, when possible.
        src = Path(str(cfg.get("defaultPromptsPath") or ""))
        if src.exists():
            path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            path.write_text(
                json.dumps(
                    {"version": 1, "updatedAt": "", "ttlSeconds": 3600, "prompts": {}},
                    indent=2,
                ),
                encoding="utf-8",
            )

    cand_obj = _read_json(path)

    # Ensure candidate includes all canonical prompt keys so switching modes
    # always loads the real baseline prompt text for that mode.
    try:
        canonical_path = Path(str(cfg.get("defaultPromptsPath") or ""))
        if canonical_path.exists():
            canonical_obj = _read_json(canonical_path)
            canonical_prompts = (
                (canonical_obj.get("prompts") or {})
                if isinstance(canonical_obj, dict)
                else {}
            )

            if not isinstance(cand_obj, dict):
                cand_obj = {
                    "version": 1,
                    "updatedAt": "",
                    "ttlSeconds": 3600,
                    "prompts": {},
                }

            cand_prompts = cand_obj.get("prompts")
            if not isinstance(cand_prompts, dict):
                cand_prompts = {}
                cand_obj["prompts"] = cand_prompts

            changed = False
            if isinstance(canonical_prompts, dict):
                for k, v in canonical_prompts.items():
                    if not isinstance(k, str):
                        continue
                    if isinstance(v, str):
                        if k not in cand_prompts:
                            cand_prompts[k] = v
                            changed = True
                            continue

                        existing = cand_prompts.get(k)
                        existing_is_blank = (
                            existing is None
                            or (isinstance(existing, str) and not existing.strip())
                            or (not isinstance(existing, str))
                        )
                        if existing_is_blank and v.strip():
                            cand_prompts[k] = v
                            changed = True

            if changed:
                path.write_text(json.dumps(cand_obj, indent=2), encoding="utf-8")
    except Exception:
        # Best-effort only; never fail candidate load due to merge issues.
        pass

    return JSONResponse(cand_obj)


@app.put("/api/candidate-prompts")
def api_put_candidate(payload: Dict[str, Any], appId: str = "") -> JSONResponse:
    _ensure_state_dirs()
    app_id = (appId or "").strip() or _default_app_id()
    path = _candidate_path(app_id)

    # Validate shape minimally by reusing the engine loader.
    raw_bytes = json.dumps(payload).encode("utf-8")
    _ = engine.load_prompts_json_from_bytes(raw_bytes, source=str(path))

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.post("/api/edit/propose")
def api_edit_propose(payload: Dict[str, Any], request: Request) -> JSONResponse:
    """Propose a single-key prompt edit via OpenAI Structured Outputs.

    Dry-run mode returns a deterministic fake edit (no network).
    """

    _ensure_state_dirs()

    app_id = (payload.get("appId") or "").strip() or _default_app_id()
    model = (payload.get("model") or "").strip() or "gpt-5-mini"
    target_key = (payload.get("targetKey") or "").strip()
    change_request = (payload.get("changeRequest") or "").strip()
    dry_run = bool(payload.get("dryRun") or False)

    trace_id = getattr(getattr(request, "state", None), "trace_id", "") or ""
    LOG.info(
        "edit.propose trace_id=%s app_id=%s model=%s target_key=%s dry_run=%s",
        trace_id or "-",
        app_id,
        model,
        target_key,
        str(dry_run),
    )

    if not target_key:
        raise HTTPException(status_code=400, detail="targetKey is required")
    if not change_request:
        raise HTTPException(status_code=400, detail="changeRequest is required")

    # Load candidate prompts to provide current text.
    candidate_path = _candidate_path(app_id)
    if not candidate_path.exists():
        _ = api_get_candidate(appId=app_id)
    cand_obj = _read_json(candidate_path)

    prompts = cand_obj.get("prompts") if isinstance(cand_obj, dict) else None
    if not isinstance(prompts, dict):
        raise HTTPException(status_code=400, detail="candidate prompts are missing")

    current_text = prompts.get(target_key)
    if not isinstance(current_text, str):
        raise HTTPException(
            status_code=400, detail=f"targetKey '{target_key}' not found in prompts"
        )

    try:
        resp = engine.propose_prompt_edit(
            model=model,
            target_key=target_key,
            current_text=current_text,
            change_request=change_request,
            dry_run=dry_run,
            trace_id=trace_id,
        )
    except Exception as e:
        msg = str(e)
        LOG.error(
            "edit.propose.failed trace_id=%s app_id=%s model=%s target_key=%s err=%r",
            trace_id or "-",
            app_id,
            model,
            target_key,
            msg,
        )
        raise HTTPException(
            status_code=400,
            detail=f"{msg} | trace_id={trace_id or '-'} | logs=/api/logs",
        )

    updated_text = resp.get("updatedText") if isinstance(resp, dict) else None
    if not isinstance(updated_text, str):
        updated_text = ""

    diff = engine.unified_diff(
        current_text,
        updated_text,
        a_label=f"current:{target_key}",
        b_label=f"proposed:{target_key}",
    )

    return JSONResponse({"proposal": resp, "diff": diff, "currentText": current_text})


@app.post("/api/edit/apply")
def api_edit_apply(payload: Dict[str, Any], request: Request) -> JSONResponse:
    """Apply an edit to the candidate prompt bundle, with apply-time validation."""

    _ensure_state_dirs()

    app_id = (payload.get("appId") or "").strip() or _default_app_id()
    target_key = (payload.get("targetKey") or "").strip()
    updated_text = payload.get("updatedText")
    self_check = payload.get("selfCheck")

    # Optional metadata for draft shelf.
    model = (payload.get("model") or "").strip()
    change_request = (payload.get("changeRequest") or "").strip()
    notes = (payload.get("notes") or "").strip()

    trace_id = getattr(getattr(request, "state", None), "trace_id", "") or ""
    LOG.info(
        "edit.apply trace_id=%s app_id=%s target_key=%s updated_len=%d",
        trace_id or "-",
        app_id,
        target_key,
        len(updated_text) if isinstance(updated_text, str) else -1,
    )

    if not target_key:
        raise HTTPException(status_code=400, detail="targetKey is required")
    if not isinstance(updated_text, str):
        raise HTTPException(status_code=400, detail="updatedText must be a string")
    if self_check is False:
        raise HTTPException(status_code=400, detail="selfCheck=false blocks apply")

    candidate_path = _candidate_path(app_id)
    if not candidate_path.exists():
        _ = api_get_candidate(appId=app_id)
    cand_obj = _read_json(candidate_path)

    prompts = cand_obj.get("prompts") if isinstance(cand_obj, dict) else None
    if not isinstance(prompts, dict):
        raise HTTPException(status_code=400, detail="candidate prompts are missing")

    current_text = prompts.get(target_key)
    if not isinstance(current_text, str):
        raise HTTPException(
            status_code=400, detail=f"targetKey '{target_key}' not found in prompts"
        )

    errors = engine.validate_prompt_edit(
        target_key=target_key,
        current_text=current_text,
        updated_text=updated_text,
    )
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    # Snapshot before apply for undo.
    _push_undo_snapshot(app_id, cand_obj, reason=f"apply:{target_key}")

    prompts[target_key] = updated_text
    cand_obj["updatedAt"] = _utc_now_iso()

    # Validate shape via engine loader before writing.
    raw_bytes = json.dumps(cand_obj).encode("utf-8")
    _ = engine.load_prompts_json_from_bytes(raw_bytes, source=str(candidate_path))

    candidate_path.write_text(json.dumps(cand_obj, indent=2), encoding="utf-8")

    # Snapshot after apply for draft shelf browsing.
    _push_draft_version(
        app_id,
        cand_obj,
        reason=f"apply:{target_key}",
        target_key=target_key,
        model=model,
        change_request=change_request,
        trace_id=trace_id,
        notes=notes,
    )

    return JSONResponse(
        {
            "ok": True,
            "appId": app_id,
            "targetKey": target_key,
            "updatedAt": cand_obj.get("updatedAt") or "",
            "traceId": trace_id,
        }
    )


@app.post("/api/edit/undo")
def api_edit_undo(payload: Dict[str, Any]) -> JSONResponse:
    """Undo the last applied edit by restoring the previous candidate snapshot."""

    _ensure_state_dirs()

    app_id = (payload.get("appId") or "").strip() or _default_app_id()
    candidate_path = _candidate_path(app_id)

    items = _read_history(app_id)
    if not items:
        raise HTTPException(status_code=400, detail="Nothing to undo")

    # History schema back-compat:
    # - New entries always include a `kind` field (undo/draft/suite).
    # - Some older history files may contain kind-less entries of *multiple* types.
    #   Once any `kind` is present, treat kind-less entries as legacy noise and do
    #   NOT allow them to hijack Undo selection.
    has_any_kind = any(isinstance(it, dict) and ("kind" in it) for it in items)

    def _looks_like_legacy_undo_snapshot(it: Dict[str, Any]) -> bool:
        cand = it.get("candidate")
        if not isinstance(cand, dict):
            return False
        # Draft/suite entries tend to carry extra metadata.
        for k in ("targetKey", "model", "changeRequest", "traceId", "notes", "suite"):
            if k in it:
                return False
        return True

    # Undo should only apply to undo snapshots (not draft shelf entries).
    idx = None
    for i in range(len(items) - 1, -1, -1):
        it = items[i]
        if not isinstance(it, dict):
            continue
        kind_val = it.get("kind", None)
        if kind_val is None:
            if has_any_kind:
                continue
            if not _looks_like_legacy_undo_snapshot(it):
                continue
        else:
            kind = str(kind_val)
            if kind != "undo":
                continue
        cand_obj = it.get("candidate")
        if isinstance(cand_obj, dict):
            idx = i
            break

    if idx is None:
        raise HTTPException(status_code=400, detail="Nothing to undo")

    snap = items.pop(idx)
    cand_obj = snap.get("candidate") if isinstance(snap, dict) else None
    if not isinstance(cand_obj, dict):
        raise HTTPException(status_code=400, detail="Undo history is corrupted")

    # Validate before writing.
    raw_bytes = json.dumps(cand_obj).encode("utf-8")
    _ = engine.load_prompts_json_from_bytes(raw_bytes, source=str(candidate_path))

    candidate_path.write_text(json.dumps(cand_obj, indent=2), encoding="utf-8")
    _write_history(app_id, items)

    return JSONResponse({"ok": True})


@app.post("/api/edit/reset")
def api_edit_reset(payload: Dict[str, Any]) -> JSONResponse:
    """Reset candidate prompts (and history) back to canonical prompts."""

    _ensure_state_dirs()
    app_id = (payload.get("appId") or "").strip() or _default_app_id()

    candidate_path = _candidate_path(app_id)

    if candidate_path.exists():
        try:
            cand_obj = _read_json(candidate_path)
            _push_undo_snapshot(app_id, cand_obj, reason="reset")
            _push_draft_version(app_id, cand_obj, reason="reset")
        except Exception:
            pass
        candidate_path.unlink(missing_ok=True)

    # Start fresh from canonical via existing getter.
    _ = api_get_candidate(appId=app_id)

    return JSONResponse({"ok": True})


@app.get("/api/drafts")
def api_drafts(appId: str = "") -> JSONResponse:
    """List local edit history versions (newest-first) and latest suite status."""

    _ensure_state_dirs()
    app_id = (appId or "").strip() or _default_app_id()

    items = _read_history(app_id)
    drafts = list(reversed(_draft_entries(items)))

    # Only show versions that represent actual prompt edits.
    # Today that means: post-apply snapshots.
    edit_drafts = [
        d
        for d in drafts
        if isinstance(d, dict) and str(d.get("reason") or "").startswith("apply:")
    ]

    out: List[Dict[str, Any]] = []
    for d in edit_drafts:
        if not isinstance(d, dict):
            continue
        ent: Dict[str, Any] = {
            "id": str(d.get("id") or ""),
            "savedAt": str(d.get("savedAt") or ""),
            "reason": str(d.get("reason") or ""),
        }
        for k in [
            "targetKey",
            "model",
            "changeRequest",
            "traceId",
            "notes",
            "suite",
        ]:
            if k in d:
                ent[k] = d.get(k)
        ent["isClean"] = bool(_compute_is_clean(d))
        out.append(ent)

    latest_suite_ent: Optional[Dict[str, Any]] = None
    latest_suite_is_clean = False
    latest_suite = _latest_suite_entry(items)
    if isinstance(latest_suite, dict):
        latest_suite_is_clean = bool(_compute_is_clean(latest_suite))
        suite_obj = (
            latest_suite.get("suite")
            if isinstance(latest_suite.get("suite"), dict)
            else None
        )
        if isinstance(suite_obj, dict):
            latest_suite_ent = dict(suite_obj)
            latest_suite_ent["isClean"] = latest_suite_is_clean

    return JSONResponse(
        {
            "appId": app_id,
            "versions": out,
            "latestSuite": latest_suite_ent,
            "latestSuiteIsClean": bool(latest_suite_is_clean),
        }
    )


@app.post("/api/drafts/restore")
def api_drafts_restore(payload: Dict[str, Any]) -> JSONResponse:
    """Restore a draft version into the candidate prompts file."""

    _ensure_state_dirs()
    app_id = (payload.get("appId") or "").strip() or _default_app_id()
    draft_id = (payload.get("id") or "").strip()
    if not draft_id:
        raise HTTPException(status_code=400, detail="id is required")

    candidate_path = _candidate_path(app_id)
    if not candidate_path.exists():
        _ = api_get_candidate(appId=app_id)

    # Best-effort: snapshot current candidate for undo.
    try:
        cur = _read_json(candidate_path)
        _push_undo_snapshot(app_id, cur, reason="restore")
    except Exception:
        pass

    items = _read_history(app_id)
    found: Optional[Dict[str, Any]] = None
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("kind") or "") != "draft":
            continue
        if str(it.get("id") or "") == draft_id:
            found = it
            break

    if not found:
        raise HTTPException(status_code=404, detail="Draft version not found")

    cand_obj = found.get("candidate")
    if not isinstance(cand_obj, dict):
        raise HTTPException(status_code=400, detail="Draft version is corrupted")

    cand_obj = dict(cand_obj)
    cand_obj["updatedAt"] = _utc_now_iso()

    raw_bytes = json.dumps(cand_obj).encode("utf-8")
    _ = engine.load_prompts_json_from_bytes(raw_bytes, source=str(candidate_path))
    candidate_path.write_text(json.dumps(cand_obj, indent=2), encoding="utf-8")

    return JSONResponse(
        {
            "ok": True,
            "appId": app_id,
            "restoredId": draft_id,
            "updatedAt": cand_obj.get("updatedAt") or "",
        }
    )


@app.get("/api/drafts/diff")
def api_drafts_diff(appId: str = "", id: str = "", targetKey: str = "") -> JSONResponse:
    """Return a unified diff for a draft version vs the previous draft version for a target key."""

    _ensure_state_dirs()
    app_id = (appId or "").strip() or _default_app_id()
    draft_id = (id or "").strip()
    target_key = (targetKey or "").strip()
    if not draft_id:
        raise HTTPException(status_code=400, detail="id is required")
    if not target_key:
        raise HTTPException(status_code=400, detail="targetKey is required")

    items = _read_history(app_id)
    drafts = [
        d
        for d in _draft_entries(items)
        if isinstance(d, dict) and str(d.get("reason") or "").startswith("apply:")
    ]

    idx = None
    for i, d in enumerate(drafts):
        if not isinstance(d, dict):
            continue
        if str(d.get("id") or "") == draft_id:
            idx = i
            break

    if idx is None:
        raise HTTPException(status_code=404, detail="Draft version not found")

    cur = drafts[idx]
    prev = drafts[idx - 1] if idx > 0 else None

    def _text_for(entry: Optional[Dict[str, Any]]) -> str:
        if not isinstance(entry, dict):
            return ""
        c = entry.get("candidate")
        if not isinstance(c, dict):
            return ""
        prompts = c.get("prompts")
        if not isinstance(prompts, dict):
            return ""
        t = prompts.get(target_key)
        return t if isinstance(t, str) else ""

    a = _text_for(prev)
    b = _text_for(cur)
    a_at = str(prev.get("savedAt") or "") if isinstance(prev, dict) else ""
    b_at = str(cur.get("savedAt") or "") if isinstance(cur, dict) else ""

    diff = engine.unified_diff(
        a,
        b,
        a_label=f"prev:{target_key}@{a_at or '-'}",
        b_label=f"draft:{target_key}@{b_at or '-'}",
    )

    return JSONResponse(
        {
            "ok": True,
            "appId": app_id,
            "id": draft_id,
            "targetKey": target_key,
            "diff": diff,
            "prevSavedAt": a_at,
            "savedAt": b_at,
        }
    )


@app.post("/api/promote")
def api_promote(payload: Dict[str, Any]) -> JSONResponse:
    """Promote the current candidate prompts to the canonical prompts/<appId>.json file."""

    _ensure_state_dirs()
    app_id = (payload.get("appId") or "").strip() or _default_app_id()
    require_clean = payload.get("requireClean")
    require_clean = True if require_clean is None else bool(require_clean)

    cfg = _get_app(app_id)
    canonical_path = Path(str(cfg.get("defaultPromptsPath") or "")).resolve()
    if not canonical_path.exists():
        raise HTTPException(status_code=404, detail="Canonical prompts file not found")
    # Safety: only allow writing under repo prompts/.
    if PROMPTS_DIR not in canonical_path.parents:
        raise HTTPException(
            status_code=400, detail="Refusing to write outside prompts/"
        )

    candidate_path = _candidate_path(app_id)
    if not candidate_path.exists():
        _ = api_get_candidate(appId=app_id)

    cand_obj = _read_json(candidate_path)
    if not isinstance(cand_obj, dict):
        raise HTTPException(status_code=400, detail="Candidate prompts are corrupted")

    if require_clean:
        # Require the latest suite snapshot to be clean.
        items = _read_history(app_id)
        latest_suite = _latest_suite_entry(items)
        if not latest_suite or not _compute_is_clean(latest_suite):
            raise HTTPException(
                status_code=400,
                detail="Promote blocked: latest suite snapshot is not clean (run suite and fix flags/errors).",
            )

    updated_at = _utc_now_iso()
    cand_obj = dict(cand_obj)
    cand_obj["updatedAt"] = updated_at

    raw_bytes = json.dumps(cand_obj).encode("utf-8")
    _ = engine.load_prompts_json_from_bytes(raw_bytes, source=str(canonical_path))

    canonical_path.write_text(json.dumps(cand_obj, indent=2), encoding="utf-8")
    candidate_path.write_text(json.dumps(cand_obj, indent=2), encoding="utf-8")

    # Clear local draft history; git is the version history after promotion.
    _write_history(app_id, [])

    # Clear any local baseline overrides.
    try:
        _baseline_path(app_id).unlink(missing_ok=True)
    except Exception:
        pass

    return JSONResponse(
        {
            "ok": True,
            "appId": app_id,
            "canonicalPath": str(canonical_path),
            "updatedAt": updated_at,
        }
    )


@app.post("/api/run/tune")
def api_run_tune(payload: Dict[str, Any]) -> JSONResponse:
    app_id = (payload.get("appId") or "").strip() or _default_app_id()
    mode = (payload.get("mode") or "").strip() or "opener"
    model = (payload.get("model") or "").strip() or "gpt-5-mini"
    system_prompt = (payload.get("systemPrompt") or "").rstrip()
    user_prompt = (payload.get("userPrompt") or "").rstrip()
    dry_run = bool(payload.get("dryRun") or False)

    _ = _get_app(app_id)

    pricing = _pricing_by_model(model)
    if pricing is None:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'.")

    if dry_run:
        usage = {
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": 0,
            "cachedTokens": 0,
        }
        cost = _compute_cost_usd(usage, pricing)
        return JSONResponse(
            {
                "model": model,
                "outputText": "[DRY RUN] (no API call made)",
                "usage": usage,
                "pricing": {
                    "inputPer1M": pricing.input_per_1m,
                    "cachedInputPer1M": pricing.cached_input_per_1m,
                    "outputPer1M": pricing.output_per_1m,
                },
                "cost": cost,
            }
        )

    try:
        engine.ensure_api_key()
        messages = engine.build_messages(system_prompt, user_prompt)
        text, usage = engine.call_openai(
            model=model,
            messages=messages,
            temperature=0.7,
            max_output_tokens=512,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Ensure cost computation has numeric keys present.
    usage_norm = {
        "inputTokens": int(usage.get("inputTokens") or 0),
        "outputTokens": int(usage.get("outputTokens") or 0),
        "totalTokens": int(usage.get("totalTokens") or 0),
        "cachedTokens": int(usage.get("cachedTokens") or 0),
    }
    cost = _compute_cost_usd(usage_norm, pricing)

    return JSONResponse(
        {
            "model": model,
            "outputText": text,
            "usage": usage_norm,
            "pricing": {
                "inputPer1M": pricing.input_per_1m,
                "cachedInputPer1M": pricing.cached_input_per_1m,
                "outputPer1M": pricing.output_per_1m,
            },
            "cost": cost,
        }
    )


@dataclass
class AbItem:
    fixture: str
    input: str
    baselineOutput: str
    candidateOutput: str
    diffFile: str


@app.post("/api/run/ab")
def api_run_ab(payload: Dict[str, Any]) -> JSONResponse:
    app_id = (payload.get("appId") or "").strip()
    mode = (payload.get("mode") or "").strip()
    model = (payload.get("model") or "").strip() or "gpt-5-mini"
    max_fx = int(payload.get("maxFixtures") or 0)
    only_fixture = (payload.get("fixture") or "").strip()
    dry_run = bool(payload.get("dryRun") or False)
    baseline_source = (payload.get("baselineSource") or "local_file").strip()
    remote_url = (payload.get("remoteUrl") or "").strip()

    cfg = _get_app(app_id)

    _ensure_state_dirs()
    candidate_path = _candidate_path(app_id)
    baseline_path = _baseline_path(app_id)

    # Build argv for engine main_argv.
    argv: List[str] = [
        "--load-env",
        "--app-id",
        app_id,
        "--fixtures-dir",
        str(FIXTURES_DIR),
        "--mode",
        mode,
        "--model",
        model,
        "--out-dir",
        str(OUT_DIR),
    ]
    if dry_run:
        argv += ["--dry-run"]
    if max_fx > 0:
        argv += ["--max-fixtures", str(max_fx)]
    if only_fixture:
        argv += ["--only-fixture", only_fixture]

    if baseline_source == "remote_url":
        url = remote_url or cfg.get("defaultRemotePromptsUrl")
        if not url:
            # No remote URL configured; fall back to local prompts path for baseline.
            argv += ["--baseline-prompts-path", cfg.get("defaultPromptsPath")]
        else:
            argv += ["--baseline-prompts-url", url]
    else:
        argv += [
            "--baseline-prompts-path",
            str(
                baseline_path
                if baseline_path.exists()
                else cfg.get("defaultPromptsPath")
            ),
        ]

    # Candidate is always local draft per app.
    if not candidate_path.exists():
        # Ensure candidate exists (initialized from canonical prompts file)
        src = Path(str(cfg.get("defaultPromptsPath") or ""))
        if src.exists():
            candidate_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            candidate_path.write_text(
                json.dumps(
                    {"version": 1, "updatedAt": "", "ttlSeconds": 3600, "prompts": {}},
                    indent=2,
                ),
                encoding="utf-8",
            )

    argv += ["--candidate-prompts-path", str(candidate_path)]

    # Run the engine. It writes outputs.
    try:
        rc = engine.main_argv(argv)
        if rc != 0:
            raise RuntimeError(f"Engine exit code {rc}")
    except SystemExit as e:
        # argparse calls SystemExit on parse errors
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    out = _latest_out_dir()
    if not out:
        raise HTTPException(status_code=500, detail="No output directory created")

    run_manifest = _read_json(out / "run.json")
    ordered_fixtures = run_manifest.get("fixtures") or []
    if not isinstance(ordered_fixtures, list):
        ordered_fixtures = []

    ab_summary = out / "ab_summary.json"
    diff_index = _read_json(ab_summary)

    items: List[Dict[str, Any]] = []
    totals: Dict[str, int] = {
        "baselineInputTokens": 0,
        "baselineOutputTokens": 0,
        "baselineTotalTokens": 0,
        "baselineCachedTokens": 0,
        "candidateInputTokens": 0,
        "candidateOutputTokens": 0,
        "candidateTotalTokens": 0,
        "candidateCachedTokens": 0,
    }
    fixture_names = ordered_fixtures or list((diff_index or {}).keys())

    # Compute a minimal suite summary for draft shelf + optional promote gating.
    candidate_flag_counts: Dict[str, int] = {}
    candidate_error_count = 0
    for name in fixture_names:
        di = diff_index.get(name) or {}
        bobj = di.get("baseline") or {}
        cobj = di.get("candidate") or {}
        b = bobj.get("output") or ""
        c = cobj.get("output") or ""
        binp = bobj.get("input") or ""
        cinp = cobj.get("input") or ""
        bu = bobj.get("usage") or {}
        cu = cobj.get("usage") or {}
        bflags = bobj.get("flags") or []
        cflags = cobj.get("flags") or []
        berr = bobj.get("error")
        cerr = cobj.get("error")
        df = di.get("diffFile") or ""

        if cerr:
            candidate_error_count += 1
        if isinstance(cflags, list):
            for f in cflags:
                if isinstance(f, str) and f:
                    candidate_flag_counts[f] = candidate_flag_counts.get(f, 0) + 1

        def _add(prefix: str, usage: Dict[str, Any]) -> None:
            try:
                totals[f"{prefix}InputTokens"] += int(usage.get("inputTokens") or 0)
                totals[f"{prefix}OutputTokens"] += int(usage.get("outputTokens") or 0)
                totals[f"{prefix}TotalTokens"] += int(usage.get("totalTokens") or 0)
                totals[f"{prefix}CachedTokens"] += int(usage.get("cachedTokens") or 0)
            except Exception:
                # Keep totals best-effort.
                pass

        _add("baseline", bu)
        _add("candidate", cu)
        items.append(
            {
                "fixture": name,
                "input": cinp or binp,
                "baselineInput": binp,
                "candidateInput": cinp,
                "baselineOutput": b,
                "candidateOutput": c,
                "baselineFlags": bflags if isinstance(bflags, list) else [],
                "candidateFlags": cflags if isinstance(cflags, list) else [],
                "baselineError": berr if isinstance(berr, str) else "",
                "candidateError": cerr if isinstance(cerr, str) else "",
                "baselineUsage": bu,
                "candidateUsage": cu,
                "diffFile": df,
            }
        )

    suite = {
        "status": "ok",
        "runId": str(out.name),
        "ranAt": _utc_now_iso(),
        "mode": mode,
        "model": model,
        "flagsSummary": {
            **candidate_flag_counts,
            "candidate_errors": candidate_error_count,
            "total_fixtures": len(fixture_names),
        },
    }

    # Compute isClean server-side.
    is_clean = _compute_is_clean({"suite": suite})
    suite["isClean"] = bool(is_clean)

    # Persist a suite snapshot for promote gating (best-effort).
    # Stored as kind='suite' so the edit-history dropdown stays focused on real edits.
    try:
        cand_obj = _read_json(candidate_path)
        _push_draft_version(
            app_id,
            cand_obj,
            kind="suite",
            reason="run_suite",
            model=model,
            suite=suite,
        )
    except Exception:
        pass

    return JSONResponse(
        {
            "outDir": str(out),
            "reportPath": f"/api/out/{out.name}/ab_report.html",
            "totals": totals,
            "suite": suite,
            "items": items,
        }
    )


@app.get("/api/out/{run_id}/ab_report.html")
def api_get_report(run_id: str) -> FileResponse:
    p = OUT_DIR / run_id / "ab_report.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(p), media_type="text/html")


@app.post("/api/open-last")
def api_open_last() -> JSONResponse:
    out = _latest_out_dir()
    if not out:
        raise HTTPException(status_code=404, detail="No runs yet")
    report = out / "ab_report.html"
    engine._try_open_path(report if report.exists() else out)  # type: ignore[attr-defined]
    return JSONResponse({"ok": True})


@app.get("/api/config")
def api_config() -> JSONResponse:
    return JSONResponse(
        {"aiPromptsIndexUrl": AI_PROMPTS_INDEX_URL, "repoRoot": str(REPO_ROOT)}
    )
