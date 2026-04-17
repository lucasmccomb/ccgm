---
name: agent-native-audit
description: >
  Audit a codebase against the four agent-native principles (parity, granularity, composability, emergent capability) and return a scored report with concrete counts and fix recommendations. Dispatches eight parallel research subagents, two per principle, so one agent measures and one agent critiques. Use before shipping an agent-facing feature or when assessing whether a product is ready for an AI assistant layer.
  Triggers: agent-native audit, audit agents, audit for AI, score agent-friendliness, parity check, tool coverage audit.
disable-model-invocation: true
---

# /agent-native-audit - Agent-Native Architecture Audit

Score a codebase against the four agent-native principles defined in `modules/agent-native/rules/agent-native.md`. Produce a report with specific counts ("agent can do X of Y user actions"), named examples of violations, and concrete first-PR recommendations.

The report is the output. The skill does not modify code.

## When to Run

- Before adding an AI assistant, copilot, or "chat with the app" feature to an existing product.
- When designing the second or third major feature of an agent-first product (the first feature rarely needs the audit; the third reveals whether the foundation holds).
- As a quarterly check on a product marketed as agent-native.
- As a review step on a pull request that adds or modifies an agent tool surface.

Do NOT run for:

- Admin-only tooling with no agent consumers.
- Marketing sites, landing pages, or pure-content projects.
- Libraries and SDKs consumed only by human developers (the audit is for product surfaces, not code packages).

## Mode Selection

Parse `$ARGUMENTS` for a mode token (see `modules/subagent-patterns/rules/subagent-patterns.md` for the standard mode contract):

- `mode:full` (or no mode token) - eight parallel subagents, full scored report.
- `mode:report-only` - strictly read-only, no file writes even for the run artifact. Safe for concurrent runs.
- `mode:headless` - structured envelope output for skill-to-skill invocation (`/ce-review`, `/xplan`).

Full mode is the default. In full mode the skill writes a run artifact to `.agent-native-audit/{timestamp}.md` so the user can diff future runs.

## Inputs

If `$ARGUMENTS` contains a path, scope the audit to that directory. Otherwise the audit covers the repo root.

Optional steering in `$ARGUMENTS`:

- `focus:parity` / `focus:granularity` / `focus:composability` / `focus:emergent` - deep-dive one principle, skip the others.
- `baseline:{path}` - compare to a prior audit artifact, report deltas only.

## Phase 0: Codebase Triage

Before dispatching subagents, do a fast one-pass scan so each subagent starts from shared context:

1. Identify the tool/primitive surface. Common shapes:
   - MCP server registrations (`server.registerTool(...)`, `navigator.modelContext.registerTool(...)`)
   - tRPC / GraphQL / REST route handlers
   - Command or action dispatch tables
   - Redux / Zustand / Context actions that mutate global state

2. Identify the user-visible action surface. Common shapes:
   - Button `onClick` handlers in component files
   - Form `onSubmit` handlers
   - Keyboard shortcut tables
   - Router `POST` / `PATCH` / `DELETE` endpoints wired to UI flows

3. Write a short "Triage Notes" block to the run artifact:

   ```
   ## Triage
   - Tool surface: {count, location, framework}
   - User-action surface: {count, location, framework}
   - Primary entry points: {list}
   - Known agent consumers: {yes/no, names}
   ```

If the codebase has no identifiable tool surface (no MCP server, no agent-facing API), STOP and return:

```
Agent-native audit not applicable: no tool/primitive surface detected.
This audit scores products that expose tools to agents. The scanned code
appears to be {description}. If you intend this to be agent-native,
start by exposing a tool surface - see modules/agent-native/rules/agent-native.md
for design guidance.
```

## Phase 1: Parallel Analysis

Dispatch **eight Task agents in parallel** - two per principle. One agent per pair measures (counts, inventory); the other critiques (examples, violations, fixes). Use `subagent_type: "Explore"` and launch all eight in a single message so they run concurrently.

Pass paths, not file contents (see `modules/subagent-patterns/rules/subagent-patterns.md`). Each agent gets the triage summary, the principle text verbatim from `modules/agent-native/rules/agent-native.md`, and the scoped paths to analyze.

Every agent prompt must end with:

```
Return findings as the specified JSON object. Scope claims to what you
actually read; do not extrapolate from file names. End your report with
one of: DONE, DONE_WITH_CONCERNS, BLOCKED, NEEDS_CONTEXT.
```

### Agent 1A - Parity: Inventory

```
You are auditing {repo} for agent-native parity.

Principle: whatever a user can do in the UI, the agent can do via a tool.

Tasks:
1. Enumerate user-visible actions. Grep for onClick, onSubmit, form handlers,
   router POST/PATCH/DELETE handlers, keyboard shortcut tables. Produce a list.
2. Enumerate agent tools. Grep for the tool registration pattern identified
   in Phase 0 triage. Produce a list.
3. Attempt a pairwise mapping: for each user action, does a tool exist with
   the same semantics?

Return JSON:
{
  "user_actions": [{ "name": string, "file": string, "line": number }],
  "agent_tools": [{ "name": string, "file": string, "line": number }],
  "mapping": [{ "user_action": string, "tool": string | null }],
  "parity_ratio": "X of Y",
  "parity_percent": number
}
```

### Agent 1B - Parity: Violations

```
You are auditing {repo} for agent-native parity gaps.

Find the top 5 user actions that have no tool equivalent. For each, report:
- The user action (name, file, line)
- Why the gap matters (what outcome the agent cannot achieve)
- A proposed tool signature that would close the gap
- Estimated effort: trivial | moderate | significant

Return JSON:
{
  "top_gaps": [{
    "user_action": string,
    "file": string,
    "line": number,
    "why_matters": string,
    "proposed_tool": string,
    "effort": "trivial" | "moderate" | "significant"
  }]
}
```

### Agent 2A - Granularity: Primitive Inventory

```
You are auditing {repo} for agent-native granularity.

Principle: prefer atomic primitives. Features are outcomes an agent achieves
by composing primitives in a loop.

Tasks:
1. Classify each tool identified in Phase 0 as atomic | coarse | bundle.
   - atomic: one action, one resource, composable
   - coarse: accepts many optional parameters that change behavior modally
   - bundle: combines what should be two or more primitives
2. Identify primitives that appear to be missing - sequences of operations
   the agent would need to chain that no current tool supports.

Return JSON:
{
  "atomic_count": number,
  "coarse_count": number,
  "bundle_count": number,
  "examples": {
    "atomic": [string], "coarse": [string], "bundle": [string]
  },
  "missing_primitives": [{ "name": string, "rationale": string }]
}
```

### Agent 2B - Granularity: Critique

```
Find the top 3 granularity violations. For each, report:
- The tool name and signature
- Why it is too coarse or bundled
- A proposed refactor (split into N atomic tools, with signatures)
- A before/after sketch of how an agent would accomplish the same outcome

Return JSON:
{
  "violations": [{
    "tool": string,
    "category": "coarse" | "bundle",
    "why": string,
    "proposed_split": [string],
    "before_sketch": string,
    "after_sketch": string
  }]
}
```

### Agent 3A - Composability: Duplication Scan

```
You are auditing {repo} for composability.

Principle: new features become new prompts, not new code. Tool surfaces that
force teams to add a new tool per feature are not composable.

Tasks:
1. Scan tool implementations for duplicated logic. Two tools that call the
   same internal helper in the same way are candidates for composition.
2. Scan git history (last 90 days) for commits that added a new tool. For
   each, note whether the feature could plausibly have been a prompt over
   existing tools.

Return JSON:
{
  "duplication_pairs": [{ "tool_a": string, "tool_b": string, "shared_logic": string }],
  "recent_additions": [{
    "tool": string,
    "commit": string,
    "could_have_been_prompt": boolean,
    "reasoning": string
  }]
}
```

### Agent 3B - Composability: Critique

```
Identify the single highest-leverage composition opportunity - a set of
existing tools that, with one refactor or one new atomic primitive, would
eliminate a recurring need to add specialized tools.

Return JSON:
{
  "opportunity": {
    "current_tools": [string],
    "refactor_or_new_primitive": string,
    "unlocks": string,
    "effort": "trivial" | "moderate" | "significant",
    "expected_impact": string
  }
}
```

### Agent 4A - Emergent Capability: Evidence

```
You are auditing {repo} for emergent capability.

Principle: a mature agent-native surface lets the agent accomplish tasks the
product team did not explicitly design for.

Tasks:
1. Look for evidence in agent logs, session history, or test prompts of the
   agent solving tasks that map to no single tool. Common signals: a user
   prompt in the test suite that exercises a chain of 3+ tools.
2. Look for product tickets or issue comments that describe "the agent
   figured out how to do X" or similar.

If the repo has no such evidence, say so - this principle is the last to
mature and absence is expected in young products.

Return JSON:
{
  "evidence_found": boolean,
  "examples": [{ "task": string, "tools_chained": [string], "source": string }],
  "maturity_signal": "absent" | "early" | "established"
}
```

### Agent 4B - Emergent Capability: Recommendations

```
Based on the parity, granularity, and composability findings, name the two
or three prompts a team could try right now that would surface whether
emergent capability exists or not.

Return JSON:
{
  "probe_prompts": [{
    "prompt": string,
    "expected_tools_chained": [string],
    "success_criterion": string
  }]
}
```

## Phase 2: Score and Synthesize

Merge the eight reports into a single scorecard. Each principle scores 0 to 25, for a total of 100.

```
## Score

| Principle | Score | Band |
|---|---|---|
| Parity | {N}/25 | {band} |
| Granularity | {N}/25 | {band} |
| Composability | {N}/25 | {band} |
| Emergent Capability | {N}/25 | {band} |
| **Total** | **{N}/100** | **{band}** |

Bands: 0-10 absent, 11-17 emerging, 18-22 solid, 23-25 exemplary.
```

### Scoring Rubric

- **Parity**: map `parity_percent` to 0-25. 100% -> 25, 80% -> 20, 50% -> 12, 0% -> 0.
- **Granularity**: start at 25, subtract 2 per coarse tool, 4 per bundle tool, floor at 0.
- **Composability**: start at 25, subtract 2 per duplication pair, 3 per "could_have_been_prompt" commit, floor at 0.
- **Emergent Capability**: `absent` = 0, `early` = 12, `established` = 20, plus up to 5 bonus for multiple distinct emergent examples.

## Phase 3: Top-5 Findings and Recommendations

After the scorecard, write a Top-5 Findings section. Each finding has:

- **Principle** (one of the four)
- **Finding** (one sentence)
- **Evidence** (file:line references from agent reports)
- **Impact** (what the agent cannot do because of this)
- **Fix** (concrete first PR, effort-sized trivial/moderate/significant)

Prefer findings that are concrete, cheap, and visible to the agent. A trivial parity fix beats a significant emergent-capability plan in almost every case.

## Phase 4: Output

### Full mode

Write the full report to `.agent-native-audit/{YYYY-MM-DD-HHmm}.md` and print it to the user. If a prior audit exists, include a "Delta vs {prior date}" block at the top.

### Report-only mode

Print the full report. Do not write any files.

### Headless mode

Emit a structured envelope:

```
<<<AUDIT_REPORT_JSON>>>
{
  "total_score": number,
  "scores": { "parity": number, "granularity": number, "composability": number, "emergent": number },
  "top_findings": [{ ... }],
  "probe_prompts": [{ ... }]
}
<<<END_AUDIT_REPORT_JSON>>>
```

Then a one-line terminal: `Audit complete.`

## Guardrails

- Do not modify application code. This skill writes only to `.agent-native-audit/` (in full mode).
- Do not extrapolate from file names. Claims must be backed by a subagent's file:line evidence.
- Do not score principles the codebase cannot support. If there is no tool surface, the audit is not applicable (see Phase 0 stop condition).
- Preserve the four-state status protocol (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT) at the end of every subagent report and at the end of the skill's own final message.

## Related

- `modules/agent-native/rules/agent-native.md` - the four principles this skill audits against.
- `modules/subagent-patterns/rules/subagent-patterns.md` - the pass-paths-not-contents and skill-mode conventions this skill uses.
- `modules/agent-native/agents/reviewers/agent-native-reviewer.md` - the persona for when this skill is invoked as one lens inside a broader `/ce-review` orchestration.
