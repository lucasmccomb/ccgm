# Skill Authoring

**Iron Law:** EVERY BYTE A SKILL LOADS AT TRIGGER TIME IS CARRIED IN EVERY SUBSEQUENT MESSAGE.

Violating the letter of this rule is violating the spirit of this rule. A skill that feels small when you write it becomes a tax on every turn of every session that invokes it. Author with that tax in mind.

**Announce at start:** "I'm using the skill-authoring discipline. Writing for context efficiency and portability."

## Scope

This rule governs authoring of:

- Slash commands in `modules/{name}/commands/*.md`
- Skill definitions (`SKILL.md`) where modules ship them
- Reusable subagent prompts in `modules/{name}/agents/*.md`
- Any file that is loaded into an agent context on invocation

It does NOT govern rule files (`rules/*.md`), which are loaded once at session start and follow separate conventions in CONTRIBUTING.md.

## The RED Baseline (Watch It Fail First)

**Iron Law:** NO SKILL WITHOUT A CAPTURED BASELINE FAILURE FIRST.

A skill exists to change an agent's behavior. If the behavior was already correct without the skill, the skill is dead weight that taxes every future invocation. The only proof that a skill is needed is a baseline run where an agent *without* the skill produces the wrong behavior. Watch it fail, capture exactly how it failed, then write the minimal skill that targets those failures - and only those.

This is red-green-refactor applied to skills:

1. **RED** - Run a representative task with an agent that does NOT have the skill. Capture the failure modes and the rationalizations it produces.
2. **GREEN** - Write the smallest skill that targets the captured failures. Re-run the same task with the skill loaded. Confirm the behavior changed.
3. **REFACTOR** - Trim the skill to context-efficient form (the rest of this rule) while keeping the GREEN result.

A skill written without watching the baseline fail is a guess about what an agent gets wrong. Guesses produce skills full of advice the agent never needed and missing the corrections it did.

### RED: Capture the Baseline Failure

Before writing any skill content:

1. **Pick a representative task** - a concrete instance of the situation the skill is meant to handle. Not a toy; the real kind of task the trigger will match.
2. **Run an agent without the skill** - a fresh subagent that does not have the skill loaded. Give it the task and nothing else.
3. **Record the failure modes** - what specifically did it get wrong? Wrong tool, skipped step, bad default, unsafe action, missing verification?
4. **Record the rationalizations** - the phrases the agent used to justify the wrong behavior ("this is too small to test," "I'll just chain these commands," "the happy path is enough"). These become the left column of the skill's "Rationalizations" table.

If the baseline agent does the task correctly with no skill, **stop**. There is no skill to write. A skill that does not change behavior is bloat, not discipline.

### GREEN: Write the Minimal Skill, Then Confirm

1. **Target only the captured failures** - each section of the skill should correct a specific failure mode or rationalization observed in RED. Do not add advice for failures the baseline agent never produced.
2. **Re-run the same representative task** with the skill loaded.
3. **Confirm the behavior changed** - the failure modes from RED no longer appear. If a failure persists, the skill text did not target it sharply enough; revise and re-run, do not declare done.

GREEN is the gate. A skill is not finishable until a skill-loaded run on the RED task demonstrably differs from the baseline.

### Rationalizations That Mean You Are About to Skip the RED Baseline

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "I already know what the agent gets wrong" | If you knew, the baseline run confirms it in two minutes. If you are wrong, you just avoided shipping a skill that targets the wrong failure. |
| "Running a baseline is slower than just writing the skill" | Writing a skill the agent did not need is the slow path - it taxes every future invocation forever. |
| "The skill is obviously needed" | "Obvious" is the word that precedes most unnecessary skills. Watch it fail first. |
| "I'll verify the skill works after I write it" | Verifying against a skill-loaded run with no recorded baseline proves nothing - you cannot see what changed. |

## Reference File Inclusion

### Use Backticks for CWD-Relative Reads

When a skill needs to point an agent at a reference file, use plain backticks around the path:

```
See `references/schema.yaml` for the full shape.
```

The agent treats this as a reference it can read on demand with its file tool. The bytes are NOT loaded until the agent chooses to read them.

### Use `@` Only for Small Structural Files

Use `@path/to/file` inline embedding only when:

- The file is under 150 lines
- The file is structural (a schema, a short template, a checklist) that every invocation needs
- Skipping the embed would force the agent to make an extra tool call for trivial content

`@` embeds are loaded at skill-trigger time and stay in context forever. Treat them as expensive.

### Never Reference Files Outside the Skill Directory

A skill that reads from `../other-skill/references/thing.md` is broken the moment someone reorganizes modules. Keep every referenced file inside the skill's own directory tree, or point at a well-known project path (e.g., `.claude/todos/`) that is documented as stable.

## Conditional Content Extraction

Any block loaded at trigger time is carried in every subsequent message. Extract a block to `references/{name}.md` when both conditions hold:

1. The block is used conditionally (only some invocations need it)
2. The block is roughly 20% or more of the skill's total length

Examples of content that should almost always live in `references/`:

- Long YAML/JSON schemas
- Per-category lookup tables (e.g., "for bug fixes do X; for features do Y; for docs do Z")
- Multi-step procedures that only apply in a specific mode
- Example outputs or fixtures

The skill body points at them:

```
If the invocation is a bug fix, follow `references/bug-fix-procedure.md`.
If it is a feature, follow `references/feature-procedure.md`.
```

The agent loads only the file that matches its path.

## Tool Selection

### Native Over Shell

Prefer the agent's native tools over shell-invoked equivalents. Native tools are faster, stream results, and don't pollute the context with shell noise.

| Task | Prefer | Avoid |
|------|--------|-------|
| Find files by pattern | native file-search tool (e.g., Glob) | `find` / `ls -R` |
| Search file contents | native content-search tool (e.g., Grep) | `grep` / `rg` in Bash |
| Read a file | native file-read tool (e.g., Read) | `cat` / `head` / `tail` |
| Edit a file | native edit tool | `sed` / `awk` |

When a skill instructs an agent to run `grep` or `find`, it is burning tokens on output that the native tool would stream more cleanly.

### Describe Tools by Capability Class

When a skill references a specific tool, describe it by capability first and name it parenthetically:

```
Use the native file-search tool (e.g., Glob in Claude Code) to enumerate test files.
```

This keeps the skill portable across agent runtimes while still giving the current runtime a concrete hint.

## Bash Invocation Discipline

### One Simple Command Per Call

Each Bash invocation from a skill or subagent prompt should be a single, readable command. Do not chain with `&&`, `;`, or pipelines unless the chain is the action (e.g., `curl ... | jq ...` where jq is the whole point).

Bad:

```
cd foo && git fetch && git checkout -b bar && npm install && npm test
```

Good: five separate calls, each independently verifiable and retryable.

Rationale: chained failures are hard to attribute; the agent loses granular exit codes; and the runtime shell does not preserve state between calls, so `cd` at the front of a chain often does not do what the author expects.

### Pre-Resolution `!` Backticks for Environment Probes

When a skill needs an environment value that is stable for the whole invocation (current branch, repo root, today's date), use a pre-resolution `!` backtick so the value is resolved once at skill load and inlined as a literal:

```
Current branch: !`git branch --show-current`
Repo root: !`git rev-parse --show-toplevel`
Today: !`date +%Y-%m-%d`
```

The agent sees the resolved value in its instructions, not a command it has to re-run in every turn. Use this for probes only - never for actions or anything with side effects.

## Writing Style

### Imperative / Infinitive Voice

Write instructions in imperative or infinitive form. Avoid second-person "you."

| Avoid | Prefer |
|-------|--------|
| "You should read the file first." | "Read the file first." |
| "You will need to run the tests." | "Run the tests." |
| "Make sure you check the logs." | "Check the logs." |

This makes the skill feel like a spec the agent is executing, not a letter addressed to a human.

### No AI Attribution

Never include AI attribution inside skill content, commit templates, or PR body templates generated by a skill. The human is the author; AI is a tool.

### Concrete Over Abstract

Skills that describe behavior in the abstract ("handle errors appropriately") are parsed as vague license. Name the specific tool, file, or pattern. If the skill cannot name it, extract the decision to a reference file with enumerated cases.

## Authoring Checklist

Before committing a new skill or command file:

- [ ] A RED baseline was captured: a no-skill agent run on a representative task that demonstrably failed
- [ ] The skill targets only the failure modes and rationalizations observed in RED
- [ ] A GREEN run (skill loaded, same task) confirmed the behavior changed
- [ ] Every reference file lives inside the skill's directory
- [ ] Backticks are used for on-demand reads; `@` is used only for small structural files
- [ ] Conditional content (~20%+ of the skill, used by some invocations) is extracted to `references/`
- [ ] Native tools are named; shell-invoked equivalents are not substituted
- [ ] Each Bash instruction is one simple command
- [ ] Environment probes use `!` backticks, not instructions to re-run commands
- [ ] Voice is imperative/infinitive; second-person "you" is absent
- [ ] No AI-attribution footers in any template the skill generates

## Rationalizations That Mean You Are About to Bloat a Skill

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "I'll `@`-embed it so the agent does not have to read it" | Every invocation pays for that embed forever. Backtick it. |
| "It is simpler to chain these commands in one call" | Simpler to write, harder to debug. Split them. |
| "The agent probably has this tool, but I'll tell it to use `grep` just in case" | Telling it to use `grep` means it will use `grep`. Name the native tool. |
| "This reference file is in the sibling skill; I'll point at it" | The moment that skill moves or is removed, your skill breaks. Copy or extract to a shared location. |
| "The block is only needed half the time, but it is short, so I'll inline it" | Short blocks add up across dozens of skills. Extract if the conditional-use rule applies. |
| "I'll write 'you should...' because it reads naturally" | It reads naturally to a human. The agent is parsing it as part of its spec. Use imperative voice. |

## Red Flags

Stop and restructure the skill if you catch yourself:

- Writing skill content before running a no-skill baseline that failed
- Declaring a skill done without a GREEN run that differs from the baseline
- Embedding a schema or long table inline at the top of the skill body
- Writing a branched procedure (if X do this, if Y do this, if Z do this) where each branch is more than a paragraph
- Chaining more than two Bash actions in a single instruction
- Referencing a file path that starts with `..` or points outside the skill directory
- Telling the agent to run `find`, `grep`, or `cat` when the native tool exists
- Addressing the agent as "you" throughout the file
