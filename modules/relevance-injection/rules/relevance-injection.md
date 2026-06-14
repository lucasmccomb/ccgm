# Relevance-Scoped Rule Injection + Tiered Safety Core

CCGM installs every selected module's rule files to `~/.claude/rules/`, where
Claude Code auto-loads all of them on every session. With a full install that
is a large, always-on token load. This module provides an **opt-in,
backward-compatible** way to scope rule attention to the current task while
guaranteeing the safety core is always present.

**This is opt-in. With the feature off (the default), nothing changes.** All
rules load exactly as before.

## The Tiered Safety Core (authoritative precedence)

The Iron Laws are not a flat list. When two disciplines could conflict, this
ordering is authoritative. The always-on minimal core is surfaced in this
precedence and is **never** scoped away by relevance selection, regardless of
task profile:

| Tier | Modules | Why it is non-negotiable |
|------|---------|--------------------------|
| 0 — safety / permissions | `git-workflow`, `hooks` | History-altering git safety, protected-branch enforcement, permission gating. A breach here is irreversible or destructive. |
| 1 — confusion protocol | `autonomy` | Stop and ask at architectural forks; do not guess on high-stakes ambiguity. Prevents wrong-direction work that the lower tiers would then faithfully execute. |
| 2 — TDD + verification | `test-driven-development`, `verification` | No production code without a failing test; no completion claim without fresh evidence. These gate correctness. |
| 3 — debugging + delegation discipline | `systematic-debugging`, `subagent-patterns` | Root cause before fix; spec + status protocol for delegated work. |

Read top-down: a Tier-0 safety rule wins over a Tier-2 convenience. "Violating
the letter of a rule is violating the spirit" applies most strongly at the top
of this table.

The machine-readable form of this ordering lives in
`lib/relevance_select.py` (`SAFETY_CORE_TIERS`). Keep the two in sync.

## How selection works

Each module's `module.json` may carry an optional `applicability` field
(schema: `lib/applicability-schema.json`):

- **Absent** or `{"always": true}` — the module's rules are always surfaced.
  This is the backward-compatible default: a module that does not declare
  applicability behaves exactly as it did before this feature existed.
- `{"langs": [...]}` and/or `{"taskTypes": [...]}` — the module is surfaced
  only when the session's profile intersects a declared dimension. Matching is
  OR across dimensions and deliberately permissive: over-inclusion is safe,
  under-inclusion would risk dropping a relevant discipline.

The safety core (above) is always selected even if a core module declared an
`applicability` constraint — core membership wins.

## Enabling the feature

Strictly opt-in via `~/.claude/.ccgm.env`:

```
CCGM_RELEVANCE_INJECTION=true
CCGM_RELEVANCE_LANGS=python,typescript      # optional task profile
CCGM_RELEVANCE_TASKTYPES=backend,testing    # optional task profile
```

With the flag set, the `SessionStart` hook emits a short pointer
(`additionalContext`) listing the safety core plus the profile-relevant
modules. The rule files themselves remain on disk and loadable — the pointer
biases routing, it does not gate access. With the flag unset, the hook is a
no-op.

## Why a pointer, not file removal

This module never deletes or relocates rule files and never disables the
auto-load path. It is additive: the most it can do is inject one extra block
of context. That property is what makes the feature safe to ship without
changing default behavior or risking an existing install.
