#!/usr/bin/env python3
"""
PreToolUse hook that HARD-BLOCKS any work on a repo's default branch.

Why: the advisory <workflow-reminder> (enforce-issue-workflow.py) tells agents
to branch first, and enforce-git-workflow.py blocks `git commit` / `git push`
on protected branches — but neither stops the edits themselves. An agent that
ignores the reminder and edits on main produces uncommitted work that is
destroyed the moment main is hard-reset to origin. This gate fires BEFORE the
first edit, so no work is ever produced on the default branch at all.

Classification: bypass-retained. Denials use exit 2 (the semantics of
hook_utils.hard_block(), inlined here so the hook is dependency-free and works
under both the symlink install and the plugin projection). A JSON
`permissionDecision: deny` does not survive bypass mode (GitHub issue #39344);
exit 2 does.

BLOCKS while HEAD == the repo's default branch (whatever origin/HEAD says,
falling back to origin/main, origin/master, then local main/master):
  - Edit / MultiEdit / Write / NotebookEdit and the filesystem-MCP write tools,
    keyed on the TARGET FILE's repo (not the session cwd) — so edits to
    non-repo files (scratchpads, memory, ~/.claude state) never block
  - Bash commands containing a mutating git invocation — git commit / add /
    stage / apply — scanning every &&/;/| segment and honoring `git -C <path>`

ALLOWS:
  - Any branch other than the default, including detached HEAD
  - ALLOW_MAIN_COMMIT=1 in the environment, or inline on a Bash command
    (escape hatch for intentional main-only ops, e.g. appcast version bumps)
  - In-progress rebase / merge / cherry-pick / revert / bisect states
    (conflict resolution and `git add` during a merge must keep working)
  - Unborn HEAD (fresh `git init` before the first commit) so bootstrap works
  - Repos with NO origin remote — nothing to sync from means the loss
    scenario cannot occur; scratch repos and local journals stay frictionless
  - Repos allowlisted in ~/.claude/git-flow-direct-to-main-repos.json (the
    same allowlist enforce-git-workflow.py honors, e.g. agent-log repos)
  - Files outside any git repo; non-git Bash commands; unknown tools

KNOWN GAPS (see rules/branch-guard.md): raw shell redirection writes
(`echo > file`, `sed -i`) are not detectable from the command string, and a
`cd <elsewhere> && git add` segment is checked against the session cwd, not
the cd target. The Edit/Write gate is the primary defense; the git-command
gate is a second layer on top of enforce-git-workflow.py's commit/push rules.

On any git/filesystem error the hook FAILS OPEN (exit 0): a guard that cannot
determine the branch must not brick the session. It only denies on a positive
"this repo is checked out on its default branch" determination.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

FILE_TOOLS = frozenset(
    {
        "Edit",
        "MultiEdit",
        "Write",
        "NotebookEdit",
        "mcp__filesystem__write_file",
        "mcp__filesystem__edit_file",
        "mcp__filesystem__move_file",
    }
)

MUTATING_GIT_SUBCOMMANDS = frozenset({"commit", "add", "stage", "apply"})

# Plumbing markers under $GIT_DIR that mean a multi-step operation is mid-flight.
IN_PROGRESS_MARKERS = (
    "rebase-merge",
    "rebase-apply",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
)

# Same allowlist enforce-git-workflow.py reads: repos (matched as substrings of
# the origin URL) that legitimately use a direct-to-main workflow.
DIRECT_TO_MAIN_FILE = os.path.expanduser(
    "~/.claude/git-flow-direct-to-main-repos.json"
)

_TRUTHY = frozenset({"1", "true", "yes"})

# git global flags that consume the NEXT token as their argument.
_GIT_FLAGS_WITH_ARG = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
)

# Tokens that may legitimately precede `git` in a segment.
_COMMAND_WRAPPERS = frozenset({"sudo", "command", "env", "nice", "nohup", "time"})

_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")


def env_bypass() -> bool:
    return os.environ.get("ALLOW_MAIN_COMMIT", "").strip().lower() in _TRUTHY


def hard_block(reason: str) -> None:
    """Bypass-proof deny: reason on stderr, exit 2 (hook_utils.hard_block parity)."""
    sys.stderr.write(reason.rstrip() + "\n")
    sys.stderr.flush()
    sys.exit(2)


def _git(args: list[str], cwd: str) -> str | None:
    """Run git in `cwd`; return stripped stdout on success, None on ANY failure."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def current_branch(cwd: str) -> str | None:
    """Current branch name; 'HEAD' when detached; None outside a repo or on an
    unborn branch (rev-parse errors before the first commit — deliberate, so a
    fresh `git init` repo can be bootstrapped)."""
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)


def default_branch(cwd: str) -> str | None:
    """The repo's default branch: origin/HEAD if known, else origin/{main,master},
    else — only when an origin remote exists — local {main,master}. None when
    undeterminable (fail open).

    Repos with NO origin remote return None on purpose: the loss scenario this
    guard exists for is uncommitted work destroyed when the default branch is
    hard-reset to origin. A local-only repo has nothing to sync from, so
    scratch `git init` repos and local journals stay frictionless.
    """
    head = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd)
    if head and "/" in head:
        return head.split("/", 1)[1]
    for cand in ("main", "master"):
        if _git(["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{cand}"], cwd) is not None:
            return cand
    if _git(["remote", "get-url", "origin"], cwd) is None:
        return None
    for cand in ("main", "master"):
        if _git(["show-ref", "--verify", "--quiet", f"refs/heads/{cand}"], cwd) is not None:
            return cand
    return None


def in_progress_git_state(cwd: str) -> bool:
    git_dir = _git(["rev-parse", "--absolute-git-dir"], cwd)
    if not git_dir:
        return False
    return any(os.path.exists(os.path.join(git_dir, m)) for m in IN_PROGRESS_MARKERS)


def is_direct_to_main_repo(cwd: str) -> bool:
    try:
        with open(DIRECT_TO_MAIN_FILE) as f:
            allowlist = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(allowlist, list):
        return False
    entries = [str(x) for x in allowlist if str(x).strip()]
    if not entries:
        return False
    remote = _git(["remote", "get-url", "origin"], cwd)
    if not remote:
        return False
    return any(entry in remote for entry in entries)


def default_branch_violation(check_dir: str) -> tuple[str, str] | None:
    """Return (branch, repo_root) iff check_dir's repo is on its default branch
    with no exemption. None means: allow."""
    branch = current_branch(check_dir)
    if not branch or branch == "HEAD":
        return None  # not a repo, unborn HEAD, or detached HEAD
    default = default_branch(check_dir)
    if not default or branch != default:
        return None
    if in_progress_git_state(check_dir):
        return None
    if is_direct_to_main_repo(check_dir):
        return None
    repo_root = _git(["rev-parse", "--show-toplevel"], check_dir) or check_dir
    return branch, repo_root


def deny(action: str, branch: str, repo_root: str) -> None:
    hard_block(
        f"BRANCH GUARD: blocked {action} — HEAD is on '{branch}', the default "
        f"branch of {repo_root}.\n"
        f"Work is NEVER done directly on '{branch}': uncommitted changes here are "
        f"destroyed the next time '{branch}' is synced to origin.\n"
        "\n"
        "Create a feature branch FIRST, then retry this exact operation:\n"
        "\n"
        f"  git fetch origin && git checkout -b <type>/<short-desc> origin/{branch}\n"
        "\n"
        "  <type> is one of: feature | fix | chore | docs   "
        "(e.g. feature/add-login-form)\n"
        "\n"
        f"Escape hatch — ONLY for {branch}-only operations the user explicitly "
        "requested (e.g. appcast version bumps): set ALLOW_MAIN_COMMIT=1 "
        "(inline for Bash: `ALLOW_MAIN_COMMIT=1 git ...`). In-progress "
        "rebase/merge/cherry-pick states are exempt automatically."
    )


# ─── File tools ──────────────────────────────────────────────────────


def target_paths(tool_name: str, tool_input: dict) -> list[str]:
    if tool_name == "mcp__filesystem__move_file":
        return [
            v
            for k in ("source", "destination")
            if isinstance((v := tool_input.get(k)), str) and v
        ]
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return [value]
    return []


def existing_anchor_dir(raw_path: str, cwd: str) -> str | None:
    """Canonicalize raw_path (~, env vars, symlinks) and return its nearest
    EXISTING ancestor directory — the directory whose repo owns the file.
    Symlinks are resolved on purpose: editing an installed symlink must be
    attributed to the repo the real file lives in."""
    expanded = os.path.expandvars(os.path.expanduser(raw_path))
    path = Path(expanded)
    if not path.is_absolute():
        path = Path(cwd or os.getcwd()) / path
    try:
        path = path.resolve()
    except (OSError, RuntimeError):
        return None
    directory = path if path.is_dir() else path.parent
    while not directory.exists():
        if directory.parent == directory:
            return None
        directory = directory.parent
    return str(directory)


# ─── Bash ────────────────────────────────────────────────────────────


def git_mutations(command: str) -> list[tuple[str, str | None]]:
    """Scan a shell command for mutating git invocations.

    Returns [(subcommand, c_path_or_None), ...] — one entry per segment whose
    first program is `git` (after env-assignment/wrapper prefixes) invoking a
    mutating subcommand. `-C <path>` is captured so the check runs against the
    repo git actually operates on. Splitting on separators inside quoted
    strings can over-trigger; that errs toward safety and the escape hatch
    covers intentional cases.
    """
    found: list[tuple[str, str | None]] = []
    for segment in _SEGMENT_SPLIT.split(command):
        tokens = segment.strip().split()
        i = 0
        while i < len(tokens) and (
            tokens[i] in _COMMAND_WRAPPERS
            or ("=" in tokens[i] and not tokens[i].startswith("-"))
        ):
            i += 1
        if i >= len(tokens) or tokens[i] != "git":
            continue
        i += 1
        c_path: str | None = None
        while i < len(tokens):
            tok = tokens[i]
            if tok in _GIT_FLAGS_WITH_ARG and i + 1 < len(tokens):
                if tok == "-C":
                    c_path = tokens[i + 1].strip("'\"")
                i += 2
                continue
            if tok.startswith("-C") and len(tok) > 2:
                c_path = tok[2:].strip("'\"")
                i += 1
                continue
            if tok.startswith("-"):
                i += 1
                continue
            break
        if i < len(tokens) and tokens[i] in MUTATING_GIT_SUBCOMMANDS:
            found.append((tokens[i], c_path))
    return found


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # malformed payload: never wedge the session

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        sys.exit(0)
    cwd = data.get("cwd") or os.getcwd()

    if env_bypass():
        sys.exit(0)

    if tool_name in FILE_TOOLS:
        for raw in target_paths(tool_name, tool_input):
            anchor = existing_anchor_dir(raw, cwd)
            if not anchor:
                continue
            violation = default_branch_violation(anchor)
            if violation:
                deny(f"{tool_name} of {raw}", *violation)
        sys.exit(0)

    if tool_name == "Bash":
        command = tool_input.get("command", "") or ""
        if "git" not in command:
            sys.exit(0)
        if "ALLOW_MAIN_COMMIT=1" in command:
            sys.exit(0)  # inline escape hatch
        for subcommand, c_path in git_mutations(command):
            check_dir = cwd
            if c_path:
                expanded = os.path.expandvars(os.path.expanduser(c_path))
                check_dir = (
                    expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded)
                )
            violation = default_branch_violation(check_dir)
            if violation:
                deny(f"`git {subcommand}`", *violation)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
