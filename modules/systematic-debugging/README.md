# systematic-debugging

4-phase root cause investigation methodology for debugging.

`rules/condition-based-waiting.md` is path-scoped (#1061): it carries `paths:` frontmatter and loads only after Claude reads a file matching one of `**/*.test.*`, `**/*.spec.*`, `**/tests/**`, `**/test/**`, `**/__tests__/**`, `**/e2e/**`. It costs no context at session start otherwise.

## What It Does

Installs a rules file that enforces structured debugging instead of random fix attempts:

1. **Root Cause Investigation** - Read errors, reproduce consistently, examine changes, add instrumentation
2. **Pattern Analysis** - Find working examples, compare systematically, understand dependencies
3. **Hypothesis Testing** - Form specific hypothesis, test with minimal change, verify result
4. **Implementation** - Write failing test, implement single fix, verify all tests pass

Includes a three-strike rule: after 3 failed fix attempts, stop and question the architecture.

The parent rule is backed by four focused sub-rules that give agents named moves during Phase 1-2:

- **Root Cause Tracing** - trace errors backward up the call chain to the originating trigger, not the surface symptom
- **Defense-in-Depth Validation** - once the origin is found, add validation at every layer the bad value passed through so the same class of bug is structurally impossible
- **Condition-Based Waiting** - replace arbitrary `sleep(N)` with `waitFor(condition)` to eliminate timing-based flaky tests
- **Animals vs Ghosts** - name which RL circuit a task falls in before diagnosing a stuck agent, so degraded output reads as a distribution gap, not defiance

## Manual Installation

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/systematic-debugging.md ~/.claude/rules/systematic-debugging.md
mkdir -p ~/.claude/skills
cp -R skills/debugging-techniques ~/.claude/skills/debugging-techniques
cp rules/condition-based-waiting.md ~/.claude/rules/condition-based-waiting.md

# Project-level
mkdir -p .claude/rules
cp rules/systematic-debugging.md .claude/rules/systematic-debugging.md
cp rules/condition-based-waiting.md .claude/rules/condition-based-waiting.md
```

## Files

| File | Description |
|------|-------------|
| `rules/systematic-debugging.md` | 4-phase debugging methodology with red flags and escalation rules |
| `skills/debugging-techniques/SKILL.md` | Root-cause tracing, defense-in-depth validation, and the animals-vs-ghosts mental model, loaded on demand during debugging |
| `rules/condition-based-waiting.md` | Replace arbitrary sleeps with condition polling to kill flaky tests |
