#!/usr/bin/env python3
"""
CCGM /audit pack-to-worker load balancer (Epic 1.7b).

Reads the registry-selected packs JSON (from stdin or a file argument) and
outputs a JSON mapping worker ids (1..N) to ordered pack-id lists.

Usage
-----
  assign-packs.py [selected-packs.json] [--workers N]

  selected-packs.json   Path to the JSON file produced by registry.py.
                        If omitted, reads from stdin.
  --workers N           Number of workers to distribute across (default: 4).
                        Must be >= 1.

Output
------
  {
    "0": ["pack/id-a", "pack/id-b"],
    "1": ["pack/id-c"],
    "2": [],
    "3": []
  }

  Keys are string integers 0..N-1 (JSON object keys are always strings).
  Workers with no packs get an empty list -- the caller should launch only
  workers whose list is non-empty.

Algorithm
---------
  1. Sort packs by (checks_count DESC, pack_id ASC) for a stable weight proxy.
     More checks = more work; alphabetical tiebreak = deterministic.
  2. Assign greedily to the currently lightest worker (lowest current load).
     Ties in load -> lowest worker id wins.

  Same input always produces byte-identical output.

Exit codes
----------
  0  success
  1  input error (bad JSON, missing keys)
"""

import json
import sys


def _parse_args(argv: list) -> tuple:
    """
    Parse argv[1:] and return (input_path_or_none, num_workers).
    Raises SystemExit(1) on bad arguments.
    """
    workers = 4
    input_path = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--workers":
            i += 1
            if i >= len(argv):
                print("ERROR: --workers requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                workers = int(argv[i])
            except ValueError:
                print(f"ERROR: --workers value must be an integer, got {argv[i]!r}",
                      file=sys.stderr)
                sys.exit(1)
            if workers < 1:
                print(f"ERROR: --workers must be >= 1, got {workers}", file=sys.stderr)
                sys.exit(1)
        elif arg.startswith("--"):
            print(f"ERROR: unknown flag {arg!r}", file=sys.stderr)
            sys.exit(1)
        else:
            if input_path is not None:
                print("ERROR: at most one positional argument (input file) allowed",
                      file=sys.stderr)
                sys.exit(1)
            input_path = arg
        i += 1
    return input_path, workers


def _load_packs(input_path) -> list:
    """Load and validate the selected-packs JSON. Returns the list of pack dicts."""
    if input_path is not None:
        try:
            with open(input_path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"ERROR: cannot read {input_path!r}: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        raw = sys.stdin.read()

    try:
        packs = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: input is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(packs, list):
        print("ERROR: input must be a JSON array of pack objects", file=sys.stderr)
        sys.exit(1)

    for i, p in enumerate(packs):
        if not isinstance(p, dict):
            print(f"ERROR: packs[{i}] is not an object", file=sys.stderr)
            sys.exit(1)
        if "id" not in p:
            print(f"ERROR: packs[{i}] missing required 'id' field", file=sys.stderr)
            sys.exit(1)

    return packs


def assign_packs(packs: list, num_workers: int) -> dict:
    """
    Greedy load-balanced assignment.

    Returns a dict: {worker_id_str: [pack_id, ...]} for worker ids 0..N-1.
    Workers with no packs get an empty list.

    Sorting key: (checks_count DESC, pack_id ASC)
    Assignment: greedily to the lightest worker; ties -> lowest worker id.
    """
    # Sort packs for deterministic assignment: most checks first, alpha tiebreak
    sorted_packs = sorted(
        packs,
        key=lambda p: (-len(p.get("checks", [])), p.get("id", "")),
    )

    # Worker loads: keyed by index 0..N-1
    worker_loads = [0] * num_workers       # current load (check count)
    worker_packs = [[] for _ in range(num_workers)]   # assigned pack ids

    for pack in sorted_packs:
        pack_id = pack["id"]
        pack_weight = len(pack.get("checks", []))

        # Find the lightest worker; break ties by lowest index (= lowest worker id)
        lightest = 0
        for idx in range(1, num_workers):
            if worker_loads[idx] < worker_loads[lightest]:
                lightest = idx

        worker_packs[lightest].append(pack_id)
        worker_loads[lightest] += pack_weight

    # Build output dict with 0-based string keys (JSON object keys are strings)
    result = {}
    for idx in range(num_workers):
        result[str(idx)] = worker_packs[idx]

    return result


def main(argv: list) -> int:
    input_path, num_workers = _parse_args(argv)
    packs = _load_packs(input_path)
    assignment = assign_packs(packs, num_workers)
    print(json.dumps(assignment, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
