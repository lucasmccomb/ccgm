#!/usr/bin/env python3
"""auto_apply.py - the nightly auto-apply step (#1099 Phase 4.2).

bin/autoheal-auto-apply.sh runs this after the analyzer. The mode comes from
`auto_apply_mode` (lib/autoheal_mode.py):

  off     nothing runs.
  shadow  every ready rule_insert row gets a decision (would apply or not, with
          the reason) appended to ~/.claude/autoheal/shadow/auto-apply.jsonl.
          No git, gh or ledger change. Harmful measured fixes are only listed.
  active  first, each measured-harmful fix is reverted through
          `autoheal-review.py revert`'s machinery (a revert PR, checked and
          squash-merged); then each row that passes the gate is applied through
          `/autoheal-review`'s apply path (PR with Autoheal-Id and
          Autoheal-Signature trailers, checks, squash-merge) and marked
          applied_by auto. Decisions are still logged.

The gate (every check must pass):
  kind == rule_insert
  >= MIN_OCCURRENCES occurrences across >= MIN_SESSIONS sessions (row evidence)
  target matches a glob in config `auto_apply_targets` (empty: nothing qualifies)
  validate() from lib/apply-proposal.py passes against origin/main

Before anything else, 3 reverts within 30 days demote active to shadow
(autoheal_mode.maybe_demote). After the decisions, the run logs the agreement
between shadow decisions and /autoheal-review outcomes.

A revert that fails (no trailer commit, conflict, checks) records revert_error
on the row and is not retried automatically; `/autoheal-review revert <id>`
retries it.

Usage: auto_apply.py [--log FILE]      always exits 0
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import sys

MIN_OCCURRENCES = 10
MIN_SESSIONS = 3
TARGETS_KEY = "auto_apply_targets"

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mode():
    return _load(os.path.join(_HERE, "autoheal_mode.py"), "autoheal_mode_lib")


def _ledger():
    return _load(os.path.join(_HERE, "ledger.py"), "autoheal_ledger")


def _review():
    return _load(os.path.join(_HERE, "..", "bin", "autoheal-review.py"), "autoheal_review")


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def gate(row: dict, cfg: dict, validate) -> tuple[bool, str]:
    """(would apply, reason). `validate(row)` returns (ok, reason) like apply-proposal.validate."""
    if row.get("kind") != "rule_insert":
        return False, f"kind {row.get('kind')!r} is not rule_insert"
    ev = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    count = _int(ev.get("count", row.get("occurrence_count")))
    sessions = _int(ev.get("sessions"))
    if count is None or count < MIN_OCCURRENCES:
        return False, f"{count} occurrences; needs {MIN_OCCURRENCES}"
    if sessions is None or sessions < MIN_SESSIONS:
        return False, f"{sessions} sessions; needs {MIN_SESSIONS}"
    targets = cfg.get(TARGETS_KEY)
    patterns = [p for p in targets if isinstance(p, str) and p] if isinstance(targets, list) else []
    target = row.get("target") or ""
    if not patterns:
        return False, f"target {target} not in {TARGETS_KEY} (the allowlist is empty)"
    if not any(fnmatch.fnmatchcase(target, p) for p in patterns):
        return False, f"target {target} not in {TARGETS_KEY}"
    ok, reason = validate(row)
    if not ok:
        return False, f"validate() failed: {reason}"
    return True, "passed every gate"


def run(log) -> dict:
    mode_lib = _mode()
    cfg_path = mode_lib.config_path()
    summary = {"mode": "off", "evaluated": 0, "would_apply": 0, "applied": 0, "failed": 0,
               "reverted": 0, "revert_failed": 0}

    demoted = mode_lib.maybe_demote(cfg_path)
    if demoted:
        log(demoted)
    cfg = mode_lib._load_config(cfg_path)
    mode, note = mode_lib.effective_auto_apply_mode(cfg)
    summary["mode"] = mode
    if mode == mode_lib.MODE_OFF:
        log("auto_apply_mode=off; skipping")
        return summary
    if note:
        log(note)

    led = _ledger()
    review = _review()
    harmful = [r for r in led.read_rows() if r.get("state") == "measured" and r.get("outcome") == "harmful"]
    for row in harmful:
        if mode != mode_lib.MODE_ACTIVE:
            log(f"harmful {row.get('id')}: flagged in the session notice; {mode} mode does not revert")
            continue
        if row.get("revert_error"):
            log(f"harmful {row.get('id')}: earlier revert failed ({row['revert_error']}); "
                "not retried automatically, run /autoheal-review revert")
            continue
        reason = (f"The fix measured harmful at +14 days: {row.get('baseline_rate')} -> "
                  f"{row.get('post_rate')} failures per 100 calls"
                  + (f"; new signatures {', '.join(row['new_signatures'])}" if row.get("new_signatures") else "")
                  + ".")
        res = review.revert_row(led, row, reason, "auto")
        if res.get("ok"):
            summary["reverted"] += 1
            log(f"reverted {row['id']}: {res.get('revert_pr_url')}")
        else:
            summary["revert_failed"] += 1
            log(f"revert {row['id']} failed: {res.get('error')}")
    if summary["reverted"]:
        demoted = mode_lib.maybe_demote(cfg_path)
        if demoted:
            log(demoted)
            mode = summary["mode"] = mode_lib.MODE_SHADOW

    apply_lib = _load(os.path.join(_HERE, "apply-proposal.py"), "autoheal_apply")
    try:
        root, how = _load(os.path.join(_HERE, "module-index.py"), "autoheal_module_index").resolve_source_repo()
    except Exception as exc:  # noqa: BLE001 -- the gate then fails as validation_unavailable
        root, how = None, str(exc)
    if root is None:
        log(f"source repo not found ({how}); validate() will fail every row")

    def validate(row):
        return apply_lib.validate(row, repo_root=root) if root else (False, "validation_unavailable")

    for row in led.ready_rows(mode_lib.now_utc()):
        if row.get("kind") != "rule_insert":
            continue
        summary["evaluated"] += 1
        would, reason = gate(row, cfg, validate)
        mode_lib.log_auto_apply_decision(row, would, reason, mode)
        if not would:
            log(f"skip {row.get('id')}: {reason}")
            continue
        summary["would_apply"] += 1
        if mode != mode_lib.MODE_ACTIVE:
            log(f"shadow {row['id']}: would apply; nothing applied")
            continue
        try:
            res = review._apply_rule(led, row, None, "auto")
        except review.Failure as exc:
            res = {"ok": False, "error": str(exc)}
        if res.get("ok"):
            summary["applied"] += 1
            log(f"applied {row['id']}: {res.get('pr_url')}")
        else:
            summary["failed"] += 1
            log(f"apply {row['id']} failed: {res.get('error')}")

    stats = mode_lib.auto_apply_stats(cfg_path)
    pct = f"{stats['agreement']:.0%}" if stats["decided"] else "n/a"
    log(f"agreement {stats['agreed']}/{stats['decided']} ({pct}), pending {stats['pending']}, "
        f"harmful {stats['harmful']}; promotion bar "
        + ("met" if stats["ready_for_active"] else "not met: " + "; ".join(stats["reasons"])))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)

    def log(message: str) -> None:
        line = f"[{_mode().now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')}] {message}"
        print(line, file=sys.stderr)
        if args.log:
            try:
                os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
                with open(args.log, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    try:
        s = run(log)
    except Exception as exc:  # noqa: BLE001 -- one bad night must not fail the daily wrapper
        log(f"auto-apply aborted: {exc!r}")
        return 0
    print(f"autoheal-auto-apply: mode={s['mode']} evaluated={s['evaluated']} would_apply={s['would_apply']} "
          f"applied={s['applied']} failed={s['failed']} reverted={s['reverted']} "
          f"revert_failed={s['revert_failed']}", file=sys.stderr)
    print(json.dumps(s), file=sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
