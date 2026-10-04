#!/usr/bin/env python3
"""draft_proposals.py - the code half of the autoheal drafting step (#1099 Phase 2.2).

autoheal-analyze.sh owns the API calls, cost log and stop_reason handling. This
file does everything that is plain computation:

  plan    Read signatures/<date>.json, take at most 3 qualifying signatures and
          route each one:
            hook denial   -> an `issue` proposal, drafted here, no model call
            everything else -> a request for the model: the signature, the full
                            text of at most 2 candidate rule files chosen by
                            lib/signature-module-map.json (keyword match as the
                            fallback), at most one redacted 1,500-character
                            excerpt, and the module index as a cacheable prefix.
          Writes item-<n>.json / .request.json / .count.json files and a
          plan.tsv the shell reads.
  finish  Check the model's answer against the real files and build the row.
          The model returns only a rule_insert or a skip. Code derives the id
          (the aggregator's signature_id, sha256(signature)[:12]), checks that
          target_path is a candidate and the anchor heading exists, and
          generates the unified diff. A failed check drops the answer with a
          counted reason (anchor_missing, path_not_candidate, ...).

  validate  Before a row is stored as ready, the gate in apply-proposal.py
          (validate) checks that the diff applies to the source repo's
          origin/main, that its personal-data and module tests pass, and that
          always-loaded rules stay inside the weekly line budget. A failing row
          is stored with state "dropped" and a drop_reason, counted with the
          other drops, and never shown.

Rows go to proposals/<today>.jsonl, where the digest and apply commands read
them until the single ledger of a later unit replaces that directory.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import difflib
import fcntl
import importlib.util
import json
import os
import re
import sys

MAX_SIGNATURES = 3
MAX_INSERT_LINES = 8
MAX_EXCERPT_CHARS = 1500
MAX_SAMPLES_SHOWN = 3

# Keywords the structured-outputs schema subset rejects. Limits they would
# express are checked after the parse instead.
SCHEMA_KEYWORD_DENYLIST = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern",
    "minItems", "maxItems", "uniqueItems",
    "default",
}

_HERE = os.path.dirname(os.path.abspath(__file__))
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
_LIST_ITEM_RE = re.compile(r"^[ \t]*([-*+]|\d+[.)])[ \t]+\S")


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _aggregate():
    return _load(os.path.join(_HERE, "..", "bin", "autoheal-aggregate.py"), "autoheal_aggregate")


def _module_index():
    return _load(os.path.join(_HERE, "module-index.py"), "autoheal_module_index")


def _today() -> str:
    return os.environ.get("CCGM_AUTOHEAL_TODAY") or dt.datetime.now(dt.timezone.utc).date().isoformat()


def _proposals_path(agg) -> str:
    base = os.environ.get("CCGM_AUTOHEAL_PROPOSALS_DIR") or os.path.join(agg.autoheal_dir(), "proposals")
    return os.path.join(base, _today() + ".jsonl")


def append_jsonl(path: str, record: dict) -> None:
    """Locked append, same discipline as hook_utils.file_locked_append."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, payload)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------
# Candidate selection (deterministic).
# ---------------------------------------------------------------------

def load_map(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def is_hook_denial(sig: dict, mp: dict) -> bool:
    cls = sig.get("error_class") or ""
    return cls in mp.get("hook_denial_modules", {}) or cls.startswith("hook_denial")


def hook_module(sig: dict, mp: dict) -> str:
    return mp.get("hook_denial_modules", {}).get(sig.get("error_class") or "", "unknown")


def _keyword_candidates(sig: dict, entries: list, stop: set, limit: int) -> list:
    words = set()
    for text in (sig.get("cmd_head"), sig.get("tool_name"), sig.get("error_class")):
        for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
            if len(w) >= 3 and w not in stop:
                words.add(w)
    scored = []
    for e in entries:
        hay = " ".join([e["path"], e.get("h1") or "", *e.get("h2", [])]).lower()
        score = len(words & set(re.findall(r"[a-z0-9]+", hay)))
        if score:
            scored.append((-score, e["path"]))
    return [p for _, p in sorted(scored)][:limit]


def pick_candidates(sig: dict, entries: list, mp: dict) -> list:
    """Up to max_files repo-relative rule paths for a signature.

    Order: modules for the command head, then modules for the error class,
    then (only if both gave nothing) keyword matches against the index.
    """
    limit = int(mp.get("max_files", 2))
    paths = [e["path"] for e in entries]
    by_module: dict = {}
    for p in paths:
        by_module.setdefault(p.split("/")[1], []).append(p)
    chosen: list = []

    def add(module: str) -> None:
        files = by_module.get(module, [])
        own = f"modules/{module}/rules/{module}.md"
        for f in ([own] if own in files else files):
            if f not in chosen:
                chosen.append(f)

    head = (sig.get("cmd_head") or "").split()
    for module in mp.get("by_cmd_head", {}).get(head[0] if head else "", []):
        add(module)
    for module in mp.get("by_error_class", {}).get(sig.get("error_class") or "", []):
        add(module)
    if not chosen:
        chosen = _keyword_candidates(sig, entries, set(mp.get("keyword_stopwords", [])), limit)
    return chosen[:limit]


# ---------------------------------------------------------------------
# Request building.
# ---------------------------------------------------------------------

def _strip_schema(node, in_properties: bool = False):
    if isinstance(node, list):
        return [_strip_schema(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if not in_properties and k in SCHEMA_KEYWORD_DENYLIST:
            continue
        out[k] = _strip_schema(v, in_properties=(k == "properties" and not in_properties))
    return out


def output_schema(schema_path: str, candidates: list) -> dict:
    """The response schema for one call, target_path pinned to the candidates."""
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    schema = copy.deepcopy(schema)
    for branch in schema["properties"]["proposal"]["anyOf"]:
        if "target_path" in branch["properties"]:
            branch["properties"]["target_path"]["enum"] = list(candidates)
    schema = _strip_schema(schema)
    return {k: schema[k] for k in ("type", "additionalProperties", "required", "properties")}


def _fence_for(text: str) -> str:
    longest = max([len(m) for m in re.findall(r"`+", text)] or [0])
    return "`" * max(3, longest + 1)


def latest_excerpt(agg, data_dir: str, sig: dict, window_end: dt.date, window_start: dt.date) -> str:
    """Redacted command and error of the most recent matching failure, <= 1,500 chars."""
    target = (sig["tool_name"], sig.get("cmd_head") or "", sig["error_class"])
    redact = agg._redactor()
    day = window_end
    while day >= window_start:
        found = None
        for row in agg._read_rows(data_dir, day):
            if row.get("kind") == "tool_failure" and agg.row_signature(row) == target:
                found = row  # rows are appended in time order; keep the last
        if found:
            parts = []
            cmd = found.get("redacted_command")
            if isinstance(cmd, str) and cmd:
                parts.append("$ " + cmd)
            err = found.get("error")
            if isinstance(err, str) and err:
                parts.append(err)
            return redact("\n".join(parts))[:MAX_EXCERPT_CHARS]
        day -= dt.timedelta(days=1)
    return ""


def user_message(sig: dict, files: dict, excerpt: str) -> str:
    shown = {k: sig.get(k) for k in (
        "tool_name", "cmd_head", "error_class", "count", "sessions", "repos", "days",
        "first_seen", "last_seen", "rate_per_100_calls")}
    shown["samples"] = (sig.get("samples") or [])[:MAX_SAMPLES_SHOWN]
    out = ["## Signature", "", "```json", json.dumps(shown, indent=2), "```", "",
           "## Candidate files", "",
           "`target_path` must be one of these paths. Each file is shown in full.", ""]
    for path, text in files.items():
        fence = _fence_for(text)
        out += [f"### {path}", "", fence + "markdown", text.rstrip("\n"), fence, ""]
    if excerpt:
        fence = _fence_for(excerpt)
        out += ["## Excerpt of the most recent occurrence", "", fence + "text", excerpt, fence, ""]
    return "\n".join(out)


def build_request(model: str, max_tokens: int, prompt: str, index_text: str,
                  user_text: str, schema: dict) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
        # Prompt and module index are identical for every signature of a run
        # (and across runs while the repo's headings hold), so the breakpoint
        # sits after the index and the per-signature user message follows it.
        "system": [
            {"type": "text", "text": prompt},
            {"type": "text", "text": "## Module index\n\n" + index_text,
             "cache_control": {"type": "ephemeral"}},
        ],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        "messages": [{"role": "user", "content": user_text}],
    }


# ---------------------------------------------------------------------
# Rows the code builds from a signature (never from model output).
# ---------------------------------------------------------------------

def _evidence(sig: dict) -> dict:
    return {
        "count": sig.get("count"),
        "sessions": sig.get("sessions"),
        "repos": sig.get("repos"),
        "days": sig.get("days"),
        "first_seen": sig.get("first_seen"),
        "last_seen": sig.get("last_seen"),
        "calls": sig.get("calls"),
        "rate_per_100_calls": sig.get("rate_per_100_calls"),
        "samples": list(sig.get("samples") or []),
    }


def _label(sig: dict) -> str:
    return f"{sig.get('cmd_head') or sig.get('tool_name')} {sig.get('error_class')}".strip()


def _summary(sig: dict) -> str:
    ev = _evidence(sig)
    return (f"{ev['count']} failures in {ev['sessions']} sessions over {ev['days']} days "
            f"({ev['first_seen']} to {ev['last_seen']}).")


def _base_row(sig: dict, ctx: dict) -> dict:
    sid = sig["signature_id"]
    return {
        "id": sid,
        "signature_id": sid,
        "state": "ready",
        "tool_name": sig.get("tool_name"),
        "cmd_head": sig.get("cmd_head"),
        "error_class": sig.get("error_class"),
        "occurrence_count": sig.get("count"),
        "evidence": _evidence(sig),
        "originating_clone": ctx.get("clone_id", ""),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_day": ctx.get("date", ""),
    }


def issue_row(sig: dict, module: str, ctx: dict) -> dict:
    samples = "\n".join(f"- `{s}`" for s in (sig.get("samples") or [])[:MAX_SAMPLES_SHOWN]) or "- (none)"
    body = "\n".join([
        f"The `{module}` hook denied the same shape of call {sig.get('count')} times.",
        "",
        "## Evidence",
        "",
        f"- Tool: `{sig.get('tool_name')}`",
        f"- Denial class: `{sig.get('error_class')}`",
        f"- {_summary(sig)}",
        "",
        "## Sample denials",
        "",
        samples,
        "",
        "## Ask",
        "",
        "Decide which side is wrong. If the hook blocks a safe call, narrow it. If the "
        "agent keeps attempting a blocked call, make the denial message say what to do "
        "instead.",
    ])
    row = _base_row(sig, ctx)
    row.update({
        "kind": "issue",
        "fix_surface": "check",
        "module": module,
        "title": f"{module}: denial recurs ({sig.get('error_class')})",
        "rationale": f"The {module} hook denied the same call shape. {_summary(sig)}",
        "issue_title": f"{module}: recurring hook denial ({sig.get('error_class')})",
        "issue_body": body,
    })
    return row


# ---------------------------------------------------------------------
# Diff building and checks on the model's answer.
# ---------------------------------------------------------------------

def _norm_heading(text: str) -> str:
    return " ".join(text.strip().lstrip("#").split())


def find_heading(lines: list, anchor: str):
    """(index, level) of the first heading whose text is `anchor`, outside code fences."""
    want = _norm_heading(anchor)
    fence = None
    for i, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
            continue
        if fence:
            continue
        h = _HEADING_RE.match(line)
        if h and _norm_heading(h.group(2)) == want:
            return i, len(h.group(1))
    return None


def insert_under_heading(text: str, anchor: str, insert_lines: list):
    """New file text with the lines added at the end of the anchored section, or None."""
    lines = text.split("\n")
    found = find_heading(lines, anchor)
    if found is None:
        return None
    start, level = found
    end = len(lines)
    fence = None
    for i in range(start + 1, len(lines)):
        m = _FENCE_RE.match(lines[i])
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
            continue
        if fence:
            continue
        h = _HEADING_RE.match(lines[i])
        if h and len(h.group(1)) <= level:
            end = i
            break
    pos = start + 1
    for i in range(start + 1, end):
        if lines[i].strip():
            pos = i + 1
    tail = [""] if pos < len(lines) and lines[pos].strip() else []
    # A bullet joins the bullet list above it; anything else starts a paragraph.
    joins_list = (pos > start + 1 and bool(_LIST_ITEM_RE.match(lines[pos - 1]))
                  and bool(_LIST_ITEM_RE.match(insert_lines[0])))
    gap = [] if joins_list else [""]
    return "\n".join(lines[:pos] + gap + insert_lines + tail + lines[pos:])


def unified_diff(path: str, old: str, new: str) -> str:
    out = []
    for line in difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                     fromfile="a/" + path, tofile="b/" + path):
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


def make_row(sig: dict, answer, candidates: list, repo_root: str, ctx: dict):
    """(row, None) for a usable answer, (None, reason) for a dropped one.

    A skip returns a row whose state is "skipped" so the aggregator treats the
    signature as covered and it is not paid for again.
    """
    proposal = answer.get("proposal") if isinstance(answer, dict) else None
    if not isinstance(proposal, dict) or proposal.get("kind") not in ("rule_insert", "skip"):
        return None, "answer_malformed"
    row = _base_row(sig, ctx)
    if proposal["kind"] == "skip":
        reason = proposal.get("reason")
        row.update({"kind": "skip", "state": "skipped", "fix_surface": "rule",
                    "title": f"skipped: {_label(sig)}",
                    "rationale": reason if isinstance(reason, str) else "",
                    "reason": reason if isinstance(reason, str) else ""})
        return row, None

    target = proposal.get("target_path")
    anchor = proposal.get("anchor_heading")
    insert = proposal.get("insert_markdown")
    if not all(isinstance(v, str) for v in (target, anchor, insert)):
        return None, "answer_malformed"
    if target not in candidates:
        return None, "path_not_candidate"
    try:
        with open(os.path.join(repo_root, target), "r", encoding="utf-8") as fh:
            old = fh.read()
    except OSError:
        return None, "target_unreadable"
    insert_lines = [ln.rstrip() for ln in insert.strip("\n").split("\n")]
    while insert_lines and not insert_lines[0].strip():
        insert_lines.pop(0)
    if not insert_lines or not any(ln.strip() for ln in insert_lines):
        return None, "insert_empty"
    if len(insert_lines) > MAX_INSERT_LINES:
        return None, "insert_too_long"
    new = insert_under_heading(old, anchor, insert_lines)
    if new is None:
        return None, "anchor_missing"
    diff = unified_diff(target, old, new)
    anchor_text = _norm_heading(anchor)
    row.update({
        "kind": "rule_insert",
        "fix_surface": "rule",
        "title": f"{_label(sig)}: add a rule to {os.path.basename(target)}",
        "rationale": (f"{_summary(sig)} The smallest rule that would have prevented them goes "
                      f"under \"{anchor_text}\" in {target}."),
        "target": target,
        "anchor": anchor_text,
        "insert_markdown": "\n".join(insert_lines),
        "diff": diff,
        # Read by apply-proposal.py and the digest until the ledger migration
        # (B7) gives them the new names.
        "proposed_diff_target": target,
        "proposed_diff": diff,
        "model": ctx.get("model", ""),
    })
    return row, None


# ---------------------------------------------------------------------
# Subcommands.
# ---------------------------------------------------------------------

def cmd_plan(args) -> int:
    agg = _aggregate()
    data_dir = agg.autoheal_dir()
    sig_path = os.path.join(data_dir, "signatures", args.date + ".json")
    try:
        with open(sig_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"draft_proposals: cannot read {sig_path}: {exc}", file=sys.stderr)
        return 4
    chosen = [s for s in data.get("signatures", []) if s.get("qualifies")][:MAX_SIGNATURES]
    mp = load_map(args.map)
    ctx = {"clone_id": args.clone_id, "date": args.date, "model": args.model}
    os.makedirs(args.out, exist_ok=True)
    plan_lines = [f"selected\t{len(chosen)}\t-"]

    repo_root = index = None
    repo_note = ""
    resolved = False
    window_end = dt.date.fromisoformat(data.get("date", args.date))
    window_start = dt.date.fromisoformat(data.get("window_start", args.date))
    prompt = index_text = None
    item_no = 0
    for sig in chosen:
        sid = sig["signature_id"]
        if is_hook_denial(sig, mp):
            module = hook_module(sig, mp)
            append_jsonl(_proposals_path(agg), issue_row(sig, module, ctx))
            plan_lines.append(f"issue\t{sid}\t{module}")
            continue
        if not resolved:
            resolved = True
            mi = _module_index()
            repo_root, how = mi.resolve_source_repo(args.config)
            if repo_root:
                index = mi.build_index(repo_root)
                index_text = index["text"]
                with open(args.prompt, "r", encoding="utf-8") as fh:
                    prompt = fh.read()
            else:
                repo_note = how
        if repo_root is None:
            plan_lines.append(f"note\t{sid}\tno_source_repo: {repo_note}")
            continue
        candidates = pick_candidates(sig, index["files"], mp)
        if not candidates:
            plan_lines.append(f"note\t{sid}\tno_candidates")
            continue
        files = {}
        for rel in candidates:
            with open(os.path.join(repo_root, rel), "r", encoding="utf-8") as fh:
                files[rel] = fh.read()
        excerpt = latest_excerpt(agg, data_dir, sig, window_end, window_start)
        user_text = user_message(sig, files, excerpt)
        schema = output_schema(args.schema, candidates)
        request = build_request(args.model, args.max_tokens, prompt, index_text, user_text, schema)
        item_no += 1
        stem = os.path.join(args.out, f"item-{item_no}")
        with open(stem + ".request.json", "w", encoding="utf-8") as fh:
            json.dump(request, fh)
        with open(stem + ".count.json", "w", encoding="utf-8") as fh:
            json.dump({k: request[k] for k in ("model", "system", "messages")}, fh)
        with open(stem + ".json", "w", encoding="utf-8") as fh:
            json.dump({"signature_id": sid, "signature": sig, "candidates": candidates,
                       "repo_root": repo_root, "model": args.model}, fh)
        prompt_log = os.environ.get("CCGM_AUTOHEAL_PROMPT_LOG")
        if prompt_log:
            os.makedirs(os.path.dirname(os.path.abspath(prompt_log)), exist_ok=True)
            with open(prompt_log, "a", encoding="utf-8") as fh:
                fh.write("SYSTEM:\n" + prompt + "\n\n" + index_text + "\n\nUSER:\n" + user_text + "\n")
        plan_lines.append(f"item\t{item_no}\t{sid}")
    with open(os.path.join(args.out, "plan.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(plan_lines) + "\n")
    return 0


def cmd_finish(args) -> int:
    agg = _aggregate()
    with open(args.meta, "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    with open(args.answer, "r", encoding="utf-8") as fh:
        text = fh.read()
    ctx = {"clone_id": args.clone_id, "date": args.date, "model": meta.get("model", "")}
    try:
        answer = json.loads(text)
    except ValueError:
        answer = None
    if answer is None:
        row, why = None, "answer_not_json"
    else:
        row, why = make_row(meta["signature"], answer, meta["candidates"], meta["repo_root"], ctx)
    if row is not None and row["kind"] == "rule_insert":
        gate = _load(os.path.join(_HERE, "apply-proposal.py"), "autoheal_apply")
        ok, reason = gate.validate(row, repo_root=meta["repo_root"])
        if not ok:
            row, why = None, reason
    if row is None:
        # Every drop is stored. The aggregator turns the row into a cooldown, so the
        # signature is not drafted (and paid for) again the next night.
        dropped = _base_row(meta["signature"], ctx)
        dropped.update({"kind": "rule_insert", "state": "dropped", "drop_reason": why})
        if why in agg.INFRA_DROP_REASONS:
            history = agg.drop_history(agg.autoheal_dir()).get(meta["signature_id"], [])
            # Read by the health writer: three in a row means validation is broken, not the draft.
            dropped["consecutive_unavailable"] = agg.unavailable_streak(history) + 1
            if dropped["consecutive_unavailable"] >= agg.INFRA_STREAK_FOR_COOLDOWN:
                dropped["health_reason"] = (f"validation_unavailable {dropped['consecutive_unavailable']} "
                                            f"nights running for signature {meta['signature_id']}")
        append_jsonl(_proposals_path(agg), dropped)
        if args.rejected_log:
            append_jsonl(args.rejected_log, {
                "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                "reason": why, "signature_id": meta["signature_id"], "answer": text[:2000]})
        print(json.dumps({"outcome": "dropped", "reason": why}))
        return 0
    append_jsonl(_proposals_path(agg), row)
    print(json.dumps({"outcome": row["kind"], "reason": ""}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--date", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--max-tokens", type=int, default=2000)
    p.add_argument("--prompt", default=os.path.join(_HERE, "analyzer-prompt.md"))
    p.add_argument("--schema", default=os.path.join(_HERE, "proposal-schema.json"))
    p.add_argument("--map", default=os.path.join(_HERE, "signature-module-map.json"))
    p.add_argument("--config", default=None)
    p.add_argument("--clone-id", default="")
    p.set_defaults(fn=cmd_plan)
    f = sub.add_parser("finish")
    f.add_argument("--meta", required=True)
    f.add_argument("--answer", required=True)
    f.add_argument("--date", required=True)
    f.add_argument("--rejected-log", default="")
    f.add_argument("--clone-id", default="")
    f.set_defaults(fn=cmd_finish)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
