#!/usr/bin/env python3
"""
PreToolUse hook that steers agents away from unranged Reads of large files.

A Read with no `offset` and no `limit` of a file over the line or byte
threshold is denied once per file per session, with a message suggesting Grep
or a ranged Read. A repeat full Read of the same file in the same session is
allowed, so a deliberate full read still works.

Never blocks: images, PDFs, notebooks, binaries (NUL byte in the first 8 KB),
missing or unreadable files, and any internal error (fails open).

Environment:
  CCGM_READ_BUDGET=off          disable the hook
  CCGM_READ_BUDGET_LINES=N      line threshold (default 2000)
  CCGM_READ_BUDGET_BYTES=N      byte threshold (default 102400)
  CCGM_READ_BUDGET_STATE_DIR    state directory (default: system temp dir)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

DEFAULT_LINES = 2000
DEFAULT_BYTES = 100 * 1024
SNIFF_BYTES = 8192
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif",
    ".ico", ".heic", ".svg", ".pdf", ".ipynb",
}


def env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def exceeds_budget(path: str, max_lines: int, max_bytes: int) -> bool:
    """True if the text file at `path` is over either threshold.

    Returns False for binaries and for anything that is not a regular file.
    Stops counting lines once past the threshold.
    """
    if not os.path.isfile(path):
        return False
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if b"\0" in f.read(SNIFF_BYTES):
            return False
        if size > max_bytes:
            return True
        f.seek(0)
        lines = 0
        for _ in f:
            lines += 1
            if lines > max_lines:
                return True
    return False


def state_file(session_id: str) -> str:
    base = os.environ.get("CCGM_READ_BUDGET_STATE_DIR") or os.path.join(
        tempfile.gettempdir(), f"ccgm-read-budget-{os.getuid()}"
    )
    os.makedirs(base, mode=0o700, exist_ok=True)
    name = hashlib.sha256(session_id.encode()).hexdigest()[:32]
    return os.path.join(base, name)


def already_warned(session_id: str, path: str) -> bool:
    """Record `path` for this session; return True if it was recorded before."""
    key = hashlib.sha256(path.encode()).hexdigest()
    fpath = state_file(session_id)
    try:
        with open(fpath) as f:
            if key in f.read().split():
                return True
    except FileNotFoundError:
        pass
    with open(fpath, "a") as f:
        f.write(key + "\n")
    return False


def main() -> None:
    try:
        if os.environ.get("CCGM_READ_BUDGET", "").lower() == "off":
            return
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Read":
            return
        tool_input = data.get("tool_input") or {}
        if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
            return
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            return
        path = os.path.abspath(os.path.expanduser(file_path))
        if os.path.splitext(path)[1].lower() in SKIP_EXTENSIONS:
            return
        max_lines = env_int("CCGM_READ_BUDGET_LINES", DEFAULT_LINES)
        max_bytes = env_int("CCGM_READ_BUDGET_BYTES", DEFAULT_BYTES)
        if not exceeds_budget(path, max_lines, max_bytes):
            return
        if already_warned(str(data.get("session_id") or "no-session"), path):
            return
    except Exception:
        return  # fail open

    reason = (
        f"{file_path} is large (over {max_lines} lines or {max_bytes // 1024} KB) "
        "and this Read has no range. A full Read may be cut off and cost a lot "
        "of context. Use Grep to find what you need, or Read with offset and "
        "limit. If you do need the whole file, repeat the same Read: the "
        "repeat full Read will be allowed."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
    sys.exit(0)
