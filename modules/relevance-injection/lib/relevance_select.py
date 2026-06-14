#!/usr/bin/env python3
"""Deterministic relevance-scoped rule selection for CCGM.

This is the pure, side-effect-free core of the opt-in relevance-injection
feature (issue #695). It answers one question:

    Given the installed modules and an (optional) task profile, which rule
    files should be surfaced for this session?

It does NOT read stdin, write files, or touch the network. The SessionStart
hook (relevance-inject.py) wires this library to Claude Code; everything that
can be tested in isolation lives here.

Design invariants (each pinned by a test in tests/):

  1. SAFETY CORE IS ALWAYS INCLUDED. Regardless of profile, the always-on
     minimal core (safety/permissions, confusion-protocol, TDD, verification,
     autonomy, ...) is selected. A bad profile can never drop an Iron Law.

  2. ABSENT `applicability` == ALWAYS. A module with no `applicability` field
     in its module.json is treated as always-applicable. This preserves
     today's behavior: before this feature, every installed rule loaded
     unconditionally, so the default for an unclassified module must remain
     "load it."

  3. EXPLICIT {"always": true} == ALWAYS. Same as absent, but declared.

  4. SELECTION IS DETERMINISTIC. Same inputs -> same ordered output. No
     randomness, no clock, no filesystem ordering leaking through. Output is
     sorted by (tier, module, file) so two runs are byte-identical.

The hook only ever calls this library when an explicit opt-in flag is set.
When the flag is unset the hook no-ops and Claude Code's normal
all-rules-always-loaded path is completely untouched. This library is dead
code in the default configuration; it cannot change default behavior.
"""
from __future__ import annotations

import json
import os
from typing import Iterable


# ---------------------------------------------------------------------------
# Safety core tiering.
#
# The tier ordering is the AUTHORITATIVE precedence for the always-on minimal
# core. It is documented in rules/relevance-injection.md as well; keep the two
# in sync. Lower tier number == higher precedence == surfaced first.
#
# These modules are ALWAYS selected, regardless of their module.json
# `applicability` field and regardless of the task profile. They are the Iron
# Laws that must hold in every session. Listing a module here is a deliberate
# statement that the rule is non-negotiable safety/discipline, not
# situational guidance.
# ---------------------------------------------------------------------------
SAFETY_CORE_TIERS: "list[list[str]]" = [
    # Tier 0 — safety / permissions / git-history protection. Highest precedence.
    ["git-workflow", "hooks"],
    # Tier 1 — confusion protocol: stop and ask at architectural forks.
    ["autonomy"],
    # Tier 2 — TDD + verification: no code without a failing test; no claim
    #          without fresh evidence.
    ["test-driven-development", "verification"],
    # Tier 3 — everything else in the core that should never be scoped away.
    ["systematic-debugging", "subagent-patterns"],
]


def safety_core_modules() -> "list[str]":
    """Flat, precedence-ordered list of the always-on core module names."""
    flat: "list[str]" = []
    for tier in SAFETY_CORE_TIERS:
        flat.extend(tier)
    return flat


def safety_core_tier(module: str) -> int:
    """Tier index for a core module, or a large sentinel for non-core.

    Used as the primary sort key so core rules sort ahead of situational
    rules and in their declared precedence order.
    """
    for idx, tier in enumerate(SAFETY_CORE_TIERS):
        if module in tier:
            return idx
    return len(SAFETY_CORE_TIERS) + 1


def is_safety_core(module: str) -> bool:
    """True iff `module` is part of the always-on safety core."""
    return safety_core_tier(module) <= len(SAFETY_CORE_TIERS)


# ---------------------------------------------------------------------------
# Applicability matching.
# ---------------------------------------------------------------------------
def _as_lower_set(values: "Iterable[str] | None") -> "set[str]":
    if not values:
        return set()
    return {str(v).strip().lower() for v in values if str(v).strip()}


def module_is_applicable(
    applicability: "dict | None",
    langs: "Iterable[str] | None" = None,
    task_types: "Iterable[str] | None" = None,
) -> bool:
    """Decide whether a module's rules apply to a given task profile.

    Rules (in order):

      * `applicability` is None or {} or {"always": true}  -> ALWAYS applies.
        (Backward-compat: an unclassified module loaded unconditionally
        before this feature, so it must continue to.)

      * Otherwise the module declares `langs` and/or `taskTypes` constraints.
        The module applies if the profile INTERSECTS any declared dimension:
          - if `langs` is declared, a profile lang in it makes it applicable;
          - if `taskTypes` is declared, a profile task type in it makes it
            applicable.
        Matching is OR across dimensions: a Python file (lang match) pulls in
        a module even if the task type does not match its taskTypes, and vice
        versa. This is deliberately permissive — over-inclusion is safe
        (you see a rule you did not strictly need); under-inclusion risks
        dropping a relevant discipline.

      * A module that declares constraints but matches NOTHING in the profile
        is excluded. This is the only case where a rule is dropped, and it can
        only ever apply to a module that explicitly opted out of "always".

    `applicability` shape:
        {"always": true}
        {"langs": ["python", "typescript"]}
        {"taskTypes": ["frontend", "css"]}
        {"langs": ["python"], "taskTypes": ["backend"]}
    """
    if not applicability:
        return True
    if applicability.get("always") is True:
        return True

    declared_langs = _as_lower_set(applicability.get("langs"))
    declared_tasks = _as_lower_set(applicability.get("taskTypes"))

    # A malformed entry with neither dimension is treated as "always" rather
    # than silently dropping the rule — fail safe toward inclusion.
    if not declared_langs and not declared_tasks:
        return True

    profile_langs = _as_lower_set(langs)
    profile_tasks = _as_lower_set(task_types)

    if declared_langs and (profile_langs & declared_langs):
        return True
    if declared_tasks and (profile_tasks & declared_tasks):
        return True
    return False


# ---------------------------------------------------------------------------
# module.json reading (the only filesystem touch; still no stdin/network).
# ---------------------------------------------------------------------------
def read_module_manifest(modules_dir: str, module: str) -> "dict | None":
    """Load modules/<module>/module.json, or None if absent/unparseable."""
    path = os.path.join(modules_dir, module, "module.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def rule_files_for_module(manifest: "dict | None") -> "list[str]":
    """Return the target paths of all type=='rule' files in a manifest."""
    if not manifest:
        return []
    files = manifest.get("files")
    if not isinstance(files, dict):
        return []
    out: "list[str]" = []
    for entry in files.values():
        if isinstance(entry, dict) and entry.get("type") == "rule":
            target = entry.get("target")
            if isinstance(target, str) and target:
                out.append(target)
    return sorted(out)


# ---------------------------------------------------------------------------
# Top-level selection.
# ---------------------------------------------------------------------------
def select_modules(
    installed_modules: "Iterable[str]",
    modules_dir: str,
    langs: "Iterable[str] | None" = None,
    task_types: "Iterable[str] | None" = None,
) -> "list[str]":
    """Return the deterministic, precedence-ordered set of selected modules.

    A module is selected if EITHER:
      * it is part of the safety core (always), OR
      * its `applicability` matches the profile (absent/always counts as
        matching everything).

    Output ordering: safety-core tier first (by precedence), then everything
    else alphabetically. Always deduplicated.
    """
    installed = list(dict.fromkeys(installed_modules))  # de-dup, keep order
    selected: "set[str]" = set()

    for module in installed:
        if is_safety_core(module):
            selected.add(module)
            continue
        manifest = read_module_manifest(modules_dir, module)
        applicability = None
        if manifest:
            ap = manifest.get("applicability")
            applicability = ap if isinstance(ap, dict) else None
        if module_is_applicable(applicability, langs=langs, task_types=task_types):
            selected.add(module)

    return sorted(
        selected,
        key=lambda m: (safety_core_tier(m), m),
    )


def select_rule_files(
    installed_modules: "Iterable[str]",
    modules_dir: str,
    langs: "Iterable[str] | None" = None,
    task_types: "Iterable[str] | None" = None,
) -> "list[tuple[str, str]]":
    """Return [(module, rule_target_path), ...] for the selected modules.

    Deterministic: ordered by (safety-core tier, module, rule file).
    """
    out: "list[tuple[str, str]]" = []
    for module in select_modules(
        installed_modules, modules_dir, langs=langs, task_types=task_types
    ):
        manifest = read_module_manifest(modules_dir, module)
        for target in rule_files_for_module(manifest):
            out.append((module, target))
    return out
