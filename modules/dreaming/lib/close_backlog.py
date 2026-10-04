#!/usr/bin/env python3
"""One-off close of the pre-redesign proposal backlog (#1098 item 2.4).

Before #1098 every proposal that did not auto-integrate waited for a human
who never came; 228 of them piled up. This replays every pending proposal,
plain and gzipped, through the current Phase 3 filters and gives each a
terminal state:

    already_encoded     the loaded-context prefilter matched a rule,
                        CLAUDE.md, auto-memory file or hook message (#1116)
    routed_to_autoheal  every cited excerpt is an installed hook's error (#1118)
    trigger_invalid     the row carries a trigger that does not parse (#1114)
    trigger_unverified  the row carries a trigger that matches none of its own
                        cited excerpts (#1114)
    expired             everything else, detail `pre-redesign`: it came from
                        the old miner

Only add/supersede rows carry content, so only they go through the
prefilter and the trigger check. A row without a trigger (the old miner
never wrote one) skips the trigger check. The tool-error half of the
autoheal routing needs the night's evidence bundle, which old proposals do
not have, so only the hook-error half runs here.

Dry run by default: prints the plan and writes nothing. `--apply` marks each
row `discarded` with its reason and writes one `discarded` apply-audit record
per row (method `backlog-close`). A second `--apply` finds nothing pending.

Run it once, by hand, at bring-up. Nothing imports or schedules it.

    bash ~/.claude/bin/dream-close-backlog.sh            # dry run
    bash ~/.claude/bin/dream-close-backlog.sh --apply
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import apply_dream_proposal as adp  # noqa: E402
import dream_analyze as da  # noqa: E402
import loaded_context  # noqa: E402
import triggers  # noqa: E402

PRE_REDESIGN = "pre-redesign"
METHOD = "backlog-close"


def _pending_rows() -> list[tuple[Path, dict[str, Any]]]:
    out = []
    for path in loaded_context.proposal_files(da.proposals_dir()):
        for row in loaded_context.read_proposal_rows(path):
            if row.get("status") == "pending" and row.get("id"):
                out.append((path, row))
    return out


def _evidence_cwds(row: dict[str, Any]) -> list[str]:
    cwds = []
    for ev in row.get("evidence") or []:
        info = da.learnings_store.resolve_session_transcript(ev.get("session_id")) if isinstance(ev, dict) else None
        if info and info.get("cwd"):
            cwds.append(info["cwd"])
    return cwds


def _classify(
    row: dict[str, Any], *, corpus: loaded_context.Corpus, roots: loaded_context.Roots,
    hook_names: set[str], threshold: float,
) -> tuple[str, str]:
    if row.get("kind") not in da.KINDS_REQUIRING_CONTENT or not isinstance(row.get("content"), str):
        return adp.REASON_EXPIRED, PRE_REDESIGN
    evidence = [e for e in row.get("evidence") or [] if isinstance(e, dict)]
    _kept, dropped = loaded_context.prefilter_candidates(
        [{"content": row["content"], "evidence": evidence}], corpus,
        threshold=threshold, hook_names=hook_names, hooks_dir=roots.hooks_dir,
    )
    if dropped:
        hit = dropped[0]
        score = f" (score {hit['score']})" if hit.get("score") is not None else ""
        return hit["reason"], f"{hit['source']}{score}"
    trigger = row.get("trigger")
    if trigger is not None:
        problem = triggers.validate_trigger(trigger)
        if problem:
            return da.TRIGGER_INVALID, problem
        if not triggers.matches_any(trigger, [e.get("excerpt") for e in evidence]):
            return da.TRIGGER_UNVERIFIED, f"trigger matches none of the {len(evidence)} cited excerpt(s)"
    return adp.REASON_EXPIRED, PRE_REDESIGN


def plan() -> dict[str, Any]:
    """Every pending row with the terminal reason it would get. Writes nothing."""
    cfg = da.load_config()
    threshold = float(cfg.get("prefilter_threshold", loaded_context.DEFAULT_THRESHOLD))
    # Pending proposals are the thing being judged, so they stay out of the
    # corpus: a row would otherwise match itself.
    roots = dataclasses.replace(
        loaded_context.Roots.from_env(), proposals_dir=da.dreaming_dir() / ".no-proposals-corpus",
    )
    hook_names = loaded_context.installed_hook_names(roots.hooks_dir)
    pending = _pending_rows()

    cwds_by_slug: dict[str, list[str]] = {}
    for _path, row in pending:
        if row.get("kind") in da.KINDS_REQUIRING_CONTENT:
            cwds_by_slug.setdefault(str(row.get("project")), []).extend(_evidence_cwds(row))
    corpora = {
        slug: loaded_context.build_corpus(slug, cwds=cwds, roots=roots)
        for slug, cwds in cwds_by_slug.items()
    }
    empty = loaded_context.Corpus([])

    records = []
    for path, row in pending:
        reason, detail = _classify(
            row, corpus=corpora.get(str(row.get("project")), empty), roots=roots,
            hook_names=hook_names, threshold=threshold,
        )
        records.append({
            "path": str(path), "proposal_id": row["id"], "kind": row.get("kind"),
            "project": row.get("project"), "reason": reason, "detail": detail,
        })
    return {
        "pending": len(pending), "planned": len(records),
        "by_reason": dict(sorted(Counter(r["reason"] for r in records).items())),
        "records": records,
    }


def apply(result: dict[str, Any]) -> int:
    """Write the planned discards, one locked rewrite per file."""
    by_path: dict[str, dict[str, tuple[str, str]]] = {}
    for rec in result["records"]:
        by_path.setdefault(rec["path"], {})[rec["proposal_id"]] = (rec["reason"], rec["detail"])
    return sum(len(adp._discard_rows(Path(p), d, method=METHOD)) for p, d in by_path.items())  # noqa: SLF001


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Close the pre-redesign dreaming proposal backlog (#1098 2.4).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan, write nothing (default)")
    mode.add_argument("--apply", action="store_true", help="write the statuses and audit records")
    args = ap.parse_args(argv)

    result = plan()
    out: dict[str, Any] = {"mode": "apply" if args.apply else "dry-run", "dreaming_dir": str(da.dreaming_dir())}
    out.update(result)
    if args.apply:
        out["discarded"] = apply(result)
        out["pending_after"] = len(_pending_rows())
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
