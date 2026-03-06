# flake8: noqa
# ruff: noqa
# pyright: ignore

"""Prompt Workbench (desktop).

Goals
- Iterate on prompt *outputs* quickly on your computer.
- Run fixtures against OpenAI without rebuilding any Android app.
- Save outputs for diffing and basic regression checks.

No secrets are stored. API key is read from OPENAI_API_KEY env var.

Repo conventions
- Prompt files: prompts/<app>.json
- Fixtures: fixtures/<app>/<mode>/*.{txt,json} (preferred) OR fixtures/<mode>/*.{txt,json} (legacy)
- Outputs: out/<runId>/...

JSON shape expected for RizzChatAI-style prompts:
{
  "version": 1,
  "ttlSeconds": 3600,
  "prompts": {
     "openerSystem": "...",
     "appChatSystem": "...",
         "regChatSystem": "...",
         "openerUser": "...",   // optional (used with .json fixtures)
         "appChatUser": "...",  // optional (used with .json fixtures)
         "regChatUser": "..."   // optional (used with .json fixtures)
  }
}

Other apps can use prompts.template.json and this tool can be extended.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import hashlib
import json
import os
import pathlib
import re
import shutil
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple


def _find_repo_root(start: pathlib.Path) -> pathlib.Path:
    """Find repo root by walking up until we find expected folders."""
    cur = start
    for _ in range(8):
        if (cur / "prompts").is_dir() and (cur / "fixtures").is_dir():
            return cur
        cur = cur.parent
    raise SystemExit(
        "Could not locate repo root (expected folders 'prompts/' and 'fixtures/'). "
        "Run this script from within the repo or keep the standard layout."
    )


REPO_ROOT = _find_repo_root(pathlib.Path(__file__).resolve())
PROMPTS_DIR = REPO_ROOT / "prompts"
FIXTURES_DIR = REPO_ROOT / "fixtures"
OUT_DIR = REPO_ROOT / "out"

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"


def _env_truthy(cli_name: str, shared_name: str, default: str = "") -> bool:
    v = os.environ.get(cli_name)
    if v is None or str(v).strip() == "":
        v = os.environ.get(shared_name)
    if v is None or str(v).strip() == "":
        v = default
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _env_int(cli_name: str, shared_name: str, default: int) -> int:
    v = os.environ.get(cli_name)
    if v is None or str(v).strip() == "":
        v = os.environ.get(shared_name)
    if v is None or str(v).strip() == "":
        return int(default)
    try:
        return int(str(v).strip())
    except Exception:
        return int(default)


_RUN_DIR_RE = re.compile(r"^\d{8}_\d{6}Z?$")


def _parse_run_dir_timestamp(name: str) -> Optional[_dt.datetime]:
    for fmt in ("%Y%m%d_%H%M%SZ", "%Y%m%d_%H%M%S"):
        try:
            return _dt.datetime.strptime(name, fmt).replace(tzinfo=_dt.timezone.utc)
        except Exception:
            continue
    return None


def _auto_prune_cli_out(out_base: pathlib.Path) -> None:
    """Keep repo-root out/ bounded by pruning older CLI run folders.

    Best-effort only (never fail a run). Prunes only directories that look like
    run IDs (YYYYMMDD_HHMMSSZ) and contain a manifest.json somewhere under them.

    Defaults:
    - enabled
    - keep last 10 run IDs

    Env overrides (CLI-specific, with shared fallbacks):
    - WORKBENCH_CLI_OUT_AUTOPRUNE (fallback: WORKBENCH_OUT_AUTOPRUNE)
    - WORKBENCH_CLI_OUT_KEEP_LAST (fallback: WORKBENCH_OUT_KEEP_LAST)
    - WORKBENCH_CLI_OUT_KEEP_DAYS (fallback: WORKBENCH_OUT_KEEP_DAYS)
    """

    try:
        if not _env_truthy(
            "WORKBENCH_CLI_OUT_AUTOPRUNE", "WORKBENCH_OUT_AUTOPRUNE", default="1"
        ):
            return

        keep_last = max(
            0,
            _env_int("WORKBENCH_CLI_OUT_KEEP_LAST", "WORKBENCH_OUT_KEEP_LAST", 10),
        )
        keep_days = max(
            0,
            _env_int("WORKBENCH_CLI_OUT_KEEP_DAYS", "WORKBENCH_OUT_KEEP_DAYS", 0),
        )
        if keep_last == 0 and keep_days == 0:
            return

        if not out_base.exists() or not out_base.is_dir():
            return

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=keep_days)

        runs: List[Tuple[_dt.datetime, pathlib.Path]] = []
        for p in out_base.iterdir():
            try:
                if not p.is_dir():
                    continue
                if not _RUN_DIR_RE.match(p.name):
                    continue
                dt = _parse_run_dir_timestamp(p.name)
                if dt is None:
                    continue
                # Safety: require at least one manifest.json under this run ID.
                if not any(p.rglob("manifest.json")):
                    continue
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


def _utc_run_id() -> str:
    # Example: 20260224_235955Z
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%SZ")


def _read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: pathlib.Path) -> dict:
    return json.loads(_read_text(path))


def _hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _prompt_for_mode(prompt_json: dict, mode: str) -> str:
    prompts = prompt_json.get("prompts") or {}
    mode_key = mode.lower()
    if mode_key == "opener":
        return str(prompts.get("openerSystem") or "")
    if mode_key in ("app_chat", "app chat", "appchat"):
        return str(prompts.get("appChatSystem") or "")
    if mode_key in ("reg_chat", "reg chat", "regchat"):
        return str(prompts.get("regChatSystem") or "")
    # Fallback for simple single-system schema
    if "system" in prompts:
        return str(prompts.get("system") or "")
    raise SystemExit(f"Unknown mode '{mode}'. Expected opener|app_chat|reg_chat")


def _user_template_for_mode(prompt_json: dict, mode: str) -> str:
    """Return the per-mode user prompt template, if present.

    This is optional and is only used when fixtures are structured (.json).
    Plain .txt fixtures are treated as already-rendered user prompts.
    """

    prompts = prompt_json.get("prompts") or {}
    mode_key = mode.lower()
    if mode_key == "opener":
        return str(prompts.get("openerUser") or "")
    if mode_key in ("app_chat", "app chat", "appchat"):
        return str(prompts.get("appChatUser") or "")
    if mode_key in ("reg_chat", "reg chat", "regchat"):
        return str(prompts.get("regChatUser") or "")
    return ""


_TEMPLATE_VAR_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


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


def _mode_key(mode: str) -> str:
    return mode.lower().strip().replace(" ", "_")


def _fixture_dirs_for_mode(mode: str, app: Optional[str]) -> List[pathlib.Path]:
    """Return fixture search dirs in priority order.

    Preferred layout is app-scoped:
        fixtures/<app>/<mode>/*.{txt,json}

    Legacy layout (still supported):
        fixtures/<mode>/*.{txt,json}
    """

    key = _mode_key(mode)
    dirs: List[pathlib.Path] = []
    if app:
        dirs.append(FIXTURES_DIR / app / key)
    dirs.append(FIXTURES_DIR / key)
    return dirs


def _select_fixtures(
    mode: str, only: Optional[str], app: Optional[str]
) -> List[pathlib.Path]:
    searched: List[pathlib.Path] = []
    files: List[pathlib.Path] = []
    for folder in _fixture_dirs_for_mode(mode, app):
        searched.append(folder)
        if not folder.exists():
            continue
        files = sorted(
            [
                p
                for p in list(folder.glob("*.txt")) + list(folder.glob("*.json"))
                if p.is_file()
            ]
        )
        if files:
            break

    if not files:
        searched_str = ", ".join(str(p) for p in searched)
        raise SystemExit(
            f"No fixtures found for mode '{mode}' (.txt or .json). Searched: {searched_str}"
        )

    if not only:
        return files

    # allow passing either the full filename or just the stem
    only_norm = only.strip()
    matched = [p for p in files if p.name == only_norm or p.stem == only_norm]
    if not matched:
        raise SystemExit(
            f"No fixture matched '{only}'. Available: {[p.name for p in files]}"
        )
    return matched


def _openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. Set it in your environment before running."
        )
    return key


def _openai_chat_completion(
    *,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
    timeout_s: int = 30,
) -> str:
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = (
            e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        )
        raise RuntimeError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e}") from e

    obj = json.loads(body)
    try:
        content = obj["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        raise RuntimeError(f"Unexpected response JSON: {body}") from exc
    return content


def _basic_flags(mode: str, output: str) -> List[str]:
    out = output
    flags: List[str] = []

    lower = out.lower()
    if (
        "chatgpt" in lower
        or "openai" in lower
        or "as an ai" in lower
        or "i'm an ai" in lower
    ):
        flags.append("mentions_ai")

    if '"' in out or "“" in out or "”" in out or "«" in out or "»" in out:
        flags.append("contains_quotes")

    if mode.lower() == "opener":
        lines = [ln for ln in out.splitlines() if ln.strip()]
        if len(lines) > 2:
            flags.append("opener_too_many_lines")

    if "coffee" in lower:
        flags.append("mentions_coffee")

    if lower.startswith("here") and "opener" in lower[:40]:
        flags.append("meta_preface")

    return flags


def _write_run_manifest(run_dir: pathlib.Path, manifest: dict) -> None:
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _sanitize_filename(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep)


def _load_prompt_json(
    app: Optional[str], prompts_file: Optional[str]
) -> Tuple[dict, pathlib.Path]:
    if prompts_file:
        path = pathlib.Path(prompts_file)
        if not path.is_absolute():
            path = (REPO_ROOT / prompts_file).resolve()
        if not path.exists():
            raise SystemExit(f"Prompt file not found: {path}")
        return _load_json(path), path

    if not app:
        raise SystemExit("Provide --app or --prompts-file")

    path = PROMPTS_DIR / f"{app}.json"
    if not path.exists():
        raise SystemExit(f"Prompt file not found: {path}")
    return _load_json(path), path


def cmd_run(args: argparse.Namespace) -> pathlib.Path:
    prompt_json, prompt_path = _load_prompt_json(args.app, args.prompts_file)

    system_prompt = _prompt_for_mode(prompt_json, args.mode)
    if not system_prompt.strip():
        raise SystemExit(
            f"System prompt for mode '{args.mode}' is blank in {prompt_path.name}"
        )

    user_template = _user_template_for_mode(prompt_json, args.mode)
    uses_user_template = bool(user_template.strip())

    fixtures = _select_fixtures(args.mode, args.fixture, args.app)

    run_id = _utc_run_id()
    label = args.label.strip() if args.label else (args.app or prompt_path.stem)
    safe_label = _sanitize_filename(label)
    run_dir = OUT_DIR / run_id / f"{safe_label}_{args.mode.replace(' ', '_')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    api_key = None if args.dry_run else _openai_api_key()

    failures: List[dict] = []

    manifest = {
        "runId": run_id,
        "timestampUtc": run_id,
        "label": label,
        "app": args.app,
        "mode": args.mode,
        "model": args.model,
        "temperature": args.temperature,
        "maxTokens": args.max_tokens,
        "promptFile": str(prompt_path).replace("\\", "/"),
        "systemPromptSha": _hash_text(system_prompt),
        "usesUserTemplate": uses_user_template,
        "userTemplateSha": _hash_text(user_template) if uses_user_template else None,
        "fixtures": [p.name for p in fixtures],
        "dryRun": bool(args.dry_run),
        "continueOnError": bool(args.continue_on_error),
    }
    _write_run_manifest(run_dir, manifest)

    print(f"Run: {run_id} -> {run_dir}")

    for fx in fixtures:
        if fx.suffix.lower() == ".txt":
            # Back-compat: .txt fixtures are treated as already-rendered user prompts.
            user_prompt = _read_text(fx)
        elif fx.suffix.lower() == ".json":
            payload = _load_json(fx)
            if not isinstance(payload, dict):
                raise SystemExit(f"Fixture JSON must be an object: {fx}")

            # Optional escape hatch: allow explicit raw override for edge cases.
            raw_override = payload.get("user_prompt")
            if isinstance(raw_override, str) and raw_override.strip():
                user_prompt = raw_override
            else:
                if not uses_user_template:
                    raise SystemExit(
                        f"No user template found for mode '{args.mode}', but fixture is .json: {fx.name}"
                    )

                tie_in = str(payload.get("tie_in") or "")
                template_vars: Dict[str, str] = {
                    "tie_in": tie_in,
                    "tie_in_block": _tie_in_block(tie_in),
                    "profile_text": str(payload.get("profile_text") or ""),
                    "chat_transcript": str(payload.get("chat_transcript") or ""),
                }
                user_prompt = _render_template(user_template, template_vars)
        else:
            raise SystemExit(f"Unsupported fixture type: {fx.name}")
        if args.dry_run:
            content = "[DRY RUN]"
            error = None
        else:
            try:
                content = _openai_chat_completion(
                    api_key=api_key,
                    model=args.model,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                error = None
            except RuntimeError as e:
                msg = str(e)
                # simple retry for rate limit
                if "HTTP 429" in msg:
                    time.sleep(2)
                    try:
                        content = _openai_chat_completion(
                            api_key=api_key,
                            model=args.model,
                            temperature=args.temperature,
                            max_tokens=args.max_tokens,
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                        )
                        error = None
                    except RuntimeError as e2:
                        content = ""
                        error = str(e2)
                else:
                    content = ""
                    error = msg

        flags = _basic_flags(args.mode, content) if content else []

        out_name = _sanitize_filename(fx.stem) + ".txt"
        if content:
            (run_dir / out_name).write_text(content, encoding="utf-8")

        if error:
            failures.append({"fixture": fx.name, "error": error})
            (run_dir / (fx.stem + ".error.txt")).write_text(error, encoding="utf-8")

        print("\n" + "=" * 80)
        print(f"Fixture: {fx.name}  Flags: {flags or 'none'}")
        if error:
            print(f"ERROR: {error}")
            if not args.continue_on_error:
                raise SystemExit(error)
            continue

        print("-" * 80)
        print(content[:2000] + ("\n...[truncated]" if len(content) > 2000 else ""))

    # update manifest with failures
    manifest["failures"] = failures
    _write_run_manifest(run_dir, manifest)

    return run_dir


def cmd_run_entry(args: argparse.Namespace) -> int:
    cmd_run(args)
    _auto_prune_cli_out(OUT_DIR)
    return 0


def _load_outputs(run_dir: pathlib.Path) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    for p in sorted(run_dir.glob("*.txt")):
        outputs[p.stem] = _read_text(p)
    return outputs


def cmd_ab(args: argparse.Namespace) -> int:
    # A/B runs: same fixtures, two prompt files.
    a_args = argparse.Namespace(
        app=None,
        prompts_file=args.promptsA,
        label=args.labelA,
        mode=args.mode,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        fixture=args.fixture,
        continue_on_error=args.continue_on_error,
        dry_run=args.dry_run,
    )
    b_args = argparse.Namespace(
        app=None,
        prompts_file=args.promptsB,
        label=args.labelB,
        mode=args.mode,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        fixture=args.fixture,
        continue_on_error=args.continue_on_error,
        dry_run=args.dry_run,
    )

    a_dir = cmd_run(a_args)
    b_dir = cmd_run(b_args)

    a_out = _load_outputs(a_dir)
    b_out = _load_outputs(b_dir)

    run_id = _utc_run_id()
    diff_dir = (
        OUT_DIR
        / run_id
        / f"diff_{_sanitize_filename(args.labelA)}_vs_{_sanitize_filename(args.labelB)}_{args.mode.replace(' ', '_')}"
    )
    diff_dir.mkdir(parents=True, exist_ok=True)

    all_keys = sorted(set(a_out.keys()) | set(b_out.keys()))
    summary: Dict[str, List[str]] = {
        "changed": [],
        "same": [],
        "missingA": [],
        "missingB": [],
    }

    for k in all_keys:
        if k not in a_out:
            summary["missingA"].append(k)
            continue
        if k not in b_out:
            summary["missingB"].append(k)
            continue
        if a_out[k].strip() == b_out[k].strip():
            summary["same"].append(k)
            continue

        summary["changed"].append(k)
        diff = difflib.unified_diff(
            a_out[k].splitlines(keepends=True),
            b_out[k].splitlines(keepends=True),
            fromfile=f"{args.labelA}/{k}.txt",
            tofile=f"{args.labelB}/{k}.txt",
        )
        (diff_dir / f"{_sanitize_filename(k)}.diff").write_text(
            "".join(diff), encoding="utf-8"
        )

    (diff_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(f"\nA/B diff written to: {diff_dir}")
    print(json.dumps(summary, indent=2))
    _auto_prune_cli_out(OUT_DIR)
    return 0


def cmd_paths(_args: argparse.Namespace) -> int:
    print(f"REPO_ROOT: {REPO_ROOT}")
    print(f"PROMPTS_DIR: {PROMPTS_DIR}")
    print(f"FIXTURES_DIR: {FIXTURES_DIR}")
    print(f"OUT_DIR: {OUT_DIR}")
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    # Run a dry-run opener pass and verify outputs exist.
    test_args = argparse.Namespace(
        app="rizzchatai",
        prompts_file=None,
        label="selftest",
        mode="opener",
        model=DEFAULT_MODEL,
        temperature=0.3,
        max_tokens=24,
        fixture=None,
        continue_on_error=False,
        dry_run=True,
    )
    run_dir = cmd_run(test_args)
    manifest = run_dir / "manifest.json"
    txts = list(run_dir.glob("*.txt"))
    if not manifest.exists():
        raise SystemExit(f"Selftest failed: missing {manifest}")
    if not txts:
        raise SystemExit("Selftest failed: no output .txt files written")
    print("Selftest OK")
    _auto_prune_cli_out(OUT_DIR)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workbench")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run fixtures for a mode")
    run.add_argument("--app", help="Prompt file name under prompts/ (without .json)")
    run.add_argument(
        "--prompts-file", help="Path to a prompt JSON file (overrides --app)"
    )
    run.add_argument("--label", help="Run label used in output folder name")
    run.add_argument("--mode", required=True, help="opener | app_chat | reg_chat")
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--temperature", type=float, default=0.3)
    run.add_argument("--max-tokens", type=int, default=160)
    run.add_argument("--fixture", help="Run only one fixture (filename or stem)")
    run.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue remaining fixtures if one fails",
    )
    run.add_argument(
        "--dry-run", action="store_true", help="No network calls; writes placeholders"
    )
    run.set_defaults(func=cmd_run_entry)

    ab = sub.add_parser("ab", help="Run A/B and write diffs")
    ab.add_argument("--promptsA", required=True, help="Prompt JSON for variant A")
    ab.add_argument("--promptsB", required=True, help="Prompt JSON for variant B")
    ab.add_argument("--labelA", default="A")
    ab.add_argument("--labelB", default="B")
    ab.add_argument("--mode", required=True)
    ab.add_argument("--model", default=DEFAULT_MODEL)
    ab.add_argument("--temperature", type=float, default=0.3)
    ab.add_argument("--max-tokens", type=int, default=160)
    ab.add_argument("--fixture", help="Run only one fixture")
    ab.add_argument("--continue-on-error", action="store_true")
    ab.add_argument("--dry-run", action="store_true")
    ab.set_defaults(func=cmd_ab)

    paths = sub.add_parser("paths", help="Print discovered repo paths")
    paths.set_defaults(func=cmd_paths)

    selftest = sub.add_parser("selftest", help="Dry-run smoke test")
    selftest.set_defaults(func=cmd_selftest)

    ls = sub.add_parser("list", help="List prompt files and fixtures")
    ls.add_argument("--verbose", action="store_true")
    ls.set_defaults(func=cmd_list)

    return p


def cmd_list(args: argparse.Namespace) -> int:
    # List prompt files and fixtures.
    print(f"Repo: {REPO_ROOT}")
    print("\nPrompt files:")
    for p in sorted(PROMPTS_DIR.glob("*.json")):
        print(f"- {p.stem}")

    print("\nFixtures:")
    known_modes = {"opener", "app_chat", "reg_chat"}

    # 1) App-scoped fixtures: fixtures/<app>/<mode>/*.{txt,json}
    app_dirs = sorted(
        [p for p in FIXTURES_DIR.iterdir() if p.is_dir() and p.name not in known_modes]
    )
    if app_dirs:
        print("App-scoped:")
        for app_dir in app_dirs:
            for mode in sorted([p for p in app_dir.iterdir() if p.is_dir()]):
                fx = sorted(list(mode.glob("*.txt")) + list(mode.glob("*.json")))
                print(f"- {app_dir.name}/{mode.name} ({len(fx)} fixtures)")
                if args.verbose:
                    for t in fx:
                        print(f"    - {t.name}")

    # 2) Legacy fixtures: fixtures/<mode>/*.{txt,json}
    legacy_dirs = sorted(
        [FIXTURES_DIR / m for m in known_modes if (FIXTURES_DIR / m).is_dir()]
    )
    if legacy_dirs:
        print("Legacy:")
        for d in legacy_dirs:
            fx = sorted(list(d.glob("*.txt")) + list(d.glob("*.json")))
            print(f"- {d.name} ({len(fx)} fixtures)")
            if args.verbose:
                for t in fx:
                    print(f"    - {t.name}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return int(cmd_run_entry(args))
    if args.cmd == "ab":
        return int(cmd_ab(args))
    if args.cmd == "paths":
        return int(cmd_paths(args))
    if args.cmd == "selftest":
        return int(cmd_selftest(args))
    if args.cmd == "list":
        return int(cmd_list(args))

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
