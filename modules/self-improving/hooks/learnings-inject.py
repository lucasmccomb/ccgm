#!/usr/bin/env python3
"""SessionStart hook: opt-in, prefix-cache-safe learnings injection (issue #754).

PURPOSE
-------
The learnings store (modules/self-improving/lib/learnings_store.py) accumulates
durable, cross-session patterns/pitfalls/preferences per project. Today the
only way to see them is to explicitly run `ccgm-learnings-search`. This hook
offers an OPT-IN alternative: at fresh session start, surface the top-ranked
learnings for the current project directly into context, so an agent starts a
session already aware of what it (or a sibling agent) has learned before.

CRITICAL SAFETY PROPERTY
-------------------------
This hook is a strict NO-OP unless BOTH of the following hold:

    1. The SessionStart event fires with source == "startup" (never on
       resume/compact -- re-injecting on every resume would re-rank and
       re-render the block each time, which is exactly the per-turn
       re-injection pattern the durable-memory plan's prefix-cache-safety
       requirement forbids -- see decisions.md Key Insight 6).
    2. The environment variable CCGM_LEARNINGS_INJECT is truthy.

With the flag unset (the default for every existing and new install), the
hook reads stdin, finds the flag absent, and exits having printed nothing.
Nothing about existing sessions changes. This mirrors the relevance-injection
module's opt-in posture (modules/relevance-injection/hooks/relevance-inject.py)
and its own settings.partial.json registration shape.

PROJECT SLUG RESOLUTION (arch-1, CRITICAL)
-------------------------------------------
The slug is resolved via `learnings_store.detect_project_slug(cwd)` -- the
SAME canonical function every read/write in the store already uses. This
hook MUST NEVER resolve the slug via session-history's repo_detect.py:
that module answers a DIFFERENT question (which Claude Code project
directories, under ~/.claude/projects/, belong to clones of a repo) and
returns a DIFFERENT, incompatible string -- a bare repo name (e.g. "myrepo")
rather than detect_project_slug()'s {owner}_{repo} slug (e.g.
"myorg-myrepo"). Reusing repo_detect.py here would make this hook silently
read an empty or wrong project directory for essentially every real repo.

CONFLICT SUPPRESSION (adrev-011)
---------------------------------
learnings_store.search() does not filter out rows flagged `conflict: true`
(two competing supersede events racing the same target) -- Epic 1's job was
only to make sure the flag reaches those rows, not to hide them, since
`/consolidate` and the dream digest are supposed to show them to a human.
This hook is different: it hands its output to an agent as ambient context,
with no human in the loop to notice a flag. A conflicted row is NOT settled
truth, so it is suppressed here before rendering -- never injected as if it
were an ordinary, resolved learning.

BUDGET / RANKING
-----------------
Selection reuses learnings_store.search()'s own ranking (effective
confidence, decay, staleness) and the store's configured token budget --
this hook does not re-implement ranking. It over-fetches a superset of
candidates so that removing conflicted rows can still backfill up to the
real cap/budget from the next-ranked alternative (see
_select_for_injection()).

OUTPUT
------
Exactly one stdout block, `<ccgm-learnings-injection>...</ccgm-learnings-injection>`,
each entry rendered with the same age/verification wrapper
ccgm-learnings-search's preamble output uses (epic 4: verification-on-read --
a learning is a claim recorded at write time, not a live guarantee). Content
is a pure function of hook input + store state + env, so two invocations
against the same store produce byte-identical output within a session
(prefix-cache safety).

SAFETY
------
Never raises: any failure path (missing flag, unresolvable store, empty
result set, malformed stdin) returns without emitting, so this can never
crash or block a session.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

FLAG = "CCGM_LEARNINGS_INJECT"

# learnings_store.py is installed at ~/.claude/lib/learnings_store.py by CCGM
# and lives at ../lib/learnings_store.py relative to this file's own repo
# location. Insert both so the hook resolves it whether it is running from
# an installed symlink (resolves back into the repo) or a plain copy.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path.home() / ".claude" / "lib"))
sys.path.insert(0, str(_HERE.parent / "lib"))

try:
    import learnings_store  # type: ignore
except Exception:  # pragma: no cover - import guard; hook must never crash a session
    learnings_store = None


def _truthy(val: "str | None") -> bool:
    return (val or "").strip().lower() in ("true", "1", "yes")


def resolve_slug(cwd: str) -> str:
    """The ONE call site this hook uses to resolve a project slug.

    MUST delegate to learnings_store.detect_project_slug() -- never
    session-history's repo_detect.py (arch-1; see module docstring)."""
    return learnings_store.detect_project_slug(cwd)


# ---------------------------------------------------------------------------
# Age / verification wrapper -- mirrors bin/ccgm-learnings-search's own
# _verify_wrapper()/_age_days() exactly (epic 4: verification-on-read). The
# two copies are deliberately independent: a bin/ CLI and a hooks/ script are
# separate entry points that must not import one another, and
# learnings_store.py itself is out of scope for this change (owned
# elsewhere; it exposes no plain "days since" helper -- effective_confidence
# folds age into a decayed score, is_stale only returns a bool).
# ---------------------------------------------------------------------------

_ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_epoch(value: str) -> float:
    """Parse an ISO-8601 UTC timestamp (ms-precision or not) to epoch
    seconds. Returns 0.0 for empty/unparseable input."""
    if not value:
        return 0.0
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return 0.0


def _age_days(entry: dict, *, now: "float | None" = None) -> int:
    """Whole days since `last_verified` (falling back to `timestamp`).
    Deterministic arithmetic on data already in hand -- never estimated."""
    ts = _parse_iso_epoch(entry.get("last_verified") or entry.get("timestamp", ""))
    if ts <= 0:
        return 0
    now_ts = now if now is not None else time.time()
    return max(0, int((now_ts - ts) // 86400))


def _verify_wrapper(entry: dict, *, repo_root: "Path | None" = None, now: "float | None" = None) -> str:
    """`[age: Nd · last_verified: DATE · verify files[] anchors before
    asserting]`, plus a trailing `[anchor-missing]` when a listed files[]
    path does not exist under `repo_root`."""
    age = _age_days(entry, now=now)
    last_verified = entry.get("last_verified") or entry.get("timestamp") or ""
    date_str = last_verified[:10] if len(last_verified) >= 10 else "unknown"
    wrapper = f"[age: {age}d · last_verified: {date_str} · verify files[] anchors before asserting]"
    if learnings_store.has_stale_file_refs(entry, repo_root):
        wrapper += " [anchor-missing]"
    return wrapper


def _select_for_injection(slug: str, *, max_results: int, token_budget: int) -> "list[dict]":
    """Fetch a superset of ranked candidates via learnings_store.search()
    (ranking/relevance/decay stay entirely owned by the store), drop
    conflicted rows (adrev-011), then re-apply the real cap/budget over the
    filtered, already-ranked set -- mirroring search()'s own trailing budget
    loop so backfill works after conflict suppression.

    Over-fetches 4x cap/budget: conflicts should be rare, and this margin is
    enough for a non-conflicted alternative to backfill in the common case
    without walking the entire store.
    """
    over_fetched = learnings_store.search(
        slug=slug,
        max_results=max_results * 4,
        token_budget=token_budget * 4,
    )
    non_conflicted = [e for e in over_fetched if not e.get("conflict")]

    char_budget = token_budget * 4
    used = 0
    out: "list[dict]" = []
    for e in non_conflicted:
        snippet_len = len(e.get("content", "")) + 80
        if used + snippet_len > char_budget:
            break
        out.append(e)
        used += snippet_len
        if len(out) >= max_results:
            break
    return out


def build_context(hook_input: dict, env: "dict[str, str] | None" = None) -> "str | None":
    """Build the injected block, or None if there is nothing to emit.

    Depends only on hook_input + env + store state -- no caller-visible
    side effects. Every "None" branch means the caller emits nothing and
    session behavior is exactly what it was before this hook existed.
    """
    env = env if env is not None else os.environ
    if not _truthy(env.get(FLAG)):
        return None
    if learnings_store is None:
        return None

    cwd = hook_input.get("cwd") or os.getcwd()
    slug = resolve_slug(cwd)

    cfg = learnings_store.load_config()
    max_results = int(cfg.get("max_results", learnings_store.DEFAULT_MAX_RESULTS))
    token_budget = int(cfg.get("token_budget", learnings_store.DEFAULT_TOKEN_BUDGET))

    selected = _select_for_injection(slug, max_results=max_results, token_budget=token_budget)
    if not selected:
        return None

    repo_root = Path(cwd)
    lines = [
        "<ccgm-learnings-injection>",
        f"Durable learnings for this project ({len(selected)} of top-ranked, budget-capped).",
        "Each is a claim recorded at write time, not a live guarantee -- verify before",
        "treating as settled fact, especially any files[] anchor.",
        "",
    ]
    for e in selected:
        eff = learnings_store.effective_confidence(e)
        tags = ",".join(e.get("tags", []))
        lines.append(
            f"  - [{e.get('type')}] ({eff:.1f}) {e.get('content')}"
            + (f"  [tags: {tags}]" if tags else "")
        )
        lines.append(f"    {_verify_wrapper(e, repo_root=repo_root)}")
    lines += [
        "",
        "Run `ccgm-learnings-search --query <topic>` for more, or `--cross-project` to widen scope.",
        "</ccgm-learnings-injection>",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, EOFError):
        hook_input = {}

    # Only fire on fresh sessions -- never resume/compact (prefix-cache
    # safety: re-injecting per-turn is the exact anti-pattern this hook
    # exists to avoid).
    if hook_input.get("source", "") != "startup":
        return

    context = build_context(hook_input)
    if context:
        sys.stdout.write(context)


if __name__ == "__main__":
    main()
