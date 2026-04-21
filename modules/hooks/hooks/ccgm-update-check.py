#!/usr/bin/env python3
"""
UserPromptSubmit hook: daily CCGM health check (upstream + install drift).

On the first prompt of each day:
  1. Check the CCGM remote for new commits and warn if updates are available.
  2. Audit install drift: verify every file the manifest claims is installed
     actually exists on disk (and symlinks resolve).

Both checks print warnings to stderr. A single daily flag file gates both so
subsequent prompts skip the work entirely.

Disable via CCGM_AUTO_UPDATE_CHECK=false in ~/.claude/.ccgm.env.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

MANIFEST_FILE = Path.home() / ".claude" / ".ccgm-manifest.json"
ENV_FILE = Path.home() / ".claude" / ".ccgm.env"
FLAG_DIR = Path(tempfile.gettempdir())


def is_enabled() -> bool:
    """Check if auto-update check is enabled in .ccgm.env."""
    if not ENV_FILE.exists():
        return False
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("CCGM_AUTO_UPDATE_CHECK="):
                    value = line.split("=", 1)[1].strip().lower()
                    return value in ("true", "1", "yes")
    except (OSError, IOError):
        pass
    return False


def already_checked_today() -> bool:
    """Check if we already ran the update check today."""
    flag_file = FLAG_DIR / f".ccgm-update-check-{date.today().isoformat()}"
    if flag_file.exists():
        return True
    # Create flag file for today, clean up old ones
    for old_flag in FLAG_DIR.glob(".ccgm-update-check-*"):
        try:
            old_flag.unlink()
        except OSError:
            pass
    try:
        flag_file.touch()
    except OSError:
        pass
    return False


def get_ccgm_root() -> str | None:
    """Read the CCGM clone path from the manifest."""
    if not MANIFEST_FILE.exists():
        return None
    try:
        with open(MANIFEST_FILE) as f:
            manifest = json.load(f)
            return manifest.get("ccgmRoot")
    except (json.JSONDecodeError, OSError):
        return None


def check_install_drift() -> list[str]:
    """Return a list of manifest-claimed files that are missing from disk.

    A file is "missing" if its path does not exist. For symlinks, the
    symlink itself must resolve to an existing target. Returns file paths
    (max 10) so output stays readable.
    """
    if not MANIFEST_FILE.exists():
        return []
    try:
        with open(MANIFEST_FILE) as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    missing: list[str] = []
    for entry in manifest.get("files", []):
        p = Path(entry)
        # Path.exists() follows symlinks, so a dangling symlink shows as missing.
        if not p.exists():
            missing.append(entry)
            if len(missing) >= 10:
                break
    return missing


def check_for_updates(ccgm_root: str) -> int:
    """Fetch remote and count new commits on main."""
    try:
        # Fetch latest (quiet, fast)
        subprocess.run(
            ["git", "fetch", "origin", "--quiet"],
            cwd=ccgm_root,
            capture_output=True,
            timeout=10,
        )
        # Count commits ahead on remote
        result = subprocess.run(
            ["git", "rev-list", "HEAD..origin/main", "--count"],
            cwd=ccgm_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            return count
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError):
        pass
    return 0


def main() -> None:
    # Read stdin (required by hook contract) but we don't use it
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    # Quick exit paths
    if not is_enabled():
        return

    if already_checked_today():
        return

    ccgm_root = get_ccgm_root()
    if not ccgm_root or not Path(ccgm_root).is_dir():
        return

    count = check_for_updates(ccgm_root)
    if count > 0:
        s = "s" if count != 1 else ""
        print(
            f"\n  CCGM: {count} update{s} available. "
            f"Run: cd {ccgm_root} && ./update.sh\n",
            file=sys.stderr,
        )

    drift = check_install_drift()
    if drift:
        more = ""
        if len(drift) >= 10:
            more = " (more truncated)"
        print(
            f"\n  CCGM install drift: {len(drift)} manifest-claimed "
            f"file(s) missing from disk{more}:",
            file=sys.stderr,
        )
        for path in drift:
            print(f"    - {path}", file=sys.stderr)
        print(
            "  Resolve by re-running the relevant module install, or "
            "prune the manifest via /ccgm-sync.\n",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
