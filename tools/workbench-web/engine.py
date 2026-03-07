# pylint: skip-file
# flake8: noqa
# ruff: noqa
# pyright: ignore

"""Prompt workbench for iterating on prompt text without rebuilding the Android app.

Key goals:
- Fixture-first prompt iteration
- Saved artifacts per run (outputs + manifest)
- Optional A/B comparison with diffs
- Uses the OpenAI Python SDK with the Responses API

Defaults:
- Loads prompts from ../../docs/prompts.json unless overridden.
- Loads fixtures from ./fixtures/<mode>/*.txt

Environment:
- OPENAI_API_KEY must be set for real runs.

Examples:
  # sanity check (no API call)
  python run.py --mode reg_chat --validate-only

  # smoke run (1 fixture) using default prompts path
  python run.py --mode reg_chat --max-fixtures 1

  # run against prompts from a URL (e.g., raw GitHub)
  python run.py --mode reg_chat --prompts-url https://example.com/rizzchatai.json

  # A/B compare two prompt JSON files
  python run.py --mode reg_chat --baseline-prompts-path A.json --candidate-prompts-path B.json --max-fixtures 3
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import difflib
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


MODES = ("opener", "app_chat", "reg_chat")


_LOG = logging.getLogger("workbench.engine")
if not _LOG.handlers:
    # Leave handler configuration to the hosting app (FastAPI server). When this
    # module is used standalone, avoid "No handler" warnings.
    _LOG.addHandler(logging.NullHandler())


@dataclasses.dataclass(frozen=True)
class PromptBundle:
    version: int
    updated_at: str
    ttl_seconds: int
    opener_system: str
    app_chat_system: str
    reg_chat_system: str
    opener_user: str
    app_chat_user: str
    reg_chat_user: str


def _repo_root() -> Path:
    cur = Path(__file__).resolve()
    if cur.is_file():
        cur = cur.parent
    for _ in range(10):
        if (cur / "prompts").is_dir() and (cur / "fixtures").is_dir():
            return cur
        cur = cur.parent
    raise RuntimeError(
        "Could not locate repo root (expected folders 'prompts/' and 'fixtures/')."
    )


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _utc_timestamp_slug() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")


def _env_truthy(name: str, default: str = "") -> bool:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        v = default
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    try:
        return int(str(v).strip())
    except Exception:
        return int(default)


def _auto_prune_out_runs(out_base: Path) -> None:
    """Keep out/ bounded by pruning older engine run folders.

    Best-effort only (never fail a run). Prunes only directories that match the
    timestamp slug pattern YYYYMMDD_HHMMSS and contain run.json.

    Defaults:
    - enabled (WORKBENCH_OUT_AUTOPRUNE=1)
    - keep last 10 runs (WORKBENCH_OUT_KEEP_LAST)
    """

    try:
        if not _env_truthy("WORKBENCH_OUT_AUTOPRUNE", default="1"):
            return

        keep_last = max(0, _env_int("WORKBENCH_OUT_KEEP_LAST", 10))
        keep_days = max(0, _env_int("WORKBENCH_OUT_KEEP_DAYS", 0))
        if keep_last == 0 and keep_days == 0:
            return

        if not out_base.exists() or not out_base.is_dir():
            return

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=keep_days
        )

        slug_re = re.compile(r"^\d{8}_\d{6}$")
        runs: List[Tuple[datetime.datetime, Path]] = []
        for p in out_base.iterdir():
            try:
                if not p.is_dir():
                    continue
                if not slug_re.match(p.name):
                    continue
                if not (p / "run.json").exists():
                    continue
                dt = datetime.datetime.strptime(p.name, "%Y%m%d_%H%M%S").replace(
                    tzinfo=datetime.timezone.utc
                )
                runs.append((dt, p))
            except Exception:
                continue

        if not runs:
            return

        runs.sort(key=lambda t: t[0], reverse=True)

        keep: set[str] = set()
        if keep_last > 0:
            for _, p in runs[:keep_last]:
                keep.add(str(p.resolve()))
        if keep_days > 0:
            for dt, p in runs:
                if dt >= cutoff:
                    keep.add(str(p.resolve()))

        for _, p in runs:
            if str(p.resolve()) in keep:
                continue
            try:
                shutil.rmtree(p)
            except Exception:
                pass
    except Exception:
        return


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clamp_int(v: int, min_v: int, max_v: int) -> int:
    return max(min_v, min(max_v, v))


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fetch_url_bytes(url: str, timeout_s: int = 15) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "RizzChatAI-PromptWorkbench/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        # Include a short response snippet; many backends return useful JSON for auth errors
        # (e.g. "invalid_client_id").
        try:
            body_bytes = e.read()  # type: ignore[no-untyped-call]
        except Exception:
            body_bytes = b""
        body_text = body_bytes.decode("utf-8", errors="replace").strip()
        if len(body_text) > 2000:
            body_text = body_text[:2000] + "…"
        msg = f"Failed to fetch URL {url} (HTTP {getattr(e, 'code', '?')}): {body_text or getattr(e, 'reason', '')}"
        raise RuntimeError(msg) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Failed to fetch URL {url}: {getattr(e, 'reason', e)}"
        ) from e


def _try_git_head_sha(cwd: Path) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def load_prompts_json_from_bytes(data: bytes, source: str) -> PromptBundle:
    raw = json.loads(data.decode("utf-8"))
    prompts = raw.get("prompts") or {}

    def _s(key: str) -> str:
        v = prompts.get(key)
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ValueError(f"{source}: prompts.{key} must be a string")
        return v

    version = raw.get("version")
    updated_at = raw.get("updatedAt")
    ttl_seconds = raw.get("ttlSeconds")

    if not isinstance(version, int):
        raise ValueError(f"{source}: version must be an int")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ValueError(f"{source}: updatedAt must be a non-empty string")
    if not isinstance(ttl_seconds, int):
        raise ValueError(f"{source}: ttlSeconds must be an int")

    return PromptBundle(
        version=version,
        updated_at=updated_at,
        ttl_seconds=ttl_seconds,
        opener_system=_s("openerSystem"),
        app_chat_system=_s("appChatSystem"),
        reg_chat_system=_s("regChatSystem"),
        opener_user=_s("openerUser"),
        app_chat_user=_s("appChatUser"),
        reg_chat_user=_s("regChatUser"),
    )


def load_prompts_bundle(
    *,
    prompts_path: Optional[Path],
    prompts_url: str,
    default_prompts_path: Path,
) -> Tuple[PromptBundle, str, str]:
    """Returns (bundle, source_kind, source_id).

    source_kind: PATH | URL
    source_id: absolute path string or URL
    """
    if prompts_path and prompts_url:
        raise ValueError("Use only one of --prompts-path or --prompts-url")

    if prompts_url:
        data = _fetch_url_bytes(prompts_url)
        return (
            load_prompts_json_from_bytes(data, source=prompts_url),
            "URL",
            prompts_url,
        )

    path = prompts_path or default_prompts_path
    data = path.read_bytes()
    return (
        load_prompts_json_from_bytes(data, source=str(path)),
        "PATH",
        str(path.resolve()),
    )


def system_prompt_for_mode(bundle: PromptBundle, mode: str) -> str:
    return {
        "opener": bundle.opener_system,
        "app_chat": bundle.app_chat_system,
        "reg_chat": bundle.reg_chat_system,
    }[mode]


def user_template_for_mode(bundle: PromptBundle, mode: str) -> str:
    return {
        "opener": bundle.opener_user,
        "app_chat": bundle.app_chat_user,
        "reg_chat": bundle.reg_chat_user,
    }[mode]


_TEMPLATE_VAR_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def extract_template_vars(text: str) -> List[str]:
    """Return template variable names referenced like {{var}}."""

    t = text or ""
    return sorted(set(_TEMPLATE_VAR_RE.findall(t)))


_URL_RE = re.compile(r"\bhttps?://", re.IGNORECASE)


def validate_prompt_edit(
    *, target_key: str, current_text: str, updated_text: str
) -> List[str]:
    """Validate a proposed prompt edit.

    Rules (enforced):
    - Must preserve placeholder set exactly (no adds/removes).
    - Must not introduce external URLs.
    - Must not be empty/whitespace.
    """

    errors: List[str] = []

    if not isinstance(updated_text, str):
        errors.append("updatedText must be a string")
        return errors

    if not updated_text.strip():
        errors.append("updatedText must not be empty")

    if _URL_RE.search(updated_text or ""):
        errors.append("updatedText must not include URLs")

    before_vars = set(extract_template_vars(current_text or ""))
    after_vars = set(extract_template_vars(updated_text or ""))
    if before_vars != after_vars:
        removed = sorted(before_vars - after_vars)
        added = sorted(after_vars - before_vars)
        if removed:
            errors.append(
                f"updatedText removed required placeholders: {', '.join(removed)}"
            )
        if added:
            errors.append(
                f"updatedText added new placeholders (not allowed): {', '.join(added)}"
            )

    # Avoid accepting a no-op update that only changes trailing whitespace.
    if (current_text or "").rstrip() == (updated_text or "").rstrip():
        errors.append("updatedText must change the prompt")

    _ = (target_key or "").strip()
    return errors


_PROMPT_EDIT_SCHEMA_V1 = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["ok", "refused", "error"]},
        "targetKey": {"type": "string"},
        "updatedText": {"type": "string"},
        "rationale": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "selfCheck": {"type": "boolean"},
        "refusalReason": {"type": "string"},
    },
    "required": [
        "status",
        "targetKey",
        "updatedText",
        "rationale",
        "warnings",
        "selfCheck",
        "refusalReason",
    ],
}


_PROMPT_EDIT_FORMAT_V1 = {
    "type": "json_schema",
    "name": "prompt_edit_v1",
    "strict": True,
    "schema": _PROMPT_EDIT_SCHEMA_V1,
}


_EDITOR_SYSTEM_PROMPT = """You are a prompt editor.

Task:
- You will receive a targetKey, the currentText for that key, and a changeRequest.
- Produce a revised updatedText for that single key only.

Hard constraints:
- Return JSON only (must match the provided JSON schema).
- Do not use tools.
- Preserve ALL template placeholders exactly (e.g., {{profile_text}}, {{chat_transcript}}, {{tie_in_block}}). You may move them, but do not add/remove/rename any placeholders.
- Do not introduce URLs (http:// or https://).

Refusal:
- If you cannot comply with the request while satisfying constraints, set status="refused", selfCheck=false, and explain why in refusalReason.
"""


def propose_prompt_edit(
    *,
    model: str,
    target_key: str,
    current_text: str,
    change_request: str,
    dry_run: bool = False,
    trace_id: str = "",
) -> Dict[str, Any]:
    """Ask the model to propose a safe edit for a single prompt key."""

    target_key = (target_key or "").strip()
    if not target_key:
        raise RuntimeError("target_key is required")

    current_text = current_text or ""
    change_request = (change_request or "").strip()
    if not change_request:
        raise RuntimeError("change_request is required")

    if dry_run:
        updated = (current_text.rstrip() + "\n\n[DRY_RUN_EDIT]\n").replace("\r\n", "\n")
        errors = validate_prompt_edit(
            target_key=target_key, current_text=current_text, updated_text=updated
        )
        if errors:
            return {
                "status": "refused",
                "targetKey": target_key,
                "updatedText": current_text,
                "rationale": "Dry-run edit failed validation.",
                "warnings": ["dry_run"],
                "selfCheck": False,
                "refusalReason": "; ".join(errors),
                "modelUsed": model,
                "usage": {
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "totalTokens": 0,
                    "cachedTokens": 0,
                },
            }
        return {
            "status": "ok",
            "targetKey": target_key,
            "updatedText": updated,
            "rationale": "Dry-run: deterministic placeholder-safe edit.",
            "warnings": ["dry_run"],
            "selfCheck": True,
            "refusalReason": "",
            "modelUsed": model,
            "usage": {
                "inputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 0,
                "cachedTokens": 0,
            },
        }

    ensure_api_key()

    # Tracing is enabled by default so users can always inspect what was sent/returned
    # without needing to remember flags. Disable with WORKBENCH_TRACE_AI=0.
    trace_enabled = _env_truthy("WORKBENCH_TRACE_AI", default="1")
    trace_keep_last = max(0, _env_int("WORKBENCH_TRACE_AI_KEEP_LAST", 10))
    trace_slug = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")

    from openai import OpenAI

    client = OpenAI()

    openai_request_id: str = ""

    user_payload = {
        "targetKey": target_key,
        "currentText": current_text,
        "changeRequest": change_request,
        "placeholders": extract_template_vars(current_text),
    }

    safe_change_preview = (change_request or "").replace("\n", " ").strip()
    if len(safe_change_preview) > 140:
        safe_change_preview = safe_change_preview[:140] + "…"
    _LOG.info(
        "edit.propose.start trace_id=%s model=%s target_key=%s current_len=%d placeholders=%s change_len=%d change_preview=%r",
        trace_id or "-",
        model,
        target_key,
        len(current_text or ""),
        ",".join(extract_template_vars(current_text)) or "-",
        len(change_request or ""),
        safe_change_preview,
    )

    # The model must return a full updatedText (typically similar length to current_text)
    # embedded in a JSON object. A fixed low token cap can truncate the JSON mid-string
    # and make it unparsable (e.g., "Unterminated string").
    approx_output_tokens = int(len(current_text) / 3.2) + 700
    max_output_tokens = _clamp_int(approx_output_tokens, 1200, 4000)
    _LOG.info(
        "edit.propose.budget trace_id=%s max_output_tokens=%d",
        trace_id or "-",
        max_output_tokens,
    )

    base_kwargs: Dict[str, Any] = {
        "model": model,
        "input": [
            {"role": "system", "content": _EDITOR_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "tools": [],
        "tool_choice": "none",
        "text": {"format": _PROMPT_EDIT_FORMAT_V1},
    }

    def _write_trace_artifact(label: str, text: str) -> str:
        if not trace_enabled:
            return ""
        try:
            web_root = Path(__file__).resolve().parent
            out_dir = web_root / "out" / "traces"
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_id = (trace_id or "trace").replace("/", "_").replace("\\", "_")
            p = out_dir / f"{label}_{safe_id}_{trace_slug}.txt"
            p.write_text(text, encoding="utf-8")
            return str(p)
        except Exception:
            return ""

    def _write_trace_json(label: str, obj: Any) -> str:
        if not trace_enabled:
            return ""
        try:
            payload = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
        except Exception:
            payload = str(obj)
        return _write_trace_artifact(label, payload)

    def _auto_prune_traces() -> None:
        """Best-effort: keep last N traces (by meta file mtime), delete older siblings."""

        if not trace_enabled:
            return
        if trace_keep_last <= 0:
            return

        try:
            web_root = Path(__file__).resolve().parent
            out_dir = web_root / "out" / "traces"
            if not out_dir.exists():
                return

            metas = [p for p in out_dir.glob("edit_response_meta_*.txt") if p.is_file()]
            metas.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            keep = metas[:trace_keep_last]

            keep_keys = set()
            for p in keep:
                parts = p.stem.rsplit("_", 2)
                if len(parts) != 3:
                    continue
                _label, safe_id, ts = parts
                keep_keys.add((safe_id, ts))

            for p in [x for x in out_dir.glob("*.txt") if x.is_file()]:
                parts = p.stem.rsplit("_", 2)
                if len(parts) != 3:
                    continue
                _label, safe_id, ts = parts
                if (safe_id, ts) in keep_keys:
                    continue
                try:
                    p.unlink()
                except Exception:
                    pass
        except Exception:
            # Never fail the edit flow due to trace housekeeping.
            return

    def _create(*, max_tokens: int, include_temperature: bool) -> Any:
        nonlocal openai_request_id
        create_kwargs = dict(base_kwargs)
        create_kwargs["max_output_tokens"] = int(max_tokens)
        if include_temperature and not _model_rejects_temperature(model):
            create_kwargs["temperature"] = 0.2
        try:
            # Prefer raw response so we can log OpenAI request IDs.
            with_raw = getattr(
                getattr(client, "responses", None), "with_raw_response", None
            )
            if with_raw is not None:
                raw_resp = with_raw.create(**create_kwargs)
                # raw_resp: has headers + parse() method
                try:
                    req_id = raw_resp.headers.get(
                        "x-request-id"
                    ) or raw_resp.headers.get("x-openai-request-id")
                except Exception:
                    req_id = None
                if req_id:
                    openai_request_id = str(req_id)
                    _LOG.info(
                        "edit.propose.openai trace_id=%s request_id=%s",
                        trace_id or "-",
                        req_id,
                    )
                return raw_resp.parse()

            return client.responses.create(**create_kwargs)
        except Exception as e:
            msg = str(e)
            # Some models reject temperature; retry once without it.
            if (
                include_temperature
                and "Unsupported parameter" in msg
                and "temperature" in msg
            ):
                try:
                    create_kwargs.pop("temperature", None)
                    with_raw = getattr(
                        getattr(client, "responses", None), "with_raw_response", None
                    )
                    if with_raw is not None:
                        raw_resp = with_raw.create(**create_kwargs)
                        try:
                            req_id = raw_resp.headers.get(
                                "x-request-id"
                            ) or raw_resp.headers.get("x-openai-request-id")
                        except Exception:
                            req_id = None
                        if req_id:
                            openai_request_id = str(req_id)
                        return raw_resp.parse()
                    return client.responses.create(**create_kwargs)
                except Exception as e2:
                    raise RuntimeError(f"OpenAI editor request failed: {e2}")
            req_id = getattr(e, "request_id", None)
            _LOG.error(
                "edit.propose.request_failed trace_id=%s request_id=%s err=%r",
                trace_id or "-",
                req_id or "-",
                msg,
            )
            raise RuntimeError(f"OpenAI editor request failed: {msg}")

    resp = _create(max_tokens=max_output_tokens, include_temperature=True)
    resp_used = resp

    raw = getattr(resp, "output_text", None)
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("OpenAI editor response parsing failed: no output_text")

    _LOG.info(
        "edit.propose.response trace_id=%s output_len=%d",
        trace_id or "-",
        len(raw),
    )

    # Optional trace artifacts for debugging (off by default).
    trace_request_path = ""
    trace_raw_path = ""
    trace_parsed_path = ""
    trace_meta_path = ""
    if trace_enabled:
        trace_request_path = _write_trace_json(
            "edit_request",
            {
                "traceId": trace_id,
                "model": model,
                "targetKey": target_key,
                "maxOutputTokens": max_output_tokens,
                "userPayload": user_payload,
                "systemPrompt": _EDITOR_SYSTEM_PROMPT,
            },
        )
        trace_raw_path = _write_trace_artifact(
            "edit_response_raw",
            f"trace_id={trace_id}\nmodel={model}\ntarget_key={target_key}\nopenai_request_id={openai_request_id or '-'}\n\nRAW:\n{raw}\n",
        )

    def _try_parse_or_retry(first_raw: str) -> Dict[str, Any]:
        nonlocal resp_used
        try:
            parsed = json.loads(first_raw)
            return parsed if isinstance(parsed, dict) else {"_non_dict": parsed}
        except Exception as e:
            # Most common cause: output truncation mid-JSON due to max_output_tokens.
            tail = (
                first_raw[-200:].replace("\n", "\\n")
                if isinstance(first_raw, str)
                else ""
            )
            likely_trunc = isinstance(first_raw, str) and (
                not first_raw.rstrip().endswith("}")
            )
            if likely_trunc and max_output_tokens < 8000:
                bumped = _clamp_int(
                    max_output_tokens * 2, max_output_tokens + 200, 8000
                )
                _LOG.warning(
                    "edit.propose.parse_failed_retry trace_id=%s err=%r max_output_tokens=%d bumped=%d tail=%r",
                    trace_id or "-",
                    str(e),
                    max_output_tokens,
                    bumped,
                    tail,
                )
                resp2 = _create(max_tokens=bumped, include_temperature=False)
                raw2 = getattr(resp2, "output_text", None)
                if isinstance(raw2, str) and raw2.strip():
                    try:
                        parsed2 = json.loads(raw2)
                        resp_used = resp2
                        return (
                            parsed2
                            if isinstance(parsed2, dict)
                            else {"_non_dict": parsed2}
                        )
                    except Exception:
                        tail2 = raw2[-200:].replace("\n", "\\n")
                        trace_path = _write_trace_artifact(
                            "edit_non_json",
                            f"trace_id={trace_id}\nmodel={model}\ntarget_key={target_key}\nmax_output_tokens={max_output_tokens}\nbumped={bumped}\n\nRAW1:\n{first_raw}\n\nRAW2:\n{raw2}\n",
                        )
                        raise RuntimeError(
                            f"OpenAI editor returned non-JSON: {e} (possible truncation; tried max_output_tokens={max_output_tokens} then {bumped}); tail={tail!r}; tail2={tail2!r}; trace={trace_path or '-'}"
                        )
            hint = ""
            if likely_trunc:
                hint = f" (possible truncation; max_output_tokens={max_output_tokens})"
            trace_path = _write_trace_artifact(
                "edit_non_json",
                f"trace_id={trace_id}\nmodel={model}\ntarget_key={target_key}\nmax_output_tokens={max_output_tokens}\n\nRAW:\n{first_raw}\n",
            )
            raise RuntimeError(
                f"OpenAI editor returned non-JSON: {e}{hint}; tail={tail!r}; trace={trace_path or '-'}"
            )

    obj = _try_parse_or_retry(raw)

    if trace_enabled:
        trace_parsed_path = _write_trace_json("edit_response_parsed", obj)

    if not isinstance(obj, dict):
        raise RuntimeError("OpenAI editor returned non-object JSON")

    def _extract_usage_dict(r: Any) -> Dict[str, int]:
        usage_obj = getattr(r, "usage", None)
        if usage_obj is None:
            return {
                "inputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 0,
                "cachedTokens": 0,
            }

        def _get_int(u: Any, key: str) -> int:
            try:
                if isinstance(u, dict):
                    v = u.get(key)
                else:
                    v = getattr(u, key, None)
                return int(v or 0)
            except Exception:
                return 0

        input_tokens = _get_int(usage_obj, "input_tokens")
        output_tokens = _get_int(usage_obj, "output_tokens")
        total_tokens = _get_int(usage_obj, "total_tokens")
        if total_tokens <= 0:
            total_tokens = max(0, input_tokens + output_tokens)

        cached_tokens = 0
        try:
            details = (
                usage_obj.get("input_tokens_details")
                if isinstance(usage_obj, dict)
                else getattr(usage_obj, "input_tokens_details", None)
            )
            if details is not None:
                cached_tokens = _get_int(details, "cached_tokens")
            else:
                cached_tokens = _get_int(usage_obj, "cached_tokens")
        except Exception:
            cached_tokens = 0

        cached_tokens = max(0, min(int(cached_tokens or 0), int(input_tokens or 0)))
        return {
            "inputTokens": int(input_tokens or 0),
            "outputTokens": int(output_tokens or 0),
            "totalTokens": int(total_tokens or 0),
            "cachedTokens": int(cached_tokens or 0),
        }

    model_used = str(getattr(resp_used, "model", "") or "").strip() or model
    usage_dict = _extract_usage_dict(resp_used)

    if trace_enabled:
        trace_meta_path = _write_trace_json(
            "edit_response_meta",
            {
                "traceId": trace_id,
                "openaiRequestId": openai_request_id or "",
                "modelRequested": model,
                "modelUsed": model_used,
                "usage": usage_dict,
                "requestArtifact": trace_request_path,
                "rawArtifact": trace_raw_path,
                "parsedArtifact": trace_parsed_path,
            },
        )
        _LOG.info(
            "edit.propose.trace trace_id=%s req=%s raw=%s parsed=%s meta=%s",
            trace_id or "-",
            trace_request_path or "-",
            trace_raw_path or "-",
            trace_parsed_path or "-",
            trace_meta_path or "-",
        )
        _auto_prune_traces()

    def _with_meta(d: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(d)
        out["modelUsed"] = model_used
        out["usage"] = usage_dict
        if trace_enabled:
            out["openaiRequestId"] = openai_request_id or ""
            out["traceArtifacts"] = {
                "request": trace_request_path,
                "raw": trace_raw_path,
                "parsed": trace_parsed_path,
                "meta": trace_meta_path,
            }
        return out

    # Normalize + apply guardrails; never return an applyable proposal that fails validation.
    obj.setdefault("warnings", [])
    if obj.get("targetKey") != target_key:
        return _with_meta(
            {
                "status": "refused",
                "targetKey": target_key,
                "updatedText": current_text,
                "rationale": "Model proposed a different targetKey; refusing.",
                "warnings": ["target_key_mismatch"],
                "selfCheck": False,
                "refusalReason": "targetKey mismatch",
            }
        )

    updated_text = obj.get("updatedText")
    if not isinstance(updated_text, str):
        return _with_meta(
            {
                "status": "error",
                "targetKey": target_key,
                "updatedText": current_text,
                "rationale": "Model did not return updatedText as a string.",
                "warnings": ["invalid_updated_text"],
                "selfCheck": False,
                "refusalReason": "",
            }
        )

    errors = validate_prompt_edit(
        target_key=target_key, current_text=current_text, updated_text=updated_text
    )
    if errors or obj.get("selfCheck") is False or obj.get("status") != "ok":
        refusal = (
            obj.get("refusalReason")
            if isinstance(obj.get("refusalReason"), str)
            else ""
        )
        combined = "; ".join([x for x in [refusal] if x] + errors)
        return _with_meta(
            {
                "status": "refused",
                "targetKey": target_key,
                "updatedText": current_text,
                "rationale": (
                    obj.get("rationale")
                    if isinstance(obj.get("rationale"), str)
                    else ""
                ),
                "warnings": (
                    (obj.get("warnings") or [])
                    if isinstance(obj.get("warnings"), list)
                    else []
                ),
                "selfCheck": False,
                "refusalReason": combined or "Proposal failed validation.",
            }
        )

    return _with_meta(obj)


def _collapse_blank_lines(s: str) -> str:
    s = s.replace("\r\n", "\n")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip() + "\n"


def _render_template(template: str, template_vars: Dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        return str(template_vars.get(key, ""))

    rendered = _TEMPLATE_VAR_RE.sub(repl, template)
    return _collapse_blank_lines(rendered)


def _tie_in_block(tie_in: str) -> str:
    cleaned = (tie_in or "").strip()
    if not cleaned:
        return ""
    return f"Naturally work in this topic if possible: {cleaned}"


def load_fixture_files(
    fixtures_dir: Path, mode: str, *, app_id: str = "", only_fixture: str = ""
) -> List[Path]:
    """Return fixture files for a mode.

    Preferred layout:
      fixtures/<appId>/<mode>/*.{txt,json}

    Legacy fallback:
      fixtures/<mode>/*.{txt,json}
    """

    mode = mode.strip()
    app_id = app_id.strip()
    only_norm = (only_fixture or "").strip()

    searched: List[Path] = []
    files: List[Path] = []

    mode_dir = fixtures_dir / app_id / mode if app_id else fixtures_dir / mode
    searched.append(mode_dir)
    if app_id and not mode_dir.exists():
        mode_dir = fixtures_dir / mode
        searched.append(mode_dir)

    if mode_dir.exists():
        files = sorted(
            [
                p
                for p in list(mode_dir.glob("*.txt")) + list(mode_dir.glob("*.json"))
                if p.is_file()
            ]
        )

    if not files:
        raise FileNotFoundError(
            "Missing fixtures. Searched: " + ", ".join(str(p) for p in searched)
        )

    if only_norm:
        matched = [p for p in files if p.name == only_norm or p.stem == only_norm]
        if not matched:
            raise FileNotFoundError(f"Fixture '{only_norm}' not found in {mode_dir}")
        return matched

    return files


def render_fixture_user_prompt(fx: Path, *, mode: str, user_template: str) -> str:
    """Render a fixture into a user prompt.

    - .txt fixtures are treated as already-rendered user prompts.
    - .json fixtures are structured and rendered through the per-mode user template.
    """

    if fx.suffix.lower() == ".txt":
        return fx.read_text(encoding="utf-8").strip()

    if fx.suffix.lower() != ".json":
        raise ValueError(f"Unsupported fixture type: {fx.name}")

    payload = json.loads(fx.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Fixture JSON must be an object: {fx.name}")

    raw_override = payload.get("user_prompt")
    if isinstance(raw_override, str) and raw_override.strip():
        return raw_override.strip()

    if not (user_template or "").strip():
        raise ValueError(
            f"No user template found for mode '{mode}', but fixture is .json: {fx.name}"
        )

    tie_in = str(payload.get("tie_in") or "")
    template_vars: Dict[str, str] = {
        "tie_in": tie_in,
        "tie_in_block": _tie_in_block(tie_in),
        "profile_text": str(payload.get("profile_text") or ""),
        "chat_transcript": str(payload.get("chat_transcript") or ""),
    }
    return _render_template(user_template, template_vars)


def load_fixtures(
    fixtures_dir: Path, mode: str, app_id: str = ""
) -> List[Tuple[str, str]]:
    """Load fixtures for a mode.

    Preferred layout:
      fixtures/<appId>/<mode>/*.txt

    Legacy fallback:
      fixtures/<mode>/*.txt
    """
    mode = mode.strip()
    app_id = app_id.strip()

    searched: List[Path] = []

    mode_dir = fixtures_dir / app_id / mode if app_id else fixtures_dir / mode
    searched.append(mode_dir)
    if app_id and not mode_dir.exists():
        mode_dir = fixtures_dir / mode
        searched.append(mode_dir)

    if not mode_dir.exists():
        raise FileNotFoundError(
            f"Missing fixtures dir. Searched: {', '.join(str(p) for p in searched)}"
        )

    items: List[Tuple[str, str]] = []
    for p in sorted(mode_dir.glob("*.txt")):
        text = p.read_text(encoding="utf-8").strip()
        if not text:
            continue
        items.append((p.stem, text))

    if not items:
        raise ValueError(f"No .txt fixtures found in {mode_dir}")

    return items


def ensure_api_key() -> None:
    key = os.getenv("OPENAI_API_KEY")
    if not key or not key.strip():
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Create tools/workbench-web/.env.local (gitignored) with OPENAI_API_KEY=..."
        )
    # Never print the key. Basic sanity: avoid strings that look like a placeholder.
    if "<" in key or ">" in key:
        raise RuntimeError("OPENAI_API_KEY looks like a placeholder; set a real key")


def build_messages(system_prompt: str, user_text: str) -> List[Dict[str, Any]]:
    # Responses API supports chat-style role messages in `input`.
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]


def _usage_to_dict(usage: Any) -> Dict[str, Any]:
    """Normalize usage from OpenAI SDK into a JSON-serializable dict.

    The Responses API usage shape can vary by SDK version/model. We keep this
    defensive and only extract fields we care about.
    """

    def _get(obj: Any, key: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    def _as_int(v: Any) -> Optional[int]:
        try:
            if v is None:
                return None
            return int(v)
        except Exception:
            return None

    input_tokens = _as_int(_get(usage, "input_tokens"))
    output_tokens = _as_int(_get(usage, "output_tokens"))
    total_tokens = _as_int(_get(usage, "total_tokens"))

    input_details = _get(usage, "input_tokens_details")
    cached_tokens = _as_int(_get(input_details, "cached_tokens"))

    out: Dict[str, Any] = {}
    if input_tokens is not None:
        out["inputTokens"] = input_tokens
    if output_tokens is not None:
        out["outputTokens"] = output_tokens
    if total_tokens is not None:
        out["totalTokens"] = total_tokens
    if cached_tokens is not None:
        out["cachedTokens"] = cached_tokens
    return out


def _model_rejects_temperature(model: str) -> bool:
    """Return True for models known to reject `temperature` in the Responses API.

    The OpenAI API surface is model-dependent; GPT-5 and o-series reasoning models
    may reject sampling params like `temperature`.
    """

    m = (model or "").strip().lower()
    if not m:
        return False
    # GPT-5 family (gpt-5, gpt-5-mini, gpt-5.2, etc.)
    if m.startswith("gpt-5"):
        return True
    # o-series reasoning models (o1, o3, o4-mini, etc.).
    # Avoid matching unrelated models like omni-moderation-latest.
    if re.match(r"^o\d", m):
        return True
    return False


def call_openai(
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_output_tokens: int,
) -> Tuple[str, Dict[str, Any]]:
    from openai import OpenAI

    client = OpenAI()

    create_kwargs: Dict[str, Any] = {
        "model": model,
        "input": messages,
        "max_output_tokens": max_output_tokens,
    }
    if not _model_rejects_temperature(model):
        create_kwargs["temperature"] = temperature
    try:
        resp = client.responses.create(**create_kwargs)
    except Exception as e:
        # Some models (e.g. o-series) reject temperature.
        # Detect via SDK .param attribute or message text; retry once without it.
        is_temp_unsupported = (
            getattr(e, "param", None) == "temperature"
            or "temperature" in str(e).lower()
        )
        if is_temp_unsupported:
            create_kwargs.pop("temperature", None)
            resp = client.responses.create(**create_kwargs)
        else:
            raise

    # Detect reasoning-model token exhaustion: the model consumed the entire
    # budget on internal reasoning, leaving no tokens for the output message
    # (status='incomplete', reasoning_tokens ≈ output_tokens).  Retry once with
    # 3× the budget so the model can actually produce a reply.
    if getattr(resp, "status", None) == "incomplete":
        used = getattr(resp, "usage", None)
        reasoning_tokens: int = 0
        if used:
            details = getattr(used, "output_tokens_details", None)
            if details:
                reasoning_tokens = int(getattr(details, "reasoning_tokens", 0) or 0)
        output_tokens_used = int(getattr(used, "output_tokens", 0) or 0)
        if reasoning_tokens >= max(output_tokens_used - 1, 1):
            bumped = min(max_output_tokens * 3, 4000)
            create_kwargs["max_output_tokens"] = bumped
            resp = client.responses.create(**create_kwargs)

    usage_dict = _usage_to_dict(getattr(resp, "usage", None))

    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip(), usage_dict

    # Fallback: best-effort extraction from output items.
    try:
        chunks: List[str] = []
        for item in resp.output:
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", "") == "output_text":
                    chunks.append(getattr(c, "text", ""))
        out = "".join(chunks).strip()
        if out:
            return out, usage_dict
    except Exception:
        pass

    status = getattr(resp, "status", "unknown")
    raise RuntimeError(
        f"OpenAI response parsing failed: no text output "
        f"(status={status}, max_output_tokens={max_output_tokens})"
    )


def basic_heuristic_flags(mode: str, text: str) -> List[str]:
    flags: List[str] = []
    t = text.strip()

    if re.search(r"\b(chatgpt|openai|as an ai|i am an ai)\b", t, re.IGNORECASE):
        flags.append("mentions_ai")

    if '"' in t or "\u201c" in t or "\u201d" in t:
        flags.append("contains_quotes")

    if ":" in t:
        flags.append("contains_colon")

    # Common dash-like chars: -, – , —
    if any(ch in t for ch in ["-", "–", "—"]):
        flags.append("contains_dash")

    if mode in ("opener", "app_chat") and re.search(r"\bcoffee\b", t, re.IGNORECASE):
        flags.append("mentions_coffee")

    if mode == "opener":
        # 1–2 lines max.
        if t.count("\n") >= 2:
            flags.append("too_many_lines_for_opener")

    if not t:
        flags.append("empty_output")

    return flags


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_output(out_dir: Path, mode: str, fixture_name: str, content: str) -> Path:
    p = out_dir / mode / f"{fixture_name}.txt"
    write_text(p, content)
    return p


def unified_diff(a: str, b: str, a_label: str, b_label: str) -> str:
    a_lines = a.splitlines(keepends=True)
    b_lines = b.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(a_lines, b_lines, fromfile=a_label, tofile=b_label)
    )


def run_one(
    *,
    mode: str,
    model: str,
    temperature: float,
    max_output_tokens: int,
    system_prompt: str,
    fixtures: Sequence[Tuple[str, str]],
    out_root: Path,
    variant: str,
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}

    for name, user_text in fixtures:
        messages = build_messages(system_prompt=system_prompt, user_text=user_text)
        try:
            output, usage = call_openai(
                model=model,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            error: Optional[str] = None
        except Exception as e:
            output = ""
            usage = {}
            error = f"{type(e).__name__}: {e}"

        flags = basic_heuristic_flags(mode, output)

        # Store artifact.
        safe = output if output else (f"[ERROR] {error}" if error else "")
        out_path = out_root / variant
        write_output(out_path, mode, name, safe)

        results[name] = {
            "input": user_text,
            "output": output,
            "error": error,
            "flags": flags,
            "chars": len(output),
            "usage": usage,
        }

    return results


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_ab_report_html(
    out_root: Path,
    mode: str,
    fixtures: Sequence[str],
    diff_index: Dict[str, Any],
) -> Path:
    parts: List[str] = []
    parts.append("<!doctype html><html><head><meta charset='utf-8'>")
    parts.append("<title>Prompt Workbench A/B Report</title>")
    parts.append(
        "<style>body{font-family:system-ui,Segoe UI,Arial;max-width:1100px;margin:24px auto;padding:0 12px;}"
        "h1{margin:0 0 12px} .meta{color:#444;margin:0 0 18px}"
        "pre{white-space:pre-wrap;background:#0b0f14;color:#e6edf3;padding:12px;border-radius:8px;overflow:auto}"
        ".grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}"
        ".card{border:1px solid #ddd;border-radius:10px;padding:12px}"
        ".flags{font-size:12px;color:#b45309}"
        "a{color:#2563eb;text-decoration:none} a:hover{text-decoration:underline}"
        "</style>"
    )
    parts.append("</head><body>")
    parts.append(f"<h1>A/B Report — { _html_escape(mode) }</h1>")
    parts.append(f"<p class='meta'>Out: {_html_escape(str(out_root))}</p>")
    parts.append("<ol>")
    for name in fixtures:
        parts.append(
            f"<li><a href='#f-{_html_escape(name)}'>{_html_escape(name)}</a></li>"
        )
    parts.append("</ol>")

    for name in fixtures:
        item = diff_index.get(name) or {}
        base = item.get("baseline") or {}
        cand = item.get("candidate") or {}
        diff_file = item.get("diffFile") or ""

        btxt = base.get("output") or (
            "[ERROR] " + str(base.get("error")) if base.get("error") else ""
        )
        ctxt = cand.get("output") or (
            "[ERROR] " + str(cand.get("error")) if cand.get("error") else ""
        )

        bflags = ",".join(base.get("flags") or [])
        cflags = ",".join(cand.get("flags") or [])

        parts.append(f"<hr><h2 id='f-{_html_escape(name)}'>{_html_escape(name)}</h2>")
        parts.append("<div class='grid'>")
        parts.append("<div class='card'>")
        parts.append(
            f"<div><strong>Baseline</strong> <span class='flags'>{_html_escape(bflags) if bflags else ''}</span></div>"
        )
        parts.append(f"<pre>{_html_escape(str(btxt))}</pre>")
        parts.append("</div>")
        parts.append("<div class='card'>")
        parts.append(
            f"<div><strong>Candidate</strong> <span class='flags'>{_html_escape(cflags) if cflags else ''}</span></div>"
        )
        parts.append(f"<pre>{_html_escape(str(ctxt))}</pre>")
        parts.append("</div>")
        parts.append("</div>")

        if diff_file:
            parts.append(f"<p>Diff file: {_html_escape(diff_file)}</p>")

    parts.append("</body></html>")
    report_path = out_root / "ab_report.html"
    write_text(report_path, "\n".join(parts))
    return report_path


def _load_dotenv_if_present(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ if not already set.

    This is intentionally minimal (no external dependency) and only for local dev.
    Supported files (checked in this order):
    - .env.local
    - .env

    Lines starting with # are ignored.
    Values may be quoted with single or double quotes.
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if not k:
            continue
        # Don't override real env vars.
        if os.getenv(k) is None:
            os.environ[k] = v


def _prompt_choice(label: str, choices: Sequence[str], default: str) -> str:
    print(f"\n{label}")
    for i, c in enumerate(choices, start=1):
        d = " (default)" if c == default else ""
        print(f"  {i}) {c}{d}")
    while True:
        raw = input(f"Select 1-{len(choices)} [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        if raw in choices:
            return raw
        print("Invalid selection.")


def _prompt_int(label: str, default: int, min_v: int, max_v: int) -> int:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            v = int(raw)
            if v < min_v or v > max_v:
                raise ValueError()
            return v
        except Exception:
            print(f"Enter an integer between {min_v} and {max_v}.")


def interactive_flow(default_prompts_url: str) -> int:
    print("Prompt Workbench — Interactive")
    print(
        "This will call the OpenAI API and save outputs under tools/prompt_workbench/out/<timestamp>."
    )
    print("Key source: OPENAI_API_KEY (recommended: put it in .env.local once)")

    mode = _prompt_choice("Which prompt mode?", list(MODES), default="reg_chat")

    run_type = _prompt_choice(
        "What do you want to do?",
        [
            "A/B compare (baseline vs candidate) — recommended for prompt editing",
            "Single run (local prompts) — quick check",
            "Single run (remote prompts URL) — test what the app fetches",
        ],
        default="A/B compare (baseline vs candidate) — recommended for prompt editing",
    )

    print("\nFixture count (what 'max fixtures' means)")
    print(
        "- Fixtures are the text files in tools/prompt_workbench/fixtures/<mode>/*.txt"
    )
    print("- max fixtures = how many of those test inputs to run")
    print("- Use 1–3 while iterating; use 0 to run ALL for confidence")
    max_fx = _prompt_int(
        "How many fixtures to run? (0 = all)", default=3, min_v=0, max_v=200
    )

    argv: List[str] = ["--mode", mode]
    if max_fx > 0:
        argv += ["--max-fixtures", str(max_fx)]

    # Always try to load local env first (.env.local) but env vars still win.
    argv += ["--load-env"]

    if run_type.startswith("Single run (remote"):
        url = (
            input(f"Remote prompts URL [{default_prompts_url}]: ").strip()
            or default_prompts_url
        )
        argv += ["--prompts-url", url]
        return main_argv(argv)

    if run_type.startswith("A/B compare"):
        argv += ["--baseline-prompts-path", "baseline_prompts.json"]
        argv += ["--candidate-prompts-path", "candidate_prompts.json"]
        return main_argv(argv)

    # Single run (local prompts)
    return main_argv(argv)


# Split core execution so interactive can call it


def _try_open_path(path: Path) -> None:
    """Best-effort open a file or folder using the OS default handler."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        # mac/linux best-effort
        subprocess.Popen(
            ["open" if sys.platform == "darwin" else "xdg-open", str(path)]
        )
    except Exception:
        pass


def main_argv(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Prompt Workbench")
    parser.add_argument(
        "--app-id",
        type=str,
        default="",
        help="Optional appId used for prompts/fixtures defaults",
    )
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--max-fixtures", type=int, default=0, help="0 = all")
    parser.add_argument(
        "--only-fixture",
        type=str,
        default="",
        help="Optional fixture selector (matches file name or stem)",
    )

    parser.add_argument(
        "--out-dir",
        type=str,
        default="",
        help="Override output directory (defaults to tools/workbench-web/out)",
    )

    parser.add_argument(
        "--fixtures-dir",
        type=str,
        default="",
        help="Override fixtures dir (defaults to ./fixtures)",
    )

    # Single-run prompt source
    parser.add_argument("--prompts-path", type=str, default="")
    parser.add_argument("--prompts-url", type=str, default="")

    # A/B compare
    parser.add_argument("--baseline-prompts-path", type=str, default="")
    parser.add_argument("--baseline-prompts-url", type=str, default="")
    parser.add_argument("--candidate-prompts-path", type=str, default="")
    parser.add_argument("--candidate-prompts-url", type=str, default="")

    # Optional override system prompt text directly
    parser.add_argument("--system-override-file", type=str, default="")

    # Utility
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No OpenAI calls. Writes placeholder outputs + manifest.",
    )
    parser.add_argument(
        "--load-env",
        action="store_true",
        help="Load OPENAI_API_KEY (and other vars) from .env.local/.env in tools/workbench-web (gitignored).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the output folder (and ab_report.html for A/B runs) after the run completes.",
    )

    args = parser.parse_args(list(argv))

    # Determine run mode: A/B or single.
    ab_enabled = any(
        [
            args.baseline_prompts_path,
            args.baseline_prompts_url,
            args.candidate_prompts_path,
            args.candidate_prompts_url,
        ]
    )

    if ab_enabled:
        if not (args.baseline_prompts_path or args.baseline_prompts_url):
            raise ValueError(
                "A/B enabled: provide --baseline-prompts-path or --baseline-prompts-url"
            )
        if not (args.candidate_prompts_path or args.candidate_prompts_url):
            raise ValueError(
                "A/B enabled: provide --candidate-prompts-path or --candidate-prompts-url"
            )

    # Load local env BEFORE key checks.
    if args.load_env:
        here = Path(__file__).resolve().parent
        _load_dotenv_if_present(here / ".env.local")
        _load_dotenv_if_present(here / ".env")

    # Repo paths
    repo_root = _repo_root()

    # Default prompt path (used if caller doesn't provide --prompts-path / --prompts-url)
    app_id = (args.app_id or "").strip()
    if app_id:
        default_prompts_path = repo_root / "prompts" / f"{app_id}.json"
    else:
        # Best-effort: use the first prompts/*.json file
        candidates = sorted((repo_root / "prompts").glob("*.json"))
        default_prompts_path = (
            candidates[0] if candidates else (repo_root / "prompts" / "template.json")
        )

    # Load fixture files (rendering happens after we know which prompt bundle we use).
    fixtures_dir = (
        Path(args.fixtures_dir).resolve()
        if args.fixtures_dir
        else (repo_root / "fixtures")
    )
    fixture_files = load_fixture_files(
        fixtures_dir, args.mode, app_id=app_id, only_fixture=args.only_fixture
    )
    if args.max_fixtures and args.max_fixtures > 0:
        fixture_files = fixture_files[: args.max_fixtures]

    out_base = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else (Path(__file__).resolve().parent / "out")
    )

    if args.validate_only:
        # Validate prompt loading (single-run only) + fixtures presence.
        bundle, source_kind, source_id = load_prompts_bundle(
            prompts_path=(
                Path(args.prompts_path).resolve() if args.prompts_path else None
            ),
            prompts_url=args.prompts_url,
            default_prompts_path=default_prompts_path,
        )
        sp = system_prompt_for_mode(bundle, args.mode)
        if args.system_override_file:
            sp = _read_text_file(Path(args.system_override_file))

        # Validate fixture rendering (supports both .txt and structured .json).
        ut = user_template_for_mode(bundle, args.mode)
        _ = [
            (p.stem, render_fixture_user_prompt(p, mode=args.mode, user_template=ut))
            for p in fixture_files
        ]

        print(f"OK: fixtures loaded: {len(fixture_files)} for mode={args.mode}")
        print(f"OK: prompts loaded: {source_kind} {source_id}")
        print(f"System prompt sha256={_sha256_text(sp)[:12]}…")
        return 0

    if args.dry_run:
        # Dry run: ensure we can load prompts/fixtures and write artifacts without network.
        out_root = out_base / _utc_timestamp_slug()
        out_root.mkdir(parents=True, exist_ok=True)

        git_sha = _try_git_head_sha(repo_root)
        manifest: Dict[str, Any] = {
            "startedAtUtc": _utc_now_iso(),
            "mode": args.mode,
            "model": args.model,
            "temperature": args.temperature,
            "maxOutputTokens": args.max_output_tokens,
            "fixturesDir": str(fixtures_dir),
            "fixtures": [p.stem for p in fixture_files],
            "gitHeadSha": git_sha,
            "dryRun": True,
        }

        if not ab_enabled:
            # Load prompt (single-run only)
            bundle, source_kind, source_id = load_prompts_bundle(
                prompts_path=(
                    Path(args.prompts_path).resolve() if args.prompts_path else None
                ),
                prompts_url=args.prompts_url,
                default_prompts_path=default_prompts_path,
            )
            system_prompt = system_prompt_for_mode(bundle, args.mode)
            if args.system_override_file:
                system_prompt = _read_text_file(Path(args.system_override_file))

            user_template = user_template_for_mode(bundle, args.mode)
            fixtures = [
                (
                    p.stem,
                    render_fixture_user_prompt(
                        p, mode=args.mode, user_template=user_template
                    ),
                )
                for p in fixture_files
            ]

            manifest.update(
                {
                    "promptsSourceKind": source_kind,
                    "promptsSourceId": source_id,
                    "systemPromptSha256": _sha256_text(system_prompt),
                    "promptsUpdatedAt": bundle.updated_at,
                    "promptsTtlSeconds": bundle.ttl_seconds,
                }
            )

            # Write placeholder outputs.
            results: Dict[str, Dict[str, Any]] = {}
            for name, _ in fixtures:
                placeholder = f"[DRY_RUN] fixture={name} mode={args.mode}"
                flags = basic_heuristic_flags(args.mode, placeholder)
                write_output(out_root / "single", args.mode, name, placeholder)
                results[name] = {
                    "input": dict(fixtures).get(name, ""),
                    "output": placeholder,
                    "error": None,
                    "flags": flags,
                    "chars": len(placeholder),
                    "usage": {},
                }

            write_text(out_root / "run.json", json.dumps(manifest, indent=2))
            write_text(out_root / "summary.json", json.dumps(results, indent=2))
            print(f"Out={out_root}")
            print("Done")
            _auto_prune_out_runs(out_base)
            return 0

        # A/B dry run
        baseline_bundle, baseline_kind, baseline_id = load_prompts_bundle(
            prompts_path=(
                Path(args.baseline_prompts_path).resolve()
                if args.baseline_prompts_path
                else None
            ),
            prompts_url=args.baseline_prompts_url,
            default_prompts_path=default_prompts_path,
        )
        candidate_bundle, candidate_kind, candidate_id = load_prompts_bundle(
            prompts_path=(
                Path(args.candidate_prompts_path).resolve()
                if args.candidate_prompts_path
                else None
            ),
            prompts_url=args.candidate_prompts_url,
            default_prompts_path=default_prompts_path,
        )

        baseline_sp = system_prompt_for_mode(baseline_bundle, args.mode)
        candidate_sp = system_prompt_for_mode(candidate_bundle, args.mode)
        if args.system_override_file:
            override = _read_text_file(Path(args.system_override_file))
            baseline_sp = override
            candidate_sp = override

        manifest.update(
            {
                "ab": {
                    "baseline": {
                        "promptsSourceKind": baseline_kind,
                        "promptsSourceId": baseline_id,
                        "promptsUpdatedAt": baseline_bundle.updated_at,
                        "systemPromptSha256": _sha256_text(baseline_sp),
                    },
                    "candidate": {
                        "promptsSourceKind": candidate_kind,
                        "promptsSourceId": candidate_id,
                        "promptsUpdatedAt": candidate_bundle.updated_at,
                        "systemPromptSha256": _sha256_text(candidate_sp),
                    },
                }
            }
        )

        baseline_ut = user_template_for_mode(baseline_bundle, args.mode)
        candidate_ut = user_template_for_mode(candidate_bundle, args.mode)

        baseline_fixtures = [
            (
                p.stem,
                render_fixture_user_prompt(
                    p, mode=args.mode, user_template=baseline_ut
                ),
            )
            for p in fixture_files
        ]
        candidate_fixtures = [
            (
                p.stem,
                render_fixture_user_prompt(
                    p, mode=args.mode, user_template=candidate_ut
                ),
            )
            for p in fixture_files
        ]

        baseline_input_by_name = {n: t for (n, t) in baseline_fixtures}
        candidate_input_by_name = {n: t for (n, t) in candidate_fixtures}

        baseline_results: Dict[str, Dict[str, Any]] = {}
        candidate_results: Dict[str, Dict[str, Any]] = {}

        for name, _ in baseline_fixtures:
            btxt = f"[DRY_RUN] variant=baseline fixture={name} mode={args.mode}"
            ctxt = f"[DRY_RUN] variant=candidate fixture={name} mode={args.mode}"

            bflags = basic_heuristic_flags(args.mode, btxt)
            cflags = basic_heuristic_flags(args.mode, ctxt)

            write_output(out_root / "baseline", args.mode, name, btxt)
            write_output(out_root / "candidate", args.mode, name, ctxt)

            baseline_results[name] = {
                "input": baseline_input_by_name.get(name, ""),
                "output": btxt,
                "error": None,
                "flags": bflags,
                "chars": len(btxt),
                "usage": {},
            }
            candidate_results[name] = {
                "input": candidate_input_by_name.get(name, ""),
                "output": ctxt,
                "error": None,
                "flags": cflags,
                "chars": len(ctxt),
                "usage": {},
            }

        diffs_dir = out_root / "diffs" / args.mode
        diffs_dir.mkdir(parents=True, exist_ok=True)

        diff_index: Dict[str, Any] = {}
        for name, _ in baseline_fixtures:
            a = baseline_results[name]["output"] or ""
            b = candidate_results[name]["output"] or ""
            d = unified_diff(
                a, b, a_label=f"baseline/{name}", b_label=f"candidate/{name}"
            )
            write_text(
                diffs_dir / f"{name}.diff.txt", d if d.strip() else "[NO DIFF]\n"
            )

            diff_index[name] = {
                "baseline": baseline_results[name],
                "candidate": candidate_results[name],
                "diffFile": str((diffs_dir / f"{name}.diff.txt").resolve()),
            }

        try:
            report_path = write_ab_report_html(
                out_root=out_root,
                mode=args.mode,
                fixtures=[n for (n, _) in baseline_fixtures],
                diff_index=diff_index,
            )
            manifest["abReportHtml"] = str(report_path.resolve())
        except Exception:
            pass

        write_text(out_root / "run.json", json.dumps(manifest, indent=2))
        write_text(out_root / "ab_summary.json", json.dumps(diff_index, indent=2))
        print(f"Out={out_root}")
        print("Done")
        _auto_prune_out_runs(out_base)
        return 0

    # Real run requires key
    ensure_api_key()

    out_root = out_base / _utc_timestamp_slug()
    out_root.mkdir(parents=True, exist_ok=True)

    git_sha = _try_git_head_sha(repo_root)

    manifest: Dict[str, Any] = {
        "startedAtUtc": _utc_now_iso(),
        "mode": args.mode,
        "model": args.model,
        "temperature": args.temperature,
        "maxOutputTokens": args.max_output_tokens,
        "fixturesDir": str(fixtures_dir),
        "fixtures": [p.stem for p in fixture_files],
        "gitHeadSha": git_sha,
    }

    if not ab_enabled:
        bundle, source_kind, source_id = load_prompts_bundle(
            prompts_path=(
                Path(args.prompts_path).resolve() if args.prompts_path else None
            ),
            prompts_url=args.prompts_url,
            default_prompts_path=default_prompts_path,
        )
        system_prompt = system_prompt_for_mode(bundle, args.mode)
        if args.system_override_file:
            system_prompt = _read_text_file(Path(args.system_override_file))

        user_template = user_template_for_mode(bundle, args.mode)
        fixtures = [
            (
                p.stem,
                render_fixture_user_prompt(
                    p, mode=args.mode, user_template=user_template
                ),
            )
            for p in fixture_files
        ]
        fixture_input_by_name = {name: inp for name, inp in fixtures}

        manifest.update(
            {
                "promptsSourceKind": source_kind,
                "promptsSourceId": source_id,
                "systemPromptSha256": _sha256_text(system_prompt),
                "promptsUpdatedAt": bundle.updated_at,
                "promptsTtlSeconds": bundle.ttl_seconds,
            }
        )

        results = run_one(
            mode=args.mode,
            model=args.model,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
            system_prompt=system_prompt,
            fixtures=fixtures,
            out_root=out_root,
            variant="single",
        )

        write_text(out_root / "run.json", json.dumps(manifest, indent=2))
        write_text(out_root / "summary.json", json.dumps(results, indent=2))
        print(f"Out={out_root}")
        for name, r in results.items():
            flags = r["flags"]
            flag_str = (" flags=" + ",".join(flags)) if flags else ""
            err = r["error"]
            err_str = f" error={err}" if err else ""
            print(f"- {name}: {r['chars']} chars{flag_str}{err_str}")

            # Show input + output for the fixture (terminal-friendly, short)
            inp = fixture_input_by_name.get(name, "")
            if inp:
                print("  INPUT:")
                print("  " + "\n  ".join(inp.splitlines()))
            out_txt = r.get("output") or ("[ERROR] " + err if err else "")
            if out_txt:
                print("  OUTPUT:")
                print("  " + "\n  ".join(str(out_txt).splitlines()))
        print("Done")
        _auto_prune_out_runs(out_base)
        return 0

    # A/B mode
    baseline_bundle, baseline_kind, baseline_id = load_prompts_bundle(
        prompts_path=(
            Path(args.baseline_prompts_path).resolve()
            if args.baseline_prompts_path
            else None
        ),
        prompts_url=args.baseline_prompts_url,
        default_prompts_path=default_prompts_path,
    )
    candidate_bundle, candidate_kind, candidate_id = load_prompts_bundle(
        prompts_path=(
            Path(args.candidate_prompts_path).resolve()
            if args.candidate_prompts_path
            else None
        ),
        prompts_url=args.candidate_prompts_url,
        default_prompts_path=default_prompts_path,
    )

    baseline_sp = system_prompt_for_mode(baseline_bundle, args.mode)
    candidate_sp = system_prompt_for_mode(candidate_bundle, args.mode)

    baseline_ut = user_template_for_mode(baseline_bundle, args.mode)
    candidate_ut = user_template_for_mode(candidate_bundle, args.mode)

    baseline_fixtures = [
        (
            p.stem,
            render_fixture_user_prompt(p, mode=args.mode, user_template=baseline_ut),
        )
        for p in fixture_files
    ]
    candidate_fixtures = [
        (
            p.stem,
            render_fixture_user_prompt(p, mode=args.mode, user_template=candidate_ut),
        )
        for p in fixture_files
    ]

    fixture_names = [n for (n, _) in baseline_fixtures]

    if args.system_override_file:
        # If you override, it applies to BOTH (useful for quick experiments).
        override = _read_text_file(Path(args.system_override_file))
        baseline_sp = override
        candidate_sp = override

    manifest.update(
        {
            "ab": {
                "baseline": {
                    "promptsSourceKind": baseline_kind,
                    "promptsSourceId": baseline_id,
                    "promptsUpdatedAt": baseline_bundle.updated_at,
                    "systemPromptSha256": _sha256_text(baseline_sp),
                },
                "candidate": {
                    "promptsSourceKind": candidate_kind,
                    "promptsSourceId": candidate_id,
                    "promptsUpdatedAt": candidate_bundle.updated_at,
                    "systemPromptSha256": _sha256_text(candidate_sp),
                },
            }
        }
    )

    baseline_results = run_one(
        mode=args.mode,
        model=args.model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        system_prompt=baseline_sp,
        fixtures=baseline_fixtures,
        out_root=out_root,
        variant="baseline",
    )
    candidate_results = run_one(
        mode=args.mode,
        model=args.model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        system_prompt=candidate_sp,
        fixtures=candidate_fixtures,
        out_root=out_root,
        variant="candidate",
    )

    diffs_dir = out_root / "diffs" / args.mode
    diffs_dir.mkdir(parents=True, exist_ok=True)

    diff_index: Dict[str, Any] = {}
    for name in fixture_names:
        a = baseline_results[name]["output"] or ""
        b = candidate_results[name]["output"] or ""
        d = unified_diff(a, b, a_label=f"baseline/{name}", b_label=f"candidate/{name}")
        write_text(diffs_dir / f"{name}.diff.txt", d if d.strip() else "[NO DIFF]\n")

        diff_index[name] = {
            "baseline": baseline_results[name],
            "candidate": candidate_results[name],
            "diffFile": str((diffs_dir / f"{name}.diff.txt").resolve()),
        }

    # Human-friendly summary report
    try:
        report_path = write_ab_report_html(
            out_root=out_root,
            mode=args.mode,
            fixtures=fixture_names,
            diff_index=diff_index,
        )
        manifest["abReportHtml"] = str(report_path.resolve())
    except Exception:
        # Report generation must never fail the run.
        pass

    # Persist manifest AFTER we may have added abReportHtml
    write_text(out_root / "run.json", json.dumps(manifest, indent=2))
    write_text(out_root / "ab_summary.json", json.dumps(diff_index, indent=2))

    print(f"Out={out_root}")
    if manifest.get("abReportHtml"):
        print(f"ReportHtml={manifest['abReportHtml']}")

    for name in fixture_names:
        b = baseline_results[name]
        c = candidate_results[name]
        bflags = b["flags"]
        cflags = c["flags"]
        print(
            f"- {name}: base={b['chars']} chars"
            f" cand={c['chars']} chars"
            f" baseFlags={','.join(bflags) if bflags else '-'}"
            f" candFlags={','.join(cflags) if cflags else '-'}"
        )

        inp = c.get("input") or ""
        if inp:
            print("  INPUT (candidate rendered):")
            print("  " + "\n  ".join(str(inp).splitlines()))

        bout = b.get("output") or (
            "[ERROR] " + str(b.get("error")) if b.get("error") else ""
        )
        cout = c.get("output") or (
            "[ERROR] " + str(c.get("error")) if c.get("error") else ""
        )

        if bout:
            print("  BASELINE:")
            print("  " + "\n  ".join(str(bout).splitlines()))
        if cout:
            print("  CANDIDATE:")
            print("  " + "\n  ".join(str(cout).splitlines()))

        df = diff_index.get(name, {}).get("diffFile")
        if df:
            print(f"  DIFF={df}")

    if args.open:
        report = out_root / "ab_report.html"
        _try_open_path(report if report.exists() else out_root)

    print("Done")
    _auto_prune_out_runs(out_base)
    return 0


def main() -> int:
    # If no args were provided, go interactive.
    if len(sys.argv) == 1:
        return interactive_flow(
            default_prompts_url="https://raw.githubusercontent.com/mloispro/axis-ai-prompts/main/prompts/rizzchatai.json"
        )

    return main_argv(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
