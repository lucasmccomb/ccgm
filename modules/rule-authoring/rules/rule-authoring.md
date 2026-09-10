# Rule Authoring

A rule is not done until it holds under pressure. A rule that reads well in isolation but fails the first time an agent has a good excuse to skip it is a suggestion. Pressure-test every discipline rule against realistic rationalizations before it ships, and keep the shipped text lean: every rule loads into every session and every subagent, so each sentence is paid for on every request.

## Scope

This rule governs discipline rules (`rules/*.md`) that enforce a non-negotiable behavior, rules promoted via `/promote-rule`, and rules sourced from `/copycat`. It does not govern reference tables with no pressure to bypass, command files (see `skill-authoring`), or project CLAUDE.md entries about paths and commands. If an agent would ever rationalize past the rule, pressure-test it; if the rule is purely informational, skip the test.

## What a Rule Contains

1. **The rule, in one plain sentence, first.** Declarative, not shouted. "Write a failing test before production code." An all-caps slogan, a `CRITICAL:` prefix, or a "violating the letter is violating the spirit" clause adds emphasis, not compliance; frontier models follow instructions literally and pay for emphasis with verbosity and extra tool calls.
2. **The mechanism, if there is one.** The hook or gate that enforces the rule, its escape hatch, and the exact command that satisfies it. A rule backed by a hook needs less prose than one that is not.
3. **The facts.** Commands, paths, tables, thresholds, the one-clause reason behind each prohibition. A prohibition with a stated reason survives review; a bare "NEVER" does not.
4. **Nothing that narrates.** No announce-at-start line (it costs an output sentence on every task, and three rules can fire at once), no fixed step choreography the model must recite, no incident retold in full. Keep the gate the incident produced; cut the story to one clause, and never a date, PR number, or version.

Optional, only when pressure-testing shows the rule fails without it:

- A **rationalizations table** of at most four rows, each quoting a rationalization captured verbatim from a pressure-test run, never invented. Delete rows that restate the rule.
- A **red flags list** of self-catch phrases the agent actually used while slipping. Delete entries that restate a table row.

Rules that govern subagent work point at the four-state status protocol in `subagent-patterns.md` rather than restating it.

## Voice

Imperative or infinitive, no second-person "you" in body prose (a rationalizations table quotes the agent in first person by design). Name the specific failure mode, not the category: "agents under pressure skip verification" is usable; "ensure quality" is not. Never include AI-attribution trailers or "generated with" footers in rule content.

## Contradictions

Before shipping, grep the other always-loaded rules and the harness's own behavior for the same topic. Two instructions that disagree are followed arbitrarily, and a rule that claims to "override system defaults" cannot: it only adds noise. Resolve the conflict by deleting one side or by changing the setting the harness exposes.

## Authoring Workflow

1. Write the one-sentence rule and identify the mechanism, if any.
2. Draft the body: mechanism, facts, reasons.
3. Pressure-test with `/pressure-test <rule-file>` or the loop in `pressure-testing.md`: 5 to 10 adversarial scenarios, run with and without the rule, rationalizations captured verbatim.
4. Only if the rule fails, add the rows and red flags the captured language justifies, then re-test until it holds in at least 4 of 5 scenarios.
5. Measure the file: if it grew past what the facts need, cut before shipping.

## When to Ask Before Shipping

Present the pressure-test results and the draft to the user before committing when the rule contradicts or narrows an existing rule, adds a second rule in a domain that already has one, is promoted from a repo CLAUDE.md and might be project-specific, or introduces a new voice or structure from `/copycat`.
