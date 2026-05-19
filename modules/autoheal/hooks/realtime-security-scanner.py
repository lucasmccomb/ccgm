#!/usr/bin/env python3
"""Real-time security scanner (Epic 10).

Registered on PostToolUse via settings.partial.json. Reads
~/.claude/autoheal/config.json -> realtime_alerts_enabled. If the flag is
false or missing the hook is a strict no-op (sys.exit(0) BEFORE the
patterns file is even read). Only when the user has explicitly opted in
does the scanner load the 7 patterns from
modules/autoheal/lib/realtime-security-patterns.json (installed to
~/.claude/lib/realtime-security-patterns.json) and scan the Bash command
for matches.

On match the scanner:
  1. Logs a realtime_security_alert event via
     hook_utils.file_locked_append to today's events JSONL.
  2. Writes a <autoheal-security-alert> block to stderr.
  3. Exits 2 with a JSON deny envelope.

Runtime contract (plan.md §3.6 / §5 Epic 10): the registration was
intended to carry `async: true, asyncRewake: true` so the exit-2 wakes
Claude mid-session with a system reminder. The current Epic 3
settings.partial.json registration omits those flags; Epic 10 has no
license to edit settings.partial.json so this scanner ships correct
behaviour for the asyncRewake contract and the parent epic owner can
add the flags as a follow-up. See DONE_WITH_CONCERNS in the Epic 10
PR description.

Guards (see plan.md §3.6 schema):
  - ALLOW_MAIN_COMMIT_unset: only flag if env var ALLOW_MAIN_COMMIT != "1".
    Honours the user's explicit bypass intent for force-push to main.
  - production_connection_string: only flag if the command contains a
    token suggesting a production target (prod, production, live). This
    keeps DROP TABLE in a test fixture from waking Claude.

Scope rules:
  - Only acts on Bash tool calls. Other tools have their own surfaces;
    the patterns target command strings, not Edit/Write content.
  - Defensive: a malformed config, a missing patterns file, a bad JSON
    payload — all degrade to sys.exit(0). NEVER raises into the hook
    pipeline. The scanner failing closed would create a worse footgun
    than missing one alert.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402


# Default location of the patterns file once installed. Tests override
# via CCGM_REALTIME_PATTERNS so they can point at the in-repo source.
_DEFAULT_PATTERNS_PATH = os.path.expanduser(
    "~/.claude/lib/realtime-security-patterns.json"
)

# Tokens that suggest a production database target. Conservative match —
# we want false positives (an extra alert) over false negatives (no
# alert on a real prod DROP).
_PRODUCTION_TOKENS = ("prod", "production", "live")


def _autoheal_dir() -> str:
    override = os.environ.get("CCGM_AUTOHEAL_DIR")
    if override:
        return override
    return os.path.expanduser("~/.claude/autoheal")


def _config_path() -> str:
    return os.path.join(_autoheal_dir(), "config.json")


def _patterns_path() -> str:
    override = os.environ.get("CCGM_REALTIME_PATTERNS")
    if override:
        return override
    return _DEFAULT_PATTERNS_PATH


def _today_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _is_enabled() -> bool:
    """Read realtime_alerts_enabled from ~/.claude/autoheal/config.json.

    Returns True ONLY when the config exists, is valid JSON, and has the
    key set to True. Any other shape returns False — the scanner is
    OPT-IN and the default posture is OFF.
    """
    path = _config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(cfg, dict):
        return False
    return cfg.get("realtime_alerts_enabled") is True


def _load_patterns() -> list[dict]:
    """Load patterns from disk. Returns [] if the file is missing or bad.

    This is only called AFTER the enabled gate has returned True, so a
    missing patterns file in disabled state never costs a syscall.
    """
    try:
        with open(_patterns_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    patterns = data.get("patterns") if isinstance(data, dict) else None
    if not isinstance(patterns, list):
        return []
    return patterns


def _guard_allows_alert(guard: str | None, command: str) -> bool:
    """Apply the per-pattern guard.

    Returns True when the guard PERMITS the alert to fire (no guard set,
    or guard condition satisfied). Returns False when the guard
    SUPPRESSES the alert (e.g., ALLOW_MAIN_COMMIT=1 means the user
    explicitly intends to force-push to main).
    """
    if not guard:
        return True
    if guard == "ALLOW_MAIN_COMMIT_unset":
        return os.environ.get("ALLOW_MAIN_COMMIT") != "1"
    if guard == "production_connection_string":
        lowered = command.lower()
        return any(tok in lowered for tok in _PRODUCTION_TOKENS)
    # Unknown guard: fail open (allow the alert). An unknown guard in
    # the patterns file is a config error, not a license to silently
    # skip security checks.
    return True


def _is_bash_call(data: dict) -> bool:
    """The patterns target Bash command strings. Other tools are skipped."""
    tool_name = data.get("tool_name")
    return isinstance(tool_name, str) and tool_name == "Bash"


def _scan_command(command: str, patterns: list[dict]) -> dict | None:
    """Walk the pattern list; return the first match record or None."""
    for entry in patterns:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        regex_src = entry.get("regex")
        if not isinstance(name, str) or not isinstance(regex_src, str):
            continue
        try:
            pattern = re.compile(regex_src)
        except re.error:
            # Bad regex in the patterns file is a config bug. Skip it.
            continue
        if not pattern.search(command):
            continue
        guard = entry.get("guard")
        if not isinstance(guard, str):
            guard = None
        if not _guard_allows_alert(guard, command):
            continue
        severity = entry.get("severity")
        if not isinstance(severity, str):
            severity = "high"
        return {
            "name": name,
            "severity": severity,
            "guard": guard,
        }
    return None


def _log_alert(data: dict, match: dict, command: str) -> None:
    """Append a realtime_security_alert record to today's events JSONL.

    The redacted_command is truncated to 500 chars matching the
    permission-event-logger schema. Errors are swallowed — the alert
    surface (stderr + exit 2) is the primary signal; the log is the
    audit trail.
    """
    try:
        # Redact secrets BEFORE truncation so a partial marker can never
        # leak. The pattern that fired may itself BE a secret (ghp_,
        # AKIA, sk-ant-) so this is double protection.
        redacted = hook_utils.redact_secrets(command)
        if len(redacted) > 500:
            redacted = redacted[:495] + "[...]"
        record = {
            "kind": "realtime_security_alert",
            "timestamp": _now_iso(),
            "session_id": str(data.get("session_id", "")),
            "tool_name": "Bash",
            "redacted_command": redacted,
            "exit_code": None,
            "stderr_excerpt": None,
            "permission_decision": None,
            "cwd": data.get("cwd"),
            "clone_path": data.get("cwd"),
            "security_pattern_matched": match["name"],
        }
        target = os.path.join(
            _autoheal_dir(), "events", _today_iso() + ".jsonl"
        )
        hook_utils.file_locked_append(target, json.dumps(record))
    except Exception:
        # Logging failure must not block the alert. Stay loud on stderr.
        pass


def _emit_alert(match: dict) -> None:
    """Write the deny envelope + system reminder, then exit 2.

    The JSON envelope is written to stdout for Claude Code's PostToolUse
    deny path. The <autoheal-security-alert> block is written to stderr
    so it surfaces in the session as a system reminder when the hook is
    registered with asyncRewake: true.

    NEVER include the matched command text in the alert. We name the
    pattern (which is descriptive enough) so a malicious command cannot
    be replayed into Claude's context via the alert payload.
    """
    severity = match.get("severity", "high")
    name = match["name"]
    reminder = (
        "<autoheal-security-alert>\n"
        f"severity: {severity}\n"
        f"pattern: {name}\n"
        "A high-confidence security pattern fired on the last Bash call. "
        "Pause and confirm with the user before continuing. If this is a "
        "false positive, the user can run `/autoheal-toggle realtime off` "
        "to disable real-time alerts.\n"
        "</autoheal-security-alert>\n"
    )
    sys.stderr.write(reminder)
    sys.stderr.flush()

    envelope = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"autoheal-security-alert: {name} ({severity})"
            ),
        }
    }
    try:
        json.dump(envelope, sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()
    except Exception:
        pass
    sys.exit(2)


def main() -> None:
    # 1. Default-OFF gate. NEVER scan when the flag is not explicitly true.
    if not _is_enabled():
        sys.exit(0)

    # 2. Read hook input. Malformed JSON: exit 0 (never block).
    try:
        data = hook_utils.read_hook_input()
    except Exception:
        sys.exit(0)

    # 3. Only act on Bash. Other tool families have different surfaces.
    if not _is_bash_call(data):
        sys.exit(0)

    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        sys.exit(0)

    # 4. Load patterns AFTER the enabled gate so a disabled config never
    # touches the patterns file.
    patterns = _load_patterns()
    if not patterns:
        sys.exit(0)

    # 5. Scan. Defensive against any unhandled exception path.
    try:
        match = _scan_command(command, patterns)
    except Exception:
        sys.exit(0)
    if match is None:
        sys.exit(0)

    # 6. Log + alert. _emit_alert exits 2.
    _log_alert(data, match, command)
    _emit_alert(match)


if __name__ == "__main__":
    main()
