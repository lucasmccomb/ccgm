#!/usr/bin/env python3
"""
Stop hook: post-prompt introspection for autoheal friction signals.

At the end of each Claude Code turn, scan today's events.jsonl for
permission_request and tool_failure events captured in THIS session and
look for repeated friction signatures (same tool + same command prefix).
If at least two same-signature events are observed, emit a one-line
suggestion pointing the user at `/permission-fix latest`.

Goals:
  - Never block. Stop hooks must not interfere with end-of-turn flow.
  - Cheap: a single JSONL read filtered to one session id. No API call.
  - Dedup per session: don't surface the same friction signature twice
    in one session. State lives in /tmp/ccgm-autoheal-{session_id}-introspect-seen.txt
    so it survives across turns but evaporates with /tmp on reboot.
  - Scoped strictly to the current session: cross-session events do not
    trigger the suggestion. Other clones doing the same dangerous thing
    are someone else's problem this turn.

Environment overrides (for tests):
  - CCGM_AUTOHEAL_EVENTS_DIR  — directory containing {today}.jsonl;
    default ~/.claude/autoheal/events
  - CCGM_AUTOHEAL_SEEN_DIR    — directory containing the per-session
    seen sentinels; default /tmp
  - CCGM_AUTOHEAL_TODAY       — YYYY-MM-DD override; default today UTC

Output:
  - Exit 0 unconditionally.
  - When the threshold is crossed, the suggestion is written to stderr.
    Claude Code surfaces Stop-hook stderr to the user, so a brief
    `<autoheal-suggestion>...</autoheal-suggestion>` block reaches them
    without requiring a specific Stop-hook JSON shape.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

# Locked friction kinds. permission_request fires when the user is asked
# to approve a tool call; tool_failure fires on a non-zero exit from a
# PostToolUseFailure event. Both indicate a tool call did not glide
# through, which is exactly what autoheal tries to surface and dedupe.
FRICTION_KINDS = frozenset({"permission_request", "tool_failure"})

# Minimum same-signature occurrences in the current session before we
# bother the user with a suggestion. Two is intentionally low: the
# point of the Stop hook is to catch friction the moment it repeats.
MIN_OCCURRENCES = 2


def _today_str() -> str:
    """Return YYYY-MM-DD for today (UTC), honoring CCGM_AUTOHEAL_TODAY."""
    override = os.environ.get("CCGM_AUTOHEAL_TODAY")
    if override:
        return override
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def _events_path() -> str:
    """Resolve today's events JSONL path, honoring env overrides."""
    base = os.environ.get("CCGM_AUTOHEAL_EVENTS_DIR") or os.path.expanduser(
        "~/.claude/autoheal/events"
    )
    return os.path.join(base, _today_str() + ".jsonl")


def _seen_path(session_id: str) -> str:
    """Resolve the per-session sentinel path for already-suggested signatures."""
    base = os.environ.get("CCGM_AUTOHEAL_SEEN_DIR") or "/tmp"
    # Defensive: session id may contain slashes in some clients; sanitize.
    safe = session_id.replace("/", "_").replace("\\", "_") or "unknown"
    return os.path.join(base, f"ccgm-autoheal-{safe}-introspect-seen.txt")


def _command_prefix(command: str | None) -> str:
    """
    Return a short canonical prefix of a Bash command for friction grouping.

    `git push --force origin main` and `git push --force origin feat-x`
    should share a signature; `git status` should not. We take the first
    three whitespace-separated tokens after light normalization. The
    upstream command is already secret-redacted and length-capped by
    permission-event-logger.py.
    """
    if not command:
        return ""
    tokens = command.strip().split()
    if not tokens:
        return ""
    return " ".join(tokens[:3])


def _friction_signature(event: dict) -> str | None:
    """
    Build a stable friction signature for an event, or None to skip.

    Same tool + same command prefix => same signature. We avoid hashing
    longer command tails so functionally identical commands (a different
    target branch, a different file path) still cluster together.
    """
    kind = event.get("kind")
    if kind not in FRICTION_KINDS:
        return None
    tool = event.get("tool_name") or ""
    if not tool:
        return None
    if tool == "Bash":
        prefix = _command_prefix(event.get("redacted_command"))
        if not prefix:
            return None
        return f"{tool}::{prefix}"
    # For non-Bash tools, the tool name alone is the signature shape.
    # Two repeated PermissionRequest events for Write or Edit are still
    # friction worth flagging.
    return f"{tool}::"


def _read_events(path: str) -> list[dict]:
    """Read JSONL events; tolerate missing file and malformed lines."""
    if not os.path.isfile(path):
        return []
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    # Skip malformed lines; don't fail the Stop hook.
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return []
    return out


def _load_seen(path: str) -> set[str]:
    """Load the set of already-suggested signatures for this session."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except OSError:
        return set()


def _mark_seen(path: str, signature: str) -> None:
    """Append a signature to the seen file. Best-effort: never raises."""
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(signature + "\n")
    except OSError:
        # Dedup is a nice-to-have; failing to record a seen entry just
        # means the next Stop fires the same suggestion again. That is
        # noisy but not broken.
        pass


def _find_repeated_signature(
    events: list[dict], session_id: str, seen: set[str]
) -> str | None:
    """
    Return the first repeated friction signature in this session that
    has not yet been surfaced, or None.

    Iteration order follows the JSONL order (chronological by append),
    so the "first" repeated signature is the earliest one to cross the
    threshold within the current turn's worth of events.
    """
    counts: dict[str, int] = {}
    first_to_cross: str | None = None
    for evt in events:
        if evt.get("session_id") != session_id:
            continue
        sig = _friction_signature(evt)
        if not sig:
            continue
        counts[sig] = counts.get(sig, 0) + 1
        if counts[sig] >= MIN_OCCURRENCES and sig not in seen:
            first_to_cross = sig
            break
    return first_to_cross


def _emit_suggestion(signature: str) -> None:
    """
    Write a brief, tagged suggestion to stderr.

    Claude Code surfaces Stop-hook stderr to the user. We wrap the
    suggestion in `<autoheal-suggestion>` tags so downstream tooling
    (or a follow-up rule) can recognise it.
    """
    # Paraphrase the signature; never echo the full redacted command.
    # The point of the prompt is "we noticed friction repeating", not
    # "here is the exact thing you ran." That keeps log-injection
    # attack surface flat: even if a malicious command got into
    # redacted_command, we never replay tokens of it to the user.
    tool, _, _ = signature.partition("::")
    msg = (
        f"<autoheal-suggestion>\n"
        f"Repeated friction detected with `{tool}` tool this session. "
        f"Run `/permission-fix latest` to see a proposed fix.\n"
        f"</autoheal-suggestion>\n"
    )
    sys.stderr.write(msg)
    sys.stderr.flush()


def main() -> None:
    # Read Stop hook input. Never raise on malformed stdin.
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, EOFError):
        data = {}

    # Stop hooks may receive a "stop_hook_active" flag to indicate a
    # loop is in progress. Respect it: do nothing extra during loops.
    if data.get("stop_hook_active"):
        sys.exit(0)

    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        # Without a session id we cannot scope the search safely.
        sys.exit(0)

    events_path = _events_path()
    events = _read_events(events_path)
    if not events:
        sys.exit(0)

    seen_path = _seen_path(session_id)
    seen = _load_seen(seen_path)

    signature = _find_repeated_signature(events, session_id, seen)
    if not signature:
        sys.exit(0)

    _emit_suggestion(signature)
    _mark_seen(seen_path, signature)
    sys.exit(0)


if __name__ == "__main__":
    main()
