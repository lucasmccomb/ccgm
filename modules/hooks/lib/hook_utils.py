"""Shared utilities for CCGM Claude Code hooks.

Locked API (referenced from plan.md §5 Epic 1 and §3 architecture):

    read_hook_input() -> dict
    permission_mode(data: dict) -> str
    is_bypass_mode(data: dict) -> bool
    emit_decision(decision: str, reason: str) -> None
    hard_block(reason: str) -> NoReturn
    redact_secrets(text: str) -> str
    file_locked_append(path: str, data: str) -> None
    load_repo_config(cwd: str) -> dict

The module is installed at ~/.claude/lib/hook_utils.py by CCGM's installer.
Hooks import it via `sys.path.insert(0, os.path.expanduser("~/.claude/lib"))`
followed by `import hook_utils`.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from typing import NoReturn

__all__ = [
    "read_hook_input",
    "permission_mode",
    "is_bypass_mode",
    "emit_decision",
    "hard_block",
    "redact_secrets",
    "file_locked_append",
    "load_repo_config",
    "BYPASS_MODES",
    "SECRET_PATTERNS",
]


BYPASS_MODES = frozenset({"bypassPermissions", "dontAsk", "auto"})


def read_hook_input() -> dict:
    """Read and parse JSON from stdin. Returns {} on parse failure.

    Hooks that need stdin in a strict mode should check the return value
    themselves; this helper never raises so that a malformed payload
    cannot wedge an enforcement hook into an error state.
    """
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, EOFError):
        return {}


def permission_mode(data: dict) -> str:
    """Return the permission_mode field from hook stdin, or 'default'.

    Claude Code passes one of: 'default', 'acceptEdits', 'plan',
    'bypassPermissions', 'dontAsk', 'auto'. Older clients may omit it.
    """
    mode = data.get("permission_mode")
    if isinstance(mode, str) and mode:
        return mode
    return "default"


def is_bypass_mode(data: dict) -> bool:
    """True iff the session is in a bypass-permission mode.

    Treats bypassPermissions, dontAsk, and auto as bypass. Conservative
    default: any unknown / missing mode is treated as NON-bypass so a
    suppressible safety check still fires when in doubt.
    """
    return permission_mode(data) in BYPASS_MODES


def emit_decision(decision: str, reason: str) -> None:
    """Emit a PreToolUse JSON decision and exit 0.

    `decision` must be one of 'allow', 'deny', 'ask'. The hook process
    terminates after this call — callers should not assume control
    returns.
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()
    sys.exit(0)


def hard_block(reason: str) -> NoReturn:
    """Bypass-proof hard block. Writes reason to stderr and exits 2.

    GitHub issue #39344: `permissionDecision: 'ask'` from any PreToolUse
    hook silently overrides declarative deny rules. The only mechanism
    that survives bypass mode is `exit 2`, which Claude Code treats as a
    hard block regardless of permission_mode.

    Use this for data-integrity invariants and protected-branch
    enforcement that MUST hold even in bypass sessions.
    """
    sys.stderr.write(reason.rstrip() + "\n")
    sys.stderr.flush()
    sys.exit(2)


# 17 secret patterns. Order matters only insofar as longer / more specific
# patterns come first so they win when a substring would match multiple.
# Each entry is (name, compiled regex). The replacement is always
# "[REDACTED:{name}]" so downstream readers can identify the kind without
# re-scanning. Patterns target prefix shapes published by each vendor.
_SECRET_PATTERN_SOURCES: list[tuple[str, str]] = [
    # Anthropic API keys (legacy and api03-prefixed).
    ("anthropic", r"sk-ant-(?:api03-)?[A-Za-z0-9_\-]{32,}"),
    # Stripe live/test secret keys.
    ("stripe_live", r"sk_live_[A-Za-z0-9]{16,}"),
    ("stripe_test", r"sk_test_[A-Za-z0-9]{16,}"),
    # GitHub token families (PAT, OAuth, user-to-server, server-to-server, refresh).
    ("github_pat", r"ghp_[A-Za-z0-9]{30,}"),
    ("github_oauth", r"gho_[A-Za-z0-9]{30,}"),
    ("github_u2s", r"ghu_[A-Za-z0-9]{30,}"),
    ("github_s2s", r"ghs_[A-Za-z0-9]{30,}"),
    ("github_refresh", r"ghr_[A-Za-z0-9]{30,}"),
    # AWS access key.
    ("aws_access_key", r"AKIA[0-9A-Z]{16}"),
    # Google API key.
    ("google_api", r"AIza[0-9A-Za-z_\-]{35}"),
    # Slack tokens.
    ("slack", r"xox[abprs]-[0-9A-Za-z\-]{10,}"),
    # Resend.
    ("resend", r"re_[A-Za-z0-9]{8,}_[A-Za-z0-9]{16,}"),
    # Supabase service-role and publishable keys (modern prefixed shape).
    ("supabase", r"sb_(?:secret|publishable)_[A-Za-z0-9]{20,}"),
    # OpenAI (generic sk- form, after Anthropic and Stripe have eaten theirs).
    ("openai", r"sk-(?!ant-)(?!live_)(?!test_)[A-Za-z0-9]{32,}"),
    # Authorization: Bearer ... header (covers most generic bearer tokens).
    ("authorization_bearer", r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._\-]+"),
    # env-var style KV assignments naming common secret keys.
    (
        "env_var_kv",
        r"(?i)\b(?:api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|"
        r"client[_-]?secret|secret[_-]?key|password|passwd)\s*[=:]\s*['\"]?[A-Za-z0-9_\-/+=.]{12,}",
    ),
    # CLI password flag (--password / -p with a value following).
    ("password_flag", r"(?<!\S)(?:--password|--passwd|-p)[=\s]+\S{6,}"),
]

# Compile once at import.
SECRET_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    (name, re.compile(pat)) for name, pat in _SECRET_PATTERN_SOURCES
]


def redact_secrets(text: str) -> str:
    """Replace any secret-shaped token in `text` with [REDACTED:{kind}].

    Applied to event log entries BEFORE truncation so the truncation
    point can never lop a redaction marker in half. Conservative: a
    pattern with broad-ish shape (env_var_kv) is fine to over-fire —
    false positives in logs cost much less than leaked secrets.
    """
    if not text:
        return text
    out = text
    for name, regex in SECRET_PATTERNS:
        out = regex.sub(f"[REDACTED:{name}]", out)
    return out


def file_locked_append(path: str, data: str) -> None:
    """Append `data` (with trailing newline) to `path`, fcntl-locked.

    Cross-clone-safe: multiple Claude Code agents in different repo
    clones may race on the same `~/.claude/autoheal/events/*.jsonl`
    path. fcntl.flock(LOCK_EX) on the open file descriptor serializes
    appends so the JSONL never truncates mid-record.

    POSIX-portable. macOS + Linux supported. Creates parent dir if
    missing. Never raises on lock contention — blocks until acquired.
    """
    payload = data if data.endswith("\n") else data + "\n"
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Open with O_APPEND so writes always land at end-of-file even
    # under contention. Combined with flock(LOCK_EX), this is the
    # standard POSIX recipe for atomic concurrent append.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def load_repo_config(cwd: str | None = None) -> dict:
    """Walk up from cwd looking for `.autoheal/config.json`. Return merged config.

    The walk stops at the first repo root that contains the file or at
    the filesystem root. Returns {} when no config is found.

    Schema (validated lightly here; full schema in
    `modules/autoheal/lib/repo-config-schema.json` for Epic 12):

        {
          "additional_allow_patterns": [str, ...],
          "calibration_days": int,
          "thresholds": {"confidence_min": int, "occurrence_min": int},
          "kind_filters": [str, ...]
        }

    Unknown top-level keys are preserved (forward-compat) but only the
    documented fields are consumed by downstream code.
    """
    here = os.path.abspath(cwd or os.getcwd())
    seen: set[str] = set()
    while here and here not in seen:
        seen.add(here)
        candidate = os.path.join(here, ".autoheal", "config.json")
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    cfg = json.load(fh)
                if isinstance(cfg, dict):
                    return cfg
            except (OSError, json.JSONDecodeError):
                # Treat a malformed repo config as if it did not exist;
                # a hook is not the right place to fail loudly on user
                # JSON typos.
                return {}
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return {}
