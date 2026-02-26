# pylint: skip-file
# flake8: noqa
# ruff: noqa
# pyright: ignore

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request

from fastapi import FastAPI, HTTPException
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

# Candidate + optional local baseline live under tools/workbench-web/state/ for local iteration (gitignored).
STATE_DIR = WEB_ROOT / "state"
CANDIDATES_DIR = STATE_DIR / "candidates"
BASELINES_DIR = STATE_DIR / "baselines"


def _candidate_path(app_id: str) -> Path:
    return CANDIDATES_DIR / f"{app_id}.json"


def _baseline_path(app_id: str) -> Path:
    return BASELINES_DIR / f"{app_id}.json"


def _ensure_state_dirs() -> None:
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)


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
                "defaultModel": (a.get("defaultModel") or "gpt-4o-mini").strip(),
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
                "defaultModel": (a.get("defaultModel") or "gpt-4o-mini").strip(),
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
            "defaultModel": "gpt-4o-mini",
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
    latest = [m for m in _MODEL_CATALOG if m.is_latest][:2]

    def _score(m: ModelPricing) -> float:
        # "Least costly" is ambiguous; for a simple heuristic, rank by input+output.
        return float(m.input_per_1m) + float(m.output_per_1m)

    chosen = {m.model for m in latest}
    cheapest = [m for m in sorted(_MODEL_CATALOG, key=_score) if m.model not in chosen][
        :2
    ]
    return latest + cheapest


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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


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


@app.post("/api/run/tune")
def api_run_tune(payload: Dict[str, Any]) -> JSONResponse:
    app_id = (payload.get("appId") or "").strip() or _default_app_id()
    mode = (payload.get("mode") or "").strip() or "opener"
    model = (payload.get("model") or "").strip() or "gpt-4o-mini"
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
    model = (payload.get("model") or "").strip() or "gpt-4o-mini"
    max_fx = int(payload.get("maxFixtures") or 0)
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

    ab_summary = out / "ab_summary.json"
    diff_index = _read_json(ab_summary)

    # Load fixture inputs
    fixtures = engine.load_fixtures(FIXTURES_DIR, mode, app_id=app_id)
    if max_fx > 0:
        fixtures = fixtures[:max_fx]
    fixture_input = {n: t for (n, t) in fixtures}

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
    for name in fixture_input.keys():
        di = diff_index.get(name) or {}
        b = (di.get("baseline") or {}).get("output") or ""
        c = (di.get("candidate") or {}).get("output") or ""
        bu = (di.get("baseline") or {}).get("usage") or {}
        cu = (di.get("candidate") or {}).get("usage") or {}
        df = di.get("diffFile") or ""

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
                "input": fixture_input.get(name, ""),
                "baselineOutput": b,
                "candidateOutput": c,
                "baselineUsage": bu,
                "candidateUsage": cu,
                "diffFile": df,
            }
        )

    return JSONResponse(
        {
            "outDir": str(out),
            "reportPath": f"/api/out/{out.name}/ab_report.html",
            "totals": totals,
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
