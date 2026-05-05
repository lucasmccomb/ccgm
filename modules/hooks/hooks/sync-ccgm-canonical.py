#!/usr/bin/env python3
"""
PostToolUse:Bash hook — sync the canonical CCGM clone after a CCGM PR merges.

Why: ~/.claude/ symlinks point at one canonical CCGM checkout. When PRs merge
in workspace clones, that canonical checkout drifts unless something pulls it.
This hook removes the manual sync step.

Triggers when:
- The Bash command was `gh pr merge ...`
- The cwd's git remote points at a repo named "ccgm" (any owner)
- The canonical clone exists at $CCGM_CANONICAL_DIR (default ~/code/ccgm)

Behavior:
- Runs `git fetch origin main && git pull --ff-only origin main` in the
  canonical clone
- Logs success/failure to stderr
- Never blocks on errors (always exit 0)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys


CANONICAL_DIR_ENV = "CCGM_CANONICAL_DIR"
DEFAULT_CANONICAL_DIR = os.path.expanduser("~/code/ccgm")
CCGM_REPO_NAME = "ccgm"


def get_origin_url(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def is_ccgm_repo(cwd: str) -> bool:
    url = get_origin_url(cwd)
    if not url:
        return False
    # Extract repo name from URL (last path segment, strip .git)
    repo_name = re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1])
    return repo_name == CCGM_REPO_NAME


def sync_canonical(canonical_dir: str) -> tuple[bool, str]:
    """Pull origin/main into canonical_dir. Returns (success, message)."""
    if not os.path.isdir(os.path.join(canonical_dir, ".git")):
        return False, f"canonical dir not a git repo: {canonical_dir}"

    try:
        fetch = subprocess.run(
            ["git", "-C", canonical_dir, "fetch", "origin", "main"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if fetch.returncode != 0:
            return False, f"fetch failed: {fetch.stderr.strip()}"

        pull = subprocess.run(
            ["git", "-C", canonical_dir, "pull", "--ff-only", "origin", "main"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if pull.returncode != 0:
            return False, f"pull failed (not fast-forward?): {pull.stderr.strip()}"

        return True, pull.stdout.strip().splitlines()[-1] if pull.stdout.strip() else "up to date"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except (subprocess.SubprocessError, OSError) as e:
        return False, str(e)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command", "")
    if not re.match(r"\s*gh\s+pr\s+merge(\s|$)", command):
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    if not is_ccgm_repo(cwd):
        sys.exit(0)

    canonical_dir = os.environ.get(CANONICAL_DIR_ENV, DEFAULT_CANONICAL_DIR)
    if not os.path.isdir(canonical_dir):
        sys.stderr.write(
            f"sync-ccgm-canonical: skipped — {canonical_dir} does not exist "
            f"(set {CANONICAL_DIR_ENV} or create the dir)\n"
        )
        sys.exit(0)

    if os.path.realpath(cwd) == os.path.realpath(canonical_dir):
        sys.exit(0)

    ok, msg = sync_canonical(canonical_dir)
    prefix = "sync-ccgm-canonical"
    if ok:
        sys.stderr.write(f"{prefix}: {canonical_dir} → {msg}\n")
    else:
        sys.stderr.write(f"{prefix}: FAILED — {msg}\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
