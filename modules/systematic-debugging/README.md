# systematic-debugging

4-phase root cause investigation methodology for debugging.

## What It Does

Installs a rules file that enforces structured debugging instead of random fix attempts:

1. **Root Cause Investigation** - Read errors, reproduce consistently, examine changes, add instrumentation
2. **Pattern Analysis** - Find working examples, compare systematically, understand dependencies
3. **Hypothesis Testing** - Form specific hypothesis, test with minimal change, verify result
4. **Implementation** - Write failing test, implement single fix, verify all tests pass

Includes a three-strike rule: after 3 failed fix attempts, stop and question the architecture.

The parent rule is backed by three focused sub-rules that give agents named moves during Phase 1-2:

- **Root Cause Tracing** - trace errors backward up the call chain to the originating trigger, not the surface symptom
- **Defense-in-Depth Validation** - once the origin is found, add validation at every layer the bad value passed through so the same class of bug is structurally impossible
- **Condition-Based Waiting** - replace arbitrary `sleep(N)` with `waitFor(condition)` to eliminate timing-based flaky tests

## Manual Installation

```bash
# Global (all projects)
cp rules/systematic-debugging.md ~/.claude/rules/systematic-debugging.md
cp rules/debugging.md ~/.claude/rules/debugging.md
cp rules/root-cause-tracing.md ~/.claude/rules/root-cause-tracing.md
cp rules/defense-in-depth.md ~/.claude/rules/defense-in-depth.md
cp rules/condition-based-waiting.md ~/.claude/rules/condition-based-waiting.md

# Project-level
cp rules/systematic-debugging.md .claude/rules/systematic-debugging.md
cp rules/debugging.md .claude/rules/debugging.md
cp rules/root-cause-tracing.md .claude/rules/root-cause-tracing.md
cp rules/defense-in-depth.md .claude/rules/defense-in-depth.md
cp rules/condition-based-waiting.md .claude/rules/condition-based-waiting.md
```

## Files

| File | Description |
|------|-------------|
| `rules/systematic-debugging.md` | 4-phase debugging methodology with red flags and escalation rules |
| `rules/debugging.md` | Trigger guide for the `/debug` skill |
| `rules/root-cause-tracing.md` | Trace errors backward up the call chain to the originating trigger |
| `rules/defense-in-depth.md` | Layered validation that makes a fixed bug structurally impossible to reintroduce |
| `rules/condition-based-waiting.md` | Replace arbitrary sleeps with condition polling to kill flaky tests |
