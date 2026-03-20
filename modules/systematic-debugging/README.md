# systematic-debugging

4-phase root cause investigation methodology for debugging.

## What It Does

Installs a rules file that enforces structured debugging instead of random fix attempts:

1. **Root Cause Investigation** - Read errors, reproduce consistently, examine changes, add instrumentation
2. **Pattern Analysis** - Find working examples, compare systematically, understand dependencies
3. **Hypothesis Testing** - Form specific hypothesis, test with minimal change, verify result
4. **Implementation** - Write failing test, implement single fix, verify all tests pass

Includes a three-strike rule: after 3 failed fix attempts, stop and question the architecture.

## Manual Installation

```bash
# Global (all projects)
cp rules/systematic-debugging.md ~/.claude/rules/systematic-debugging.md

# Project-level
cp rules/systematic-debugging.md .claude/rules/systematic-debugging.md
```

## Files

| File | Description |
|------|-------------|
| `rules/systematic-debugging.md` | 4-phase debugging methodology with red flags and escalation rules |
