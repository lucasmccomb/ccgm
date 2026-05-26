#!/usr/bin/env python3
"""Durable loop-state bookkeeping for the Argus convergence loop.

The loop's counters are deterministic arithmetic, so they live in a script, not in the
orchestrator's head (see the latent-vs-deterministic discipline). The skill calls a
subcommand each iteration and reads back a `decision` block; it never tracks
consecutive_passes or per-dimension attempts itself.

state.json shape:
  { feature, target, iteration, consecutive_passes, attempts:{dim:N}, frozen:[dim],
    reference_source }

Subcommands (all take --state PATH):
  init      --feature F --target T [--reference-source human|candidate]
  record    --verdict verdict.json [--rubric rubric.json] [overrides]   (a fresh judge verdict)
  unchanged [--rubric ...] [overrides]   (hash-suppressed confirm; counts as a pass)
  gate-fail [--rubric ...] [overrides]   (deterministic floor failed; resets the streak)
  show
Each mutating subcommand prints the new state plus a `decision` block as JSON.
Exit: 0 ok, 2 on bad input / missing state.
"""
from __future__ import annotations

import argparse
import json
import sys

DEFAULTS = {"required_passes": 2, "max_attempts": 3, "max_iterations": 12}


def _err(msg: str) -> None:
    print(f"loop_state: {msg}", file=sys.stderr)


def load_params(args) -> dict:
    params = dict(DEFAULTS)
    if getattr(args, "rubric", None):
        try:
            with open(args.rubric) as f:
                loop = json.load(f).get("loop", {})
            params["required_passes"] = loop.get("consecutive_passes_required", params["required_passes"])
            params["max_attempts"] = loop.get("max_attempts_per_dimension", params["max_attempts"])
            params["max_iterations"] = loop.get("max_iterations_default", params["max_iterations"])
        except (OSError, json.JSONDecodeError) as e:
            _err(f"cannot read rubric: {e}")
            raise SystemExit(2)
    for key in ("required_passes", "max_attempts", "max_iterations"):
        override = getattr(args, key, None)
        if override is not None:
            params[key] = override
    return params


def read_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _err(f"cannot read state ({e}); run 'init' first")
        raise SystemExit(2)


def write_state(path: str, state: dict) -> None:
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def decide(state: dict, params: dict, newly_frozen=None, fix_dimensions=None) -> dict:
    return {
        "should_signoff": state["consecutive_passes"] >= params["required_passes"],
        "budget_exhausted": state["iteration"] >= params["max_iterations"],
        "consecutive_passes": state["consecutive_passes"],
        "required_passes": params["required_passes"],
        "iteration": state["iteration"],
        "max_iterations": params["max_iterations"],
        "frozen": state["frozen"],
        "newly_frozen": newly_frozen or [],
        "fix_dimensions": fix_dimensions if fix_dimensions is not None else [],
    }


def emit(state: dict, decision: dict) -> int:
    print(json.dumps({"state": state, "decision": decision}, indent=2))
    return 0


def cmd_init(args) -> int:
    state = {
        "feature": args.feature,
        "target": args.target,
        "iteration": 0,
        "consecutive_passes": 0,
        "attempts": {},
        "frozen": [],
        "reference_source": args.reference_source,
    }
    write_state(args.state, state)
    return emit(state, decide(state, load_params(args)))


def cmd_record(args) -> int:
    params = load_params(args)
    state = read_state(args.state)
    try:
        with open(args.verdict) as f:
            verdict = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _err(f"cannot read verdict: {e}")
        return 2

    state["iteration"] += 1
    if verdict.get("reference_source") and not state.get("reference_source"):
        state["reference_source"] = verdict["reference_source"]

    newly_frozen = []
    if verdict.get("all_pass"):
        state["consecutive_passes"] += 1
        fix_dimensions = []
    else:
        state["consecutive_passes"] = 0
        for dim in verdict.get("failed_dimensions", []):
            state["attempts"][dim] = state["attempts"].get(dim, 0) + 1
            if state["attempts"][dim] >= params["max_attempts"] and dim not in state["frozen"]:
                state["frozen"].append(dim)
                newly_frozen.append(dim)
        fix_dimensions = [d for d in verdict.get("failed_dimensions", []) if d not in state["frozen"]]

    write_state(args.state, state)
    return emit(state, decide(state, params, newly_frozen, fix_dimensions))


def cmd_unchanged(args) -> int:
    params = load_params(args)
    state = read_state(args.state)
    state["iteration"] += 1
    state["consecutive_passes"] += 1
    write_state(args.state, state)
    return emit(state, decide(state, params, fix_dimensions=[]))


def cmd_gate_fail(args) -> int:
    params = load_params(args)
    state = read_state(args.state)
    state["iteration"] += 1
    state["consecutive_passes"] = 0
    write_state(args.state, state)
    return emit(state, decide(state, params, fix_dimensions=[]))


def cmd_show(args) -> int:
    state = read_state(args.state)
    return emit(state, decide(state, load_params(args)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Argus loop-state counters.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p, with_rubric=True):
        p.add_argument("--state", required=True)
        if with_rubric:
            p.add_argument("--rubric")
            p.add_argument("--required-passes", dest="required_passes", type=int)
            p.add_argument("--max-attempts", dest="max_attempts", type=int)
            p.add_argument("--max-iterations", dest="max_iterations", type=int)

    p = sub.add_parser("init"); add_common(p)
    p.add_argument("--feature", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--reference-source", dest="reference_source", default=None)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("record"); add_common(p)
    p.add_argument("--verdict", required=True)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("unchanged"); add_common(p); p.set_defaults(func=cmd_unchanged)
    p = sub.add_parser("gate-fail"); add_common(p); p.set_defaults(func=cmd_gate_fail)
    p = sub.add_parser("show"); add_common(p); p.set_defaults(func=cmd_show)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
