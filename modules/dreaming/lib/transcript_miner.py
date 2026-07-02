#!/usr/bin/env python3
"""Deterministic session-transcript miner for the CCGM `dreaming` module.

Turns Claude Code session-transcript JSONLs into a bounded, redacted,
PII-scrubbed, clustered "evidence bundle" -- the frozen input contract
Epic 3's map/reduce analyzer consumes (see lib/evidence-bundle-schema.json).
No network calls, no LLM calls, no scheduling live here: this file is pure,
deterministic Python stdlib (plan.md §5 Epic 2 scope; the
latent-vs-deterministic rule -- mining is mechanical extraction, not
judgment, so it stays out of latent space entirely).

Pipeline: discover() -> mine() -> cluster() -> budget() -> evidence bundle.
`mine_to_evidence_bundle()` wires the last three stages together and is
the function both `--self-check` and Epic 3 are expected to call.

Locked API (Epic 3 depends on these signatures):
    discover(slugs, since_watermark=None, *, projects_root=None) -> list[str]
    mine(path) -> dict                       # MinedSession
    cluster(events) -> list[dict]            # list[Cluster]
    budget(clusters, max_input_tokens) -> dict
    schema_canary(mined_sessions) -> dict    # raises SchemaDriftError on drift
    mine_to_evidence_bundle(paths, *, max_input_tokens=200_000) -> dict
    read_watermark() / write_watermark(slug, iso_timestamp)
    redact_pii(text) -> str
    make_excerpt(text) -> str
    validate_against_schema(instance, schema) -> list[str]

Slug identity (arch-1, CRITICAL): the owning learnings-store slug for
every transcript is re-derived from the transcript's own `cwd` field via
learnings_store.detect_project_slug() -- NEVER via
session-history/repo_detect.py, which computes a DIFFERENT string for the
same repo (a bare repo-directory name vs the canonical `owner-repo` form
derived from the git remote, empirically verified to diverge in plan.md).
session-history's discover-sessions.sh/repo_detect.py are never imported
or consulted here; this file resolves identity fresh, per transcript,
from content -- not from a project-directory name.
"""
from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Cross-module imports (hooks.hook_utils, self-improving.learnings_store)
# ---------------------------------------------------------------------------


def _import_sibling_module(dep_module: str, module_name: str, purpose: str):
    """Import a single-file sibling-module dependency.

    Primary path mirrors autoheal's installed-path convention
    (`sys.path.insert(0, ~/.claude/lib)` then `import <name>`,
    see modules/autoheal/hooks/permission-event-logger.py and
    modules/autoheal/lib/apply-proposal.py) -- this is also what actually
    happens at real runtime: dreaming's module.json declares a hard
    dependency on `dep_module`, so once both are installed via
    `start.sh --add`, `~/.claude/lib/<module_name>.py` is a symlink into
    THIS SAME repo checkout (start.sh symlinks from the canonical clone),
    so "installed" and "repo-relative" resolve to the identical file.

    Falls back to the repo-relative sibling path
    (modules/<dep_module>/lib/<module_name>.py, mirroring
    apply-proposal.py's own "fall back when the hooks module is not
    installed" precedent) so `python3 -m pytest modules/dreaming/tests/`
    and `--self-check` run cleanly on a fresh checkout that has never been
    through `start.sh --add`.

    Never silently degrades: redaction and slug-identity are
    safety/correctness-critical (sec-6, arch-1), so a failure to import
    either path raises rather than falling back to a weaker stand-in.
    """
    installed_lib = os.path.expanduser("~/.claude/lib")
    if installed_lib not in sys.path:
        sys.path.insert(0, installed_lib)
    try:
        return importlib.import_module(module_name)
    except ImportError:
        pass

    repo_modules_dir = Path(__file__).resolve().parents[2]
    sibling_lib = str(repo_modules_dir / dep_module / "lib")
    if sibling_lib not in sys.path:
        sys.path.insert(0, sibling_lib)
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ImportError(
            f"transcript_miner: cannot import '{module_name}' (needed for "
            f"{purpose}) from ~/.claude/lib or {sibling_lib}. Is the "
            f"'{dep_module}' module installed? (bash start.sh --add {dep_module})"
        ) from exc


_hook_utils = _import_sibling_module(
    "hooks", "hook_utils", "secret redaction (redact_secrets)"
)
_learnings_store = _import_sibling_module(
    "self-improving", "learnings_store", "canonical slug resolution (detect_project_slug)"
)

redact_secrets = _hook_utils.redact_secrets
detect_project_slug = _learnings_store.detect_project_slug


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SchemaDriftError(RuntimeError):
    """Raised by schema_canary() when the transcript schema appears to
    have drifted (recognized friction fields are structurally absent
    despite tool_use activity being present). See schema_canary()."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCERPT_MAX_CHARS = 400
MAX_EXEMPLARS_PER_CLUSTER = 3
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_INPUT_TOKENS = 200_000

# Peek at most this many lines when resolving a transcript's owning slug
# in discover() -- the cwd field is present on essentially every message
# line (research-inputs/agent-d-claude-code.md §3), so this is generous
# headroom, not a tight budget.
_PEEK_LINE_LIMIT = 50

# Fixed list of negation/correction phrases for the user-correction
# heuristic (Epic 2 spec: "user message within 2 turns of a failed tool
# call containing negation phrases from a fixed list"). Deterministic,
# case-insensitive substring matching -- a mechanical check, not a model
# judgment call (latent-vs-deterministic rule).
NEGATION_PHRASES = (
    "no,",
    "no wait",
    "not that",
    "not what i",
    "that's not",
    "that isn't",
    "that is not",
    "don't do that",
    "do not do that",
    "revert that",
    "undo that",
    "that's wrong",
    "that is wrong",
    "incorrect",
    "stop doing that",
    "please don't",
    "please do not",
    "actually no",
    "you broke",
    "that broke",
    "wrong approach",
    "not correct",
)

# Transcript `version` values the miner has been validated against.
# schema_canary() WARNS (does not fail) on an unrecognized version -- the
# transcript format is internal/undocumented and known to drift across
# Claude Code releases (adrev-002; live-verified version at plan-authoring
# time was 2.1.198, plan.md §5 Epic 2).
TESTED_TRANSCRIPT_VERSIONS = {"2.1.198"}


# ---------------------------------------------------------------------------
# PII redaction (companion to hook_utils.redact_secrets -- sec-6)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# US-style phone numbers: (555) 123-4567, 555-123-4567, 555.123.4567,
# +1 555 123 4567. Requires phone-shaped separators (not a bare 10-digit
# run, which collides with commit SHAs / ids) -- conservative-by-overfiring,
# same posture hook_utils.redact_secrets documents for its own patterns.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)"
)

# Coarse US street-address pattern: a leading house number, 1-4
# capitalized words, and a recognized street-type suffix. Not exhaustive
# (no PO boxes, no international shapes) -- deliberately conservative-by-
# overfiring, matching the same posture as the phone/secret patterns.
_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][a-zA-Z']*\s+){1,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|"
    r"Court|Ct|Place|Pl|Way|Circle|Cir|Terrace|Ter|Highway|Hwy)\b\.?"
)


def redact_pii(text: str) -> str:
    """Redact email/phone/address-shaped PII from `text`.

    Companion to hook_utils.redact_secrets(), which covers 17 SECRET
    token shapes but zero generic PII (sec-6). Transcripts are prose that
    routinely carries the operator's own PII; unlike secrets this is not
    a single canonical token shape, so the patterns below match
    tests/test-no-personal-data.sh's own bar (its SECRET_PATTERN already
    treats any email shape as PII) and extend it to phone/address, per
    the Epic 2 spec.

    Cheap substring pre-checks guard each pattern against catastrophic
    backtracking on large text with no plausible match: _EMAIL_RE's
    greedy local-part class immediately followed by a literal "@" that
    may not exist anywhere in the text is the textbook O(n^2)
    backtracking shape, and this function runs on FULL, untruncated
    transcript text by design (make_excerpt() redacts before
    truncating). Skipping a pattern entirely when its cheap precondition
    ("@" present / a digit present) is absent keeps every pattern
    linear-time on the common case without weakening what any pattern
    matches -- the same substitutions still run, in the same order, for
    any text that could plausibly contain a match.
    """
    if not text:
        return text
    out = text
    if any(ch.isdigit() for ch in text):
        out = _ADDRESS_RE.sub("[REDACTED:address]", out)
        out = _PHONE_RE.sub("[REDACTED:phone]", out)
    if "@" in text:
        out = _EMAIL_RE.sub("[REDACTED:email]", out)
    return out


def _redact(text: str) -> str:
    """Run the redact_secrets -> redact_pii chain make_excerpt() uses,
    without the truncation step.

    Shared by normalize_command_prefix() and the tool_name capture in
    mine() -- command_prefix and tool_name are raw transcript text same
    as any excerpt, and are required/always-populated fields in the
    evidence bundle, so they need the identical redaction guarantee
    make_excerpt() already gives every excerpt field (sec-6).
    """
    if not text:
        return text
    return redact_pii(redact_secrets(text))


def make_excerpt(text: str) -> str:
    """Redact secrets + PII, then truncate to EXCERPT_MAX_CHARS.

    Redaction MUST happen before truncation (hook_utils.redact_secrets'
    own documented contract) so the truncation boundary can never lop a
    redaction marker -- or a partial secret/PII fragment -- in half.
    Guarantees len(result) <= EXCERPT_MAX_CHARS.
    """
    redacted = redact_secrets(text or "")
    redacted = redact_pii(redacted)
    if len(redacted) <= EXCERPT_MAX_CHARS:
        return redacted
    return redacted[: EXCERPT_MAX_CHARS - 3].rstrip() + "..."


def _text_from_content(content: Any) -> str:
    """Extract human-readable text from a message `content` field.

    Message content is either a plain string or a list of typed content
    blocks. Only "text"-typed blocks (and a tool_result block's own
    nested `content`) contribute text; other block types (tool_use, etc.)
    carry no prose to redact/search and are skipped.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif btype == "tool_result":
                parts.append(_text_from_content(block.get("content")))
        return "\n".join(p for p in parts if p)
    return ""


def normalize_command_prefix(command: str, max_len: int = 80) -> str:
    """Normalize a shell command to a stable clustering key.

    Redacts secrets/PII (via _redact(), the same redact_secrets ->
    redact_pii chain make_excerpt() uses) BEFORE collapsing whitespace
    and truncating. command_prefix is raw, untrusted transcript text --
    it routinely carries tokens and PII (curl -H "Authorization: Bearer
    ghp_...", "psql postgres://user:pass@host/db", "mail -s hi
    user@example.com") and is a required, always-populated field in the
    evidence bundle schema, so it needs the same redaction guarantee
    every excerpt field already gets. Redacting first (not after
    truncating) mirrors make_excerpt()'s own ordering contract, so
    max_len can never lop a redaction marker -- or worse, a raw secret
    fragment -- in half.

    Collapses whitespace and truncates to `max_len` chars -- mirrors
    autoheal's own clustering signature (`(tool_name, cmd[:80])`, see
    modules/autoheal/bin/autoheal-analyze.sh `signature()`) so the two
    pipelines produce comparably-shaped cluster keys.
    """
    if not isinstance(command, str):
        return ""
    redacted = _redact(command)
    return re.sub(r"\s+", " ", redacted.strip())[:max_len]


def _bash_exit_code(
    line_obj: dict[str, Any], tool_result_block: dict[str, Any], tool_info: dict[str, Any]
) -> int | None:
    """Best-effort non-zero-exit-code detection for Bash tool results.

    The transcript format is internal/undocumented; exit-code metadata is
    not consistently named across observed shapes (`toolUseResult` appears
    as a top-level sibling key on some lines --
    research-inputs/agent-d-claude-code.md §3). This checks the
    `toolUseResult` object (if present, either on the line itself or
    nested in the tool_result block's own `content`) for a plausible
    `exit_code`/`exitCode` integer, returned ONLY when the associated tool
    was Bash. Returns None when no exit-code signal is present -- that is
    NOT friction by itself, just "no additional signal beyond is_error".
    """
    if tool_info.get("name") != "Bash":
        return None
    candidates = []
    tur = line_obj.get("toolUseResult")
    if isinstance(tur, dict):
        candidates.append(tur)
    content = tool_result_block.get("content")
    if isinstance(content, dict):
        candidates.append(content)
    for candidate in candidates:
        for key in ("exit_code", "exitCode"):
            v = candidate.get(key)
            if isinstance(v, int):
                return v
    return None


# ---------------------------------------------------------------------------
# JSONL line iteration
# ---------------------------------------------------------------------------


def _iter_jsonl(path: str | Path):
    """Yield (line_number, parsed_dict_or_None) for every non-blank line.

    None means the line was present but failed to parse as a JSON object
    (malformed JSON, or valid JSON that is not a dict). Callers count
    these and skip them -- never crash on a corrupt transcript.
    """
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                yield lineno, None
                continue
            if not isinstance(obj, dict):
                yield lineno, None
                continue
            yield lineno, obj


# ---------------------------------------------------------------------------
# mine() -- the core extraction pass
# ---------------------------------------------------------------------------


def mine(path: str | Path) -> dict[str, Any]:
    """Mine one session-transcript JSONL into a MinedSession dict.

    Deterministic, forward-only. Extracts:
      - friction events: tool_result.is_error, non-zero Bash exit codes,
        system-line hookErrors, system-line preventedContinuation
      - user-correction events: a user turn within 2 turns of a friction
        event whose text contains a NEGATION_PHRASES match
      - pr-link rows
      - per-session token totals + cache-read ratio
      - gitBranch / cwd / sessionId / start+end timestamps
      - the resolved learnings-store slug (arch-1: via
        learnings_store.detect_project_slug(cwd), never repo_detect.py)

    Every excerpt is passed through make_excerpt() (redact_secrets +
    redact_pii, then truncated) BEFORE being stored on the returned dict --
    no raw transcript text survives past this function.

    Turn-indexing: a "turn" is any line whose type is "assistant" or
    "user" (system/pr-link/other line types do not advance the turn
    counter). Friction events are tagged with the turn_index of the turn
    line they were observed on (or the most recent preceding turn's
    index, for system-line friction). The correction heuristic then looks
    BACKWARD from each user turn up to 2 turn-positions for a friction
    event -- a fixed, cheap, two-pass design (collect friction with
    turn_index, then scan user turns) rather than a streaming pending-
    queue, so "within 2 turns" is unambiguous and easy to test.
    """
    path = Path(path)

    lines: list[tuple[int, dict[str, Any]]] = []
    malformed_line_count = 0
    for lineno, obj in _iter_jsonl(path):
        if obj is None:
            malformed_line_count += 1
            continue
        lines.append((lineno, obj))

    session_id: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    transcript_version: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    tool_use_count = 0
    friction_field_presence = 0
    pr_links: list[dict[str, Any]] = []
    token_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    # tool_use_id -> {"name": ..., "command_prefix": ...}
    tool_uses: dict[str, dict[str, Any]] = {}

    turn_sequence: list[dict[str, Any]] = []
    friction_events: list[dict[str, Any]] = []

    for lineno, obj in lines:
        line_type = obj.get("type")

        if session_id is None and isinstance(obj.get("sessionId"), str):
            session_id = obj["sessionId"]
        if cwd is None and isinstance(obj.get("cwd"), str):
            cwd = obj["cwd"]
        if git_branch is None and isinstance(obj.get("gitBranch"), str):
            git_branch = obj["gitBranch"]
        if transcript_version is None and isinstance(obj.get("version"), str):
            transcript_version = obj["version"]
        ts = obj.get("timestamp") if isinstance(obj.get("timestamp"), str) else None
        if ts:
            if started_at is None or ts < started_at:
                started_at = ts
            if ended_at is None or ts > ended_at:
                ended_at = ts

        if line_type == "pr-link":
            pr_links.append(
                {
                    "pr_number": obj.get("prNumber"),
                    "pr_repository": obj.get("prRepository"),
                    "pr_url": obj.get("prUrl"),
                }
            )

        elif line_type == "assistant":
            turn_index = len(turn_sequence)
            turn_sequence.append(
                {"turn_index": turn_index, "role": "assistant", "lineno": lineno, "text": "", "timestamp": ts}
            )
            message = obj.get("message") or {}
            usage = message.get("usage") or {}
            for key in token_totals:
                v = usage.get(key)
                if isinstance(v, (int, float)):
                    token_totals[key] += int(v)
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    tool_use_count += 1
                    tu_id = block.get("id")
                    name = block.get("name")
                    tinput = block.get("input") or {}
                    command_prefix = None
                    if name == "Bash" and isinstance(tinput, dict):
                        command_prefix = normalize_command_prefix(tinput.get("command", ""))
                    if isinstance(tu_id, str):
                        tool_uses[tu_id] = {
                            # Defensive: tool_name is drawn from a small
                            # fixed vocabulary in practice but is never
                            # validated against an enum, so it gets the
                            # same redaction guarantee as command_prefix.
                            "name": _redact(name) if isinstance(name, str) else name,
                            "command_prefix": command_prefix,
                        }

        elif line_type == "user":
            turn_index = len(turn_sequence)
            message = obj.get("message") or {}
            content = message.get("content")
            user_text = _text_from_content(content)
            turn_sequence.append(
                {"turn_index": turn_index, "role": "user", "lineno": lineno, "text": user_text, "timestamp": ts}
            )

            if isinstance(obj.get("toolUseResult"), dict):
                friction_field_presence += 1

            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    if "is_error" in block:
                        friction_field_presence += 1
                    tu_id = block.get("tool_use_id")
                    tool_info = tool_uses.get(tu_id, {}) if isinstance(tu_id, str) else {}
                    is_error = bool(block.get("is_error"))
                    exit_code = _bash_exit_code(obj, block, tool_info)
                    if is_error or (exit_code not in (None, 0)):
                        friction_events.append(
                            {
                                "kind": "tool_error",
                                "tool_name": tool_info.get("name"),
                                "command_prefix": tool_info.get("command_prefix"),
                                "excerpt": make_excerpt(_text_from_content(block.get("content"))),
                                "timestamp": ts,
                                "session_id": session_id,
                                "line": lineno,
                                "turn_index": turn_index,
                            }
                        )

        elif line_type == "system":
            turn_index = turn_sequence[-1]["turn_index"] if turn_sequence else -1
            hook_errors = obj.get("hookErrors")
            if "hookErrors" in obj:
                friction_field_presence += 1
            if isinstance(hook_errors, list) and hook_errors:
                friction_events.append(
                    {
                        "kind": "hook_error",
                        "tool_name": None,
                        "command_prefix": None,
                        "excerpt": make_excerpt(json.dumps(hook_errors, ensure_ascii=False)),
                        "timestamp": ts,
                        "session_id": session_id,
                        "line": lineno,
                        "turn_index": turn_index,
                    }
                )
            if "preventedContinuation" in obj:
                friction_field_presence += 1
            if obj.get("preventedContinuation"):
                friction_events.append(
                    {
                        "kind": "prevented_continuation",
                        "tool_name": None,
                        "command_prefix": None,
                        "excerpt": make_excerpt(str(obj.get("stopReason") or "prevented continuation")),
                        "timestamp": ts,
                        "session_id": session_id,
                        "line": lineno,
                        "turn_index": turn_index,
                    }
                )

    user_corrections: list[dict[str, Any]] = []
    for turn in turn_sequence:
        if turn["role"] != "user":
            continue
        lowered = turn["text"].lower()
        if not any(phrase in lowered for phrase in NEGATION_PHRASES):
            continue
        best: tuple[int, dict[str, Any]] | None = None
        for event in friction_events:
            distance = turn["turn_index"] - event["turn_index"]
            if 0 <= distance <= 2 and (best is None or distance < best[0]):
                best = (distance, event)
        if best is not None:
            distance, event = best
            user_corrections.append(
                {
                    "excerpt": make_excerpt(turn["text"]),
                    "timestamp": turn["timestamp"],
                    "session_id": session_id,
                    "line": turn["lineno"],
                    "turns_after_failure": distance,
                    "friction_line": event["line"],
                }
            )

    cache_read = token_totals["cache_read_input_tokens"]
    cache_creation = token_totals["cache_creation_input_tokens"]
    base_input = token_totals["input_tokens"]
    denom = cache_read + cache_creation + base_input
    cache_read_ratio = round(cache_read / denom, 4) if denom > 0 else 0.0

    resolved_slug = detect_project_slug(cwd) if cwd else detect_project_slug()

    return {
        "session_id": session_id,
        "slug": resolved_slug,
        "cwd": cwd,
        "git_branch": git_branch,
        "transcript_path": str(path),
        "transcript_version": transcript_version,
        "started_at": started_at,
        "ended_at": ended_at,
        "friction_events": friction_events,
        "user_corrections": user_corrections,
        "pr_links": pr_links,
        "token_totals": token_totals,
        "cache_read_ratio": cache_read_ratio,
        "malformed_line_count": malformed_line_count,
        "tool_use_count": tool_use_count,
        "friction_field_presence": friction_field_presence,
    }


# ---------------------------------------------------------------------------
# cluster() -- group events by (event_kind, tool_name, command_prefix)
# ---------------------------------------------------------------------------


def cluster(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group events by (event_kind, tool_name, normalized_command_prefix).

    `events` is a flat iterable of event dicts (v1: always
    MinedSession.friction_events; every entry is implicitly friction
    unless it carries an explicit `"is_friction": False`, which lets a
    future routine-event source compose without a signature change --
    Epic 2 has no routine-tool-call capture yet, so all v1 input is
    friction).

    Returns one Cluster per distinct (event_kind, tool_name,
    command_prefix) signature, friction clusters first (by count desc),
    then routine clusters (by count desc) -- mirrors autoheal's own
    "friction first, then clusters descending by count" convention
    (autoheal-analyze.sh build_payload()). Friction clusters retain up to
    MAX_EXEMPLARS_PER_CLUSTER full exemplars (session_id + excerpt +
    timestamp); non-friction clusters never carry exemplars, matching
    autoheal's "cluster records never carry excerpts" rule.
    """
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []

    for ev in events:
        kind = ev.get("kind") or ev.get("event_kind") or "unknown"
        tool_name = ev.get("tool_name") or ""
        command_prefix = ev.get("command_prefix") or ""
        is_friction = bool(ev.get("is_friction", True))
        sig = (kind, tool_name, command_prefix)

        if sig not in groups:
            groups[sig] = {
                "event_kind": kind,
                "tool_name": ev.get("tool_name"),
                "command_prefix": ev.get("command_prefix"),
                "count": 0,
                "is_friction": is_friction,
                "sample_session_ids": [],
                "exemplars": [],
            }
            order.append(sig)

        g = groups[sig]
        g["count"] += 1
        sid = ev.get("session_id")
        if sid not in g["sample_session_ids"]:
            g["sample_session_ids"].append(sid)
        if g["is_friction"] and len(g["exemplars"]) < MAX_EXEMPLARS_PER_CLUSTER:
            g["exemplars"].append(
                {
                    "session_id": sid,
                    "excerpt": ev.get("excerpt", ""),
                    "timestamp": ev.get("timestamp"),
                }
            )

    clusters = [groups[sig] for sig in order]
    clusters.sort(key=lambda c: (not c["is_friction"], -c["count"]))
    return clusters


# ---------------------------------------------------------------------------
# budget() -- trim clusters to fit a token cap without dropping friction
# ---------------------------------------------------------------------------


def _estimate_tokens(obj: Any) -> int:
    """Rough token estimate: char/4 approximation (autoheal + Epic 2 spec
    convention -- see autoheal-analyze.sh's own `char_total // 4`)."""
    return len(json.dumps(obj, ensure_ascii=False)) // 4


def budget(clusters: list[dict[str, Any]], max_input_tokens: int) -> dict[str, Any]:
    """Trim clusters to fit `max_input_tokens` (chars/4 estimate).

    ALL friction clusters are always kept (never dropped) with at least
    one exemplar. If the friction exemplars alone exceed budget,
    exemplars are down-sampled ROUND-ROBIN across friction clusters
    (strip one exemplar from the cluster currently holding the MOST
    exemplars, repeat) until either the estimate fits or every friction
    cluster is down to its single mandatory exemplar -- a floor, matching
    the acceptance criterion "retain >=1 exemplar per friction cluster"
    even when the budget is very tight. Routine clusters are collapsed to
    bare counts (no exemplars, by construction of cluster()) and are
    never trimmed -- they are cheap by design (autoheal's friction-vs-
    routine token-budgeting rule).
    """
    friction = [dict(c, exemplars=list(c.get("exemplars") or [])) for c in clusters if c.get("is_friction")]
    routine = [dict(c) for c in clusters if not c.get("is_friction")]

    def current_estimate() -> int:
        return _estimate_tokens({"friction": friction, "routine": routine})

    while current_estimate() > max_input_tokens:
        strip_candidates = [c for c in friction if len(c["exemplars"]) > 1]
        if not strip_candidates:
            break
        strip_candidates.sort(key=lambda c: len(c["exemplars"]), reverse=True)
        strip_candidates[0]["exemplars"].pop()

    estimate = current_estimate()
    return {
        "clusters": friction + routine,
        "friction_cluster_count": len(friction),
        "routine_cluster_count": len(routine),
        "token_estimate": estimate,
        "max_input_tokens": max_input_tokens,
        "over_budget": estimate > max_input_tokens,
    }


# ---------------------------------------------------------------------------
# schema_canary() -- fail loud on silent transcript-schema drift (adrev-002)
# ---------------------------------------------------------------------------


def schema_canary(mined_sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail loud when the transcript schema appears to have drifted.

    Keyed on FIELD/SHAPE presence, not event count (adrev-015): a batch
    of sessions with tool_use blocks but zero recognized friction-bearing
    fields (`is_error`, `hookErrors`, `preventedContinuation`,
    `toolUseResult`) ANYWHERE in the whole window is treated as drift
    (the parser no longer recognizes this transcript version's field
    names) and raises SchemaDriftError. A batch with tool_use blocks AND
    recognized fields present but reporting no problems
    (is_error=False everywhere, hookErrors=[] everywhere) is a genuinely
    quiet window -- friction_field_presence is what distinguishes "quiet"
    from "drifted", not len(friction_events), so a real quiet week never
    cries wolf.

    Returns a summary dict {"observed_versions": {version: count},
    "untested_versions": [...]} for the caller to persist in run state
    and surface in the digest (adrev-002). Never returns silently on
    drift -- raises SchemaDriftError instead.
    """
    total_tool_use = sum(s.get("tool_use_count", 0) for s in mined_sessions)
    total_friction_fields = sum(s.get("friction_field_presence", 0) for s in mined_sessions)

    observed_versions: dict[str, int] = {}
    for s in mined_sessions:
        v = s.get("transcript_version")
        if v:
            observed_versions[v] = observed_versions.get(v, 0) + 1
    untested = sorted(v for v in observed_versions if v not in TESTED_TRANSCRIPT_VERSIONS)

    if total_tool_use > 0 and total_friction_fields == 0:
        raise SchemaDriftError(
            f"schema_canary: {total_tool_use} tool_use block(s) observed across "
            f"{len(mined_sessions)} session(s) but zero recognized friction-bearing "
            "fields (is_error/hookErrors/preventedContinuation/toolUseResult) were "
            "found anywhere in the window. This likely means the transcript schema "
            f"drifted (observed versions: {sorted(observed_versions) or ['unknown']}) "
            "and the miner is silently reading zero friction. Investigate before "
            "trusting an empty evidence bundle."
        )

    return {"observed_versions": observed_versions, "untested_versions": untested}


# ---------------------------------------------------------------------------
# discover() -- enumerate transcript files by re-derived slug + mtime
# ---------------------------------------------------------------------------


def _iso_to_epoch(iso: str) -> float | None:
    """Parse an ISO 8601 UTC timestamp (with or without milliseconds) to
    epoch seconds. Mirrors learnings_store.py's own `_parse_iso`."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(iso, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _peek_slug(path: Path) -> str | None:
    """Read just enough of a transcript to resolve its owning slug.

    Scans forward (bounded by _PEEK_LINE_LIMIT) until a line with a `cwd`
    field is found and returns detect_project_slug(cwd) -- the SAME
    canonical function mine() uses (arch-1). Returns None if no readable
    `cwd` field is found within the scan window, or the file cannot be
    read at all; callers treat None as "cannot determine ownership,
    exclude from this slug's discovery" rather than guessing.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for _ in range(_PEEK_LINE_LIMIT):
                raw = fh.readline()
                if not raw:
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("cwd"), str):
                    return detect_project_slug(obj["cwd"])
    except OSError:
        return None
    return None


def discover(
    slugs: Iterable[str],
    since_watermark: dict[str, str] | None = None,
    *,
    projects_root: str | Path | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[str]:
    """Enumerate transcript files under ~/.claude/projects/*/ whose owning
    learnings-store slug is in `slugs`.

    Slug identity is re-derived from EACH transcript's own `cwd` field via
    detect_project_slug() (arch-1) -- never from a ~/.claude/projects/
    directory-name heuristic (that directory is keyed by the encoded
    absolute cwd PATH, one per clone; multiple clones of the same repo
    share ONE learnings-store slug via git-remote resolution, so
    directory-name matching would silently miss sibling-clone evidence).

    since_watermark: optional {slug: ISO8601} map, the same shape as
    ~/.claude/dreaming/state/last-dreamed.json. A file is skipped only
    when its mtime is NOT newer than the watermark recorded for its
    resolved slug; files whose slug has no prior watermark fall back to
    the `lookback_days` cutoff (bounds the FIRST run so a machine with
    years of transcript history is not mined in one pass -- matches Epic
    3's `lookback_days` config key, plan.md §3.3).

    `projects_root` defaults to ~/.claude/projects; tests pass a temp dir
    so real transcripts are never touched.
    """
    root = Path(projects_root) if projects_root else Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return []

    wanted = set(slugs)
    since_watermark = since_watermark or {}
    cutoff = time.time() - lookback_days * 86400

    matches: list[str] = []
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        for transcript_path in sorted(project_dir.glob("*.jsonl")):
            try:
                mtime = transcript_path.stat().st_mtime
            except OSError:
                continue

            resolved_slug = _peek_slug(transcript_path)
            if resolved_slug is None or resolved_slug not in wanted:
                continue

            watermark_iso = since_watermark.get(resolved_slug)
            if watermark_iso:
                watermark_epoch = _iso_to_epoch(watermark_iso)
                if watermark_epoch is not None and mtime <= watermark_epoch:
                    continue
            elif mtime < cutoff:
                continue

            matches.append(str(transcript_path))

    return matches


# ---------------------------------------------------------------------------
# Watermark read/write (~/.claude/dreaming/state/last-dreamed.json)
# ---------------------------------------------------------------------------


def _dreaming_dir() -> Path:
    return Path(os.environ.get("CCGM_DREAMING_DIR", os.path.expanduser("~/.claude/dreaming")))


def watermark_path() -> Path:
    return _dreaming_dir() / "state" / "last-dreamed.json"


def read_watermark() -> dict[str, str]:
    """Read {slug: ISO8601-of-newest-mined-line} from state/last-dreamed.json.
    Returns {} if the file is absent or corrupt (fails open, never crashes
    a caller that has not dreamed yet).

    Intentionally a plain, unlocked read: write_watermark()'s on-disk
    swap is a tempfile + os.replace() (atomic), so a concurrent,
    lock-free read here can only ever observe a fully-old or fully-new
    file, never a torn one.
    """
    path = watermark_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _watermark_is_newer(candidate: str, existing: str | None) -> bool:
    """True if `candidate` should replace `existing` as the stored watermark.

    Compares by epoch-seconds via _iso_to_epoch() rather than raw string
    ordering: a fractional-precision timestamp ("...T10:00:00.500Z")
    must compare newer than the non-fractional form of the same second
    ("...T10:00:00Z"), but lexicographic string comparison gets this
    backwards -- "." (0x2E) sorts below "Z" (0x5A), so the fractional
    value would wrongly compare as NOT newer. Falls back to raw string
    comparison only when either side fails to parse, matching
    write_watermark()'s original fail-open posture for malformed input.
    """
    if existing is None:
        return True
    candidate_epoch = _iso_to_epoch(candidate)
    existing_epoch = _iso_to_epoch(existing)
    if candidate_epoch is not None and existing_epoch is not None:
        return candidate_epoch > existing_epoch
    return candidate > existing


def write_watermark(slug: str, iso_timestamp: str) -> None:
    """Update the watermark for one slug, preserving every other slug's
    entry (read-modify-write; the watermark file is a small dict, not a
    log -- schema per plan.md §3.3). Only advances forward: a call whose
    timestamp is not strictly newer than the stored value (per
    _watermark_is_newer()) is a no-op, so a watermark is never regressed
    and history never gets re-mined.

    The read+merge+write critical section is fcntl-locked (mirrors
    hook_utils.file_locked_append's cross-process discipline) so two
    concurrent writers -- e.g. a manual `--force-day` run overlapping the
    scheduled nightly job -- cannot race: without the lock, a writer that
    reads the file before another writer's update lands can clobber that
    update when it writes last, silently losing a DIFFERENT slug's
    advance. The on-disk swap itself goes through a tempfile +
    os.replace() (atomic) rather than an in-place write, so any caller
    that reads without taking the lock (read_watermark() is
    intentionally unlocked -- see its own docstring) never observes a
    partially written file.
    """
    path = watermark_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lock_fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            data = read_watermark()
            existing = data.get(slug)
            if not _watermark_is_newer(iso_timestamp, existing):
                return
            data[slug] = iso_timestamp
            payload = json.dumps(data, indent=2, sort_keys=True)
            tmp_fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
            )
            try:
                os.fchmod(tmp_fd, 0o644)
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_fh:
                    tmp_fh.write(payload)
                os.replace(tmp_name, path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


# ---------------------------------------------------------------------------
# Evidence bundle assembly
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def mine_to_evidence_bundle(
    transcript_paths: Iterable[str | Path],
    *,
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
) -> dict[str, Any]:
    """End-to-end: mine() every path, run schema_canary(), cluster() the
    friction events, budget() them, assemble the evidence bundle.

    Returns the evidence-bundle dict (schema: lib/evidence-bundle-schema.json).
    Raises SchemaDriftError via schema_canary() if the transcript schema
    appears to have drifted (adrev-002) -- callers should NOT catch this
    silently; an empty evidence bundle from a drifted parser is worse
    than a loud failure.
    """
    mined_sessions = [mine(p) for p in transcript_paths]
    canary = schema_canary(mined_sessions)

    all_friction_events = [ev for s in mined_sessions for ev in s["friction_events"]]
    clustered = cluster(all_friction_events)
    budgeted = budget(clustered, max_input_tokens)

    slugs = sorted({s["slug"] for s in mined_sessions if s.get("slug")})
    malformed_total = sum(s["malformed_line_count"] for s in mined_sessions)

    sessions_summary = [
        {
            "session_id": s["session_id"],
            "slug": s["slug"],
            "git_branch": s["git_branch"],
            "started_at": s["started_at"],
            "ended_at": s["ended_at"],
            "token_totals": s["token_totals"],
            "cache_read_ratio": s["cache_read_ratio"],
            "user_corrections": s["user_corrections"],
            "pr_links": s["pr_links"],
            "malformed_line_count": s["malformed_line_count"],
            "tool_use_count": s["tool_use_count"],
            "friction_field_presence": s["friction_field_presence"],
        }
        for s in mined_sessions
    ]

    return {
        "generated_at": _utc_now_iso(),
        "slugs": slugs,
        "session_count": len(mined_sessions),
        "sessions": sessions_summary,
        "clusters": budgeted["clusters"],
        "friction_cluster_count": budgeted["friction_cluster_count"],
        "routine_cluster_count": budgeted["routine_cluster_count"],
        "token_estimate": budgeted["token_estimate"],
        "max_input_tokens": max_input_tokens,
        "over_budget": budgeted["over_budget"],
        "malformed_line_total": malformed_total,
        "canary": canary,
    }


# ---------------------------------------------------------------------------
# Stdlib-only JSON Schema validation (no `jsonschema` dependency)
# ---------------------------------------------------------------------------

_TYPE_MAP = {"object": dict, "array": list, "string": str, "boolean": bool}


def _matches_type(instance: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "null":
        return instance is None
    py_type = _TYPE_MAP.get(expected)
    if py_type is None:
        return True  # unknown declared type -- do not block on it
    return isinstance(instance, py_type)


def validate_against_schema(instance: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Minimal, dependency-free JSON Schema validator (subset: type,
    required, properties, items, enum, minimum, maximum, minLength; `type`
    may be a single string or a list of strings per the JSON Schema spec).

    Returns a list of human-readable error strings; empty list = valid.
    Deliberately not a full draft-07 implementation (no $ref, no
    oneOf/anyOf/allOf, no patternProperties, additionalProperties is
    always implicitly allowed) -- Epic 2's schema does not need those,
    and code-quality's "minimize dependencies" rule rules out pulling in
    the `jsonschema` package for this. Both transcript_miner.py's
    --self-check and Epic 3's dream_analyze.py are expected to validate
    against the SAME evidence-bundle-schema.json using this function
    (arch-3: one shared validator, one shared schema, one shared fixture).
    """
    errors: list[str] = []
    declared_type = schema.get("type")
    allowed_types = declared_type if isinstance(declared_type, list) else ([declared_type] if declared_type else None)

    if allowed_types and not any(_matches_type(instance, t) for t in allowed_types):
        errors.append(f"{path}: expected type {declared_type!r}, got {type(instance).__name__}")
        return errors

    if isinstance(instance, dict) and (allowed_types is None or "object" in allowed_types):
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property {req!r}")
        for key, subschema in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(validate_against_schema(instance[key], subschema, path=f"{path}.{key}"))

    if isinstance(instance, list) and (allowed_types is None or "array" in allowed_types):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(instance):
                errors.extend(validate_against_schema(item, item_schema, path=f"{path}[{i}]"))

    enum = schema.get("enum")
    if enum is not None and instance not in enum:
        errors.append(f"{path}: value {instance!r} not in enum {enum!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        if minimum is not None and instance < minimum:
            errors.append(f"{path}: {instance} < minimum {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and instance > maximum:
            errors.append(f"{path}: {instance} > maximum {maximum}")

    if isinstance(instance, str):
        min_len = schema.get("minLength")
        if min_len is not None and len(instance) < min_len:
            errors.append(f"{path}: length {len(instance)} < minLength {min_len}")

    return errors


# ---------------------------------------------------------------------------
# --self-check entry point
# ---------------------------------------------------------------------------


def _fixtures_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def self_check() -> dict[str, Any]:
    """Run the fixture pipeline end-to-end and validate the output.

    Mines every "healthy" fixture together (friction.jsonl, clean.jsonl,
    user-correction.jsonl, quiet-week.jsonl), runs the full
    cluster()/budget() pipeline, and validates the resulting evidence
    bundle against evidence-bundle-schema.json.

    Also exercises the negative-control path: drift.jsonl (deliberately
    excluded from the healthy bundle) is mined and passed to
    schema_canary() alone, and MUST raise SchemaDriftError -- this is
    reported in the summary as `drift_fixture_raises_canary`, not treated
    as a self-check failure (raising is the correct, expected behavior).
    """
    fixtures = _fixtures_dir()
    healthy = ["friction.jsonl", "clean.jsonl", "user-correction.jsonl", "quiet-week.jsonl"]
    paths = [fixtures / name for name in healthy]
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(f"self-check fixture missing: {p}")

    bundle = mine_to_evidence_bundle(paths, max_input_tokens=DEFAULT_MAX_INPUT_TOKENS)

    schema_path = Path(__file__).resolve().parent / "evidence-bundle-schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate_against_schema(bundle, schema)
    if errors:
        raise ValueError("self-check: evidence bundle failed schema validation:\n" + "\n".join(errors))

    drift_path = fixtures / "drift.jsonl"
    drift_raises = False
    if drift_path.is_file():
        try:
            schema_canary([mine(drift_path)])
        except SchemaDriftError:
            drift_raises = True

    return {
        "ok": True,
        "fixtures_mined": len(paths),
        "session_count": bundle["session_count"],
        "friction_cluster_count": bundle["friction_cluster_count"],
        "routine_cluster_count": bundle["routine_cluster_count"],
        "malformed_line_total": bundle["malformed_line_total"],
        "canary": bundle["canary"],
        "schema_valid": True,
        "drift_fixture_raises_canary": drift_raises,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CCGM dreaming: deterministic session-transcript miner (Epic 2)."
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Run the fixture pipeline end-to-end, validate against the schema, print a JSON summary.",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        try:
            summary = self_check()
        except SchemaDriftError as exc:
            print(json.dumps({"ok": False, "error": "schema_drift", "detail": str(exc)}, indent=2))
            return 1
        except Exception as exc:  # noqa: BLE001 -- top-level CLI boundary
            print(json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)}, indent=2))
            return 1
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
