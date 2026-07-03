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

TELEMETRY (issue #781)
----------------------
After the injected block is written to stdout, the hook appends ONE
best-effort telemetry record per surfacing so a future weekly scorecard can
measure how often / which memories are actually surfaced. The record carries
memory IDs + counts + a token estimate ONLY -- never any memory CONTENT (the
content already lives in the store; copying it here would create a second PII
surface). It lands in a per-machine JSONL under the dreaming module's
CCGM_DREAMING_DIR root (~/.claude/dreaming/injection-log/<date>.jsonl),
deliberately OUTSIDE the synced ~/.claude/learnings/ store. The whole write is
wrapped so any failure is swallowed: it can never alter the injected bytes,
block the injection, or raise. Nothing is written when injection did not run.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

FLAG = "CCGM_LEARNINGS_INJECT"

# Rough chars-per-token approximation; matches learnings_store.py's own
# "4 chars ~ 1 token" convention (search()'s char_budget = budget * 4).
# Distinct from the *candidate over-fetch* multiplier used below (also 4,
# but an unrelated "fetch this many times the cap" concept -- Stage-2
# review nit).
CHARS_PER_TOKEN = 4

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

# hook_utils (modules/hooks/lib/hook_utils.py, installed at
# ~/.claude/lib/hook_utils.py) provides file_locked_append for the #781
# injection-telemetry side-channel. The ~/.claude/lib path was already
# inserted above; add the repo path too so it resolves from a plain checkout.
# Guarded: its absence must never crash a session (telemetry is best-effort).
sys.path.insert(0, str(_HERE.parent.parent / "hooks" / "lib"))
try:
    import hook_utils  # type: ignore
except Exception:  # pragma: no cover - import guard; telemetry is best-effort
    hook_utils = None


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
    # files[] elements are supposed to be strings, but learnings_store's own
    # validate_entry() only checks list-ness, not element type -- a caller
    # of build_entry(..., files=[123]) writes successfully through the
    # store's public API and only crashes here, at read time, inside
    # has_stale_file_refs(). Filter defensively (skip, don't crash) rather
    # than trust the shape (Stage-2 review: "hook must never raise").
    safe_files = [f for f in (entry.get("files") or []) if isinstance(f, str)]
    if learnings_store.has_stale_file_refs({**entry, "files": safe_files}, repo_root):
        wrapper += " [anchor-missing]"
    return wrapper


def _render_entry_lines(entry: dict, *, repo_root: "Path | None" = None) -> "list[str]":
    """The exact two lines build_context() emits for one entry: the bullet
    (type/confidence/content/tags) and the verification wrapper. Shared by
    _select_for_injection()'s budget accounting and build_context()'s real
    render so the two can never drift apart -- the root cause of the
    Stage-2 budget-overflow finding was an estimate (`len(content) + 80`)
    that did not know this second, wrapper line existed at all.
    """
    eff = learnings_store.effective_confidence(entry)
    tags = ",".join(entry.get("tags", []))
    bullet = (
        f"  - [{entry.get('type')}] ({eff:.1f}) {entry.get('content')}"
        + (f"  [tags: {tags}]" if tags else "")
    )
    wrapper = f"    {_verify_wrapper(entry, repo_root=repo_root)}"
    return [bullet, wrapper]


def _envelope_lines(count: int) -> "tuple[list[str], list[str]]":
    """The exact header/footer line lists build_context() wraps entries in,
    parameterized by the "N of top-ranked" count so the real render and the
    budget pre-check below always use identical text."""
    header = [
        "<ccgm-learnings-injection>",
        f"Durable learnings for this project ({count} of top-ranked, budget-capped).",
        "Each is a claim recorded at write time, not a live guarantee -- verify before",
        "treating as settled fact, especially any files[] anchor.",
        "",
    ]
    footer = [
        "",
        "Run `ccgm-learnings-search --query <topic>` for more, or `--cross-project` to widen scope.",
        "</ccgm-learnings-injection>",
    ]
    return header, footer


def _envelope_char_cost(max_results: int) -> int:
    """Reserved char cost of the header+footer envelope around the entries,
    computed with max_results as an upper bound on the eventual "N of
    top-ranked" digit count -- the real len(selected) can never exceed
    max_results, so this can never *underestimate* the true reservation
    (only ever reserve a few extra, harmless chars when the digit count of
    the eventual real count is shorter than max_results's).

    Mirrors exactly what "\\n".join(header + entries + footer) + "\\n" costs
    when zero entries are spliced in: sum(line lengths) + (n-1) internal
    separators + 1 trailing newline == sum(line lengths) + n. The per-entry
    loop in _select_for_injection() adds its own "+2" per entry for the two
    newline separators each entry's two lines introduce once spliced
    between header and footer -- see that loop for the entry-side half of
    this same accounting.
    """
    header, footer = _envelope_lines(max(max_results, 0))
    all_lines = header + footer
    return sum(len(line) for line in all_lines) + len(all_lines)


def _select_for_injection(
    slug: str, *, max_results: int, token_budget: int, repo_root: "Path | None" = None
) -> "list[dict]":
    """Fetch a superset of ranked candidates via learnings_store.search()
    (ranking/relevance/decay stay entirely owned by the store), drop
    conflicted rows (adrev-011), then re-apply the real cap/budget over the
    filtered, already-ranked set -- mirroring search()'s own trailing budget
    loop so backfill works after conflict suppression.

    Budget accounting uses the ACTUAL rendered text (_render_entry_lines(),
    the same helper build_context() renders with) rather than an estimate,
    and reserves the header/footer envelope's fixed cost
    (_envelope_char_cost()) before the per-entry loop runs -- so the
    invariant `len(build_context(...)) <= token_budget * CHARS_PER_TOKEN`
    holds by construction, not by chance (Stage-2 review: the prior
    `len(content) + 80` heuristic knew about neither the wrapper line nor
    the envelope, and drifted 129-136% over budget under realistic,
    non-default configs).

    max_results <= 0 means "inject nothing": returns [] immediately, rather
    than the previous pre-cap-check loop shape that appended before
    checking the cap and so returned exactly 1 entry for max_results=0
    (Stage-2 review, Recommend).

    Over-fetches 4x cap/budget: conflicts should be rare, and this margin is
    enough for a non-conflicted alternative to backfill in the common case
    without walking the entire store.
    """
    if max_results <= 0:
        return []

    over_fetched = learnings_store.search(
        slug=slug,
        max_results=max_results * 4,
        token_budget=token_budget * 4,
    )
    non_conflicted = [e for e in over_fetched if not e.get("conflict")]

    char_budget = token_budget * CHARS_PER_TOKEN
    available = char_budget - _envelope_char_cost(max_results)

    used = 0
    out: "list[dict]" = []
    for e in non_conflicted:
        bullet, wrapper = _render_entry_lines(e, repo_root=repo_root)
        # +2: the two newline separators this entry's two lines add once
        # spliced between the surrounding lines (see _envelope_char_cost()'s
        # docstring for the matching header/footer half of this accounting).
        entry_cost = len(bullet) + len(wrapper) + 2
        if used + entry_cost > available:
            break
        out.append(e)
        used += entry_cost
        if len(out) >= max_results:
            break
    return out


def _build_injection(
    hook_input: dict, env: "dict[str, str] | None" = None
) -> "tuple[str | None, list[dict], str]":
    """Core selection+render shared by build_context() and main().

    Returns (context, selected, slug):

      - context: the rendered `<ccgm-learnings-injection>` block, or None when
        nothing should be emitted -- byte-identical to what build_context()
        has always returned (build_context() is now a thin wrapper over this,
        so no existing caller ever sees a different string).
      - selected: the EXACT list of store entries rendered into `context`
        (empty when context is None). main() reuses this for the #781
        telemetry side-channel -- the memory list is never re-queried.
      - slug: the resolved project slug ("" when the flag gate short-circuits
        before slug resolution).

    See build_context()'s docstring for the `env` nuance (it gates only the
    CCGM_LEARNINGS_INJECT flag; slug resolution always reads os.environ).
    """
    env = env if env is not None else os.environ
    if not _truthy(env.get(FLAG)):
        return None, [], ""
    if learnings_store is None:
        return None, [], ""

    cwd = hook_input.get("cwd") or os.getcwd()
    slug = resolve_slug(cwd)
    repo_root = Path(cwd)

    cfg = learnings_store.load_config()
    # cfg values come from a user-editable config.json: syntactically valid
    # JSON with the wrong type (a string, or null) must fall back to the
    # store's own defaults, never crash a SessionStart hook (Stage-2
    # review, matches this file's own established local-guard idiom).
    try:
        max_results = int(cfg.get("max_results", learnings_store.DEFAULT_MAX_RESULTS))
    except (TypeError, ValueError):
        max_results = learnings_store.DEFAULT_MAX_RESULTS
    try:
        token_budget = int(cfg.get("token_budget", learnings_store.DEFAULT_TOKEN_BUDGET))
    except (TypeError, ValueError):
        token_budget = learnings_store.DEFAULT_TOKEN_BUDGET

    selected = _select_for_injection(
        slug, max_results=max_results, token_budget=token_budget, repo_root=repo_root
    )
    if not selected:
        return None, [], slug

    header, footer = _envelope_lines(len(selected))
    lines = list(header)
    for e in selected:
        lines.extend(_render_entry_lines(e, repo_root=repo_root))
    lines.extend(footer)
    return "\n".join(lines) + "\n", selected, slug


def build_context(hook_input: dict, env: "dict[str, str] | None" = None) -> "str | None":
    """Build the injected block, or None if there is nothing to emit.

    Depends only on hook_input + env + store state -- no caller-visible
    side effects. Every "None" branch means the caller emits nothing and
    session behavior is exactly what it was before this hook existed.

    NOTE: `env` only gates the CCGM_LEARNINGS_INJECT flag checked just
    below -- project-slug resolution (resolve_slug() ->
    learnings_store.detect_project_slug()) always reads the REAL process
    os.environ, regardless of what is passed here. Harmless in production
    (where `env` defaults to `os.environ` anyway); tests that need to
    isolate slug resolution do so via CCGM_LEARNINGS_PROJECT/DIR, not via
    this parameter.
    """
    context, _selected, _slug = _build_injection(hook_input, env)
    return context


# ---------------------------------------------------------------------------
# Injection telemetry (issue #781) -- a per-machine, best-effort side-channel.
#
# After the injected block is written to stdout, main() appends ONE record per
# surfacing so a future weekly scorecard can measure memory utilization. The
# record carries memory IDs + counts + a token estimate ONLY -- never any
# memory CONTENT: the content already lives in the store, and copying it here
# would create a second PII surface (issue #781). The log lives OUTSIDE the
# synced ~/.claude/learnings/ store (telemetry is per-machine, never
# committed), under the dreaming module's own CCGM_DREAMING_DIR root so the
# scorecard reads a consistent path.
# ---------------------------------------------------------------------------

def _utc_now_iso(now: "datetime | None" = None) -> str:
    """ISO-8601 UTC, millisecond precision -- matches learnings_store's own
    timestamp format. Inlined rather than imported from the store to keep this
    side-channel self-contained (same independence rationale as
    _verify_wrapper vs. the search CLI's copy)."""
    dt = now if now is not None else datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{dt.microsecond // 1000:03d}Z"


def _injection_log_path(now: "datetime | None" = None) -> Path:
    """Per-machine telemetry path:
    <CCGM_DREAMING_DIR>/injection-log/<date>.jsonl (default root
    ~/.claude/dreaming). Deliberately NOT under ~/.claude/learnings/ -- that
    directory is a synced git repo and telemetry must never be committed to
    it (issue #781)."""
    root = Path(os.environ.get("CCGM_DREAMING_DIR", os.path.expanduser("~/.claude/dreaming")))
    day = (now if now is not None else datetime.now(timezone.utc)).date().isoformat()
    return root / "injection-log" / f"{day}.jsonl"


def _telemetry_record(
    hook_input: dict,
    slug: str,
    selected: "list[dict]",
    context: str,
    *,
    now: "datetime | None" = None,
) -> dict:
    """One telemetry record for a single injection. IDs + counts + a token
    estimate ONLY -- no memory content (issue #781). session_id/source come
    from the hook's stdin input; approx_tokens is the injected block's own
    size (len(context) // CHARS_PER_TOKEN), reusing the already-rendered
    string rather than recomputing anything."""
    return {
        "timestamp": _utc_now_iso(now),
        "session_id": str(hook_input.get("session_id", "")),
        "source": str(hook_input.get("source", "")),
        "project_slug": slug,
        "injected_count": len(selected),
        "injected_ids": [e.get("id") for e in selected],
        "approx_tokens": len(context) // CHARS_PER_TOKEN,
    }


def _log_injection(hook_input: dict, slug: str, selected: "list[dict]", context: str) -> None:
    """Best-effort append of one telemetry record. Wrapped so ANY failure
    (hook_utils unavailable, unwritable dir, malformed input, the append
    helper raising) is swallowed: telemetry must NEVER block the injected
    context from reaching stdout or raise from the hook (issue #781). The
    caller MUST have already written `context` to stdout before calling this.
    """
    try:
        if hook_utils is None:
            return
        record = _telemetry_record(hook_input, slug, selected, context)
        hook_utils.file_locked_append(
            str(_injection_log_path()), json.dumps(record, ensure_ascii=False)
        )
    except Exception:
        return


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

    # Defense-in-depth (Stage-2 review): _build_injection() should never
    # raise, but a SessionStart hook must NEVER surface a traceback regardless
    # of what upstream guard might have a gap -- any unexpected failure here is
    # a silent no-op, same as every other "nothing to inject" branch above.
    try:
        context, selected, slug = _build_injection(hook_input)
    except Exception:
        return

    if not context:
        # Inert (flag off or zero memories selected): emit nothing and write
        # NO telemetry record (issue #781).
        return

    # Byte-stability + fail-safe ordering (issue #781): write the injected
    # context to stdout FIRST -- it is the load-bearing output and must be
    # byte-identical to the pre-telemetry behavior -- THEN attempt the
    # best-effort telemetry side-channel. _log_injection swallows every
    # failure, so it can neither alter nor block what was just written.
    sys.stdout.write(context)
    _log_injection(hook_input, slug, selected, context)


if __name__ == "__main__":
    main()
