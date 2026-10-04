#!/usr/bin/env python3
"""autoheal-aggregate.py - deterministic friction signature aggregator.

Counts recurring tool failures with plain code (no model, no network) so the
drafting step only sees signatures that earned attention (#1099 Phase 2.1).

Input, under the autoheal data dir ($CCGM_AUTOHEAL_DIR, default
~/.claude/autoheal):
  events/{date}.jsonl   tool_failure and user_interrupt rows
  counts/{date}.json    per-tool call counters ({"Bash": 123, ...})
  snoozed.json          {"<signature_id or tool|head|class>": {"snoozed_until": ISO}}
  proposals.jsonl       optional ledger; rows carrying `signature_id` cover that
                        signature unless their state is "dropped"

Signature: (tool_name, cmd_head, error_class), from tool_failure rows only.
Rows written before PR #1112 have no error_class; they become class
"unknown" and never qualify. user_interrupt rows are tallied per tool in a
separate `interrupts` list.

Output: signatures/{date}.json, ranked by count x sessions.

Bar and window come from config.json (CCGM_AUTOHEAL_CONFIG or
<dir>/config.json), key "aggregation":
  {"window_days": 14, "min_occurrences": 5, "min_sessions": 2, "min_days": 2}

Usage: autoheal-aggregate.py [--date YYYY-MM-DD]   (default: today, UTC)

Phase 4.1 imports signature_rate() to compare baseline and post-merge rates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys

DEFAULTS = {"window_days": 14, "min_occurrences": 5, "min_sessions": 2, "min_days": 2}
MAX_SAMPLES = 3
MAX_SAMPLE_LEN = 300
UNKNOWN = "unknown"
KINDS = ("tool_failure", "user_interrupt")


def autoheal_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_DIR") or os.path.expanduser("~/.claude/autoheal")


def _redactor():
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (
        os.path.join(here, "..", "..", "hooks", "lib"),
        os.path.expanduser("~/.claude/lib"),
    ):
        if os.path.isfile(os.path.join(path, "hook_utils.py")):
            sys.path.insert(0, path)
            try:
                from hook_utils import redact_secrets

                return redact_secrets
            except Exception:
                pass
            finally:
                sys.path.remove(path)
    return lambda text: text


def load_config(data_dir: str) -> dict:
    path = os.environ.get("CCGM_AUTOHEAL_CONFIG") or os.path.join(data_dir, "config.json")
    cfg = dict(DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return cfg
    agg = raw.get("aggregation") if isinstance(raw, dict) else None
    if isinstance(agg, dict):
        for key in DEFAULTS:
            val = agg.get(key)
            if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                cfg[key] = val
    return cfg


def signature_id(sig: tuple) -> str:
    return hashlib.sha256("\x1f".join(sig).encode("utf-8")).hexdigest()[:12]


def _dates(start: dt.date, end: dt.date):
    for n in range((end - start).days + 1):
        yield start + dt.timedelta(days=n)


def _read_rows(data_dir: str, date: dt.date):
    path = os.path.join(data_dir, "events", date.isoformat() + ".jsonl")
    try:
        fh = open(path, "r", encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _read_counts(data_dir: str, date: dt.date) -> dict:
    try:
        with open(os.path.join(data_dir, "counts", date.isoformat() + ".json"), "r",
                  encoding="utf-8") as fh:
            val = json.load(fh)
    except (OSError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def _calls(data_dir: str, tool: str, start: dt.date, end: dt.date) -> int:
    total = 0
    for d in _dates(start, end):
        n = _read_counts(data_dir, d).get(tool, 0)
        if isinstance(n, int) and not isinstance(n, bool):
            total += n
    return total


def _rate(occurrences: int, calls: int):
    return occurrences / calls * 100 if calls > 0 else None


def row_signature(row: dict) -> tuple:
    """(tool_name, cmd_head, error_class); blind legacy rows -> unknown."""
    tool = str(row.get("tool_name") or "")
    cls = row.get("error_class")
    if not isinstance(cls, str) or not cls or cls == UNKNOWN:
        return (tool, "", UNKNOWN)
    head = row.get("cmd_head")
    return (tool, head if isinstance(head, str) else "", cls)


def signature_rate(data_dir: str, sig: tuple, start: dt.date, end: dt.date) -> dict:
    """Failure rate of one signature over [start, end] (inclusive).

    Returns {"occurrences", "calls", "rate_per_100_calls"}; the rate is None
    when counts/ holds no calls of the tool in the window.
    """
    sig = tuple(sig)
    occurrences = 0
    for d in _dates(start, end):
        for row in _read_rows(data_dir, d):
            if row.get("kind") == "tool_failure" and row_signature(row) == sig:
                occurrences += 1
    calls = _calls(data_dir, sig[0], start, end)
    return {"occurrences": occurrences, "calls": calls,
            "rate_per_100_calls": _rate(occurrences, calls)}


def _repo(cwd) -> str:
    """Repo name from a cwd: the dir under code/, minus -repos/-workspaces."""
    if not isinstance(cwd, str) or not cwd:
        return ""
    parts = [p for p in cwd.split("/") if p]
    if "code" in parts and parts.index("code") + 1 < len(parts):
        name = parts[parts.index("code") + 1]
    else:
        name = parts[-1] if parts else ""
    for suffix in ("-repos", "-workspaces"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _covered_ids(data_dir: str) -> set:
    ids = set()
    paths = [os.path.join(data_dir, "proposals.jsonl")]
    try:
        pdir = os.path.join(data_dir, "proposals")
        paths += [os.path.join(pdir, f) for f in sorted(os.listdir(pdir)) if f.endswith(".jsonl")]
    except OSError:
        pass
    for path in paths:
        try:
            fh = open(path, "r", encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(row, dict) and row.get("state") != "dropped"
                        and isinstance(row.get("signature_id"), str)):
                    ids.add(row["signature_id"])
    return ids


def _snoozed_keys(data_dir: str, as_of: dt.datetime) -> set:
    try:
        with open(os.path.join(data_dir, "snoozed.json"), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    keys = set()
    for key, entry in (data.items() if isinstance(data, dict) else []):
        until = entry.get("snoozed_until") if isinstance(entry, dict) else None
        if not isinstance(until, str):
            continue
        try:
            when = dt.datetime.fromisoformat(until.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        if when > as_of:
            keys.add(key)
    return keys


def aggregate(data_dir: str, end: dt.date, cfg: dict) -> dict:
    redact = _redactor()
    start = end - dt.timedelta(days=cfg["window_days"] - 1)
    stats: dict = {}
    interrupts: dict = {}
    for d in _dates(start, end):
        iso = d.isoformat()
        for row in _read_rows(data_dir, d):
            kind = row.get("kind")
            if kind not in KINDS:
                continue
            sess = row.get("session_id") or ""
            if kind == "user_interrupt":
                rec = interrupts.setdefault(str(row.get("tool_name") or ""),
                                            {"count": 0, "sessions": set(), "days": set()})
                rec["count"] += 1
                rec["sessions"].add(sess)
                rec["days"].add(iso)
                continue
            sig = row_signature(row)
            rec = stats.get(sig)
            if rec is None:
                rec = stats[sig] = {"count": 0, "sessions": set(), "repos": set(),
                                    "days": set(), "first": iso, "last": iso, "samples": {}}
            rec["count"] += 1
            rec["sessions"].add(sess)
            repo = _repo(row.get("cwd"))
            if repo:
                rec["repos"].add(repo)
            rec["days"].add(iso)
            rec["last"] = iso  # days iterate in order
            err = row.get("error")
            if isinstance(err, str) and err:
                text = redact(err)[:MAX_SAMPLE_LEN]
                rec["samples"].pop(text, None)  # keep the latest occurrence last
                rec["samples"][text] = True

    covered = _covered_ids(data_dir)
    as_of = dt.datetime.combine(end, dt.time(23, 59, 59), tzinfo=dt.timezone.utc)
    snoozed = _snoozed_keys(data_dir, as_of)
    call_totals: dict = {}

    out = []
    for sig, rec in stats.items():
        sid = signature_id(sig)
        tool = sig[0]
        if tool not in call_totals:
            call_totals[tool] = _calls(data_dir, tool, start, end)
        calls = call_totals[tool]
        excluded = None
        if sig[2] == UNKNOWN:
            excluded = "unknown"
        elif sid in covered:
            excluded = "covered"
        elif sid in snoozed or "|".join(sig) in snoozed:
            excluded = "snoozed"
        meets = (rec["count"] >= cfg["min_occurrences"]
                 and len(rec["sessions"]) >= cfg["min_sessions"]
                 and len(rec["days"]) >= cfg["min_days"])
        item = {
            "signature_id": sid,
            "tool_name": sig[0],
            "cmd_head": sig[1],
            "error_class": sig[2],
            "count": rec["count"],
            "sessions": len(rec["sessions"]),
            "repos": len(rec["repos"]),
            "days": len(rec["days"]),
            "first_seen": rec["first"],
            "last_seen": rec["last"],
            "calls": calls,
            "rate_per_100_calls": _rate(rec["count"], calls),
            "samples": list(rec["samples"])[-MAX_SAMPLES:],
            "qualifies": meets and excluded is None,
        }
        if excluded:
            item["excluded"] = excluded
        out.append(item)
    out.sort(key=lambda s: (-s["count"] * s["sessions"], s["signature_id"]))

    ints = [{"tool_name": t, "count": r["count"], "sessions": len(r["sessions"]),
             "days": len(r["days"])} for t, r in sorted(interrupts.items())]
    return {
        "date": end.isoformat(),
        "window_start": start.isoformat(),
        "window_days": cfg["window_days"],
        "bar": {k: cfg[k] for k in ("min_occurrences", "min_sessions", "min_days")},
        "signatures": out,
        "interrupts": ints,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="window end, YYYY-MM-DD (default: today UTC)")
    args = ap.parse_args(argv)
    try:
        end = (dt.date.fromisoformat(args.date) if args.date
               else dt.datetime.now(dt.timezone.utc).date())
    except ValueError:
        print("autoheal-aggregate: --date must be YYYY-MM-DD", file=sys.stderr)
        return 2
    data_dir = autoheal_dir()
    result = aggregate(data_dir, end, load_config(data_dir))
    out_dir = os.path.join(data_dir, "signatures")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, end.isoformat() + ".json")
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, out_path)
    qualifying = sum(1 for s in result["signatures"] if s["qualifies"])
    print(f"autoheal-aggregate: {len(result['signatures'])} signatures, "
          f"{qualifying} qualify -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
