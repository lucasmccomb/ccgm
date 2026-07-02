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
    learning_verify      -> `ccgm-learnings-log verify <target_id>`
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
target_not_found, unsupported_kind) leaves `status` untouched at `pending` --
schema-safe, and keeps the proposal visible for retry. The FULL outcome
detail for every attempt -- success or failure -- lives in
~/.claude/dreaming/state/apply-audit.jsonl, never only in a return value that
evaporates when the caller exits (adrev-012/adrev-302: "never silent").

adrev-013 (refuse non-pending): a proposal whose `status` is already
anything other than `pending` is refused outright -- no CLI call is even
attempted -- so a stray re-apply can never double-count a counter-op or
re-supersede an already-superseded target.
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


def _run_sync_commit() -> dict[str, Any]:
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
    """
    try:
        binpath = _resolve_sibling_bin("ccgm-learnings-sync")
    except FileNotFoundError as exc:
        return {"ok": False, "reason": str(exc)}
    try:
        proc = subprocess.run(
            [sys.executable, binpath, "commit"],
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


def _rewrite_status(path: Path, proposal_id: str, new_status: str) -> dict[str, Any] | None:
    """Locked read-modify-write of exactly the `status` field on one row.

    Every row is re-serialized (not hand-patched as a text diff), so the
    frozen proposal-schema.json shape Epic 3 owns is round-tripped exactly
    as dream_analyze.py wrote it, plus the one field this module is
    licensed to touch. Returns the updated row, or None if `proposal_id`
    is not present in `path` (caller's problem to report -- this function
    never raises on a not-found).
    """
    with _apply_lock():
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
            row = json.loads(line)
            if row.get("id") == proposal_id:
                row["status"] = new_status
                updated = row
            out_lines.append(json.dumps(row, sort_keys=True))
        if updated is None:
            return None
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        tmp.replace(path)
        return updated


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


def _apply_learning_add(row: dict[str, Any], *, reviewed_by: str) -> dict[str, Any]:
    if row.get("project") == GLOBAL_SLUG:
        return _apply_global_add(row, reviewed_by=reviewed_by)

    args = [
        "--type", row["type"],
        "--content", row["content"],
        "--confidence", str(row["confidence"]),
        "--source", DEFAULT_MINED_SOURCE,
        "--project", row["project"],
    ]
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


def _apply_counter_op(row: dict[str, Any], op: str) -> dict[str, Any]:
    args = [op, row["target_id"], "--project", row["project"]]
    session = _first_evidence_session(row)
    if session:
        args += ["--session", session]
    proc = _run_learnings_log(args)
    if proc.returncode == 0:
        return {"outcome": "applied"}
    if proc.returncode == 1:
        return {"outcome": "target_not_found", "detail": proc.stderr.strip()}
    if proc.returncode == 4:
        return {"outcome": "failed_promotion", "detail": proc.stderr.strip()}
    return {"outcome": "unexpected_exit_code", "detail": f"exit={proc.returncode}: {proc.stderr.strip()}"}


def _apply_learning_verify(row: dict[str, Any], *, reviewed_by: str) -> dict[str, Any]:
    return _apply_counter_op(row, "verify")


def _apply_learning_contradict(row: dict[str, Any], *, reviewed_by: str) -> dict[str, Any]:
    return _apply_counter_op(row, "contradict")


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
        if proc.returncode == 1:
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


def _apply_learning_deprecate(row: dict[str, Any], *, reviewed_by: str) -> dict[str, Any]:
    def build_argv(sha: str) -> list[str]:
        args = ["deprecate", row["target_id"], "--project", row["project"], "--expected-sha", sha]
        session = _first_evidence_session(row)
        if session:
            args += ["--session", session]
        return args

    return _apply_cas_op(row, build_argv=build_argv)


def _apply_learning_supersede(row: dict[str, Any], *, reviewed_by: str) -> dict[str, Any]:
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


def apply_proposal(proposal_id: str, *, method: str = "human_accept", reviewed_by: str | None = None) -> dict[str, Any]:
    """The single write entry point for accepting a pending proposal.

    Refuses (adrev-013) any proposal whose status is not 'pending' rather
    than re-applying it -- no CLI call is even attempted. On success the
    row's `status` becomes 'accepted' (method=human_accept) or
    'auto_applied' (method=auto_apply), the only two positive terminal
    states this path is licensed to write. Every OTHER outcome leaves the
    row 'pending' (schema-safe, retry-visible). Always writes exactly one
    audit record, whatever the outcome (adrev-012/adrev-302: never silent).
    """
    reviewed_by = reviewed_by or os.environ.get("USER") or os.environ.get("LOGNAME") or "human"
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

    result = handler(row, reviewed_by=reviewed_by)
    outcome = result.get("outcome")
    ok = outcome == "applied"

    if ok:
        new_status = "auto_applied" if method == "auto_apply" else "accepted"
        _rewrite_status(path, proposal_id, new_status)

    record = {
        "proposal_id": proposal_id, "kind": kind, "project": row.get("project"),
        "target_id": row.get("target_id"), "method": method, "reviewed_by": reviewed_by,
        "ok": ok, **result,
    }
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
             "(config/eval-gating is dream-daily.sh's job, not this CLI's)",
    )
    auto_p.add_argument("--day", help="defaults to today (UTC, or CCGM_DREAMING_TODAY)")
    auto_p.set_defaults(func=_cmd_auto_apply)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
