"""
ccgm-doctor checks: pure functions that take paths and return findings.

A finding is a dict:
    {"check": str, "severity": "warn"|"error", "path": str, "detail": str}

The CLI in bin/ccgm-doctor composes these into a report. Checks are pure so
they can be tested in isolation with tempdir fixtures (see tests/test_doctor.py).
"""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Iterable


Finding = dict

# Paths like $HOME/.claude/hooks/foo.py, ~/.claude/hooks/foo.py, or absolute paths.
_PATH_TOKEN_RE = re.compile(r'(?:\$HOME|~|/)[^\s"\';]+')

# Fenced bash block: the only context where `ccgm-*` tokens are treated as
# script invocations. Scanning outside bash blocks picks up directory names
# like `ccgm-repos/` and false-flags them.
_BASH_BLOCK_RE = re.compile(r'```(?:bash|sh|shell)\n(.*?)```', re.DOTALL)

# Inside a bash block, a `ccgm-*` token preceded by a non-path character and
# followed by whitespace, end-of-line, or shell punctuation is a script
# invocation. The lookbehind excludes `/` and `-` so path segments like
# `code/ccgm-repos/ccgm-1` stay filtered.
_SCRIPT_REF_RE = re.compile(
    r'(?:^|(?<=[\s`;|&()$]))(ccgm-[a-z0-9][a-z0-9-]*)(?=[\s;|&()<>]|$)',
    re.MULTILINE,
)


def expand_path(raw: str, home: Path) -> Path:
    """
    Expand $HOME, ${HOME}, and leading ~ to the given `home`. Relative paths
    become absolute against `home`.

    `home` here is the user's actual HOME dir (e.g. /Users/foo), NOT the
    Claude install dir (~/.claude). Hook commands in settings.json
    reference paths via $HOME and expect it to expand to the OS HOME.
    """
    expanded = raw.replace("$HOME", str(home)).replace("${HOME}", str(home))
    if expanded.startswith("~"):
        expanded = str(home) + expanded[1:]
    p = Path(expanded)
    if not p.is_absolute():
        p = home / p
    return p


def _iter_hook_commands(settings: dict) -> Iterable[tuple[str, str]]:
    """Yield (event_name, command_string) for every hook entry in settings.json."""
    hooks = settings.get("hooks") or {}
    if not isinstance(hooks, dict):
        return
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            if not isinstance(inner, list):
                continue
            for hook in inner:
                if not isinstance(hook, dict):
                    continue
                cmd = hook.get("command")
                if isinstance(cmd, str) and cmd.strip():
                    yield event, cmd


def check_hook_refs(settings_path: Path, user_home: Path) -> list[Finding]:
    """
    Verify every hook command references an existing file.

    `user_home` is the user's OS home (for $HOME / ~ expansion). The claude
    install dir usually lives AT `user_home/.claude` and its own settings.json
    references paths back through $HOME.
    """
    findings: list[Finding] = []
    if not settings_path.exists():
        return findings

    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError as e:
        findings.append({
            "check": "hook-refs",
            "severity": "error",
            "path": str(settings_path),
            "detail": f"settings.json is not valid JSON: {e}",
        })
        return findings

    for event, cmd in _iter_hook_commands(settings):
        # Extract path-like tokens. A hook command typically has one file
        # path; we check every path-like token to be safe.
        paths = _PATH_TOKEN_RE.findall(cmd)
        if not paths:
            continue
        for raw in paths:
            # Strip any trailing shell-like characters that slipped into the regex match.
            raw = raw.rstrip(".,;)")
            resolved = expand_path(raw, user_home)
            if not resolved.exists():
                findings.append({
                    "check": "hook-refs",
                    "severity": "error",
                    "path": str(resolved),
                    "detail": f"{event} hook references missing file: {cmd.strip()}",
                })
    return findings


_FRONTMATTER_DESC_RE = re.compile(r'^description:\s*(.+?)\s*$', re.MULTILINE)


def _extract_trigger_description(text: str) -> str | None:
    """
    Return the text the model will use to decide whether to reach for this
    command. Two valid sources, in priority order:

        1. YAML frontmatter `description:` field (how Claude Code advertises
           commands in the slash-command picker).
        2. First-line Markdown heading (used by CCGM's hand-written commands
           that do not have frontmatter).

    Returns None when neither is present.
    """
    stripped = text.lstrip("\n")
    if stripped.startswith("---\n"):
        # Find the closing --- on its own line.
        end_idx = stripped.find("\n---", 4)
        if end_idx != -1:
            frontmatter = stripped[4:end_idx]
            m = _FRONTMATTER_DESC_RE.search(frontmatter)
            if m:
                desc = m.group(1).strip().strip('"').strip("'")
                return desc if desc else None

    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    if first_line.startswith("#"):
        heading = first_line.lstrip("#").strip()
        return heading if heading else None

    return None


def check_command_descriptions(commands_dir: Path) -> list[Finding]:
    """
    Every command file should have a discoverable trigger description so the
    model knows when to reach for it. Accepts either a YAML frontmatter
    `description:` field or a first-line Markdown heading. Flag files with
    neither, or whose description is suspiciously short.
    """
    findings: list[Finding] = []
    if not commands_dir.is_dir():
        return findings

    for md in sorted(commands_dir.glob("*.md")):
        try:
            text = md.read_text()
        except OSError as e:
            findings.append({
                "check": "command-descriptions",
                "severity": "error",
                "path": str(md),
                "detail": f"cannot read command file: {e}",
            })
            continue

        desc = _extract_trigger_description(text)

        if desc is None:
            findings.append({
                "check": "command-descriptions",
                "severity": "warn",
                "path": str(md),
                "detail": "no frontmatter description or first-line heading; model may not discover its trigger",
            })
            continue

        if len(desc) < 10:
            findings.append({
                "check": "command-descriptions",
                "severity": "warn",
                "path": str(md),
                "detail": f"description is very short ('{desc}'); model may not discover its trigger",
            })
    return findings


def check_script_refs(commands_dir: Path, claude_dir: Path) -> list[Finding]:
    """
    Command markdown that references a `ccgm-*` script should point at a
    script that actually exists in `{claude_dir}/bin` or on PATH.
    """
    findings: list[Finding] = []
    if not commands_dir.is_dir():
        return findings

    bin_dir = claude_dir / "bin"

    # PATH dirs (from env) plus the claude install's bin dir.
    path_dirs = [Path(p) for p in os.environ.get("PATH", "").split(":") if p]
    path_dirs.append(bin_dir)

    def script_exists(name: str) -> bool:
        for d in path_dirs:
            candidate = d / name
            if candidate.exists() and os.access(candidate, os.X_OK):
                return True
        return False

    for md in sorted(commands_dir.glob("*.md")):
        try:
            text = md.read_text()
        except OSError:
            continue
        # Only scan inside fenced bash blocks. Prose mentions and paths like
        # `~/code/ccgm-repos/` should not trigger this check.
        referenced: set[str] = set()
        for block in _BASH_BLOCK_RE.findall(text):
            referenced.update(_SCRIPT_REF_RE.findall(block))
        for name in sorted(referenced):
            if not script_exists(name):
                findings.append({
                    "check": "script-refs",
                    "severity": "error",
                    "path": str(md),
                    "detail": f"references missing script: {name}",
                })
    return findings


def run_all_checks(claude_dir: Path, user_home: Path | None = None) -> list[Finding]:
    """
    Run every check_resolvable check against a Claude install at `claude_dir`.

    `user_home` is the OS home for $HOME / ~ expansion in hook refs. Defaults
    to `claude_dir.parent` (since the install conventionally lives at
    `~/.claude`, its parent IS the user home).
    """
    if user_home is None:
        user_home = claude_dir.parent
    settings = claude_dir / "settings.json"
    commands = claude_dir / "commands"
    return (
        check_hook_refs(settings, user_home)
        + check_command_descriptions(commands)
        + check_script_refs(commands, claude_dir)
    )


# --- DRY / overlap audit ---

# Stopwords for command-trigger tokenization. Words too generic to signal
# command identity (the, a), common CLI/workflow verbs (run, use, add),
# and filler. Kept deliberately tight so meaningful nouns like "calendar",
# "commit", "review" stay in.
_STOPWORDS = frozenset({
    "the", "and", "any", "all", "are", "but", "can", "did", "does", "done",
    "during", "else", "for", "from", "get", "had", "has", "have", "here",
    "how", "its", "just", "make", "must", "new", "not", "one", "only",
    "should", "some", "that", "the", "then", "this", "those", "two", "use",
    "using", "via", "was", "were", "what", "when", "where", "why", "will",
    "with", "would", "you", "your", "set", "run", "task", "command",
    "commands", "skill", "workflow", "claude", "code", "agent", "before",
    "after", "because", "current", "previous", "next", "these",
})

_TOKEN_RE = re.compile(r'[a-z][a-z0-9]{2,}')


def _trigger_tokens(text: str) -> set[str]:
    """
    Extract the identity-bearing tokens of a command's trigger description.
    Lowercase, strip punctuation, drop stopwords and tokens shorter than 3.
    """
    desc = _extract_trigger_description(text) or ""
    return {tok for tok in _TOKEN_RE.findall(desc.lower()) if tok not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def check_dry_overlap(commands_dir: Path, threshold: float = 0.5) -> list[Finding]:
    """
    Flag pairs of commands whose trigger-description tokens overlap above
    `threshold` (Jaccard similarity). Catches ambiguous routing: two skills
    the model might plausibly pick for the same intent.

    Commands whose trigger description is empty (already flagged by
    check_command_descriptions) are skipped so this check stays orthogonal.
    """
    findings: list[Finding] = []
    if not commands_dir.is_dir():
        return findings

    commands: list[tuple[Path, set[str]]] = []
    for md in sorted(commands_dir.glob("*.md")):
        try:
            text = md.read_text()
        except OSError:
            continue
        tokens = _trigger_tokens(text)
        if tokens:
            commands.append((md, tokens))

    # Pairwise comparison. O(n^2) but n is small (dozens, not thousands).
    for i in range(len(commands)):
        for j in range(i + 1, len(commands)):
            path_a, tokens_a = commands[i]
            path_b, tokens_b = commands[j]
            sim = _jaccard(tokens_a, tokens_b)
            if sim >= threshold:
                shared = sorted(tokens_a & tokens_b)
                findings.append({
                    "check": "dry-overlap",
                    "severity": "warn",
                    "path": f"{path_a.name} <-> {path_b.name}",
                    "detail": (
                        f"Jaccard={sim:.2f} over {len(shared)} shared tokens "
                        f"({', '.join(shared[:5])}"
                        f"{'...' if len(shared) > 5 else ''}). "
                        "Review for merge/deprecate, or sharpen descriptions."
                    ),
                })
    return findings
