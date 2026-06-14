# /skillify - Promote a Session Capability to a Durable Skill

Take what just worked in this session and turn it into a permanent skill: a command file with triggers and rules, deterministic code for the parts that don't need judgment, a test that pins behavior, and a learnings-store entry so future sessions find it.

## When to Use

- A multi-step process just worked in conversation and is likely to recur (OAuth setup, a deploy dance, a verification ritual)
- The agent made a mistake that shouldn't be possible to repeat (wrong side of a latent/deterministic divide — see `rules/latent-vs-deterministic.md` if installed)
- The user said something like "remember this" or "make it a skill" or "skillify it"

If the thing to capture is a single prose lesson rather than an executable workflow, prefer `/reflect` instead.

## Inputs

- `$ARGUMENTS` — optional kebab-case name for the new skill. If omitted, propose one based on what just happened and confirm before creating files.

## Workflow

Follow phases in order. Skip a phase only by announcing which phase and why.

### Phase 1: Identify the Capability

Summarize in one sentence: what did we just build or get right? What's the trigger — the phrase or situation where a future session should invoke this skill?

Classify every step in the workflow:

- **Latent** — needs judgment (summarizing, picking an approach, handling open-ended input)
- **Deterministic** — one right answer given inputs (arithmetic, parsing, file lookups, format conversions)

If `rules/latent-vs-deterministic.md` is installed, follow it strictly. Deterministic steps must become scripts; latent steps stay in the skill's prose.

### Phase 2: Capture the RED Baseline (Gate)

**Do not write any skill content until a no-skill agent has been watched failing the task.** This is red-green-refactor for skills: the baseline failure proves the skill is needed and pins exactly what it must correct. A skill written without a captured baseline is a guess about what an agent gets wrong.

If `rules/skill-authoring.md` is installed, follow its "RED Baseline" section. The steps:

1. **Pick a representative task** — a concrete instance of the situation the trigger will match, not a toy.
2. **Run a fresh subagent WITHOUT the skill** — give it only the task. Use the agent-dispatch tool (e.g., Task in Claude Code).
3. **Record the failure modes** — wrong tool, skipped step, bad default, unsafe action, missing verification.
4. **Record the rationalizations** — the phrases the baseline agent used to justify the wrong behavior. These become the left column of the skill's "Rationalizations" table in Phase 5.

**Gate:** If the baseline agent does the task correctly with no skill, **stop and do not create the skill.** A skill that does not change behavior is bloat that taxes every future invocation. Report that no skill was warranted and exit.

Keep the captured failure modes and rationalizations — Phase 5 targets them and Phase 8 re-runs against them.

### Phase 3: Decide Scope and Location

Ask (or infer from context):

- **Scope**: project-level (`.claude/commands/{name}.md`) or global (`~/.claude/commands/{name}.md`)?
  - Project-level if it depends on this repo's structure
  - Global if the capability is repo-agnostic
- **Helper code location**: project's existing scripts/lib directory, or `~/.claude/lib/` for global

### Phase 4: Check for Collisions

Run the deterministic helper:

```bash
ccgm-skillify-check <name>
```

It scans the user's command directories (`~/.claude/commands/` and any `.claude/commands/` in the current project) and reports:

- Exact name collisions (abort — pick another name)
- Fuzzy matches (warn — likely overlap; consider merging instead of creating a new skill)

If the check reports a collision, stop and resolve before creating files.

### Phase 5: Write the Skill Contract (Target the RED Failures)

Create the command file with this structure:

```markdown
# /{name} - <one-line purpose>

<2-3 sentence description: what the skill does, when the agent should reach for it>

## When to Use

- <trigger condition 1>
- <trigger condition 2>

## Inputs

- `$ARGUMENTS` — <what the user passes, if anything>

## Workflow

### Step 1: <latent or deterministic>
...

### Step 2: <latent or deterministic>
...
```

Each section of the skill must correct a specific failure mode or rationalization captured in the Phase 2 RED baseline. Add the captured rationalizations to the skill's "Rationalizations" table. Do not add advice for failures the baseline agent never produced — unprompted advice is the bloat the skill-authoring discipline exists to prevent.

Follow `rules/skill-authoring.md` if installed:
- Reference files by path, don't inline large content
- Imperative voice, not second-person
- One command per bash invocation, no chaining in the runtime shell

### Phase 6: Extract Deterministic Code

For every deterministic step identified in Phase 1:

1. Write a script (bash, python, or node) that pins the computation. Pure function: same input, same output.
2. Place it in the chosen helper directory. Name it after the skill (`<name>-<verb>` or just `<name>` if there's one operation).
3. Make it executable (`chmod +x`).
4. Have the skill's workflow invoke the script instead of describing the computation in prose.

### Phase 7: Write a Pinning Test

One test per script. Pin the output for a representative input. The goal is a regression guard, not exhaustive coverage.

- Shell projects: a small bats test or a `test_<name>.sh` with exit-code asserts
- Python projects: `test_<name>.py` with unittest/pytest
- JS/TS projects: `<name>.test.ts` with vitest

The test must fail if the script's output drifts. Watch it pass before moving on.

### Phase 8: Confirm GREEN (Re-run the RED Task With the Skill)

Close the red-green loop. Re-run the **same representative task from Phase 2**, this time with the new skill loaded (a fresh subagent that has the skill, or reload and invoke the trigger). Compare against the baseline:

- The failure modes captured in RED no longer appear.
- The behavior demonstrably differs from the no-skill baseline.

**Gate:** If a captured failure persists, the skill text did not target it sharply enough. Revise the skill (back to Phase 5) and re-run. Do not proceed to Register/Report until the GREEN run differs from the baseline. A skill whose GREEN run matches its RED run changed nothing and should not ship.

### Phase 9: Register with the Learnings Store

If `ccgm-learnings-log` is available, log an entry pointing at the new skill so future `/reflect` runs and searches surface it:

```bash
ccgm-learnings-log \
  --type pattern \
  --content "Skill '<name>' captures <one-line capability>. Trigger: <trigger>." \
  --tag skill --tag <topic> \
  --file <relative-path-to-skill.md> \
  --confidence 7
```

If the learnings store isn't installed, skip this phase without ceremony.

### Phase 10: Report

State the result in 3-6 lines:

- RED baseline: `<the failure modes the no-skill agent produced>`
- GREEN confirmation: `<how the skill-loaded run differed from the baseline>`
- Skill created at: `<path>`
- Helper script at: `<path>` (or "no script — pure prose workflow")
- Test at: `<path>` (confirmed passing / pending)
- Learnings entry: `<id>` (or "skipped — no learnings store")
- Next: reload Claude Code if needed, and try the trigger to confirm the skill fires

## Red Flags

Stop and reconsider if you catch yourself:

- Writing skill content before a no-skill baseline (Phase 2) was watched failing the task
- Creating a skill when the baseline agent did the task correctly with no skill — there is nothing to skillify
- Shipping the skill without a GREEN re-run (Phase 8) that differs from the baseline
- Creating a skill before the workflow has actually worked once in this session
- Skipping Phase 4 (collision check) to save time
- Writing prose for a deterministic computation instead of a script
- Shipping the skill without writing the test
- Naming the skill generically (`helper`, `util`, `fix-stuff`) — the trigger won't match anything

## Rationalizations That Mean You Are About to Skip Steps

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "I know what the agent gets wrong, skip the baseline" | If you know, the baseline confirms it in two minutes. If you are wrong, you just avoided shipping a skill that targets the wrong failure. |
| "The baseline run is slower than just writing the skill" | Writing a skill the agent did not need taxes every future invocation forever. The baseline is the cheap path. |
| "The skill works, I'll skip the GREEN re-run" | Without a re-run against the RED task, you cannot prove the skill changed anything. The GREEN run is the gate. |
| "The test is trivial, I'll add it later" | Later means never. A skill without a test rots silently. |
| "It's a one-off, no need to skillify" | If it's one-off, don't skillify. If it might recur, don't cut the test. |
| "The collision check is paranoid" | The collision check runs in 200ms. Name conflicts are silent and permanent. |
| "I'll reuse that existing script" | Check whether the existing script is tested. If not, your new skill inherits its rot. |
