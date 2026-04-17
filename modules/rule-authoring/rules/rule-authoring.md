# Rule Authoring

**Iron Law:** A RULE IS NOT DONE UNTIL IT HOLDS UNDER PRESSURE.

Violating the letter of this rule is violating the spirit of this rule. A rule that reads well in isolation but fails the first time an agent has a good excuse to skip it is not a rule - it is a suggestion. Every discipline-enforcing rule must be pressure-tested against realistic rationalizations before it ships.

**Announce at start:** "I'm using the rule-authoring discipline. Pressure-testing before shipping."

## Scope

This rule governs authoring of:

- Discipline rules (`rules/*.md`) that enforce a non-negotiable behavior (TDD, verification, systematic debugging, safety protocols)
- Promoted rules added via `/promote-rule`
- New rules sourced from `/copycat` analysis of other configs

It does NOT govern:

- Reference tables (e.g., stack-specific lookup lists) where there is no agent pressure to bypass
- Command files (`commands/*.md`) - see the `skill-authoring` rule for those
- Project-specific CLAUDE.md entries about file paths or tool commands

The distinction is simple: if an agent would ever have reason to rationalize *past* the rule, pressure-test it. If the rule is purely informational, skip the pressure test.

## Required Structural Elements

Every discipline rule must contain the following, in roughly this order:

### 1. Iron Law

A single, declarative, all-caps sentence stating the one thing the rule forbids. Examples:

- NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
- NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.
- NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE.

The Iron Law is not a summary. It is a refusal of negotiation. Write it at the top of the file so an agent that reads the first screen cannot miss it.

### 2. Spirit-vs-Letter Clause

Immediately after the Iron Law, write:

> Violating the letter of this rule is violating the spirit of this rule.

Then a one-sentence expansion that names the failure mode the rule prevents ("If you did not watch the test fail, you do not know if it tests the right thing.").

This clause closes the most common bypass: an agent that finds a technicality the rule does not explicitly cover and uses the technicality as permission. The clause makes clear that technicalities do not count.

### 3. Announce-at-Start Line

A one-line public commitment the agent states at the top of a response that invokes the rule:

> **Announce at start:** "I'm using the X discipline. Doing Y."

Public commitment activates the consistency principle - an agent that has announced it will follow the rule is more likely to follow through. The announcement also makes it observable to the user whether the rule was actually invoked.

### 4. Rationalizations Table

A two-column markdown table mapping rationalizations the agent might use to the reality that the rule addresses. Minimum 6 rows. Derive the rows empirically from pressure-testing (see `pressure-testing.md`) - do not invent them from armchair intuition.

Format:

```markdown
| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "It's too simple to test" | Simple code has simple tests. Write them. |
| "I'll add tests after" | Tests written after prove nothing about correctness. |
```

Each row should quote a specific excuse and reply with the specific reality. Generic replies ("just follow the rule") do not close loopholes.

### 5. Red Flags List

A bulleted list of self-catch phrases. When the agent notices itself about to say or do any of them, the rule says stop and return to the discipline.

Format:

```markdown
## Red Flags

Stop and {follow the discipline} if you catch yourself:

- Saying "one more fix attempt"
- Being "pragmatic, not dogmatic"
- "I already tested this manually"
```

Red Flags are meta-cognitive triggers. The Rationalizations Table addresses arguments; the Red Flags list addresses language the agent uses as it is about to slip.

### 6. Four-State Subagent Protocol (when the rule governs subagent work)

When the rule describes subagent behavior, require subagents to end their reports with one of four structured status values:

| Status | Meaning | Dispatcher Action |
|--------|---------|-------------------|
| **DONE** | Task completed as specified; all deliverables present; no unresolved concerns. | Verify the artifact and move on. |
| **DONE_WITH_CONCERNS** | Task completed but the agent has doubts about the approach, missing context, or edge cases. | Read the concerns. Decide to accept, fix, or re-dispatch. |
| **BLOCKED** | Task cannot be completed as specified. | Resolve the blocker, revise the spec, or re-dispatch. |
| **NEEDS_CONTEXT** | Task is under-specified. | Supply the missing context and re-dispatch. |

Free-form summaries force the dispatcher to re-read everything to decide what to do. The four-state protocol enables immediate routing and surfaces doubts that silent success would hide.

## Voice Conventions

### Imperative / Infinitive

Write in imperative or infinitive form. Avoid second-person "you" in rule body prose. (The Rationalizations Table is an intentional exception - it quotes what the agent is about to say in first person, and replies in second person as a direct address.)

| Avoid | Prefer |
|-------|--------|
| "You should verify the output." | "Verify the output." |
| "You will need to run the tests." | "Run the tests." |
| "Make sure you check the logs." | "Check the logs." |

### Concrete Over Abstract

Name the specific failure mode, not the category. "Agents under pressure skip verification" is usable; "ensure quality" is not. If the rule cannot name the specific failure, it is not ready to ship.

### No AI Attribution

Never include AI-attribution trailers, "generated with Claude" footers, or similar signatures inside rule content. The human is the author; AI is the tool.

## Authoring Workflow

1. **Identify the discipline the rule enforces.** What is the one behavior it is non-negotiable about? Write the Iron Law sentence.
2. **Draft the rule body.** Spirit-vs-letter clause, announce-at-start line, the core discipline explained in imperative voice.
3. **Pressure-test the draft.** Use `/pressure-test <rule-file>` or follow the methodology in `pressure-testing.md` manually. Generate 5-10 adversarial scenarios. Dispatch subagents with and without the rule. Capture rationalizations verbatim.
4. **Fill in the Rationalizations Table** from the captured rationalizations. One row per distinct rationalization observed.
5. **Fill in the Red Flags list** from the language the agent used as it slipped.
6. **Re-pressure-test.** Run the same scenarios again with the updated rule. Any scenarios where the agent still slips identify remaining loopholes.
7. **Iterate until the rule holds.** A rule holds when pressure-tested agents follow it in at least 4 of 5 scenarios. If the rule still fails, the Iron Law probably needs sharpening or the rationalization table needs an additional row.

## Rationalizations That Mean You Are About to Ship an Untested Rule

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "The rule reads well, it will hold" | Rules that read well and rules that hold under pressure are different things. Test it. |
| "This is just a small addition" | Small additions that are not pressure-tested become the loopholes in the next pressure test. |
| "I copied this from superpowers / another config" | Their rule was pressure-tested in their context. Yours may collide with existing CCGM rules or voice. Test it. |
| "Agents in CCGM already follow TDD, this rule is only a reminder" | Reminders that are not pressure-tested are noise the agent routes around. |
| "I do not have time to pressure-test every rule" | Every rule you ship without pressure-testing is a rule the next agent under pressure will explain away. The time cost is paid later, by a worse agent. |
| "The Iron Law is enough; the table is optional" | The Iron Law states the principle. The table closes specific loopholes. An Iron Law with no table leaves the loopholes open. |
| "Pressure-testing is only for discipline rules" | Any rule that an agent has reason to bypass is a discipline rule, whether you labelled it that way or not. |

## Red Flags

Stop and pressure-test the rule if you catch yourself:

- Writing a Rationalizations Table from memory instead of from captured rationalizations
- Shipping a rule with fewer than 6 rows in the table
- Skipping the Announce-at-start line because "it feels cheesy"
- Weakening the Iron Law to sound less absolute ("usually" / "generally" / "when appropriate")
- Copying a rule from another config without running it through pressure-testing in the CCGM voice
- Telling yourself the rule is "covered well enough" by an existing rule without checking whether an agent under pressure would actually reach that existing rule first
- Adding a rule because it sounds good, not because you observed the failure mode it addresses

## When to Ask Before Shipping

Some rules should be reviewed by the user before landing, even after pressure-testing:

- Rules that contradict or narrow an existing rule
- Rules that add a new Iron Law in a domain that already has one
- Rules promoted from a repo CLAUDE.md that might reflect project-specific context rather than a global pattern
- Rules sourced from `/copycat` that introduce a new voice or structural convention not present in CCGM

If the rule falls into any of these categories, present the pressure-test results and the draft to the user before committing.
