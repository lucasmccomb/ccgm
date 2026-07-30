#!/usr/bin/env python3
"""merge_fragments.py -- orrery merge stage (plan section 3.1 stage 4 / Epic 3).

Turns per-pack fragments (fragments/{pack}.json) into a screened, merged
model.json. Stdlib only; deterministic given identical inputs (pin
ORRERY_GENERATED_AT to make the meta timestamp reproducible).

Usage (build mode):
  merge_fragments.py --fragments-dir DIR --packs p1,p2,... \
      --census census.json --anchor anchor.json --out model.json

Update mode (plan section 3.1 / Epic 5):
  ... --patch [--state state.json] [--diff diff.json]
  --patch loads the BASELINE model from --out (which must exist), replaces
  every element/relation contributed by a re-run pack (--packs is the re-run
  list), deletes elements named in the diff report's orphaned_elements[],
  keeps the rest, and refreshes meta from the new anchor/census. Old
  fragments are never read back (section 3.1: update patches the baseline
  MODEL, never fragments).

Contract highlights (plan Epic 3):
  * --packs is REQUIRED and is the run's whitelist: a file in fragments/
    that no listed pack produced is IGNORED and reported, never merged.
  * Per-fragment schema validation: an invalid fragment is quarantined
    whole (reported); the run continues.
  * Secret screening: SECRET_PATTERNS over every element title/summary/
    description, relation summary, and open_questions string. A match
    QUARANTINES the element (or relation / question) -- recorded and
    surfaced as "N elements withheld: secret-shaped content" -- never
    silently stripped. The matched VALUE is never written to the report.
  * Injection neutralization: INJECTION_PATTERNS matches are wrapped in
    [neutralized]...[/neutralized], then the field is clamped to its
    schema max so a wrapped string cannot fail model validation.
  * Id namespacing: an area pack (pack id "area-{id}") may only define
    element ids prefixed "{id}__"; violations are withheld + reported.
  * Cross-pack same-id collision with disjoint files[] is an ERROR
    (flagged, both withheld, never fused). Same-id with overlapping files,
    or the reserved cross-cutting ids (system, users), merge normally:
    longest description wins, files/tags union, source_packs[] provenance.
  * Relations are deduped; dangling endpoints dropped + reported.
  * Ancestor-descendant relations (one endpoint on the other's parent
    chain, or equal endpoints) are dropped + reported: containment is
    already expressed by nesting, and LikeC4 rejects such edges
    ("Invalid parent-child relationship").

Exit codes: 0 = merged (the report carries all screening findings);
2 = usage / unreadable input.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

ELEMENT_KINDS = [
    "system", "actor", "container", "component", "datastore", "queue",
    "external_service", "cloud_provider", "package", "tool", "file",
]
RELATION_KINDS = [
    "uses", "calls", "reads", "writes", "deploys_to", "depends_on", "triggers",
]
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Bare ids designed to be emitted by more than one wave-0 pack (plan
# section 3.3): these merge normally even with disjoint files.
RESERVED_IDS = {"system", "users"}

MAX_TITLE = 60
MAX_SUMMARY = 200
MAX_DESCRIPTION = 2000

# ---------------------------------------------------------------------------
# SECRET_PATTERNS -- adapted from ccgm's tests/test-no-personal-data.sh
# Class-2 secret/PII shapes (sk-/ghp_/gho_/github_pat_/re_/AKIA/PEM/email),
# plus the credentialed-URL userinfo shape from the security C6 rule.
# Copied + adapted per the modules-are-self-contained convention (no
# cross-module imports). Adaptation: a left boundary (?<![A-Za-z0-9]) is
# added to the token classes so prose containing "task-management-..." or
# "structure_re_..." substrings does not falsely quarantine an element --
# a false positive here silently deletes a legitimate map node.
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    ("openai-anthropic-key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"(?<![A-Za-z0-9])gh[po]_[A-Za-z0-9]{20,}")),
    ("github-fine-grained-token", re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}")),
    ("resend-key", re.compile(r"(?<![A-Za-z0-9])re_[A-Za-z0-9]{20,}")),
    ("aws-access-key-id", re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}")),
    ("private-key-pem", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("credentialed-url", re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@")),
    ("email-address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
]

# The full pattern class runs over every prose string that reaches the
# emitter (PR #910 stage-2 finding 1: `technology` sailed to the published
# artifact unscreened).
SCREENED_PROSE_FIELDS = ("title", "summary", "description", "technology")

# external_url is guaranteed to hold a URL, so the email pattern would
# false-positive constantly; it gets the credentialed-URL pattern plus a
# bare-userinfo check instead (any user@ before the first path separator is
# suspicious in a docs link, with or without a token after a colon).
_CREDENTIALED_URL_RE = dict(SECRET_PATTERNS)["credentialed-url"]
_URL_USERINFO_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/?#\s]*@")


def screen_external_url(url):
    """Return a pattern name when an external_url carries credentials or any
    userinfo, else None. Normal https URLs pass untouched."""
    if not isinstance(url, str):
        return None
    if _CREDENTIALED_URL_RE.search(url):
        return "credentialed-url"
    if _URL_USERINFO_RE.search(url):
        return "url-userinfo"
    return None

# ---------------------------------------------------------------------------
# INJECTION_PATTERNS -- adapted from
# modules/self-improving/lib/learnings_store.py (security R3). Copied +
# attributed per the modules-are-self-contained convention (no cross-module
# imports). Matches are wrapped [neutralized]...[/neutralized] so the text
# stays readable while downstream injection becomes inert.
# ---------------------------------------------------------------------------
INJECTION_PATTERNS = [
    re.compile(r"(?im)^\s*system\s*:"),
    re.compile(r"(?im)^\s*assistant\s*:"),
    re.compile(r"(?im)^\s*user\s*:"),
    re.compile(r"(?im)^\s*ignore (?:all\s+|previous\s+|prior\s+)+(?:instructions|prompts)"),
    re.compile(r"(?im)^\s*you are (?:now|an?)\b"),
    re.compile(r"(?im)^\s*disregard .* (?:rules|instructions|guidelines)"),
    re.compile(r"(?im)<\s*/?\s*(?:system|instructions|prompt)\s*>"),
    re.compile(r"(?im)```\s*system"),
]


def screen_secret(text):
    """Return the name of the first SECRET_PATTERNS match in text, or None."""
    if not isinstance(text, str):
        return None
    for name, rx in SECRET_PATTERNS:
        if rx.search(text):
            return name
    return None


def _wrap_injections(text):
    changed = False
    for rx in INJECTION_PATTERNS:
        text, n = rx.subn(lambda m: "[neutralized]" + m.group(0) + "[/neutralized]", text)
        if n:
            changed = True
    return text, changed


def neutralize(text, max_len=None):
    """Wrap INJECTION_PATTERNS matches; keep the result within max_len
    (the schema max) WITHOUT ever cutting a marker.

    A naive truncate-after-wrap can slice through the closing
    [/neutralized] (PR #910 stage-2 finding 2), leaving a dangling open
    marker. Instead the SOURCE text is shortened and re-wrapped until the
    wrapped result fits, so both markers always survive intact. If even an
    empty source cannot fit (max_len smaller than a marker pair -- never
    true for the schema caps, all >= 60), the field collapses to "".
    Returns (text, changed).
    """
    out, changed = _wrap_injections(text)
    if max_len is None or len(out) <= max_len:
        return out, changed
    src = text
    while src and len(out) > max_len:
        overshoot = len(out) - max_len
        src = src[:len(src) - overshoot]
        out, _ = _wrap_injections(src)
    if len(out) > max_len:
        out = ""
    return out, True


# ---------------------------------------------------------------------------
# Fragment validation (fragment.schema.json semantics, stdlib -- the schema
# file in skills/orrery/references/ is the contract; this enforces it
# without a jsonschema dependency).
# ---------------------------------------------------------------------------

def _check_str(errs, where, obj, field, max_len=None, required=False):
    val = obj.get(field)
    if val is None:
        if required:
            errs.append("%s: missing required field %s" % (where, field))
        return
    if not isinstance(val, str):
        errs.append("%s: %s is not a string" % (where, field))
        return
    if max_len is not None and len(val) > max_len:
        errs.append("%s: %s exceeds maxLength %d" % (where, field, max_len))


def validate_fragment(frag, pack):
    """Return a list of error strings; empty list == schema-valid."""
    errs = []
    if not isinstance(frag, dict):
        return ["fragment is not a JSON object"]
    if frag.get("pack") != pack:
        errs.append("pack field %r does not match the pack id %r" % (frag.get("pack"), pack))
    elements = frag.get("elements")
    if not isinstance(elements, list):
        errs.append("elements: required array missing or not an array")
        return errs
    for i, el in enumerate(elements):
        where = "elements[%d]" % i
        if not isinstance(el, dict):
            errs.append("%s: not an object" % where)
            continue
        eid = el.get("id")
        if not isinstance(eid, str) or not ID_RE.match(eid):
            errs.append("%s: id %r does not match ^[a-z][a-z0-9_]*$" % (where, eid))
        if el.get("kind") not in ELEMENT_KINDS:
            errs.append("%s: kind %r not in the kind enum" % (where, el.get("kind")))
        _check_str(errs, where, el, "title", MAX_TITLE, required=True)
        _check_str(errs, where, el, "summary", MAX_SUMMARY, required=True)
        _check_str(errs, where, el, "description", MAX_DESCRIPTION)
        _check_str(errs, where, el, "technology")
        parent = el.get("parent")
        if parent is not None and not isinstance(parent, str):
            errs.append("%s: parent is neither string nor null" % where)
        ext = el.get("external_url")
        if ext is not None and not isinstance(ext, str):
            errs.append("%s: external_url is neither string nor null" % where)
        tags = el.get("tags")
        if tags is not None and (
            not isinstance(tags, list) or any(not isinstance(t, str) for t in tags)
        ):
            errs.append("%s: tags is not an array of strings" % where)
        files = el.get("files")
        if files is not None:
            if not isinstance(files, list):
                errs.append("%s: files is not an array" % where)
            else:
                for j, f in enumerate(files):
                    fwhere = "%s.files[%d]" % (where, j)
                    if not isinstance(f, dict) or not isinstance(f.get("path"), str):
                        errs.append("%s: missing required string path" % fwhere)
                        continue
                    if f["path"].startswith("/"):
                        errs.append("%s: path must not start with /" % fwhere)
                    for lf in ("start_line", "end_line"):
                        lv = f.get(lf)
                        if lv is not None and (not isinstance(lv, int) or isinstance(lv, bool) or lv < 1):
                            errs.append("%s: %s is not an integer >= 1" % (fwhere, lf))
    relations = frag.get("relations")
    if relations is not None:
        if not isinstance(relations, list):
            errs.append("relations: not an array")
        else:
            for i, rel in enumerate(relations):
                where = "relations[%d]" % i
                if not isinstance(rel, dict):
                    errs.append("%s: not an object" % where)
                    continue
                for req in ("from", "to"):
                    if not isinstance(rel.get(req), str):
                        errs.append("%s: missing required string %s" % (where, req))
                _check_str(errs, where, rel, "summary", MAX_SUMMARY, required=True)
                rkind = rel.get("kind")
                if rkind is not None and rkind not in RELATION_KINDS:
                    errs.append("%s: kind %r not in the relation kind enum" % (where, rkind))
    oq = frag.get("open_questions")
    if oq is not None and (
        not isinstance(oq, list) or any(not isinstance(q, str) for q in oq)
    ):
        errs.append("open_questions: not an array of strings")
    return errs


# ---------------------------------------------------------------------------
# Screening + neutralization of one validated fragment
# ---------------------------------------------------------------------------

def process_pack(pack, frag, report, quarantined_parents=None):
    """Screen and neutralize one schema-valid fragment.

    Returns (elements, relations, open_questions); every element/relation
    carries _packs (provenance list) for the merge step. A secret match in
    ANY screened field withholds the whole element; its parent is recorded
    in quarantined_parents so surviving children can be reparented instead
    of cascade-dropped (stage-2 finding 4).
    """
    if quarantined_parents is None:
        quarantined_parents = {}
    area_prefix = None
    if pack.startswith("area-"):
        area_prefix = pack[len("area-"):] + "__"

    kept_elements = []
    for el in frag.get("elements", []):
        hit = None
        for field in SCREENED_PROSE_FIELDS:
            pat = screen_secret(el.get(field))
            if pat:
                hit = {"pack": pack, "id": el.get("id"), "field": field, "pattern": pat}
                break
        if hit is None:
            for tag in el.get("tags") or []:
                pat = screen_secret(tag)
                if pat:
                    hit = {"pack": pack, "id": el.get("id"), "field": "tags", "pattern": pat}
                    break
        if hit is None:
            pat = screen_external_url(el.get("external_url"))
            if pat:
                hit = {"pack": pack, "id": el.get("id"), "field": "external_url", "pattern": pat}
        if hit:
            report["withheld_secret_elements"].append(hit)
            quarantined_parents.setdefault(el.get("id"), el.get("parent"))
            continue
        if area_prefix and not el["id"].startswith(area_prefix):
            report["namespace_violations"].append(
                {"pack": pack, "id": el["id"], "expected_prefix": area_prefix}
            )
            continue
        el = dict(el)
        for field, cap in (("title", MAX_TITLE), ("summary", MAX_SUMMARY), ("description", MAX_DESCRIPTION)):
            if isinstance(el.get(field), str):
                el[field], changed = neutralize(el[field], cap)
                if changed:
                    report["neutralized"].append({"pack": pack, "id": el["id"], "field": field})
        el["_packs"] = [pack]
        kept_elements.append(el)

    kept_relations = []
    for rel in frag.get("relations", []) or []:
        pat = screen_secret(rel.get("summary"))
        if pat:
            report["withheld_secret_relations"].append(
                {"pack": pack, "from": rel.get("from"), "to": rel.get("to"), "pattern": pat}
            )
            continue
        rel = dict(rel)
        if isinstance(rel.get("summary"), str):
            rel["summary"], changed = neutralize(rel["summary"], MAX_SUMMARY)
            if changed:
                report["neutralized"].append(
                    {"pack": pack, "relation": "%s -> %s" % (rel.get("from"), rel.get("to")), "field": "summary"}
                )
        rel["_packs"] = [pack]
        kept_relations.append(rel)

    kept_questions = []
    for q in frag.get("open_questions", []) or []:
        pat = screen_secret(q)
        if pat:
            report["withheld_open_questions"] += 1
            continue
        q2, changed = neutralize(q)
        if changed:
            report["neutralized"].append({"pack": pack, "field": "open_questions"})
        kept_questions.append(q2)

    return kept_elements, kept_relations, kept_questions


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

ELEMENT_KEY_ORDER = [
    "id", "parent", "kind", "title", "summary", "description", "technology",
    "files", "external_url", "tags", "source_packs",
]


def _ordered_element(el):
    return {k: el[k] for k in ELEMENT_KEY_ORDER if k in el and el[k] is not None}


def merge_element_group(eid, items, report):
    """Merge same-id items; return the merged element or None on collision."""
    packs = sorted({p for it in items for p in it["_packs"]})
    if len(packs) > 1 and eid not in RESERVED_IDS:
        # Cross-pack same-id: fuse ONLY when every pack pair shares at least
        # one evidence path. Disjoint files -> collision error, never fused.
        per_pack_paths = {}
        for it in items:
            paths = {f.get("path") for f in (it.get("files") or []) if isinstance(f, dict)}
            for p in it["_packs"]:
                per_pack_paths.setdefault(p, set()).update(paths)
        plist = [per_pack_paths[p] for p in sorted(per_pack_paths)]
        for i in range(len(plist)):
            for j in range(i + 1, len(plist)):
                if not (plist[i] & plist[j]):
                    report["collisions"].append({"id": eid, "packs": packs})
                    return None
    def desc_len(it):
        return len(it.get("description") or "")
    items_sorted = sorted(items, key=lambda it: (-desc_len(it), sorted(it["_packs"])))
    out = {"id": eid}
    for field in ("parent", "kind", "title", "summary", "description", "technology", "external_url"):
        for it in items_sorted:
            val = it.get(field)
            if val not in (None, ""):
                out[field] = val
                break
    seen = set()
    files = []
    for it in items_sorted:
        for f in it.get("files") or []:
            key = (f.get("path"), f.get("start_line"), f.get("end_line"))
            if key in seen:
                continue
            seen.add(key)
            files.append(dict(f))
    files.sort(key=lambda f: (f.get("path") or "", f.get("start_line") or 0, f.get("end_line") or 0))
    if files:
        out["files"] = files
    tags = sorted({t for it in items for t in (it.get("tags") or [])})
    if tags:
        out["tags"] = tags
    out["source_packs"] = packs
    return out


def merge_elements(pool, report):
    by_id = {}
    for el in pool:
        by_id.setdefault(el["id"], []).append(el)
    merged = []
    for eid in sorted(by_id):
        el = merge_element_group(eid, by_id[eid], report)
        if el is not None:
            merged.append(_ordered_element(el))
    return merged


def reparent_quarantine_orphans(elements, quarantined_parents, report):
    """Reparent children of a secret-quarantined element instead of letting
    the cascade delete the whole subtree (stage-2 finding 4).

    A child whose parent was withheld by secret screening moves to the
    quarantined element's own parent (walking a chain of quarantined
    ancestors to the nearest survivor), falling back to the system root, or
    to top level when no system element exists. The offending element stays
    fully withheld; only its evidence-clean descendants survive. Every move
    is reported. Non-quarantine orphans (never-defined or collision-dropped
    parents) still go through cascade_parent_orphans afterwards.
    """
    ids = {e["id"] for e in elements}
    has_system = "system" in ids
    out = []
    for e in elements:
        parent = e.get("parent")
        if parent is None or parent in ids or parent not in quarantined_parents:
            out.append(e)
            continue
        candidate = quarantined_parents.get(parent)
        seen = {parent}
        while candidate is not None and candidate not in ids:
            if candidate in quarantined_parents and candidate not in seen:
                seen.add(candidate)
                candidate = quarantined_parents[candidate]
            else:
                candidate = None
        if candidate is None and has_system and e["id"] != "system":
            candidate = "system"
        moved = dict(e)
        moved["parent"] = candidate
        report["reparented"].append({"id": e["id"], "from": parent, "to": candidate})
        out.append(_ordered_element(moved))
    return out


def cascade_parent_orphans(elements, report):
    """Drop elements whose parent id is absent (e.g. quarantined), repeatedly.

    Keeping them would guarantee a validate_map.py check-6 failure; dropping
    is deterministic and reported, so the fix loop / report can act on it.
    """
    kept = list(elements)
    while True:
        ids = {e["id"] for e in kept}
        nxt = []
        dropped_any = False
        for e in kept:
            parent = e.get("parent")
            if parent is not None and parent not in ids:
                report["dropped_parent_orphans"].append({"id": e["id"], "parent": parent})
                dropped_any = True
            else:
                nxt.append(e)
        kept = nxt
        if not dropped_any:
            return kept


def merge_relations(pool, valid_ids, report):
    by_key = {}
    for rel in pool:
        key = (rel.get("from"), rel.get("to"), rel.get("kind"), rel.get("summary"))
        entry = by_key.setdefault(key, set())
        entry.update(rel["_packs"])
    out = []
    for key in sorted(by_key, key=lambda k: tuple(x or "" for x in k)):
        frm, to, kind, summary = key
        if frm not in valid_ids or to not in valid_ids:
            report["dropped_relations"].append(
                {"from": frm, "to": to, "reason": "dangling endpoint"}
            )
            continue
        rel = {"from": frm, "to": to}
        if kind is not None:
            rel["kind"] = kind
        rel["summary"] = summary
        rel["source_packs"] = sorted(by_key[key])
        out.append(rel)
    return out


def drop_ancestor_relations(relations, elements, report):
    """Drop relations where one endpoint is an ancestor of the other (via
    the elements' parent chains), or the endpoints are equal (#915).

    Containment is already expressed by nesting, so the relation is
    semantically redundant -- and LikeC4 rejects it outright ("Invalid
    parent-child relationship"), which failed validate on the first
    full-scale run (16 such relations on a 551-element model). The walk
    carries a visited set so a defensive parent cycle (validate_map.py
    check 6 catches those later) can never loop it forever.
    """
    parent = {e["id"]: e.get("parent") for e in elements}

    def is_ancestor(anc, node):
        seen = set()
        cur = parent.get(node)
        while cur is not None and cur not in seen:
            if cur == anc:
                return True
            seen.add(cur)
            cur = parent.get(cur)
        return False

    out = []
    for rel in relations:
        frm, to = rel["from"], rel["to"]
        if frm == to or is_ancestor(frm, to) or is_ancestor(to, frm):
            report["dropped_ancestor_relations"].append(
                {"from": frm, "to": to, "reason": "implied by nesting"}
            )
            continue
        out.append(rel)
    return out


# ---------------------------------------------------------------------------
# Meta (anchor + census -> model.schema.json meta)
# ---------------------------------------------------------------------------

_SCHEME_USERINFO_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)([^/@]+)@")


def strip_credentials(url):
    """Remove user[:token]@ userinfo from a scheme URL (security C6).

    anchor_repo.sh already strips before emitting anchor.json; this is
    defense in depth because model.schema.json says remote_url is stored
    ONLY after credential stripping. For scp-like ssh remotes
    (git@host:path) the bare user carries no secret and is kept -- a
    user:token@ userinfo is stripped there too.
    """
    if not url:
        return None
    m = _SCHEME_USERINFO_RE.match(url)
    if m:
        return m.group(1) + url[m.end():]
    m = re.match(r"^([^/@:]+):([^/@]+)@(.+)$", url)
    if m:
        return m.group(3)
    return url


def github_owner_repo(url):
    """Normalized (owner, repo) when the remote host is exactly github.com.

    Handles https://, ssh://, and scp-like git@host:path forms (ssh->https
    normalization, plan section 3.4). Returns None for any other host,
    an unparseable URL, or None.
    """
    if not url:
        return None
    url = strip_credentials(url)
    host = path = None
    m = re.match(r"^(?:git\+)?ssh://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$", url)
    if m:
        host, path = m.group(1), m.group(2)
    if host is None:
        m = re.match(r"^https?://([^/:]+)(?::\d+)?/(.+)$", url)
        if m:
            host, path = m.group(1), m.group(2)
    if host is None:
        m = re.match(r"^(?:[^@/:]+@)?([^/:]+):(.+)$", url)
        if m and "/" not in m.group(1):
            host, path = m.group(1), m.group(2)
    if host is None or host.lower() != "github.com":
        return None
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return owner, repo


def build_meta(anchor, census):
    remote_url = None
    if not anchor.get("no_remote"):
        remote_url = strip_credentials(anchor.get("remote_url"))
    repo_path = anchor.get("repo_path") or ""
    repo_title = os.path.basename(repo_path.rstrip("/")) or anchor.get("slug", "")
    source_links = "github" if github_owner_repo(remote_url) else "none (non-GitHub remote)"
    generated_at = os.environ.get("ORRERY_GENERATED_AT") or (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    areas = []
    for area in census.get("areas", []) or []:
        areas.append({
            "id": area.get("id"),
            "title": area.get("title") or area.get("id"),
            "root_paths": area.get("root_paths", []),
        })
    return {
        "slug": anchor.get("slug"),
        "repo_title": repo_title,
        "remote_url": remote_url,
        "default_ref": anchor.get("default_ref"),
        "anchor_sha": anchor.get("anchor_sha"),
        "visibility": anchor.get("visibility", "unknown"),
        "generated_at": generated_at,
        "source_links": source_links,
        "areas": areas,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _load_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise SystemExit("merge_fragments.py: cannot read %s %s: %s" % (what, path, exc))


def _atomic_write(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".merge-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def new_report(mode, packs):
    return {
        "mode": mode,
        "packs": packs,
        "loaded_packs": [],
        "missing_packs": [],
        "ignored_files": [],
        "quarantined_fragments": [],
        "withheld_secret_elements": [],
        "withheld_secret_relations": [],
        "withheld_open_questions": 0,
        "namespace_violations": [],
        "collisions": [],
        "neutralized": [],
        "dropped_relations": [],
        "dropped_ancestor_relations": [],
        "reparented": [],
        "dropped_parent_orphans": [],
        "open_questions": {},
        "counts": {},
    }


def run(argv=None):
    ap = argparse.ArgumentParser(prog="merge_fragments.py")
    ap.add_argument("--fragments-dir", required=True)
    ap.add_argument("--packs", required=True,
                    help="comma-separated pack ids: the run whitelist")
    ap.add_argument("--census", required=True)
    ap.add_argument("--anchor", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--patch", action="store_true")
    ap.add_argument("--state", default=None)
    ap.add_argument("--diff", default=None)
    args = ap.parse_args(argv)

    packs = [p for p in (s.strip() for s in args.packs.split(",")) if p]
    if not packs:
        print("merge_fragments.py: --packs must list at least one pack", file=sys.stderr)
        return 2
    if not os.path.isdir(args.fragments_dir):
        print("merge_fragments.py: fragments dir not found: %s" % args.fragments_dir, file=sys.stderr)
        return 2

    anchor = _load_json(args.anchor, "anchor")
    census = _load_json(args.census, "census")

    mode = "patch" if args.patch else "build"
    report = new_report(mode, packs)

    # The whitelist (adrev2-008): every *.json in fragments/ that no listed
    # pack produced is ignored + reported, never merged.
    listed = set(packs)
    for name in sorted(os.listdir(args.fragments_dir)):
        if not name.endswith(".json"):
            continue
        if name[:-len(".json")] not in listed:
            report["ignored_files"].append(name)

    element_pool = []
    relation_pool = []
    quarantined_parents = {}
    for pack in packs:
        frag_path = os.path.join(args.fragments_dir, pack + ".json")
        if not os.path.isfile(frag_path):
            report["missing_packs"].append(pack)
            continue
        try:
            with open(frag_path, "r", encoding="utf-8") as fh:
                frag = json.load(fh)
        except ValueError as exc:
            report["quarantined_fragments"].append(
                {"pack": pack, "errors": ["unparseable JSON: %s" % exc]}
            )
            continue
        errs = validate_fragment(frag, pack)
        if errs:
            report["quarantined_fragments"].append({"pack": pack, "errors": errs})
            continue
        report["loaded_packs"].append(pack)
        els, rels, questions = process_pack(pack, frag, report, quarantined_parents)
        element_pool.extend(els)
        relation_pool.extend(rels)
        if questions:
            report["open_questions"][pack] = questions

    if args.patch:
        baseline = _load_json(args.out, "baseline model (--patch mode)")
        diff = _load_json(args.diff, "diff") if args.diff else {}
        state = _load_json(args.state, "state") if args.state else None
        # A pack replaces its baseline content ONLY when it actually produced
        # a valid fragment this run (stage-2 finding 3). A re-run pack whose
        # fragment is missing or quarantined KEEPS its baseline elements --
        # patch mode must never silently shrink the map because one scout
        # re-investigation failed.
        rerun_loaded = set(report["loaded_packs"])
        rerun_failed = sorted(set(packs) - rerun_loaded)
        orphaned = set(diff.get("orphaned_elements", []) or [])
        patch_info = {
            "rerun_packs": sorted(set(packs)),
            "baseline_elements_replaced": [],
            "orphaned_deleted": [],
            "reinvestigation_failed_retained": rerun_failed,
            "baseline_anchor_sha": (state or {}).get("anchor_sha"),
        }
        for el in baseline.get("elements", []) or []:
            src = set(el.get("source_packs") or [])
            if src & rerun_loaded:
                patch_info["baseline_elements_replaced"].append(el["id"])
                continue
            if el["id"] in orphaned:
                patch_info["orphaned_deleted"].append(el["id"])
                continue
            kept = dict(el)
            kept["_packs"] = sorted(src) or ["baseline"]
            element_pool.append(kept)
        for rel in baseline.get("relations", []) or []:
            src = set(rel.get("source_packs") or [])
            if src & rerun_loaded:
                continue
            kept = dict(rel)
            kept["_packs"] = sorted(src) or ["baseline"]
            relation_pool.append(kept)
        report["patch"] = patch_info

    elements = merge_elements(element_pool, report)
    elements = reparent_quarantine_orphans(elements, quarantined_parents, report)
    elements = cascade_parent_orphans(elements, report)
    valid_ids = {e["id"] for e in elements}
    relations = merge_relations(relation_pool, valid_ids, report)
    # After dangling-drop, before the model is written; both modes (build
    # and --patch) flow through here, so the patched model gets the same
    # screen (#915).
    relations = drop_ancestor_relations(relations, elements, report)

    model = {
        "meta": build_meta(anchor, census),
        "elements": elements,
        "relations": relations,
    }
    report["counts"] = {"elements": len(elements), "relations": len(relations)}

    _atomic_write(args.out, json.dumps(model, indent=2) + "\n")
    report_path = os.path.join(os.path.dirname(os.path.abspath(args.out)), "merge-report.json")
    _atomic_write(report_path, json.dumps(report, indent=2) + "\n")

    print("merge_fragments.py: model written: %s (%d elements, %d relations)"
          % (args.out, len(elements), len(relations)))
    # Frozen report phrase (plan Epic 3): always printed, even at zero.
    print("merge_fragments.py: %d elements withheld: secret-shaped content"
          % len(report["withheld_secret_elements"]))
    if report["ignored_files"]:
        print("merge_fragments.py: ignored %d fragment file(s) not produced by a listed pack: %s"
              % (len(report["ignored_files"]), ", ".join(report["ignored_files"])))
    if report["missing_packs"]:
        print("merge_fragments.py: missing fragment for listed pack(s): %s"
              % ", ".join(report["missing_packs"]))
    if report["quarantined_fragments"]:
        print("merge_fragments.py: quarantined %d invalid fragment(s): %s"
              % (len(report["quarantined_fragments"]),
                 ", ".join(q["pack"] for q in report["quarantined_fragments"])))
    if report["namespace_violations"]:
        print("merge_fragments.py: withheld %d element(s): id outside the pack namespace"
              % len(report["namespace_violations"]))
    if report["collisions"]:
        print("merge_fragments.py: %d cross-pack id collision(s) flagged (withheld, never fused): %s"
              % (len(report["collisions"]),
                 ", ".join(c["id"] for c in report["collisions"])))
    if report["dropped_relations"]:
        print("merge_fragments.py: dropped %d dangling relation(s)"
              % len(report["dropped_relations"]))
    if report["dropped_ancestor_relations"]:
        print("merge_fragments.py: %d ancestor relation(s) dropped: implied by nesting"
              % len(report["dropped_ancestor_relations"]))
    if report["reparented"]:
        print("merge_fragments.py: reparented %d child(ren) of withheld element(s): %s"
              % (len(report["reparented"]),
                 ", ".join(r["id"] for r in report["reparented"])))
    if report["dropped_parent_orphans"]:
        print("merge_fragments.py: dropped %d element(s) whose parent is not in the model"
              % len(report["dropped_parent_orphans"]))
    for pack in (report.get("patch") or {}).get("reinvestigation_failed_retained", []):
        print("merge_fragments.py: pack %s: re-investigation failed, baseline retained" % pack)
    print("merge_fragments.py: report written: %s" % report_path)
    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
