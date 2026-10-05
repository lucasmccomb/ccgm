#!/usr/bin/env python3
"""Loaded-context corpus and deterministic prefilter for dreaming (#1098 Phase 3.3).

Every Claude Code session already loads the rules, the CLAUDE.md chain,
auto-memory, and hook messages. A mined learning that restates one of those
teaches the agent nothing, yet the reduce step used to dedupe only against
the learnings store. This module builds the full set of "what every session
already knows" each night, with no model calls, and scores map candidates
against it.

Corpus sources (each unit keeps the path it came from):

    rule                ~/.claude/rules/*.md (symlinks followed)
    claude_md           ~/.claude/CLAUDE.md plus every CLAUDE.md and
                        .claude/rules/*.md from each known cwd up to /
    auto_memory         <projects>/<cwd-encoded>/memory/*.md
    hook                string constants and docstrings of ~/.claude/hooks/*.py
                        (the denial and block messages)
    store               live learnings-store rows for the slug and _global
    pending_proposal    status=pending add/supersede rows in proposals/, .gz too
    discarded_proposal  status=rejected add/supersede rows, same files

Scoring is the cosine of two token sets (lower-cased, stop-word-free, lightly
stemmed), each token weighted by its inverse document frequency in the corpus,
the weighting BM25 uses. Plain Jaccard topped out at 0.36 on real pending
learnings: they elaborate the rule text, so a candidate shares a fraction of a
long unit's tokens. Stdlib only.

`prefilter_candidates()` runs between the map and the reduce so dropped
candidates never reach the reduce prompt. It drops a candidate when

  * its best match in a droppable category scores >= threshold
    (reason `already_encoded`, with the matching source path), or
  * (Phase 3.2, reason `routed_to_autoheal`) all of its evidence is friction
    that autoheal's `failure-logger.py` already records first-hand, in real
    time: a hook error from an installed hook, or a tool error whose text the
    candidate's content mostly restates. A candidate that cites any signal
    from the miner's extractors (redirection, struggle_arc, conclusion,
    abandoned_work, rediscovery) is kept even when tool errors are present.
    Dreaming forwards nothing to autoheal; it only stops turning that
    friction into memory proposals.

`store` rows are in the corpus but are not droppable: a candidate that
restates a live row is a `learning_verify` waiting to happen, so it passes
through with the row as one of its snippets.

Every root is a field of `Roots`, overridable by env var or argument, so
tests run on temp directories.
"""
from __future__ import annotations

import ast
import gzip
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from transcript_miner import _WORKTREE_SEGMENT  # noqa: E402  (sibling module, same lib/ dir)

ALREADY_ENCODED = "already_encoded"
ROUTED_TO_AUTOHEAL = "routed_to_autoheal"

DEFAULT_THRESHOLD = 0.35
# Tool-error restatement: the same idf-weighted cosine, scored between the
# candidate's content and its own error excerpts. See the README for the pick.
DEFAULT_FRICTION_THRESHOLD = 0.35
# An evidence excerpt counts as a bundle signal or friction exemplar when it
# shares at least this fraction of the shorter text's tokens with it, so a
# quote the model truncated or lightly trimmed still classifies.
_EXCERPT_MATCH_OVERLAP = 0.8
_MIN_EXCERPT_TOKENS = 3
DEFAULT_SNIPPET_COUNT = 3
DEFAULT_RECENT_DAYS = 30

# Categories whose match drops a candidate. `store` is absent on purpose.
DROP_CATEGORIES = frozenset({
    "rule", "claude_md", "auto_memory", "hook", "pending_proposal", "discarded_proposal",
})
# Drops matched to a prior proposal count toward `proposals_deduped`.
PRIOR_PROPOSAL_CATEGORIES = frozenset({"pending_proposal", "discarded_proposal"})

_MIN_UNIT_TOKENS = 4
_MAX_UNIT_CHARS = 3000
_SNIPPET_CHARS = 300
_HEAD_LINES_FOR_CWD = 60

# ---------------------------------------------------------------------------
# Roots
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Roots:
    claude_home: Path
    rules_dir: Path
    hooks_dir: Path
    projects_root: Path
    proposals_dir: Path

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        projects_root: str | Path | None = None,
        proposals_dir: str | Path | None = None,
    ) -> "Roots":
        """CCGM_DREAMING_CLAUDE_HOME moves the whole tree (default ~/.claude);
        CCGM_DREAMING_RULES_DIR and CCGM_DREAMING_HOOKS_DIR move one piece."""
        env = os.environ if env is None else env
        home = Path(env.get("CCGM_DREAMING_CLAUDE_HOME") or os.path.expanduser("~/.claude"))
        dreaming = Path(env.get("CCGM_DREAMING_DIR") or home / "dreaming")
        return cls(
            claude_home=home,
            rules_dir=Path(env.get("CCGM_DREAMING_RULES_DIR") or home / "rules"),
            hooks_dir=Path(env.get("CCGM_DREAMING_HOOKS_DIR") or home / "hooks"),
            projects_root=Path(projects_root) if projects_root else home / "projects",
            proposals_dir=Path(proposals_dir) if proposals_dir else dreaming / "proposals",
        )


# ---------------------------------------------------------------------------
# Tokens and similarity
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have how if in into is it its may
might more most no not of on one only or other our out over should so some such than that the their them then
there these they this those to too up use used uses using was we were what when where which while who will with
would you your also any each every just like must now than very via within without
""".split())


def _stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 4 and word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> frozenset[str]:
    out = set()
    for word in _WORD_RE.findall(text.lower()):
        if len(word) < 2 or word in _STOPWORDS:
            continue
        out.add(_stem(word))
    return frozenset(out)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Unit:
    source: str
    category: str
    text: str
    tokens: frozenset[str] = field(compare=False)


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MD_NOISE_RE = re.compile(r"^[\s>#*|`-]+|[\s|`]+$")


def split_units(text: str) -> list[str]:
    """The whole text when it is short, its paragraphs, each multi-line paragraph's lines (bullets, table rows),
    and each long paragraph's sentences and sentence pairs. A paraphrase of
    one bullet should not have to compete with the whole file."""
    seen: set[str] = set()
    out: list[str] = []

    def add(chunk: str) -> None:
        chunk = chunk.strip()[:_MAX_UNIT_CHARS]
        if chunk and chunk not in seen and len(tokenize(chunk)) >= _MIN_UNIT_TOKENS:
            seen.add(chunk)
            out.append(chunk)

    # A short note (an auto-memory file) is one idea spread over several
    # paragraphs; match it whole as well.
    if len(text.strip()) <= _MAX_UNIT_CHARS:
        add(text)
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        add(paragraph)
        lines = [_MD_NOISE_RE.sub("", ln) for ln in paragraph.splitlines()]
        lines = [ln for ln in lines if ln]
        if len(lines) > 1:
            for ln in lines:
                add(ln)
        flat = " ".join(lines)
        sentences = [s for s in _SENTENCE_RE.split(flat) if s]
        if len(sentences) > 1:
            for s in sentences:
                add(s)
            for first, second in zip(sentences, sentences[1:]):
                add(f"{first} {second}")
    return out


def _units_from_text(text: str, source: str, category: str) -> list[Unit]:
    return [Unit(source, category, chunk, tokenize(chunk)) for chunk in split_units(text)]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _python_string_units(path: Path) -> list[Unit]:
    text = _read_text(path)
    if text is None:
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    units: list[Unit] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if len(value) >= 25 and len(value.split()) >= 4:
                units.extend(_units_from_text(value, str(path), "hook"))
    return units


def installed_hook_names(hooks_dir: Path) -> set[str]:
    try:
        return {p.name for p in Path(hooks_dir).glob("*.py") if p.is_file()}
    except OSError:
        return set()


# ---------------------------------------------------------------------------
# Proposal files (plain and gzipped)
# ---------------------------------------------------------------------------


def proposal_files(pdir: Path) -> list[Path]:
    """Every proposals/*.jsonl and *.jsonl.gz, oldest first."""
    pdir = Path(pdir)
    if not pdir.is_dir():
        return []
    return sorted([*pdir.glob("*.jsonl"), *pdir.glob("*.jsonl.gz")], key=lambda p: p.name)


def read_proposal_rows(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if str(path).endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except (OSError, EOFError, gzip.BadGzipFile):
        return


def _plain_name(path: Path) -> str:
    name = Path(path).name
    return name[:-3] if name.endswith(".gz") else name


def _file_date(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.name[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


def encode_cwd(cwd: str) -> str:
    """Claude Code's project-directory name for a cwd."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


class Corpus:
    """Units plus an inverted index. Similarity is the cosine of the two token
    sets with each token weighted by its inverse document frequency in this
    corpus (the weighting BM25 uses): sum(idf of shared tokens) divided by
    sqrt(sum(idf of the candidate) * sum(idf of the unit)). A shared rare term
    such as a tool or hook name counts for more than shared filler, and the
    unit-size term keeps a long unit from matching everything."""

    def __init__(self, units: list[Unit]):
        self.units = units
        self._index: dict[str, list[int]] = {}
        for i, unit in enumerate(units):
            for token in unit.tokens:
                self._index.setdefault(token, []).append(i)
        n = max(len(units), 1)
        self._idf = {t: math.log(1 + n / len(ids)) for t, ids in self._index.items()}
        self._unseen_idf = math.log(1 + n)
        self._unit_weight = [sum(self._idf[t] for t in u.tokens) for u in units]

    def matches(
        self, text: str, *, n: int = DEFAULT_SNIPPET_COUNT, categories: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Best unit per source, highest score first, at most `n`."""
        tokens = tokenize(text)
        if not tokens:
            return []
        allowed = frozenset(categories) if categories is not None else None
        cand_weight = sum(self._idf.get(t, self._unseen_idf) for t in tokens)
        shared: dict[int, float] = {}
        for token in tokens:
            weight = self._idf.get(token)
            if weight is None:
                continue
            for i in self._index[token]:
                shared[i] = shared.get(i, 0.0) + weight
        best: dict[str, tuple[float, Unit]] = {}
        for i, inter in shared.items():
            unit = self.units[i]
            if allowed is not None and unit.category not in allowed:
                continue
            score = inter / math.sqrt(cand_weight * self._unit_weight[i])
            current = best.get(unit.source)
            if current is None or score > current[0]:
                best[unit.source] = (score, unit)
        ranked = sorted(best.values(), key=lambda pair: (-pair[0], pair[1].source))[:n]
        return [
            {"score": round(score, 3), "source": unit.source, "category": unit.category, "text": unit.text}
            for score, unit in ranked
        ]


def _cwd_chain(cwd: str) -> list[Path]:
    path = Path(cwd)
    return [path, *path.parents]


def build_corpus(
    slug: str,
    *,
    cwds: Iterable[str],
    roots: Roots,
    store_rows: Mapping[str, list[dict[str, Any]]] | None = None,
    today: str | None = None,
    recent_days: int = DEFAULT_RECENT_DAYS,
    exclude_proposal_path: Path | None = None,
) -> Corpus:
    cwds = [c for c in dict.fromkeys(cwds) if isinstance(c, str) and c]
    units: list[Unit] = []
    seen_files: set[str] = set()

    def add_file(path: Path, category: str) -> None:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen_files:
            return
        seen_files.add(key)
        text = _read_text(path)
        if text:
            units.extend(_units_from_text(text, str(path), category))

    try:
        rule_files = sorted(Path(roots.rules_dir).glob("*.md"))
    except OSError:
        rule_files = []
    for path in rule_files:
        add_file(path, "rule")

    add_file(Path(roots.claude_home) / "CLAUDE.md", "claude_md")
    for cwd in cwds:
        for directory in _cwd_chain(cwd):
            add_file(directory / "CLAUDE.md", "claude_md")
            try:
                project_rules = sorted((directory / ".claude" / "rules").glob("*.md"))
            except OSError:
                project_rules = []
            for path in project_rules:
                add_file(path, "claude_md")

    for cwd in cwds:
        candidates = [cwd]
        if _WORKTREE_SEGMENT in cwd:
            candidates.append(cwd.split(_WORKTREE_SEGMENT, 1)[0])
        for candidate in candidates:
            memory_dir = Path(roots.projects_root) / encode_cwd(candidate) / "memory"
            try:
                memory_files = sorted(memory_dir.glob("*.md"))
            except OSError:
                memory_files = []
            for path in memory_files:
                add_file(path, "auto_memory")

    try:
        hook_files = sorted(Path(roots.hooks_dir).glob("*.py"))
    except OSError:
        hook_files = []
    for path in hook_files:
        units.extend(_python_string_units(path))

    for scope, rows in (store_rows or {}).items():
        for row in rows or []:
            content = row.get("content") if isinstance(row, dict) else None
            if isinstance(content, str) and content.strip():
                units.extend(_units_from_text(content, f"store:{scope}:{row.get('id')}", "store"))

    units.extend(_proposal_units(slug, roots, today, recent_days, exclude_proposal_path))

    # Equal text from two sources stays: the source path is the point.
    return Corpus(units)


def _proposal_units(
    slug: str, roots: Roots, today: str | None, recent_days: int, exclude: Path | None,
) -> list[Unit]:
    cutoff = None
    if today:
        try:
            cutoff = date.fromisoformat(today) - timedelta(days=recent_days)
        except ValueError:
            cutoff = None
    exclude_name = _plain_name(exclude) if exclude is not None else None
    exclude_parent = Path(exclude).resolve().parent if exclude is not None else None
    units: list[Unit] = []
    for path in proposal_files(roots.proposals_dir):
        if exclude_name and _plain_name(path) == exclude_name and path.resolve().parent == exclude_parent:
            continue
        file_day = _file_date(path)
        if cutoff is not None and file_day is not None and file_day < cutoff:
            continue
        for row in read_proposal_rows(path):
            status = row.get("status")
            category = {"pending": "pending_proposal", "rejected": "discarded_proposal"}.get(status)
            content = row.get("content")
            if (
                category is None
                or row.get("kind") not in ("learning_add", "learning_supersede")
                or not isinstance(content, str)
                or not content.strip()
                or row.get("project") not in (slug, "_global")
            ):
                continue
            units.extend(_units_from_text(content, f"{path}#{row.get('id')}", category))
    return units


_PENDING_CONTENT_CHARS = 240


def pending_proposals_for_reduce(
    proposals_dir: Path,
    projects: Iterable[str],
    *,
    limit: int,
    exclude_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Pending proposals for the given projects in compact form, newest first,
    so the reduce can verify or skip one instead of proposing it again."""
    wanted = set(projects)
    exclude_name = _plain_name(exclude_path) if exclude_path is not None else None
    out: list[dict[str, Any]] = []
    for path in reversed(proposal_files(proposals_dir)):
        if exclude_name and _plain_name(path) == exclude_name:
            continue
        for row in reversed(list(read_proposal_rows(path))):
            if row.get("status") != "pending" or row.get("project") not in wanted:
                continue
            content = row.get("content")
            out.append({
                "id": row.get("id"),
                "kind": row.get("kind"),
                "project": row.get("project"),
                "target_id": row.get("target_id"),
                "content": content[:_PENDING_CONTENT_CHARS] if isinstance(content, str) else None,
                "sessions": sorted({
                    e["session_id"] for e in row.get("evidence") or []
                    if isinstance(e, dict) and e.get("session_id")
                }),
            })
            if len(out) >= limit:
                return out
    return out


# ---------------------------------------------------------------------------
# cwds of the transcripts being mined
# ---------------------------------------------------------------------------


def transcript_cwds(paths: Iterable[str | Path]) -> list[str]:
    """The distinct `cwd` of each transcript, read from its first lines."""
    found: dict[str, None] = {}
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh):
                    if lineno >= _HEAD_LINES_FOR_CWD:
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict) and isinstance(obj.get("cwd"), str) and obj["cwd"]:
                        found[obj["cwd"]] = None
                        break
        except OSError:
            continue
    return list(found)


# ---------------------------------------------------------------------------
# Prefilter
# ---------------------------------------------------------------------------

_HOOK_ERROR_RE = re.compile(r"hook error:\s*\[([^\]]*)\]")
_HOOK_FILE_RE = re.compile(r"hooks/([\w.\-]+\.py)")


def installed_hook_in_error(excerpt: str, hook_names: set[str]) -> str | None:
    """The installed hook file a hook-error excerpt names, or None."""
    for bracket in _HOOK_ERROR_RE.findall(excerpt or ""):
        for name in _HOOK_FILE_RE.findall(bracket):
            if name in hook_names:
                return name
    return None


def is_installed_hook_error(excerpt: str, hook_names: set[str]) -> bool:
    return installed_hook_in_error(excerpt, hook_names) is not None


def _snippet(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": match["source"],
        "category": match["category"],
        "score": match["score"],
        "text": match["text"][:_SNIPPET_CHARS],
    }


class EvidenceIndex:
    """What kind of text each bundle excerpt is: a knowledge-bearing signal or
    a friction-cluster exemplar (a tool error or hook denial)."""

    def __init__(self, signals: list[frozenset[str]], friction: list[frozenset[str]]):
        self.signals = signals
        self.friction = friction

    @staticmethod
    def _matches(tokens: frozenset[str], pool: list[frozenset[str]]) -> bool:
        if len(tokens) < _MIN_EXCERPT_TOKENS:
            return False
        for other in pool:
            if (
                len(other) >= _MIN_EXCERPT_TOKENS
                and len(tokens & other) / min(len(tokens), len(other)) >= _EXCERPT_MATCH_OVERLAP
            ):
                return True
        return False

    def classify(self, excerpt: str) -> str:
        """`signal`, `friction`, or `unknown`. A signal wins over friction;
        text that matches neither is never treated as friction."""
        tokens = tokenize(excerpt or "")
        if self._matches(tokens, self.signals):
            return "signal"
        if self._matches(tokens, self.friction):
            return "friction"
        return "unknown"


def build_evidence_index(bundle: Mapping[str, Any]) -> EvidenceIndex:
    signals = [
        tokenize(sig["excerpt"]) for sig in bundle.get("signals") or []
        if isinstance(sig, dict) and isinstance(sig.get("excerpt"), str)
    ]
    friction = [
        tokenize(ex["excerpt"])
        for cluster in bundle.get("clusters") or []
        if isinstance(cluster, dict) and cluster.get("is_friction")
        for ex in cluster.get("exemplars") or []
        if isinstance(ex, dict) and isinstance(ex.get("excerpt"), str)
    ]
    return EvidenceIndex(signals, friction)


def error_restatement_score(content: str, error_excerpts: list[str]) -> float | None:
    """Best score of `content` against the error excerpts, or None when no
    excerpt is long enough to form a unit."""
    units: list[Unit] = []
    for excerpt in error_excerpts:
        units.extend(_units_from_text(excerpt, "tool_error", "tool_error"))
    hits = Corpus(units).matches(content, n=1) if units else []
    return hits[0]["score"] if hits else None


def prefilter_candidates(
    candidates: list[dict[str, Any]],
    corpus: Corpus,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    hook_names: set[str],
    hooks_dir: Path | None = None,
    snippet_count: int = DEFAULT_SNIPPET_COUNT,
    evidence_index: EvidenceIndex | None = None,
    friction_threshold: float = DEFAULT_FRICTION_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (kept, dropped). Each kept candidate is a copy carrying its top
    `snippet_count` corpus snippets as `corpus_snippets`. Each dropped record
    names the reason, the matching source path and category, and the score.

    Without `evidence_index` the tool-error rule is off: nothing says which
    evidence is a signal and which is friction."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for cand in candidates:
        content = cand.get("content") or ""
        excerpts = [e.get("excerpt", "") for e in cand.get("evidence") or [] if isinstance(e, dict)]
        hook_files = [installed_hook_in_error(x, hook_names) for x in excerpts]
        if excerpts and all(hook_files):
            source = str(Path(hooks_dir) / hook_files[0]) if hooks_dir else hook_files[0]
            dropped.append({"reason": ROUTED_TO_AUTOHEAL, "source": source, "category": "hook", "score": None, "content": content[:160]})
            continue
        if evidence_index is not None and excerpts and all(evidence_index.classify(x) == "friction" for x in excerpts):
            score = error_restatement_score(content, excerpts)
            if score is not None and score >= friction_threshold:
                dropped.append({
                    "reason": ROUTED_TO_AUTOHEAL, "source": "tool_error", "category": "tool_error",
                    "score": score, "content": content[:160],
                })
                continue
        top = corpus.matches(content, n=snippet_count)
        droppable = corpus.matches(content, n=1, categories=DROP_CATEGORIES)
        if droppable and droppable[0]["score"] >= threshold:
            hit = droppable[0]
            dropped.append({
                "reason": ALREADY_ENCODED, "source": hit["source"], "category": hit["category"],
                "score": hit["score"], "content": content[:160],
            })
            continue
        kept.append({**cand, "corpus_snippets": [_snippet(m) for m in top]})
    return kept, dropped


# ---------------------------------------------------------------------------
# Evidence-based fingerprint key
# ---------------------------------------------------------------------------

_MAX_KEY_TERMS = 12
_MIN_KEY_TERM_CHARS = 4


def evidence_key_basis(content: str, evidence: list[dict[str, Any]], target_id: str | None = None) -> str:
    """`target | sorted evidence session ids | normalized key terms`.

    Key terms are the content tokens that also occur in the cited excerpts,
    so they come from the verbatim evidence and survive a reworded `content`.
    When none overlap, the content's own long tokens stand in."""
    sessions = sorted({e["session_id"] for e in evidence if isinstance(e, dict) and e.get("session_id")})
    evidence_tokens: set[str] = set()
    for e in evidence:
        if isinstance(e, dict) and isinstance(e.get("excerpt"), str):
            evidence_tokens |= tokenize(e["excerpt"])
    content_tokens = {t for t in tokenize(content) if len(t) >= _MIN_KEY_TERM_CHARS}
    terms = content_tokens & evidence_tokens or content_tokens
    ranked = sorted(terms, key=lambda t: (-len(t), t))[:_MAX_KEY_TERMS]
    return f"{target_id or ''}|{','.join(sessions)}|{','.join(sorted(ranked))}"
