#!/usr/bin/env python3
"""
apply_dream_proposal.py -- human-gated apply path for dreaming proposals (Epic 6).

Maps a proposal row's `kind` onto a `ccgm-learnings-log` store operation,
records the outcome, and keeps the proposals file + a dedicated audit trail
in sync. This is the ONE place Epic 6's apply surfaces (`/dream-apply` and
dream-daily.sh's opt-in auto-apply step) route through, so the branch of
"what actually happens to the store" stays identical regardless of who
triggered it.

Dispatch table (plan.md Section 5 Epic 6):
    learning_add        -> `ccgm-learnings-log add` (project != _global)
                            -> `learnings_store.promote_to_global()` (project == _global)
    learning_verify      -> `ccgm-learnings-log verify <target_id>` (human accept)
                            -> `... verify <target_id> --auto` (auto-apply; adrev-404:
                               bumps uses but does NOT refresh last_verified, so a
                               nightly unattended verify cannot pin decay/staleness)
    learning_contradict  -> `ccgm-learnings-log contradict <target_id>`
    learning_supersede    -> `ccgm-learnings-log supersede <target_id> --expected-sha <sha>`
    learning_deprecate    -> `ccgm-learnings-log deprecate <target_id> --expected-sha <sha>`

`_global` writes (adrev-405 net contract, arbitrating adrev-302/sec-1/adrev-009):
    Exactly ONE write path to `_global` exists: `learnings_store.promote_to_global()`,
    called here directly (an in-process Python call, not a subprocess) ONLY for
    `learning_add` proposals whose `project == "_global"`, after a recorded human
    accept. It verifies every cited evidence session resolves to a real, on-disk
    transcript and derives `writer` from that transcript's `cwd` -- never from
    CCGM_AGENT_ID. It does NOT enforce a breadth minimum: the human accept IS
    the authority; prevalence is informational only (see the `needs_manual_promotion`
    marker dream_analyze.py already writes onto under-prevalence `_global`
    proposals). This module NEVER sets CCGM_LEARNINGS_ADMIN=1 -- not inline, not
    exported -- because doing so from an automated script would reduce the sole
    `_global` guard to a one-line env-var bypass any prompt-injected agent could
    set too (exactly what adrev-302 found and adrev-405 closed). Every OTHER
    `_global`-targeting proposal kind (verify/contradict/supersede/deprecate
    against an EXISTING `_global` row) has no structural privileged path here --
    it is dispatched through the ordinary general-CLI branch like any other
    project, which will itself raise the ADMIN-gate (exit 4) since ADMIN is
    never set by this script. That failure is caught and surfaced exactly like
    a `learning_add` promotion failure (`failed_promotion`, audited, never
    silent) -- the store's own guard is the real backstop, not a kind-specific
    carve-out here.

CAS retry-once (adrev-012): `learning_supersede`/`learning_deprecate` compute
the target's CURRENT content sha immediately before each attempt (never a
value cached from proposal-generation time -- the proposal schema carries no
such field, and per adrev-010 the real trigger for a CAS mismatch here is a
genuine cross-process TOCTOU race, not staleness against an old read). On a
CAS mismatch (exit 3) the target is re-projected fresh: if it is no longer a
live head (already superseded by something else), the proposal is left
`pending` with an "already superseded to <id>; re-review" detail and NO
second attempt is made; otherwise one retry is attempted with a freshly
re-read sha. Exhausting that retry still on a mismatch marks the outcome
`failed_cas` (audited, proposal LEFT pending -- never silently dropped).

Status discipline: the proposals file's `status` field is part of Epic 3's
FROZEN proposal-schema.json enum (`pending|accepted|rejected|auto_applied`).
This module writes `accepted`/`auto_applied`/`rejected` ONLY on an outcome
that actually landed a store change (or, for reject, a deliberate no-store-
write refusal); every failure/refusal outcome (refused_not_pending,
target_no_longer_live, failed_cas, failed_promotion, validation_error,
target_not_found, unsupported_kind, internal_error) leaves `status`
untouched at `pending` -- schema-safe, and keeps the proposal visible for
retry. The FULL outcome detail for every attempt -- success or failure --
lives in ~/.claude/dreaming/state/apply-audit.jsonl, never only in a return
value that evaporates when the caller exits (adrev-012/adrev-302: "never
silent"). `internal_error` covers any handler failure NOT already modeled
by one of the named outcomes above (e.g. a malformed/schema-drifted
proposal row) -- `apply_proposal()` never lets a handler exception escape
uncaught, so a single bad row can never crash the process or (via
`run_auto_apply`'s loop) abort the rest of a batch.

adrev-013 (refuse non-pending): a proposal whose `status` is already
anything other than `pending` is refused outright -- no CLI call is even
attempted -- so a stray re-apply can never double-count a counter-op or
re-supersede an already-superseded target. This refusal is only meaningful
if it cannot itself be raced: `apply_proposal()` holds `_apply_lock()` across
the ENTIRE read -> not-pending-check -> handler-dispatch -> status-rewrite
sequence for a given proposal id (not just the final rewrite), so two
concurrent invocations of the same id -- same process or two separate OS
processes (e.g. the nightly auto-apply LaunchAgent racing a human's
`/dream-apply accept`) -- can never both observe `pending` and both mutate
the store.

Optimistic auto-integration engine (optimistic-memory plan.md Epic 3):
`run_optimistic_integrate()` supersedes `run_auto_apply()`'s narrow
verify-only predicate with a full per-op-kind posture engine
(`dream_analyze.resolve_posture()`), per-slug blast-radius caps, a batch
eviction-concentration anomaly check, a cross-night accumulation signal,
and a windowed circuit breaker (`state/optimistic.json`). `run_auto_apply()`
itself is left UNCHANGED (still reachable via the `auto-apply` CLI
subcommand) for backward compatibility with its existing callers/tests;
`dream-daily.sh`'s nightly chain now calls `optimistic-integrate` instead.
Every proposal this engine applies goes through the SAME `apply_proposal()`
this module already uses for human accepts, so the existing human-race
lock (adrev-013, above) and per-outcome audit trail cover the new path for
free -- the engine adds three NEW optional `apply_proposal()` parameters
(`dwell_hours`, `batch_id`, `posture`) that are no-ops (None) for every
existing caller.

Lock topology (adrev-opt-011): the engine NEVER holds `_apply_lock()` across
the batch -- each proposal is applied through `apply_proposal()`, which
takes/releases the lock per call exactly as it does today. The breaker
state read (before the loop) and the breaker state write + single batch
commit (after the loop) each acquire the lock in their OWN, non-nested
critical section. `fcntl.flock` is non-reentrant; nesting a batch-wide lock
around per-proposal `apply_proposal()` calls would self-deadlock on the
very first row.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import fcntl
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import dream_analyze as da  # noqa: E402  (sibling module, same lib/ dir)

# Reuse dream_analyze.py's already-resolved cross-module learnings_store
# import and its path helpers, rather than re-deriving either (one source
# of truth for "where does dreaming's state live" and "how do we reach the
# self-improving module's store library").
learnings_store = da.learnings_store
GLOBAL_SLUG = learnings_store.GLOBAL_SLUG

dreaming_dir = da.dreaming_dir
proposals_dir = da.proposals_dir
state_dir = da.state_dir
today_iso = da.today_iso
_utc_now_iso = da._utc_now_iso

# Mined proposals are model-inferred from transcript evidence, never a
# direct human statement or an agent's own first-hand observation this
# session -- "inferred" is the LOWEST rank in learnings_store.SOURCE_TIER_RANK,
# which is the epistemically honest default and, being the floor, can never
# weaken origin-binding's tier-raise protection for anything created here.
DEFAULT_MINED_SOURCE = "inferred"


def apply_audit_path() -> Path:
    return state_dir() / "apply-audit.jsonl"


# ---------------------------------------------------------------------------
# Sibling CLI resolution (ccgm-learnings-log, ccgm-learnings-sync)
# ---------------------------------------------------------------------------


def _resolve_sibling_bin(name: str) -> str:
    """Resolve a sibling module's bin/ script.

    Prefers the installed ~/.claude/bin/<name> symlink (real runtime after
    `start.sh --add self-improving`; mirrors learnings_store._maybe_autocommit's
    own resolution of ccgm-learnings-sync), falling back to the repo-relative
    modules/self-improving/bin/<name> path so this module's own tests run
    cleanly on a fresh checkout that was never installed (mirrors
    transcript_miner._import_sibling_module's two-path convention).
    """
    installed = os.path.expanduser(f"~/.claude/bin/{name}")
    if os.path.isfile(installed):
        return installed
    repo_modules_dir = Path(__file__).resolve().parents[2]  # .../modules
    sibling = str(repo_modules_dir / "self-improving" / "bin" / name)
    if os.path.isfile(sibling):
        return sibling
    raise FileNotFoundError(
        f"apply_dream_proposal: cannot find sibling CLI '{name}' at {installed} or "
        f"{sibling}. Is the 'self-improving' module installed? "
        f"(bash start.sh --add self-improving)"
    )


def _run_learnings_log(args: list[str]) -> subprocess.CompletedProcess:
    binpath = _resolve_sibling_bin("ccgm-learnings-log")
    return subprocess.run(
        [sys.executable, binpath, *args],
        capture_output=True, text=True, check=False,
    )


_AUTOCOMMIT_ENV_KEY = "CCGM_LEARNINGS_AUTOCOMMIT"


@contextlib.contextmanager
def _suppressed_autocommit():
    """Force `CCGM_LEARNINGS_AUTOCOMMIT=false` for every `ccgm-learnings-log`
    subprocess spawned while this context is active (adrev-opt-013).

    `subprocess.run(..., env=None)` inherits the CURRENT `os.environ` at
    call time, so mutating `os.environ` itself for the duration of a batch
    is sufficient -- no need to thread an `env=` override through
    `_run_learnings_log()`. The optimistic engine commits the WHOLE batch
    exactly once at the end (`_run_sync_commit()`); if the operator's
    ambient environment has per-write autocommit enabled, it must not fire
    mid-batch and turn an N-write batch into up to N separate commits
    (which would make Epic 5's single-SHA "revert this batch" UX revert
    only one of the N writes). Restores whatever value (or absence) the key
    had on entry, even if the body raises.
    """
    previous = os.environ.get(_AUTOCOMMIT_ENV_KEY)
    os.environ[_AUTOCOMMIT_ENV_KEY] = "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(_AUTOCOMMIT_ENV_KEY, None)
        else:
            os.environ[_AUTOCOMMIT_ENV_KEY] = previous


def _run_sync_commit(message: str | None = None) -> dict[str, Any]:
    """Blocking `ccgm-learnings-sync commit` -- the spec's "runs
    ccgm-learnings-sync commit after a batch" requirement. Called once per
    CLI invocation (a single accept/reject IS a batch of one; auto-apply
    calls it once after its whole loop), not once per proposal, so N
    auto-applied counters land as one commit, not N.

    Parses the CLI's own documented contract ("every subcommand's LAST
    stdout line is a single machine-parseable JSON object with an 'ok'
    boolean"). Never raises: a sync failure (no git repo yet, no remote,
    binary missing) must not crash the apply CLI -- the store write itself
    already landed regardless of whether this commit succeeds.

    `message`, if given, is passed as `-m <message>` (adrev-opt-013): the
    optimistic engine tags its one-commit-per-batch with the `batch_id` so
    a human reading `git log` in the learnings store can identify -- and
    revert -- one night's whole batch by its commit message. `None` (every
    existing caller) preserves the CLI's own default message.
    """
    try:
        binpath = _resolve_sibling_bin("ccgm-learnings-sync")
    except FileNotFoundError as exc:
        return {"ok": False, "reason": str(exc)}
    argv = [sys.executable, binpath, "commit"]
    if message:
        argv += ["-m", message]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            break
    return {"ok": proc.returncode == 0, "reason": (proc.stderr or proc.stdout).strip()}


# ---------------------------------------------------------------------------
# Proposal file scan (bounded linear scan -- mirrors autoheal's
# lib/apply-proposal.py._find_proposal rationale: proposal volume is tens
# per day, an index file is not worth the complexity)
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def find_proposal(proposal_id: str) -> tuple[Path, dict[str, Any]] | tuple[None, None]:
    """Scan every proposals/*.jsonl file (most recent day first) for
    `proposal_id`. Unlike autoheal (today-only scan), proposals stay
    `pending` and reviewable across days until a human acts on them or
    dream-daily.sh's retention sweep ages the file out -- so the search
    window is "everything retained", not just today.
    """
    pdir = proposals_dir()
    if not pdir.is_dir():
        return None, None
    for path in sorted(pdir.glob("*.jsonl"), reverse=True):
        for row in _read_jsonl(path):
            if row.get("id") == proposal_id:
                return path, row
    return None, None


def _confidence_of(row: dict[str, Any]) -> int:
    c = row.get("confidence")
    return c if isinstance(c, int) and not isinstance(c, bool) else 0


def list_pending(days_back: int = 8) -> list[dict[str, Any]]:
    """Pending proposals across the last `days_back` daily files (today +
    days_back-1 prior), sorted (confidence desc, generated_at desc) --
    mirrors autoheal-apply.md's "walk back over the last 8 days" review
    window and its confidence-first ordering.
    """
    pdir = proposals_dir()
    if not pdir.is_dir():
        return []

    today_override = os.environ.get("CCGM_DREAMING_TODAY")
    try:
        today = _dt.date.fromisoformat(today_override) if today_override else _dt.datetime.now(_dt.timezone.utc).date()
    except ValueError:
        today = _dt.datetime.now(_dt.timezone.utc).date()
    cutoff = today - _dt.timedelta(days=days_back - 1)

    rows: list[dict[str, Any]] = []
    for path in sorted(pdir.glob("*.jsonl")):
        try:
            file_date = _dt.date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        for row in _read_jsonl(path):
            if row.get("status") == "pending":
                rows.append(row)

    rows.sort(key=lambda r: (_confidence_of(r), str(r.get("generated_at") or "")), reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Locked status rewrite (adrev-013's "status != pending" refusal depends on
# every writer serializing through this so two near-simultaneous applies of
# the same id cannot both observe "pending" and both act)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _apply_lock():
    lock_path = state_dir() / ".apply.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _rewrite_status_locked(
    path: Path, proposal_id: str, new_status: str, *, extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Read-modify-write of exactly the `status` field (plus, optionally,
    `extra_fields`) on one row.

    Callers MUST already hold `_apply_lock()` -- this function never
    acquires it itself (acquiring the same fcntl.flock a second time via a
    fresh `os.open()` would block forever, since flock's lock domain is the
    open file description, not the process: see `apply_proposal()`, which
    now holds the lock across its whole critical section and calls this
    directly instead of the locking `_rewrite_status()` wrapper below).

    `extra_fields` (optimistic-memory plan.md §3.4): the optimistic engine
    additionally records `batch_id`, `posture`, and (for dwell postures)
    `dwell_until` onto a proposal it auto-applies, so Epic 5's report can
    group tonight's batch and Epic 6's rollback can filter by `batch_id`.
    `None` (every pre-Epic-3 caller) writes only `status`, unchanged from
    before this parameter existed.

    Every parseable row is re-serialized (not hand-patched as a text diff),
    so the frozen proposal-schema.json shape Epic 3 owns is round-tripped
    exactly as dream_analyze.py wrote it, plus the field(s) this module is
    licensed to touch. A line that fails to parse as a JSON object (a
    corrupt or torn write from an unrelated, sibling proposal) is preserved
    VERBATIM rather than crashing the rewrite -- mirrors `_read_jsonl()`'s
    own defensive skip-on-read, applied here to skip-on-rewrite instead, so
    one bad sibling line can never prevent this proposal's own status from
    being recorded (a crash here previously left the store mutation already
    landed but the status stuck at `pending`, indistinguishable from "never
    attempted" and liable to be double-applied on retry). Returns the
    updated row, or None if `proposal_id` is not present in `path`
    (caller's problem to report -- this function never raises on a
    not-found).
    """
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    updated: dict[str, Any] | None = None
    out_lines: list[str] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            out_lines.append(line)  # corrupt sibling line -- preserve verbatim, do not crash
            continue
        if not isinstance(row, dict):
            out_lines.append(line)  # valid JSON but not an object -- preserve verbatim (mirrors _read_jsonl)
            continue
        if row.get("id") == proposal_id:
            row["status"] = new_status
            if extra_fields:
                row.update(extra_fields)
            updated = row
        out_lines.append(json.dumps(row, sort_keys=True))
    if updated is None:
        return None
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return updated


def _rewrite_status(path: Path, proposal_id: str, new_status: str) -> dict[str, Any] | None:
    """Locked entry point for `_rewrite_status_locked()` -- acquires
    `_apply_lock()` itself. Used by callers (`reject_proposal()`) that are
    NOT already holding the lock; `apply_proposal()` holds the lock across
    its whole critical section and calls `_rewrite_status_locked()`
    directly to avoid a re-entrant flock deadlock (see that function's
    docstring)."""
    with _apply_lock():
        return _rewrite_status_locked(path, proposal_id, new_status)


# ---------------------------------------------------------------------------
# Audit trail (never schema-constrained by proposal-schema.json -- this is
# Epic 6's own file, free to carry every outcome/detail/cas_retries field)
# ---------------------------------------------------------------------------


def _write_audit(record: dict[str, Any]) -> None:
    record.setdefault("id", f"audit_{uuid.uuid4().hex[:12]}")
    record.setdefault("ts", _utc_now_iso())
    learnings_store.file_locked_append(str(apply_audit_path()), json.dumps(record, sort_keys=True))


# ---------------------------------------------------------------------------
# Per-kind appliers
# ---------------------------------------------------------------------------


def _first_evidence_session(row: dict[str, Any]) -> str | None:
    for e in row.get("evidence") or []:
        sid = e.get("session_id") if isinstance(e, dict) else None
        if sid:
            return sid
    return None


def _apply_learning_add(
    row: dict[str, Any], *, reviewed_by: str, method: str = "human_accept",
    dwell_hours: float | None = None,
) -> dict[str, Any]:
    if row.get("project") == GLOBAL_SLUG:
        return _apply_global_add(row, reviewed_by=reviewed_by)

    args = [
        "--type", row["type"],
        "--content", row["content"],
        "--confidence", str(row["confidence"]),
        "--source", DEFAULT_MINED_SOURCE,
        "--project", row["project"],
    ]
    if method == "auto_apply":
        # adrev-opt-008: tag the engine's own optimistic writes `auto: true`
        # so memory_eval.py's freshness clock (Epic 4) can skip them --
        # only reachable because Epic 1 extended `--auto` to every
        # ccgm-learnings-log subcommand, not just verify.
        args.append("--auto")
    if dwell_hours is not None:
        # optimistic-memory §3.2: needs_dwell postures (add/supersede/
        # contradict/deprecate) thread the engine's configured dwell_hours
        # as a FLOOR -- the store applies max(existing, new) at the fold
        # layer, so this can only extend, never shorten, a target's dwell.
        args += ["--dwell-hours", str(int(dwell_hours))]
    session = _first_evidence_session(row)
    if session:
        args += ["--session", session]

    proc = _run_learnings_log(args)
    if proc.returncode == 0:
        new_id = None
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        if lines:
            try:
                new_id = json.loads(lines[-1]).get("id")
            except json.JSONDecodeError:
                pass
        return {"outcome": "applied", "new_entry_id": new_id}
    if proc.returncode == 4:
        return {"outcome": "failed_promotion", "detail": proc.stderr.strip()}
    if proc.returncode == 2:
        return {"outcome": "validation_error", "detail": proc.stderr.strip()}
    return {"outcome": "unexpected_exit_code", "detail": f"exit={proc.returncode}: {proc.stderr.strip()}"}


def _apply_global_add(row: dict[str, Any], *, reviewed_by: str) -> dict[str, Any]:
    """adrev-405 net contract: the ONE write path to `_global` is
    `learnings_store.promote_to_global()`, called in-process here -- NEVER
    via the general CLI, which is ADMIN-gated and must never see
    CCGM_LEARNINGS_ADMIN exported by an automated script (sec-8)."""
    evidence_sessions = [
        e.get("session_id") for e in (row.get("evidence") or [])
        if isinstance(e, dict) and e.get("session_id")
    ]
    entry = {
        "type": row["type"],
        "content": row["content"],
        "source": DEFAULT_MINED_SOURCE,
        "confidence": row["confidence"],
        "tags": [],
        "files": [],
    }
    try:
        new_entry = learnings_store.promote_to_global(
            entry, evidence_sessions=evidence_sessions, reviewed_by=reviewed_by,
        )
    except learnings_store.GlobalPromotionError as exc:
        return {"outcome": "failed_promotion", "detail": str(exc)}
    return {"outcome": "applied", "new_entry_id": new_entry["id"]}


def _looks_like_uncaught_exception(stderr: str) -> bool:
    """True if `stderr` is a Python traceback dump rather than a clean,
    intentional error message.

    Exit code 1 is heavily overloaded in `ccgm-learnings-log`'s CLI: it is
    BOTH the deliberate "target not found" signal (`return 0 if ok else 1`
    in `_cmd_verify`/`_cmd_contradict`, which prints nothing to stderr) AND
    Python's own default exit code for any uncaught exception in that
    subprocess (which DOES dump a traceback to stderr). Blindly trusting
    exit 1 as "target not found" mislabels a genuine internal crash as a
    permanent, don't-retry condition -- exactly the wrong guidance (see
    commands/dream-apply.md's instruction to report `target_not_found`
    verbatim and suggest re-review rather than retrying). This is a cheap,
    conservative text check, not a fix for whatever caused the crash.
    """
    return "Traceback (most recent call last):" in stderr


def _apply_counter_op(
    row: dict[str, Any], op: str, *, auto: bool = False, dwell_hours: float | None = None,
) -> dict[str, Any]:
    args = [op, row["target_id"], "--project", row["project"]]
    if auto:
        # adrev-404: an unattended auto-apply verify must NOT refresh
        # last_verified. For verify specifically, `--auto` means "bump uses
        # only" (VF6). For contradict (the other _apply_counter_op caller,
        # optimistic-memory Epic 3), `--auto` just tags the write as
        # unattended for audit/reporting -- adrev-opt-008 extended `--auto`
        # to every subcommand in Epic 1, it is no longer verify-only.
        args.append("--auto")
    if dwell_hours is not None:
        # optimistic-memory §3.2: contradict is `dwell-quarantine` --
        # dwell is MANDATORY for this kind. Floor semantics (max-with-
        # existing) are enforced at the store's fold layer, not here.
        args += ["--dwell-hours", str(int(dwell_hours))]
    session = _first_evidence_session(row)
    if session:
        args += ["--session", session]
    proc = _run_learnings_log(args)
    if proc.returncode == 0:
        return {"outcome": "applied"}
    if proc.returncode == 1 and not _looks_like_uncaught_exception(proc.stderr):
        return {"outcome": "target_not_found", "detail": proc.stderr.strip()}
    if proc.returncode == 4:
        return {"outcome": "failed_promotion", "detail": proc.stderr.strip()}
    return {"outcome": "unexpected_exit_code", "detail": f"exit={proc.returncode}: {proc.stderr.strip()}"}


def _apply_learning_verify(
    row: dict[str, Any], *, reviewed_by: str, method: str = "human_accept",
    dwell_hours: float | None = None,
) -> dict[str, Any]:
    # adrev-404: an unattended auto-apply (method == "auto_apply") issues an
    # AUTO verify (bump uses, do NOT refresh last_verified). A human accept
    # (method == "human_accept", the /dream-apply accept path) issues a normal
    # verify that refreshes last_verified exactly as before. `verify`'s
    # posture is `optimistic-immediate` (needs_dwell=False, plan.md §3.3),
    # so the optimistic engine never passes a real dwell_hours here -- this
    # parameter exists only for signature parity with the other handlers in
    # `_HANDLERS` (apply_proposal() calls every handler uniformly) and so a
    # human accept could, in principle, extend a target's existing dwell
    # floor via the same `--dwell-hours` flag ccgm-learnings-log already
    # exposes on `verify`.
    return _apply_counter_op(row, "verify", auto=(method == "auto_apply"), dwell_hours=dwell_hours)


def _apply_learning_contradict(
    row: dict[str, Any], *, reviewed_by: str, method: str = "human_accept",
    dwell_hours: float | None = None,
) -> dict[str, Any]:
    # optimistic-memory §3.3: contradict is `dwell-quarantine` -- the
    # optimistic engine (method == "auto_apply") tags the write `auto` and
    # supplies a mandatory dwell_hours; a human accept (the existing
    # /dream-apply path) passes neither, identical to pre-Epic-3 behavior.
    return _apply_counter_op(row, "contradict", auto=(method == "auto_apply"), dwell_hours=dwell_hours)


def _current_content_sha_if_live(project: str, target_id: str) -> tuple[str, None] | tuple[None, str]:
    """Fresh re-projection of `project`; returns (sha, None) if `target_id`
    is still a live (non-superseded) head, or (None, detail) naming why it
    is not -- either gone entirely, or already superseded to a new id
    (adrev-012: never CAS-retry against a target that moved out from under
    it; surface the new id and leave the proposal pending instead).
    """
    heads = {h["id"]: h for h in learnings_store.load_all(project)}
    target = heads.get(target_id)
    if target is None:
        return None, f"target_id {target_id!r} no longer resolves in project {project!r}"
    superseded_by = target.get("superseded_by")
    if superseded_by:
        return None, f"already superseded to {superseded_by!r}; re-review"
    return learnings_store.content_sha256(target.get("content")), None


def _apply_cas_op(row: dict[str, Any], *, build_argv: Callable[[str], list[str]]) -> dict[str, Any]:
    """Shared CAS-retry-once mechanics for deprecate/supersede (adrev-012).

    `build_argv(sha)` returns the full ccgm-learnings-log argv for one
    attempt, given the freshly-computed expected sha. The sha is
    recomputed via `_current_content_sha_if_live` immediately before EVERY
    attempt (never cached across the retry), which is what makes the retry
    self-healing against the real trigger for a mismatch here: a genuine
    cross-process TOCTOU race (adrev-010), not staleness against an old
    in-memory value.
    """
    project = row["project"]
    target_id = row["target_id"]

    for attempt in range(2):  # first attempt + one retry
        sha, not_live_detail = _current_content_sha_if_live(project, target_id)
        if sha is None:
            return {"outcome": "target_no_longer_live", "detail": not_live_detail, "cas_retries": attempt}

        proc = _run_learnings_log(build_argv(sha))
        if proc.returncode == 0:
            result: dict[str, Any] = {"outcome": "applied", "cas_retries": attempt}
            if row.get("kind") == "learning_supersede":
                lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
                if lines:
                    try:
                        result["new_entry_id"] = json.loads(lines[-1]).get("id")
                    except json.JSONDecodeError:
                        pass
            return result
        if proc.returncode == 3:
            continue  # CAS mismatch -- loop re-checks liveness + fresh sha
        if proc.returncode == 1 and not _looks_like_uncaught_exception(proc.stderr):
            return {"outcome": "target_not_found", "detail": proc.stderr.strip(), "cas_retries": attempt}
        if proc.returncode == 2:
            return {"outcome": "validation_error", "detail": proc.stderr.strip(), "cas_retries": attempt}
        if proc.returncode == 4:
            return {"outcome": "failed_promotion", "detail": proc.stderr.strip(), "cas_retries": attempt}
        return {
            "outcome": "unexpected_exit_code",
            "detail": f"exit={proc.returncode}: {proc.stderr.strip()}",
            "cas_retries": attempt,
        }

    # adrev-012: "on retry-2 exit-3: mark failed_cas ... continue the batch."
    return {"outcome": "failed_cas", "detail": "CAS mismatch persisted after one retry", "cas_retries": 1}


def _apply_learning_deprecate(
    row: dict[str, Any], *, reviewed_by: str, method: str = "human_accept",
    dwell_hours: float | None = None,
) -> dict[str, Any]:
    # optimistic-memory §3.3: deprecate is `dwell-quarantine`, same shape as
    # contradict but blunter (hard-excludes vs. soft confidence cut).
    auto = method == "auto_apply"

    def build_argv(sha: str) -> list[str]:
        args = ["deprecate", row["target_id"], "--project", row["project"], "--expected-sha", sha]
        if auto:
            args.append("--auto")
        if dwell_hours is not None:
            args += ["--dwell-hours", str(int(dwell_hours))]
        session = _first_evidence_session(row)
        if session:
            args += ["--session", session]
        return args

    return _apply_cas_op(row, build_argv=build_argv)


def _apply_learning_supersede(
    row: dict[str, Any], *, reviewed_by: str, method: str = "human_accept",
    dwell_hours: float | None = None,
) -> dict[str, Any]:
    # optimistic-memory §3.3: supersede is `optimistic-dwell`, the same
    # posture as add -- the surgical-rewrite-of-a-trusted-row attack the
    # compaction guard (compact_preserves_facts, checked upstream in
    # dream_analyze.py before this proposal was even written) already
    # defends against.
    auto = method == "auto_apply"

    def build_argv(sha: str) -> list[str]:
        args = [
            "supersede", row["target_id"],
            "--content", row["content"],
            "--type", row["type"],
            "--source", DEFAULT_MINED_SOURCE,
            "--project", row["project"],
            "--expected-sha", sha,
        ]
        if row.get("justification"):
            args += ["--reason", row["justification"]]
        if auto:
            args.append("--auto")
        if dwell_hours is not None:
            args += ["--dwell-hours", str(int(dwell_hours))]
        session = _first_evidence_session(row)
        if session:
            args += ["--session", session]
        return args

    return _apply_cas_op(row, build_argv=build_argv)


_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "learning_add": _apply_learning_add,
    "learning_verify": _apply_learning_verify,
    "learning_contradict": _apply_learning_contradict,
    "learning_deprecate": _apply_learning_deprecate,
    "learning_supersede": _apply_learning_supersede,
}


# ---------------------------------------------------------------------------
# Top-level accept / reject
# ---------------------------------------------------------------------------


def apply_proposal(
    proposal_id: str, *, method: str = "human_accept", reviewed_by: str | None = None,
    dwell_hours: float | None = None, batch_id: str | None = None, posture: str | None = None,
) -> dict[str, Any]:
    """The single write entry point for accepting a pending proposal.

    Refuses (adrev-013) any proposal whose status is not 'pending' rather
    than re-applying it -- no CLI call is even attempted. On success the
    row's `status` becomes 'accepted' (method=human_accept) or
    'auto_applied' (method=auto_apply), the only two positive terminal
    states this path is licensed to write. Every OTHER outcome leaves the
    row 'pending' (schema-safe, retry-visible). Always writes exactly one
    audit record, whatever the outcome (adrev-012/adrev-302: never silent).

    `dwell_hours`/`batch_id`/`posture` (optimistic-memory plan.md §3.2/§3.4,
    Epic 3): optional, `None` for every pre-Epic-3 caller (human accept via
    `/dream-apply`, `run_auto_apply()`'s verify-only path). `dwell_hours` is
    threaded into the handler so a `needs_dwell` posture's
    `ccgm-learnings-log` invocation carries `--dwell-hours` (the store
    applies it as a FLOOR, never a shortening, at the fold layer --
    learnings_store.py's `_max_dwell`). `batch_id`/`posture` are recorded
    onto the proposal row itself (not threaded into the handler -- they do
    not affect the store write) so Epic 5's report can group tonight's
    batch and Epic 6's rollback can filter by `batch_id`.

    The ENTIRE read -> not-pending-check -> handler-dispatch -> status-
    rewrite sequence runs under a single `_apply_lock()` acquisition, so two
    concurrent invocations of the same `proposal_id` (same process or two
    separate OS processes) cannot both observe `pending` and both mutate the
    store -- see `_rewrite_status_locked()`'s docstring for why this calls
    that function directly instead of the locking `_rewrite_status()`
    wrapper (re-entrant flock acquisition would deadlock). The handler call
    itself is never allowed to raise past this function: an unexpected
    exception (a malformed/schema-drifted proposal row, for example) is
    caught and turned into an audited `internal_error` outcome rather than
    crashing the process -- which matters doubly for `run_auto_apply()` and
    `run_optimistic_integrate()`, whose per-row loops call this function and
    depend on one bad row never aborting evaluation of the rest of the batch.

    Lock topology note (adrev-opt-011): this function's own `_apply_lock()`
    acquisition is per-proposal, exactly as before Epic 3. The optimistic
    engine calls this function once per proposal inside its loop -- it never
    wraps a whole batch of these calls in an OUTER `_apply_lock()`, which
    would self-deadlock (flock is non-reentrant).
    """
    reviewed_by = reviewed_by or os.environ.get("USER") or os.environ.get("LOGNAME") or "human"

    with _apply_lock():
        path, row = find_proposal(proposal_id)
        if row is None or path is None:
            record = {"proposal_id": proposal_id, "method": method, "outcome": "not_found", "ok": False}
            _write_audit(record)
            return record

        if row.get("status") != "pending":
            record = {
                "proposal_id": proposal_id, "kind": row.get("kind"), "project": row.get("project"),
                "target_id": row.get("target_id"), "method": method, "outcome": "refused_not_pending",
                "detail": f"status is {row.get('status')!r}, not pending", "ok": False,
            }
            _write_audit(record)
            return record

        kind = row.get("kind")
        handler = _HANDLERS.get(kind)
        if handler is None:
            record = {
                "proposal_id": proposal_id, "kind": kind, "project": row.get("project"),
                "target_id": row.get("target_id"), "method": method, "outcome": "unsupported_kind",
                "detail": f"no apply handler for kind {kind!r}", "ok": False,
            }
            _write_audit(record)
            return record

        try:
            result = handler(row, reviewed_by=reviewed_by, method=method, dwell_hours=dwell_hours)
        except Exception:  # noqa: BLE001 -- deliberate: a handler crash must become
            # an audited outcome, never an uncaught exception (adrev-012/adrev-302
            # "never silent"; also what keeps run_auto_apply's batch loop alive).
            result = {"outcome": "internal_error", "detail": traceback.format_exc()}
        outcome = result.get("outcome")
        ok = outcome == "applied"

        if ok:
            new_status = "auto_applied" if method == "auto_apply" else "accepted"
            extra_fields: dict[str, Any] = {}
            if batch_id is not None:
                extra_fields["batch_id"] = batch_id
            if posture is not None:
                extra_fields["posture"] = posture
            if dwell_hours is not None:
                extra_fields["dwell_until"] = learnings_store.dwell_until_from_hours(dwell_hours)
            _rewrite_status_locked(path, proposal_id, new_status, extra_fields=extra_fields or None)

        record = {
            "proposal_id": proposal_id, "kind": kind, "project": row.get("project"),
            "target_id": row.get("target_id"), "method": method, "reviewed_by": reviewed_by,
            "ok": ok, **result,
        }
        if batch_id is not None:
            record["batch_id"] = batch_id
        if posture is not None:
            record["posture"] = posture
        _write_audit(record)
        return record


def reject_proposal(proposal_id: str, *, method: str = "human_reject") -> dict[str, Any]:
    """Mark a pending proposal 'rejected'. No store write of any kind --
    a rejection is purely a bookkeeping decision."""
    path, row = find_proposal(proposal_id)
    if row is None or path is None:
        record = {"proposal_id": proposal_id, "method": method, "outcome": "not_found", "ok": False}
        _write_audit(record)
        return record
    if row.get("status") != "pending":
        record = {
            "proposal_id": proposal_id, "kind": row.get("kind"), "method": method,
            "outcome": "refused_not_pending", "detail": f"status is {row.get('status')!r}, not pending",
            "ok": False,
        }
        _write_audit(record)
        return record
    _rewrite_status(path, proposal_id, "rejected")
    record = {
        "proposal_id": proposal_id, "kind": row.get("kind"), "project": row.get("project"),
        "target_id": row.get("target_id"), "method": method, "outcome": "rejected", "ok": True,
    }
    _write_audit(record)
    return record


# ---------------------------------------------------------------------------
# Auto-apply batch (plan.md Epic 6, sec-5) -- config/eval-gate checking
# lives in dream-daily.sh (bash); this function IS the structural per-
# proposal predicate plus the actual apply loop.
# ---------------------------------------------------------------------------


def run_auto_apply(day: str) -> dict[str, Any]:
    """Batch predicate: kind == 'learning_verify' AND confidence >= 9 AND
    status == 'pending', scoped to exactly one day's proposals file (the
    day dream-daily.sh just generated). NEVER learning_add/supersede/
    deprecate/contradict, at ANY confidence -- verify is the only op whose
    confidence-raise is bounded (+0.25/use, capped at +2.0, per
    self-improving/rules/learnings-store.md) and reversible by a human
    contradict; every other op either writes/destroys content
    irreversibly, or (contradict) is a silent-suppression vector sec-5
    excludes from auto-apply entirely. A `_global`-targeting
    learning_verify still cannot succeed here -- the CLI raises exit 4
    without CCGM_LEARNINGS_ADMIN, which this path never sets -- and is
    handled the same as any other failed_promotion, not special-cased,
    since the store's own guard is the real backstop, not this predicate.
    Never raises; a single proposal's failure does not abort the batch.

    RETAINED for backward compatibility (its own CLI subcommand and test
    coverage predate Epic 3) but no longer called by dream-daily.sh's
    nightly chain -- `run_optimistic_integrate()` below supersedes it
    there, applying `learning_verify` through the SAME posture engine
    (`optimistic-immediate`, no dwell) as every other op-kind.
    """
    path = proposals_dir() / f"{day}.jsonl"
    summary: dict[str, Any] = {
        "day": day, "evaluated": 0, "qualified": 0, "applied": 0, "failed": 0, "results": [],
    }
    if not path.is_file():
        return summary
    for row in _read_jsonl(path):
        summary["evaluated"] += 1
        if row.get("status") != "pending":
            continue
        if row.get("kind") != "learning_verify":
            continue
        conf = row.get("confidence")
        if not isinstance(conf, int) or isinstance(conf, bool) or conf < 9:
            continue
        summary["qualified"] += 1
        result = apply_proposal(row["id"], method="auto_apply", reviewed_by="auto-apply")
        summary["results"].append(result)
        if result.get("ok"):
            summary["applied"] += 1
        else:
            summary["failed"] += 1
    return summary


# ---------------------------------------------------------------------------
# Optimistic auto-integration engine (optimistic-memory plan.md Epic 3).
#
# run_optimistic_integrate() supersedes run_auto_apply()'s narrow verify-
# only predicate with the full per-op-kind posture engine
# (dream_analyze.resolve_posture()), per-slug blast-radius caps, a batch
# eviction-concentration anomaly check, a cross-night accumulation signal,
# and a windowed circuit breaker. Config/eval-gate checking lives in
# dream-daily.sh (bash), exactly as it did for the retired
# run_auto_apply_step -- this module's job is the structural per-proposal
# predicate plus the actual apply loop.
# ---------------------------------------------------------------------------

OPTIMISTIC_STATE_FILENAME = "optimistic.json"

# An eviction batch of size 1 cannot be "concentrated" -- every possible
# grouping of a single item is trivially 100% of that item, which would
# make every lone quarantine proposal a false anomaly. The batch-anomaly
# check (plan.md §3.3) requires at least this many contradict/deprecate
# candidates in a slug's pending batch before the configured fraction
# threshold is even meaningful.
MIN_EVICTION_BATCH_FOR_ANOMALY_CHECK = 2

# Ledger `model` field value the eval-refresh step tags its own cost.log
# rows with (see run_eval_refresh below) -- distinguishes its spend from
# the nightly analyzer's map_model/reduce_model rows in the SAME shared
# ledger file (adrev-opt-010).
EVAL_REFRESH_COST_LABEL = "eval-refresh"


def optimistic_state_path() -> Path:
    return state_dir() / OPTIMISTIC_STATE_FILENAME


def _default_optimistic_state() -> dict[str, Any]:
    return {"suspended": False, "suspended_at": None, "anomaly_log": [], "last_run": None}


def _read_optimistic_state() -> dict[str, Any]:
    """Fail-CLOSED on any parse problem (adrev-opt-014): a corrupt or
    unreadable state file must never silently un-suspend the breaker -- it
    is treated as an immediate, freshly-timestamped suspension instead. A
    missing file (never tripped, or first run ever) is the one case that
    legitimately means "not suspended"; that is `_default_optimistic_state()`
    verbatim, not a parse failure.
    """
    path = optimistic_state_path()
    if not path.is_file():
        return _default_optimistic_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {**_default_optimistic_state(), "suspended": True, "suspended_at": _utc_now_iso()}
    if not isinstance(data, dict):
        return {**_default_optimistic_state(), "suspended": True, "suspended_at": _utc_now_iso()}
    merged = _default_optimistic_state()
    merged.update(data)
    if not isinstance(merged.get("anomaly_log"), list):
        # A valid-JSON-but-wrong-shape anomaly_log (e.g. hand-edited) must
        # not crash the rolling-window computation below -- coerce to an
        # empty list rather than fail the whole read (the top-level parse
        # guard above already covers the "file is garbage" case).
        merged["anomaly_log"] = []
    return merged


def _write_optimistic_state_atomic(state: dict[str, Any]) -> None:
    """Temp-file + `Path.replace()` (an atomic rename on POSIX) -- adrev-
    opt-014: never an in-place partial write. Mirrors dream_analyze.py's
    `_write_json_atomic()` (same three-line pattern, reimplemented here
    rather than imported since this module does not otherwise depend on
    that helper)."""
    path = optimistic_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def _live_head_count(slug: str) -> int:
    """Count of `slug`'s currently-live heads: not deprecated, not already
    superseded (mirrors search()'s own superseded-exclusion and
    effective_confidence()'s deprecated -> 0.0 treatment -- "real,
    currently relevant store content"). A still-dwelling row counts as live
    (it IS real store content, just not yet read-eligible) -- only
    deprecated/superseded rows are excluded.

    This is the eviction cap's denominator (plan.md §3.3:
    min(max_eviction_absolute, max_eviction_fraction_per_run x
    live_head_count(slug))) and MUST be computed once per slug, before ANY
    write in the whole batch (P2, security review) -- see
    run_optimistic_integrate(), which computes this for every slug up
    front, before the apply loop begins.
    """
    heads = learnings_store.load_all(slug)
    return sum(1 for h in heads if not h.get("deprecated") and not h.get("superseded_by"))


def _raw_op_events(slug: str) -> list[dict[str, Any]]:
    """Union of every raw JSONL row for `slug`: the legacy file + every
    agent shard, UNFOLDED (not projected through the fold/quarantine
    layer). Used only for read-only signals that must be derived from
    committed op-events on disk rather than a mutable in-memory/JSON
    counter (adrev-opt-014's crash-consistency requirement for the
    cross-night accumulation signal, §3.8) -- never for anything that needs
    the deduped/folded head view (use learnings_store.load_all() for that).
    Mirrors memory_eval.py's own `latest_content_shaping_mutation_epoch()`,
    which walks the same two file classes directly for the same reason.
    """
    rows = _read_jsonl(learnings_store.project_jsonl(slug))
    for shard in learnings_store.list_agent_shards(slug):
        rows.extend(_read_jsonl(shard))
    return rows


def _batch_anomaly_fires(
    eviction_rows: list[dict[str, Any]], heads_by_id: dict[str, dict[str, Any]], cfg: dict[str, Any],
) -> bool:
    """Batch-anomaly check (plan.md §3.3), scoped to EVICTION CONCENTRATION
    only -- never add-tag overlap (adrev-opt-006/007: a same-tag `add`
    fraction check false-positives on a solo dev's legitimate focused
    single-project night and, per SMSR, is trivially bypassed by fluent
    poisoning; dropped from v1 entirely, not merely de-scoped here).

    Fires when `eviction_rows` (a slug's pending learning_contradict +
    learning_deprecate proposals) concentrate on ONE target row, or on rows
    sharing ONE tag -- tags are resolved from the TARGET's current head via
    `heads_by_id`, since contradict/deprecate proposals carry no tags of
    their own (proposal-schema.json) -- above
    `batch_anomaly_max_same_tag_fraction`.

    Requires at least `MIN_EVICTION_BATCH_FOR_ANOMALY_CHECK` candidates.
    """
    total = len(eviction_rows)
    if total < MIN_EVICTION_BATCH_FOR_ANOMALY_CHECK:
        return False
    threshold = float(cfg.get("batch_anomaly_max_same_tag_fraction", 0.6))

    target_counts: dict[Any, int] = {}
    for row in eviction_rows:
        tid = row.get("target_id")
        target_counts[tid] = target_counts.get(tid, 0) + 1
    if target_counts and (max(target_counts.values()) / total) >= threshold:
        return True

    tag_counts: dict[str, int] = {}
    for row in eviction_rows:
        head = heads_by_id.get(row.get("target_id")) or {}
        for tag in set(head.get("tags") or []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    if tag_counts and (max(tag_counts.values()) / total) >= threshold:
        return True

    return False


def _rolling_auto_add_supersede_count(slug: str, *, window_nights: int, now: float | None = None) -> int:
    """Count of `auto: true` add/supersede op-events for `slug` committed
    within the last `window_nights` days -- derived FRESH from committed
    op-events on disk every call (adrev-opt-014: NOT a mutable counter, so
    a mid-batch crash can never desync it; a re-run simply re-derives the
    same answer from whatever is actually on disk)."""
    now_ts = now if now is not None else time.time()
    cutoff = now_ts - (window_nights * 86400.0)
    count = 0
    for raw in _raw_op_events(slug):
        if raw.get("op") not in ("add", "supersede"):
            continue
        if raw.get("auto") is not True:
            continue
        ts = learnings_store._parse_iso(raw.get("timestamp") or "")  # noqa: SLF001 -- cross-module reuse of self-improving's ISO parser, mirroring memory_eval.py's own precedent for the same private helper
        if ts and ts >= cutoff:
            count += 1
    return count


def _rolling_rate_exceeded(slug: str, cfg: dict[str, Any], *, now: float | None = None) -> bool:
    """§3.8 cross-night accumulation signal: the patient-drip-attacker
    residual. A single per-run cap cannot see a slow trickle spread across
    many nights; this signal looks back `rolling_add_rate_window_nights`
    and treats exceeding `rolling_add_rate_max` as an anomaly feeding the
    circuit breaker. Bounded, not eliminated -- a plausible, prevalence-
    backed drip that stays under this threshold still gets through; the
    risk register names this honestly rather than claiming a guarantee.
    """
    window = int(cfg.get("rolling_add_rate_window_nights", 14))
    max_rate = int(cfg.get("rolling_add_rate_max", 40))
    return _rolling_auto_add_supersede_count(slug, window_nights=window, now=now) > max_rate


def _maybe_auto_resume(state: dict[str, Any], cfg: dict[str, Any], batch_id: str) -> dict[str, Any]:
    """If `state['suspended']` and enough quiet time has elapsed since
    `suspended_at`, clears the suspension, persists it, and audits the
    transition. Returns the (possibly updated) state. Caller MUST already
    hold `_apply_lock()`.

    "Quiet" needs no separate tracking: while suspended, the engine applies
    nothing (see run_optimistic_integrate's early return below), so no NEW
    anomaly can be recorded during the suspension window -- the mere
    passage of `circuit_breaker_auto_resume_nights` is sufficient. An
    ambiguous state (suspended but no parseable `suspended_at`, e.g. a
    hand-edited file) never auto-resumes -- fails closed, requires a
    manual `optimistic-resume`.
    """
    if not state.get("suspended"):
        return state
    suspended_at = state.get("suspended_at")
    if not suspended_at:
        return state
    ts = learnings_store._parse_iso(suspended_at)  # noqa: SLF001 -- see _rolling_auto_add_supersede_count
    if ts <= 0:
        return state
    resume_after_s = float(cfg.get("circuit_breaker_auto_resume_nights", 7)) * 86400.0
    if (time.time() - ts) < resume_after_s:
        return state
    state = dict(state)
    state["suspended"] = False
    state["suspended_at"] = None
    _write_optimistic_state_atomic(state)
    _write_audit({
        "outcome": "circuit_breaker_auto_resumed", "batch_id": batch_id,
        "detail": f"quiet for >= {cfg.get('circuit_breaker_auto_resume_nights', 7)} night(s) since suspension",
    })
    return state


def optimistic_resume() -> dict[str, Any]:
    """Manual, immediate re-enable (plan.md §3.5) -- the
    `apply_dream_proposal.py optimistic-resume` CLI subcommand. Always
    audited (never a silent un-suspend, matching every other breaker-state
    transition)."""
    with _apply_lock():
        state = _read_optimistic_state()
        was_suspended = bool(state.get("suspended"))
        state["suspended"] = False
        state["suspended_at"] = None
        _write_optimistic_state_atomic(state)
    record = {"outcome": "circuit_breaker_manual_resume", "was_suspended": was_suspended, "ok": True}
    _write_audit(record)
    return record


def _process_one_proposal(
    row: dict[str, Any], *, slug: str, cfg: dict[str, Any], live_count: int,
    anomaly_slugs: set[str], add_supersede_counts: dict[str, int],
    eviction_counts: dict[str, int], batch_id: str,
) -> dict[str, Any]:
    """Per-proposal posture/floor/cap/anomaly gate, then apply via the SAME
    `apply_proposal()` human accepts use (so the human-race lock and
    per-outcome audit trail cover this path for free).

    Returns a result dict `run_optimistic_integrate()` tallies via:
      - `applied: True`   -- apply_proposal() succeeded.
      - `attempted: True` (applied absent) -- apply_proposal() was CALLED
        but did not succeed (a real failure: CAS mismatch, target gone,
        etc.) -- distinct from a proposal this function decided NOT to
        attempt at all (gated/floor/prevalence/compaction-guard/cap/
        anomaly), which sets neither key.

    Never raises: every branch is inside a try/except so one malformed row
    (an unhashable `kind`, a non-dict `prevalence`, etc.) can never abort
    the rest of the batch -- mirrors apply_proposal()'s own handler-crash
    guard, one layer up.
    """
    proposal_id = row.get("id")
    try:
        kind = row.get("kind")
        project = row.get("project")

        posture = da.resolve_posture(kind, project)
        if posture["posture"] == "gated":
            _write_audit({
                "outcome": "skipped_gated", "batch_id": batch_id, "proposal_id": proposal_id,
                "kind": kind, "project": project,
            })
            return {"outcome": "skipped_gated", "proposal_id": proposal_id}

        floor_key = posture.get("confidence_floor")
        floor = int(cfg.get(floor_key, 0)) if floor_key else 0
        conf = _confidence_of(row)
        if conf < floor:
            _write_audit({
                "outcome": "skipped_floor", "batch_id": batch_id, "proposal_id": proposal_id,
                "kind": kind, "project": project, "detail": f"confidence {conf} < floor {floor}",
            })
            return {"outcome": "skipped_floor", "proposal_id": proposal_id}

        if kind == "learning_add":
            prevalence = row.get("prevalence") or {}
            sessions = prevalence.get("sessions") if isinstance(prevalence, dict) else None
            min_sessions = int(cfg.get("add_min_sessions", 2))
            if not isinstance(sessions, int) or isinstance(sessions, bool) or sessions < min_sessions:
                _write_audit({
                    "outcome": "skipped_prevalence", "batch_id": batch_id, "proposal_id": proposal_id,
                    "kind": kind, "project": project, "detail": f"sessions={sessions!r} < {min_sessions}",
                })
                return {"outcome": "skipped_prevalence", "proposal_id": proposal_id}

        if kind == "learning_supersede" and row.get("compaction_guard_failed"):
            _write_audit({
                "outcome": "skipped_compaction_guard", "batch_id": batch_id, "proposal_id": proposal_id,
                "kind": kind, "project": project,
            })
            return {"outcome": "skipped_compaction_guard", "proposal_id": proposal_id}

        per_run_cap = posture.get("per_run_cap")
        is_eviction = isinstance(per_run_cap, tuple)
        if is_eviction:
            if slug in anomaly_slugs:
                _write_audit({
                    "outcome": "skipped_anomaly", "batch_id": batch_id, "proposal_id": proposal_id,
                    "kind": kind, "project": project,
                })
                return {"outcome": "skipped_anomaly", "proposal_id": proposal_id}
            abs_key, frac_key = per_run_cap
            cap = min(float(cfg.get(abs_key, 0)), float(cfg.get(frac_key, 0)) * live_count)
            if eviction_counts[slug] >= cap:
                _write_audit({
                    "outcome": "skipped_over_cap", "batch_id": batch_id, "proposal_id": proposal_id,
                    "kind": kind, "project": project, "detail": f"eviction cap {cap} reached for {slug!r}",
                })
                return {"outcome": "skipped_over_cap", "proposal_id": proposal_id}
        elif isinstance(per_run_cap, str):
            cap = float(cfg.get(per_run_cap, 0))
            if add_supersede_counts[slug] >= cap:
                _write_audit({
                    "outcome": "skipped_over_cap", "batch_id": batch_id, "proposal_id": proposal_id,
                    "kind": kind, "project": project, "detail": f"add/supersede cap {cap} reached for {slug!r}",
                })
                return {"outcome": "skipped_over_cap", "proposal_id": proposal_id}

        dwell_hours = float(cfg.get("dwell_hours", 24)) if posture.get("needs_dwell") else None

        result = apply_proposal(
            proposal_id, method="auto_apply", reviewed_by="optimistic-integrate",
            dwell_hours=dwell_hours, batch_id=batch_id, posture=posture["posture"],
        )
        if result.get("ok"):
            if is_eviction:
                eviction_counts[slug] += 1
            elif isinstance(per_run_cap, str):
                add_supersede_counts[slug] += 1
            return {"outcome": result.get("outcome"), "proposal_id": proposal_id, "applied": True}
        return {
            "outcome": result.get("outcome"), "proposal_id": proposal_id, "attempted": True,
            "detail": result.get("detail"),
        }
    except Exception:  # noqa: BLE001 -- deliberate: a malformed row's gating logic must never
        # abort the rest of the batch (mirrors apply_proposal()'s own handler-crash guard).
        detail = traceback.format_exc()
        _write_audit({
            "outcome": "internal_error", "batch_id": batch_id, "proposal_id": proposal_id, "detail": detail,
        })
        return {"outcome": "internal_error", "proposal_id": proposal_id, "detail": detail}


def run_optimistic_integrate(day: str) -> dict[str, Any]:
    """The optimistic auto-integration engine (plan.md §5 Epic 3).

    Lock topology (adrev-opt-011): this function NEVER holds `_apply_lock()`
    across the batch. Each proposal is applied through `apply_proposal()`,
    which takes/releases the lock per call. The breaker-state read (before
    the loop) and the breaker-state write + single batch commit (after the
    loop) each acquire the lock in their OWN, non-nested critical section.

    Transaction model (adrev-opt-012/013): the whole batch runs with
    per-write autocommit suppressed (`_suppressed_autocommit()`) and makes
    at most ONE `ccgm-learnings-sync commit` at the end, tagged with
    `batch_id` in the commit message. Only `pending` proposals are ever
    considered (read once, at the top) -- an already-`auto_applied` row
    from an earlier run is never re-evaluated, so a `--force-day` re-run of
    a fully-integrated night applies nothing and adds no commit.

    Never raises; a single proposal's failure (or malformation) does not
    abort the batch -- see `_process_one_proposal()`.
    """
    path = proposals_dir() / f"{day}.jsonl"
    summary: dict[str, Any] = {
        "day": day, "batch_id": None, "evaluated": 0, "applied": 0, "skipped": 0,
        "failed": 0, "results": [], "anomalies": [], "circuit_breaker": None,
    }
    if not path.is_file():
        return summary

    rows = _read_jsonl(path)
    summary["evaluated"] = len(rows)
    pending = [r for r in rows if r.get("status") == "pending"]
    if not pending:
        return summary

    cfg = da.load_config().get("optimistic_integration") or {}

    batch_id = f"optbatch_{uuid.uuid4().hex[:12]}"

    # Circuit-breaker check: OWN, non-nested critical section (adrev-opt-011).
    with _apply_lock():
        state = _read_optimistic_state()
        was_suspended_before = bool(state.get("suspended"))
        state = _maybe_auto_resume(state, cfg, batch_id)
    if state.get("suspended"):
        summary["circuit_breaker"] = "suspended"
        return summary
    if was_suspended_before:
        summary["circuit_breaker"] = "auto_resumed"

    by_slug: dict[str, list[dict[str, Any]]] = {}
    for row in pending:
        project = row.get("project")
        if not isinstance(project, str) or not project:
            # Defensive (never expected from a schema-valid proposal row,
            # but a malformed/hand-edited row must not crash the whole
            # batch's slug-keyed bookkeeping below): treat like any other
            # proposal this engine declines to touch.
            _write_audit({
                "outcome": "skipped_malformed", "batch_id": batch_id, "proposal_id": row.get("id"),
                "kind": row.get("kind"), "detail": f"invalid project field: {project!r}",
            })
            summary["skipped"] += 1
            summary["results"].append({"outcome": "skipped_malformed", "proposal_id": row.get("id")})
            continue
        by_slug.setdefault(project, []).append(row)

    if not by_slug:
        return summary

    summary["batch_id"] = batch_id

    # P2 (security review): live_head_count is the eviction cap's
    # denominator -- computed for EVERY slug in the batch ONCE, before any
    # write, so same-run adds cannot inflate it.
    live_counts: dict[str, int] = {slug: _live_head_count(slug) for slug in by_slug}
    heads_by_slug: dict[str, dict[str, dict[str, Any]]] = {
        slug: {h["id"]: h for h in learnings_store.load_all(slug)} for slug in by_slug
    }

    # Batch-anomaly check (pre-apply, per slug, eviction-concentration only).
    anomaly_slugs: set[str] = set()
    run_anomaly_timestamps: list[str] = []
    for slug, slug_rows in by_slug.items():
        eviction_rows = [r for r in slug_rows if r.get("kind") in ("learning_contradict", "learning_deprecate")]
        if _batch_anomaly_fires(eviction_rows, heads_by_slug[slug], cfg):
            anomaly_slugs.add(slug)
            run_anomaly_timestamps.append(_utc_now_iso())
            summary["anomalies"].append({"slug": slug, "kind": "batch_eviction_concentration"})
            _write_audit({
                "outcome": "batch_anomaly_eviction_concentration", "batch_id": batch_id,
                "project": slug, "detail": f"{len(eviction_rows)} eviction proposal(s) concentrated",
            })

    add_supersede_counts: dict[str, int] = {slug: 0 for slug in by_slug}
    eviction_counts: dict[str, int] = {slug: 0 for slug in by_slug}

    with _suppressed_autocommit():  # adrev-opt-013: one commit for the whole batch, not one per write
        for slug, slug_rows in by_slug.items():
            for row in slug_rows:
                outcome = _process_one_proposal(
                    row, slug=slug, cfg=cfg, live_count=live_counts[slug],
                    anomaly_slugs=anomaly_slugs, add_supersede_counts=add_supersede_counts,
                    eviction_counts=eviction_counts, batch_id=batch_id,
                )
                summary["results"].append(outcome)
                if outcome.get("applied"):
                    summary["applied"] += 1
                elif outcome.get("attempted"):
                    summary["failed"] += 1
                else:
                    summary["skipped"] += 1

    # Cross-night accumulation signal (§3.8) -- derived AFTER applying, so
    # it reflects tonight's own contribution too. Feeds the breaker for
    # FUTURE nights; never retroactively undoes tonight's writes.
    for slug in by_slug:
        if _rolling_rate_exceeded(slug, cfg):
            run_anomaly_timestamps.append(_utc_now_iso())
            summary["anomalies"].append({"slug": slug, "kind": "rolling_add_rate_exceeded"})
            _write_audit({"outcome": "rolling_add_rate_exceeded", "batch_id": batch_id, "project": slug})

    # Breaker-state write + single batch commit: ONE non-nested critical
    # section (adrev-opt-011), acquired AFTER every per-proposal
    # apply_proposal() call above has already released the lock.
    with _apply_lock():
        state = _read_optimistic_state()
        state.setdefault("anomaly_log", [])
        state["anomaly_log"].extend(run_anomaly_timestamps)
        state["last_run"] = _utc_now_iso()

        window_nights = int(cfg.get("circuit_breaker_window_nights", 7))
        window_start = time.time() - (window_nights * 86400.0)
        recent = [
            t for t in state["anomaly_log"]
            if learnings_store._parse_iso(t) >= window_start  # noqa: SLF001 -- see _rolling_auto_add_supersede_count
        ]
        max_anomalies = int(cfg.get("circuit_breaker_max_anomalies", 2))
        if len(recent) >= max_anomalies and not state.get("suspended"):
            state["suspended"] = True
            state["suspended_at"] = _utc_now_iso()
            summary["circuit_breaker"] = "tripped"
            _write_audit({
                "outcome": "circuit_breaker_tripped", "batch_id": batch_id,
                "detail": f"{len(recent)} anomalies within {window_nights} night window "
                          f"(threshold {max_anomalies})",
            })

        _write_optimistic_state_atomic(state)

        if summary["applied"] > 0:
            commit_result = _run_sync_commit(
                message=f"dreaming: optimistic-integrate batch {batch_id} ({day})"
            )
            summary["commit"] = commit_result

    return summary


# ---------------------------------------------------------------------------
# Weekly, cost-capped eval refresh (optimistic-memory plan.md Epic 3, "fix
# (b) for adrev-opt-001"): keeps dream-eval.sh --gate's 14-day freshness
# bound met without manual intervention, without competing with the
# nightly analyzer for the SAME daily_cost_cap_usd (adrev-opt-010).
# ---------------------------------------------------------------------------


def _eval_script_path() -> Path:
    """`modules/dreaming/eval/memory_eval.py`, resolved relative to this
    file (lib/ and eval/ are sibling directories WITHIN the same module --
    always installed/checked-out together, unlike the self-improving
    cross-module resolution `_resolve_sibling_bin()` handles above, so no
    installed-vs-repo-relative fallback dance is needed here).
    `CCGM_DREAMING_EVAL_REFRESH_SCRIPT` lets tests substitute a fixture
    script that mimics memory_eval.py's `--date`/results-file contract
    without ever invoking the real live A/B harness -- mirrors dream-
    daily.sh's own `CCGM_DREAMING_EVAL_SCRIPT` override for the --gate
    script.
    """
    override = os.environ.get("CCGM_DREAMING_EVAL_REFRESH_SCRIPT")
    if override:
        return Path(override)
    return _HERE.parent / "eval" / "memory_eval.py"


def _latest_eval_results_age_days(*, now: float | None = None) -> float | None:
    """Age in days of the most recently-modified eval results file under
    dreaming's evals/ dir, or None if none exists yet (treated by the
    caller as "infinitely stale" -- always eligible to refresh)."""
    evals_dir = dreaming_dir() / "evals"
    if not evals_dir.is_dir():
        return None
    files = sorted(evals_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    now_ts = now if now is not None else time.time()
    return (now_ts - files[0].stat().st_mtime) / 86400.0


def _read_cost_spent_today_by_label(path: Path, today: str, label: str) -> float:
    """Like `dream_analyze._read_cost_spent_today()`, but scoped to ledger
    rows whose `model` field equals `label` exactly. Lets the eval-refresh
    step check its OWN spend against its OWN `eval_refresh_cost_cap_usd`
    without being confused by the analyzer's spend on the SAME shared
    `cost.log` file (adrev-opt-010: the two must never silently compete
    for one cap, but they DO share one ledger so total daily spend stays
    visible in one place)."""
    if not path.is_file():
        return 0.0
    total = 0.0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 5 and parts[0] == today and parts[4] == label:
                try:
                    total += float(parts[3])
                except ValueError:
                    continue
    return total


def _eval_refresh_preconditions(day: str, cfg: dict[str, Any]) -> tuple[bool, str]:
    """Pure(-ish) precondition gate for `run_eval_refresh()`: no
    subprocess, no network -- only an mtime check, an env var read, and a
    ledger read. Split out from `run_eval_refresh()` specifically so this
    gating logic (the part that matters for cost safety) is unit-testable
    without ever invoking the live eval harness. Returns (should_run,
    reason).
    """
    opt_cfg = cfg.get("optimistic_integration") or {}
    min_age_days = float(opt_cfg.get("eval_refresh_min_age_days", 7))
    cost_cap = float(opt_cfg.get("eval_refresh_cost_cap_usd", 2.0))

    age_days = _latest_eval_results_age_days()
    if age_days is not None and age_days < min_age_days:
        return False, f"latest eval results are {age_days:.1f}d old (< {min_age_days}d min); skipping"

    da.load_env()  # dreaming's own .env, falling back to autoheal's (mirrors memory_eval.main())
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "no ANTHROPIC_API_KEY configured; skipping"

    spent = _read_cost_spent_today_by_label(da.cost_log_path(), day, EVAL_REFRESH_COST_LABEL)
    if spent >= cost_cap:
        return False, f"eval_refresh_cost_cap_usd exhausted (spent ${spent:.4f} of ${cost_cap:.4f})"

    return True, "ok"


def run_eval_refresh(day: str) -> dict[str, Any]:
    """Fix (b) for adrev-opt-001: runs the full live A/B eval
    (memory_eval.py, no --offline) to keep dream-eval.sh --gate's 14-day
    freshness bound met -- but ONLY when `_eval_refresh_preconditions()`
    passes. If not eligible, logs the reason and returns without touching
    anything (the 14-day bound then eventually fails the gate closed on
    its own -- a surfaced, safe degradation, never a silent one;
    adrev-opt-009's named, accepted drift window).

    Honest limitation: `_eval_refresh_preconditions()`'s cost-cap check is
    a START gate (refuses to begin if the ledger already shows the cap
    spent today), not a HARD mid-run stop -- memory_eval.py has no
    cumulative total-run cost limiter today (only a PER-CALL
    `--max-budget-usd`, a different knob), and adding one is out of this
    function's file-touch scope (memory_eval.py is not modified here). A
    single refresh run can therefore spend somewhat more than
    `eval_refresh_cost_cap_usd` before the NEXT day's precondition check
    sees the overage and refuses to run again. Actual spend is always
    recorded to the shared ledger regardless of whether it overshot, so
    the overage is visible, not hidden.
    """
    cfg = da.load_config()
    summary: dict[str, Any] = {"day": day, "ran": False, "reason": None}

    should_run, reason = _eval_refresh_preconditions(day, cfg)
    if not should_run:
        summary["reason"] = reason
        return summary

    script = _eval_script_path()
    if not script.is_file():
        summary["reason"] = f"eval refresh script not found at {script}"
        return summary

    proc = subprocess.run(
        [sys.executable, str(script), "--date", day],
        capture_output=True, text=True, check=False,
    )
    summary["exit_code"] = proc.returncode
    if proc.stderr:
        summary["stderr_tail"] = proc.stderr[-2000:]

    results_path = dreaming_dir() / "evals" / f"{day}.jsonl"
    if results_path.is_file():
        result_rows = _read_jsonl(results_path)
        total_cost = sum(float(r.get("cost_usd") or 0.0) for r in result_rows)
        if total_cost > 0:
            da._append_cost(  # noqa: SLF001 -- cross-module reuse of the analyzer's own shared cost-ledger writer
                da.cost_log_path(), day, 0, 0, total_cost, EVAL_REFRESH_COST_LABEL,
            )
        summary["cost_usd"] = round(total_cost, 6)
        summary["rows_written"] = len(result_rows)

    summary["ran"] = proc.returncode == 0
    if not summary["ran"] and not summary.get("reason"):
        summary["reason"] = f"memory_eval.py exited {proc.returncode}"
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_list(args: argparse.Namespace) -> int:
    rows = list_pending(days_back=args.days_back)
    print(json.dumps(rows, sort_keys=True))
    return 0


def _cmd_accept(args: argparse.Namespace) -> int:
    result = apply_proposal(args.id, method="human_accept", reviewed_by=args.reviewed_by)
    print(json.dumps(result, sort_keys=True))
    sync_result = _run_sync_commit()
    if not sync_result.get("ok"):
        print(json.dumps({"sync_commit": sync_result}, sort_keys=True), file=sys.stderr)
    return 1 if result.get("outcome") == "not_found" else 0


def _cmd_reject(args: argparse.Namespace) -> int:
    result = reject_proposal(args.id)
    print(json.dumps(result, sort_keys=True))
    sync_result = _run_sync_commit()
    if not sync_result.get("ok"):
        print(json.dumps({"sync_commit": sync_result}, sort_keys=True), file=sys.stderr)
    return 1 if result.get("outcome") == "not_found" else 0


def _cmd_auto_apply(args: argparse.Namespace) -> int:
    day = args.day or today_iso()
    summary = run_auto_apply(day)
    print(json.dumps(summary, sort_keys=True))
    _run_sync_commit()
    return 0


def _cmd_optimistic_integrate(args: argparse.Namespace) -> int:
    # No _run_sync_commit() call here -- run_optimistic_integrate() already
    # makes its own single batch commit internally (adrev-opt-013), under
    # the same critical section as the breaker-state write. Calling it
    # again here would either no-op (clean tree) or, worse, fold any
    # unrelated dirty state into a second, unlabeled commit.
    day = args.day or today_iso()
    summary = run_optimistic_integrate(day)
    print(json.dumps(summary, sort_keys=True))
    return 0


def _cmd_optimistic_resume(args: argparse.Namespace) -> int:
    result = optimistic_resume()
    print(json.dumps(result, sort_keys=True))
    return 0


def _cmd_eval_refresh(args: argparse.Namespace) -> int:
    day = args.day or today_iso()
    summary = run_eval_refresh(day)
    print(json.dumps(summary, sort_keys=True))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CCGM dreaming: human-gated apply path (Epic 6).")
    sub = p.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list", help="list pending proposals across the last N days")
    list_p.add_argument("--days-back", type=int, default=8)
    list_p.set_defaults(func=_cmd_list)

    accept_p = sub.add_parser("accept", help="apply one pending proposal by id")
    accept_p.add_argument("id")
    accept_p.add_argument("--reviewed-by")
    accept_p.set_defaults(func=_cmd_accept)

    reject_p = sub.add_parser("reject", help="mark one pending proposal rejected (no store write)")
    reject_p.add_argument("id")
    reject_p.set_defaults(func=_cmd_reject)

    auto_p = sub.add_parser(
        "auto-apply",
        help="batch-apply qualifying learning_verify rows for one day "
             "(config/eval-gating is dream-daily.sh's job, not this CLI's; retained for "
             "backward compatibility -- dream-daily.sh's nightly chain now calls "
             "optimistic-integrate instead)",
    )
    auto_p.add_argument("--day", help="defaults to today (UTC, or CCGM_DREAMING_TODAY)")
    auto_p.set_defaults(func=_cmd_auto_apply)

    opt_p = sub.add_parser(
        "optimistic-integrate",
        help="run the full per-op-kind posture engine over one day's pending proposals "
             "(config/eval-gating is dream-daily.sh's job, not this CLI's; optimistic-memory "
             "plan.md Epic 3)",
    )
    opt_p.add_argument("--day", help="defaults to today (UTC, or CCGM_DREAMING_TODAY)")
    opt_p.set_defaults(func=_cmd_optimistic_integrate)

    resume_p = sub.add_parser(
        "optimistic-resume", help="force-clear a tripped optimistic-integration circuit breaker immediately",
    )
    resume_p.set_defaults(func=_cmd_optimistic_resume)

    refresh_p = sub.add_parser(
        "eval-refresh",
        help="weekly, cost-capped live eval refresh so dream-eval.sh --gate's 14-day freshness "
             "bound stays met without manual intervention (fix (b) for adrev-opt-001)",
    )
    refresh_p.add_argument("--day", help="defaults to today (UTC, or CCGM_DREAMING_TODAY)")
    refresh_p.set_defaults(func=_cmd_eval_refresh)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
