#!/usr/bin/env python3
"""
Learnings store: shared library for ccgm-learnings-log and ccgm-learnings-search.

A learning is a structured, project-scoped record of a pattern, pitfall,
preference, architecture note, tool gotcha, or operational fact. Learnings are
appended to a JSONL file per project with schema validation, prompt-injection
sanitization on write, and time-based confidence decay on read.

Storage layout:
    ~/.claude/learnings/
        config.json                 # Cross-project search opt-in and tunables
        {project-slug}/
            learnings.jsonl         # Append-only, one JSON object per line
        _global/
            learnings.jsonl         # Cross-project scope (tagged learnings)

Schema per entry:
    {
      "id": "<uuid4 short>",
      "timestamp": "<ISO 8601 UTC>",
      "type": "pattern|pitfall|preference|architecture|tool|operational",
      "source": "observed|user-stated|inferred|cross-model",
      "content": "<sanitized prose, single paragraph>",
      "confidence": 1-10,
      "tags": ["<lowercase kebab>", ...],
      "files": ["<repo-relative path>", ...],
      "project": "<slug>",
      "key": "<dedup key, auto-derived from content if absent>",
      "last_verified": "<ISO 8601 UTC>",
      "uses": 0,
      "contradictions": 0,
      "deprecated": false
    }

Read path applies:
    - Time-based confidence decay (half-life configurable, default 90d).
    - Dedup by (key, type): latest winner when keys collide.
    - Optional staleness flag when referenced files no longer exist.
    - Injection filter: drops sanitized-only noise, caps output by token budget.

This file is intentionally stdlib-only (no PyYAML, no requests) so it installs
cleanly without pip.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

LEARNINGS_ROOT = Path(os.path.expanduser(
    os.environ.get("CCGM_LEARNINGS_DIR", "~/.claude/learnings")
))
CONFIG_PATH = LEARNINGS_ROOT / "config.json"
GLOBAL_SLUG = "_global"

# ---------------------------------------------------------------------------
# Schema vocabulary
# ---------------------------------------------------------------------------

VALID_TYPES = {"pattern", "pitfall", "preference", "architecture", "tool", "operational"}
VALID_SOURCES = {"observed", "user-stated", "inferred", "cross-model"}
CONFIDENCE_MIN = 1
CONFIDENCE_MAX = 10
DEFAULT_CONFIDENCE = 5

DEFAULT_HALF_LIFE_DAYS = 90.0
DEFAULT_DEPRECATE_THRESHOLD = 2.0   # effective confidence below this -> skip on read
DEFAULT_STALE_DAYS = 180.0          # flag entries not verified in this long
DEFAULT_TOKEN_BUDGET = 2000         # rough character-based budget (4 chars/token)
DEFAULT_MAX_RESULTS = 8

# ---------------------------------------------------------------------------
# Config (cross-project opt-in, tunables)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "cross_project_search": False,
    "half_life_days": DEFAULT_HALF_LIFE_DAYS,
    "deprecate_threshold": DEFAULT_DEPRECATE_THRESHOLD,
    "stale_days": DEFAULT_STALE_DAYS,
    "token_budget": DEFAULT_TOKEN_BUDGET,
    "max_results": DEFAULT_MAX_RESULTS,
}


def load_config() -> dict[str, Any]:
    """Load config.json if present, merged over defaults."""
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.is_file():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    LEARNINGS_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Project slug detection
# ---------------------------------------------------------------------------

def detect_project_slug(cwd: str | None = None) -> str:
    """
    Derive a stable project slug from the git remote URL or the working dir.

    Precedence:
    1. CCGM_LEARNINGS_PROJECT env var (explicit override).
    2. git remote origin -> {owner}_{repo} (sanitized).
    3. basename of git toplevel.
    4. basename of cwd.
    """
    env = os.environ.get("CCGM_LEARNINGS_PROJECT")
    if env:
        return _slugify(env)

    wd = cwd or os.getcwd()
    try:
        import subprocess
        remote = subprocess.run(
            ["git", "-C", wd, "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=2,
        )
        if remote.returncode == 0 and remote.stdout.strip():
            url = remote.stdout.strip()
            # Parse owner/repo from https or ssh URLs
            m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
            if m:
                return _slugify(f"{m.group(1)}_{m.group(2)}")

        toplevel = subprocess.run(
            ["git", "-C", wd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        if toplevel.returncode == 0 and toplevel.stdout.strip():
            return _slugify(Path(toplevel.stdout.strip()).name)
    except Exception:
        pass

    return _slugify(Path(wd).name)


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "unknown"


def project_jsonl(slug: str) -> Path:
    return LEARNINGS_ROOT / slug / "learnings.jsonl"


# ---------------------------------------------------------------------------
# Prompt-injection sanitizer
# ---------------------------------------------------------------------------

# Patterns that look like LLM instructions and should never survive the write
# path. We neutralize them by wrapping in literal quotes and prefixing with
# [neutralized] so the text survives but cannot be executed as an instruction
# by a downstream consumer.
#
# The goal is NOT to prevent all possible injection; it is to catch the common
# accidental case where a user pastes a prompt into the content field and the
# content later gets injected into a system prompt verbatim.

INJECTION_PATTERNS = [
    r"(?im)^\s*system\s*:",
    r"(?im)^\s*assistant\s*:",
    r"(?im)^\s*user\s*:",
    r"(?im)^\s*ignore (?:all\s+|previous\s+|prior\s+)+(?:instructions|prompts)",
    r"(?im)^\s*you are (?:now|an?)\b",
    r"(?im)^\s*disregard .* (?:rules|instructions|guidelines)",
    r"(?im)<\s*/?\s*(?:system|instructions|prompt)\s*>",
    r"(?im)```\s*system",
]


def sanitize_content(text: str) -> str:
    """
    Neutralize instruction-like patterns in user-supplied content.

    Wraps matches with `[neutralized]...[/neutralized]` markers so the text
    stays readable but downstream injection becomes inert.
    """
    out = text
    for pat in INJECTION_PATTERNS:
        out = re.sub(
            pat,
            lambda m: f"[neutralized]{m.group(0)}[/neutralized]",
            out,
        )
    # Collapse runs of whitespace
    out = re.sub(r"[ \t]+", " ", out).strip()
    # Cap length to prevent pathological entries
    if len(out) > 2000:
        out = out[:2000].rstrip() + "..."
    return out


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class ValidationError(ValueError):
    pass


def validate_entry(entry: dict[str, Any]) -> None:
    """Raise ValidationError if entry violates schema. Mutates nothing."""
    required = {"type", "content"}
    missing = required - entry.keys()
    if missing:
        raise ValidationError(f"missing required fields: {sorted(missing)}")

    if entry["type"] not in VALID_TYPES:
        raise ValidationError(
            f"invalid type {entry['type']!r}, expected one of {sorted(VALID_TYPES)}"
        )

    src = entry.get("source", "observed")
    if src not in VALID_SOURCES:
        raise ValidationError(
            f"invalid source {src!r}, expected one of {sorted(VALID_SOURCES)}"
        )

    conf = entry.get("confidence", DEFAULT_CONFIDENCE)
    if not isinstance(conf, (int, float)) or not (CONFIDENCE_MIN <= conf <= CONFIDENCE_MAX):
        raise ValidationError(
            f"confidence must be {CONFIDENCE_MIN}-{CONFIDENCE_MAX}, got {conf!r}"
        )

    if not isinstance(entry["content"], str) or not entry["content"].strip():
        raise ValidationError("content must be a non-empty string")

    for field in ("tags", "files"):
        if field in entry and not isinstance(entry[field], list):
            raise ValidationError(f"{field} must be a list")


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    # Millisecond precision so rapid successive writes produce distinct timestamps
    # for dedup tie-breaking. Still serializes as ISO 8601 with trailing Z.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def _dedup_key(content: str, type_: str) -> str:
    """Derive a stable dedup key from content."""
    normalized = re.sub(r"\s+", " ", content.lower().strip())
    digest = hashlib.sha1(f"{type_}:{normalized}".encode()).hexdigest()
    return digest[:12]


def build_entry(
    *,
    type_: str,
    content: str,
    source: str = "observed",
    confidence: int = DEFAULT_CONFIDENCE,
    tags: list[str] | None = None,
    files: list[str] | None = None,
    project: str | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    """
    Build a schema-valid, sanitized entry. Does NOT write.
    """
    sanitized = sanitize_content(content)
    entry: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": _utc_now_iso(),
        "type": type_,
        "source": source,
        "content": sanitized,
        "confidence": int(confidence),
        "tags": sorted({t.lower().strip() for t in (tags or []) if t.strip()}),
        "files": [f for f in (files or []) if f],
        "project": project or detect_project_slug(),
        "key": key or _dedup_key(sanitized, type_),
        "last_verified": _utc_now_iso(),
        "uses": 0,
        "contradictions": 0,
        "deprecated": False,
    }
    validate_entry(entry)
    return entry


def append_entry(entry: dict[str, Any], slug: str | None = None) -> Path:
    """Append a pre-validated entry to the project JSONL file."""
    validate_entry(entry)
    target_slug = slug or entry.get("project") or detect_project_slug()
    path = project_jsonl(target_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return path


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def iter_entries(slug: str) -> Iterable[dict[str, Any]]:
    """Yield entries from one project's JSONL, skipping malformed lines."""
    path = project_jsonl(slug)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_all(slug: str) -> list[dict[str, Any]]:
    return list(iter_entries(slug))


def list_project_slugs() -> list[str]:
    if not LEARNINGS_ROOT.is_dir():
        return []
    return sorted(
        d.name for d in LEARNINGS_ROOT.iterdir()
        if d.is_dir() and (d / "learnings.jsonl").is_file()
    )


# ---------------------------------------------------------------------------
# Confidence decay + staleness
# ---------------------------------------------------------------------------

def _parse_iso(s: str) -> float:
    """Parse ISO 8601 UTC string to epoch seconds. 0.0 on failure.
    Accepts both second- and millisecond-precision forms (trailing Z).
    """
    if not s:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return 0.0


def effective_confidence(
    entry: dict[str, Any],
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    now: float | None = None,
) -> float:
    """
    Compute time-decayed confidence for read-time ranking.

    Uses exponential decay with the given half-life, anchored on last_verified
    (falling back to timestamp). A `uses` counter slows decay; a
    `contradictions` counter accelerates it. Explicit `deprecated` zeroes out.
    """
    if entry.get("deprecated"):
        return 0.0
    base = float(entry.get("confidence", DEFAULT_CONFIDENCE))
    uses = int(entry.get("uses", 0))
    contra = int(entry.get("contradictions", 0))

    # Reuse slightly boosts; contradictions cut hard.
    base = base + min(uses * 0.25, 2.0) - (contra * 1.5)
    base = max(0.0, min(float(CONFIDENCE_MAX), base))

    ts = _parse_iso(entry.get("last_verified") or entry.get("timestamp", ""))
    if ts <= 0:
        return base

    now_ts = now if now is not None else time.time()
    age_days = max(0.0, (now_ts - ts) / 86400.0)
    if half_life_days <= 0:
        return base
    decay = math.pow(0.5, age_days / half_life_days)
    return base * decay


def is_stale(
    entry: dict[str, Any],
    *,
    stale_days: float = DEFAULT_STALE_DAYS,
    now: float | None = None,
) -> bool:
    ts = _parse_iso(entry.get("last_verified") or entry.get("timestamp", ""))
    if ts <= 0:
        return True
    now_ts = now if now is not None else time.time()
    return (now_ts - ts) / 86400.0 > stale_days


def has_stale_file_refs(entry: dict[str, Any], repo_root: Path | None = None) -> bool:
    """
    If entry lists files and a repo_root is provided, return True when any
    referenced file no longer exists. Used to flag entries whose anchor
    moved.
    """
    files = entry.get("files") or []
    if not files or repo_root is None:
        return False
    for rel in files:
        if not (repo_root / rel).exists():
            return True
    return False


# ---------------------------------------------------------------------------
# Dedup + ranking
# ---------------------------------------------------------------------------

def dedup_latest(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Within each (key, type), keep only the latest entry by timestamp.
    Preserves input order for stability within the selected set.
    """
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for e in entries:
        k = (e.get("key") or _dedup_key(e.get("content", ""), e.get("type", "")),
             e.get("type", ""))
        prev = latest.get(k)
        if prev is None or _parse_iso(e.get("timestamp", "")) > _parse_iso(prev.get("timestamp", "")):
            latest[k] = e
    # Restore original order: newest among each key
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for e in reversed(entries):
        k = (e.get("key") or _dedup_key(e.get("content", ""), e.get("type", "")),
             e.get("type", ""))
        if k in seen:
            continue
        out.append(latest[k])
        seen.add(k)
    out.reverse()
    return out


def score_relevance(entry: dict[str, Any], query: str, tags: list[str]) -> float:
    """
    Simple keyword + tag relevance score in [0, 1].
    Empty query returns a constant 0.5 so confidence alone orders results.
    """
    if not query and not tags:
        return 0.5

    content = entry.get("content", "").lower()
    entry_tags = {t.lower() for t in entry.get("tags", [])}
    entry_type = entry.get("type", "").lower()

    score = 0.0
    if query:
        q = query.lower().strip()
        terms = [t for t in re.split(r"\s+", q) if t]
        if terms:
            hits = sum(1 for t in terms if t in content or t in entry_tags or t == entry_type)
            score += hits / len(terms)

    if tags:
        want = {t.lower() for t in tags}
        if want:
            overlap = len(want & entry_tags) / len(want)
            score += overlap

    # Normalize into [0, 1]
    if query and tags:
        score /= 2.0
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Search (injection filter)
# ---------------------------------------------------------------------------

def search(
    *,
    query: str = "",
    tags: list[str] | None = None,
    types: list[str] | None = None,
    slug: str | None = None,
    cross_project: bool | None = None,
    max_results: int | None = None,
    token_budget: int | None = None,
    include_stale: bool = False,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Return a ranked, filtered, token-capped list of learnings.

    The caller is expected to inject this into a command preamble or skill
    context. Results are already sanitized; deprecated and stale-below-
    threshold entries are excluded by default.
    """
    cfg = config or load_config()
    half_life = float(cfg.get("half_life_days", DEFAULT_HALF_LIFE_DAYS))
    threshold = float(cfg.get("deprecate_threshold", DEFAULT_DEPRECATE_THRESHOLD))
    stale_days = float(cfg.get("stale_days", DEFAULT_STALE_DAYS))
    budget = int(token_budget if token_budget is not None else cfg.get("token_budget", DEFAULT_TOKEN_BUDGET))
    cap = int(max_results if max_results is not None else cfg.get("max_results", DEFAULT_MAX_RESULTS))
    allow_cross = bool(cross_project if cross_project is not None else cfg.get("cross_project_search", False))

    tags = tags or []
    types = types or []

    slugs: list[str] = []
    if slug:
        slugs.append(slug)
    else:
        slugs.append(detect_project_slug())
    if allow_cross:
        for s in list_project_slugs():
            if s not in slugs:
                slugs.append(s)

    now = time.time()
    pool: list[dict[str, Any]] = []
    for s in slugs:
        pool.extend(load_all(s))

    if types:
        wanted = set(types)
        pool = [e for e in pool if e.get("type") in wanted]

    pool = dedup_latest(pool)

    scored: list[tuple[float, dict[str, Any]]] = []
    for e in pool:
        eff = effective_confidence(e, half_life_days=half_life, now=now)
        if eff < threshold:
            continue
        if not include_stale and is_stale(e, stale_days=stale_days, now=now):
            continue
        rel = score_relevance(e, query, tags)
        # Rank: effective confidence (0-10) weighted with relevance (0-1)
        rank = eff * (0.5 + rel)
        scored.append((rank, e))

    scored.sort(key=lambda row: row[0], reverse=True)

    # Apply token budget (character approximation: 4 chars ~ 1 token)
    out: list[dict[str, Any]] = []
    char_budget = budget * 4
    used = 0
    for _, e in scored:
        snippet_len = len(e.get("content", "")) + 80  # overhead for tags/type
        if used + snippet_len > char_budget:
            break
        out.append(e)
        used += snippet_len
        if len(out) >= cap:
            break

    return out


# ---------------------------------------------------------------------------
# Update helpers (verify / contradict / deprecate)
# ---------------------------------------------------------------------------

def _rewrite_jsonl(slug: str, entries: list[dict[str, Any]]) -> None:
    """Rewrite a project's JSONL atomically."""
    path = project_jsonl(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, sort_keys=True) + "\n")
    tmp.replace(path)


def update_entry_by_id(
    entry_id: str,
    *,
    slug: str | None = None,
    verify: bool = False,
    contradict: bool = False,
    deprecate: bool = False,
    confidence: int | None = None,
) -> bool:
    """Mutate a single entry by id. Returns True if found."""
    target_slug = slug or detect_project_slug()
    entries = load_all(target_slug)
    found = False
    for e in entries:
        if e.get("id") == entry_id:
            found = True
            if verify:
                e["uses"] = int(e.get("uses", 0)) + 1
                e["last_verified"] = _utc_now_iso()
            if contradict:
                e["contradictions"] = int(e.get("contradictions", 0)) + 1
            if deprecate:
                e["deprecated"] = True
            if confidence is not None:
                e["confidence"] = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, int(confidence)))
            break
    if found:
        _rewrite_jsonl(target_slug, entries)
    return found
