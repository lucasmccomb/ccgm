#!/usr/bin/env python3
"""
PostToolUse:Bash hook — sync the canonical CCGM clone after a CCGM PR merges.

Why: ~/.claude/ symlinks point at one canonical CCGM checkout. When PRs merge
in workspace clones, that canonical checkout drifts unless something pulls it.
This hook removes the manual sync step.

Triggers when:
- The Bash command invokes `gh pr merge ...` in any segment (it is usually
  `cd <repo>` first, or chained with && / piped to tail -- not the first token)
- The cwd's git remote points at a repo named "ccgm" (any owner)
- The canonical clone exists at $CCGM_CANONICAL_DIR (default ~/code/ccgm)

Behavior:
- Runs `git fetch origin main && git pull --ff-only origin main` in the
  canonical clone
- On success, symlinks module files the pull newly added to installed modules
  (link-mode installs only, never overwrites; see lib/ccgm_sync_install.py) and
  reports hook commands in changed settings.partial.json files that the live
  settings.json does not register (settings are never auto-merged)
- On a refused pull, reports how many commits the canonical clone is behind
- Logs to stderr and, so the session sees it, emits the report lines as
  PostToolUse additionalContext on stdout
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

# The helper ships beside this hook in the canonical clone (hooks/ and lib/ are
# siblings), so resolve through the symlink instead of relying on ~/.claude/lib
# already containing a file this very change adds.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"))


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


def command_triggers_merge(command: str) -> bool:
    """True if any segment of `command` invokes `gh pr merge`.

    `gh pr merge` is almost never the first token of the command string -- it is
    typically `cd <repo>` first (often on its own line) or chained with && / piped
    to tail. A start-anchored match therefore misses real merges and leaves the
    canonical clone stale (#728). Split on shell separators (newline ; | &) and
    check each segment. A false positive only costs one harmless, idempotent
    ff-only pull, so erring toward matching is safe.
    """
    for segment in re.split(r"[\n;|&]+", command):
        if re.match(r"\s*gh\s+pr\s+merge(\s|$)", segment):
            return True
    return False


def is_ccgm_repo(cwd: str) -> bool:
    url = get_origin_url(cwd)
    if not url:
        return False
    # Extract repo name from URL (last path segment, strip .git)
    repo_name = re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1])
    return repo_name == CCGM_REPO_NAME


def git_out(canonical_dir: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", canonical_dir, *args],
                           capture_output=True, text=True, timeout=10, check=False)
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.SubprocessError, OSError):
        return None


def commits_behind(canonical_dir: str) -> str:
    return git_out(canonical_dir, "rev-list", "--count", "HEAD..origin/main") or "an unknown number of"


def post_pull_report(canonical_dir: str, old_head: str | None) -> list[str]:
    """Install newly added module files and list unregistered hooks. Returns report lines."""
    lines: list[str] = []
    try:
        import ccgm_sync_install as inst

        claude_dir = os.path.join(os.path.expanduser("~"), ".claude")
        created = inst.install_new_files(claude_dir, canonical_dir)
        if created:
            rel = [os.path.relpath(p, claude_dir) for p in created]
            lines.append(f"installed {len(rel)} new CCGM file(s): {', '.join(rel)}")

        manifest = inst.load_manifest(claude_dir)
        new_head = git_out(canonical_dir, "rev-parse", "HEAD")
        if manifest and old_head and new_head and old_head != new_head:
            changed = git_out(canonical_dir, "diff", "--name-only", old_head, new_head) or ""
            installed = set(manifest.get("modules") or [])
            mods = sorted({
                parts[1] for parts in (c.split("/") for c in changed.splitlines())
                if len(parts) == 3 and parts[0] == "modules"
                and parts[2] == "settings.partial.json" and parts[1] in installed
            })
            missing = inst.unregistered_hooks(claude_dir, canonical_dir, mods)
            if missing:
                lines.append(
                    f"{len(missing)} hook command(s) in updated modules are not registered in "
                    f"~/.claude/settings.json (settings are not auto-merged): {'; '.join(missing)}"
                )
    except Exception as e:  # the install step must never break the hook
        lines.append(f"post-pull install step failed: {e}")
    return lines


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
            reason = " ".join(pull.stderr.split()) or "not fast-forward?"
            return False, f"pull failed: {reason}"

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
    if not command_triggers_merge(command):
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

    old_head = git_out(canonical_dir, "rev-parse", "HEAD")
    ok, msg = sync_canonical(canonical_dir)
    prefix = "sync-ccgm-canonical"
    if ok:
        sys.stderr.write(f"{prefix}: {canonical_dir} → {msg}\n")
        report = post_pull_report(canonical_dir, old_head)
    else:
        sys.stderr.write(f"{prefix}: FAILED — {msg}\n")
        report = [f"canonical CCGM clone is {commits_behind(canonical_dir)} commits behind origin/main: {msg}"]

    if report:
        text = "\n".join(f"{prefix}: {line}" for line in report)
        sys.stderr.write(text + "\n")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": text}}))

    sys.exit(0)


if __name__ == "__main__":
    main()
