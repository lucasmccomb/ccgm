#!/usr/bin/env python3
"""validate_map.py -- orrery hard validation gate (plan section 3.7 / Epic 3).

Usage:
  validate_map.py --model model.json --model-dir <out>/model \\
      --repo <repo-or-worktree> --anchor-sha <40-hex sha>

The seven ordered checks (plan Epic 3):
  1. model.json is model.schema.json-valid (stdlib semantic validation).
  2. Every element has non-empty files[] OR external_url -- EXCEPT
     kind: actor, which is exempt (a persona is a modelling primitive,
     not a code claim) and must instead carry a non-empty description.
  3. Every files[].path passes the traversal rules (no leading /, no ..
     segment, no NUL/control characters) AND exists at the anchor:
     `git -C <repo> cat-file -e <anchor_sha>:<path>` -- git-native ONLY,
     never a raw filesystem join (security C4: cannot escape the repo by
     construction).
  4. Line ranges sane (start_line <= end_line; no end without start).
  5. Relation endpoints exist.
  6. Parent refs exist and are acyclic.
  7. `likec4.sh validate --json <model-dir>` -- its structured errors are
     merged. Checks 1-6 are cheap and structural; when any of them fails
     the emitted DSL is already condemned and re-running the toolchain
     would only duplicate noise, so check 7 runs once 1-6 are green (it is
     the final gate, and `validate` -- never `build` -- is the only gate:
     the build exit code is meaningless).

Any failure: exit 1 and errors.json written next to --model as
[{"check", "element_id", "path", "message"}]. Success: exit 0 and any
stale errors.json is removed. Exit 2 = usage / unreadable input.
"""

import argparse
import json
import os
import re
import subprocess
import sys

ELEMENT_KINDS = [
    "system", "actor", "container", "component", "datastore", "queue",
    "external_service", "cloud_provider", "package", "tool", "file",
]
RELATION_KINDS = [
    "uses", "calls", "reads", "writes", "deploys_to", "depends_on", "triggers",
]
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VISIBILITY = ["public", "private", "unknown"]
SOURCE_LINKS = ["github", "none (non-GitHub remote)"]

MAX_TITLE = 60
MAX_SUMMARY = 200
MAX_DESCRIPTION = 2000


def err(check, message, element_id=None, path=None):
    return {"check": check, "element_id": element_id, "path": path, "message": message}


# ---------------------------------------------------------------------------
# Check 1: model.schema.json semantics (stdlib -- the schema file in
# skills/orrery/references/ is the contract; enforced without a jsonschema
# dependency).
# ---------------------------------------------------------------------------

def check_schema(model):
    errors = []

    def add(msg, element_id=None, path=None):
        errors.append(err("schema", msg, element_id, path))

    if not isinstance(model, dict):
        add("model is not a JSON object")
        return errors
    meta = model.get("meta")
    if not isinstance(meta, dict):
        add("meta: required object missing")
    else:
        for req in ("slug", "repo_title", "remote_url", "default_ref", "anchor_sha",
                    "visibility", "generated_at", "source_links", "areas"):
            if req not in meta:
                add("meta: missing required field %s" % req)
        slug = meta.get("slug")
        if isinstance(slug, str) and not SLUG_RE.match(slug):
            add("meta.slug %r does not match ^[a-z0-9][a-z0-9_-]*$" % slug)
        sha = meta.get("anchor_sha")
        if isinstance(sha, str) and not SHA_RE.match(sha):
            add("meta.anchor_sha %r is not a 40-hex sha" % sha)
        if "visibility" in meta and meta.get("visibility") not in VISIBILITY:
            add("meta.visibility %r not in %s" % (meta.get("visibility"), VISIBILITY))
        if "source_links" in meta and meta.get("source_links") not in SOURCE_LINKS:
            add("meta.source_links %r not in %s" % (meta.get("source_links"), SOURCE_LINKS))
        remote = meta.get("remote_url")
        if remote is not None and not isinstance(remote, str):
            add("meta.remote_url is neither string nor null")
        areas = meta.get("areas")
        if areas is not None:
            if not isinstance(areas, list):
                add("meta.areas is not an array")
            else:
                for i, area in enumerate(areas):
                    if not isinstance(area, dict):
                        add("meta.areas[%d] is not an object" % i)
                        continue
                    for req in ("id", "title", "root_paths"):
                        if req not in area:
                            add("meta.areas[%d]: missing required field %s" % (i, req))
                    aid = area.get("id")
                    if isinstance(aid, str) and not ID_RE.match(aid):
                        add("meta.areas[%d].id %r does not match ^[a-z][a-z0-9_]*$" % (i, aid))

    elements = model.get("elements")
    if not isinstance(elements, list):
        add("elements: required array missing")
        elements = []
    seen_ids = set()
    for i, el in enumerate(elements):
        where = "elements[%d]" % i
        if not isinstance(el, dict):
            add("%s: not an object" % where)
            continue
        eid = el.get("id")
        if not isinstance(eid, str) or not ID_RE.match(eid):
            add("%s: id %r does not match ^[a-z][a-z0-9_]*$" % (where, eid), element_id=eid)
        elif eid in seen_ids:
            add("%s: duplicate element id" % where, element_id=eid)
        else:
            seen_ids.add(eid)
        if el.get("kind") not in ELEMENT_KINDS:
            add("%s: kind %r not in the kind enum" % (where, el.get("kind")), element_id=eid)
        for field, cap, required in (
            ("title", MAX_TITLE, True),
            ("summary", MAX_SUMMARY, True),
            ("description", MAX_DESCRIPTION, False),
        ):
            val = el.get(field)
            if val is None:
                if required:
                    add("%s: missing required field %s" % (where, field), element_id=eid)
            elif not isinstance(val, str):
                add("%s: %s is not a string" % (where, field), element_id=eid)
            elif len(val) > cap:
                add("%s: %s exceeds maxLength %d" % (where, field, cap), element_id=eid)
        parent = el.get("parent")
        if parent is not None and not isinstance(parent, str):
            add("%s: parent is neither string nor null" % where, element_id=eid)
        files = el.get("files")
        if files is not None:
            if not isinstance(files, list):
                add("%s: files is not an array" % where, element_id=eid)
            else:
                for j, f in enumerate(files):
                    fwhere = "%s.files[%d]" % (where, j)
                    if not isinstance(f, dict) or not isinstance(f.get("path"), str):
                        add("%s: missing required string path" % fwhere, element_id=eid)
                        continue
                    if f["path"].startswith("/"):
                        add("%s: path must not start with /" % fwhere,
                            element_id=eid, path=f["path"])
                    for lf in ("start_line", "end_line"):
                        lv = f.get(lf)
                        if lv is not None and (not isinstance(lv, int) or isinstance(lv, bool) or lv < 1):
                            add("%s: %s is not an integer >= 1" % (fwhere, lf),
                                element_id=eid, path=f["path"])

    relations = model.get("relations")
    if not isinstance(relations, list):
        add("relations: required array missing")
        relations = []
    for i, rel in enumerate(relations):
        where = "relations[%d]" % i
        if not isinstance(rel, dict):
            add("%s: not an object" % where)
            continue
        for req in ("from", "to"):
            if not isinstance(rel.get(req), str):
                add("%s: missing required string %s" % (where, req))
        summary = rel.get("summary")
        if summary is None:
            add("%s: missing required field summary" % where)
        elif not isinstance(summary, str):
            add("%s: summary is not a string" % where)
        elif len(summary) > MAX_SUMMARY:
            add("%s: summary exceeds maxLength %d" % (where, MAX_SUMMARY))
        rkind = rel.get("kind")
        if rkind is not None and rkind not in RELATION_KINDS:
            add("%s: kind %r not in the relation kind enum" % (where, rkind))
    return errors


# ---------------------------------------------------------------------------
# Checks 2-6
# ---------------------------------------------------------------------------

def check_evidence(model):
    errors = []
    for el in model.get("elements", []):
        eid = el.get("id")
        if el.get("kind") == "actor":
            # The section 3.3 actor exemption: a persona anchors its claim
            # in prose, never a fabricated file anchor.
            if not (el.get("description") or "").strip():
                errors.append(err(
                    "evidence",
                    "actor is exempt from files-or-external_url but must carry a non-empty description",
                    element_id=eid,
                ))
            continue
        if not el.get("files") and not el.get("external_url"):
            errors.append(err(
                "evidence",
                "element has neither a non-empty files[] nor an external_url",
                element_id=eid,
            ))
    return errors


def path_shape_error(path):
    """Traversal rules (security C4): schema already bans a leading /; this
    additionally rejects any .. segment and NUL/control characters."""
    if path.startswith("/"):
        return "path is absolute"
    if any(seg == ".." for seg in path.split("/")):
        return "path contains a .. segment"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        return "path contains NUL/control characters"
    return None


def check_paths(model, repo, anchor_sha):
    errors = []
    for el in model.get("elements", []):
        eid = el.get("id")
        for f in el.get("files") or []:
            path = f.get("path")
            if not isinstance(path, str):
                continue
            shape = path_shape_error(path)
            if shape:
                errors.append(err("path", shape, element_id=eid, path=path))
                continue
            # Existence is checked exclusively via git (git-native ONLY --
            # a raw filesystem join could escape the repo; cat-file cannot).
            proc = subprocess.run(
                ["git", "-C", repo, "cat-file", "-e", "%s:%s" % (anchor_sha, path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if proc.returncode != 0:
                errors.append(err(
                    "path",
                    "path not present at anchor sha %s" % anchor_sha,
                    element_id=eid, path=path,
                ))
    return errors


def check_ranges(model):
    errors = []
    for el in model.get("elements", []):
        eid = el.get("id")
        for f in el.get("files") or []:
            start, end = f.get("start_line"), f.get("end_line")
            if end is not None and start is None:
                errors.append(err("range", "end_line without start_line",
                                  element_id=eid, path=f.get("path")))
            elif start is not None and end is not None and end < start:
                errors.append(err("range", "end_line %s < start_line %s" % (end, start),
                                  element_id=eid, path=f.get("path")))
    return errors


def check_relations(model):
    ids = {el.get("id") for el in model.get("elements", [])}
    errors = []
    for rel in model.get("relations", []):
        for endpoint in ("from", "to"):
            val = rel.get(endpoint)
            if val not in ids:
                errors.append(err(
                    "relation",
                    "relation %s -> %s: %s endpoint %r does not exist"
                    % (rel.get("from"), rel.get("to"), endpoint, val),
                    element_id=val if isinstance(val, str) else None,
                ))
    return errors


def check_parents(model):
    by_id = {el.get("id"): el for el in model.get("elements", [])}
    errors = []
    for el in model.get("elements", []):
        eid = el.get("id")
        parent = el.get("parent")
        if parent is not None and parent not in by_id:
            errors.append(err("parent", "parent %r does not exist" % parent, element_id=eid))
    # Acyclicity over resolvable chains.
    state = {}  # 0 = visiting, 1 = done
    def visit(eid, trail):
        if state.get(eid) == 1:
            return
        if state.get(eid) == 0:
            errors.append(err("parent", "parent cycle: %s" % " -> ".join(trail + [eid]),
                              element_id=eid))
            return
        state[eid] = 0
        parent = by_id.get(eid, {}).get("parent")
        if parent is not None and parent in by_id:
            visit(parent, trail + [eid])
        state[eid] = 1
    for eid in sorted(k for k in by_id if isinstance(k, str)):
        if state.get(eid) is None:
            visit(eid, [])
    return errors


# ---------------------------------------------------------------------------
# Check 7: likec4 validate --json (the toolchain gate)
# ---------------------------------------------------------------------------

def check_likec4(model_dir):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = ["bash", os.path.join(script_dir, "likec4.sh"), "validate", "--json", model_dir]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    data = None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        pass
    errors = []
    if data is None:
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            errors.append(err(
                "likec4",
                "likec4 validate exited %d with unparseable output: %s"
                % (proc.returncode, " | ".join(tail)),
            ))
        return errors
    if data.get("valid") is True and proc.returncode == 0:
        return errors
    for e in data.get("errors", []) or []:
        message = e.get("message", "likec4 validation error")
        line = e.get("line")
        if line is not None:
            message = "%s (line %s)" % (message, line)
        errors.append(err("likec4", message, path=e.get("file")))
    if not errors:
        errors.append(err("likec4", "likec4 validate reported invalid with no error detail"))
    return errors


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run(argv=None):
    ap = argparse.ArgumentParser(prog="validate_map.py")
    ap.add_argument("--model", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--anchor-sha", required=True)
    args = ap.parse_args(argv)

    try:
        with open(args.model, "r", encoding="utf-8") as fh:
            model = json.load(fh)
    except (OSError, ValueError) as exc:
        print("validate_map.py: cannot read model %s: %s" % (args.model, exc), file=sys.stderr)
        return 2

    errors = check_schema(model)
    if not errors:
        # Checks 2-6 assume schema-valid shapes; a schema failure condemns
        # the model already, so they are skipped rather than crash-prone.
        errors.extend(check_evidence(model))
        errors.extend(check_paths(model, args.repo, args.anchor_sha))
        errors.extend(check_ranges(model))
        errors.extend(check_relations(model))
        errors.extend(check_parents(model))
    if not errors:
        errors.extend(check_likec4(args.model_dir))

    errors_path = os.path.join(os.path.dirname(os.path.abspath(args.model)), "errors.json")
    if errors:
        with open(errors_path, "w", encoding="utf-8") as fh:
            json.dump(errors, fh, indent=2)
            fh.write("\n")
        print("validate_map.py: FAIL: %d error(s); written to %s" % (len(errors), errors_path))
        for e in errors[:20]:
            loc = e["element_id"] or e["path"] or "-"
            print("  [%s] %s: %s" % (e["check"], loc, e["message"]))
        if len(errors) > 20:
            print("  ... and %d more (see errors.json)" % (len(errors) - 20))
        return 1
    if os.path.exists(errors_path):
        os.unlink(errors_path)  # a stale errors.json must not outlive a green run
    print("validate_map.py: ok: all 7 checks green (%d elements, %d relations)"
          % (len(model.get("elements", [])), len(model.get("relations", []))))
    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
