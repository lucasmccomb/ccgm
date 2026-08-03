---
description: Propose (and optionally write) a claudeMdExcludes block that suppresses CCGM rules irrelevant to this repo
argument-hint: "[--write]"
---

# /rules-scope - Generate a Repo's claudeMdExcludes Block

Inspects the current repo, decides which installed CCGM rule files are
irrelevant to it, and proposes a `claudeMdExcludes` array for that repo's
`.claude/settings.json`. Turns a per-machine hand-edit into a generated,
reviewable, committable artifact.

**Dry run by default.** Nothing is written unless `--write` is passed.

## Usage

```
/rules-scope             # print the proposal; write nothing
/rules-scope --write     # print the proposal AND write it to .claude/settings.json
```

## When to invoke

- Onboarding a repo whose tech stack clearly does not need every installed
  CCGM module's rules (e.g. a Rust-only service does not need `tailwind`,
  `shadcn`, `supabase`, or `mcp-development` loaded every session).
- Revisiting a repo's `.claude/settings.json` after installing new CCGM
  modules, to see whether the exclusion proposal changed.

## When NOT to invoke

- On a repo that genuinely uses most of CCGM's tech-specific tooling — the
  proposal will legitimately come back small or empty, which is correct,
  not a bug.
- To remove a rule you personally find noisy but that is actually relevant
  to this repo's stack. `claudeMdExcludes` is a repo-wide, committed
  decision, not a personal preference toggle.

## How it works

1. Run `python3 modules/relevance-injection/lib/rules_scope.py` (or the
   installed `~/.claude/lib/rules_scope.py`, if the module is installed)
   from the target repo's root, or pass the repo path as an argument.
2. The script reads the installed CCGM manifest
   (`~/.claude/.ccgm-manifest.json`) for the set of installed modules, and
   inspects the target repo for language/framework markers
   (`detect_repo_profile()`).
3. It proposes excluding two kinds of rule file:
   - **tech-specific** (repo-profile-gated): rule files belonging to a
     module whose `module.json` declares `"category": "tech-specific"`
     (`tailwind`, `shadcn`, `supabase`, `cloudflare`, `mcp-development`),
     proposed only when the repo shows no marker for that module (e.g. no
     `tailwind.config.*` and no `tailwindcss` dependency -> `tailwind.md`
     and `frontend-css.md` are proposed).
   - **niche** (not repo-profile-gated): a small, conservative, hand-picked
     set of rule files about specific CCGM meta-workflows (the nightly
     dreaming pipeline, the Argus visual-convergence loop, SSH to a
     configured remote box, ...) that are rarely in play regardless of the
     target repo's tech stack.
4. It prints every proposed row (module, rule file, category, estimated
   token cost) and a total. **Nothing is written at this point.**
5. With `--write`, it merges the proposed paths into
   `<repo>/.claude/settings.json`'s `claudeMdExcludes` array, preserving
   every other key in the file untouched, and creating the file if it does
   not exist.

## Safety rules (this is what makes exclusion safe to automate)

- **Never proposes a `PINNED_FLOOR` module's rules.** `PINNED_FLOOR` is the
  seven `SAFETY_CORE_TIERS` modules (`git-workflow`, `hooks`, `autonomy`,
  `test-driven-development`, `verification`, `systematic-debugging`,
  `subagent-patterns`) plus `identity`, `live-testing-guard`,
  `git-worktrees`, `model-vetting`, and `branch-guard` — derived from
  `relevance_select.safety_core_modules()` plus four named additions, in
  exactly one place (`lib/rules_scope.py`'s `PINNED_FLOOR`), never
  re-typed. This is checked explicitly in code, not merely true by
  construction of the two candidate categories above.
- **Never writes outside the target repo's `.claude/settings.json`.** It
  never touches `~/.claude/rules/`, `~/.claude/hooks/`, or any other
  machine-global CCGM state — the rule files stay installed and readable;
  only their auto-load into THIS repo's sessions is suppressed.
- **Merges, never overwrites.** An existing `claudeMdExcludes` array is
  extended (deduplicated), and every other key already in the file is
  preserved untouched.
- **Dry run by default; `--write` is required to modify anything.** A
  silent rule-dropping command would be exactly the failure this tool
  exists to prevent.

## Why this differs from installing fewer modules

Uninstalling a module makes its rules absent everywhere, permanently, for
every repo. `claudeMdExcludes` suppresses auto-loading a rule into ONE
repo's sessions while the rule file stays installed, readable on demand,
and untouched for every other repo on the machine. The rule can still be
read directly (`Read ~/.claude/rules/<file>.md`) if a task in the excluded
repo turns out to need it after all — exclusion narrows what auto-loads,
it does not delete anything.

## A load-bearing detail: paths are resolved, not symlink paths

Claude Code's `claudeMdExcludes` matches against the REAL, symlink-resolved
path of the loaded instruction file — not the `~/.claude/rules/<file>.md`
symlink path CCGM's installer creates under `linkMode`. This was verified
empirically (headless `claude -p`, the `InstructionsLoaded` hook as the
oracle): excluding the symlink path did nothing; excluding the real,
resolved path worked. `rules_scope.py` handles this automatically
(`os.path.realpath()` on the installed location) — nothing to configure.

## Cross-references

- Library: `modules/relevance-injection/lib/rules_scope.py`
  (`detect_repo_profile()`, `propose_excludes()`, `write_settings()`)
- Plan: `~/code/plans/ccgm-dynamic-rule-injection/plan.md` Epic 0.5
- `modules/relevance-injection/lib/relevance_select.py` — the safety-core
  precedence and manifest-reading helpers this tool reuses rather than
  duplicating
