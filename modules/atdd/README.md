# ATDD Module

Agentic Test-Driven Development - build app code to pass E2E vision specs.

## What is ATDD?

ATDD is TDD applied at the E2E level for agent-driven development. Instead of writing code and then testing it, vision specs (Playwright test files) define the target behavior first, and agents iteratively build app code until all specs pass.

The cycle:
1. Vision specs exist (Playwright tests describing what the app SHOULD do)
2. Agent reads specs to understand expected behavior
3. Agent runs specs, sees what fails
4. Agent implements app code (never modifies specs)
5. Agent re-runs, sees progress
6. Repeat until all green
7. Commit, push, PR

## Usage

```bash
/atdd habits                     # Build code to pass habits vision specs
/atdd habits --issue 178         # Use existing issue
/atdd coaching --issue 180       # Build coaching feature
/atdd "principles journal"       # Multi-word feature name
```

## The ATDD Contract

- **Specs are immutable** - never modify test files during an ATDD run
- **Mocks are the API contract** - mock response shapes define the expected API format
- **UI expectations are the design spec** - test assertions define the UX
- **Work incrementally** - one failing test at a time, commit every 5-10 tests

## Expected Directory Structure

The command expects Playwright vision specs organized by feature:

```
e2e/
  fixtures/           # Shared test fixtures (mocks, helpers, personas)
  tests/
    auth/             # Auth feature vision specs
      login.spec.ts
      signup.spec.ts
    habits/           # Habits feature vision specs
      create.spec.ts
      list.spec.ts
      edit.spec.ts
    coaching/         # Coaching feature vision specs
      ...
```

## Relationship to Other Commands

- **`/test-vision`** - generates comprehensive vision specs for a repo (run this first)
- **`/e2e`** - generates a single feature's vision spec
- **`/atdd`** - consumes vision specs to build app code (run this after specs exist)

Pipeline: `/test-vision` or `/e2e` (write specs) -> `/atdd` (build code to pass specs)

## Manual Installation

1. Copy `commands/atdd.md` to `~/.claude/commands/atdd.md`
2. Copy `rules/atdd.md` to `~/.claude/rules/atdd.md`
