# code-quality

Code standards, testing requirements, error handling patterns, security practices, build verification, and living documents maintenance.

## What It Does

This module installs a rules file that instructs Claude to:

- Follow consistent code standards (environment variables, database migrations, dependencies, component patterns, path aliases)
- Write tests for new features, edge cases, bug fixes, and complex logic
- Apply structured error handling patterns for both frontend and backend
- Enforce security practices (input sanitization, upload validation, secrets management, RLS)
- Run full build verification before pushing code
- Maintain living documents (README, project story) after PR merges

## Manual Installation

Copy `rules/code-quality.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/code-quality.md ~/.claude/rules/code-quality.md
cp rules/change-philosophy.md ~/.claude/rules/change-philosophy.md
cp rules/latent-vs-deterministic.md ~/.claude/rules/latent-vs-deterministic.md
cp rules/completeness.md ~/.claude/rules/completeness.md
cp rules/receiving-code-review.md ~/.claude/rules/receiving-code-review.md
cp rules/in-the-circuits.md ~/.claude/rules/in-the-circuits.md
cp rules/spec-is-the-artifact.md ~/.claude/rules/spec-is-the-artifact.md
cp rules/menu-gen-test.md ~/.claude/rules/menu-gen-test.md

# Project-level
cp rules/code-quality.md .claude/rules/code-quality.md
cp rules/change-philosophy.md .claude/rules/change-philosophy.md
cp rules/latent-vs-deterministic.md .claude/rules/latent-vs-deterministic.md
cp rules/completeness.md .claude/rules/completeness.md
cp rules/receiving-code-review.md .claude/rules/receiving-code-review.md
cp rules/in-the-circuits.md .claude/rules/in-the-circuits.md
cp rules/spec-is-the-artifact.md .claude/rules/spec-is-the-artifact.md
cp rules/menu-gen-test.md .claude/rules/menu-gen-test.md
```

## Files

| File | Description |
|------|-------------|
| `rules/code-quality.md` | Rule file covering code standards, testing, error handling, security, build verification, and living documents |
| `rules/change-philosophy.md` | Rule file on elegant integration: redesign existing systems rather than bolting on |
| `rules/latent-vs-deterministic.md` | Rule file on classifying work as latent (judgment) vs deterministic (scripts) and pushing deterministic steps into code |
| `rules/completeness.md` | Rule file on the Boil-the-Lake completeness principle and scoring rubric |
| `rules/receiving-code-review.md` | Rule file on receiving code review feedback: verify before implementing, push back with evidence, no sycophantic agreement |
| `rules/in-the-circuits.md` | Rule file on classifying tasks as in-circuit (dense RL training, trust output) vs out-of-circuit (no verifier, slow down) before proceeding |
| `rules/spec-is-the-artifact.md` | Rule file on treating the spec as the durable artifact and code as regenerable output; write and review the spec before the code runs |
| `rules/menu-gen-test.md` | Rule file on the Menu-Gen Test: before building an app/script/feature, ask whether a single prompt or multimodal call could replace it |
