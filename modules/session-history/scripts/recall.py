#!/usr/bin/env python3
"""/recall - unified view of Claude Code session history for a repo.

Reads ~/.claude/projects/**/*.jsonl across all clones of the current repo
and renders either a summary list or query-filtered turns.

Default: last 7 days of sessions for the current repo (detected from cwd/git
remote), unified across all clones (flat and workspace models).

Usage:
  recall.py                         # summary, current repo, 7 days
  recall.py <query>                 # query-filtered turns
  recall.py --days 30 [query]       # custom window
  recall.py --repo <name> [query]   # different repo
  recall.py --summary --limit 3     # compact summary, N most-recent sessions
  recall.py --session <id>          # dump a single session as readable text
  recall.py --full <query>          # include full turn content (no truncation)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from repo_detect import clone_label, detect_repo, list_project_dirs

DEFAULT_DAYS = 7
DEFAULT_LIMIT = 50
CONTENT_TRUNCATE = 160


@dataclass
class SessionMeta:
    session_id: str
    path: Path
    project_dir: Path
    clone: str
    repo: str
    mtime: float
    turn_count: int
    first_user_msg: str
    last_user_msg: str
    branch: str


def _iter_jsonl(path: Path) -> Iterator[dict]:
    """Stream a JSONL file, skipping malformed lines."""
    try:
        with path.open("r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _extract_text(content, include_tool_markers: bool = True) -> str:
    """Convert a Claude Code message content field (string or list of parts)
    to a single plain-text string. When include_tool_markers is False, skip
    tool_use/tool_result entries entirely (used for human-readable summaries)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t == "text":
                parts.append(item.get("text", ""))
            elif include_tool_markers and t == "tool_use":
                parts.append(f"[tool_use: {item.get('name', '?')}]")
            elif include_tool_markers and t == "tool_result":
                parts.append("[tool_result]")
        return " ".join(parts).strip()
    return ""


def _summarize_session(path: Path, repo: str, project_dir: Path) -> SessionMeta | None:
    """Scan a JSONL file to produce a one-line summary."""
    try:
        stat = path.stat()
    except OSError:
        return None

    first_user = ""
    last_user = ""
    turn_count = 0
    branch = ""
    session_id = path.stem

    for obj in _iter_jsonl(path):
        t = obj.get("type")
        if t == "user":
            msg = obj.get("message", {})
            # For summaries, ignore tool_result-only messages (they come wrapped
            # in user-role turns but aren't real user intent).
            text = _extract_text(msg.get("content", ""), include_tool_markers=False)
            # Skip synthetic system-injected messages
            if not text or text.startswith("<") or "<system-reminder>" in text[:200]:
                continue
            turn_count += 1
            if not first_user:
                first_user = text
            last_user = text
            if not branch:
                branch = obj.get("gitBranch", "")
        elif t == "assistant":
            # Count assistant turns toward turn_count too (conversation pairs)
            pass

    if turn_count == 0:
        return None

    return SessionMeta(
        session_id=session_id,
        path=path,
        project_dir=project_dir,
        clone=clone_label(project_dir, repo),
        repo=repo,
        mtime=stat.st_mtime,
        turn_count=turn_count,
        first_user_msg=first_user,
        last_user_msg=last_user,
        branch=branch,
    )


def _find_sessions(repo: str, days: int) -> list[SessionMeta]:
    """Enumerate sessions across all clones of a repo within the last N days."""
    cutoff = time.time() - days * 86400
    project_dirs = list_project_dirs(repo)
    sessions: list[SessionMeta] = []

    for project_dir in project_dirs:
        for jsonl in project_dir.glob("*.jsonl"):
            try:
                if jsonl.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            meta = _summarize_session(jsonl, repo, project_dir)
            if meta:
                sessions.append(meta)

    sessions.sort(key=lambda s: s.mtime, reverse=True)
    return sessions


def _truncate(s: str, n: int = CONTENT_TRUNCATE) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_date(mtime: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(mtime))


def _print_summary(sessions: list[SessionMeta], limit: int) -> None:
    if not sessions:
        return
    for s in sessions[:limit]:
        print(
            f"{_fmt_date(s.mtime)}  {s.clone:<14}  {s.session_id[:8]}  "
            f"{s.turn_count:>3} turns  {_truncate(s.last_user_msg, 60)}"
        )


def _print_header(repo: str, days: int, sessions: list[SessionMeta], mode: str) -> None:
    clones = sorted({s.clone for s in sessions})
    suffix = f", {len(clones)} clones" if len(clones) > 1 else ""
    count = len(sessions)
    print(f"Recent activity: {repo} (last {days} days{suffix}, {count} sessions) — {mode}")


def _query_session(meta: SessionMeta, query_re: re.Pattern, full: bool) -> list[str]:
    """Return formatted matching turns from a single session."""
    lines: list[str] = []
    for obj in _iter_jsonl(meta.path):
        t = obj.get("type")
        if t not in ("user", "assistant"):
            continue
        text = _extract_text(obj.get("message", {}).get("content", ""))
        if not text or not query_re.search(text):
            continue
        ts = obj.get("timestamp", "")
        role = t
        body = text if full else _truncate(text, 240)
        lines.append(f"    {role}: {body}")
    if lines:
        header = (
            f"{_fmt_date(meta.mtime)}  {meta.clone}  {meta.session_id[:8]}  "
            f"({meta.turn_count} turns total)"
        )
        return [header, *lines, ""]
    return []


def cmd_dump_session(session_id: str) -> int:
    """Dump a specific session's JSONL as readable text."""
    # Search all project dirs for a matching session
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.exists():
        print(f"No Claude Code projects directory at {claude_projects}", file=sys.stderr)
        return 1
    for project_dir in claude_projects.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            _dump_full(candidate)
            return 0
        # Also match by prefix if user gave a short id
        matches = list(project_dir.glob(f"{session_id}*.jsonl"))
        if matches:
            _dump_full(matches[0])
            return 0
    print(f"Session '{session_id}' not found", file=sys.stderr)
    return 1


def _dump_full(path: Path) -> None:
    print(f"# Session: {path.stem}")
    print(f"# File: {path}")
    print()
    for obj in _iter_jsonl(path):
        t = obj.get("type")
        if t in ("user", "assistant"):
            ts = obj.get("timestamp", "")
            text = _extract_text(obj.get("message", {}).get("content", ""))
            if text:
                print(f"[{ts}] {t}:")
                print(text)
                print()


def main() -> int:
    p = argparse.ArgumentParser(
        prog="recall",
        description="Search Claude Code session history across all clones of a repo.",
    )
    p.add_argument("query", nargs="?", help="substring/regex to search (default: summary mode)")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"window in days (default {DEFAULT_DAYS})")
    p.add_argument("--repo", help="canonical repo name (full name from `git remote`, not a substring)")
    p.add_argument("--dir", dest="project_dir", help="override: specific ~/.claude/projects/ subdir")
    p.add_argument("--summary", action="store_true", help="summary mode (one line per session)")
    p.add_argument("--full", action="store_true", help="do not truncate matched turn content")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"max sessions to show (default {DEFAULT_LIMIT})")
    p.add_argument("--session", help="dump a specific session by id (full or prefix)")
    args = p.parse_args()

    if args.session:
        return cmd_dump_session(args.session)

    repo = args.repo or detect_repo()
    if not repo:
        # Graceful: no repo detected, exit 0 with a note so dashboard wrappers
        # can skip the Recent Activity block.
        print("(no repo detected from cwd)", file=sys.stderr)
        return 0

    sessions = _find_sessions(repo, args.days)

    if not sessions:
        print(f"No sessions found for {repo} in the last {args.days} days.")
        return 0

    # Summary mode: default when no query is given, or explicitly requested.
    if args.summary or not args.query:
        mode = "summary"
        _print_header(repo, args.days, sessions, mode)
        _print_summary(sessions, args.limit)
        return 0

    # Query mode
    try:
        query_re = re.compile(args.query, re.IGNORECASE)
    except re.error:
        query_re = re.compile(re.escape(args.query), re.IGNORECASE)

    _print_header(repo, args.days, sessions, f"query: {args.query}")
    any_hits = False
    for s in sessions[: args.limit]:
        block = _query_session(s, query_re, args.full)
        if block:
            any_hits = True
            for line in block:
                print(line)
    if not any_hits:
        print(f"No turns matched '{args.query}' in the last {args.days} days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
