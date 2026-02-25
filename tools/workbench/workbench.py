"""Prompt Workbench (desktop).

Goals
- Iterate on prompt *outputs* quickly on your computer.
- Run fixtures against OpenAI without rebuilding any Android app.
- Save outputs for diffing and basic regression checks.

No secrets are stored. API key is read from OPENAI_API_KEY env var.

Repo conventions
- Prompt files: prompts/<app>.json
- Fixtures: fixtures/<mode>/*.txt
- Outputs: out/<runId>/...

JSON shape expected for RizzChatAI-style prompts:
{
  "version": 1,
  "ttlSeconds": 3600,
  "prompts": {
     "openerSystem": "...",
     "appChatSystem": "...",
     "regChatSystem": "..."
  }
}

Other apps can use prompts.template.json and this tool can be extended.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import difflib
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional


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


@dataclasses.dataclass(frozen=True)
class RunConfig:
    app: str
    mode: str
    model: str
    temperature: float
    max_tokens: int


def _utc_run_id() -> str:
    # Example: 20260224_235955Z
    return _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")


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


def _fixture_paths_for_mode(mode: str) -> List[pathlib.Path]:
    mode_key = mode.lower().replace(" ", "_")
    folder = FIXTURES_DIR / mode_key
    if not folder.exists():
        # Also allow "app chat" → app_chat, "reg chat" → reg_chat
        folder = FIXTURES_DIR / mode.lower().strip().replace(" ", "_")
    if not folder.exists():
        raise SystemExit(f"Fixtures folder not found: {folder}")
    files = sorted([p for p in folder.glob("*.txt") if p.is_file()])
    if not files:
        raise SystemExit(f"No .txt fixtures found in {folder}")
    return files


def _openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set. Set it in your environment before running.")
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
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e}")

    obj = json.loads(body)
    try:
        content = obj["choices"][0]["message"]["content"].strip()
    except Exception:
        raise RuntimeError(f"Unexpected response JSON: {body}")
    return content


def _basic_flags(mode: str, output: str) -> List[str]:
    out = output
    flags: List[str] = []

    lower = out.lower()
    if "chatgpt" in lower or "openai" in lower or "as an ai" in lower or "i'm an ai" in lower:
        flags.append("mentions_ai")

    if "\"" in out or "“" in out or "”" in out or "«" in out or "»" in out:
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
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _sanitize_filename(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep)


def cmd_run(args: argparse.Namespace) -> pathlib.Path:
    prompt_path = PROMPTS_DIR / f"{args.app}.json"
    if not prompt_path.exists():
        raise SystemExit(f"Prompt file not found: {prompt_path}")

    prompt_json = _load_json(prompt_path)
    system_prompt = _prompt_for_mode(prompt_json, args.mode)
    if not system_prompt.strip():
        raise SystemExit(f"System prompt for mode '{args.mode}' is blank in {prompt_path.name}")

    fixtures = _fixture_paths_for_mode(args.mode)

    run_id = _utc_run_id()
    run_dir = OUT_DIR / run_id / f"{args.app}_{args.mode.replace(' ', '_')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    api_key = None if args.dry_run else _openai_api_key()

    manifest = {
        "runId": run_id,
        "timestampUtc": run_id,
        "app": args.app,
        "mode": args.mode,
        "model": args.model,
        "temperature": args.temperature,
        "maxTokens": args.max_tokens,
        "promptFile": str(prompt_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "systemPromptSha": _hash_text(system_prompt),
        "fixtures": [p.name for p in fixtures],
        "dryRun": bool(args.dry_run),
    }
    _write_run_manifest(run_dir, manifest)

    print(f"Run: {run_id} -> {run_dir}")

    for fx in fixtures:
        user_prompt = _read_text(fx)
        if args.dry_run:
            content = "[DRY RUN]"
        else:
            # simple retry for 429-ish transient failures
            try:
                content = _openai_chat_completion(
                    api_key=api_key,
                    model=args.model,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            except RuntimeError as e:
                msg = str(e)
                if "HTTP 429" in msg:
                    time.sleep(2)
                    content = _openai_chat_completion(
                        api_key=api_key,
                        model=args.model,
                        temperature=args.temperature,
                        max_tokens=args.max_tokens,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                    )
                else:
                    raise

        flags = _basic_flags(args.mode, content)

        out_name = _sanitize_filename(fx.stem) + ".txt"
        (run_dir / out_name).write_text(content, encoding="utf-8")

        print("\n" + "=" * 80)
        print(f"Fixture: {fx.name}  Flags: {flags or 'none'}")
        print("-" * 80)
        print(content[:2000] + ("\n...[truncated]" if len(content) > 2000 else ""))

    return run_dir


def cmd_run_entry(args: argparse.Namespace) -> int:
    cmd_run(args)
    return 0


def _load_outputs(run_dir: pathlib.Path) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    for p in sorted(run_dir.glob("*.txt")):
        outputs[p.stem] = _read_text(p)
    return outputs


def cmd_ab(args: argparse.Namespace) -> int:
    # A/B runs: same fixtures, two prompt files.
    a_args = argparse.Namespace(
        app=args.appA,
        mode=args.mode,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        dry_run=args.dry_run,
    )
    b_args = argparse.Namespace(
        app=args.appB,
        mode=args.mode,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        dry_run=args.dry_run,
    )

    a_dir = cmd_run(a_args)
    b_dir = cmd_run(b_args)

    a_out = _load_outputs(a_dir)
    b_out = _load_outputs(b_dir)

    run_id = _utc_run_id()
    diff_dir = OUT_DIR / run_id / f"diff_{args.appA}_vs_{args.appB}_{args.mode.replace(' ', '_')}"
    diff_dir.mkdir(parents=True, exist_ok=True)

    all_keys = sorted(set(a_out.keys()) | set(b_out.keys()))
    summary: Dict[str, List[str]] = {"changed": [], "same": [], "missingA": [], "missingB": []}

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
            fromfile=f"A/{k}.txt",
            tofile=f"B/{k}.txt",
        )
        (diff_dir / f"{_sanitize_filename(k)}.diff").write_text("".join(diff), encoding="utf-8")

    (diff_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nA/B diff written to: {diff_dir}")
    print(json.dumps(summary, indent=2))
    return 0


def cmd_paths(args: argparse.Namespace) -> int:
    print(f"REPO_ROOT: {REPO_ROOT}")
    print(f"PROMPTS_DIR: {PROMPTS_DIR}")
    print(f"FIXTURES_DIR: {FIXTURES_DIR}")
    print(f"OUT_DIR: {OUT_DIR}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    # Run a dry-run opener pass and verify outputs exist.
    test_args = argparse.Namespace(
        app="rizzchatai",
        mode="opener",
        model=DEFAULT_MODEL,
        temperature=0.3,
        max_tokens=24,
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
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workbench")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run fixtures for a mode")
    run.add_argument("--app", required=True, help="Prompt file name under prompts/ (without .json)")
    run.add_argument("--mode", required=True, help="opener | app_chat | reg_chat")
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--temperature", type=float, default=0.3)
    run.add_argument("--max-tokens", type=int, default=160)
    run.add_argument("--dry-run", action="store_true", help="No network calls; writes placeholders")
    run.set_defaults(func=cmd_run_entry)

    ab = sub.add_parser("ab", help="Run A/B and write diffs")
    ab.add_argument("--appA", required=True)
    ab.add_argument("--appB", required=True)
    ab.add_argument("--mode", required=True)
    ab.add_argument("--model", default=DEFAULT_MODEL)
    ab.add_argument("--temperature", type=float, default=0.3)
    ab.add_argument("--max-tokens", type=int, default=160)
    ab.add_argument("--dry-run", action="store_true")
    ab.set_defaults(func=cmd_ab)

    paths = sub.add_parser("paths", help="Print discovered repo paths")
    paths.set_defaults(func=cmd_paths)

    selftest = sub.add_parser("selftest", help="Dry-run smoke test")
    selftest.set_defaults(func=cmd_selftest)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
