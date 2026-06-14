#!/usr/bin/env python3
"""Single-process PreToolUse:Bash dispatcher (composition entry point).

This is the BACKWARD-COMPATIBLE composition layer for the PreToolUse:Bash
event. It replaces the six-process legacy chain
(enforce-git-workflow → auto-approve-bash → port-check → agent-tracking-pre
→ check-migration-timestamps → check-careful) with ONE process that runs the
same checks in-process, by priority, through hook_dispatcher.

It is OPT-IN. The default install keeps the legacy per-process chain registered
in settings.partial.json. Migrating a deployment means replacing those six
PreToolUse:Bash entries with this single entry — the decisions are identical
because the handlers (lib/pretooluse_bash_checks.py) call the legacy hooks'
own pure functions; the dispatcher only resolves precedence.

DECLARATIVE MANIFEST (priority order mirrors the legacy registration order).
Precedence among the decisions they return is governed by hook_dispatcher's
DECISION_RANK: hard_block > deny > allow > ask. The curated destructive set is
short_circuit so it is emitted the instant it fires, nothing can soften it.

  priority  check                       decision kinds       bypass-safe  short
  --------  --------------------------  -------------------  -----------  -----
  10        git_workflow_check          hard_block / adv     yes          no
  20        destructive_check           hard_block           yes          YES
  30        smart_rules_check           hard_block / allow   yes          YES
  40        port_advisory_check         advisory             no           no
  50        agent_tracking_check        advisory             no           no
  60        migration_timestamp_check   hard_block           yes          no
  70        force_push_main_check       hard_block           yes          no
  80        careful_check               ask                  no           no
  90        pattern_check               deny / allow         no           no

bypass-safe=no means the dispatcher skips it in bypass mode, exactly as the
legacy hook exits 0 before its suppressible logic when is_bypass_mode() is
true. bypass-safe=yes means it runs even in bypass mode (the only path that
can produce a bypass-proof exit-2 block).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_dispatcher as hd  # noqa: E402
import pretooluse_bash_checks as checks  # noqa: E402


def build_manifest() -> "hd.Manifest":
    """Construct the declarative PreToolUse:Bash manifest."""
    bash_only = hd.tool_matcher("Bash")
    m = hd.Manifest(event="PreToolUse")
    m.add(hd.Check(10, "git_workflow", bash_only, checks.git_workflow_check,
                   runs_in_bypass=True, short_circuit=False))
    m.add(hd.Check(20, "destructive", bash_only, checks.destructive_check,
                   runs_in_bypass=True, short_circuit=True))
    m.add(hd.Check(30, "smart_rules", bash_only, checks.smart_rules_check,
                   runs_in_bypass=True, short_circuit=True))
    m.add(hd.Check(40, "port_advisory", bash_only, checks.port_advisory_check,
                   runs_in_bypass=False, short_circuit=False))
    m.add(hd.Check(50, "agent_tracking", bash_only, checks.agent_tracking_check,
                   runs_in_bypass=False, short_circuit=False))
    m.add(hd.Check(60, "migration_timestamp", bash_only, checks.migration_timestamp_check,
                   runs_in_bypass=True, short_circuit=False))
    m.add(hd.Check(70, "force_push_main", bash_only, checks.force_push_main_check,
                   runs_in_bypass=True, short_circuit=False))
    m.add(hd.Check(80, "careful", bash_only, checks.careful_check,
                   runs_in_bypass=False, short_circuit=False))
    m.add(hd.Check(90, "pattern", bash_only, checks.pattern_check,
                   runs_in_bypass=False, short_circuit=False))
    return m


def main() -> None:
    hd.dispatch(build_manifest())


if __name__ == "__main__":
    main()
