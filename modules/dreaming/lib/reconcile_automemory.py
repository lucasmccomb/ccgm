#!/usr/bin/env python3
"""Read-only reconciliation between Claude Code's own auto-memory and the
CCGM learnings store (Epic 8, plan.md §5).

Claude Code ships a built-in, harness-owned memory feature
(`~/.claude/projects/<harness-slug>/memory/MEMORY.md` + per-fact markdown
files, "auto-memory") that is completely independent of CCGM's learnings
store (`~/.claude/learnings/<learnings-slug>/...`, `self-improving`
module). The two stores use DIFFERENT slug namespaces for the same repo:
auto-memory keys by an encoded absolute cwd path (one per clone, e.g.
`-Users-lem-code-myrepo-clone-0`); the learnings store keys by
`learnings_store.detect_project_slug()` (git-remote derived, e.g.
`myorg_myrepo`, shared across every clone of the same repo). See
research-inputs/agent-d-claude-code.md §2.1 for the documented auto-memory
contract and its verified real-file frontmatter shape.

This module never writes to either store. It PARSES auto-memory fact
files, PARSES the learnings-store projection (via learnings_store.load_all,
already read-only), and PRINTS a markdown report identifying:

  - import candidates: auto-memory facts with no corresponding learnings-
    store row (candidates a human might want to import via
    `ccgm-learnings-log add`).
  - contradictions: learnings-store rows that dispute a topic an
    auto-memory fact still presents as current (the store row is
    deprecated, superseded, or has a `contradictions` counter > 0) --
    flagged for a human to resolve via `/consolidate`.
  - counts-only, when both sides are empty for a project.

Per decisions.md #10, reconciliation stays REPORT-ONLY in v1: the harness's
own `autoDream` consolidator owns auto-memory; colliding writers on that
file is exactly the failure class this whole system exists to prevent (see
plan.md §1.4 / adrev-306). This module MUST NEVER open a file under the
auto-memory root in a write mode -- enforced by
modules/dreaming/tests/test_reconcile_automemory.py's dynamic write-guard
test, which patches `builtins.open` and asserts zero write-mode calls
target that tree across a real end-to-end run.

Slug identity (arch-1): resolving WHICH learnings-store slug a given
auto-memory directory belongs to reuses transcript_miner's own
`_peek_slug()` -- the SAME "read a sibling transcript's `cwd` field, then
call learnings_store.detect_project_slug()" mechanism `discover()` already
uses, rather than guessing from the auto-memory directory name (arch-1: that
name is an encoded absolute cwd PATH, not the learnings-store slug, and
never conflated here).

CLI:
    reconcile_automemory.py [--projects-root DIR] [--slug SLUG]

Prints the full "## Reconciliation" markdown section to stdout. Exit code
is always 0 on a successful run (nothing to reconcile is not an error, same
posture as the rest of the dreaming chain).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import transcript_miner as tm  # noqa: E402  (sibling module, same lib/ dir)

# learnings_store lives in a DIFFERENT module's lib/ dir (self-improving).
# Reuse transcript_miner's own cross-module import helper rather than
# re-implementing it -- mirrors dream_analyze.py's identical pattern.
learnings_store = tm._import_sibling_module(  # noqa: SLF001
    "self-improving", "learnings_store", "store projection (load_all) + sanitize_content"
)

# ---------------------------------------------------------------------------
# Discovery: harness auto-memory dirs -> learnings-store slug
# ---------------------------------------------------------------------------


def default_projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def resolve_slug_for_project_dir(project_dir: Path) -> str | None:
    """Resolve the learnings-store slug this harness project dir's
    auto-memory belongs to, by peeking any sibling transcript's own `cwd`
    field via transcript_miner's `_peek_slug()` (arch-1) -- the SAME
    mechanism transcript_miner.discover() already uses for evidence mining.
    Never guessed from the directory name (that name is an encoded absolute
    cwd PATH, one per clone; multiple clones of the same repo resolve to
    ONE learnings-store slug via git-remote resolution, so directory-name
    matching would silently miss or misgroup evidence). Returns None if no
    sibling transcript resolves a slug -- callers treat None as "cannot
    determine ownership, exclude" rather than guessing.
    """
    for transcript_path in sorted(project_dir.glob("*.jsonl")):
        slug = tm._peek_slug(transcript_path)  # noqa: SLF001 (sibling module reuse, mirrors dream_analyze.py's own tm.* usage)
        if slug:
            return slug
    return None


def _scan_project_dirs_with_facts(projects_root: Path):
    """Yield `(project_dir, memory_dir, slug)` for every harness project dir
    directly under `projects_root` whose `memory/` subdir contains at least
    one `*.md` fact file. `slug` is the RESOLVED learnings-store slug, or
    `None` when no sibling transcript could resolve one (see
    resolve_slug_for_project_dir). Shared by discover_slug_to_memory_dirs()
    (keeps only the resolved entries) and count_unresolvable_slug_dirs()
    (counts the excluded/unresolved ones) so both walk the filesystem via
    one shared scan rather than duplicating the directory-listing logic."""
    if not projects_root.is_dir():
        return
    for project_dir in sorted(projects_root.iterdir()):
        if not project_dir.is_dir():
            continue
        memory_dir = project_dir / "memory"
        if not memory_dir.is_dir():
            continue
        if not any(memory_dir.glob("*.md")):
            continue
        slug = resolve_slug_for_project_dir(project_dir)
        yield project_dir, memory_dir, slug


def discover_slug_to_memory_dirs(projects_root: Path) -> dict[str, list[Path]]:
    """Enumerate `<projects_root>/*/memory/` dirs that contain at least one
    `*.md` fact file, grouped by their RESOLVED learnings-store slug (never
    by the harness directory name -- see resolve_slug_for_project_dir).
    Multiple harness project dirs (sibling clones) can map to the same
    learnings-store slug; their memory dirs are grouped under that one key.
    Dirs whose slug cannot be resolved are silently excluded here -- see
    count_unresolvable_slug_dirs() for visibility into how many were.
    """
    out: dict[str, list[Path]] = {}
    for _project_dir, memory_dir, slug in _scan_project_dirs_with_facts(projects_root):
        if slug is None:
            continue
        out.setdefault(slug, []).append(memory_dir)
    return out


def count_unresolvable_slug_dirs(projects_root: Path) -> int:
    """Count harness project dirs with fact files whose owning
    learnings-store slug could not be resolved (see
    resolve_slug_for_project_dir). These dirs are excluded from
    discover_slug_to_memory_dirs()'s mapping -- and therefore from the
    entire reconciliation report -- with no other trace. reconcile_all()
    surfaces this count as a one-line summary so a shrinking reconciliation
    surface (e.g. transcript retention pruning old sessions while
    memory/*.md files persist) is visible instead of silent (#775 Stage-2
    Recommend)."""
    return sum(1 for _pd, _md, slug in _scan_project_dirs_with_facts(projects_root) if slug is None)


# ---------------------------------------------------------------------------
# Auto-memory fact-file parsing (minimal, stdlib-only frontmatter parser)
# ---------------------------------------------------------------------------
#
# Deliberately NOT a general YAML parser -- scoped to what Claude Code's
# harness actually emits, verified against real files (research-inputs/
# agent-d-claude-code.md §2.1): `---\nname: ...\ndescription: ...\nmetadata:
# \n  node_type: memory\n  type: project\n  originSessionId: <uuid>\n---\n
# <body>`. `description` may be a bare scalar or a double-quoted, JSON-
# escaped string (both forms observed in real files). Unrecognized or
# malformed shapes degrade gracefully (missing/empty fields) rather than
# raising -- a hand-edited or future-harness-version fact file must never
# crash this read-only report.


def _parse_scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        # YAML double-quoted scalars use JSON-compatible escaping (\" \\ \n
        # etc.) for every case this harness actually produces -- reuse the
        # stdlib JSON decoder rather than hand-rolling escape handling.
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    return raw


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split `text` into (frontmatter_dict, body). frontmatter_dict is
    flattened: a one-level-nested block (e.g. `metadata:` followed by
    indented `key: value` lines) is hoisted as `metadata_key` alongside
    top-level keys -- fact files are frontmatter-shallow by construction
    (name/description, then exactly one `metadata:` block), never deeper.
    Returns ({}, text) unchanged if `text` has no `---`-delimited header.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    body = "\n".join(lines[end + 1:]).lstrip("\n")

    fm: dict[str, Any] = {}
    nested_key: str | None = None
    for line in lines[1:end]:
        if not line.strip():
            continue
        if line[:1] in (" ", "\t") and nested_key:
            stripped = line.strip()
            if ":" not in stripped:
                continue
            k, _, v = stripped.partition(":")
            fm[f"{nested_key}_{k.strip()}"] = _parse_scalar(v)
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if v == "":
            # Opens a nested block (e.g. "metadata:" with no inline value).
            nested_key = k
            continue
        nested_key = None
        fm[k] = _parse_scalar(v)
    return fm, body


def parse_fact_file(path: Path) -> dict[str, Any] | None:
    """Parse one auto-memory fact file. Returns None (never raises) on any
    read/decode failure or when neither `name` nor `description` is
    present -- a file this parser cannot make sense of is excluded from
    the report rather than guessed at.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    fm, body = parse_frontmatter(text)
    name = fm.get("name")
    description = fm.get("description")
    if not name and not description:
        return None

    return {
        "name": name or path.stem,
        "description": description or "",
        "type": fm.get("metadata_type"),
        "node_type": fm.get("metadata_node_type"),
        "origin_session_id": fm.get("metadata_originSessionId"),
        "body": body,
        "path": str(path),
    }


def parse_memory_facts(memory_dir: Path) -> list[dict[str, Any]]:
    """Parse every fact file in one auto-memory dir, excluding the index
    file itself (`MEMORY.md`, case-insensitive)."""
    out = []
    for path in sorted(memory_dir.glob("*.md")):
        if path.name.upper() == "MEMORY.MD":
            continue
        fact = parse_fact_file(path)
        if fact:
            out.append(fact)
    return out


def gather_facts_for_slug(memory_dirs: list[Path]) -> list[dict[str, Any]]:
    """Union of every fact across every memory dir mapped to one
    learnings-store slug (sibling clones), deduped by `name` (first
    occurrence wins -- order is the sorted memory_dirs order, which is
    deterministic)."""
    by_name: dict[str, dict[str, Any]] = {}
    for memory_dir in memory_dirs:
        for fact in parse_memory_facts(memory_dir):
            key = fact.get("name") or fact.get("path")
            by_name.setdefault(key, fact)
    return sorted(by_name.values(), key=lambda f: f.get("name") or "")


# ---------------------------------------------------------------------------
# Normalized-key overlap matching (deterministic bag-of-words comparison --
# NOT a semantic/LLM judgment call; see latent-vs-deterministic rule)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "were", "with", "this", "that",
    "from", "into", "onto", "than", "then", "when", "where", "which",
    "who", "whom", "have", "has", "had", "not", "but", "its", "a", "an",
    "of", "to", "in", "on", "is", "be", "as", "at", "by", "or", "if", "so",
    "no", "do", "does", "did", "can", "will", "you", "your", "their",
    "they", "them", "any", "all", "one", "two", "per", "it", "these",
    "those",
})

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")

MATCH_THRESHOLD = 0.2


def normalize_tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def _fact_tokens(fact: dict[str, Any]) -> set[str]:
    return normalize_tokens(f"{fact.get('name', '')} {fact.get('description', '')}")


def _entry_tokens(entry: dict[str, Any]) -> set[str]:
    return normalize_tokens(entry.get("content", "") or "")


def token_overlap_score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return (len(a & b) / union) if union else 0.0


def best_match(fact: dict[str, Any], entries: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    """Best-scoring store entry for `fact` by normalized token overlap.
    Returns (None, best_score_seen) when nothing clears MATCH_THRESHOLD --
    never a false-positive match on a low-confidence score."""
    fact_tokens = _fact_tokens(fact)
    best_entry: dict[str, Any] | None = None
    best_score = 0.0
    for entry in entries:
        score = token_overlap_score(fact_tokens, _entry_tokens(entry))
        if score > best_score:
            best_score = score
            best_entry = entry
    if best_score >= MATCH_THRESHOLD:
        return best_entry, best_score
    return None, best_score


def _dispute_reason(entry: dict[str, Any]) -> str:
    reasons = []
    if entry.get("deprecated"):
        reasons.append("deprecated")
    if entry.get("superseded_by"):
        reasons.append("superseded")
    contra = int(entry.get("contradictions", 0) or 0)
    if contra > 0:
        reasons.append(f"contradictions={contra}")
    return ", ".join(reasons) if reasons else "disputed"


def classify_fact(fact: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Match one fact against the store's entries for its slug and bucket
    it: `import_candidate` (no match), `contradiction` (matched a
    deprecated/superseded/contradicted row -- the store disputes what
    auto-memory still presents as current), or `confirmed` (matched a
    live, undisputed row)."""
    match, score = best_match(fact, entries)
    if match is None:
        return {"fact": fact, "match": None, "score": score, "bucket": "import_candidate"}
    disputed = bool(match.get("deprecated")) or bool(match.get("superseded_by")) or int(match.get("contradictions", 0) or 0) > 0
    return {"fact": fact, "match": match, "score": score, "bucket": "contradiction" if disputed else "confirmed"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_EXCERPT_MAX = 300


def _safe_text(text: str) -> str:
    """Auto-memory fact text (name/description) never passed through the
    store's write-time sanitizer -- unlike learnings-store `content`
    (already sanitized at write time; re-running sanitize_content() on it
    would double-wrap [neutralized] markers, since it is deliberately not
    idempotent). Sanitize once here, at first render, mirroring dream-
    digest.sh's own render-time defense-in-depth for text sourced outside
    the store's write path."""
    if not text:
        return ""
    cleaned = learnings_store.sanitize_content(text)
    if len(cleaned) > _EXCERPT_MAX:
        cleaned = cleaned[:_EXCERPT_MAX].rstrip() + "..."
    return cleaned


def _store_excerpt(text: str) -> str:
    """Store `content` is already sanitized at write time -- truncate for
    display only, never re-sanitize (see _safe_text's docstring)."""
    if not text:
        return ""
    if len(text) > _EXCERPT_MAX:
        return text[:_EXCERPT_MAX].rstrip() + "..."
    return text


def reconcile_slug(slug: str, facts: list[dict[str, Any]], entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure comparison + render for one learnings-store slug. No I/O --
    testable directly with hand-built fact/entry dicts. Returns a
    structured result (classifications) plus the rendered markdown for
    this slug's subsection."""
    classifications = [classify_fact(f, entries) for f in facts]
    import_candidates = [c for c in classifications if c["bucket"] == "import_candidate"]
    contradictions = [c for c in classifications if c["bucket"] == "contradiction"]
    confirmed = [c for c in classifications if c["bucket"] == "confirmed"]

    lines = [f"### {slug}", ""]

    if not facts and not entries:
        lines.append("_0 auto-memory facts, 0 learnings-store rows for this project. Nothing to reconcile._")
        lines.append("")
        return {
            "slug": slug, "facts": facts, "entries": entries,
            "import_candidates": import_candidates, "contradictions": contradictions,
            "confirmed": confirmed, "markdown": "\n".join(lines),
        }

    lines.append(f"- {len(facts)} auto-memory fact(s), {len(entries)} learnings-store row(s) compared.")
    lines.append("")

    if import_candidates:
        lines.append("**Import candidates** (auto-memory facts not represented in the learnings store):")
        lines.append("")
        for c in import_candidates:
            fact = c["fact"]
            # Both `name` and `description` are model-influenceable (the
            # harness's own memory tool chooses both when it writes a fact)
            # and never passed through the store's write-time sanitizer --
            # _safe_text() must wrap BOTH at render time (#775 Stage-2
            # Blocking: `name` was previously interpolated raw here).
            lines.append(f"- `{_safe_text(fact.get('name') or '')}` -- {_safe_text(fact.get('description') or '')} (`{fact.get('path')}`)")
        lines.append("")

    if contradictions:
        lines.append("**Contradictions** (learnings-store rows disputing an auto-memory fact -- flag for `/consolidate`):")
        lines.append("")
        for c in contradictions:
            fact = c["fact"]
            entry = c["match"] or {}
            lines.append(
                f"- store row `{entry.get('id', '?')}` ({_dispute_reason(entry)}) conflicts with auto-memory fact "
                f"`{_safe_text(fact.get('name') or '')}`: store says \"{_store_excerpt(entry.get('content') or '')}\"; "
                f"auto-memory says \"{_safe_text(fact.get('description') or '')}\""
            )
        lines.append("")

    if not import_candidates and not contradictions:
        lines.append(
            f"_All {len(confirmed)} matched auto-memory fact(s) already represented in the learnings store; "
            "no contradictions detected._"
        )
        lines.append("")

    return {
        "slug": slug, "facts": facts, "entries": entries,
        "import_candidates": import_candidates, "contradictions": contradictions,
        "confirmed": confirmed, "markdown": "\n".join(lines),
    }


REPORT_HEADER = [
    "## Reconciliation",
    "",
    "_Read-only comparison between Claude Code's own auto-memory "
    "(`~/.claude/projects/*/memory/`) and the CCGM learnings store "
    "(`~/.claude/learnings/`). Never writes to either store -- see "
    "`modules/dreaming/lib/reconcile_automemory.py`._",
    "",
]


def reconcile_all(projects_root: str | Path | None = None, target_slug: str | None = None) -> str:
    """Full orchestration: discover every harness auto-memory dir, resolve
    each to a learnings-store slug, compare against that slug's store
    projection, and return the complete "## Reconciliation" markdown
    section (all slugs, or just `target_slug` when given)."""
    root = Path(projects_root) if projects_root else default_projects_root()
    header = list(REPORT_HEADER)

    excluded_count = count_unresolvable_slug_dirs(root)
    if excluded_count:
        header.append(
            f"_{excluded_count} project dir(s) had fact files but no resolvable learnings-store slug; "
            "excluded from this comparison._"
        )
        header.append("")

    slug_to_dirs = discover_slug_to_memory_dirs(root)
    if target_slug:
        slug_to_dirs = {s: d for s, d in slug_to_dirs.items() if s == target_slug}

    if not slug_to_dirs:
        header.append(f"_No auto-memory directories with fact files found under `{root}`._")
        header.append("")
        return "\n".join(header)

    sections = []
    for slug in sorted(slug_to_dirs):
        facts = gather_facts_for_slug(slug_to_dirs[slug])
        entries = learnings_store.load_all(slug)
        result = reconcile_slug(slug, facts, entries)
        sections.append(result["markdown"])

    return "\n".join(header + sections)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read-only reconciliation between Claude Code's own auto-memory and the CCGM learnings store."
    )
    p.add_argument(
        "--projects-root", metavar="DIR",
        help="override the harness auto-memory discovery root (default ~/.claude/projects)",
    )
    p.add_argument(
        "--slug", metavar="SLUG",
        help="limit reconciliation to one learnings-store slug (default: every discoverable slug)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    print(reconcile_all(projects_root=args.projects_root, target_slug=args.slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
