#!/usr/bin/env python3
"""Memory eval harness: with/without-memory A/B on a coding-native seed task
suite, with a saturation third arm and a four-bucket outcome classifier.

Orchestrates Epic 7 of the CCGM durable-memory plan (plan.md §5 Epic 7).
For each task: build a fresh temp fixture workdir, seed a temp learnings
store with the task's `seed_learnings`, then run `claude -p` under an
ISOLATED config (adrev-003a) across THREE arms -- baseline (injection off),
treatment (injection on), full-context-dump (Δ_sat, bizlogic-002; the same
facts pasted directly into the prompt, injection off) -- `--runs N` times
each, judge every run with a blind Messages API call, and classify the
task into one of four buckets (or "inconclusive"): high_value / regression
/ redundant / gap.

The ninth task (`kind: "dreamed"`) closes the loop end-to-end: mine a
synthetic transcript corpus with the REAL transcript_miner, analyze it with
the REAL dream_analyze map/reduce pipeline (offline-canned or live), apply
the resulting proposal to a temp store, then run the SAME three-arm A/B on
a follow-up task the mined memory should help -- this is the ONLY task that
measures "dreaming produces value from real experience," not "a
hand-authored memory helps" (bizlogic-001). It runs alongside a noise-only
negative-control corpus that must yield zero high-value proposals
(adrev-305).

`--gate` mode (consumed by Epic 6's auto-apply): exits 0 iff the most
recent results file exists, is fresh (newer than the configured freshness
bound AND newer than the last CONTENT-SHAPING store mutation -- pure
`verify` counter-ops are excluded from that bound, adrev-403), has zero
`regression` rows, at least one `high_value` row, AND the live (non-offline)
`kind:dreamed` row itself classifies `high_value` with Δ_sat>0 (adrev-305).
Fails closed -- same reason shape for "stale" as for "missing".

Isolation (adrev-003a, CRITICAL): every `claude -p` arm runs under a
purpose-built, ephemeral `CLAUDE_CONFIG_DIR` + `HOME` containing ONLY a
`settings.json` that registers the learnings-inject SessionStart hook --
never the operator's live `~/.claude` (which would load the full global
CLAUDE.md rule stack, every other SessionStart injector, and every
PreToolUse gate into BOTH arms, confounding the delta or letting a gate
like branch-guard block a seeded task). The ONLY thing that varies between
baseline and treatment is the `CCGM_LEARNINGS_INJECT` env var;
`assert_isolated_config_registers_only_injection_hook()` is a structural
guard against that isolation ever silently regressing.

`--offline <dir>` replaces every judge call AND every `claude -p` arm call
with canned data read from `<dir>/eval-scores.json` (keyed by task id and
arm) -- no network, no ANTHROPIC_API_KEY, no `claude` subprocess is ever
invoked. This is a PLUMBING check: it proves the classifier/gate/reporting
pipeline runs end-to-end, never that memory measurably helps in reality
(see H3 for a live judged run). The `kind:dreamed` task's own internal
mine->analyze step also runs offline in this mode (reusing dream_analyze.py
via `--offline <dir>/../offline-responses-dreamed`, a sibling of the outer
`--offline` directory) and is explicitly labeled `"offline": true` in its
results row -- `--gate` never accepts an offline-labeled `dreamed` row as
satisfying its live-Δ_sat requirement.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.util
import json
import os
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_MODULE_ROOT = _HERE.parent  # modules/dreaming
if str(_MODULE_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT / "lib"))

import transcript_miner as tm  # noqa: E402  (sibling module, modules/dreaming/lib/)
import dream_analyze as da  # noqa: E402  (sibling module, modules/dreaming/lib/) -- REUSED, never modified

# self-improving/lib is a DIFFERENT module's lib dir; transcript_miner's own
# cross-module import helper already resolves the installed-vs-repo-relative
# split (mirrors dream_analyze.py's own import of the same helper).
learnings_store = tm._import_sibling_module(  # noqa: SLF001
    "self-improving", "learnings_store", "store seeding, projection, sanitize_content"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RUNS = 5
DEFAULT_MAX_BUDGET_USD_PER_RUN = 0.50
DEFAULT_RUN_TIMEOUT_S = 300
DEFAULT_EVAL_FRESHNESS_DAYS = 14
DEFAULT_JUDGE_MAX_OUTPUT_TOKENS = 200

# Four-bucket classifier thresholds (plan.md §5 Epic 7, decisions.md #8).
HIGH_VALUE_DELTA_THRESHOLD = 1.5
REGRESSION_DELTA_THRESHOLD = -1.0
REDUNDANT_BASELINE_THRESHOLD = 8.5
REDUNDANT_DELTA_ABS_THRESHOLD = 1.0
GAP_MEAN_THRESHOLD = 5.0

ARMS = ("baseline", "treatment", "full_context")

# Content-shaping op-events (adrev-403): the gate's freshness bound is
# scoped to these. Pure `verify` counter-ops -- the only thing auto-apply
# itself can write -- are deliberately excluded, or the gate would
# self-close after every routine reinforcement.
CONTENT_SHAPING_OPS = {"add", "supersede", "deprecate", "contradict"}


class IsolatedConfigError(RuntimeError):
    """Raised by assert_isolated_config_registers_only_injection_hook() when
    the eval's isolated CLAUDE_CONFIG_DIR would register anything other
    than the learnings-inject SessionStart hook (adrev-003a)."""


# ---------------------------------------------------------------------------
# Paths (mirrors dream_analyze.py's own env-overridable path helpers)
# ---------------------------------------------------------------------------


def dreaming_dir() -> Path:
    return Path(os.environ.get("CCGM_DREAMING_DIR", os.path.expanduser("~/.claude/dreaming")))


def evals_dir() -> Path:
    return dreaming_dir() / "evals"


def today_iso() -> str:
    override = os.environ.get("CCGM_DREAMING_TODAY")
    if override:
        return override
    return datetime.now(timezone.utc).date().isoformat()


def _utc_now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def _learnings_root_for_gate() -> Path:
    """Fresh (never cached) read of the real learnings root, for the gate's
    content-shaping-mutation scan. Deliberately NOT learnings_store.LEARNINGS_ROOT
    (a constant frozen at import time) -- the gate must see CCGM_LEARNINGS_DIR
    exactly as set at call time, including by a test that sets it right
    before calling gate_check()."""
    return Path(os.path.expanduser(os.environ.get("CCGM_LEARNINGS_DIR", "~/.claude/learnings")))


def default_tasks_glob() -> str:
    return str(_HERE / "tasks" / "*.json")


def judge_prompt_path() -> Path:
    return _HERE / "judge-prompt.md"


# ---------------------------------------------------------------------------
# Task loading
# ---------------------------------------------------------------------------


def discover_task_paths(glob_pattern: str) -> list[Path]:
    import glob as globmod

    return sorted(Path(p) for p in globmod.glob(glob_pattern))


def load_task(path: Path) -> dict[str, Any]:
    task = json.loads(path.read_text(encoding="utf-8"))
    if "id" not in task or "kind" not in task:
        raise ValueError(f"{path}: task JSON missing required 'id'/'kind'")
    return task


def load_tasks(glob_pattern: str) -> list[dict[str, Any]]:
    return [load_task(p) for p in discover_task_paths(glob_pattern)]


# ---------------------------------------------------------------------------
# Isolated Claude Code config (adrev-003a)
# ---------------------------------------------------------------------------


def resolve_learnings_inject_hook_path() -> Path:
    """Installed-symlink-first, repo-relative-fallback resolution (mirrors
    transcript_miner._import_sibling_module's own convention) -- so this
    works both against a real `start.sh --add` install and a bare repo
    checkout that has never been installed."""
    installed = Path(os.path.expanduser("~/.claude/hooks/learnings-inject.py"))
    if installed.is_file():
        return installed
    fallback = _MODULE_ROOT.parent / "self-improving" / "hooks" / "learnings-inject.py"
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(
        "memory_eval: cannot find learnings-inject.py at ~/.claude/hooks/learnings-inject.py "
        f"or {fallback} -- is the self-improving module installed? (bash start.sh --add self-improving)"
    )


def assert_isolated_config_registers_only_injection_hook(config_dir: Path) -> None:
    """Structural guard (adrev-003a): the isolated eval config may ONLY ever
    register the learnings-inject SessionStart hook. Raises
    IsolatedConfigError on anything else -- an unexpected hook event, an
    unexpected command, or a missing settings.json entirely."""
    settings_path = config_dir / "settings.json"
    if not settings_path.is_file():
        raise IsolatedConfigError(f"isolated config guard: {settings_path} does not exist")
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IsolatedConfigError(f"isolated config guard: {settings_path} is not valid JSON: {exc}") from exc

    hooks = settings.get("hooks") or {}
    if not hooks:
        raise IsolatedConfigError("isolated config guard: no hooks registered at all (expected SessionStart)")

    found_injection = False
    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            raise IsolatedConfigError(f"isolated config guard: hooks.{event_name} is not a list")
        for entry in entries:
            for h in entry.get("hooks", []):
                command = h.get("command", "")
                if "learnings-inject.py" not in command:
                    raise IsolatedConfigError(
                        f"isolated config guard: unexpected hook registered for event "
                        f"{event_name!r}: {command!r} (the isolated eval config may only "
                        "register the learnings-inject SessionStart hook -- adrev-003a)"
                    )
                if event_name != "SessionStart":
                    raise IsolatedConfigError(
                        "isolated config guard: learnings-inject hook registered under "
                        f"unexpected event {event_name!r}, expected SessionStart"
                    )
                found_injection = True

    if not found_injection:
        raise IsolatedConfigError("isolated config guard: learnings-inject hook was never registered")


def build_isolated_config(config_dir: Path, *, hook_path: Path | None = None) -> Path:
    """Write a `settings.json` registering ONLY the learnings-inject
    SessionStart hook into `config_dir`, then self-verify via the guard
    above before returning. `config_dir` becomes the eval arm's
    CLAUDE_CONFIG_DIR -- it deliberately contains nothing else (no
    `.claude.json`, no CLAUDE.md, no other hooks/commands/plugins):
    copying the operator's live config here is exactly the confound
    adrev-003a exists to prevent."""
    hook_path = hook_path or resolve_learnings_inject_hook_path()
    config_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{shlex.quote(sys.executable)} {shlex.quote(str(hook_path))}",
                        }
                    ]
                }
            ]
        }
    }
    (config_dir / "settings.json").write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert_isolated_config_registers_only_injection_hook(config_dir)
    return config_dir


# ---------------------------------------------------------------------------
# Fixture workdir builder
# ---------------------------------------------------------------------------


def build_fixture_workdir(files: dict[str, str], dest_dir: Path) -> Path:
    """Write EXACTLY the declared files (relative path -> text content) into
    `dest_dir`, creating parent directories as needed. Writes nothing else
    -- `dest_dir` must already exist and be empty (or absent; created if
    so) before this is called for the property to hold."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in (files or {}).items():
        target = dest_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return dest_dir


_SKIP_DIR_NAMES = {".git", "__pycache__", ".claude"}
_SNAPSHOT_MAX_FILE_BYTES = 4000
_SNAPSHOT_MAX_TOTAL_BYTES = 60_000


def snapshot_workdir(
    workdir: Path,
    *,
    max_file_bytes: int = _SNAPSHOT_MAX_FILE_BYTES,
    max_total_bytes: int = _SNAPSHOT_MAX_TOTAL_BYTES,
) -> dict[str, str]:
    """Read every file under `workdir` (skipping .git/__pycache__/.claude)
    into a {relative_path: content} dict for the judge to inspect.
    Per-file and total-budget truncated (best-effort text decode; a file
    that fails to decode as UTF-8 is recorded as a `[binary file]` marker
    rather than raising)."""
    out: dict[str, str] = {}
    total = 0
    if not workdir.is_dir():
        return out
    for path in sorted(workdir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.relative_to(workdir).parts):
            continue
        rel = str(path.relative_to(workdir))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            out[rel] = "[binary file]"
            continue
        if len(text) > max_file_bytes:
            text = text[:max_file_bytes] + "\n...(truncated)"
        if total + len(text) > max_total_bytes:
            out[rel] = "[omitted -- eval snapshot total-byte budget exceeded]"
            continue
        out[rel] = text
        total += len(text)
    return out


# ---------------------------------------------------------------------------
# Temp learnings store pointing + seeding
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _learnings_store_pointed_at(learnings_dir: Path, *, claude_projects_dir: Path | None = None):
    """Monkeypatch learnings_store's module-level path constants (computed
    ONCE at import time from env, per that module's own docstring) so
    direct in-process calls -- seeding, reading back, applying a mined
    proposal -- operate against an isolated temp store instead of the
    real ~/.claude/learnings. Also exports the matching env vars so any
    SUBPROCESS spawned inside the `with` block (a claude -p arm, which
    imports learnings_store fresh in its own process) sees the identical
    isolated store via CCGM_LEARNINGS_DIR. Restores everything on exit.

    NOT thread-safe (process-global module state) -- this harness runs
    tasks strictly sequentially by design, never in parallel threads.
    """
    prev = {
        "LEARNINGS_ROOT": learnings_store.LEARNINGS_ROOT,
        "CONFIG_PATH": learnings_store.CONFIG_PATH,
        "LEARNINGS_CACHE_ROOT": learnings_store.LEARNINGS_CACHE_ROOT,
        "CLAUDE_PROJECTS_ROOT": learnings_store.CLAUDE_PROJECTS_ROOT,
    }
    prev_env = {
        k: os.environ.get(k)
        for k in ("CCGM_LEARNINGS_DIR", "CCGM_LEARNINGS_CACHE_DIR", "CCGM_CLAUDE_PROJECTS_DIR")
    }
    try:
        learnings_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = learnings_dir.parent / (learnings_dir.name + "-cache")
        learnings_store.LEARNINGS_ROOT = learnings_dir
        learnings_store.CONFIG_PATH = learnings_dir / "config.json"
        learnings_store.LEARNINGS_CACHE_ROOT = cache_dir
        os.environ["CCGM_LEARNINGS_DIR"] = str(learnings_dir)
        os.environ["CCGM_LEARNINGS_CACHE_DIR"] = str(cache_dir)
        if claude_projects_dir is not None:
            learnings_store.CLAUDE_PROJECTS_ROOT = claude_projects_dir
            os.environ["CCGM_CLAUDE_PROJECTS_DIR"] = str(claude_projects_dir)
        yield
    finally:
        for key, val in prev.items():
            setattr(learnings_store, key, val)
        for key, val in prev_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def seed_temp_store(seed_learnings: list[dict[str, Any]], *, learnings_dir: Path, project_slug: str) -> None:
    """Write `seed_learnings` into the writer's shard for `project_slug`
    inside `learnings_dir`. Entries are added in array order; an entry
    carrying `"supersedes_previous": true` supersedes the id of the
    IMMEDIATELY PRECEDING entry instead of adding fresh -- this is how the
    `kind: contradiction` task builds a real old-row/current-head chain
    (the store's own supersede-filtering is what the task exercises)."""
    if not seed_learnings:
        return
    with _learnings_store_pointed_at(learnings_dir):
        prev_id: str | None = None
        for spec in seed_learnings:
            content = spec["content"]
            type_ = spec.get("type", "pattern")
            confidence = spec.get("confidence", learnings_store.DEFAULT_CONFIDENCE)
            tags = spec.get("tags") or []
            if spec.get("supersedes_previous"):
                if prev_id is None:
                    raise ValueError("seed_learnings: supersedes_previous set with no preceding entry to supersede")
                new_entry = learnings_store.supersede_entry(
                    prev_id,
                    content=content,
                    type_=type_,
                    confidence=confidence,
                    tags=tags,
                    slug=project_slug,
                    reason=spec.get("supersede_reason"),
                )
                if new_entry is None:
                    raise ValueError(f"seed_temp_store: supersede target {prev_id!r} not found")
                prev_id = new_entry["id"]
            else:
                entry = learnings_store.build_entry(
                    type_=type_, content=content, confidence=confidence, tags=tags, project=project_slug,
                )
                learnings_store.append_entry(entry, slug=project_slug)
                prev_id = entry["id"]


# ---------------------------------------------------------------------------
# claude -p invocation
# ---------------------------------------------------------------------------


def full_context_facts(task: dict[str, Any]) -> list[str]:
    """The Δ_sat arm's prompt supplement: defaults to every seed_learnings
    entry's content (both sides of a contradiction chain included by
    default -- an unfiltered dump does not know how to resolve a
    contradiction, which is exactly the property the contradiction task
    wants to compare against curated injection). Override per-task with an
    explicit `full_context_facts` list."""
    if "full_context_facts" in task:
        return list(task["full_context_facts"])
    return [sl["content"] for sl in task.get("seed_learnings", [])]


def build_full_context_prompt(prompt: str, facts: list[str]) -> str:
    if not facts:
        return prompt
    facts_block = "\n".join(f"- {f}" for f in facts)
    return f"Relevant project context (from prior sessions):\n{facts_block}\n\n{prompt}"


def run_claude_p(
    *,
    prompt: str,
    workdir: Path,
    config_dir: Path,
    home_dir: Path,
    model: str,
    inject: bool,
    api_key: str,
    learnings_dir: Path,
    claude_bin: str,
    max_budget_usd: float,
    timeout_s: int,
) -> dict[str, Any]:
    """Invoke the real `claude -p` binary under the isolated config. Never
    raises on a subprocess failure/timeout/unparseable-output -- returns a
    synthetic is_error result instead, so one flaky live run does not
    crash the whole eval (it is simply judged on whatever the workdir
    ended up looking like, which is the correct signal for a run that
    failed to execute)."""
    home_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for key in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY", "CCGM_LEARNINGS_INJECT"):
        env.pop(key, None)
    env.update(
        {
            "HOME": str(home_dir),
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "ANTHROPIC_API_KEY": api_key or "",
            "CCGM_LEARNINGS_INJECT": "true" if inject else "false",
            "CCGM_LEARNINGS_DIR": str(learnings_dir),
        }
    )
    cmd = [
        claude_bin,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--model",
        model,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--setting-sources",
        "user",
        "--strict-mcp-config",
        "--max-budget-usd",
        str(max_budget_usd),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), env=env, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"is_error": True, "result": f"claude -p timed out after {timeout_s}s", "usage": {}, "num_turns": 0, "total_cost_usd": 0.0}
    except OSError as exc:
        return {"is_error": True, "result": f"claude -p failed to launch: {exc}", "usage": {}, "num_turns": 0, "total_cost_usd": 0.0}

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detail = (proc.stderr or proc.stdout or "")[:2000]
        return {"is_error": True, "result": f"claude -p produced unparseable output: {detail}", "usage": {}, "num_turns": 0, "total_cost_usd": 0.0}
    if not isinstance(parsed, dict):
        return {"is_error": True, "result": "claude -p JSON output was not an object", "usage": {}, "num_turns": 0, "total_cost_usd": 0.0}
    return parsed


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------


def build_judge_payload(
    *, prompt: str, criteria: list[str], final_files: dict[str, str], agent_summary: str
) -> dict[str, Any]:
    """The exact object sent to the judge. Deliberately carries NO field
    naming which arm/condition produced `final_files` -- the judge must be
    blind to baseline/treatment/full_context (adrev-003a test contract)."""
    return {
        "task_prompt": prompt,
        "criteria": list(criteria),
        "final_files": final_files,
        "agent_summary": agent_summary,
    }


def _call_judge_api(
    *, model: str, system_prompt: str, user_obj: dict[str, Any], max_output_tokens: int, api_key: str, api_url: str,
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """A judge-specific Messages API call with `temperature: 0`
    (deterministic grading, as the spec requires for the judge
    specifically). `da.get_model_response()` / `_call_curl_with_retry()`
    have no temperature dial and dream_analyze.py is never modified to add
    one (Epic 3's own map/reduce calls never needed it) -- this is a small,
    judge-specific sibling that mirrors da's retry/transport shape while
    reusing da's own (unmodified) response-parsing helpers, rather than an
    edit to that shared file. Never raises -- returns (None, zeroed usage)
    on any transport/parse failure."""
    request_body = {
        "model": model,
        "max_tokens": max_output_tokens,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)}],
    }
    payload = json.dumps(request_body)
    zero_usage = {"input_tokens": 0, "output_tokens": 0}

    for attempt in range(da.MAX_429_RETRIES + 1):
        try:
            proc = subprocess.run(
                [
                    "curl", "-s", "-S",
                    "-H", f"x-api-key: {api_key}",
                    "-H", f"anthropic-version: {da.ANTHROPIC_VERSION}",
                    "-H", "content-type: application/json",
                    "--max-time", "90",
                    "-w", "\n%{http_code}",
                    api_url,
                    "--data-binary", "@-",
                ],
                input=payload, capture_output=True, text=True,
            )
        except OSError:
            return None, zero_usage
        if proc.returncode != 0:
            return None, zero_usage

        body, _, code = proc.stdout.rpartition("\n")
        if code == "429":
            if attempt < da.MAX_429_RETRIES:
                delay = da.BACKOFF_SCHEDULE_SECONDS[min(attempt, len(da.BACKOFF_SCHEDULE_SECONDS) - 1)]
                print(f"memory_eval: 429 from judge Messages API, retrying in {delay}s (attempt {attempt + 1})", file=sys.stderr)
                time.sleep(delay)
                continue
            return None, zero_usage
        if code != "200":
            return None, zero_usage

        try:
            response = json.loads(body)
        except json.JSONDecodeError:
            return None, zero_usage
        usage = response.get("usage") if isinstance(response, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        usage_out = {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
        }
        text = da._extract_assistant_text(response)  # noqa: SLF001 -- reusing Epic 3's own parsing helper, unmodified
        parsed = da._parse_json_object(text)  # noqa: SLF001
        return parsed, usage_out

    return None, zero_usage  # pragma: no cover - unreachable (loop always returns or continues)


def judge_output(
    payload: dict[str, Any],
    *,
    judge_model: str,
    judge_system_prompt: str,
    api_key: str | None,
    api_url: str,
    offline_score: dict[str, Any] | None,
) -> dict[str, Any]:
    """Returns {"pass": bool, "score": float 0-10, "usage": {...}}.

    `offline_score`, when given, short-circuits to a canned score with NO
    network call at all (memory_eval's own --offline contract) -- the
    canned value stands in for "what the judge would have said", so the
    live judge-call machinery below is exercised only when actually live.
    """
    if offline_score is not None:
        score = max(0.0, min(10.0, float(offline_score["score"])))
        return {"pass": score >= 6.0, "score": score, "usage": {"input_tokens": 0, "output_tokens": 0}}

    parsed, usage = _call_judge_api(
        model=judge_model,
        system_prompt=judge_system_prompt,
        user_obj=payload,
        max_output_tokens=DEFAULT_JUDGE_MAX_OUTPUT_TOKENS,
        api_key=api_key or "",
        api_url=api_url,
    )
    if parsed is None or "score" not in parsed:
        return {"pass": False, "score": 0.0, "usage": usage, "error": "judge did not return parseable {pass, score}"}
    try:
        score = max(0.0, min(10.0, float(parsed.get("score"))))
    except (TypeError, ValueError):
        score = 0.0
    return {"pass": bool(parsed.get("pass", score >= 6.0)), "score": score, "usage": usage}


# ---------------------------------------------------------------------------
# Offline score lookup (memory_eval's own --offline contract)
# ---------------------------------------------------------------------------


def load_offline_scores(offline_dir: Path) -> dict[str, Any]:
    path = offline_dir / "eval-scores.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def offline_scores_for_task(all_scores: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    if not all_scores:
        return None
    return all_scores.get(task_id) or all_scores.get("default")


# ---------------------------------------------------------------------------
# Arm runner: N runs of one arm, aggregated
# ---------------------------------------------------------------------------


def _run_one(
    *,
    task_id: str,
    project_slug: str,
    arm: str,
    run_index: int,
    prompt: str,
    fixture_files: dict[str, str],
    learnings_dir: Path,
    backbone: str,
    inject: bool,
    api_key: str,
    claude_bin: str,
    max_budget_usd: float,
    timeout_s: int,
    judge_model: str,
    judge_system_prompt: str,
    criteria: list[str],
    api_url: str,
    offline_score: dict[str, Any] | None,
    sandbox_root: Path,
) -> dict[str, Any]:
    run_root = Path(tempfile.mkdtemp(prefix=f"ccgm-eval-{arm}-{run_index}-", dir=str(sandbox_root)))
    workdir = run_root / project_slug
    home_dir = run_root / "home"
    config_dir = run_root / "claude-config"
    build_fixture_workdir(fixture_files, workdir)
    build_isolated_config(config_dir)

    if offline_score is not None:
        arm_score = offline_score
        result = {
            "is_error": False,
            "result": "[offline: claude -p not invoked]",
            "num_turns": arm_score.get("turns", 0),
            "total_cost_usd": arm_score.get("cost_usd", 0.0),
            "usage": {
                "input_tokens": arm_score.get("input_tokens", 0),
                "output_tokens": arm_score.get("output_tokens", 0),
            },
        }
    else:
        result = run_claude_p(
            prompt=prompt, workdir=workdir, config_dir=config_dir, home_dir=home_dir,
            model=backbone, inject=inject, api_key=api_key, learnings_dir=learnings_dir,
            claude_bin=claude_bin, max_budget_usd=max_budget_usd, timeout_s=timeout_s,
        )

    final_files = {} if offline_score is not None else snapshot_workdir(workdir)
    payload = build_judge_payload(
        prompt=prompt, criteria=criteria, final_files=final_files,
        agent_summary=str(result.get("result") or ""),
    )
    judged = judge_output(
        payload, judge_model=judge_model, judge_system_prompt=judge_system_prompt,
        api_key=api_key, api_url=api_url,
        offline_score=(offline_score if offline_score is not None else None),
    )

    usage = result.get("usage") or {}
    row = {
        "score": judged["score"],
        "pass": judged["pass"],
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "turns": int(result.get("num_turns", 0) or 0),
        "run_cost_usd": float(result.get("total_cost_usd", 0.0) or 0.0),
        "judge_input_tokens": int(judged.get("usage", {}).get("input_tokens", 0) or 0),
        "judge_output_tokens": int(judged.get("usage", {}).get("output_tokens", 0) or 0),
        "is_error": bool(result.get("is_error", False)),
    }
    shutil.rmtree(run_root, ignore_errors=True)
    return row


def _aggregate_arm_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        return {
            "mean_score": 0.0, "pass_rate": 0.0, "mean_input_tokens": 0.0, "mean_output_tokens": 0.0,
            "mean_turns": 0.0, "mean_cost_usd": 0.0, "format_error_rate": 0.0, "runs": 0,
        }
    scores = [r["score"] for r in runs]
    return {
        "mean_score": statistics.fmean(scores),
        "pass_rate": sum(1 for r in runs if r["pass"]) / len(runs),
        "mean_input_tokens": statistics.fmean(r["input_tokens"] for r in runs),
        "mean_output_tokens": statistics.fmean(r["output_tokens"] for r in runs),
        "mean_turns": statistics.fmean(r["turns"] for r in runs),
        "mean_cost_usd": statistics.fmean(r["run_cost_usd"] for r in runs),
        "format_error_rate": sum(1 for r in runs if r["is_error"]) / len(runs),
        "runs": len(runs),
    }


def run_arms(
    *,
    task_id: str,
    project_slug: str,
    prompt: str,
    fixture_files: dict[str, str],
    criteria: list[str],
    facts: list[str],
    learnings_dir: Path,
    backbone: str,
    runs: int,
    api_key: str,
    claude_bin: str,
    max_budget_usd: float,
    timeout_s: int,
    judge_model: str,
    judge_system_prompt: str,
    api_url: str,
    offline_scores: dict[str, Any] | None,
    sandbox_root: Path,
) -> dict[str, dict[str, Any]]:
    """Run all three arms, `runs` times each, for one (task, backbone)
    combination. Returns {"baseline": {...}, "treatment": {...},
    "full_context": {...}} of aggregated per-arm stats."""
    arm_prompts = {
        "baseline": prompt,
        "treatment": prompt,
        "full_context": build_full_context_prompt(prompt, facts),
    }
    arm_inject = {"baseline": False, "treatment": True, "full_context": False}

    out: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        offline_score = None
        if offline_scores is not None:
            offline_score = offline_scores.get(arm) or {}
        arm_runs = [
            _run_one(
                task_id=task_id, project_slug=project_slug, arm=arm, run_index=i,
                prompt=arm_prompts[arm], fixture_files=fixture_files, learnings_dir=learnings_dir,
                backbone=backbone, inject=arm_inject[arm], api_key=api_key, claude_bin=claude_bin,
                max_budget_usd=max_budget_usd, timeout_s=timeout_s, judge_model=judge_model,
                judge_system_prompt=judge_system_prompt, criteria=criteria, api_url=api_url,
                offline_score=offline_score, sandbox_root=sandbox_root,
            )
            for i in range(runs)
        ]
        out[arm] = _aggregate_arm_runs(arm_runs)
    return out


# ---------------------------------------------------------------------------
# Four-bucket classifier (pure function -- decisions.md #8, bizlogic-002)
# ---------------------------------------------------------------------------


def classify_bucket(
    *, baseline_mean: float, treatment_mean: float, full_context_mean: float
) -> tuple[str, float, float]:
    """Returns (bucket, delta, delta_sat).

    delta = treatment_mean - baseline_mean
    delta_sat = treatment_mean - full_context_mean (bizlogic-002, Δ_sat)

    Precedence (regression checked first -- a real regression must never
    be reclassified as "gap" just because both means happen to also be
    low; the two conditions can genuinely overlap, e.g. baseline=4.0,
    treatment=2.9): regression > high_value > redundant > gap >
    "inconclusive" (a task that clears none of the four named buckets).
    """
    delta = treatment_mean - baseline_mean
    delta_sat = treatment_mean - full_context_mean

    if delta <= REGRESSION_DELTA_THRESHOLD:
        return "regression", delta, delta_sat
    if delta >= HIGH_VALUE_DELTA_THRESHOLD and delta_sat > 0:
        return "high_value", delta, delta_sat
    if baseline_mean >= REDUNDANT_BASELINE_THRESHOLD and abs(delta) < REDUNDANT_DELTA_ABS_THRESHOLD:
        return "redundant", delta, delta_sat
    if baseline_mean < GAP_MEAN_THRESHOLD and treatment_mean < GAP_MEAN_THRESHOLD:
        return "gap", delta, delta_sat
    return "inconclusive", delta, delta_sat


# ---------------------------------------------------------------------------
# Per-task orchestration (the 8 non-dreamed tasks)
# ---------------------------------------------------------------------------


def run_task(
    task: dict[str, Any],
    *,
    backbones: list[str],
    runs: int,
    api_key: str,
    claude_bin: str,
    max_budget_usd: float,
    timeout_s: int,
    judge_model: str,
    judge_system_prompt: str,
    api_url: str,
    offline_all_scores: dict[str, Any] | None,
    sandbox_root: Path,
) -> list[dict[str, Any]]:
    task_id = task["id"]
    kind = task["kind"]
    prompt = task["prompt"]
    fixture_files = (task.get("fixture") or {}).get("files") or {}
    seed_learnings = task.get("seed_learnings") or []
    criteria = task.get("criteria") or []
    facts = full_context_facts(task)
    project_slug = task_id

    offline_task_scores = offline_scores_for_task(offline_all_scores, task_id) if offline_all_scores is not None else None

    rows: list[dict[str, Any]] = []
    for backbone in backbones:
        store_root = Path(tempfile.mkdtemp(prefix=f"ccgm-eval-store-{task_id}-", dir=str(sandbox_root)))
        learnings_dir = store_root / "learnings"
        seed_temp_store(seed_learnings, learnings_dir=learnings_dir, project_slug=project_slug)

        arms = run_arms(
            task_id=task_id, project_slug=project_slug, prompt=prompt, fixture_files=fixture_files,
            criteria=criteria, facts=facts, learnings_dir=learnings_dir, backbone=backbone, runs=runs,
            api_key=api_key, claude_bin=claude_bin, max_budget_usd=max_budget_usd, timeout_s=timeout_s,
            judge_model=judge_model, judge_system_prompt=judge_system_prompt, api_url=api_url,
            offline_scores=offline_task_scores, sandbox_root=sandbox_root,
        )
        shutil.rmtree(store_root, ignore_errors=True)

        bucket, delta, delta_sat = classify_bucket(
            baseline_mean=arms["baseline"]["mean_score"], treatment_mean=arms["treatment"]["mean_score"],
            full_context_mean=arms["full_context"]["mean_score"],
        )
        rows.append(_build_result_row(
            task_id=task_id, kind=kind, backbone=backbone, runs=runs, offline=offline_all_scores is not None,
            arms=arms, bucket=bucket, delta=delta, delta_sat=delta_sat,
        ))
    return rows


def _build_result_row(
    *, task_id: str, kind: str, backbone: str, runs: int, offline: bool,
    arms: dict[str, dict[str, Any]], bucket: str, delta: float, delta_sat: float, extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token_delta = arms["treatment"]["mean_input_tokens"] + arms["treatment"]["mean_output_tokens"] - (
        arms["baseline"]["mean_input_tokens"] + arms["baseline"]["mean_output_tokens"]
    )
    turn_delta = arms["treatment"]["mean_turns"] - arms["baseline"]["mean_turns"]
    total_cost = sum(a["mean_cost_usd"] * a["runs"] for a in arms.values())
    row = {
        "date": today_iso(),
        "generated_at": _utc_now_iso(),
        "task_id": task_id,
        "kind": kind,
        "backbone": backbone,
        "runs": runs,
        "offline": offline,
        "baseline": arms["baseline"],
        "treatment": arms["treatment"],
        "full_context": arms["full_context"],
        "delta": round(delta, 4),
        "delta_sat": round(delta_sat, 4),
        "token_delta": round(token_delta, 2),
        "turn_delta": round(turn_delta, 2),
        "cost_usd": round(total_cost, 6),
        "bucket": bucket,
    }
    if extra:
        row.update(extra)
    return row


# ---------------------------------------------------------------------------
# Dreamed task: mine -> analyze -> apply -> A/B, plus noise negative control
# ---------------------------------------------------------------------------


def _write_transcript_corpus(corpus: dict[str, Any], *, projects_root: Path, fixtures_dir: Path) -> None:
    """Copy the task's packaged transcript fixture .jsonl files into a
    fresh temp --projects-root, under an arbitrary subdirectory (mirrors
    test-dream-pipeline.sh's own `${PROJECTS_ROOT}/session-a/*.jsonl`
    convention -- discover() re-derives slug identity from each
    transcript's own `cwd` field, never from this directory's name)."""
    subdir = projects_root / corpus.get("slug", "corpus")
    subdir.mkdir(parents=True, exist_ok=True)
    for filename in corpus.get("files", []):
        src = fixtures_dir / filename
        if not src.is_file():
            raise FileNotFoundError(f"memory_eval: dreamed-task fixture not found: {src}")
        shutil.copy(src, subdir / filename)


def _try_apply_via_epic6(row: dict[str, Any], *, learnings_dir: Path) -> dict[str, Any] | None:
    """Best-effort integration with Epic 6's apply_dream_proposal.py, built
    concurrently in a sibling clone and not guaranteed to exist yet, or to
    expose any particular call shape. Returns None (NEVER raises) on any
    failure -- import error, missing file, unexpected signature -- so the
    caller always falls back to _apply_proposal_row_directly() below.
    Tolerating Epic 6's absence is a hard constraint of this epic."""
    apply_lib_path = _MODULE_ROOT / "lib" / "apply_dream_proposal.py"
    if not apply_lib_path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("apply_dream_proposal", apply_lib_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for fn_name in ("apply_proposal_row", "apply_proposal"):
            fn = getattr(module, fn_name, None)
            if callable(fn):
                result = fn(row, learnings_dir=learnings_dir)
                if isinstance(result, dict):
                    return result
    except Exception:  # noqa: BLE001 -- ANY failure here means "not usable yet", never a crash
        return None
    return None


def apply_proposal_row(row: dict[str, Any], *, learnings_dir: Path) -> dict[str, Any]:
    """Apply one accepted dreaming proposal row to the (already
    environment-pointed-at) temp learnings store. Maps `kind` -> the
    matching learnings_store op exactly as plan.md describes
    apply_dream_proposal.py's own contract (Epic 6). Prefers a real,
    already-landed apply_dream_proposal.py when importable and shaped
    right; otherwise applies directly so the eval's own
    mine->analyze->apply->A/B chain always completes standalone."""
    epic6_result = _try_apply_via_epic6(row, learnings_dir=learnings_dir)
    if epic6_result is not None:
        return epic6_result

    kind = row["kind"]
    project = row["project"]

    if kind == "learning_add":
        entry = learnings_store.build_entry(
            type_=row["type"], content=row["content"], confidence=row.get("confidence", 5), project=project,
        )
        learnings_store.append_entry(entry, slug=project)
        return {"applied": True, "op": "add", "id": entry["id"], "project": project}

    if kind in ("learning_verify", "learning_contradict"):
        ok = learnings_store.update_entry_by_id(
            row["target_id"], slug=project, verify=(kind == "learning_verify"), contradict=(kind == "learning_contradict"),
        )
        return {"applied": ok, "op": kind, "id": row["target_id"], "project": project}

    if kind == "learning_deprecate":
        heads = {h["id"]: h for h in learnings_store.load_all(project)}
        target = heads.get(row["target_id"])
        expected_sha = learnings_store.content_sha256(target.get("content")) if target else None
        ok = learnings_store.update_entry_by_id(
            row["target_id"], slug=project, deprecate=True, expected_sha256=expected_sha,
        )
        return {"applied": ok, "op": "deprecate", "id": row["target_id"], "project": project}

    if kind == "learning_supersede":
        heads = {h["id"]: h for h in learnings_store.load_all(project)}
        target = heads.get(row["target_id"])
        expected_sha = learnings_store.content_sha256(target.get("content")) if target else None
        new_entry = learnings_store.supersede_entry(
            row["target_id"], content=row["content"], type_=row.get("type"), confidence=row.get("confidence"),
            slug=project, expected_sha256=expected_sha, reason=row.get("justification"),
        )
        applied = new_entry is not None
        return {"applied": applied, "op": "supersede", "id": (new_entry or {}).get("id"), "project": project}

    return {"applied": False, "op": kind, "reason": f"unrecognized proposal kind: {kind!r}"}


def _mine_and_analyze(
    *, slugs: list[str], projects_root: Path, dreaming_state_dir: Path, offline_dir: Path | None, api_key: str | None,
    force_day: str,
) -> Path:
    """Run the REAL Epic 2/3 pipeline (transcript_miner + dream_analyze,
    imported, never modified) against a temp --projects-root, writing
    proposals under `dreaming_state_dir/proposals/<force_day>.jsonl`.

    `slugs` MUST include both the signal AND the noise corpus's slugs in
    ONE combined run (a single dream_analyze.main() call, one reduce
    call spanning both) -- passing the signal slug alone would make the
    noise-only negative control vacuous: "zero noise proposals" only
    means something if the noise corpus was actually mined and analyzed
    alongside the signal, not simply never attempted (adrev-305).

    Returns the proposals path (may not exist if nothing was
    mined/proposed for either slug)."""
    argv = ["--force-day", force_day, "--slugs", ",".join(slugs), "--projects-root", str(projects_root)]
    if offline_dir is not None:
        argv = ["--offline", str(offline_dir)] + argv
    prev_dreaming_dir = os.environ.get("CCGM_DREAMING_DIR")
    prev_api_key = os.environ.get("ANTHROPIC_API_KEY")
    try:
        os.environ["CCGM_DREAMING_DIR"] = str(dreaming_state_dir)
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        da.main(argv)
    finally:
        if prev_dreaming_dir is None:
            os.environ.pop("CCGM_DREAMING_DIR", None)
        else:
            os.environ["CCGM_DREAMING_DIR"] = prev_dreaming_dir
        if prev_api_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = prev_api_key
    return dreaming_state_dir / "proposals" / f"{force_day}.jsonl"


def _read_proposals(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def run_dreamed_task(
    task: dict[str, Any],
    *,
    backbones: list[str],
    runs: int,
    api_key: str,
    claude_bin: str,
    max_budget_usd: float,
    timeout_s: int,
    judge_model: str,
    judge_system_prompt: str,
    api_url: str,
    offline: bool,
    offline_dir: Path | None,
    offline_all_scores: dict[str, Any] | None,
    sandbox_root: Path,
) -> list[dict[str, Any]]:
    """The bizlogic-001 / adrev-305 end-to-end task: mine -> analyze ->
    apply -> A/B on a real synthetic transcript corpus, plus a paired
    noise-only corpus that must yield no high-value proposal."""
    task_id = task["id"]
    fixtures_dir = _HERE / "tasks" / "fixtures"
    signal = task["transcript_corpus"]
    noise = task["noise_corpus"]
    follow_up = task["follow_up"]

    sandbox = Path(tempfile.mkdtemp(prefix=f"ccgm-eval-dreamed-{task_id}-", dir=str(sandbox_root)))
    projects_root = sandbox / "claude-projects"
    dreaming_state_dir = sandbox / "dreaming-state"
    store_root = sandbox / "learnings"
    _write_transcript_corpus(signal, projects_root=projects_root, fixtures_dir=fixtures_dir)
    _write_transcript_corpus(noise, projects_root=projects_root, fixtures_dir=fixtures_dir)

    dreamed_offline_dir: Path | None = None
    if offline:
        dreamed_offline_dir = (offline_dir.parent / "offline-responses-dreamed") if offline_dir else None

    mine_date = today_iso()
    with _learnings_store_pointed_at(store_root, claude_projects_dir=projects_root):
        proposals_path = _mine_and_analyze(
            slugs=[signal["slug"], noise["slug"]], projects_root=projects_root, dreaming_state_dir=dreaming_state_dir,
            offline_dir=dreamed_offline_dir if offline else None, api_key=(None if offline else api_key),
            force_day=mine_date,
        )
        all_proposals = _read_proposals(proposals_path)
        signal_proposals = [p for p in all_proposals if p.get("project") == signal["slug"]]
        noise_proposals = [p for p in all_proposals if p.get("project") == noise["slug"]]

        applied_info: dict[str, Any] = {"applied": False}
        follow_up_facts: list[str] = []
        if signal_proposals:
            accepted = signal_proposals[0]
            applied_info = apply_proposal_row(accepted, learnings_dir=store_root)
            applied_info["proposal_id"] = accepted.get("id")
            follow_up_facts = [accepted.get("content", "")]

    project_slug = signal["slug"]
    fixture_files = (follow_up.get("fixture") or {}).get("files") or {}
    criteria = follow_up.get("criteria") or []
    prompt = follow_up["prompt"]
    facts = follow_up.get("full_context_facts") or follow_up_facts

    offline_task_scores = offline_scores_for_task(offline_all_scores, task_id) if offline_all_scores is not None else None

    rows: list[dict[str, Any]] = []
    for backbone in backbones:
        arms = run_arms(
            task_id=task_id, project_slug=project_slug, prompt=prompt, fixture_files=fixture_files,
            criteria=criteria, facts=facts, learnings_dir=store_root, backbone=backbone, runs=runs,
            api_key=api_key, claude_bin=claude_bin, max_budget_usd=max_budget_usd, timeout_s=timeout_s,
            judge_model=judge_model, judge_system_prompt=judge_system_prompt, api_url=api_url,
            offline_scores=offline_task_scores, sandbox_root=sandbox_root,
        )
        bucket, delta, delta_sat = classify_bucket(
            baseline_mean=arms["baseline"]["mean_score"], treatment_mean=arms["treatment"]["mean_score"],
            full_context_mean=arms["full_context"]["mean_score"],
        )
        rows.append(_build_result_row(
            task_id=task_id, kind="dreamed", backbone=backbone, runs=runs, offline=offline,
            arms=arms, bucket=bucket, delta=delta, delta_sat=delta_sat,
            extra={
                "mining": {
                    "signal_proposals_written": len(signal_proposals),
                    "noise_proposals_written": len(noise_proposals),
                    "noise_high_value": len(noise_proposals) > 0,
                    **applied_info,
                },
                "note": "offline plumbing-only -- NOT evidence of value" if offline else None,
            },
        ))

    shutil.rmtree(sandbox, ignore_errors=True)
    return rows


# ---------------------------------------------------------------------------
# Results I/O
# ---------------------------------------------------------------------------


def results_path_for_date(date: str) -> Path:
    return evals_dir() / f"{date}.jsonl"


def write_results(rows: list[dict[str, Any]], *, date: str) -> Path:
    path = results_path_for_date(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def _find_latest_results_file() -> Path | None:
    d = evals_dir()
    if not d.is_dir():
        return None
    candidates = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _read_results_file(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


# ---------------------------------------------------------------------------
# Gate (--gate mode; consumed by Epic 6 auto-apply)
# ---------------------------------------------------------------------------


def latest_content_shaping_mutation_epoch(learnings_root: Path) -> float | None:
    """Max timestamp (epoch seconds) across every add/supersede/deprecate/
    contradict op-event (and every legacy v1 row, which IS an add-
    equivalent) in the store. Pure `verify` counter-ops are excluded
    (adrev-403) -- the only op auto-apply itself can ever write, so
    including it would make the gate self-close after every routine
    reinforcement instead of only after a real content change."""
    if not learnings_root.is_dir():
        return None
    latest: float | None = None
    for slug_dir in learnings_root.iterdir():
        if not slug_dir.is_dir() or slug_dir.name.startswith("."):
            continue
        candidates = []
        legacy = slug_dir / "learnings.jsonl"
        if legacy.is_file():
            candidates.append(legacy)
        agents_dir = slug_dir / "agents"
        if agents_dir.is_dir():
            candidates.extend(agents_dir.glob("*.jsonl"))
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                op = obj.get("op")
                if op is not None and op not in CONTENT_SHAPING_OPS:
                    continue  # verify/other non-content-shaping op -- excluded
                ts = obj.get("timestamp")
                if not ts:
                    continue
                epoch = learnings_store._parse_iso(ts)  # noqa: SLF001 -- same-package internal reuse
                if epoch and (latest is None or epoch > latest):
                    latest = epoch
    return latest


def gate_check(*, freshness_days: int = DEFAULT_EVAL_FRESHNESS_DAYS, now: float | None = None) -> tuple[bool, str]:
    """Returns (open, reason). Fails closed on every branch: missing
    results, stale results (either bound), any regression row, no
    high_value row, or no LIVE dreamed row classifying high_value with
    Δ_sat>0 (adrev-305) -- exactly one reason string per failure mode,
    "stale" handled identically to "missing"."""
    now = now if now is not None else time.time()

    latest = _find_latest_results_file()
    if latest is None:
        return False, "no results"

    results_mtime = latest.stat().st_mtime
    if now - results_mtime > freshness_days * 86400:
        return False, f"stale: results file {latest.name} is older than the freshness bound ({freshness_days}d)"

    last_mutation = latest_content_shaping_mutation_epoch(_learnings_root_for_gate())
    if last_mutation is not None and results_mtime < last_mutation:
        return False, "stale: results predate the last content-shaping store mutation (add/supersede/deprecate/contradict)"

    rows = _read_results_file(latest)
    if not rows:
        return False, "results file is empty"

    regressions = [r for r in rows if r.get("bucket") == "regression"]
    if regressions:
        return False, f"{len(regressions)} regression bucket row(s) present"

    high_value = [r for r in rows if r.get("bucket") == "high_value"]
    if not high_value:
        return False, "no high_value rows"

    live_dreamed_high_value = [
        r for r in rows
        if r.get("kind") == "dreamed" and not r.get("offline") and r.get("bucket") == "high_value" and r.get("delta_sat", -1) > 0
    ]
    if not live_dreamed_high_value:
        return False, "kind:dreamed task has not classified high_value with Δ_sat>0 under a live (non-offline) run"

    return True, "ok"


# ---------------------------------------------------------------------------
# Summary rendering
# ---------------------------------------------------------------------------


def render_summary_table(rows: list[dict[str, Any]]) -> str:
    headers = ["task_id", "kind", "backbone", "baseline", "treatment", "full_context", "delta", "delta_sat", "bucket", "fmt_err%"]
    lines = [" | ".join(headers), "-" * 100]
    for r in rows:
        lines.append(" | ".join([
            r["task_id"], r["kind"], r["backbone"],
            f"{r['baseline']['mean_score']:.2f}", f"{r['treatment']['mean_score']:.2f}", f"{r['full_context']['mean_score']:.2f}",
            f"{r['delta']:+.2f}", f"{r['delta_sat']:+.2f}", r["bucket"],
            f"{r['treatment']['format_error_rate'] * 100:.0f}",
        ]))
    bucket_counts: dict[str, int] = {}
    for r in rows:
        bucket_counts[r["bucket"]] = bucket_counts.get(r["bucket"], 0) + 1
    lines.append("")
    lines.append("Buckets: " + ", ".join(f"{k}={v}" for k, v in sorted(bucket_counts.items())))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CCGM dreaming: memory eval harness (Epic 7).")
    p.add_argument("--tasks", metavar="GLOB", default=default_tasks_glob(), help="glob of task JSON files")
    p.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="runs per arm per task per backbone")
    p.add_argument("--backbone", metavar="A,B", help="comma-separated model list (default: configured map_model,reduce_model)")
    p.add_argument("--judge-model", metavar="MODEL", help="default: configured reduce_model")
    p.add_argument("--offline", metavar="DIR", help="canned judge/arm scores + analyzer responses; no network, no API key")
    p.add_argument("--gate", action="store_true", help="check the latest results file against the auto-apply gate contract; print JSON, exit 0/1")
    p.add_argument("--freshness-days", type=int, default=DEFAULT_EVAL_FRESHNESS_DAYS)
    p.add_argument("--date", metavar="YYYY-MM-DD", help="override the results filename date (default: today)")
    p.add_argument("--claude-bin", default=os.environ.get("CCGM_EVAL_CLAUDE_BIN", "claude"))
    p.add_argument("--max-budget-usd", type=float, default=DEFAULT_MAX_BUDGET_USD_PER_RUN)
    p.add_argument("--timeout-s", type=int, default=DEFAULT_RUN_TIMEOUT_S)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.gate:
        is_open, reason = gate_check(freshness_days=args.freshness_days)
        print(json.dumps({"gate": "open" if is_open else "closed", "reason": reason}))
        return 0 if is_open else 1

    da.load_env()
    cfg = da.load_config()
    offline_dir = Path(args.offline).resolve() if args.offline else None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if offline_dir is None and not api_key:
        print("memory_eval: ANTHROPIC_API_KEY not set; skipping (offline-only verification is fine).", file=sys.stderr)
        return 0

    backbones = (
        [b.strip() for b in args.backbone.split(",") if b.strip()]
        if args.backbone
        else list(dict.fromkeys([cfg.get("map_model", da.DEFAULT_MAP_MODEL), cfg.get("reduce_model", da.DEFAULT_REDUCE_MODEL)]))
    )
    judge_model = args.judge_model or cfg.get("reduce_model", da.DEFAULT_REDUCE_MODEL)
    judge_system_prompt = judge_prompt_path().read_text(encoding="utf-8")
    api_url = os.environ.get("CCGM_DREAMING_API_URL", da.DEFAULT_API_URL)
    date = args.date or today_iso()

    offline_all_scores = load_offline_scores(offline_dir) if offline_dir is not None else None

    tasks = load_tasks(args.tasks)
    if not tasks:
        print(f"memory_eval: no tasks matched {args.tasks!r}", file=sys.stderr)
        return 1

    sandbox_root = Path(tempfile.mkdtemp(prefix="ccgm-eval-sandbox-"))
    all_rows: list[dict[str, Any]] = []
    try:
        for task in tasks:
            print(f"memory_eval: running task {task['id']} (kind={task['kind']})...", file=sys.stderr)
            if task["kind"] == "dreamed":
                rows = run_dreamed_task(
                    task, backbones=backbones, runs=args.runs, api_key=api_key or "", claude_bin=args.claude_bin,
                    max_budget_usd=args.max_budget_usd, timeout_s=args.timeout_s, judge_model=judge_model,
                    judge_system_prompt=judge_system_prompt, api_url=api_url, offline=offline_dir is not None,
                    offline_dir=offline_dir, offline_all_scores=offline_all_scores, sandbox_root=sandbox_root,
                )
            else:
                rows = run_task(
                    task, backbones=backbones, runs=args.runs, api_key=api_key or "", claude_bin=args.claude_bin,
                    max_budget_usd=args.max_budget_usd, timeout_s=args.timeout_s, judge_model=judge_model,
                    judge_system_prompt=judge_system_prompt, api_url=api_url, offline_all_scores=offline_all_scores,
                    sandbox_root=sandbox_root,
                )
            all_rows.extend(rows)
    finally:
        shutil.rmtree(sandbox_root, ignore_errors=True)

    results_path = write_results(all_rows, date=date)
    print(f"memory_eval: wrote {len(all_rows)} result row(s) to {results_path}", file=sys.stderr)
    print(render_summary_table(all_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
