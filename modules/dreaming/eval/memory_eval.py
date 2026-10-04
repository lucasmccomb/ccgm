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

`--gate` mode (the nightly integration gate, #1098 item 2.1) prints
`{"gate", "code", "reason", "since"}` and exits 0 / 1 / 3 for
open / closed / paused. It OPENS unless there is a supported regression:
treatment fails a check the baseline passes, each in at least 2 of 3 runs,
on a canary task or on a task whose seed changed since the previous run
(see gate_check() and assess_row()). It CLOSES on that, or when the live
dreamed task's noise-only corpus yielded a proposal (adrev-305). It PAUSES
when nothing usable was measured -- missing, stale, broken or budget-aborted
results, results older than dreaming's own last auto-integrated write, or a
checked row that did not fully run. No high_value row is required (#1037);
the buckets below are reporting only.

Fail-loud contract (#1027): a single arm run that fails to execute is
non-fatal -- it is recorded as a format error and the eval carries on, and
is never sent to the judge (nothing to grade). A run where EVERY arm
failed is not a measurement at all, so the harness aborts with the first
failure's raw output on stderr and a non-zero exit instead of writing a
results file `--gate` would read as a memory regression: it drops any
partial file it wrote this run and records `evals/<date>.harness-broken`.
That marker is load-bearing rather than informational -- evals/ always
holds prior runs, so an abort that merely wrote nothing would leave
gate_check() reading the PREVIOUS run's file and reporting `open` on a
harness that provably did not run. The `claude` binary is resolved to an
absolute path before any task runs (see resolve_claude_bin), so the PATH
the caller happens to export -- a LaunchAgent's is not a login shell's --
cannot decide whether the harness works.

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
results row.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
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
# A verdict is two fields; 1024 is a backstop against a truncated response,
# not a tuning knob (#1026). The judge request pins `thinking: disabled`, so
# this cap covers the JSON answer alone even on a model that thinks by
# default -- a bump to such a model cannot silently eat the budget.
DEFAULT_JUDGE_MAX_OUTPUT_TOKENS = 1024

# The judge's response schema, sent as `output_config.format` so the verdict
# is JSON-valid by construction, and re-checked after parsing (#1029). The
# harness has always validated this shape; the schema states it once for both
# the API and _parse_judge_verdict().
#
# No `minimum`/`maximum` on `score`: the structured-outputs schema subset
# rejects numeric range keywords outright ("For 'number' type, properties
# maximum, minimum are not supported", HTTP 400). The 0-10 range is stated in
# judge-prompt.md and clamped in judge_output(); the schema's job here is the
# field set and their types.
JUDGE_VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pass", "score"],
    "properties": {
        "pass": {"type": "boolean"},
        "score": {"type": "number"},
    },
}

# Four-bucket classifier thresholds (plan.md §5 Epic 7, decisions.md #8).
HIGH_VALUE_DELTA_THRESHOLD = 1.5
REGRESSION_DELTA_THRESHOLD = -1.0
REDUNDANT_BASELINE_THRESHOLD = 8.5
REDUNDANT_DELTA_ABS_THRESHOLD = 1.0
GAP_MEAN_THRESHOLD = 5.0
# high_value Path B, the efficiency win (#784): memory that MATCHES the
# full-context dump's outcome at materially fewer input tokens is high_value
# even when it does not BEAT the dump on score. Both bounds must hold.
HIGH_VALUE_SAT_TOLERANCE = 0.5      # treatment may be at most 0.5 below full_context on score (must essentially MATCH, within noise)
HIGH_VALUE_EFFICIENCY_RATIO = 0.5   # treatment mean_total_input_tokens must be <= 0.5 * full_context mean_total_input_tokens (#789: total incl. cached prompt tokens, not just marginal input_tokens)

ARMS = ("baseline", "treatment", "full_context")

# Stage-2 #771 Recommend fix (defense-in-depth: "refuse unless proven safe"
# over "allow unless proven dangerous"): run_claude_p()'s isolated arm
# subprocess builds its env from this ALLOWLIST rather than inheriting the
# operator's full ambient environment and popping a few known-dangerous
# keys -- an ambient XDG_CONFIG_HOME/ANTHROPIC_BASE_URL/stray CLAUDE_* var
# would otherwise pass through into the "purpose-built, ephemeral" child
# untouched. Shell/locale/binary-resolution plumbing only; NEVER anything
# that could redirect Claude Code's own config/auth resolution --
# HOME/CLAUDE_CONFIG_DIR/ANTHROPIC_API_KEY/CCGM_LEARNINGS_* are always the
# explicit isolation overrides applied AFTER this allowlist, never
# forwarded from the ambient environment regardless of what is in it.
SUBPROCESS_ENV_ALLOWLIST = ("PATH", "SHELL", "TERM", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TMPDIR")

# Where Claude Code's own installers put the `claude` CLI, searched (in this
# order) when the ambient PATH does not resolve it (#1027). The LaunchAgent
# that runs the nightly chain exports a fixed, login-shell-free PATH
# (/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin), and the native installer
# puts the binary in ~/.local/bin -- so from 2026-07-15 every arm subprocess
# died with FileNotFoundError before it ran, and every row scored a silent
# format error. resolve_claude_bin() below hands run_claude_p an ABSOLUTE
# path so the child's PATH stops deciding whether the harness works.
CLAUDE_BIN_FALLBACK_DIRS = (
    "~/.local/bin",
    "~/.claude/local",
    "/opt/homebrew/bin",
    "/usr/local/bin",
)

# The gate's supported-regression rule (#1098 item 2.1): treatment fails a
# check the baseline passes, each in at least 2 of 3 runs, with at least 3
# scored runs per arm.
SUPPORTED_FRACTION = 2 / 3
MIN_SUPPORTED_RUNS = 3

# `--gate` exit codes, one per state.
GATE_EXIT_CODES = {"open": 0, "closed": 1, "paused": 3}

# Content-shaping op-events (adrev-403): the gate's freshness bound is
# scoped to these. Pure `verify` counter-ops -- the only thing auto-apply
# itself can write -- are deliberately excluded, or the gate would
# self-close after every routine reinforcement.
CONTENT_SHAPING_OPS = {"add", "supersede", "deprecate", "contradict"}

# Filename suffix of the whole-run abort's marker (#1027). NOT ".jsonl": the
# results glob must not see it as a results file, but gate_check() must see
# it (it pauses the gate), or an abort that writes nothing leaves the gate reading the PREVIOUS
# night's file -- which, once its regression rows clear, is green. That is a
# broken harness reporting "open", the one direction this gate must never
# fail in.
HARNESS_BROKEN_MARKER_SUFFIX = ".harness-broken"


# Hard total-cost stop (#1098 item 0.2). A run that aborts on budget writes
# `evals/<date>.budget-abort`. Like the harness-broken marker it is not a
# `.jsonl`, so no results glob picks it up. While it is at least as new as
# the newest results, gate_check() returns `paused` (#1098 item 2.1).
BUDGET_ABORT_MARKER_SUFFIX = ".budget-abort"
# Preflight price of one `claude -p` arm session: the measured mean of the
# 270-session run on 2026-10-04 ($20.97 / 270). Recalibrate when a run's
# ledger rows say otherwise.
ESTIMATED_SESSION_COST_USD = 0.08
# Preflight price of the dreamed task's in-eval mining (2 map + 1 reduce).
ESTIMATED_MINING_COST_USD = 0.50
# Preflight guess at a judge request's payload size, in characters.
ESTIMATED_JUDGE_PAYLOAD_CHARS = 8000
_COST_EPSILON = 1e-9


class BudgetAbortError(RuntimeError):
    """Raised when the next billed call would cross the run's cost cap.
    main() turns it into a `budget-abort` marker and an untouched gate;
    the per-task `except Exception` in main() must let it through."""


class IsolatedConfigError(RuntimeError):
    """Raised by assert_isolated_config_registers_only_injection_hook() when
    the eval's isolated CLAUDE_CONFIG_DIR would register anything other
    than the learnings-inject SessionStart hook (adrev-003a)."""


class ClaudeBinaryNotFoundError(RuntimeError):
    """Raised by resolve_claude_bin() when the `claude` CLI is on neither the
    ambient PATH nor any known install directory (#1027). Raised BEFORE any
    task runs, so a broken harness costs nothing and says why."""


class HarnessBrokenError(RuntimeError):
    """Raised by main() when every agent run of the whole eval failed to
    execute (#1027). A single failed run is a flaky run; every run failing
    is the harness, and writing that out as a red results file would tell
    `--gate` that memory regressed when nothing was ever measured."""


# ---------------------------------------------------------------------------
# Paths (mirrors dream_analyze.py's own env-overridable path helpers)
# ---------------------------------------------------------------------------


def dreaming_dir() -> Path:
    return Path(os.environ.get("CCGM_DREAMING_DIR", os.path.expanduser("~/.claude/dreaming")))


def evals_dir() -> Path:
    return dreaming_dir() / "evals"


def real_dreaming_dir() -> Path:
    """The operator's live dreaming dir: the default when no override is set."""
    return Path(os.path.expanduser("~/.claude/dreaming"))


def _isolate_offline_run(*, allow_real_dir: bool) -> Path | None:
    """An --offline run is a plumbing smoke; its results are canned. Written
    into the live dreaming dir they overwrite a paid eval's results (it
    happened on 2026-10-04), clear its harness-broken markers, and make the
    live gate read a fresh-looking file. Unless `allow_real_dir`, a run whose
    dreaming dir resolves to the live one is moved to a fresh temp dir by
    pointing CCGM_DREAMING_DIR at it, so every path below follows. Returns
    that temp dir, or None when nothing moved."""
    if allow_real_dir or dreaming_dir().resolve() != real_dreaming_dir().resolve():
        return None
    tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-offline-"))
    os.environ["CCGM_DREAMING_DIR"] = str(tmp)
    return tmp


# ---------------------------------------------------------------------------
# Cost tracking: one running total over every billed call, mirrored to the
# shared cost.log ledger (#1098 items 0.2, 0.3)
# ---------------------------------------------------------------------------


class CostTracker:
    """Running total of this run's spend, checked BEFORE each billed call.

    `check()` raises BudgetAbortError when `spent + estimate` would cross the
    cap, so the run stops before the call that overspends, not after it.
    `record()` adds a finished call's cost and appends one cost.log row
    (`eval:arm:<model>`, `eval:judge:<model>`, `eval:mine:<model>`). The
    ledger path is captured at construction, because in-eval mining
    repoints CCGM_DREAMING_DIR at a sandbox for a while."""

    def __init__(
        self, *, cap_usd: float, ledger_path: Path, date: str, cfg: dict[str, Any],
        session_estimate_usd: float = ESTIMATED_SESSION_COST_USD,
    ) -> None:
        self.cap_usd = cap_usd
        self.ledger_path = ledger_path
        self.date = date
        self.cfg = cfg
        self.session_estimate_usd = session_estimate_usd
        self.spent_usd = 0.0
        self.sessions_run = 0
        self.max_session_cost_usd = 0.0

    def remaining_usd(self) -> float:
        return self.cap_usd - self.spent_usd

    def check(self, estimate_usd: float, what: str) -> None:
        if self.spent_usd + estimate_usd > self.cap_usd + _COST_EPSILON:
            raise BudgetAbortError(
                f"next {what} (estimated ${estimate_usd:.4f}) would cross the ${self.cap_usd:.4f} cap "
                f"(spent ${self.spent_usd:.4f})"
            )

    def next_session_estimate(self, max_budget_usd: float) -> float:
        """Worst case for the next arm session: its own --max-budget-usd
        ceiling, or the dearest session seen so far if that is higher."""
        return max(max_budget_usd, self.max_session_cost_usd)

    def judge_cost(self, model: str, in_tok: int, out_tok: int) -> float:
        return da.estimate_call_cost_usd(in_tok, out_tok, da.resolve_pricing(self.cfg, model))

    def judge_estimate(self, model: str, system_prompt: str, payload_chars: int) -> float:
        in_tok = (len(system_prompt) + payload_chars) // 3 + 1
        return self.judge_cost(model, in_tok, DEFAULT_JUDGE_MAX_OUTPUT_TOKENS)

    def record(self, *, in_tok: int, out_tok: int, cost_usd: float, label: str) -> None:
        self.spent_usd += cost_usd
        if label.startswith("eval:arm:"):
            self.sessions_run += 1
            self.max_session_cost_usd = max(self.max_session_cost_usd, cost_usd)
        if cost_usd > 0 or in_tok or out_tok:
            da._append_cost(self.ledger_path, self.date, in_tok, out_tok, cost_usd, label)  # noqa: SLF001 -- the analyzer's own ledger writer


_COST_TRACKER: CostTracker | None = None


def set_cost_tracker(tracker: CostTracker | None) -> None:
    global _COST_TRACKER
    _COST_TRACKER = tracker


def forward_mining_cost(state_dir: Path) -> None:
    """The dreamed task mines under a sandbox CCGM_DREAMING_DIR, so the
    analyzer wrote its spend to a cost.log that is deleted with the sandbox.
    Copy those rows into the run's tracker and the real ledger."""
    tracker = _COST_TRACKER
    sandbox_log = state_dir / "cost.log"
    if tracker is None or not sandbox_log.is_file():
        return
    for line in sandbox_log.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        try:
            in_tok, out_tok, cost = int(parts[1]), int(parts[2]), float(parts[3])
        except ValueError:
            continue
        tracker.record(in_tok=in_tok, out_tok=out_tok, cost_usd=cost, label=f"eval:mine:{parts[4]}")
    if tracker.spent_usd > tracker.cap_usd + _COST_EPSILON:
        raise BudgetAbortError(
            f"in-eval mining pushed spend to ${tracker.spent_usd:.4f}, over the ${tracker.cap_usd:.4f} cap"
        )


def write_mining_budget(state_dir: Path) -> None:
    """Hand the sandboxed analyzer what is left of the run cap as its daily
    cap, so mining cannot overspend what the arms and judges already used."""
    tracker = _COST_TRACKER
    if tracker is None or tracker.cap_usd == float("inf"):
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "config.json").write_text(
        json.dumps({"daily_cost_cap_usd": max(0.0, tracker.remaining_usd())}), encoding="utf-8",
    )


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
    (the store's own supersede-filtering is what the task exercises).

    An entry carrying `"dwell_hours": N` (Epic 4, dwell-leak assertion)
    stamps `dwell_until = utcnow() + N hours` via the store's own
    `dwell_until_from_hours()` -- the exact posture Epic 3's optimistic
    engine gives a fresh `learning_add`/`learning_supersede` (optimistic-
    memory §3.2) -- so a task can declare a seeded row that is written but
    not yet read-eligible. Absent/None (the overwhelmingly common case,
    every one of the 9 real eval tasks today) seeds an immediately-live
    row, unchanged from before this key existed."""
    if not seed_learnings:
        return
    with _learnings_store_pointed_at(learnings_dir):
        prev_id: str | None = None
        for spec in seed_learnings:
            content = spec["content"]
            type_ = spec.get("type", "pattern")
            confidence = spec.get("confidence", learnings_store.DEFAULT_CONFIDENCE)
            tags = spec.get("tags") or []
            dwell_until = (
                learnings_store.dwell_until_from_hours(spec["dwell_hours"])
                if spec.get("dwell_hours") is not None
                else None
            )
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
                    dwell_until=dwell_until,
                )
                if new_entry is None:
                    raise ValueError(f"seed_temp_store: supersede target {prev_id!r} not found")
                prev_id = new_entry["id"]
            else:
                entry = learnings_store.build_entry(
                    type_=type_, content=content, confidence=confidence, tags=tags, project=project_slug,
                    dwell_until=dwell_until,
                )
                learnings_store.append_entry(entry, slug=project_slug)
                prev_id = entry["id"]


# ---------------------------------------------------------------------------
# claude -p invocation
# ---------------------------------------------------------------------------


def resolve_claude_bin(claude_bin: str) -> str:
    """Turn `claude_bin` into an ABSOLUTE path, so the arm subprocess launches
    regardless of what PATH the caller's environment happens to carry (#1027).

    A name with no separator is looked up on the ambient PATH first, then in
    CLAUDE_BIN_FALLBACK_DIRS. A caller who already passed a path (absolute,
    or relative with a separator) is taken at its word and only checked for
    executability. Raises ClaudeBinaryNotFoundError, naming everything it
    searched, rather than letting every run degrade into a format error.

    "Is it a path" is decided on the RAW string, not on `Path.parts`:
    `Path("./claude").parts` is `('claude',)` -- the leading dot normalizes
    away -- so a parts-based test misroutes `--claude-bin ./claude` into the
    PATH branch. `shutil.which` happens to honour the dirname when the file
    exists, but when it does NOT exist the run falls through to
    CLAUDE_BIN_FALLBACK_DIRS and launches whatever is installed there, with
    no diagnostic that the operator's choice was ignored.

    Absolute, but NOT symlink-resolved: `~/.local/bin/claude` is a symlink
    into a versioned binary, and a CLI update mid-run swings that link and
    can delete the version it pointed at. Keeping the installer's stable
    entry point means a long eval survives an update under it."""
    candidate = Path(claude_bin).expanduser()
    caller_gave_a_path = (
        os.sep in claude_bin
        or (os.altsep is not None and os.altsep in claude_bin)
        or claude_bin.startswith((".", "~"))
    )
    if caller_gave_a_path:
        absolute = Path(os.path.abspath(candidate))
        if absolute.is_file() and os.access(absolute, os.X_OK):
            return str(absolute)
        raise ClaudeBinaryNotFoundError(f"{claude_bin!r} is not an executable file (resolved to {absolute})")

    searched: list[str] = []
    on_path = shutil.which(claude_bin)
    if on_path:
        return os.path.abspath(on_path)
    searched.append(f"PATH={os.environ.get('PATH', '')!r}")

    for raw_dir in CLAUDE_BIN_FALLBACK_DIRS:
        install_dir = Path(raw_dir).expanduser()
        searched.append(str(install_dir))
        found = install_dir / claude_bin
        if found.is_file() and os.access(found, os.X_OK):
            return os.path.abspath(found)

    raise ClaudeBinaryNotFoundError(
        f"{claude_bin!r} not found. Searched: " + "; ".join(searched)
        + ". Set CCGM_EVAL_CLAUDE_BIN (or --claude-bin) to its absolute path."
    )


# The raw output of the FIRST agent run that failed to execute this process
# (#1027). Kept out of the result rows on purpose -- it is a diagnostic for
# the whole-run abort below, printed to stderr, never persisted into the
# JSONL the gate reads. reset_agent_error_samples() exists for tests.
_AGENT_ERROR_SAMPLES: list[str] = []


def reset_agent_error_samples() -> None:
    _AGENT_ERROR_SAMPLES.clear()


def _record_agent_error(detail: str) -> None:
    if not _AGENT_ERROR_SAMPLES:
        _AGENT_ERROR_SAMPLES.append(detail)


def whole_run_format_error_rate(rows: list[dict[str, Any]]) -> float | None:
    """Fraction of agent runs, across every arm of every row so far, that
    failed to execute. None when no arm actually ran (an all-`error`-row run,
    or a set of rows with runs == 0) -- "nothing ran" is not "everything
    failed", and only the caller knows which of the two it is looking at."""
    total = 0
    errors = 0.0
    for row in rows:
        for arm in ARMS:
            stats = row.get(arm) or {}
            count = int(stats.get("runs", 0) or 0)
            if count <= 0:
                continue
            total += count
            errors += float(stats.get("format_error_rate", 0.0) or 0.0) * count
    if total == 0:
        return None
    return errors / total


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
    failed to execute).

    `claude_bin` should already be an absolute path (main() runs it through
    resolve_claude_bin first, #1027). A bare name still works when the
    ambient PATH resolves it, but relying on that is what let a launchd
    PATH turn every run into a silent format error for seven weeks."""
    home_dir.mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in SUBPROCESS_ENV_ALLOWLIST if key in os.environ}
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


def _parse_judge_verdict(text: str) -> dict[str, Any] | None:
    """Parse and validate one judge verdict (#1029). `output_config.format`
    already makes the response JSON-valid against JUDGE_VERDICT_SCHEMA, so
    this is a plain json.loads plus the shape check the harness has always
    applied -- no fence stripping, no scanning for the first `{`. The judge
    owns its own parse: it deliberately does NOT reuse dream_analyze.py's
    `_parse_json_object`, whose leniency exists for the map/reduce prompts'
    unconstrained output, not for a schema-enforced two-field verdict.
    Returns None on anything that is not a well-formed verdict."""
    try:
        obj = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    score = obj.get("score")
    # bool is a subclass of int; `{"score": true}` is not a score.
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if "pass" in obj and not isinstance(obj["pass"], bool):
        return None
    return obj


def _call_judge_api(
    *, model: str, system_prompt: str, user_obj: dict[str, Any], max_output_tokens: int, api_key: str, api_url: str,
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """A judge-specific Messages API call. `da.get_model_response()` /
    `_call_curl_with_retry()` carry the map/reduce request shape and
    dream_analyze.py is never modified from here -- this is a small,
    judge-specific sibling that mirrors da's retry/transport shape while
    reusing da's own (unmodified) assistant-text extractor, rather than an
    edit to that shared file. Never raises -- returns (None, zeroed usage)
    on any transport/parse failure.

    The request pins three things (#1029, #1026, #1028):

    * NO `temperature`. Every judge model from Opus 4.7 / Sonnet 5 onward
      rejects sampling parameters with a 400, and the default judge is
      `claude-opus-4-8`, so the old probe-and-retry made one guaranteed-
      failing request per run. Grading determinism now comes from the
      schema and the rubric, not a sampling dial.
    * `thinking: {"type": "disabled"}`, explicitly. Effort is left at the
      model default (`high`), where disabling thinking is accepted; only
      `xhigh`/`max` reject the pairing. Without this, a bump to a model
      that thinks by default would spend the output cap on thinking.
    * `output_config.format`, so the verdict is schema-valid by
      construction and _parse_judge_verdict() is a plain json.loads."""
    zero_usage = {"input_tokens": 0, "output_tokens": 0}
    request_body = {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": system_prompt,
        "thinking": {"type": "disabled"},
        "output_config": {"format": {"type": "json_schema", "schema": JUDGE_VERDICT_SCHEMA}},
        "messages": [{"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)}],
    }
    payload = json.dumps(request_body)

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
            print(f"memory_eval: judge Messages API returned HTTP {code}: {body[:400]}", file=sys.stderr)
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
        return _parse_judge_verdict(text), usage_out

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
    """Returns {"pass": bool, "score": float 0-10, "usage": {...}}, plus an
    "error" key (ONLY present on failure -- never on a genuine, parsed
    judge verdict) whenever the score below is a placeholder rather than a
    real judgment.

    Stage-2 #771 Blocking fix: a transport failure (`_call_judge_api()`
    returning `(None, ...)`) or a structurally-valid-but-non-numeric
    `score` field used to be coerced into `score: 0.0` with NO visible
    marker -- indistinguishable from a genuine low score to every
    downstream consumer (`_run_one()`, `_aggregate_arm_runs()`,
    `classify_bucket()`, `gate_check()`). Both failure branches below now
    tag the sentinel with "error" so `_run_one()` can propagate it into
    the row and `_aggregate_arm_runs()` can exclude it from `mean_score`
    instead of silently averaging in a fabricated zero.

    `offline_score`, when given, short-circuits to a canned score with NO
    network call at all (memory_eval's own --offline contract) -- the
    canned value stands in for "what the judge would have said", so the
    live judge-call machinery below is exercised only when actually live,
    and NEVER carries an "error" key (a canned score is never a failure).
    """
    tracker = _COST_TRACKER
    if offline_score is not None:
        score = max(0.0, min(10.0, float(offline_score["score"])))
        # `judge_usage` in a canned score stands in for the usage a live
        # judge call would report; it reaches the ledger the same way.
        canned = offline_score.get("judge_usage") or {}
        usage = {
            "input_tokens": int(canned.get("input_tokens", 0) or 0),
            "output_tokens": int(canned.get("output_tokens", 0) or 0),
        }
        if tracker is not None and (usage["input_tokens"] or usage["output_tokens"]):
            tracker.record(
                in_tok=usage["input_tokens"], out_tok=usage["output_tokens"],
                cost_usd=tracker.judge_cost(judge_model, usage["input_tokens"], usage["output_tokens"]),
                label=f"eval:judge:{judge_model}",
            )
        return {"pass": score >= 6.0, "score": score, "usage": usage}

    if tracker is not None:
        tracker.check(
            tracker.judge_estimate(judge_model, judge_system_prompt, len(json.dumps(payload))), "judge call",
        )
    parsed, usage = _call_judge_api(
        model=judge_model,
        system_prompt=judge_system_prompt,
        user_obj=payload,
        max_output_tokens=DEFAULT_JUDGE_MAX_OUTPUT_TOKENS,
        api_key=api_key or "",
        api_url=api_url,
    )
    if tracker is not None:
        tracker.record(
            in_tok=usage["input_tokens"], out_tok=usage["output_tokens"],
            cost_usd=tracker.judge_cost(judge_model, usage["input_tokens"], usage["output_tokens"]),
            label=f"eval:judge:{judge_model}",
        )
    if parsed is None or "score" not in parsed:
        return {"pass": False, "score": 0.0, "usage": usage, "error": "judge did not return parseable {pass, score}"}
    try:
        score = max(0.0, min(10.0, float(parsed.get("score"))))
    except (TypeError, ValueError):
        return {
            "pass": False, "score": 0.0, "usage": usage,
            "error": f"judge returned a non-numeric score: {parsed.get('score')!r}",
        }
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
        tracker = _COST_TRACKER
        if tracker is not None:
            tracker.check(tracker.next_session_estimate(max_budget_usd), "claude -p session")
        result = run_claude_p(
            prompt=prompt, workdir=workdir, config_dir=config_dir, home_dir=home_dir,
            model=backbone, inject=inject, api_key=api_key, learnings_dir=learnings_dir,
            claude_bin=claude_bin, max_budget_usd=max_budget_usd, timeout_s=timeout_s,
        )
        if tracker is not None:
            session_usage = result.get("usage") or {}
            tracker.record(
                in_tok=int(session_usage.get("input_tokens", 0) or 0),
                out_tok=int(session_usage.get("output_tokens", 0) or 0),
                cost_usd=float(result.get("total_cost_usd", 0.0) or 0.0),
                label=f"eval:arm:{backbone}",
            )
        if result.get("is_error"):
            # Keep the first failure's raw detail for the whole-run abort in
            # main() (#1027); per-row failures stay non-fatal.
            _record_agent_error(f"{task_id} / {arm} / run {run_index}: {result.get('result')}")

    if result.get("is_error"):
        # #1027: an agent run that never executed has nothing to grade. The
        # judge would score the untouched fixture -- which on a canary task
        # scores 10.0, an actively wrong number for a run that did no work --
        # and on a broken harness that is a full task's judge calls spent
        # every night before the whole-run abort fires.
        #
        # The placeholder score below is NEVER averaged into anything: the
        # row is tagged `launch_error` and _aggregate_arm_runs() drops it
        # from every mean. Recording an untagged 0.0 here was itself a
        # fail-open -- two failed launches in a five-run baseline arm pulled
        # the mean down far enough to classify the row `high_value` and
        # open the gate on a partially broken harness. A run that did not
        # execute must not move a score in EITHER direction.
        judged = {"pass": False, "score": 0.0, "usage": {"input_tokens": 0, "output_tokens": 0}}
    else:
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
    # #789: Claude Code caches the static prompt prefix (system prompt,
    # tools, and the large static facts block), so usage["input_tokens"]
    # reports only the marginal UNCACHED remainder -- the cache_read/
    # cache_creation counts carry the rest of the true prompt size. The
    # efficiency ratio (classify_bucket Path B) must compare TOTAL input or
    # the full-context arm's facts block is invisible to the metric. Keep
    # input_tokens unchanged (its meaning for cost/reporting is the billable
    # marginal count); the offline branch above has no cache fields, so
    # total_input_tokens == input_tokens there.
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    cache_read_input_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
    cache_creation_input_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)
    row = {
        "score": judged["score"],
        "pass": judged["pass"],
        "input_tokens": input_tokens,
        "total_input_tokens": input_tokens + cache_read_input_tokens + cache_creation_input_tokens,
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "turns": int(result.get("num_turns", 0) or 0),
        "run_cost_usd": float(result.get("total_cost_usd", 0.0) or 0.0),
        "judge_input_tokens": int(judged.get("usage", {}).get("input_tokens", 0) or 0),
        "judge_output_tokens": int(judged.get("usage", {}).get("output_tokens", 0) or 0),
        "is_error": bool(result.get("is_error", False)),
        # #1027: None when the agent process ran; a string naming the
        # failure when it never executed. Consumed by _aggregate_arm_runs()
        # to exclude this run from every mean -- the sibling of
        # "judge_error" one level down the same pipeline.
        "launch_error": (str(result.get("result")) if result.get("is_error") else None),
        # Stage-2 #771: None on a genuine judge verdict (including the
        # --offline canned path); a non-empty string whenever `score`
        # above is a failure sentinel, not a real judgment -- consumed by
        # _aggregate_arm_runs() to exclude this run from mean_score.
        "judge_error": judged.get("error"),
    }
    shutil.rmtree(run_root, ignore_errors=True)
    return row


def _aggregate_arm_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        return {
            "mean_score": 0.0, "pass_rate": 0.0, "mean_input_tokens": 0.0, "mean_total_input_tokens": 0.0,
            "mean_output_tokens": 0.0,
            "mean_turns": 0.0, "mean_cost_usd": 0.0, "format_error_rate": 0.0, "judge_error_rate": 0.0, "runs": 0,
        }
    # Stage-2 #771 Blocking fix: a run whose judge call itself failed
    # (transport/parse failure -- judge_output() tags it via "judge_error")
    # carries a FABRICATED score=0.0/pass=False sentinel, not a real
    # judgment. Averaging it into mean_score/pass_rate would let a judge
    # outage masquerade as "the agent scored 0.0 here", which is exactly
    # the silent-fabrication defect the fix closes -- both stats are
    # computed only from runs the judge actually scored. format_error_rate
    # stays scoped to the AGENT's own is_error flag (unrelated -- an agent
    # run can succeed while its judge call fails, and vice versa);
    # judge_error_rate is the judge-side counterpart, tracked separately so
    # gate_check() can refuse to trust a classification built on it.
    #
    # #1027: a run that never EXECUTED is excluded one level earlier, from
    # every mean rather than only the score ones. Its token, turn and cost
    # figures are all zero -- averaging them in understates the arm on
    # exactly the metrics classify_bucket() compares. The rates below stay
    # over ALL attempted runs: format_error_rate is the failure rate, so
    # its denominator must be everything that was tried.
    # Keyed on `is_error` as well as the tag: `is_error` is the canonical
    # per-run flag (format_error_rate is computed from it), and one
    # predicate over both keeps the two from drifting apart.
    executed_runs = [r for r in runs if not (r.get("is_error") or r.get("launch_error"))]
    scored_runs = [r for r in executed_runs if not r.get("judge_error")]
    return {
        "mean_score": statistics.fmean(r["score"] for r in scored_runs) if scored_runs else 0.0,
        "pass_rate": (sum(1 for r in scored_runs if r["pass"]) / len(scored_runs)) if scored_runs else 0.0,
        "mean_input_tokens": statistics.fmean(r["input_tokens"] for r in executed_runs) if executed_runs else 0.0,
        "mean_total_input_tokens": statistics.fmean(r["total_input_tokens"] for r in executed_runs) if executed_runs else 0.0,
        "mean_output_tokens": statistics.fmean(r["output_tokens"] for r in executed_runs) if executed_runs else 0.0,
        "mean_turns": statistics.fmean(r["turns"] for r in executed_runs) if executed_runs else 0.0,
        # Cost stays over ALL attempted runs, unlike the quality metrics
        # above: a run that stopped against --max-budget-usd spent real
        # money before it was flagged, and _build_result_row() multiplies
        # this by the full `runs` count. Averaging over survivors while
        # multiplying by everything under-reports spend into the shared
        # ledger that eval_refresh_cost_cap_usd is checked against.
        "mean_cost_usd": statistics.fmean(r["run_cost_usd"] for r in runs),
        "format_error_rate": sum(1 for r in runs if r["is_error"]) / len(runs),
        "judge_error_rate": sum(1 for r in runs if r.get("judge_error")) / len(runs),
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
    *, baseline_mean: float, treatment_mean: float, full_context_mean: float,
    treatment_input_tokens: float = 0.0, full_context_input_tokens: float = 0.0,
) -> tuple[str, float, float]:
    """Returns (bucket, delta, delta_sat).

    delta = treatment_mean - baseline_mean
    delta_sat = treatment_mean - full_context_mean (bizlogic-002, Δ_sat)

    Precedence (regression checked first -- a real regression must never
    be reclassified as "gap" just because both means happen to also be
    low; the two conditions can genuinely overlap, e.g. baseline=4.0,
    treatment=2.9): regression > high_value > redundant > gap >
    "inconclusive" (a task that clears none of the four named buckets).

    high_value has TWO independent paths (#784), both gated behind
    delta >= HIGH_VALUE_DELTA_THRESHOLD -- a task that does not clear
    baseline over noise is never high_value by either path:
      - Path A (outcome win): memory BEATS the full-context dump on score
        (delta_sat > 0). Memory added value beyond a naive dump of the same
        facts. Independent of token cost.
      - Path B (efficiency win): memory MATCHES the dump's outcome within
        noise (delta_sat >= -HIGH_VALUE_SAT_TOLERANCE) at materially fewer
        input tokens (treatment_input_tokens <= HIGH_VALUE_EFFICIENCY_RATIO
        * full_context_input_tokens). For a capable model that resolves even
        a full dump on its own, matching the dump's result at a fraction of
        the context cost IS memory's value. Self-guarding: Path B can only
        fire when full_context_input_tokens is materially larger than
        treatment's, so it stays inert on today's small fixtures (where the
        two arms' token counts are comparable) and defaults OFF when the
        token means are absent -- both params default to 0.0, which fails
        the `full_context_input_tokens > 0` guard.
    """
    delta = treatment_mean - baseline_mean
    delta_sat = treatment_mean - full_context_mean

    if delta <= REGRESSION_DELTA_THRESHOLD:
        return "regression", delta, delta_sat
    if delta >= HIGH_VALUE_DELTA_THRESHOLD:
        # Path A (outcome win): memory beats the full dump on score.
        if delta_sat > 0:
            return "high_value", delta, delta_sat
        # Path B (efficiency win): memory MATCHES the dump's outcome (does
        # not lose beyond noise) at materially fewer input tokens. BOTH
        # token means must be positive -- a degenerate zero-input treatment
        # arm (a total run failure) is trivially <= any ratio of the dump
        # and must never spuriously satisfy the efficiency condition.
        if (
            delta_sat >= -HIGH_VALUE_SAT_TOLERANCE
            and treatment_input_tokens > 0
            and full_context_input_tokens > 0
            and treatment_input_tokens <= HIGH_VALUE_EFFICIENCY_RATIO * full_context_input_tokens
        ):
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
            treatment_input_tokens=arms["treatment"]["mean_total_input_tokens"],
            full_context_input_tokens=arms["full_context"]["mean_total_input_tokens"],
        )
        rows.append(_build_result_row(
            task_id=task_id, kind=kind, backbone=backbone, runs=runs, offline=offline_all_scores is not None,
            arms=arms, bucket=bucket, delta=delta, delta_sat=delta_sat, seed=seed_learnings,
        ))
    return rows


def launch_failure_summary(arms: dict[str, dict[str, Any]]) -> str | None:
    """A human-readable "which arm, how many runs" summary of the launch
    failures in `arms`, or None when every attempted run executed (#1027).

    This is the evidence half of the row-level rule; the decision half is
    downgrade_bucket_for_launch_failures() below."""
    parts = []
    for arm in ARMS:
        stats = arms.get(arm) or {}
        total = int(stats.get("runs", 0) or 0)
        rate = float(stats.get("format_error_rate", 0.0) or 0.0)
        if total <= 0 or rate <= 0:
            continue
        parts.append(f"{arm} {round(rate * total)}/{total}")
    if not parts:
        return None
    return "runs that failed to execute: " + ", ".join(parts)


def downgrade_bucket_for_launch_failures(
    bucket: str, arms: dict[str, dict[str, Any]]
) -> tuple[str, str | None]:
    """THE INVARIANT: a launch failure may only move a row TOWARD a closed
    gate, never toward an open one (#1027).

    A row is classified from the runs that executed -- _aggregate_arm_runs()
    already keeps a run that did not complete out of every mean. But an arm
    measured on the survivors is a smaller sample, not a measurement of
    memory, so a row holding one is a harness observation and must not be
    allowed to open the gate. This function is the single place that decides
    that, and it is monotone in exactly one direction:

    * `regression` is PRESERVED, so the row still reads as one. (Since #1098
      the gate reads pass rates through assess_row(), not bucket names, and
      applies the same invariant there: a row with a failed launch shows its
      regression or pauses the gate, never opens it.)
    * EVERY other bucket becomes `error` -- including `high_value`, which is
      the case that matters (a flake in the full_context arm can inflate
      Δ_sat off runs that never happened), and including the already-inert
      `redundant` / `inconclusive` / `gap`. One rule with one exception is
      easier to verify than a list, and `error` states in the row and the
      summary that the harness, not memory, produced this row.

    `error` is a bucket classify_bucket() never returns; it marks the row as
    a harness observation in the JSONL and the summary.

    Returns (bucket, launch_failures) -- the summary string is returned even
    when the bucket is preserved, so the flake stays visible in the row and
    the printed summary either way."""
    launch_failures = launch_failure_summary(arms)
    if launch_failures is None:
        return bucket, None
    if bucket == "regression":
        return bucket, launch_failures
    return "error", launch_failures


def _build_result_row(
    *, task_id: str, kind: str, backbone: str, runs: int, offline: bool,
    arms: dict[str, dict[str, Any]], bucket: str, delta: float, delta_sat: float, extra: dict[str, Any] | None = None,
    seed: Any = None,
) -> dict[str, Any]:
    token_delta = arms["treatment"]["mean_input_tokens"] + arms["treatment"]["mean_output_tokens"] - (
        arms["baseline"]["mean_input_tokens"] + arms["baseline"]["mean_output_tokens"]
    )
    turn_delta = arms["treatment"]["mean_turns"] - arms["baseline"]["mean_turns"]
    total_cost = sum(a["mean_cost_usd"] * a["runs"] for a in arms.values())
    # #1027: a launch failure may only move this row toward a CLOSED gate.
    # See downgrade_bucket_for_launch_failures() for why `regression`
    # survives the downgrade and everything else does not.
    bucket, launch_failures = downgrade_bucket_for_launch_failures(bucket, arms)
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
    if seed is not None:
        # The gate checks a non-canary task only when this changed since the
        # previous run (#1098 item 2.1).
        row["seed_fingerprint"] = seed_fingerprint(seed)
    if launch_failures is not None:
        row["task_error"] = launch_failures
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
    tracker = _COST_TRACKER
    if tracker is not None and offline_dir is None:
        tracker.check(ESTIMATED_MINING_COST_USD, "in-eval mining")
        write_mining_budget(dreaming_state_dir)
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
    forward_mining_cost(dreaming_state_dir)
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
            treatment_input_tokens=arms["treatment"]["mean_total_input_tokens"],
            full_context_input_tokens=arms["full_context"]["mean_total_input_tokens"],
        )
        rows.append(_build_result_row(
            task_id=task_id, kind="dreamed", backbone=backbone, runs=runs, offline=offline,
            arms=arms, bucket=bucket, delta=delta, delta_sat=delta_sat,
            # The dreamed task's seed is the learning mining produced tonight.
            seed=follow_up_facts,
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


def _results_files_by_mtime() -> list[Path]:
    d = evals_dir()
    if not d.is_dir():
        return []
    return sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)


def _find_latest_results_file() -> Path | None:
    candidates = _results_files_by_mtime()
    return candidates[-1] if candidates else None


def harness_broken_marker_path(date: str) -> Path:
    """Where the whole-run abort records that the harness, not memory, is why
    there are no results for `date` (#1027). Deliberately NOT a `.jsonl`:
    `_find_latest_results_file()`'s glob must never pick it up as results."""
    return evals_dir() / f"{date}{HARNESS_BROKEN_MARKER_SUFFIX}"


def write_harness_broken_marker(*, date: str, detail: str) -> Path:
    path = harness_broken_marker_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"date": date, "generated_at": _utc_now_iso(), "first_failure": detail}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def clear_harness_broken_markers() -> int:
    """Remove every abort marker in evals/. Called on the success path: a run
    that produced results has demonstrated the harness works."""
    d = evals_dir()
    if not d.is_dir():
        return 0
    removed = 0
    for marker in d.glob(f"*{HARNESS_BROKEN_MARKER_SUFFIX}"):
        marker.unlink(missing_ok=True)
        removed += 1
    return removed


def _find_latest_harness_broken_marker() -> Path | None:
    d = evals_dir()
    if not d.is_dir():
        return None
    candidates = sorted(d.glob(f"*{HARNESS_BROKEN_MARKER_SUFFIX}"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def budget_abort_marker_path(date: str) -> Path:
    return evals_dir() / f"{date}{BUDGET_ABORT_MARKER_SUFFIX}"


def _find_latest_budget_abort_marker() -> Path | None:
    d = evals_dir()
    if not d.is_dir():
        return None
    candidates = sorted(d.glob(f"*{BUDGET_ABORT_MARKER_SUFFIX}"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def write_budget_abort_marker(
    *, date: str, phase: str, cap_usd: float, spent_usd: float, sessions_run: int, detail: str,
) -> Path:
    """Record that a run stopped on budget. `phase` is `module-budget` (the
    30-day budget was already spent), `preflight` (the estimate exceeded the
    cap) or `run` (the running total would cross it). It pauses the gate
    until a later run writes results."""
    path = budget_abort_marker_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "date": date, "generated_at": _utc_now_iso(), "phase": phase, "cap_usd": cap_usd,
                "spent_usd": round(spent_usd, 6), "sessions_run": sessions_run, "detail": detail,
            },
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return path


def estimate_run_cost(
    tasks: list[dict[str, Any]], *, backbones: list[str], runs: int, judge_model: str,
    judge_system_prompt: str, tracker: CostTracker,
) -> float:
    """Preflight estimate: arm sessions at the typical session price, one
    judge call per session, and the mining cost of each dreamed task."""
    sessions = len(tasks) * len(backbones) * len(ARMS) * runs
    judge = tracker.judge_estimate(judge_model, judge_system_prompt, ESTIMATED_JUDGE_PAYLOAD_CHARS)
    mining = sum(ESTIMATED_MINING_COST_USD for t in tasks if t["kind"] == "dreamed")
    return sessions * (tracker.session_estimate_usd + judge) + mining


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


def latest_auto_integration_epoch(learnings_root: Path) -> float | None:
    """Max timestamp (epoch seconds) across dreaming's OWN content-shaping
    writes: add/supersede/deprecate/contradict op-events tagged `auto: true`
    (the optimistic engine tags every write it makes, learnings_store.py
    `_build_op_row`). These are the only writes that change what a re-run of
    the eval would measure about dreaming, so they are the only ones that
    make the results stale (#1098 item 2.1).

    Excluded on purpose: `verify` counter-ops (adrev-403), every non-auto
    op-event, and legacy v1 rows. An agent's in-session `ccgm-learnings-log`
    write has nothing to do with dreaming; before #1098 it made the eval
    stale on 15 of the last 30 nights."""
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
                if obj.get("op") not in CONTENT_SHAPING_OPS or obj.get("auto") is not True:
                    continue
                epoch = learnings_store._parse_iso(obj.get("timestamp") or "")  # noqa: SLF001 -- same-package internal reuse
                if epoch and (latest is None or epoch > latest):
                    latest = epoch
    return latest


def seed_fingerprint(seed: Any) -> str:
    """Stable short hash of a task's seed learnings (or, for the dreamed
    task, the mined proposal it applied). The gate compares it across runs
    to tell whether a task's seed changed since the last run."""
    canonical = json.dumps(seed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _iso_from_epoch(epoch: float) -> str:
    return learnings_store._iso_from_epoch(epoch)  # noqa: SLF001 -- same-package internal reuse


def _scored_runs(arm: dict[str, Any], runs: int) -> int:
    """Runs of one arm that executed AND were judged: the denominator of its
    `pass_rate` (_aggregate_arm_runs excludes launch and judge failures)."""
    failed = round(float(arm.get("format_error_rate", 0) or 0) * runs)
    judge_failed = round(float(arm.get("judge_error_rate", 0) or 0) * runs)
    return max(0, runs - failed - judge_failed)


def assess_row(row: dict[str, Any]) -> str:
    """One checked row's verdict for the gate: `regression`, `ok`, or
    `unmeasured`.

    A supported regression: the baseline arm passes the task's check in at
    least 2 of 3 runs (SUPPORTED_FRACTION) and the treatment arm fails it in
    at least 2 of 3, each arm with at least MIN_SUPPORTED_RUNS scored runs.
    Pass rates, not judge-score deltas: the old -1.0 mean-score rule fired on
    one-point dips of a single backbone (RCA R1).

    `unmeasured` covers a row with too few runs, or any failed launch or
    judge error in either arm. A regression the surviving runs still show
    stands; otherwise the row cannot vouch for memory and the gate pauses.
    This keeps #1027's invariant: a launch failure never moves the gate
    toward open."""
    runs = int(row.get("runs", 0) or 0)
    baseline = row.get("baseline") or {}
    treatment = row.get("treatment") or {}
    n_base, n_treat = _scored_runs(baseline, runs), _scored_runs(treatment, runs)
    if n_base >= MIN_SUPPORTED_RUNS and n_treat >= MIN_SUPPORTED_RUNS:
        base_pass = round(float(baseline.get("pass_rate", 0) or 0) * n_base)
        treat_fail = n_treat - round(float(treatment.get("pass_rate", 0) or 0) * n_treat)
        if base_pass >= SUPPORTED_FRACTION * n_base and treat_fail >= SUPPORTED_FRACTION * n_treat:
            return "regression"
    complete = n_base == runs and n_treat == runs and runs >= MIN_SUPPORTED_RUNS
    return "ok" if complete else "unmeasured"


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("task_id")), str(row.get("backbone"))


def _checked_rows(rows: list[dict[str, Any]], previous: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows the regression rule applies to: every canary, and every task
    whose seed changed since the previous run. A row with no fingerprint on
    either side cannot prove its seed stayed the same, so it is checked."""
    before = {_row_key(r): r.get("seed_fingerprint") for r in previous}
    checked = []
    for row in rows:
        fingerprint = row.get("seed_fingerprint")
        prior = before.get(_row_key(row))
        if row.get("kind") == "canary" or not fingerprint or not prior or fingerprint != prior:
            checked.append(row)
    return checked


def _gate(state: str, code: str, reason: str, *, since: str | None = None) -> dict[str, Any]:
    return {"state": state, "code": code, "reason": reason, "since": since}


def gate_check(*, freshness_days: int = DEFAULT_EVAL_FRESHNESS_DAYS, now: float | None = None) -> dict[str, Any]:
    """The integration gate (#1098 item 2.1). Returns
    `{"state", "code", "reason", "since"}` with state one of:

    * `open`   -- no supported regression. No high_value row and no live
                  dreamed row is required (#1037): value is measured by the
                  recurrence metric, not by this gate.
    * `closed` -- a supported regression (see assess_row) on a checked row
                  (see _checked_rows), or the live dreamed row's noise-only
                  corpus yielded a proposal (adrev-305). `since` is the mtime
                  of the results file before this one -- the last run that
                  could have been green -- or None when there is none; the
                  breaker implicates batches integrated after it.
    * `paused` -- nothing usable was measured: a harness-broken marker or a
                  budget-abort marker at least as new as the newest results,
                  no results, results past the freshness bound, results
                  older than dreaming's own last auto-integrated write, an
                  empty file, or a checked row that did not fully run. An
                  infra state: it pauses integration and is never a breaker
                  content anomaly.

    Codes: ok, regression, noise_contamination, harness_broken,
    budget_abort, no_results, results_stale, stale_own_writes,
    results_empty, unmeasured_rows."""
    now = now if now is not None else time.time()
    results = _results_files_by_mtime()
    latest = results[-1] if results else None
    latest_mtime = latest.stat().st_mtime if latest is not None else None

    # `>=`, not `>`: on a filesystem with 1-second mtime granularity a marker
    # written in the same second as the newest results must not lose the tie.
    marker = _find_latest_harness_broken_marker()
    if marker is not None and (latest_mtime is None or marker.stat().st_mtime >= latest_mtime):
        broken_date = marker.name[: -len(HARNESS_BROKEN_MARKER_SUFFIX)] or "an unknown date"
        return _gate("paused", "harness_broken", f"harness broken: every agent run failed to execute on {broken_date}")

    abort = _find_latest_budget_abort_marker()
    if abort is not None and (latest_mtime is None or abort.stat().st_mtime >= latest_mtime):
        abort_date = abort.name[: -len(BUDGET_ABORT_MARKER_SUFFIX)] or "an unknown date"
        return _gate("paused", "budget_abort", f"the eval run on {abort_date} stopped on its cost cap; no results since")

    if latest is None:
        return _gate("paused", "no_results", "no results")

    if now - latest_mtime > freshness_days * 86400:
        return _gate(
            "paused", "results_stale",
            f"results file {latest.name} is older than the freshness bound ({freshness_days}d)",
        )

    last_auto = latest_auto_integration_epoch(_learnings_root_for_gate())
    if last_auto is not None and latest_mtime < last_auto:
        return _gate(
            "paused", "stale_own_writes",
            f"dreaming integrated learnings after {latest.name} was written; the results no longer describe the store",
        )

    rows = _read_results_file(latest)
    if not rows:
        return _gate("paused", "results_empty", f"results file {latest.name} is empty")

    previous = _read_results_file(results[-2]) if len(results) > 1 else []
    since = _iso_from_epoch(results[-2].stat().st_mtime) if len(results) > 1 else None
    checked = _checked_rows(rows, previous)
    verdicts = [(row, assess_row(row)) for row in checked]

    regressions = [row for row, verdict in verdicts if verdict == "regression"]
    if regressions:
        names = ", ".join(f"{r.get('task_id')} on {r.get('backbone')}" for r in regressions)
        return _gate(
            "closed", "regression",
            f"supported regression (treatment fails a check baseline passes, >= 2 of 3 runs): {names}",
            since=since,
        )

    noisy = [r for r in rows if r.get("kind") == "dreamed" and not r.get("offline")
             and (r.get("mining") or {}).get("noise_high_value")]
    if noisy:
        return _gate(
            "closed", "noise_contamination",
            "noise-only negative-control corpus yielded a proposal -- mining false-positive (adrev-305)",
            since=since,
        )

    unmeasured = [row for row, verdict in verdicts if verdict == "unmeasured"]
    if unmeasured:
        names = ", ".join(f"{r.get('task_id')} on {r.get('backbone')}" for r in unmeasured)
        return _gate(
            "paused", "unmeasured_rows",
            f"checked row(s) with too few runs, failed launches or judge errors: {names}",
        )

    return _gate("open", "ok", f"no supported regression in {latest.name} ({len(checked)} checked row(s))")


# ---------------------------------------------------------------------------
# Summary rendering
# ---------------------------------------------------------------------------


def render_summary_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "task_id", "kind", "backbone", "baseline", "treatment", "full_context",
        "delta", "delta_sat", "bucket", "fmt_err%", "judge_err%",
    ]
    lines = [" | ".join(headers), "-" * 100]
    any_offline_dreamed = False
    any_judge_error = False
    for r in rows:
        # adrev-305 part (b): the offline dreamed run is a plumbing/
        # regression check only, explicitly NOT evidence of value -- label
        # it as such in the summary (the JSONL already carries this in
        # `note`, but a human reading only stdout would otherwise miss it).
        is_offline_dreamed = r.get("kind") == "dreamed" and bool(r.get("offline"))
        any_offline_dreamed = any_offline_dreamed or is_offline_dreamed
        bucket_cell = f"{r['bucket']}*" if is_offline_dreamed else r["bucket"]
        # Stage-2 #771: worst-case (max) judge_error_rate across the three
        # arms -- surfaces a judge outage in the printed summary, not only
        # the JSONL row, so a human running this interactively sees it too.
        judge_err_rate = max((r.get(arm) or {}).get("judge_error_rate", 0.0) or 0.0 for arm in ARMS)
        any_judge_error = any_judge_error or judge_err_rate > 0
        lines.append(" | ".join([
            r["task_id"], r["kind"], r["backbone"],
            f"{r['baseline']['mean_score']:.2f}", f"{r['treatment']['mean_score']:.2f}", f"{r['full_context']['mean_score']:.2f}",
            f"{r['delta']:+.2f}", f"{r['delta_sat']:+.2f}", bucket_cell,
            # Worst-case across the arms, like judge_err% beside it: a
            # launch failure in ANY arm now buckets the row `error`
            # (#1027), so showing only treatment's rate would leave the
            # reason for that bucket invisible in the printed summary.
            f"{max((r.get(arm) or {}).get('format_error_rate', 0.0) or 0.0 for arm in ARMS) * 100:.0f}",
            f"{judge_err_rate * 100:.0f}",
        ]))
    bucket_counts: dict[str, int] = {}
    for r in rows:
        bucket_counts[r["bucket"]] = bucket_counts.get(r["bucket"], 0) + 1
    lines.append("")
    lines.append("Buckets: " + ", ".join(f"{k}={v}" for k, v in sorted(bucket_counts.items())))
    if any_offline_dreamed:
        lines.append("* offline dreamed row -- plumbing/regression check only, NOT evidence of value (adrev-305)")
    if any_judge_error:
        lines.append(
            "judge_err% > 0 on at least one row -- judge API transport/parse failures occurred; "
            "affected runs are excluded from mean_score, not averaged in as a fabricated 0.0 (Stage-2 #771)"
        )
    if bucket_counts.get("error"):
        lines.append(
            "bucket `error` -- the row's own orchestration failed, or an arm had a run that never "
            "executed; either way it is a harness observation, not a memory measurement. A checked "
            "row like this pauses the gate unless it still shows a regression (#1027, #1098)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def _positive_int(value: str) -> int:
    """argparse `type=` validator (Stage-2 #771 Recommend): `--runs 0` (or
    negative) used to be silently accepted and produced a fully-populated,
    plausible-looking results file where every task falls into the "gap"
    bucket (0 runs -> _aggregate_arm_runs([])'s zeroed defaults for every
    arm) -- a human could misread that as "memory doesn't help here"
    rather than "no runs were ever attempted". Reject it loud at parse
    time instead."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1 (got {value!r})")
    return parsed


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CCGM dreaming: memory eval harness (Epic 7).")
    p.add_argument("--tasks", metavar="GLOB", default=default_tasks_glob(), help="glob of task JSON files")
    p.add_argument("--runs", type=_positive_int, default=DEFAULT_RUNS, help="runs per arm per task per backbone")
    p.add_argument("--backbone", metavar="A,B", help="comma-separated model list (default: configured map_model,reduce_model)")
    p.add_argument("--judge-model", metavar="MODEL", help="default: configured reduce_model")
    p.add_argument("--offline", metavar="DIR", help="canned judge/arm scores + analyzer responses; no network, no API key")
    p.add_argument(
        "--allow-real-dir", action="store_true",
        help="let an --offline run write into the live ~/.claude/dreaming (default: a temp dir)",
    )
    p.add_argument(
        "--gate", action="store_true",
        help="check the latest results file against the integration gate; print JSON, exit 0 open / 1 closed / 3 paused",
    )
    p.add_argument("--freshness-days", type=int, default=DEFAULT_EVAL_FRESHNESS_DAYS)
    p.add_argument("--date", metavar="YYYY-MM-DD", help="override the results filename date (default: today)")
    p.add_argument("--claude-bin", default=os.environ.get("CCGM_EVAL_CLAUDE_BIN", "claude"))
    p.add_argument("--max-budget-usd", type=float, default=DEFAULT_MAX_BUDGET_USD_PER_RUN, help="per-session ceiling passed to claude -p")
    p.add_argument(
        "--max-total-usd", type=float, metavar="USD",
        help="hard cap on this run's total spend (default: config eval_run_cost_cap_usd, 5.0). "
             "Also bounded by what is left of module_budget_usd_30d",
    )
    p.add_argument("--timeout-s", type=int, default=DEFAULT_RUN_TIMEOUT_S)
    return p


def _synthetic_error_row(
    task: dict[str, Any], *, backbones: list[str], runs: int, offline: bool, exc: BaseException,
) -> dict[str, Any]:
    """A placeholder row recorded when a task's own orchestration (mine/
    seed/apply/run) raises before it can produce real arm results (Stage-2
    #771 Recommend). Schema-compatible with a real _build_result_row()
    output (zeroed arms via the same _aggregate_arm_runs([]) defaults
    every other empty-runs case uses) so write_results()/
    render_summary_table()/gate_check() all handle it without special-
    casing. `bucket: "error"` is a value classify_bucket() itself never
    returns, and gate_check() treats it as neither high_value nor
    regression -- inert to the gate, visible in the JSONL and summary."""
    empty_arm = _aggregate_arm_runs([])
    return {
        "date": today_iso(),
        "generated_at": _utc_now_iso(),
        "task_id": task["id"],
        "kind": task["kind"],
        "backbone": ",".join(backbones) if backbones else "unknown",
        "runs": runs,
        "offline": offline,
        "baseline": empty_arm,
        "treatment": empty_arm,
        "full_context": empty_arm,
        "delta": 0.0,
        "delta_sat": 0.0,
        "token_delta": 0.0,
        "turn_delta": 0.0,
        "cost_usd": 0.0,
        "bucket": "error",
        "task_error": f"{type(exc).__name__}: {exc}",
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.gate:
        gate = gate_check(freshness_days=args.freshness_days)
        print(json.dumps({"gate": gate["state"], "code": gate["code"], "reason": gate["reason"], "since": gate["since"]}))
        return GATE_EXIT_CODES[gate["state"]]

    if args.offline:
        moved_to = _isolate_offline_run(allow_real_dir=args.allow_real_dir)
        if moved_to is not None:
            print(
                f"memory_eval: --offline never writes the live dreaming dir; writing to {moved_to} instead "
                "(set CCGM_DREAMING_DIR to choose a dir, or pass --allow-real-dir to write the live one)",
                file=sys.stderr,
            )

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

    # Resolve the CLI to an absolute path ONCE, before anything is spent
    # (#1027). Doing it here means the arm subprocess never depends on the
    # PATH it inherits -- the LaunchAgent's PATH does not carry the native
    # installer's ~/.local/bin, which is what silently turned every nightly
    # run since 2026-07-15 into 100% format errors.
    claude_bin = args.claude_bin
    if offline_dir is None:
        try:
            claude_bin = resolve_claude_bin(args.claude_bin)
        except ClaudeBinaryNotFoundError as exc:
            print(f"memory_eval: {exc}", file=sys.stderr)
            return 1
        print(f"memory_eval: using claude binary {claude_bin}", file=sys.stderr)

    ledger_path = da.cost_log_path()
    ledger_day = today_iso()
    if offline_dir is None:
        run_cap = args.max_total_usd if args.max_total_usd is not None else float(
            cfg.get("eval_run_cost_cap_usd", da.DEFAULT_EVAL_RUN_COST_CAP_USD)
        )
        spent_30d, module_budget = da.module_budget_status(cfg, ledger_day)
        if spent_30d >= module_budget:
            detail = (
                f"30-day module budget reached (spent ${spent_30d:.4f} of ${module_budget:.4f} in cost.log); "
                "refusing to start."
            )
            print(f"memory_eval: {detail}", file=sys.stderr)
            write_budget_abort_marker(
                date=date, phase="module-budget", cap_usd=module_budget, spent_usd=spent_30d,
                sessions_run=0, detail=detail,
            )
            return 1
        cap = min(run_cap, module_budget - spent_30d)
    else:
        cap = float("inf")  # offline: no billed calls, nothing to cap
    tracker = CostTracker(cap_usd=cap, ledger_path=ledger_path, date=ledger_day, cfg=cfg)
    if offline_dir is None:
        estimate = estimate_run_cost(
            tasks, backbones=backbones, runs=args.runs, judge_model=judge_model,
            judge_system_prompt=judge_system_prompt, tracker=tracker,
        )
        if estimate > cap + _COST_EPSILON:
            detail = (
                f"preflight estimate ${estimate:.2f} exceeds the ${cap:.2f} cap "
                f"({len(tasks)} task(s) x {len(backbones)} backbone(s) x {len(ARMS)} arms x {args.runs} run(s)); "
                "lower --runs/--tasks/--backbone or raise --max-total-usd."
            )
            print(f"memory_eval: {detail}", file=sys.stderr)
            write_budget_abort_marker(
                date=date, phase="preflight", cap_usd=cap, spent_usd=0.0, sessions_run=0, detail=detail,
            )
            return 1
    set_cost_tracker(tracker)

    # What the gate reads for `date` today. A budget abort puts it back.
    results_before = results_path_for_date(date).read_bytes() if results_path_for_date(date).is_file() else None

    reset_agent_error_samples()
    sandbox_root = Path(tempfile.mkdtemp(prefix="ccgm-eval-sandbox-"))
    all_rows: list[dict[str, Any]] = []
    # st_mtime_ns of this process's last write_results(), or None if it never
    # wrote. Not a bool: the abort's unlink must remove the file THIS process
    # wrote and not one a concurrent same-date run finished in the meantime
    # (#1027 review). Concurrent same-date runs are already unsafe --
    # write_results() truncates -- but deleting another run's paid-for rows
    # is a new way to lose them, and the check costs one stat().
    wrote_results: int | None = None
    try:
        for task in tasks:
            print(f"memory_eval: running task {task['id']} (kind={task['kind']})...", file=sys.stderr)
            # Stage-2 #771 Recommend fix: isolate each task's own failure --
            # an unguarded exception anywhere in the mine/seed/apply/run
            # chain (e.g. a missing fixture, an orphan supersede, an
            # unrecognized proposal shape) used to propagate straight out
            # of this loop, discarding every already-completed (live:
            # already-paid-for) task's rows with nothing written to disk.
            try:
                if task["kind"] == "dreamed":
                    rows = run_dreamed_task(
                        task, backbones=backbones, runs=args.runs, api_key=api_key or "", claude_bin=claude_bin,
                        max_budget_usd=args.max_budget_usd, timeout_s=args.timeout_s, judge_model=judge_model,
                        judge_system_prompt=judge_system_prompt, api_url=api_url, offline=offline_dir is not None,
                        offline_dir=offline_dir, offline_all_scores=offline_all_scores, sandbox_root=sandbox_root,
                    )
                else:
                    rows = run_task(
                        task, backbones=backbones, runs=args.runs, api_key=api_key or "", claude_bin=claude_bin,
                        max_budget_usd=args.max_budget_usd, timeout_s=args.timeout_s, judge_model=judge_model,
                        judge_system_prompt=judge_system_prompt, api_url=api_url, offline_all_scores=offline_all_scores,
                        sandbox_root=sandbox_root,
                    )
            except BudgetAbortError:
                raise
            except Exception as exc:  # noqa: BLE001 -- ANY task-orchestration failure degrades to a recorded row; it must never discard earlier tasks' results
                print(f"memory_eval: task {task['id']!r} raised {exc!r}; recording an error row and continuing", file=sys.stderr)
                rows = [_synthetic_error_row(task, backbones=backbones, runs=args.runs, offline=offline_dir is not None, exc=exc)]
            all_rows.extend(rows)
            # #1027: check BEFORE writing. Once every agent run of the eval
            # so far has failed to execute, nothing measurable is left to
            # write -- and a red results file is worse than none, because
            # gate_check() reads it as "memory regressed" rather than "the
            # harness never ran". The rate can only be 1.0 while no arm has
            # ever succeeded, so a single flaky task later in the run (the
            # non-fatal per-row case) never trips this.
            error_rate = whole_run_format_error_rate(all_rows)
            if error_rate is not None and error_rate >= 1.0:
                first_failure = _AGENT_ERROR_SAMPLES[0] if _AGENT_ERROR_SAMPLES else "(no raw output captured)"
                raise HarnessBrokenError(
                    f"every agent run failed to execute ({len(all_rows)} row(s), format_error_rate 1.0). "
                    "Aborting instead of writing a results file the gate would read as a memory regression. "
                    f"First failure -- {first_failure}"
                )
            # Written after EVERY task, not only at the end -- a later
            # task's failure (or an uncaught BaseException the `except
            # Exception` above deliberately does not swallow, e.g.
            # KeyboardInterrupt) must not discard already-completed tasks'
            # results either.
            write_results(all_rows, date=date)
            wrote_results = results_path_for_date(date).stat().st_mtime_ns
    except HarnessBrokenError as exc:
        print(f"memory_eval: {exc}", file=sys.stderr)
        # An earlier task whose own orchestration raised writes a zero-run
        # `error` row before the rate can reach 1.0, so "no results file" is
        # not an invariant -- drop the partial file this process wrote. Its
        # content is already gone either way (write_results truncates). The
        # mtime check keeps this from deleting a concurrent run's results.
        if wrote_results is not None:
            partial = results_path_for_date(date)
            try:
                still_ours = partial.stat().st_mtime_ns == wrote_results
            except OSError:
                still_ours = False
            if still_ours:
                partial.unlink(missing_ok=True)
            else:
                print(
                    f"memory_eval: {partial} changed since this run wrote it; leaving it alone",
                    file=sys.stderr,
                )
        # The marker is what actually keeps the gate closed: with no results
        # file, gate_check() would otherwise read the previous run's.
        marker = write_harness_broken_marker(
            date=date,
            detail=_AGENT_ERROR_SAMPLES[0] if _AGENT_ERROR_SAMPLES else "(no raw output captured)",
        )
        print(f"memory_eval: wrote {marker}; the gate stays closed until a run produces results", file=sys.stderr)
        return 1
    except BudgetAbortError as exc:
        print(f"memory_eval: budget abort: {exc}", file=sys.stderr)
        # Put the results file back exactly as this run found it, so the gate
        # reads what it read before the run started.
        if wrote_results is not None:
            partial = results_path_for_date(date)
            try:
                still_ours = partial.stat().st_mtime_ns == wrote_results
            except OSError:
                still_ours = False
            if still_ours:
                if results_before is None:
                    partial.unlink(missing_ok=True)
                else:
                    partial.write_bytes(results_before)
        marker = write_budget_abort_marker(
            date=date, phase="run", cap_usd=tracker.cap_usd, spent_usd=tracker.spent_usd,
            sessions_run=tracker.sessions_run, detail=str(exc),
        )
        print(f"memory_eval: wrote {marker}; gate state unchanged", file=sys.stderr)
        return 1
    finally:
        set_cost_tracker(None)
        shutil.rmtree(sandbox_root, ignore_errors=True)

    results_path = write_results(all_rows, date=date)
    # A run that produced results has proved the harness works, whatever
    # date it wrote -- so it clears EVERY marker, not just its own date's
    # (#1027 review). Clearing only one leaves a marker whose mtime sorts
    # newest (an NTP correction, a restore, an `rsync -a` of ~/.claude)
    # holding the gate closed forever, with nothing to recover it: evals/ is
    # not swept by retention and no doc tells an operator the file exists.
    # It also stops markers accumulating one per aborted night.
    clear_harness_broken_markers()
    print(f"memory_eval: wrote {len(all_rows)} result row(s) to {results_path}", file=sys.stderr)
    print(render_summary_table(all_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
