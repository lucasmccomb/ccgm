#!/usr/bin/env python3
"""
Multi-agent handoff storage lib.

Handoffs are short agent-authored markdown files that let sibling clones
see what a peer just finished without mining the full session transcript
(which is what `/recall` is for). They live locally under ~/.claude/handoffs
and are read on SessionStart by auto-startup.py.

Storage layout:
    ~/.claude/handoffs/
        {repo-slug}/
            {YYYY-MM-DD}T{HH-MM-SS}-{agent-id}.md

File format (markdown with YAML frontmatter):
    ---
    agent: agent-w0-c0
    repo: ccgm
    branch: 370-multi-agent-handoff
    pr: 371
    issue: 370
    timestamp: 2026-04-21T05:49:00Z
    ---

    # Handoff — #370 ...

    ## What I did
    ...

    ## What's next
    ...

    ## Blockers / context
    ...

This module provides:
    write_handoff(body, repo, agent, ...): persist a handoff file
    list_peer_handoffs(repo, this_agent, days=7, include_self=False): recent handoffs
        (peers by default; pass include_self=True for self-continuity, e.g. /sds → /startup)
    prune_old_handoffs(repo=None, days=30): delete handoffs older than the window
    summarize_for_startup(repo, this_agent, max_items=5, include_self=False): compact text
        block for context injection

Import-safe: stdlib only, no side effects at import time.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HANDOFFS_ROOT = Path(os.environ.get("CCGM_HANDOFFS_DIR", Path.home() / ".claude" / "handoffs"))

_SAFE_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def slugify_repo(repo: str) -> str:
    """Normalize repo name to a filesystem-safe slug."""
    return _SAFE_SLUG.sub("-", repo).strip("-") or "unknown"


def _ts_now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_ts(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H-%M-%S")


def _parse_filename(path: Path) -> tuple[datetime, str] | None:
    """Parse filename into (timestamp, agent-id), or None on malformed input."""
    name = path.stem  # strip .md
    # Format: 2026-04-21T05-49-00-agent-w0-c0
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-(.+)$", name)
    if not m:
        return None
    ts_s, agent = m.group(1), m.group(2)
    try:
        ts = datetime.strptime(ts_s, "%Y-%m-%dT%H-%M-%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return ts, agent


def _repo_dir(repo: str) -> Path:
    return HANDOFFS_ROOT / slugify_repo(repo)


def write_handoff(
    body: str,
    repo: str,
    agent: str,
    branch: str | None = None,
    pr: int | str | None = None,
    issue: int | str | None = None,
    title: str | None = None,
    when: datetime | None = None,
) -> Path:
    """Write a handoff file. Returns the destination path."""
    if not repo:
        raise ValueError("repo is required")
    if not agent:
        raise ValueError("agent is required")

    ts = when or _ts_now()
    slug = slugify_repo(repo)
    safe_agent = _SAFE_SLUG.sub("-", agent).strip("-") or "agent"

    dest_dir = HANDOFFS_ROOT / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{_fmt_ts(ts)}-{safe_agent}.md"

    frontmatter_lines = [
        "---",
        f"agent: {safe_agent}",
        f"repo: {slug}",
    ]
    if branch:
        frontmatter_lines.append(f"branch: {branch}")
    if pr is not None:
        frontmatter_lines.append(f"pr: {pr}")
    if issue is not None:
        frontmatter_lines.append(f"issue: {issue}")
    frontmatter_lines.append(f"timestamp: {ts.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if title:
        frontmatter_lines.append(f"title: {title}")
    frontmatter_lines.append("---")

    content = "\n".join(frontmatter_lines) + "\n\n" + body.rstrip() + "\n"
    dest.write_text(content)
    return dest


def list_peer_handoffs(
    repo: str,
    this_agent: str,
    days: int = 7,
    include_self: bool = False,
) -> list[dict]:
    """Return recent handoffs for `repo`.

    By default, returns only handoffs from agents OTHER than `this_agent`
    (the sibling-coordination case). Pass `include_self=True` to also include
    handoffs written by `this_agent` itself — used for self-continuity flows
    like /sds → /startup, where the writer wants the next session to see
    what they handed off to "future-me".

    Each dict has: path, agent, timestamp, body, is_self.
    Sorted newest-first.
    """
    repo_dir = _repo_dir(repo)
    if not repo_dir.is_dir():
        return []

    cutoff = _ts_now() - timedelta(days=days)
    this_agent_safe = _SAFE_SLUG.sub("-", this_agent).strip("-")
    out: list[dict] = []
    for p in repo_dir.glob("*.md"):
        parsed = _parse_filename(p)
        if not parsed:
            continue
        ts, agent = parsed
        if ts < cutoff:
            continue
        is_self = agent == this_agent_safe
        if is_self and not include_self:
            continue
        try:
            body = p.read_text()
        except OSError:
            continue
        out.append({
            "path": str(p),
            "agent": agent,
            "timestamp": ts,
            "body": body,
            "is_self": is_self,
        })
    out.sort(key=lambda d: d["timestamp"], reverse=True)
    return out


def prune_old_handoffs(repo: str | None = None, days: int = 30) -> int:
    """Delete handoffs older than `days`. Returns count deleted.

    If `repo` is given, only that repo's dir is pruned; otherwise all repos.
    """
    cutoff = _ts_now() - timedelta(days=days)
    deleted = 0
    if repo:
        dirs: list[Path] = [_repo_dir(repo)]
    else:
        if not HANDOFFS_ROOT.is_dir():
            return 0
        dirs = [d for d in HANDOFFS_ROOT.iterdir() if d.is_dir()]

    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.md"):
            parsed = _parse_filename(p)
            if not parsed:
                continue
            ts, _ = parsed
            if ts < cutoff:
                try:
                    p.unlink()
                    deleted += 1
                except OSError:
                    pass
    return deleted


def summarize_for_startup(
    repo: str,
    this_agent: str,
    max_items: int = 5,
    days: int = 7,
    body_lines: int = 4,
    include_self: bool = False,
) -> str | None:
    """Build a compact context block summarizing handoffs, or None if none.

    By default surfaces peer handoffs only (sibling coordination). Pass
    `include_self=True` to also include the writer's own handoffs — needed
    by self-continuity flows like /sds → /startup. Self entries are marked
    `(you)` after the agent name so the source is unambiguous.

    Returns a string suitable for injecting into session context. Each entry
    shows agent, age, title (from frontmatter) or first heading, and the
    first `body_lines` of the body.
    """
    items = list_peer_handoffs(repo, this_agent, days=days, include_self=include_self)
    if not items:
        return None

    items = items[:max_items]
    now = _ts_now()
    has_self = any(h.get("is_self") for h in items)
    if include_self and has_self:
        header = f"Recent {repo} handoffs (you + peers, last {days}d):"
    else:
        header = f"Recent handoffs from other {repo} clones (last {days}d):"
    lines = ["<peer-handoffs>", header]
    for h in items:
        age = now - h["timestamp"]
        age_str = _human_age(age)
        fm, rest = _split_frontmatter(h["body"])
        title = fm.get("title") or _first_heading(rest) or "(no title)"
        preview = _first_lines(rest, body_lines)
        self_marker = " (you)" if h.get("is_self") else ""
        lines.append(f"")
        lines.append(f"- **{h['agent']}{self_marker}** ({age_str}): {title}")
        if preview:
            for pl in preview.splitlines():
                lines.append(f"  {pl}")
    lines.append("</peer-handoffs>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_frontmatter(body: str) -> tuple[dict, str]:
    """Extract a simple YAML-ish frontmatter (key: value) block, returning (fm, rest)."""
    fm: dict[str, str] = {}
    if not body.startswith("---\n"):
        return fm, body
    end = body.find("\n---", 4)
    if end < 0:
        return fm, body
    block = body[4:end]
    rest = body[end + len("\n---"):].lstrip("\n")
    for line in block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, rest


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return None


def _first_lines(text: str, n: int) -> str:
    """First n non-empty, non-heading lines."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        out.append(s)
        if len(out) >= n:
            break
    return "\n".join(out)


def _human_age(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 3600:
        return f"{max(1, secs // 60)}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


# ---------------------------------------------------------------------------
# Git + env introspection for CLI
# ---------------------------------------------------------------------------

def _run(*argv: str, cwd: str | None = None, timeout: float = 5.0) -> str | None:
    import subprocess
    try:
        r = subprocess.run(
            list(argv), cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def detect_repo(cwd: str | None = None) -> str | None:
    """Canonical repo name from git remote origin, stripped of .git."""
    url = _run("git", "remote", "get-url", "origin", cwd=cwd)
    if not url:
        return None
    name = os.path.basename(url)
    if name.endswith(".git"):
        name = name[:-4]
    return name or None


def detect_branch(cwd: str | None = None) -> str | None:
    return _run("git", "branch", "--show-current", cwd=cwd)


def detect_agent(cwd: str | None = None) -> str:
    """Derive agent ID from cwd / .env.clone. Matches agent_tracking convention."""
    wd = cwd or os.getcwd()
    env_clone = os.path.join(wd, ".env.clone")
    if os.path.isfile(env_clone):
        try:
            for line in Path(env_clone).read_text().splitlines():
                if line.startswith("AGENT_ID="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass
    base = os.path.basename(wd)
    m = re.search(r"w(\d+)-c(\d+)$", base)
    if m:
        return f"agent-w{m.group(1)}-c{m.group(2)}"
    m = re.search(r"-(\d+)$", base)
    if m:
        return f"agent-{m.group(1)}"
    return "agent-0"


def detect_issue_from_branch(branch: str | None) -> str | None:
    """Return leading digits from a branch name like `368-implement-...`."""
    if not branch:
        return None
    m = re.match(r"^(\d+)[-/]", branch)
    return m.group(1) if m else None


def detect_pr(cwd: str | None = None) -> str | None:
    """Best-effort: find the open PR for the current branch via gh."""
    branch = detect_branch(cwd)
    if not branch:
        return None
    out = _run("gh", "pr", "view", branch, "--json", "number", cwd=cwd)
    if not out:
        return None
    import json as _json
    try:
        return str(_json.loads(out).get("number"))
    except (_json.JSONDecodeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_TEMPLATE = """# Handoff{title_suffix}

## Current state

{body_state}

## Next steps

{body_next}

## Decisions & rationale

{body_decisions}

## Files in progress

{body_files}

## Gotchas

{body_gotchas}

## Blockers

{body_blockers}
"""


def _render_body(
    title: str | None,
    state: str,
    nxt: str,
    decisions: str,
    files: str,
    gotchas: str,
    blockers: str,
) -> str:
    """Render the 6-section handoff template.

    Section vocabulary chosen to force a state snapshot, not a journal:
      - Current state replaces the older "What I did" — snapshot, not retrospective
      - Decisions & rationale and Files in progress are new; both flagged as
        critical-for-handoff by every template source surveyed
      - Gotchas captures anti-patterns the writer learned NOT to repeat
    """
    title_suffix = f" — {title}" if title else ""
    return _TEMPLATE.format(
        title_suffix=title_suffix,
        body_state=state.strip() or "(not filled in)",
        body_next=nxt.strip() or "(not filled in)",
        body_decisions=decisions.strip() or "(none)",
        body_files=files.strip() or "(none)",
        body_gotchas=gotchas.strip() or "(none)",
        body_blockers=blockers.strip() or "(none)",
    )


_KICKOFF_DIVIDER = "-" * 64

_KICKOFF_TEMPLATE = """Continue from session handoff at {path}.

Read it completely before doing anything else. Trust the context it gives you — do not re-explore the codebase unless the handoff is wrong or incomplete. Then start with item #1 in "Next steps".

[USER DIRECTIVE: leave blank to let the agent propose the next action, or fill in to override]"""


def render_kickoff_prompt(path: str | os.PathLike) -> str:
    """Render the copy-paste kickoff prompt the next session pastes in.

    3 sentences + an optional [USER DIRECTIVE] slot. Format chosen for
    copy-paste safety: no smart quotes, ASCII-safe punctuation, framed
    so the receiving agent reads first and does not re-explore.
    """
    return _KICKOFF_TEMPLATE.format(path=str(path))


def _cli_write(args) -> int:
    repo = args.repo or detect_repo()
    if not repo:
        print("error: could not detect repo (pass --repo)", file=__import__("sys").stderr)
        return 2
    agent = args.agent or detect_agent()
    branch = args.branch or detect_branch()
    issue = args.issue or detect_issue_from_branch(branch)
    pr = args.pr or detect_pr()

    body = args.body
    if body is None:
        # Read from stdin (pipeline usage) if available
        import sys as _sys
        if not _sys.stdin.isatty():
            body = _sys.stdin.read()
    if not body:
        # --state is preferred; --did is back-compat alias mapping to Current state
        state = args.state or args.did or ""
        body = _render_body(
            args.title,
            state,
            args.next or "",
            args.decisions or "",
            args.files or "",
            args.gotchas or "",
            args.blockers or "",
        )

    dest = write_handoff(
        body=body,
        repo=repo,
        agent=agent,
        branch=branch,
        pr=pr,
        issue=issue,
        title=args.title,
    )
    # First line is the path so script callers using `head -n1` or capturing
    # stdout still get a clean answer. The kickoff block follows visually
    # separated, so a human running the CLI directly can copy-paste it.
    print(dest)
    if not args.no_kickoff:
        print()
        print("Copy the prompt below into your next session:")
        print(_KICKOFF_DIVIDER)
        print(render_kickoff_prompt(dest))
        print(_KICKOFF_DIVIDER)
    return 0


def _cli_list(args) -> int:
    repo = args.repo or detect_repo()
    if not repo:
        print("error: could not detect repo (pass --repo)", file=__import__("sys").stderr)
        return 2
    agent = args.agent or detect_agent()
    peers = list_peer_handoffs(repo, agent, days=args.days)
    if not peers:
        print(f"(no peer handoffs for {repo} in last {args.days}d)")
        return 0
    for h in peers:
        print(f"{h['timestamp'].strftime('%Y-%m-%d %H:%M')}  {h['agent']:20}  {h['path']}")
    return 0


def _cli_prune(args) -> int:
    n = prune_old_handoffs(repo=args.repo, days=args.days)
    print(f"pruned {n} handoff(s) older than {args.days}d")
    return 0


def _cli_summary(args) -> int:
    repo = args.repo or detect_repo()
    if not repo:
        return 0
    agent = args.agent or detect_agent()
    s = summarize_for_startup(
        repo,
        agent,
        max_items=args.max,
        days=args.days,
        include_self=getattr(args, "include_self", False),
    )
    if s:
        print(s)
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse, sys as _sys

    p = argparse.ArgumentParser(
        prog="handoff",
        description="Write/read cross-clone handoff notes under ~/.claude/handoffs/",
    )
    sub = p.add_subparsers(dest="cmd")

    w = sub.add_parser("write", help="Write a new handoff (default)")
    w.add_argument("--repo")
    w.add_argument("--agent")
    w.add_argument("--branch")
    w.add_argument("--pr")
    w.add_argument("--issue")
    w.add_argument("--title")
    w.add_argument("--state", help="Current state section (snapshot of where things are)")
    w.add_argument("--next", help="Next steps section (numbered, immediate actions)")
    w.add_argument("--decisions", help="Decisions & rationale section (what + why)")
    w.add_argument("--files", help="Files in progress section (path:line + state)")
    w.add_argument("--gotchas", help="Gotchas section (anti-patterns, surprises)")
    w.add_argument("--blockers", help="Blockers section")
    w.add_argument("--did", help="(back-compat alias for --state)")
    w.add_argument("--body", help="Full markdown body override (skips template)")
    w.add_argument(
        "--no-kickoff",
        action="store_true",
        help="Suppress the copy-paste kickoff prompt printed after the path",
    )
    w.set_defaults(func=_cli_write)

    ls = sub.add_parser("list", help="List peer handoffs for the current repo")
    ls.add_argument("--repo")
    ls.add_argument("--agent")
    ls.add_argument("--days", type=int, default=7)
    ls.set_defaults(func=_cli_list)

    pr = sub.add_parser("prune", help="Delete old handoffs")
    pr.add_argument("--repo", default=None, help="Limit to one repo")
    pr.add_argument("--days", type=int, default=30)
    pr.set_defaults(func=_cli_prune)

    su = sub.add_parser("summary", help="Print the startup-injection block, or nothing")
    su.add_argument("--repo")
    su.add_argument("--agent")
    su.add_argument("--days", type=int, default=7)
    su.add_argument("--max", type=int, default=5)
    su.add_argument(
        "--include-self",
        action="store_true",
        help="Include handoffs written by the current agent (self-continuity, e.g. /sds → /startup)",
    )
    su.set_defaults(func=_cli_summary)

    # Default subcommand: write
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        # No subcommand -> behave like `write` with empty flags
        w.parse_args([])
        args = w.parse_args([])
        args.func = _cli_write
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
