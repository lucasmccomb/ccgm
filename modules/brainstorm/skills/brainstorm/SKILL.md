---
name: brainstorm
description: >
  Design-before-implementation gate. Forbids code, scaffolding, or implementation
  until a design spec has been written and the user has explicitly approved it.
  Explores context, proposes 2-3 approaches with tradeoffs, writes a spec to
  docs/brainstorm-notes/, self-reviews for TBDs and contradictions, then hands
  off to /xplan. Pairs with /ideate (concept refinement) to enforce
  spec-before-plan-before-code separation.
  Triggers: brainstorm, design this, spec this out, think through the design,
  no code yet, design first, approach options, tradeoffs
disable-model-invocation: true
---

# /brainstorm - Design Spec Before Any Implementation

**Iron Law: NO CODE, SCAFFOLDING, OR IMPLEMENTATION UNTIL A DESIGN SPEC IS WRITTEN AND USER-APPROVED.**

Violating the letter of this rule is violating the spirit. If you produce any file
outside of the spec itself, or sketch any implementation in prose, you have skipped
the gate.

**Announce at start:** "I'm using the /brainstorm discipline. Writing the design spec first. No code until you approve it."

<HARD-GATE>
The following actions are FORBIDDEN until Phase 4 approval:
- Writing any code (source files, config files, scripts, tests)
- Creating scaffolding (package.json, tsconfig.json, directory trees)
- Running Bash tool commands that modify the project (install, init, scaffold)
- Invoking /xplan, /atdd, or any implementation-adjacent command
- Drafting pseudocode or "here's roughly what the implementation looks like"

The ONLY artifact you may produce in Phases 0-3 is the design spec itself at
docs/brainstorm-notes/YYYY-MM-DD-{topic}-design.md.

If the user asks you to "just start coding" or "skip the spec", refuse once and
restate the gate. If they insist a second time, honor their override but note in
the final message that the gate was bypassed at their request.
</HARD-GATE>

## Usage

```
/brainstorm "add a rate limiter to the API gateway"
/brainstorm "migrate auth from Supabase to Clerk"
/brainstorm                                    # Asks what you want to design
/brainstorm --from-concept {path}              # Start from an /ideate concept brief
/brainstorm --resume                           # Resume an in-progress design session
```

## Relationship to Other Commands

- **`/ideate`** refines a fuzzy idea into a Concept Brief (problem/audience/solution). It answers "what are we building?"
- **`/brainstorm`** (this command) turns an approved concept or a well-defined problem into an approved design spec. It answers "how are we building it?"
- **`/xplan`** turns an approved design spec into an executable plan (phases, tasks, files). It answers "what are the concrete steps?"

Flow: loose idea -> `/ideate` -> Concept Brief -> `/brainstorm` -> Design Spec -> `/xplan` -> Plan -> implementation.

You do not need `/ideate` first if the input is already a concrete, well-scoped
problem (e.g., "add rate limiting to the Express API"). `/brainstorm` can be the
entry point for design work on an already-understood problem.

---

## Phase 0: Setup & Scope Check

### 0.1 Parse Input

Extract from `$ARGUMENTS`:
- **Topic**: The thing to design (can reference a file, concept brief, or free text)
- **`--from-concept {path}`**: Load an /ideate concept brief as the starting context
- **`--resume`**: Resume a prior design session from `docs/brainstorm-notes/`

If no arguments, ask:

> "What do you want to design? Give me the problem, feature, or system. If you
> already ran /ideate, point me at the concept brief with --from-concept."

### 0.2 Oversized Project Check

Before going further, gauge scope. Ask yourself:

- Does this touch more than one major subsystem?
- Would a reasonable spec exceed ~400 lines?
- Are there multiple distinct user-facing features bundled together?

If any answer is yes, tell the user:

> "This feels bigger than a single design spec. I'd like to decompose it into
> 2-4 smaller designs that can be specced independently. Here's how I'd split
> it: {list}. Want to proceed with decomposition, or push through as one spec?"

If they choose decomposition, have them pick ONE piece to design now; save the
others as follow-ups.

### 0.3 Create Session Directory

```
slug = kebab-case(topic, max 50 chars)
date = YYYY-MM-DD
session_dir = docs/brainstorm-notes/{date}-{slug}/
mkdir -p {session_dir}
```

If `docs/brainstorm-notes/` does not exist in the repo, create it.

### 0.4 Initialize Session State

Create `{session_dir}/session.md`:

```markdown
# Brainstorm Session: {topic}
Started: {timestamp}
Status: exploring
Spec path: {session_dir}/design.md (not yet written)

## Input
{raw user input or concept brief reference}

## Context Exploration Log
{appended during Phase 1}

## Approaches Considered
{appended during Phase 2}

## Decisions
{appended as decisions get locked}
```

---

## Phase 1: Context Exploration (One Question at a Time)

Understand the surrounding system before proposing approaches. The goal is
enough context to propose informed options, not exhaustive investigation.

### Exploration Techniques

1. **Read relevant code.** Use Glob/Grep/Read to understand the existing
   patterns in the affected area. NEVER edit anything.
2. **Check for prior art.** Search the codebase for similar features or
   subsystems. How did those end up structured? What would be consistent?
3. **Identify constraints.** Look at package.json, tsconfig, lint rules,
   existing abstractions. What's already in the stack?
4. **Map dependencies.** What other modules/services/users would this touch?

### Interview the User (One Question at a Time)

Never dump a list of questions. Each question should feel like the natural next
thing to ask given what you've learned.

Useful questions in this phase:

- "What's the trigger? How does a user or system end up needing this?"
- "What does the current workflow look like, and which part of it is painful?"
- "Are there hard constraints I should know about (perf, budget, compliance, stack)?"
- "What would a working solution look like from the outside? Describe the observable behavior."
- "Have you tried anything already? What didn't work?"
- "Is there an existing pattern in this codebase I should follow or explicitly break from?"

After 3-6 questions (or when you can confidently sketch the problem), synthesize:

> "Here's what I'm hearing: {problem}, {constraints}, {observable target behavior}.
> Before I propose approaches, is there anything I'm missing or getting wrong?"

Log each exchange to `session.md` under Context Exploration Log.

---

## Phase 2: Propose 2-3 Approaches with Tradeoffs

This is the core of the gate. You must present MULTIPLE concrete approaches
(not one blessed plan) with honest tradeoffs. The user picks or directs you to
synthesize.

### Approach Template

For each approach, write:

```markdown
### Approach {N}: {Short name}

**Core idea**: {One or two sentences. Name the pattern, don't describe the code.}

**What changes**:
- {File or subsystem 1}: {what changes conceptually}
- {File or subsystem 2}: {what changes conceptually}
- {...}

**Pros**:
- {Concrete benefit, not generic like "simple" or "clean"}
- {...}

**Cons / Tradeoffs**:
- {Concrete cost, failure mode, or limitation}
- {...}

**Rough effort**: {S / M / L with one-line justification}

**Fits existing patterns?**: {Yes / No / Partially, with explanation}
```

### Rules for Approaches

1. **Actually distinct.** If Approach 2 is Approach 1 with a different variable
   name, you have one approach, not two. Force genuine divergence: different
   abstraction, different layer, different tech, different sequencing.
2. **At least one "simpler than you'd think" option.** Always include the
   minimum-viable approach, even if you don't think it's the best answer.
3. **Name a recommended approach with reasoning.** Don't hide behind
   neutrality. Say which you'd pick and why, then let the user override.
4. **Call out the "one-way doors."** If an approach makes future changes hard
   to reverse, flag it explicitly under Cons.

### Present and Ask

Display the approaches inline. Then use AskUserQuestion with:

| Option | Description |
|--------|-------------|
| **Approach 1** | {name} |
| **Approach 2** | {name} |
| **Approach 3** | {name} (if applicable) |
| **Combine / hybrid** | I want pieces from multiple - I'll tell you which |
| **None of these** | Let's go back to context exploration |

Append the chosen approach and reasoning to `session.md` under Decisions.

---

## Phase 3: Write the Design Spec

Once an approach is selected, write the spec to
`{session_dir}/design.md`. This is the ONLY implementation-shaped artifact
allowed before user approval.

### Spec Template

```markdown
# Design: {topic}

**Date**: {YYYY-MM-DD}
**Status**: draft-pending-approval
**Concept brief**: {path, if from /ideate, else "direct"}
**Related issues**: {list, if any}

## Problem

{2-3 paragraphs. What is broken, missing, or needed? Who is affected?
What is the observable symptom?}

## Goals

- {Specific, verifiable outcome 1}
- {Specific, verifiable outcome 2}
- {...}

## Non-Goals

- {What this explicitly does NOT address}
- {...}

## Approach

{The selected approach, expanded. 1-3 paragraphs of prose that name the
pattern, the key abstractions, and the rationale.}

### Why this over the alternatives

{1-2 paragraphs explaining why this approach beats the ones you considered.
Reference the tradeoffs from Phase 2.}

## Design Details

### Data / State Changes
{Tables, schemas, new fields, migrations. NOT code - describe shape.}

### Interfaces / API Surface
{Function signatures, endpoint contracts, CLI flags. Describe the contract,
not the implementation.}

### Control Flow
{Step-by-step description of the main workflow. Prose or numbered steps.
NO pseudocode.}

### Error / Edge Cases
- {Case}: {Expected behavior}
- {...}

### Observability
{What logs, metrics, or user-visible feedback does this produce? How does
an operator diagnose a failure?}

## Risks & Open Questions

### Risks
- {What could go wrong in production and how we'd catch it}

### Open Questions
- {Things I couldn't resolve from context - flag for the user}

## Testing Strategy

{High-level: what kinds of tests (unit/integration/E2E), what's the
acceptance criterion for "done", any known tricky-to-test parts.}

## Rollout / Migration

{If the change touches existing behavior: how do we deploy it safely?
Feature flag? Gradual rollout? One-shot? Backward compat?}

## Follow-ups (Deferred)

- {Things intentionally left for later}
```

### After Writing

1. Tell the user the spec exists at `{session_dir}/design.md`.
2. Display the full spec inline (not just the path).
3. Move to Phase 4 self-review BEFORE asking for approval.

---

## Phase 4: Self-Review Before User Approval

Before you ask the user to approve, review your own spec. This is not optional.

### Self-Review Checklist

Scan the spec and verify:

- [ ] **No TBDs, TODOs, or "to be determined"** - if something is unresolved,
      move it to Open Questions explicitly; don't leave `TBD` inline.
- [ ] **No contradictions** - cross-reference Goals vs Non-Goals vs Approach.
      If Approach contradicts a Non-Goal, fix one.
- [ ] **No placeholder types or shapes** - every data/interface section has
      concrete names, not "TBD: some kind of config object".
- [ ] **No vague tradeoffs** - "this approach is more flexible" is not a
      tradeoff. "This approach costs an extra DB query per request but allows
      dynamic config changes without redeploy" is.
- [ ] **No skipped sections** - if a section does not apply, say "N/A -
      {reason}" explicitly; don't silently omit.
- [ ] **One-way doors are flagged** - irreversible or expensive-to-reverse
      decisions are called out.
- [ ] **Test strategy is real** - "we'll add tests" is not a strategy. Name
      the categories and at least one concrete example.

If the checklist surfaces a gap, FIX THE SPEC, then re-run the checklist. Do
not present a spec you know has gaps.

### Announce the Review

Tell the user:

> "I self-reviewed the spec. Here's what I checked: {checklist}. Here's what I
> fixed in the pass: {list of corrections, or 'nothing - it was clean'}.
> Remaining Open Questions for you: {list}."

---

## Phase 5: User Approval Gate

Present the spec with AskUserQuestion:

| Option | Description |
|--------|-------------|
| **Approve** | Lock the spec. Status -> approved. Ready for /xplan or implementation. |
| **Needs edits** | Tell me what to change. I'll revise and re-present. |
| **Reconsider approach** | The spec is correct but the approach is wrong. Back to Phase 2. |
| **Back to exploration** | Context is incomplete. Back to Phase 1. |

### Handling Responses

**Approve**:
1. Update spec front-matter: `Status: approved`
2. Update `session.md` status: `approved`
3. Move to Phase 6.

**Needs edits**:
1. Ask what to change. Apply edits to `design.md`.
2. Re-run Phase 4 self-review.
3. Re-present. Loop until approved.

**Reconsider approach**:
1. Save the current spec draft as `design-v1-rejected.md` for history.
2. Return to Phase 2 with the user's concerns as constraints.

**Back to exploration**:
1. Save the current spec draft as `design-v1-rejected.md`.
2. Return to Phase 1 with a sharper focus on the missing context.

---

## Phase 6: Handoff

The spec is approved. Ask the user what comes next:

| Option | Description |
|--------|-------------|
| **Plan it** | Invoke `/xplan` with the approved spec as input. |
| **Implement now** | Jump to implementation using the spec as a contract. |
| **Just save it** | Keep the spec for later. Report the path. |

**Plan it**: Invoke `/xplan` via the Skill tool. Pass the spec path so xplan
does not have to re-derive the design. `/xplan`'s job is now execution
sequencing, not redesign.

**Implement now**: Only appropriate for small, single-file changes. For
anything larger, strongly recommend `/xplan` first. If the user insists,
implement directly using the spec as the contract. Every code change must
trace back to a section of the spec.

**Just save it**: Report `{session_dir}/design.md` as the canonical path.
Suggest the user can return with `/brainstorm --resume` or feed the spec to
`/xplan` manually.

---

## Anti-Patterns (Do NOT Do These)

- **Don't skip the gate.** Even if the task feels trivial, write the spec. A
  5-line spec is fine for a 5-line change; the gate is about the discipline,
  not the length.
- **Don't propose one approach and call it "two" with cosmetic differences.**
  If you cannot name genuinely distinct approaches, say "I only see one viable
  approach here because {reason}" and let the user push back.
- **Don't write code in the spec.** Contracts, shapes, names, yes. Function
  bodies, no. If you need pseudocode to explain, use numbered prose steps.
- **Don't ask for approval before self-review.** The self-review catches the
  gaps the user shouldn't have to.
- **Don't bypass the gate because the user is impatient.** Restate the gate
  once. If they override, honor it but log that the gate was bypassed.
- **Don't hand off to /xplan without an approved spec.** /xplan assumes the
  design is settled. Handing it an un-approved spec wastes the plan phase.
- **Don't re-derive what /ideate already produced.** If --from-concept is
  used, load the concept brief as input to Phase 1 and skip problem
  clarification unless genuinely needed.

## Rationalizations That Mean You Are About to Skip the Gate

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "The spec is obvious, let me just start" | If it were obvious, writing it down takes 2 minutes. Do it. |
| "I'll write the spec after the prototype" | Specs written after code prove nothing about design quality - they describe what got built, not what should have been built. |
| "This is too small for a full spec" | Then write a small spec. Five headings, three sentences each. Skip sections that are N/A. |
| "The user said just do it" | Restate the gate once. If they insist, note the bypass explicitly in your final message. |
| "I'll propose one approach and call it the plan" | The gate requires tradeoff analysis. A plan without considered alternatives is a guess. |
| "Self-review slows things down" | Self-review catches the gaps you'd otherwise fix in code review or production. |
| "I already know the answer" | Then writing it down costs nothing. Stop explaining why you won't and just write it. |
