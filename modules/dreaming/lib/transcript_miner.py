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
    discover(slugs, *, cursors=None, projects_root=None) -> list[str]
    discover_with_offsets(...) -> dict[str, int]   # path -> byte offset to mine from
    mine(path, start_offset=0) -> dict       # MinedSession
    cluster(events) -> list[dict]            # list[Cluster]
    budget(clusters, max_input_tokens) -> dict
    validate_structure(mined_sessions) -> list[dict]  # pure; list[finding]
    schema_canary(mined_sessions) -> dict    # {observed_versions}; raises SchemaDriftError on drift
    mine_to_evidence_bundle(paths, *, max_input_tokens=200_000, start_offsets=None, end_offsets_out=None) -> dict
    read_watermark() / write_watermark(slug, iso_timestamp)   # LRU ordering only
    read_cursors() / write_cursors(slug, {path: offset})      # what has been mined
    migrate_watermarks_to_cursors(slugs, *, projects_root=None)
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
    """Raised by schema_canary() when the field-level structural contract
    (see validate_structure()) is violated -- a whole family of expected
    fields (friction, token-economics, or turn-structure) is structurally
    absent from the mined batch despite its corroborating signal being
    present. See schema_canary()."""


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


def make_excerpt(text: str, limit: int = EXCERPT_MAX_CHARS) -> str:
    """Redact secrets + PII, then truncate to `limit` (default
    EXCERPT_MAX_CHARS).

    Redaction MUST happen before truncation (hook_utils.redact_secrets'
    own documented contract) so the truncation boundary can never lop a
    redaction marker -- or a partial secret/PII fragment -- in half.
    Guarantees len(result) <= min(limit, EXCERPT_MAX_CHARS).
    """
    limit = min(limit, EXCERPT_MAX_CHARS)
    redacted = redact_secrets(text or "")
    redacted = redact_pii(redacted)
    if len(redacted) <= limit:
        return redacted
    return redacted[: limit - 3].rstrip() + "..."


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


def _is_human_origin_turn(obj: dict[str, Any]) -> bool:
    """True iff a `type:"user"` transcript line was authored by the human
    operator directly, rather than being a tool_result / synthetic / replayed
    turn.

    Requires an explicit POSITIVE origin signal -- `origin.kind == "human"`
    OR `promptSource == "typed"` (both fields already present in the
    transcript format and previously unread here; sec-C1, decisions.md #15).
    Fail-closed: a turn missing BOTH signals is NOT treated as human-origin,
    so a tool_result-only turn (which carries neither) can never mint a
    user-correction even when its embedded tool output happens to contain a
    negation phrase.
    """
    origin = obj.get("origin")
    if isinstance(origin, dict) and origin.get("kind") == "human":
        return True
    return obj.get("promptSource") == "typed"


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


def _iter_jsonl(path: str | Path, start_offset: int = 0):
    """Yield (line_number, parsed_dict_or_None, start_byte, end_byte) for
    every non-blank line at or after byte `start_offset`.

    None means the line was present but failed to parse as a JSON object
    (malformed JSON, or valid JSON that is not a dict). Callers count
    these and skip them -- never crash on a corrupt transcript.

    line_number is absolute (it counts the lines before `start_offset`), so
    evidence line references mean the same thing whether a file is mined
    whole or from a cursor. A final line with no trailing newline is
    yielded only if it parses; otherwise the writer is mid-append, and the
    line is left for the next read (end_byte never passes it).

    Lazy and linear: lines are read one at a time, so a caller that stops
    early (_head_metadata, _has_new_content) never reads the rest of the file.
    """
    with open(path, "rb") as fh:
        # Count the lines before the cursor in chunks (never held in memory).
        head_lines = 0
        remaining = start_offset
        while remaining > 0:
            chunk = fh.read(min(1 << 20, remaining))
            if not chunk:
                break
            head_lines += chunk.count(b"\n")
            remaining -= len(chunk)

        pos = start_offset
        lineno = head_lines
        while True:
            raw_line = fh.readline()
            if not raw_line:
                return
            terminated = raw_line.endswith(b"\n")
            lineno += 1
            line_start, pos = pos, pos + len(raw_line)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                if not terminated:
                    return
                yield lineno, None, line_start, pos
                continue
            yield lineno, (obj if isinstance(obj, dict) else None), line_start, pos


def _file_end_offset(path: str | Path, start_offset: int = 0) -> int:
    """Byte offset just past the last line _iter_jsonl() would consume."""
    end = start_offset
    for _lineno, _obj, _start, line_end in _iter_jsonl(path, start_offset):
        end = line_end
    return end


# ---------------------------------------------------------------------------
# mine() -- the core extraction pass
# ---------------------------------------------------------------------------


def _head_metadata(path: Path) -> dict[str, str]:
    """First sessionId / cwd / gitBranch / version in the file head (bounded
    by _PEEK_LINE_LIMIT lines), for mining a range that starts mid-file."""
    found: dict[str, str] = {}
    try:
        for i, (_n, obj, _s, _e) in enumerate(_iter_jsonl(path)):
            if i >= _PEEK_LINE_LIMIT:
                break
            if obj is None:
                continue
            for key in ("sessionId", "cwd", "gitBranch", "version"):
                if key not in found and isinstance(obj.get(key), str):
                    found[key] = obj[key]
            if len(found) == 4:
                break
    except OSError:
        pass
    return found


# ---------------------------------------------------------------------------
# Signal extractors (#1098 Phase 3.1): knowledge the agent does not already
# carry. Five deterministic extractors -- human redirections, resolved
# struggle arcs, conclusions, rediscovery, abandoned work. Each emits a
# "signal" dict:
#   kind        redirection | struggle_arc | conclusion | abandoned_work |
#               rediscovery
#   session_id, timestamp, line
#   excerpt     the cited text: redacted, <= EXCERPT_MAX_CHARS, and a single
#               contiguous span of the transcript so the apply-time
#               corroboration check can find it
#   context     (redirection, conclusion, abandoned_work) what came before:
#               the assistant turn, or for a conclusion the friction event or
#               human redirection that opened its window
# Hook friction stays in the friction clusters; corrections no longer need a
# nearby tool error to count.
# ---------------------------------------------------------------------------

# Budget priority, highest first. A strict 3-failure arc is rare but strong,
# so it outranks the broader conclusion extractor that subsumes its idea.
SIGNAL_KINDS = ("redirection", "struggle_arc", "conclusion", "abandoned_work", "rediscovery")
# Signals may use at most this share of the token budget; friction gets the
# rest. When signals alone exceed it, later kinds in SIGNAL_KINDS drop first.
SIGNAL_BUDGET_FRACTION = 0.8
MAX_SIGNALS_PER_KIND_PER_SESSION = 20
MAX_REDISCOVERY_PER_SLUG = 15
STRUGGLE_MIN_FAILURES = 3
CONTEXT_MAX_CHARS = 240
# A human-typed redirection is a sentence or two. Anything longer is pasted
# content or a skill/command expansion that carries origin markers.
MAX_HUMAN_TURN_CHARS = 800

_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL | re.IGNORECASE)
_HARNESS_PREFIXES = (
    "<system-reminder",
    "<command-",
    "<local-command",
    "<task-notification",
    "<user-prompt-submit-hook",
    "caveat:",
    "[request interrupted",
    "base directory for this skill",
)

_REDIRECT_RE = re.compile(
    r"^\s*(?:no|nope|wrong)\b"
    r"|\bthat(?:'s| is) (?:not|wrong|incorrect)\b"
    r"|\bwe (?:don't|do not|never|shouldn't|should not)\b"
    r"|\b(?:always|never)\b"
    r"|\binstead\b"
    r"|\bi (?:want|prefer|need you to)\b|\bi'd rather\b"
    r"|\bnot (?:that|what i)\b"
    r"|\bstop (?:doing|using)\b"
    r"|\bplease (?:don't|do not)\b"
    r"|\b(?:incorrect|you broke|that broke|wrong approach|actually,? no)\b",
    re.IGNORECASE,
)
_ABANDON_USER_RE = re.compile(
    r"\bundo (?:that|this|it|those|the)\b"
    r"|\brevert(?:ed|ing)?\b"
    r"|\broll(?:ed)? ?back\b"
    r"|\bscrap (?:that|this|it)\b",
    re.IGNORECASE,
)
# `git reset --hard origin/...` is how this workflow syncs a branch, not how
# it abandons work, so it is excluded.
_GIT_ABANDON_RE = re.compile(
    r"(?:^|[;&|(]\s*|\s)git(?:\s+-[Cc]\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+(?:revert\b|reset\s+--hard\b(?!\s+origin/))"
)
_CONCLUSION_RE = re.compile(r"root cause|the fix|turns out|because", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_TEST_TOKEN_RE = re.compile(r"\S*(?:test|spec)\S*\.(?:py|js|jsx|ts|tsx|sh|rb|go|rs)(?:::\S+)?", re.IGNORECASE)

# Files every session loads or reads by habit: re-reading them is not
# rediscovery of anything.
_ALWAYS_READ_BASENAMES = frozenset({"claude.md", "memory.md", "readme.md", "agents.md"})
_FILE_PATH_TOOLS = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit", "Read"})


def _clean_human_text(turn: dict[str, Any]) -> str:
    """The typed text of a genuinely human turn, or "" if it is not one.

    Reuses the miner's human_origin gate, then drops what rides along with
    it: <system-reminder> blocks appended to the same message, harness
    wrappers (command output, interrupts, skill expansions), `isMeta`
    lines, and anything longer than MAX_HUMAN_TURN_CHARS."""
    if turn.get("role") != "user" or not turn.get("human_origin") or turn.get("is_meta"):
        return ""
    text = _REMINDER_RE.sub("", turn.get("text") or "").strip()
    if not text or len(text) > MAX_HUMAN_TURN_CHARS:
        return ""
    if text.lower().startswith(_HARNESS_PREFIXES):
        return ""
    return text


def _preceding_assistant_text(turn_sequence: list[dict[str, Any]], index: int) -> str:
    """Text of the nearest assistant turn before `index` that has any,
    without crossing a human turn."""
    for turn in reversed(turn_sequence[:index]):
        if turn["role"] == "assistant":
            if turn.get("text", "").strip():
                return turn["text"]
        elif turn.get("human_origin"):
            break
    return ""


def _conclusion_excerpt(text: str) -> str:
    """The sentences of `text` that state a conclusion ("root cause", "the
    fix", "turns out", "because"); when none do, the first three sentences."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s and s.strip()]
    chosen = [s for s in sentences if _CONCLUSION_RE.search(s)] or sentences[:3]
    return make_excerpt(" ".join(chosen))


def _attempt_signature(name: Any, tinput: Any) -> str | None:
    """What an attempt is "the same as": a file path, a test name, or the
    first three words of a shell command."""
    if not isinstance(tinput, dict):
        return None
    if name in _FILE_PATH_TOOLS:
        path = tinput.get("file_path") or tinput.get("notebook_path")
        return f"path:{path}" if isinstance(path, str) and path else None
    if name == "Bash":
        command = tinput.get("command")
        if not isinstance(command, str) or not command.strip():
            return None
        test = _TEST_TOKEN_RE.search(command)
        if test:
            return f"test:{test.group(0)}"
        return "cmd:" + " ".join(command.split()[:3])
    return None


def _explore_target(name: Any, tinput: Any) -> str | None:
    """Raw (not yet cwd-relative) Read/Grep/Glob target, or None."""
    if not isinstance(tinput, dict):
        return None
    if name == "Read":
        path = tinput.get("file_path")
        return f"Read {path}" if isinstance(path, str) and path else None
    if name == "Grep":
        pattern = tinput.get("pattern")
        if not isinstance(pattern, str) or len(pattern) < 4:
            return None
        path = tinput.get("path")
        return f'Grep "{pattern}"' + (f" {path}" if isinstance(path, str) and path else "")
    if name == "Glob":
        pattern = tinput.get("pattern")
        return f"Glob {pattern}" if isinstance(pattern, str) and pattern else None
    return None


def _relativize_target(target: str, cwd: str | None) -> str | None:
    """Make a path-bearing target cwd-relative so the same file explored from
    two clones or worktrees compares equal; drop always-read files."""
    if cwd:
        target = target.replace(cwd.rstrip("/") + "/", "")
    words = target.split()
    last = words[-1].strip('"') if words else ""
    if target.startswith("Read ") and (
        last.rsplit("/", 1)[-1].lower() in _ALWAYS_READ_BASENAMES or "/.claude/" in "/" + last
    ):
        return None
    return _redact(target)[:200]


def _struggle_arcs(
    attempts: list[dict[str, Any]],
    turn_sequence: list[dict[str, Any]],
    session_id: str | None,
) -> list[dict[str, Any]]:
    """Three or more consecutive failed attempts on one signature, then a
    success on it. The excerpt is the assistant's conclusion after the
    success; an arc with no assistant text after it has nothing to mine."""
    failures: dict[str, int] = {}
    arcs: list[dict[str, Any]] = []
    for attempt in attempts:
        sig = attempt["signature"]
        if attempt["failed"]:
            failures[sig] = failures.get(sig, 0) + 1
            continue
        count = failures.pop(sig, 0)
        if count < STRUGGLE_MIN_FAILURES:
            continue
        following: list[str] = []
        for turn in turn_sequence[attempt["turn_index"] + 1:]:
            if turn["role"] == "user" and turn.get("human_origin"):
                break
            if turn["role"] == "assistant" and turn.get("text", "").strip():
                following.append(turn["text"])
                if len(following) == 3:
                    break
        if not following:
            continue
        arcs.append(
            {
                "kind": "struggle_arc",
                "session_id": session_id,
                "timestamp": attempt["timestamp"],
                "line": attempt["line"],
                "excerpt": _conclusion_excerpt("\n".join(following)),
                "signature": _redact(sig)[:120],
                "failure_count": count,
            }
        )
    return arcs


# Conclusions: sentences of assistant prose that state a finding. Narration
# ("let me check", "I'll run") is kept out by two gates -- the sentence must
# land within CONCLUSION_WINDOW_TURNS turns after a friction event or a human
# redirection, and it must carry a finding marker. The marker set is
# deliberate and small:
#   strong  root cause | turns out | the fix is/was | the problem is/was |
#           the actual | the reason
#   weak    because | doesn't/does not support | only works when |
#           "so ... requires/needs/must"
# Strong markers rank first when the per-session cap bites.
MAX_CONCLUSIONS_PER_SESSION = 6
CONCLUSION_WINDOW_TURNS = 8
CONCLUSION_MIN_CHARS = 40
# A sentence is a restatement of the error (already in the friction cluster)
# when this share of its content tokens appears in a friction excerpt of the
# same window.
CONCLUSION_RESTATE_OVERLAP = 0.6
CONCLUSION_DEDUPE_JACCARD = 0.8
_CONCLUSION_STRONG_RE = re.compile(
    r"root cause|turns out|the fix (?:is|was)\b|the problem (?:is|was)\b|the actual\b|the reason\b", re.IGNORECASE
)
_CONCLUSION_WEAK_RE = re.compile(
    r"\bbecause\b|doesn'?t support|does not support|only works when|\bso\b[^.!?]{0,60}\b(?:requires?|needs?|must)\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_CONTENT_TOKEN_RE = re.compile(r"[a-z][a-z0-9_\-]{3,}")


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of each sentence of `text`, so a run of
    sentences can be cut back out as one contiguous span."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _SENTENCE_BREAK_RE.finditer(text):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def _content_tokens(text: str) -> set[str]:
    return set(_CONTENT_TOKEN_RE.findall(text.lower()))


def _conclusion_signals(
    turn_sequence: list[dict[str, Any]],
    friction_events: list[dict[str, Any]],
    redirections: list[dict[str, Any]],
    arcs: list[dict[str, Any]],
    session_id: str | None,
) -> list[dict[str, Any]]:
    """Finding-stating sentences of assistant prose shortly after friction
    or a human redirection. Text blocks only, never tool inputs (the turn
    `text` is built from text blocks)."""
    line_to_turn = {t["lineno"]: t["turn_index"] for t in turn_sequence}
    anchors: list[dict[str, Any]] = [
        {"turn_index": ev["turn_index"], "text": ev["excerpt"], "friction": True} for ev in friction_events
    ]
    anchors += [
        {"turn_index": line_to_turn[r["line"]], "text": r["excerpt"], "friction": False}
        for r in redirections
        if r["line"] in line_to_turn
    ]
    if not anchors:
        return []
    arc_text = " ".join(a["excerpt"].lower() for a in arcs)

    candidates: list[dict[str, Any]] = []
    for turn in turn_sequence:
        if turn["role"] != "assistant" or not turn.get("text", "").strip():
            continue
        t = turn["turn_index"]
        window = [a for a in anchors if a["turn_index"] < t <= a["turn_index"] + CONCLUSION_WINDOW_TURNS]
        if not window:
            continue
        opener = max(window, key=lambda a: a["turn_index"])
        friction_tokens = [_content_tokens(a["text"]) for a in window if a["friction"]]
        text = turn["text"]
        spans = _sentence_spans(text)
        for i, (a, b) in enumerate(spans):
            sentence = text[a:b].strip()
            if len(sentence) < CONCLUSION_MIN_CHARS:
                continue
            strong = bool(_CONCLUSION_STRONG_RE.search(sentence))
            if not strong and not _CONCLUSION_WEAK_RE.search(sentence):
                continue
            tokens = _content_tokens(sentence)
            if tokens and any(len(tokens & ft) / len(tokens) >= CONCLUSION_RESTATE_OVERLAP for ft in friction_tokens):
                continue
            if sentence[:60].lower() in arc_text:
                continue
            # The sentence plus one neighbour (the next, else the previous),
            # cut from the original text so it stays contiguous.
            if i + 1 < len(spans):
                start, end = a, spans[i + 1][1]
            elif i > 0:
                start, end = spans[i - 1][0], b
            else:
                start, end = a, b
            candidates.append(
                {
                    "strong": strong,
                    "order": (t, a),
                    "tokens": tokens,
                    "signal": {
                        "kind": "conclusion",
                        "session_id": session_id,
                        "timestamp": turn["timestamp"],
                        "line": turn["lineno"],
                        "excerpt": make_excerpt(text[start:end].strip()),
                        "context": make_excerpt(opener["text"], CONTEXT_MAX_CHARS),
                    },
                }
            )

    # Dedupe near-identical sentences (earliest wins), then keep the
    # strongest MAX_CONCLUSIONS_PER_SESSION, in transcript order.
    kept: list[dict[str, Any]] = []
    for cand in sorted(candidates, key=lambda c: c["order"]):
        if any(
            cand["tokens"] and k["tokens"]
            and len(cand["tokens"] & k["tokens"]) / len(cand["tokens"] | k["tokens"]) >= CONCLUSION_DEDUPE_JACCARD
            for k in kept
        ):
            continue
        kept.append(cand)
    kept = sorted(kept, key=lambda c: (not c["strong"], c["order"]))[:MAX_CONCLUSIONS_PER_SESSION]
    return [c["signal"] for c in sorted(kept, key=lambda c: c["order"])]


def _human_turn_signals(
    turn_sequence: list[dict[str, Any]], session_id: str | None, *, mid_session: bool
) -> list[dict[str, Any]]:
    """Redirections and user-requested abandonment. Each human turn is
    classified once: abandonment wins over redirection.

    Until the assistant has done something there is nothing to redirect or
    undo, so a turn before the first assistant turn is a task statement, not
    a signal. `mid_session` (mining resumed from a cursor) lifts that: the
    assistant turn it answers sits in the part already mined."""
    signals: list[dict[str, Any]] = []
    seen_assistant = mid_session
    for turn in turn_sequence:
        if turn["role"] == "assistant":
            seen_assistant = True
            continue
        text = _clean_human_text(turn)
        if not text or not seen_assistant:
            continue
        if _ABANDON_USER_RE.search(text):
            kind = "abandoned_work"
        elif _REDIRECT_RE.search(text):
            kind = "redirection"
        else:
            continue
        signals.append(
            {
                "kind": kind,
                "session_id": session_id,
                "timestamp": turn["timestamp"],
                "line": turn["lineno"],
                "excerpt": make_excerpt(text),
                "context": make_excerpt(_preceding_assistant_text(turn_sequence, turn["turn_index"]), CONTEXT_MAX_CHARS),
            }
        )
    return signals


def mine(path: str | Path, start_offset: int = 0) -> dict[str, Any]:
    """Mine one session-transcript JSONL into a MinedSession dict.

    start_offset: mine only the bytes at or after this offset (the
    per-file cursor from read_cursors()). An offset past the end of the
    file means it was truncated or rotated, so it is re-read from 0. When
    the mined range has no `cwd` / `sessionId` / `gitBranch` / `version` of
    its own, they come from the file head, so the slug stays correct.
    The result carries `start_offset` and `end_offset` for the cursor.

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

    Structural presence counters (turn_count, assistant_turn_count,
    usage_field_presence, parsed_line_count) feed validate_structure()'s
    field-level drift contract (schema_canary()) -- they count STRUCTURAL
    presence of a recognized field/shape, not event volume, mirroring
    friction_field_presence's existing idiom.
    """
    path = Path(path)

    if start_offset > path.stat().st_size:
        start_offset = 0

    lines: list[tuple[int, dict[str, Any]]] = []
    malformed_line_count = 0
    end_offset = start_offset
    for lineno, obj, _line_start, line_end in _iter_jsonl(path, start_offset):
        end_offset = line_end
        if obj is None:
            malformed_line_count += 1
            continue
        lines.append((lineno, obj))

    session_id: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    transcript_version: str | None = None
    if start_offset > 0:
        head = _head_metadata(path)
        session_id = head.get("sessionId")
        cwd = head.get("cwd")
        git_branch = head.get("gitBranch")
        transcript_version = head.get("version")
    started_at: str | None = None
    ended_at: str | None = None
    tool_use_count = 0
    friction_field_presence = 0
    usage_field_presence = 0
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
    # Inputs to the signal extractors: every completed tool attempt in order,
    # abandonment commands that ran clean, and raw Read/Grep/Glob targets.
    attempts: list[dict[str, Any]] = []
    abandon_commands: list[dict[str, Any]] = []
    explore_raw: list[str] = []

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
            if isinstance(usage, dict) and any(key in usage for key in token_totals):
                usage_field_presence += 1
            for key in token_totals:
                v = usage.get(key)
                if isinstance(v, (int, float)):
                    token_totals[key] += int(v)
            content = message.get("content")
            if isinstance(content, list):
                turn_sequence[turn_index]["text"] = _text_from_content(
                    [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
                )
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
                            "signature": _attempt_signature(name, tinput),
                            "command": tinput.get("command") if name == "Bash" and isinstance(tinput, dict) else None,
                        }
                    target = _explore_target(name, tinput)
                    if target:
                        explore_raw.append(target)

        elif line_type == "user":
            turn_index = len(turn_sequence)
            message = obj.get("message") or {}
            content = message.get("content")
            user_text = _text_from_content(content)
            turn_sequence.append(
                {
                    "turn_index": turn_index,
                    "role": "user",
                    "lineno": lineno,
                    "text": user_text,
                    "timestamp": ts,
                    "human_origin": _is_human_origin_turn(obj),
                    "is_meta": bool(obj.get("isMeta")),
                }
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
                    failed = is_error or (exit_code not in (None, 0))
                    if tool_info.get("signature"):
                        attempts.append(
                            {
                                "signature": tool_info["signature"],
                                "failed": failed,
                                "turn_index": turn_index,
                                "timestamp": ts,
                                "line": lineno,
                            }
                        )
                    command = tool_info.get("command")
                    if not failed and isinstance(command, str) and _GIT_ABANDON_RE.search(command):
                        abandon_commands.append(
                            {"command": command, "turn_index": turn_index, "timestamp": ts, "line": lineno}
                        )
                    if failed:
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
        # sec-C1 (decisions.md #15): a user-correction may only be minted from
        # a human-authored turn. A tool_result-only turn carries no origin
        # signal and is skipped here, so a negation phrase appearing INSIDE
        # tool output can never be mistaken for the operator correcting the
        # agent. Fail-closed: a turn with neither origin.kind=="human" nor
        # promptSource=="typed" is not a correction candidate.
        if not turn.get("human_origin"):
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

    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in SIGNAL_KINDS}
    for signal in _human_turn_signals(turn_sequence, session_id, mid_session=start_offset > 0):
        by_kind[signal["kind"]].append(signal)
    by_kind["struggle_arc"] = _struggle_arcs(attempts, turn_sequence, session_id)
    by_kind["conclusion"] = _conclusion_signals(
        turn_sequence, friction_events, by_kind["redirection"], by_kind["struggle_arc"], session_id
    )
    for cmd in abandon_commands:
        by_kind["abandoned_work"].append(
            {
                "kind": "abandoned_work",
                "session_id": session_id,
                "timestamp": cmd["timestamp"],
                "line": cmd["line"],
                "excerpt": make_excerpt(cmd["command"]),
                "context": make_excerpt(_preceding_assistant_text(turn_sequence, cmd["turn_index"]), CONTEXT_MAX_CHARS),
            }
        )
    by_kind["abandoned_work"].sort(key=lambda s: s["line"])
    signals = [s for kind in SIGNAL_KINDS for s in by_kind[kind][:MAX_SIGNALS_PER_KIND_PER_SESSION]]

    explored_targets = sorted(
        {t for t in (_relativize_target(raw, cwd) for raw in explore_raw) if t}
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
        "start_offset": start_offset,
        "end_offset": end_offset,
        "transcript_version": transcript_version,
        "started_at": started_at,
        "ended_at": ended_at,
        "friction_events": friction_events,
        "user_corrections": user_corrections,
        "signals": signals,
        "explored_targets": explored_targets,
        "pr_links": pr_links,
        "token_totals": token_totals,
        "cache_read_ratio": cache_read_ratio,
        "malformed_line_count": malformed_line_count,
        "tool_use_count": tool_use_count,
        "friction_field_presence": friction_field_presence,
        "turn_count": len(turn_sequence),
        "assistant_turn_count": sum(1 for t in turn_sequence if t.get("role") == "assistant"),
        "usage_field_presence": usage_field_presence,
        "parsed_line_count": len(lines),
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


def budget_signals(signals: list[dict[str, Any]], max_input_tokens: int) -> tuple[list[dict[str, Any]], int]:
    """Keep signals in SIGNAL_KINDS priority order (stable within a kind)
    until they use SIGNAL_BUDGET_FRACTION of `max_input_tokens`; drop the
    rest. Returns (kept, dropped_count)."""
    rank = {kind: i for i, kind in enumerate(SIGNAL_KINDS)}
    ordered = sorted(signals, key=lambda s: rank.get(s["kind"], len(rank)))
    cap = int(max_input_tokens * SIGNAL_BUDGET_FRACTION)
    kept: list[dict[str, Any]] = []
    used = 0
    for signal in ordered:
        cost = _estimate_tokens(signal)
        if used + cost > cap:
            break
        kept.append(signal)
        used += cost
    return kept, len(ordered) - len(kept)


def _rediscovery_signals(mined_sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read/Grep/Glob targets explored in two or more distinct sessions of
    one slug within this mining window. Most-repeated first."""
    by_slug: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for s in mined_sessions:
        sid = s.get("session_id") or s.get("transcript_path")
        for target in s.get("explored_targets") or []:
            hits = by_slug.setdefault(s.get("slug") or "", {}).setdefault(target, [])
            if all(h["id"] != sid for h in hits):
                hits.append({"id": sid, "session_id": s.get("session_id"), "at": s.get("started_at")})
    signals: list[dict[str, Any]] = []
    for slug in sorted(by_slug):
        repeated = [(t, h) for t, h in by_slug[slug].items() if len(h) >= 2]
        repeated.sort(key=lambda th: (-len(th[1]), th[0]))
        for target, hits in repeated[:MAX_REDISCOVERY_PER_SLUG]:
            signals.append(
                {
                    "kind": "rediscovery",
                    "session_id": hits[0]["session_id"],
                    "session_ids": [h["session_id"] for h in hits if h["session_id"]],
                    "timestamp": hits[0]["at"],
                    "excerpt": make_excerpt(f"Explored in {len(hits)} sessions: {target}"),
                }
            )
    return signals


# ---------------------------------------------------------------------------
# validate_structure() / schema_canary() -- fail loud on silent transcript-
# schema drift via a field-level structural contract (plan.md §3.2)
# ---------------------------------------------------------------------------


def validate_structure(mined_sessions: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Pure, batch-level structural contract over MinedSession dicts.

    Returns list[{"extraction", "field", "detail"}] -- an empty list means
    clean. Three hard invariants, each gated on a corroborating
    "should-be-present" signal so a genuinely quiet/thin window never
    trips a finding (adrev-015); a finding only fires when the WHOLE
    family of fields an extraction depends on is structurally absent
    across the entire batch:

      - friction_events: gated on total tool_use > 0; violated when zero
        recognized friction-bearing fields (is_error/toolUseResult/
        hookErrors/preventedContinuation) were found anywhere.
      - token_economics: gated on total assistant turns > 0 (NOT
        tool_use -- message.usage is read on every assistant line
        regardless of tool_use); violated when zero recognized
        token/cache usage fields were found anywhere.
      - turn_structure: gated on total parsed lines > 0 (NOT tool_use --
        this is what catches an envelope-`type` rename, which silently
        zeros tool_use_count too); violated when zero recognized
        user/assistant turns were found anywhere.

    A best-effort PR-link invariant (note-only, never raising) is
    deliberately NOT implemented here -- PR links are optional evidence,
    not integrity-critical (decision #4, accepted residual, plan.md
    §8.5/§11/decisions.md).

    Every counter is read via `.get(key, 0)`, so a MinedSession-shaped
    dict missing any counter (including a hand-built test dict) defaults
    to a non-raising state rather than raising a KeyError.

    Pure function: no I/O, never raises -- callers (schema_canary())
    decide whether a non-empty finding list means "raise".
    """
    total_tool_use = sum(s.get("tool_use_count", 0) for s in mined_sessions)
    total_friction_fields = sum(s.get("friction_field_presence", 0) for s in mined_sessions)
    total_assistant_turns = sum(s.get("assistant_turn_count", 0) for s in mined_sessions)
    total_usage_fields = sum(s.get("usage_field_presence", 0) for s in mined_sessions)
    total_parsed_lines = sum(s.get("parsed_line_count", 0) for s in mined_sessions)
    total_turns = sum(s.get("turn_count", 0) for s in mined_sessions)

    findings: list[dict[str, str]] = []

    if total_tool_use > 0 and total_friction_fields == 0:
        findings.append(
            {
                "extraction": "friction_events",
                "field": "is_error/toolUseResult/hookErrors/preventedContinuation",
                "detail": (
                    f"{total_tool_use} tool_use block(s) observed across "
                    f"{len(mined_sessions)} session(s) but zero recognized "
                    "friction-bearing fields were found anywhere in the window."
                ),
            }
        )

    if total_assistant_turns > 0 and total_usage_fields == 0:
        findings.append(
            {
                "extraction": "token_economics",
                "field": "message.usage.{input,output,cache_creation,cache_read}_tokens",
                "detail": (
                    f"{total_assistant_turns} assistant turn(s) observed across "
                    f"{len(mined_sessions)} session(s) but zero recognized token/cache "
                    "usage fields were found anywhere in the window."
                ),
            }
        )

    if total_parsed_lines > 0 and total_turns == 0:
        findings.append(
            {
                "extraction": "turn_structure",
                "field": "type (user/assistant)",
                "detail": (
                    f"{total_parsed_lines} parsed line(s) observed across "
                    f"{len(mined_sessions)} session(s) but zero recognized user/assistant "
                    "turns were found anywhere in the window."
                ),
            }
        )

    return findings


def schema_canary(mined_sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail loud when the transcript schema appears to have drifted.

    Delegates to validate_structure() for the field-level structural
    contract (three hard invariants: friction, token-economics,
    turn-structure -- see validate_structure()'s docstring). Raises
    SchemaDriftError naming every finding's extraction + field when the
    contract is violated; returns {"observed_versions": {version: count}}
    (informational only -- never gates the raise) when clean. Never
    returns silently on drift -- raises SchemaDriftError instead.
    """
    observed_versions: dict[str, int] = {}
    for s in mined_sessions:
        v = s.get("transcript_version")
        if v:
            observed_versions[v] = observed_versions.get(v, 0) + 1

    findings = validate_structure(mined_sessions)
    if findings:
        named = "; ".join(f"{f['extraction']} ({f['field']}): {f['detail']}" for f in findings)
        raise SchemaDriftError(
            f"schema_canary: structural drift detected -- {named} "
            f"(observed versions: {sorted(observed_versions) or ['unknown']}). "
            "This likely means the transcript schema drifted and the miner is "
            "silently reading incomplete evidence. Investigate before trusting "
            "an empty evidence bundle."
        )

    return {"observed_versions": observed_versions}


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


def _iter_slug_transcripts(slugs: Iterable[str], projects_root: str | Path | None):
    """Yield (path, resolved_slug) for every transcript under the projects
    root whose owning slug is in `slugs`."""
    root = Path(projects_root) if projects_root else Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return
    wanted = set(slugs)
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        for transcript_path in sorted(project_dir.glob("*.jsonl")):
            resolved_slug = _peek_slug(transcript_path)
            if resolved_slug is not None and resolved_slug in wanted:
                yield transcript_path, resolved_slug


def _has_new_content(path: Path, offset: int) -> bool:
    """True if the bytes at or after `offset` hold at least one complete
    line with a timestamp. Claude Code appends timestamp-less bookkeeping
    lines (file-history-snapshot) to old transcripts; those are not new
    evidence and must not make a mined file due again (R6)."""
    for _lineno, obj, _start, _end in _iter_jsonl(path, offset):
        if obj is not None and isinstance(obj.get("timestamp"), str):
            return True
    return False


def discover_with_offsets(
    slugs: Iterable[str],
    *,
    cursors: dict[str, dict[str, Any]] | None = None,
    projects_root: str | Path | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, int]:
    """Enumerate transcript files under ~/.claude/projects/*/ whose owning
    learnings-store slug is in `slugs` and that hold unmined content.
    Returns {path: byte offset to start mining from}.

    Slug identity is re-derived from EACH transcript's own `cwd` field via
    detect_project_slug() (arch-1) -- never from a ~/.claude/projects/
    directory-name heuristic (that directory is keyed by the encoded
    absolute cwd PATH, one per clone; multiple clones of the same repo
    share ONE learnings-store slug via git-remote resolution, so
    directory-name matching would silently miss sibling-clone evidence).

    cursors: {path: {"slug", "offset"}} from read_cursors(). A file is due
    when the bytes after its cursor hold a complete, timestamped line.
    A file whose current size is below its cursor was truncated or rotated
    and is re-read from 0. A file with no cursor starts at 0, bounded by
    the `lookback_days` mtime cutoff (so a machine with years of history is
    not mined in one pass -- Epic 3's `lookback_days`, plan.md §3.3).
    Slugs dreamed before cursors existed are seeded by
    migrate_watermarks_to_cursors() first.

    `projects_root` defaults to ~/.claude/projects; tests pass a temp dir
    so real transcripts are never touched.
    """
    cursors = cursors or {}
    cutoff = time.time() - lookback_days * 86400

    due: dict[str, int] = {}
    for transcript_path, _slug in _iter_slug_transcripts(slugs, projects_root):
        try:
            stat = transcript_path.stat()
        except OSError:
            continue
        key = str(transcript_path)
        cursor = cursors.get(key)
        if cursor is not None:
            offset = int(cursor.get("offset", 0))
            if stat.st_size < offset:
                offset = 0
            elif stat.st_size == offset:
                continue
        else:
            if stat.st_mtime < cutoff:
                continue
            offset = 0
        if _has_new_content(transcript_path, offset):
            due[key] = offset
    return due


def discover(
    slugs: Iterable[str],
    *,
    cursors: dict[str, dict[str, Any]] | None = None,
    projects_root: str | Path | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[str]:
    """discover_with_offsets() without the offsets: just the due paths."""
    return list(discover_with_offsets(
        slugs, cursors=cursors, projects_root=projects_root, lookback_days=lookback_days,
    ))


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

    The lock is taken on a STABLE sidecar file (`<path>.lock`), never on
    the watermark file itself. The watermark file's inode is discarded on
    every write by os.replace(); a lock held on that inode stops
    serializing the instant a later writer opens the *new* post-replace
    inode and flocks it without contention, so two writers can both hold
    "the lock" on different inodes, both read the same version, and clobber
    each other's read-modify-write -- dropping a DIFFERENT slug's advance
    under parallel load (#776). The sidecar's inode is never replaced or
    unlinked, so every writer contends on the one fd and the whole
    read-merge-write-replace section is genuinely serialized. The sidecar
    is created on demand (O_CREAT); a leftover lock file is harmless
    (flock releases on close), so it is never cleaned up.
    """
    path = watermark_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lock_path = path.with_name(path.name + ".lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
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


# ---------------------------------------------------------------------------
# Mining cursors (~/.claude/dreaming/state/mining-cursors.json)
#
# {"version": 1, "files": {transcript_path: {"slug": ..., "offset": N}}}
# `offset` is the byte position just past the last line mined from that
# file. The watermark (above) still orders slugs least-recently-dreamed
# first; it no longer decides what is new.
# ---------------------------------------------------------------------------


def cursors_path() -> Path:
    return _dreaming_dir() / "state" / "mining-cursors.json"


def read_cursors() -> dict[str, dict[str, Any]]:
    """{transcript_path: {"slug", "offset"}}; {} if absent or corrupt.
    Unlocked read -- write_cursors() swaps the file atomically."""
    path = cursors_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return {}
    return {
        k: v for k, v in files.items()
        if isinstance(v, dict) and isinstance(v.get("offset"), int) and not isinstance(v.get("offset"), bool)
    }


def write_cursors(slug: str, offsets: dict[str, int]) -> None:
    """Set the cursor for each {path: offset} under `slug`, keeping every
    other entry and dropping entries whose file no longer exists. Unlike
    write_watermark() it can lower an offset: a rotated file starts over.
    Same locking discipline as write_watermark(): flock on a stable sidecar,
    then tempfile + os.replace()."""
    if not offsets:
        return
    path = cursors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(path.with_name(path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            files = {k: v for k, v in read_cursors().items() if os.path.exists(k)}
            for transcript_path, offset in offsets.items():
                files[transcript_path] = {"slug": slug, "offset": int(offset)}
            payload = json.dumps({"version": 1, "files": files}, indent=2, sort_keys=True)
            tmp_fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
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


def _offset_after_watermark(path: Path, watermark_epoch: float) -> int:
    """Byte offset of the first line timestamped after the watermark, or
    the end of the consumable file if there is none."""
    end = 0
    for _lineno, obj, line_start, line_end in _iter_jsonl(path):
        ts = obj.get("timestamp") if obj is not None else None
        epoch = _iso_to_epoch(ts) if isinstance(ts, str) else None
        if epoch is not None and epoch > watermark_epoch:
            return line_start
        end = line_end
    return end


def plan_watermark_migration(
    slugs: Iterable[str], *, projects_root: str | Path | None = None,
) -> dict[str, dict[str, int]]:
    """{slug: {path: offset}} cursors that migrate_watermarks_to_cursors()
    would write. Pure: reads state, writes nothing (--dry-run uses it).

    Only slugs that have a last-dreamed.json watermark and no cursor
    entries yet are planned. Every transcript of such a slug gets an offset
    at its first line timestamped after the watermark (or end of file),
    including files that are not due, so a later night never mistakes them
    for new."""
    watermark = read_watermark()
    seeded = {c.get("slug") for c in read_cursors().values()}
    todo = [s for s in slugs if s in watermark and s not in seeded]
    plan: dict[str, dict[str, int]] = {}
    if not todo:
        return plan
    for transcript_path, slug in _iter_slug_transcripts(todo, projects_root):
        epoch = _iso_to_epoch(watermark[slug])
        if epoch is None:
            continue
        plan.setdefault(slug, {})[str(transcript_path)] = _offset_after_watermark(transcript_path, epoch)
    return plan


def migrate_watermarks_to_cursors(
    slugs: Iterable[str], *, projects_root: str | Path | None = None,
) -> None:
    """One-time, per slug: persist plan_watermark_migration(), so the first
    night after the upgrade does not re-mine history. Idempotent: a slug
    with cursors is never planned again."""
    for slug, per_file in plan_watermark_migration(slugs, projects_root=projects_root).items():
        write_cursors(slug, per_file)


def _utc_now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def mine_to_evidence_bundle(
    transcript_paths: Iterable[str | Path],
    *,
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
    start_offsets: dict[str, int] | None = None,
    end_offsets_out: dict[str, int] | None = None,
) -> dict[str, Any]:
    """End-to-end: mine() every path, run schema_canary(), cluster() the
    friction events, budget() them, assemble the evidence bundle.

    Returns the evidence-bundle dict (schema: lib/evidence-bundle-schema.json).
    start_offsets: {path: byte offset} to mine from (default 0 for every
    path). end_offsets_out: if given, filled with {path: offset just past the
    last line mined} -- the value to store as that file's cursor once the
    run consumes the bundle. Offsets stay out of the bundle itself because
    the bundle is sent to the model.
    Raises SchemaDriftError via schema_canary() if the transcript schema
    appears to have drifted (adrev-002) -- callers should NOT catch this
    silently; an empty evidence bundle from a drifted parser is worse
    than a loud failure.
    """
    start_offsets = start_offsets or {}
    mined_sessions = [mine(p, start_offsets.get(str(p), 0)) for p in transcript_paths]
    if end_offsets_out is not None:
        for mined in mined_sessions:
            end_offsets_out[mined["transcript_path"]] = mined["end_offset"]
    canary = schema_canary(mined_sessions)

    all_friction_events = [ev for s in mined_sessions for ev in s["friction_events"]]
    clustered = cluster(all_friction_events)
    # Signals are budgeted first; friction gets what they leave.
    all_signals = [sig for s in mined_sessions for sig in s["signals"]] + _rediscovery_signals(mined_sessions)
    signals, signals_dropped = budget_signals(all_signals, max_input_tokens)
    signal_tokens = _estimate_tokens(signals)
    budgeted = budget(clustered, max(max_input_tokens - signal_tokens, 1))
    token_estimate = budgeted["token_estimate"] + signal_tokens

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
            "turn_count": s["turn_count"],
            "assistant_turn_count": s["assistant_turn_count"],
            "usage_field_presence": s["usage_field_presence"],
            "parsed_line_count": s["parsed_line_count"],
        }
        for s in mined_sessions
    ]

    return {
        "generated_at": _utc_now_iso(),
        "slugs": slugs,
        "session_count": len(mined_sessions),
        "sessions": sessions_summary,
        "signals": signals,
        "signals_dropped": signals_dropped,
        "clusters": budgeted["clusters"],
        "friction_cluster_count": budgeted["friction_cluster_count"],
        "routine_cluster_count": budgeted["routine_cluster_count"],
        "token_estimate": token_estimate,
        "max_input_tokens": max_input_tokens,
        "over_budget": token_estimate > max_input_tokens,
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
