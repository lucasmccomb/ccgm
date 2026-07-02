#!/usr/bin/env python3
"""
Learnings store: shared library for ccgm-learnings-log and ccgm-learnings-search.

A learning is a structured, project-scoped record of a pattern, pitfall,
preference, architecture note, tool gotcha, or operational fact.

v2 storage model (op-events, per-agent shards):
    ~/.claude/learnings/
        config.json                     # Cross-project search opt-in and tunables
        {project-slug}/
            learnings.jsonl             # Legacy v1 file: full-state snapshot rows
            agents/
                <agent-id>.jsonl        # v2: ALL new writes land here, append-only
        _global/
            learnings.jsonl
            agents/<agent-id>.jsonl     # promotion-only (see promote_to_global)

Every line under `agents/` is an OP-EVENT, not a snapshot:

    {"id": "...", "op": "add|verify|contradict|supersede|deprecate",
     "target_id": "<id acted on, null for add>", "timestamp": "...",
     "type": ..., "source": ..., "content": ..., "confidence": ...,
     "tags": [...], "files": [...], "project": "<slug>", "key": "...",
     "content_sha256": "...", "writer": "agent-w0-c0|human",
     "source_session": "<claude session uuid or null>",
     "expected_sha256": "<CAS, supersede/deprecate only>",
     "supersede_reason": "...", "last_verified": "...", "deprecated": ...}

Legacy v1 rows (no `op` field) are full-state snapshots and are projected
VERBATIM (their `uses`/`contradictions`/`deprecated`/`superseded_by` fields
already ARE the state). The read path is a deterministic, two-phase fold
over the union of the legacy file and every agent shard:

    Phase A - seed heads from legacy rows (verbatim) + v2 `add` events
              (fresh, zeroed counters).
    Phase B - apply verify/contradict/deprecate/supersede op-events, in
              (timestamp, id) order, onto their `target_id`'s head. A
              `supersede` event both mutates its target (`superseded_by`)
              and seeds a brand-new head of its own. Ops whose target has
              not yet been seeded are retried until a fixpoint; ops that
              never resolve are surfaced as `orphan_ops`, never dropped.

Two concurrent `supersede` events targeting the same live head are a
CONFLICT, not a last-write-wins race: both new heads are retained and the
old head is flagged `conflict: true` for a human to resolve.

A per-project, per-machine snapshot cache (outside the store dir, never a
git-sync participant) accelerates repeated reads: `project_slug()` folds
only the lines appended since the last cached watermark, falling back to a
full replay whenever that fast path cannot be proven safe (e.g. cross-writer
clock skew, or a cached state with unresolved orphan ops).

Concurrency: writes are `fcntl`-locked per-shard appends
(`hook_utils.file_locked_append`), so distinct writers racing the same
shard never tear a line. Cross-shard races on the SAME logical entry (e.g.
two agent-ids superseding the same row) are not prevented -- they are
DETECTED via the conflict flag above.

Security invariants (write-time, never bypassable via caller-supplied
strings alone):
    - `_global` writes require CCGM_LEARNINGS_ADMIN=1 (general CLI/API) or
      go through `promote_to_global()`, the one structurally privileged
      path, which verifies every cited evidence session against a REAL,
      on-disk transcript file and derives `writer` from that transcript's
      recorded cwd -- never from the freely-exportable CCGM_AGENT_ID.
    - Raising a supersede chain's `source` tier (e.g. inferred ->
      user-stated) requires a NEW `source_session` (not already present in
      the chain) that likewise resolves to a real transcript file.
    - `sanitize_content()` is applied to every model-influenceable
      free-text field at the write path: `content` and `supersede_reason`.

This file is intentionally stdlib-only (no PyYAML, no requests) so it
installs cleanly without pip.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# hook_utils import (file_locked_append) -- best-effort with a local
# fallback so this module stays importable in isolation (e.g. tests that
# don't have ~/.claude/lib on sys.path).
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised implicitly by every write-path test
    _HOOKS_LIB = Path(os.path.expanduser("~/.claude/lib"))
    if str(_HOOKS_LIB) not in sys.path:
        sys.path.insert(0, str(_HOOKS_LIB))
    from hook_utils import file_locked_append  # type: ignore
except Exception:  # pragma: no cover - fallback path
    import fcntl

    def file_locked_append(path: str, data: str) -> None:  # type: ignore[misc]
        """Fallback: append `data` (newline-terminated) to `path`, fcntl-locked.

        Mirrors modules/hooks/lib/hook_utils.py::file_locked_append exactly,
        used only when that module is not importable (e.g. a bare checkout
        with no ~/.claude/lib installed yet).
        """
        payload = data if data.endswith("\n") else data + "\n"
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                os.write(fd, payload.encode("utf-8"))
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

LEARNINGS_ROOT = Path(os.path.expanduser(
    os.environ.get("CCGM_LEARNINGS_DIR", "~/.claude/learnings")
))
CONFIG_PATH = LEARNINGS_ROOT / "config.json"
GLOBAL_SLUG = "_global"

# Read-time snapshot/materialization cache (arch-2). Lives OUTSIDE
# LEARNINGS_ROOT as a sibling directory -- structurally never a git-sync
# participant even before Epic 5's own .gitignore exists (adrev-301): no
# git operation is required or performed anywhere in this module. Purely a
# rebuildable, per-machine performance aid; never consulted for CAS or
# origin-binding truth (those always re-project fresh).
LEARNINGS_CACHE_ROOT = Path(os.path.expanduser(
    os.environ.get(
        "CCGM_LEARNINGS_CACHE_DIR",
        str(LEARNINGS_ROOT.parent / (LEARNINGS_ROOT.name + "-cache")),
    )
))

# Claude Code session transcripts: ~/.claude/projects/<cwd-slug>/<session-id>.jsonl
# NOTE this is a DIFFERENT slug space than detect_project_slug() below (the
# transcript directory name is a sanitized cwd path, not a git-remote
# derived slug -- arch-1). Only used to verify a session id is real.
CLAUDE_PROJECTS_ROOT = Path(os.path.expanduser(
    os.environ.get("CCGM_CLAUDE_PROJECTS_DIR", "~/.claude/projects")
))

# ---------------------------------------------------------------------------
# Schema vocabulary
# ---------------------------------------------------------------------------

VALID_TYPES = {"pattern", "pitfall", "preference", "architecture", "tool", "operational"}
VALID_SOURCES = {"observed", "user-stated", "inferred", "cross-model"}
VALID_OPS = {"add", "verify", "contradict", "supersede", "deprecate"}
CONFIDENCE_MIN = 1
CONFIDENCE_MAX = 10
DEFAULT_CONFIDENCE = 5

# Origin-binding tier ranking (§3.3 write rules): a supersede may never
# RAISE source tier (move to a higher rank) without a fresh, transcript
# verified source_session. Higher = more authoritative.
SOURCE_TIER_RANK = {
    "inferred": 0,
    "cross-model": 1,
    "observed": 2,
    "user-stated": 3,
}

DEFAULT_HALF_LIFE_DAYS = 90.0
DEFAULT_DEPRECATE_THRESHOLD = 2.0   # effective confidence below this -> skip on read
DEFAULT_STALE_DAYS = 180.0          # flag entries not verified in this long
DEFAULT_TOKEN_BUDGET = 2000         # rough character-based budget (4 chars/token)
DEFAULT_MAX_RESULTS = 8

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    pass


class CASConflictError(Exception):
    """Raised when --expected-sha does not match the target's current content.

    `current_sha` carries the target's actual content_sha256 so the caller
    can re-read and retry (§3.4: CLI exit code 3).
    """

    def __init__(self, current_sha: str, message: str | None = None):
        self.current_sha = current_sha
        super().__init__(message or f"CAS mismatch: current content sha256 is {current_sha}")


class OriginBindingError(ValueError):
    """Raised when a supersede would raise the source tier without a fresh,
    transcript-verified source_session (§3.3, sec-1)."""


class GlobalPromotionError(Exception):
    """Raised when a write targets `_global` without authorization (§3.3, sec-1)."""


# ---------------------------------------------------------------------------
# Config (cross-project opt-in, tunables)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "cross_project_search": False,
    "half_life_days": DEFAULT_HALF_LIFE_DAYS,
    "deprecate_threshold": DEFAULT_DEPRECATE_THRESHOLD,
    "stale_days": DEFAULT_STALE_DAYS,
    "token_budget": DEFAULT_TOKEN_BUDGET,
    "max_results": DEFAULT_MAX_RESULTS,
}


def load_config() -> dict[str, Any]:
    """Load config.json if present, merged over defaults."""
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.is_file():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    LEARNINGS_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Project slug detection
# ---------------------------------------------------------------------------

def detect_project_slug(cwd: str | None = None) -> str:
    """
    Derive a stable project slug from the git remote URL or the working dir.

    Precedence:
    1. CCGM_LEARNINGS_PROJECT env var (explicit override).
    2. git remote origin -> {owner}_{repo} (sanitized).
    3. basename of git toplevel.
    4. basename of cwd.

    This is the ONE canonical slug resolver for the learnings store (arch-1).
    It is NOT the same slug space as Claude Code's own transcript directory
    naming under ~/.claude/projects/ -- never conflate the two.
    """
    env = os.environ.get("CCGM_LEARNINGS_PROJECT")
    if env:
        return _slugify(env)

    wd = cwd or os.getcwd()
    try:
        import subprocess
        remote = subprocess.run(
            ["git", "-C", wd, "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=2,
        )
        if remote.returncode == 0 and remote.stdout.strip():
            url = remote.stdout.strip()
            # Parse owner/repo from https or ssh URLs
            m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
            if m:
                return _slugify(f"{m.group(1)}_{m.group(2)}")

        toplevel = subprocess.run(
            ["git", "-C", wd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        if toplevel.returncode == 0 and toplevel.stdout.strip():
            return _slugify(Path(toplevel.stdout.strip()).name)
    except Exception:
        pass

    return _slugify(Path(wd).name)


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "unknown"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def project_dir(slug: str) -> Path:
    return LEARNINGS_ROOT / slug


def project_jsonl(slug: str) -> Path:
    """The legacy v1 file. Read-only from v2's perspective (still folded
    on every read for backward compatibility); no new writes land here."""
    return LEARNINGS_ROOT / slug / "learnings.jsonl"


def agent_shard_path(slug: str, writer: str) -> Path:
    """§3.3: `<project-slug>/agents/<agent_id>.jsonl` -- ALL new writes
    land in the writer's own shard."""
    return LEARNINGS_ROOT / slug / "agents" / f"{writer}.jsonl"


def list_agent_shards(slug: str) -> list[Path]:
    d = LEARNINGS_ROOT / slug / "agents"
    if not d.is_dir():
        return []
    return sorted(d.glob("*.jsonl"))


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    # Millisecond precision so rapid successive writes produce distinct timestamps
    # for dedup tie-breaking. Still serializes as ISO 8601 with trailing Z.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def _iso_from_epoch(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{dt.microsecond // 1000:03d}Z"


def _parse_iso(s: str) -> float:
    """Parse ISO 8601 UTC string to epoch seconds. 0.0 on failure.
    Accepts both second- and millisecond-precision forms (trailing Z).
    """
    if not s:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return 0.0


# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------

def agent_id(cwd: str | None = None) -> str:
    """
    Resolve the writer identity for a shard write / display label.

    Precedence: CCGM_AGENT_ID env var -> AGENT_ID in <cwd>/.env.clone ->
    'solo'. This is a DISPLAY/SHARD label only -- it is NEVER trusted for
    `_global` promotion or an origin-binding tier raise. Both of those
    derive `writer` from a verified transcript's own recorded `cwd`
    instead (sec-1: a caller-exportable env var cannot bind provenance).
    """
    env = os.environ.get("CCGM_AGENT_ID")
    if env:
        return env
    wd = cwd or os.getcwd()
    env_clone = Path(wd) / ".env.clone"
    if env_clone.is_file():
        try:
            for line in env_clone.read_text(encoding="utf-8").splitlines():
                if line.startswith("AGENT_ID="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return val
        except OSError:
            pass
    return "solo"


def _is_global_admin() -> bool:
    return os.environ.get("CCGM_LEARNINGS_ADMIN") == "1"


# ---------------------------------------------------------------------------
# Content hashing (CAS)
# ---------------------------------------------------------------------------

def content_sha256(content: str | None) -> str:
    """sha256 hex digest of `content`; empty-string hash when content is None."""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Prompt-injection sanitizer
# ---------------------------------------------------------------------------

# Patterns that look like LLM instructions and should never survive the write
# path. We neutralize them by wrapping in literal quotes and prefixing with
# [neutralized] so the text survives but cannot be executed as an instruction
# by a downstream consumer.
#
# The goal is NOT to prevent all possible injection; it is to catch the common
# accidental case where a user pastes a prompt into a free-text field and the
# content later gets injected into a system prompt verbatim.

INJECTION_PATTERNS = [
    r"(?im)^\s*system\s*:",
    r"(?im)^\s*assistant\s*:",
    r"(?im)^\s*user\s*:",
    r"(?im)^\s*ignore (?:all\s+|previous\s+|prior\s+)+(?:instructions|prompts)",
    r"(?im)^\s*you are (?:now|an?)\b",
    r"(?im)^\s*disregard .* (?:rules|instructions|guidelines)",
    r"(?im)<\s*/?\s*(?:system|instructions|prompt)\s*>",
    r"(?im)```\s*system",
]


def sanitize_content(text: str) -> str:
    """
    Neutralize instruction-like patterns in user-supplied content.

    Wraps matches with `[neutralized]...[/neutralized]` markers so the text
    stays readable but downstream injection becomes inert. Applied to EVERY
    model-influenceable free-text field at the write path -- `content` and
    `supersede_reason` (sec-4) -- never re-applied on read (not idempotent
    for `<system>`-tag shapes).
    """
    out = text
    for pat in INJECTION_PATTERNS:
        out = re.sub(
            pat,
            lambda m: f"[neutralized]{m.group(0)}[/neutralized]",
            out,
        )
    # Collapse runs of whitespace
    out = re.sub(r"[ \t]+", " ", out).strip()
    # Cap length to prevent pathological entries
    if len(out) > 2000:
        out = out[:2000].rstrip() + "..."
    return out


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_entry(entry: dict[str, Any]) -> None:
    """Raise ValidationError if entry violates schema. Mutates nothing."""
    required = {"type", "content"}
    missing = required - entry.keys()
    if missing:
        raise ValidationError(f"missing required fields: {sorted(missing)}")

    if entry["type"] not in VALID_TYPES:
        raise ValidationError(
            f"invalid type {entry['type']!r}, expected one of {sorted(VALID_TYPES)}"
        )

    src = entry.get("source", "observed")
    if src not in VALID_SOURCES:
        raise ValidationError(
            f"invalid source {src!r}, expected one of {sorted(VALID_SOURCES)}"
        )

    conf = entry.get("confidence", DEFAULT_CONFIDENCE)
    if not isinstance(conf, (int, float)) or not (CONFIDENCE_MIN <= conf <= CONFIDENCE_MAX):
        raise ValidationError(
            f"confidence must be {CONFIDENCE_MIN}-{CONFIDENCE_MAX}, got {conf!r}"
        )

    if not isinstance(entry["content"], str) or not entry["content"].strip():
        raise ValidationError("content must be a non-empty string")

    for field in ("tags", "files"):
        if field in entry and not isinstance(entry[field], list):
            raise ValidationError(f"{field} must be a list")


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

def _dedup_key(content: str, type_: str) -> str:
    """Derive a stable dedup key from content."""
    normalized = re.sub(r"\s+", " ", content.lower().strip())
    digest = hashlib.sha1(f"{type_}:{normalized}".encode()).hexdigest()
    return digest[:12]


def build_entry(
    *,
    type_: str,
    content: str,
    source: str = "observed",
    confidence: int = DEFAULT_CONFIDENCE,
    tags: list[str] | None = None,
    files: list[str] | None = None,
    project: str | None = None,
    key: str | None = None,
    supersedes: str | None = None,
    supersede_reason: str | None = None,
    source_session: str | None = None,
    evidence_sessions: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build a schema-valid, sanitized entry. Does NOT write.

    sanitize_content() is applied to BOTH `content` and `supersede_reason`
    (sec-4: every model-influenceable free-text field, not just content).
    """
    sanitized = sanitize_content(content)
    sanitized_reason = sanitize_content(supersede_reason) if supersede_reason else None
    entry: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": _utc_now_iso(),
        "type": type_,
        "source": source,
        "content": sanitized,
        "confidence": int(confidence),
        "tags": sorted({t.lower().strip() for t in (tags or []) if t.strip()}),
        "files": [f for f in (files or []) if f],
        "project": project or detect_project_slug(),
        "key": key or _dedup_key(sanitized, type_),
        "last_verified": _utc_now_iso(),
        "uses": 0,
        "contradictions": 0,
        "deprecated": False,
        "supersedes": supersedes,
        "superseded_by": None,
        "supersede_reason": sanitized_reason,
        "source_session": source_session,
        "evidence_sessions": list(evidence_sessions) if evidence_sessions else [],
    }
    validate_entry(entry)
    return entry


def _read_last_line(path: Path) -> dict[str, Any] | None:
    """Efficiently read + parse the last JSON line of a file via a tail seek."""
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None
    chunk = 4096
    data = b""
    with path.open("rb") as f:
        pos = size
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
            if data.count(b"\n") >= 2 or pos == 0:
                break
    lines = [ln for ln in data.split(b"\n") if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        # Pathological single giant line near the tail chunk boundary --
        # fall back to a full read rather than silently losing monotonicity.
        all_lines = _read_jsonl_file(path)
        return all_lines[-1] if all_lines else None


def _next_writer_timestamp(shard_path: Path) -> str:
    """
    Per-writer monotonic timestamp (adrev-402): stamp = max(wall_now,
    own_last + 1ms). Reads this writer's own shard tail so successive
    writes from the SAME writer -- even across separate process
    invocations -- never go backward or collide, with no extra state file.
    """
    now_iso = _utc_now_iso()
    last = _read_last_line(shard_path)
    last_ts = last.get("timestamp") if last else None
    if not last_ts:
        return now_iso
    now_epoch = _parse_iso(now_iso)
    last_epoch = _parse_iso(last_ts)
    if now_epoch > last_epoch:
        return now_iso
    return _iso_from_epoch(last_epoch + 0.001)


def _build_op_row(
    *,
    op: str,
    target_id: str | None,
    project: str,
    writer: str,
    timestamp: str,
    type_: str | None = None,
    source: str | None = None,
    content: str | None = None,
    confidence: int | None = None,
    tags: list[str] | None = None,
    files: list[str] | None = None,
    key: str | None = None,
    source_session: str | None = None,
    expected_sha256: str | None = None,
    supersede_reason: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Build a canonical v2 op-event row (§3.3 schema). Does not write."""
    return {
        "id": event_id or uuid.uuid4().hex[:12],
        "op": op,
        "target_id": target_id,
        "timestamp": timestamp,
        "type": type_,
        "source": source,
        "content": content,
        "confidence": confidence,
        "tags": tags if tags is not None else ([] if op in ("add", "supersede") else None),
        "files": files if files is not None else ([] if op in ("add", "supersede") else None),
        "project": project,
        "key": key,
        "content_sha256": content_sha256(content),
        "writer": writer,
        "source_session": source_session,
        "expected_sha256": expected_sha256,
        "supersede_reason": supersede_reason,
        "last_verified": timestamp,
        "deprecated": True if op == "deprecate" else (False if op == "add" else None),
    }


def append_entry(entry: dict[str, Any], slug: str | None = None) -> Path:
    """
    Append a pre-validated entry as a v2 `add` op-event to the writer's own
    shard (§3.3 -- ALL new writes land in agents/<agent_id>.jsonl; the
    legacy learnings.jsonl file is read-only from v2's perspective, still
    folded on every read for backward compatibility).

    Raises GlobalPromotionError if `slug` (or `entry["project"]`) resolves
    to `_global` and CCGM_LEARNINGS_ADMIN=1 is not set -- the general write
    path never lands `_global` content otherwise; see `promote_to_global()`.
    """
    validate_entry(entry)
    target_slug = slug or entry.get("project") or detect_project_slug()
    if target_slug == GLOBAL_SLUG and not _is_global_admin():
        raise GlobalPromotionError(
            "writing to _global requires CCGM_LEARNINGS_ADMIN=1 (inline, never exported) "
            "or promote_to_global() from a reviewed, human-accepted proposal"
        )
    writer = agent_id()
    shard = agent_shard_path(target_slug, writer)
    ts = _next_writer_timestamp(shard)
    row = _build_op_row(
        op="add", target_id=None, project=target_slug, writer=writer, timestamp=ts,
        type_=entry["type"], source=entry.get("source", "observed"), content=entry["content"],
        confidence=entry["confidence"], tags=entry.get("tags", []), files=entry.get("files", []),
        key=entry.get("key"), source_session=entry.get("source_session"),
        event_id=entry["id"],
    )
    if entry.get("evidence_sessions"):
        row["evidence_sessions"] = list(entry["evidence_sessions"])
    file_locked_append(str(shard), json.dumps(row, sort_keys=True))
    entry["timestamp"] = ts
    entry["last_verified"] = ts
    entry["project"] = target_slug
    return shard


# ---------------------------------------------------------------------------
# Projection / fold engine (read path core)
# ---------------------------------------------------------------------------

def _read_jsonl_file(path: Path) -> list[dict[str, Any]]:
    """Read and parse every line of a JSONL file, skipping malformed lines."""
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def iter_entries(slug: str) -> Iterable[dict[str, Any]]:
    """Yield raw parsed rows from one project's LEGACY JSONL file only,
    skipping malformed lines. (Shard files are read separately by
    `_all_source_lines`; use `load_all()` for the full v2 projection.)"""
    path = project_jsonl(slug)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _all_source_lines(slug: str) -> list[dict[str, Any]]:
    """Union of every raw line for a slug: the legacy file + every agent shard."""
    lines: list[dict[str, Any]] = list(iter_entries(slug))
    for shard in list_agent_shards(slug):
        lines.extend(_read_jsonl_file(shard))
    return lines


def _dedupe_lines_by_id(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Op-events are deduped by `id` BEFORE folding (adrev-007/l3) so a
    duplicated physical line (e.g. from a future git union-merge) never
    double-applies a counter. First occurrence in the given order wins.

    Critically, this is dedup by EVENT id, never by content `key` -- a
    contradict/verify op carries no `key` of its own, so a content-keyed
    pre-fold dedup would risk colliding unrelated counter-ops and silently
    orphaning one of them before it ever reaches its target (the exact
    "pipeline-ordering trap" contradiction-before-dedup exists to avoid).
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ln in lines:
        _id = ln.get("id")
        if _id is not None:
            if _id in seen:
                continue
            seen.add(_id)
        out.append(ln)
    return out


def _fold_sort_key(line: dict[str, Any]) -> tuple[float, str]:
    return (_parse_iso(line.get("timestamp", "")), line.get("id") or "")


def _seed_head_from_add_event(event: dict[str, Any]) -> dict[str, Any]:
    """Phase A: materialize a fresh head from a v2 `add` op-event (adrev-007:
    v2 adds seed EMPTY counters, unlike legacy rows which seed verbatim)."""
    content = event.get("content") or ""
    type_ = event.get("type")
    return {
        "id": event["id"],
        "timestamp": event.get("timestamp"),
        "type": type_,
        "source": event.get("source") or "observed",
        "content": content,
        "confidence": event.get("confidence", DEFAULT_CONFIDENCE),
        "tags": list(event.get("tags") or []),
        "files": list(event.get("files") or []),
        "project": event.get("project"),
        "key": event.get("key") or _dedup_key(content, type_ or ""),
        "last_verified": event.get("timestamp"),
        "uses": 0,
        "contradictions": 0,
        "deprecated": False,
        "supersedes": None,
        "superseded_by": None,
        "supersede_reason": None,
        "writer": event.get("writer"),
        "source_session": event.get("source_session"),
    }


def _seed_head_from_supersede_event(event: dict[str, Any], old_head: dict[str, Any]) -> dict[str, Any]:
    """Phase B: a `supersede` op-event both mutates its target AND seeds a
    brand-new head -- it is the one non-`add` op that introduces a fresh id."""
    content = event.get("content") or ""
    type_ = event.get("type") or old_head.get("type")
    return {
        "id": event["id"],
        "timestamp": event.get("timestamp"),
        "type": type_,
        "source": event.get("source") or old_head.get("source") or "observed",
        "content": content,
        "confidence": event.get("confidence") if event.get("confidence") is not None
        else old_head.get("confidence", DEFAULT_CONFIDENCE),
        "tags": list(event.get("tags") or []),
        "files": list(event.get("files") or []),
        "project": event.get("project") or old_head.get("project"),
        "key": event.get("key") or _dedup_key(content, type_ or ""),
        "last_verified": event.get("timestamp"),
        "uses": 0,
        "contradictions": 0,
        "deprecated": False,
        "supersedes": event.get("target_id"),
        "superseded_by": None,
        "supersede_reason": event.get("supersede_reason"),
        "writer": event.get("writer"),
        "source_session": event.get("source_session"),
    }


def _apply_op(heads: dict[str, dict[str, Any]], op: dict[str, Any], target: dict[str, Any]) -> None:
    """Phase B: fold one non-`add` op-event onto its already-seeded target head."""
    kind = op.get("op")
    if kind == "verify":
        target["uses"] = int(target.get("uses", 0)) + 1
        target["last_verified"] = op.get("timestamp") or target.get("last_verified")
    elif kind == "contradict":
        target["contradictions"] = int(target.get("contradictions", 0)) + 1
    elif kind == "deprecate":
        target["deprecated"] = True
    elif kind == "supersede":
        new_id = op["id"]
        prior = target.get("superseded_by")
        if prior is not None and prior != new_id:
            # Conflict detection (adrev-010/adrev-011): two supersedes
            # targeting the same live row. Both new heads are retained;
            # the OLD head is flagged so a human (or the read path) knows
            # not to treat it as a settled single lineage.
            target["conflict"] = True
            chain = target.setdefault("conflicting_superseded_by", [])
            for cid in (prior, new_id):
                if cid not in chain:
                    chain.append(cid)
        target["superseded_by"] = new_id
        heads[new_id] = _seed_head_from_supersede_event(op, target)


def _fold(ordered: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Two-phase fold over an ALREADY deduped + total-ordered line list
    (adrev-008 total order, adrev-402 two-phase + deferral-until-fixpoint).

    Returns {"heads": [...], "orphan_ops": [...]}. Ops whose target never
    resolves land in orphan_ops -- never silently dropped.
    """
    heads: dict[str, dict[str, Any]] = {}
    for ln in ordered:
        op = ln.get("op")
        if op is None:
            heads[ln["id"]] = dict(ln)
        elif op == "add":
            heads[ln["id"]] = _seed_head_from_add_event(ln)

    pending = [ln for ln in ordered if ln.get("op") in ("verify", "contradict", "supersede", "deprecate")]
    progress = True
    while pending and progress:
        progress = False
        still_pending: list[dict[str, Any]] = []
        for op_ln in pending:
            target = heads.get(op_ln.get("target_id"))
            if target is None:
                still_pending.append(op_ln)
                continue
            _apply_op(heads, op_ln, target)
            progress = True
        pending = still_pending

    return {"heads": list(heads.values()), "orphan_ops": pending}


def _project_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Deterministic full projection from a raw line list: dedupe by id,
    impose total order by (timestamp, id) (adrev-008), then two-phase fold
    (adrev-402). Returns {"heads": [...], "orphan_ops": [...],
    "max_timestamp": "..."}.
    """
    deduped = _dedupe_lines_by_id(lines)
    ordered = sorted(deduped, key=_fold_sort_key)
    max_ts = ordered[-1].get("timestamp", "") if ordered else ""
    result = _fold(ordered)
    result["max_timestamp"] = max_ts
    return result


# ---------------------------------------------------------------------------
# Snapshot / materialization cache (arch-2, adrev-301)
# ---------------------------------------------------------------------------

def _cache_dir(slug: str) -> Path:
    return LEARNINGS_CACHE_ROOT / slug


def _snapshot_path(slug: str) -> Path:
    return _cache_dir(slug) / "snapshot.jsonl"


def _watermark_path(slug: str) -> Path:
    return _cache_dir(slug) / "watermark.json"


def _line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def _source_meta(path: Path) -> dict[str, int]:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {"lines": _line_count(path), "size": size}


def _read_new_lines(path: Path, from_line: int) -> list[dict[str, Any]]:
    """Parse only the lines at index >= from_line (0-based). Cheap for the
    common case: text-scans skipped lines but never json.loads()es them."""
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < from_line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write_snapshot(slug: str, result: dict[str, Any]) -> None:
    """
    Persist the projected state as a rebuildable, per-machine cache.

    Lives OUTSIDE ~/.claude/learnings/ entirely (LEARNINGS_CACHE_ROOT is a
    sibling directory), so it is structurally never a git-sync participant
    even before Epic 5's .gitignore exists (arch-2/adrev-301) -- no git
    operation is required or performed here.
    """
    cache_dir = _cache_dir(slug)
    cache_dir.mkdir(parents=True, exist_ok=True)

    snap_tmp = _snapshot_path(slug).with_suffix(".jsonl.tmp")
    with snap_tmp.open("w", encoding="utf-8") as f:
        for h in result["heads"]:
            f.write(json.dumps(h, sort_keys=True) + "\n")
    snap_tmp.replace(_snapshot_path(slug))

    sources: dict[str, dict[str, int]] = {}
    legacy = project_jsonl(slug)
    if legacy.is_file():
        sources[str(legacy)] = _source_meta(legacy)
    for shard in list_agent_shards(slug):
        sources[str(shard)] = _source_meta(shard)

    watermark = {
        "schema_version": 1,
        "sources": sources,
        "max_timestamp": result.get("max_timestamp", ""),
        "has_orphans": bool(result.get("orphan_ops")),
    }
    wm_tmp = _watermark_path(slug).with_suffix(".json.tmp")
    wm_tmp.write_text(json.dumps(watermark, sort_keys=True), encoding="utf-8")
    wm_tmp.replace(_watermark_path(slug))


def _read_watermark(slug: str) -> dict[str, Any] | None:
    path = _watermark_path(slug)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_snapshot_heads(slug: str) -> list[dict[str, Any]] | None:
    path = _snapshot_path(slug)
    if not path.is_file():
        return None
    try:
        return _read_jsonl_file(path)
    except OSError:
        return None


def _try_incremental_projection(slug: str) -> dict[str, Any] | None:
    """
    Fast path (arch-2): if a valid, orphan-free snapshot exists and every
    newly-appended line is chronologically >= the snapshot's watermark,
    fold ONLY the new lines onto the cached heads. Falls back to None
    (caller does a full rebuild) whenever that safety property cannot be
    proven -- correctness always wins over the cache.

    The common "nothing changed" case is O(number of source files): each
    source is skipped via a cheap stat()-based size comparison before any
    line is ever read, independent of total event count.
    """
    wm = _read_watermark(slug)
    if wm is None or wm.get("has_orphans"):
        return None
    heads_list = _read_snapshot_heads(slug)
    if heads_list is None:
        return None

    sources: dict[str, Any] = wm.get("sources", {})
    current_paths: list[Path] = []
    legacy = project_jsonl(slug)
    if legacy.is_file():
        current_paths.append(legacy)
    current_paths.extend(list_agent_shards(slug))

    new_lines: list[dict[str, Any]] = []
    for path in current_paths:
        meta = sources.get(str(path)) or {}
        prev_lines = int(meta.get("lines", 0))
        prev_size = int(meta.get("size", -1))
        try:
            cur_size = path.stat().st_size
        except OSError:
            cur_size = 0
        if cur_size == prev_size:
            continue
        new_lines.extend(_read_new_lines(path, prev_lines))

    if not new_lines:
        return {"heads": heads_list, "orphan_ops": [], "max_timestamp": wm.get("max_timestamp", "")}

    watermark_max = _parse_iso(wm.get("max_timestamp", ""))
    for ln in new_lines:
        if _parse_iso(ln.get("timestamp", "")) < watermark_max:
            # A new line sorts BEFORE the cached watermark -- e.g. a
            # delayed cross-writer op under clock skew. An incremental
            # merge here is not provably equivalent to a full replay
            # (it could apply out of true chronological order). Bail to
            # a full, always-correct rebuild.
            return None

    heads = {h["id"]: dict(h) for h in heads_list}
    new_lines = _dedupe_lines_by_id(new_lines)
    ordered_new = sorted(new_lines, key=_fold_sort_key)

    for ln in ordered_new:
        op = ln.get("op")
        if op is None:
            heads[ln["id"]] = dict(ln)
        elif op == "add":
            heads[ln["id"]] = _seed_head_from_add_event(ln)

    pending = [ln for ln in ordered_new if ln.get("op") in ("verify", "contradict", "supersede", "deprecate")]
    progress = True
    while pending and progress:
        progress = False
        still_pending: list[dict[str, Any]] = []
        for op_ln in pending:
            target = heads.get(op_ln.get("target_id"))
            if target is None:
                still_pending.append(op_ln)
                continue
            _apply_op(heads, op_ln, target)
            progress = True
        pending = still_pending

    new_max = ordered_new[-1].get("timestamp", "") if ordered_new else wm.get("max_timestamp", "")
    result = {"heads": list(heads.values()), "orphan_ops": pending, "max_timestamp": new_max}
    _write_snapshot(slug, result)
    return result


def project_slug(slug: str, *, use_snapshot: bool = True) -> dict[str, Any]:
    """
    Full v2 read-time projection for one project slug (§3.3): union of the
    legacy file + every agent shard, folded deterministically. Returns
    {"heads": [...], "orphan_ops": [...], "max_timestamp": "..."}.

    Uses the snapshot cache by default (arch-2) for read performance;
    pass use_snapshot=False to force a from-scratch replay (used by tests
    to assert the cached path agrees with a full replay).
    """
    if use_snapshot:
        cached = _try_incremental_projection(slug)
        if cached is not None:
            return cached
    result = _project_lines(_all_source_lines(slug))
    _write_snapshot(slug, result)
    return result


def snapshot(slug: str) -> dict[str, Any]:
    """Force a fresh full projection and (re)persist it as the cache."""
    return project_slug(slug, use_snapshot=False)


def get_orphan_ops(slug: str) -> list[dict[str, Any]]:
    """Op-events whose target_id never resolved to a head (never silently dropped)."""
    return list(project_slug(slug).get("orphan_ops", []))


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def load_all(slug: str) -> list[dict[str, Any]]:
    """Union-read + project a slug's legacy file and agent shards into the
    current set of chain heads (v2). Superseded/deprecated rows are still
    present here (filtering happens in `search()`, matching v1 behavior)."""
    return list(project_slug(slug)["heads"])


def list_project_slugs() -> list[str]:
    if not LEARNINGS_ROOT.is_dir():
        return []
    slugs: set[str] = set()
    for d in LEARNINGS_ROOT.iterdir():
        if not d.is_dir():
            continue
        if (d / "learnings.jsonl").is_file():
            slugs.add(d.name)
        elif (d / "agents").is_dir() and any((d / "agents").glob("*.jsonl")):
            slugs.add(d.name)
    return sorted(slugs)


# ---------------------------------------------------------------------------
# Confidence decay + staleness
# ---------------------------------------------------------------------------

def effective_confidence(
    entry: dict[str, Any],
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    now: float | None = None,
) -> float:
    """
    Compute time-decayed confidence for read-time ranking.

    Uses exponential decay with the given half-life, anchored on last_verified
    (falling back to timestamp). A `uses` counter slows decay; a
    `contradictions` counter accelerates it. Explicit `deprecated` zeroes out.
    """
    if entry.get("deprecated"):
        return 0.0
    base = float(entry.get("confidence", DEFAULT_CONFIDENCE))
    uses = int(entry.get("uses", 0))
    contra = int(entry.get("contradictions", 0))

    # Reuse slightly boosts; contradictions cut hard.
    base = base + min(uses * 0.25, 2.0) - (contra * 1.5)
    base = max(0.0, min(float(CONFIDENCE_MAX), base))

    ts = _parse_iso(entry.get("last_verified") or entry.get("timestamp", ""))
    if ts <= 0:
        return base

    now_ts = now if now is not None else time.time()
    age_days = max(0.0, (now_ts - ts) / 86400.0)
    if half_life_days <= 0:
        return base
    decay = math.pow(0.5, age_days / half_life_days)
    return base * decay


def is_stale(
    entry: dict[str, Any],
    *,
    stale_days: float = DEFAULT_STALE_DAYS,
    now: float | None = None,
) -> bool:
    ts = _parse_iso(entry.get("last_verified") or entry.get("timestamp", ""))
    if ts <= 0:
        return True
    now_ts = now if now is not None else time.time()
    return (now_ts - ts) / 86400.0 > stale_days


def has_stale_file_refs(entry: dict[str, Any], repo_root: Path | None = None) -> bool:
    """
    If entry lists files and a repo_root is provided, return True when any
    referenced file no longer exists. Used to flag entries whose anchor
    moved.
    """
    files = entry.get("files") or []
    if not files or repo_root is None:
        return False
    for rel in files:
        if not (repo_root / rel).exists():
            return True
    return False


# ---------------------------------------------------------------------------
# Dedup + ranking
# ---------------------------------------------------------------------------

def dedup_latest(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Within each (key, type), keep only the latest entry by timestamp.
    Preserves input order for stability within the selected set.

    Operates on PROJECTED HEADS only (never raw op-events) -- contradiction
    / verify counters are folded onto their targets BEFORE this ever runs
    (§3.3: contradiction-check before dedup), so a key collision can never
    silently discard a correction that hasn't yet been applied.
    """
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for e in entries:
        k = (e.get("key") or _dedup_key(e.get("content", ""), e.get("type", "")),
             e.get("type", ""))
        prev = latest.get(k)
        if prev is None or _parse_iso(e.get("timestamp", "")) > _parse_iso(prev.get("timestamp", "")):
            latest[k] = e
    # Restore original order: newest among each key
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for e in reversed(entries):
        k = (e.get("key") or _dedup_key(e.get("content", ""), e.get("type", "")),
             e.get("type", ""))
        if k in seen:
            continue
        out.append(latest[k])
        seen.add(k)
    out.reverse()
    return out


def score_relevance(entry: dict[str, Any], query: str, tags: list[str]) -> float:
    """
    Simple keyword + tag relevance score in [0, 1].
    Empty query returns a constant 0.5 so confidence alone orders results.
    """
    if not query and not tags:
        return 0.5

    content = entry.get("content", "").lower()
    entry_tags = {t.lower() for t in entry.get("tags", [])}
    entry_type = entry.get("type", "").lower()

    score = 0.0
    if query:
        q = query.lower().strip()
        terms = [t for t in re.split(r"\s+", q) if t]
        if terms:
            hits = sum(1 for t in terms if t in content or t in entry_tags or t == entry_type)
            score += hits / len(terms)

    if tags:
        want = {t.lower() for t in tags}
        if want:
            overlap = len(want & entry_tags) / len(want)
            score += overlap

    # Normalize into [0, 1]
    if query and tags:
        score /= 2.0
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Search (injection filter)
# ---------------------------------------------------------------------------

def search(
    *,
    query: str = "",
    tags: list[str] | None = None,
    types: list[str] | None = None,
    slug: str | None = None,
    cross_project: bool | None = None,
    max_results: int | None = None,
    token_budget: int | None = None,
    include_stale: bool = False,
    include_superseded: bool = False,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Return a ranked, filtered, token-capped list of learnings.

    The caller is expected to inject this into a command preamble or skill
    context. Results are already sanitized; deprecated, superseded, and
    stale-below-threshold entries are excluded by default.
    """
    cfg = config or load_config()
    half_life = float(cfg.get("half_life_days", DEFAULT_HALF_LIFE_DAYS))
    threshold = float(cfg.get("deprecate_threshold", DEFAULT_DEPRECATE_THRESHOLD))
    stale_days = float(cfg.get("stale_days", DEFAULT_STALE_DAYS))
    budget = int(token_budget if token_budget is not None else cfg.get("token_budget", DEFAULT_TOKEN_BUDGET))
    cap = int(max_results if max_results is not None else cfg.get("max_results", DEFAULT_MAX_RESULTS))
    allow_cross = bool(cross_project if cross_project is not None else cfg.get("cross_project_search", False))

    tags = tags or []
    types = types or []

    slugs: list[str] = []
    if slug:
        slugs.append(slug)
    else:
        slugs.append(detect_project_slug())
    if allow_cross:
        for s in list_project_slugs():
            if s not in slugs:
                slugs.append(s)

    now = time.time()
    pool: list[dict[str, Any]] = []
    for s in slugs:
        pool.extend(load_all(s))

    if types:
        wanted = set(types)
        pool = [e for e in pool if e.get("type") in wanted]

    if not include_superseded:
        pool = [e for e in pool if not e.get("superseded_by")]

    pool = dedup_latest(pool)

    scored: list[tuple[float, dict[str, Any]]] = []
    for e in pool:
        eff = effective_confidence(e, half_life_days=half_life, now=now)
        if eff < threshold:
            continue
        if not include_stale and is_stale(e, stale_days=stale_days, now=now):
            continue
        rel = score_relevance(e, query, tags)
        # Rank: effective confidence (0-10) weighted with relevance (0-1)
        rank = eff * (0.5 + rel)
        scored.append((rank, e))

    scored.sort(key=lambda row: row[0], reverse=True)

    # Apply token budget (character approximation: 4 chars ~ 1 token)
    out: list[dict[str, Any]] = []
    char_budget = budget * 4
    used = 0
    for _, e in scored:
        snippet_len = len(e.get("content", "")) + 80  # overhead for tags/type
        if used + snippet_len > char_budget:
            break
        out.append(e)
        used += snippet_len
        if len(out) >= cap:
            break

    return out


# ---------------------------------------------------------------------------
# Session / transcript resolution (origin binding, sec-1)
# ---------------------------------------------------------------------------

def resolve_session_transcript(session_id: str | None) -> dict[str, Any] | None:
    """
    Resolve a Claude Code session id to a real, on-disk transcript file.

    Transcripts live at ~/.claude/projects/<cwd-slug>/<session-id>.jsonl --
    a DIFFERENT slug space than the learnings-store project slug (arch-1).
    Returns {"path": Path, "cwd": str|None} on a match; None if the session
    does not resolve to a real transcript anywhere under
    CLAUDE_PROJECTS_ROOT. sec-1: caller-supplied session strings must never
    be trusted for provenance without this check.
    """
    if not session_id or not re.fullmatch(r"[A-Za-z0-9\-]{1,128}", session_id):
        return None
    if not CLAUDE_PROJECTS_ROOT.is_dir():
        return None
    matches = sorted(CLAUDE_PROJECTS_ROOT.glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None
    path = matches[0]
    return {"path": path, "cwd": _extract_transcript_cwd(path)}


def _extract_transcript_cwd(path: Path, *, max_lines: int = 2000) -> str | None:
    """Scan a transcript's leading lines for the recorded `cwd` field."""
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = obj.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def _chain_sessions(by_id: dict[str, dict[str, Any]], start_id: str) -> set[str]:
    """Walk a supersede chain backward from `start_id`, collecting every
    `source_session` recorded along the way."""
    seen: set[str] = set()
    sessions: set[str] = set()
    cur_id: str | None = start_id
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        cur = by_id.get(cur_id)
        if cur is None:
            break
        s = cur.get("source_session")
        if s:
            sessions.add(s)
        cur_id = cur.get("supersedes")
    return sessions


def _enforce_origin_binding(
    by_id: dict[str, dict[str, Any]],
    old_id: str,
    *,
    new_source: str,
    session_id: str | None,
) -> None:
    """
    §3.3 write rules: a supersede may never RAISE the source tier (e.g.
    inferred -> user-stated) unless the new event carries a session id
    that (a) is not already present anywhere in the chain, AND (b)
    resolves to a real, on-disk transcript file. Non-raises are always
    allowed with no session required.
    """
    old = by_id.get(old_id)
    if old is None:
        return
    old_rank = SOURCE_TIER_RANK.get(old.get("source", "observed"), 0)
    new_rank = SOURCE_TIER_RANK.get(new_source, 0)
    if new_rank <= old_rank:
        return

    if not session_id:
        raise OriginBindingError(
            f"cannot raise source tier {old.get('source')!r} -> {new_source!r} "
            "without --session resolving to a real transcript"
        )
    prior_sessions = _chain_sessions(by_id, old_id)
    if session_id in prior_sessions:
        raise OriginBindingError(
            "source_session already present earlier in this supersede chain; "
            "a tier raise requires a NEW, distinct session"
        )
    info = resolve_session_transcript(session_id)
    if info is None:
        raise OriginBindingError(
            f"session {session_id!r} does not resolve to a real transcript "
            f"under {CLAUDE_PROJECTS_ROOT}/**"
        )


# ---------------------------------------------------------------------------
# Update helpers (verify / contradict / deprecate)
# ---------------------------------------------------------------------------

def update_entry_by_id(
    entry_id: str,
    *,
    slug: str | None = None,
    verify: bool = False,
    contradict: bool = False,
    deprecate: bool = False,
    expected_sha256: str | None = None,
    source_session: str | None = None,
) -> bool:
    """
    Mutate a chain head by appending verify/contradict/deprecate op-event(s)
    to the writer's own shard (v2 -- no more in-place JSONL rewrites).

    Returns True if `entry_id` currently resolves to a live head; False if
    not found (nothing is written). `deprecate` honors CAS when
    `expected_sha256` is given (raises CASConflictError on mismatch).
    """
    target_slug = slug or detect_project_slug()
    heads = load_all(target_slug)
    target = next((h for h in heads if h.get("id") == entry_id), None)
    if target is None:
        return False

    if deprecate and expected_sha256 is not None:
        current_sha = content_sha256(target.get("content"))
        if current_sha != expected_sha256:
            raise CASConflictError(current_sha)

    kinds: list[str] = []
    if verify:
        kinds.append("verify")
    if contradict:
        kinds.append("contradict")
    if deprecate:
        kinds.append("deprecate")
    if not kinds:
        return True

    target_proj = target.get("project") or target_slug
    writer = agent_id()
    shard = agent_shard_path(target_proj, writer)
    for kind in kinds:
        ts = _next_writer_timestamp(shard)
        row = _build_op_row(
            op=kind, target_id=entry_id, project=target_proj, writer=writer, timestamp=ts,
            source_session=source_session,
            expected_sha256=expected_sha256 if kind == "deprecate" else None,
        )
        file_locked_append(str(shard), json.dumps(row, sort_keys=True))
    return True


# ---------------------------------------------------------------------------
# Supersede (atomic replace with linked chain)
# ---------------------------------------------------------------------------

def supersede_entry(
    old_id: str,
    *,
    content: str,
    type_: str | None = None,
    source: str = "observed",
    confidence: int | None = None,
    tags: list[str] | None = None,
    files: list[str] | None = None,
    slug: str | None = None,
    reason: str | None = None,
    expected_sha256: str | None = None,
    source_session: str | None = None,
) -> dict[str, Any] | None:
    """
    Atomically replace one entry with a new one by appending a single
    `supersede` op-event (v2): folding it both marks the old head
    `superseded_by` and seeds the new head in one deterministic step.

    Missing `type_` / `confidence` / `tags` / `files` are inherited from
    the old entry so a bare `supersede_entry(old_id, content=...)` call
    does the right thing for the common "same idea, updated wording" case.

    Honors CAS (`expected_sha256` -- raises CASConflictError on mismatch,
    carrying the target's actual current sha) and origin binding (raises
    OriginBindingError if `source` would raise the tier without a fresh,
    transcript-verified `source_session`, §3.3). Returns the new entry
    dict, or None if `old_id` was not found.
    """
    target_slug = slug or detect_project_slug()
    heads = load_all(target_slug)
    by_id = {h["id"]: h for h in heads}
    old = by_id.get(old_id)
    if old is None:
        return None

    if expected_sha256 is not None:
        current_sha = content_sha256(old.get("content"))
        if current_sha != expected_sha256:
            raise CASConflictError(current_sha)

    _enforce_origin_binding(by_id, old_id, new_source=source, session_id=source_session)

    inherited_type = type_ or old.get("type")
    inherited_conf = confidence if confidence is not None else old.get("confidence", DEFAULT_CONFIDENCE)
    inherited_tags = tags if tags is not None else list(old.get("tags", []))
    inherited_files = files if files is not None else list(old.get("files", []))
    target_proj = old.get("project") or target_slug

    if target_proj == GLOBAL_SLUG and not _is_global_admin():
        raise GlobalPromotionError(
            "superseding a _global entry requires CCGM_LEARNINGS_ADMIN=1 (inline, never exported) "
            "or promote_to_global() from a reviewed, human-accepted proposal"
        )

    new_entry = build_entry(
        type_=inherited_type, content=content, source=source, confidence=inherited_conf,
        tags=inherited_tags, files=inherited_files, project=target_proj,
        supersedes=old_id, supersede_reason=reason,
    )

    writer = agent_id()
    shard = agent_shard_path(target_proj, writer)
    ts = _next_writer_timestamp(shard)
    row = _build_op_row(
        op="supersede", target_id=old_id, project=target_proj, writer=writer, timestamp=ts,
        type_=new_entry["type"], source=new_entry["source"], content=new_entry["content"],
        confidence=new_entry["confidence"], tags=new_entry["tags"], files=new_entry["files"],
        key=new_entry["key"], source_session=source_session,
        supersede_reason=new_entry["supersede_reason"], event_id=new_entry["id"],
    )
    file_locked_append(str(shard), json.dumps(row, sort_keys=True))

    new_entry["timestamp"] = ts
    new_entry["last_verified"] = ts
    new_entry["writer"] = writer
    new_entry["source_session"] = source_session
    return new_entry


# ---------------------------------------------------------------------------
# Global promotion (structural privileged write path, §3.3 adrev-405)
# ---------------------------------------------------------------------------

def promote_to_global(
    entry: dict[str, Any],
    *,
    evidence_sessions: list[str],
    reviewed_by: str,
) -> dict[str, Any]:
    """
    Structural, privileged write path for `_global` scope (§3.3 adrev-405
    net contract) -- the ONE legitimate way to land a `_global` add outside
    the manual CCGM_LEARNINGS_ADMIN terminal hatch. Intended caller: a
    future dreaming apply path, invoked only after a recorded human accept.

    Does NOT check CCGM_LEARNINGS_ADMIN (this function IS the privileged
    path) and does NOT enforce a breadth minimum on evidence_sessions --
    the recorded human accept (`reviewed_by`) is the authority; prevalence
    is informational only. `writer` is derived from the FIRST evidence
    session that resolves to a real, on-disk transcript's recorded `cwd`
    -- never from CCGM_AGENT_ID. Raises GlobalPromotionError if
    evidence_sessions is empty or none resolve to a real transcript.
    """
    if not evidence_sessions:
        raise GlobalPromotionError("promote_to_global requires at least one evidence session")

    resolved_cwd: str | None = None
    resolved_session: str | None = None
    for sid in evidence_sessions:
        info = resolve_session_transcript(sid)
        if info and info.get("cwd"):
            resolved_cwd = info["cwd"]
            resolved_session = sid
            break
    if resolved_cwd is None:
        raise GlobalPromotionError(
            "no cited evidence_sessions resolve to a real transcript file under "
            f"{CLAUDE_PROJECTS_ROOT}/**"
        )

    writer = agent_id(resolved_cwd)

    new_entry = build_entry(
        type_=entry.get("type"),
        content=entry.get("content", ""),
        source=entry.get("source", "observed"),
        confidence=entry.get("confidence", DEFAULT_CONFIDENCE),
        tags=entry.get("tags") or [],
        files=entry.get("files") or [],
        project=GLOBAL_SLUG,
        key=entry.get("key"),
    )

    shard = agent_shard_path(GLOBAL_SLUG, writer)
    ts = _next_writer_timestamp(shard)
    row = _build_op_row(
        op="add", target_id=None, project=GLOBAL_SLUG, writer=writer, timestamp=ts,
        type_=new_entry["type"], source=new_entry["source"], content=new_entry["content"],
        confidence=new_entry["confidence"], tags=new_entry["tags"], files=new_entry["files"],
        key=new_entry["key"], source_session=resolved_session, event_id=new_entry["id"],
    )
    row["reviewed_by"] = reviewed_by
    row["evidence_sessions"] = list(evidence_sessions)
    file_locked_append(str(shard), json.dumps(row, sort_keys=True))

    new_entry["timestamp"] = ts
    new_entry["last_verified"] = ts
    new_entry["writer"] = writer
    new_entry["source_session"] = resolved_session
    return new_entry


# ---------------------------------------------------------------------------
# Compaction guard (reject lossy rewrites)
# ---------------------------------------------------------------------------

# Fact-bearing tokens: identifiers, proper nouns, quoted strings, dates,
# version numbers, acronyms. The regex is intentionally conservative - false
# positives just mean the guard complains about a rewrite that didn't
# actually lose meaning, which fails safe.
_FACT_TOKEN_RE = re.compile(
    r"""
    (?P<ident>   [A-Za-z][A-Za-z0-9]*(?:[_.\-][A-Za-z0-9]+)+ )   # foo_bar, Foo.Bar, foo-bar
  | (?P<proper> \b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+\b )       # Proper Noun Phrases (handles McComb, iPhone-free)
  | (?P<quoted> "[^"\n]{2,}" | '[^'\n]{2,}' )                    # "quoted" or 'quoted'
  | (?P<date>   \b\d{4}(?:-\d{2}(?:-\d{2})?)?\b )                # 2026 or 2026-04-23
  | (?P<ver>    \b\d+(?:\.\d+){1,}\b )                           # 1.2.3
  | (?P<acr>    \b[A-Z]{2,}\b )                                  # ACRONYMS
    """,
    re.VERBOSE,
)


def _extract_fact_tokens(text: str) -> set[str]:
    """Extract the set of fact-bearing tokens from a block of prose."""
    return {m.group(0) for m in _FACT_TOKEN_RE.finditer(text or "")}


def compact_preserves_facts(
    old_text: str,
    new_text: str,
    *,
    threshold: float = 0.05,
) -> tuple[bool, list[str]]:
    """
    Check that a rewrite preserves the bulk of fact-bearing tokens.

    Extracts identifiers, proper nouns, quoted strings, dates, version
    numbers, and acronyms from both texts. Returns `(ok, dropped)` where
    `ok` is True if at most `threshold` of unique old tokens are missing
    from the new text. `dropped` is the sorted list of tokens lost.

    Use to guard against lossy model-driven compaction: if the check fails,
    do not commit the rewrite - flag for human review.
    """
    old_tokens = _extract_fact_tokens(old_text)
    if not old_tokens:
        return True, []
    new_tokens = _extract_fact_tokens(new_text)
    dropped = sorted(old_tokens - new_tokens)
    loss = len(dropped) / len(old_tokens)
    return loss <= threshold, dropped
