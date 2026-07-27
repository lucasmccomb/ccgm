#!/usr/bin/env python3
"""SessionStart hook: keep this clone's `.env.clone` true to its own path.

`.env.clone` used to be written once at clone-creation time and never checked
again, so a copied or hand-edited file stayed wrong forever -- and every
consumer (port allocation, agent-id tracking) believed it. This hook closes
that loop: on every session start or resume, the clone's identity is re-derived
from its absolute path plus ~/.claude/port-registry.json, and the file is
rewritten if it disagrees.

Safety posture -- this hook is deliberately narrow:

  * It only ever touches `.env.clone`, and only inside a directory whose path
    matches the workspace or flat-clone layout. A standalone checkout, a
    worktree, or any other cwd is a no-op.
  * A repo missing from the port registry is left alone. Writing a fallback
    base port would invent an allocation and collide with a real one.
  * Unknown keys in an existing file are preserved verbatim.
  * Any unexpected failure is swallowed. A session must never fail to start
    because a config file could not be normalized.

It prints one line only when it actually changed something, so a healthy
clone starts silently.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))


def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    # Fires on startup and resume. Unlike context-injection hooks there is no
    # prefix-cache concern here: the common case writes nothing and prints
    # nothing, and a drifted file should be fixed at the first opportunity.
    if hook_input.get("source", "startup") not in ("startup", "resume"):
        return

    cwd = hook_input.get("cwd") or os.getcwd()

    try:
        import clone_identity
    except ImportError:
        return

    try:
        result = clone_identity.repair_clone(cwd)
    except Exception:
        return

    if result.get("status") != "repaired":
        return

    drift = result.get("drift", {})
    changes = ", ".join(
        f"{key} {info['current']!r} -> {info['expected']!r}"
        for key, info in sorted(drift.items())
    )
    sys.stdout.write(
        f"<clone-identity-repaired>\n"
        f"{Path(cwd).name}/.env.clone disagreed with its own path and was "
        f"rewritten from the clone path + ~/.claude/port-registry.json.\n"
        f"Corrected: {changes}\n"
        f"This clone is {result['agent_id']}; frontend port "
        f"{result.get('frontend_port')}, backend port {result.get('backend_port')}.\n"
        f"</clone-identity-repaired>\n"
    )


if __name__ == "__main__":
    main()
