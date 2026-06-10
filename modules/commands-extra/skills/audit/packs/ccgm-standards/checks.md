# checks.md — CCGM Project Standards Pack

---

## Scope

This pack audits repos for two project-convention gaps surfaced by the CCGM ruleset:
code that violates rules explicitly declared in the repo's own `CLAUDE.md` or `AGENTS.md`
project standards file; and MCP server tool definitions that are missing the safety
annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) required
by the CCGM MCP development rules.

Both checks are LLM-detected and self-scope to repos where the relevant signals exist:
`ccgm/project-standards-conformance` only runs when a `CLAUDE.md` or `AGENTS.md` file is
present; `ccgm/mcp-tool-annotations` only runs when MCP server registration patterns are
detected in source.

This pack does NOT cover general code quality, security, environment-variable hygiene
(covered by `ccgm-hygiene`), or TODO markers — those belong in their respective packs.

**Pack ID:** `ccgm/ccgm-standards`
**Applies when:** `always`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | Both checks are self-scoping via their LLM instructions. On repos with no `CLAUDE.md`/`AGENTS.md` and no MCP server code, both checks produce zero findings. Ecosystem-gating would miss repos written in non-standard stacks. |

---

## Checks

---

### `ccgm/project-standards-conformance`

**Severity:** `medium`
**Confidence:** `low`
**Detection:** `llm`

#### Detection

The LLM agent reads the repo's `CLAUDE.md` or `AGENTS.md` (whichever exists), extracts
explicit, actionable rules stated there, then scans recent source changes for code that
visibly violates those rules. The check produces findings only when (a) a project standards
file exists and (b) a violation is clearly detectable in the diff or source without
deep runtime reasoning.

**Self-scoping:** If no `CLAUDE.md` or `AGENTS.md` file exists at the repo root, produce
ZERO findings. Stop here.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
You are checking whether recently changed source files violate rules declared in this
repo's project standards file (CLAUDE.md or AGENTS.md).

Step 1 — Self-scope:
  - Check whether CLAUDE.md or AGENTS.md exists at the repo root.
  - If neither exists, produce ZERO findings and stop.

Step 2 — Extract rules:
  - Read the project standards file.
  - Identify explicit, actionable, DETECTABLE rules. Focus on rules that produce a
    clear code-level signal:
      - "Never use git stash" → flag if git stash appears in scripts
      - "Always quote PostgreSQL reserved keywords in migrations" → flag unquoted keywords
      - "New env vars must be added to .env.example" → covered by env-example-drift check
      - "Run tests before pushing" → not statically detectable; skip
      - "Use functional React components only" → flag class components
  - Skip rules that are policy/process (require reading developer intent) or that are
    covered by other checks in this audit (env-example-drift, shipped-todo-marker, etc.)

Step 3 — Scan for violations:
  - For each detectable rule, scan the source files in scope (recently changed files
    preferred; fall back to full source if no diff is available).
  - Report only violations you are confident about. Ambiguous cases should not be flagged.

Step 4 — Report:
  For each violation:
    FINDING: ccgm/project-standards-conformance
    file: <file>:<line>
    message: "Violates rule in CLAUDE.md: '<quoted rule text>' — <specific violation>"

Do NOT flag:
  - Violations in test fixtures, example files, or documentation (unless the rule
    explicitly covers them).
  - Violations that are already covered by more specific checks in this audit run.
  - Ambiguous cases where you are less than 70% confident.
  - Rules about workflow, branching, or commit messages (not source-code rules).
```

#### Spine Wiring

```yaml
check_id: ccgm/project-standards-conformance
detection: llm
```

#### Severity / Confidence

**Severity rationale:** A project standards file is the team's explicit agreement on how
the codebase should be maintained. Violating it directly undermines the declared contract.
Medium severity: the violation may not cause runtime failures but degrades maintainability
and team trust in the process.

**Confidence rationale:** The LLM must extract rules from a natural-language document and
then find violations — two inference steps, each with potential for error. Rules vary widely
in precision and detectability. Low confidence: findings are plausible but require human
review before acting. The check is most valuable as a signal, not a gate.

**Rubric entry:** `ccgm/project-standards-conformance`

#### Fixture

**True positive** (repo has `CLAUDE.md` that says "Use functional React components only"):

```tsx
// FINDS: class component violates the rule declared in CLAUDE.md
import React from 'react';

class UserCard extends React.Component<{ name: string }> {
  render() {
    return <div>{this.props.name}</div>;
  }
}
```

**True negative** (should produce NO finding):

```tsx
// OK: functional component — conforms to the rule
import React from 'react';

export function UserCard({ name }: { name: string }) {
  return <div>{name}</div>;
}
```

---

### `ccgm/mcp-tool-annotations`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for MCP server tool registration calls — both the Web MCP Declarative
API (`navigator.modelContext.registerTool(...)`) and the MCP SDK server pattern
(`server.tool(...)` from `@modelcontextprotocol/sdk`) — and flags any tool definition that
is missing all four safety annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`. Per the CCGM MCP development rules, these annotations must be set on every
tool so clients can make safety decisions.

**Self-scoping:** If the repo contains no patterns matching `registerTool`, `server.tool`,
`navigator.modelContext`, or imports from `@modelcontextprotocol/sdk`, produce ZERO findings.
Stop here.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard linter rule for MCP annotations)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
You are checking for missing safety annotations on MCP server tool definitions.

Step 1 — Self-scope:
  - Search the repo for any of these patterns:
      - navigator.modelContext.registerTool(
      - server.tool(
      - import ... from '@modelcontextprotocol/sdk'
      - require('@modelcontextprotocol/sdk')
  - If none of these patterns exist in any source file, produce ZERO findings and stop.

Step 2 — Locate tool definitions:
  - Find every MCP tool registration call. Include:
      - navigator.modelContext.registerTool({ name: '...', ... })
      - server.tool('name', schema, handler)  — MCP SDK server pattern
      - Any wrapper function that delegates to one of the above
  - For each tool definition, determine whether it includes ALL FOUR of:
      readOnlyHint    — does not modify external state
      destructiveHint — does not delete or overwrite
      idempotentHint  — safe to retry without side effects
      openWorldHint   — interacts with external services

Step 3 — Report:
  For each tool definition missing one or more annotations:
    FINDING: ccgm/mcp-tool-annotations
    file: <file>:<line>
    message: "MCP tool '<tool-name>' missing annotations: <list of missing keys>"

  If a tool has some but not all annotations, report only the missing ones.
  If a tool definition uses a spread or variable for annotations and you cannot
  determine the complete set, flag it with a note: "annotation completeness
  cannot be statically determined".

Do NOT flag:
  - Client-side MCP tool invocation calls (only flag server-side registration).
  - Test mocks or stub implementations in test files.
  - Tools inside documentation examples (README code blocks, .md files).
```

#### Spine Wiring

```yaml
check_id: ccgm/mcp-tool-annotations
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Missing annotations mean clients cannot determine whether a tool
is safe to call automatically, safe to retry, or whether it interacts with external services.
This degrades safety and discoverability but does not directly cause data loss or security
issues. Low severity: a metadata gap that harms integration quality.

**Confidence rationale:** The LLM can reliably identify `registerTool` and `server.tool`
call sites. The annotation keys are well-defined. The main uncertainty is dynamic annotation
objects (e.g., spreading a config object) where static inspection is insufficient. Medium
confidence: reliable for straightforward patterns; flagging dynamic spread cases requires
judgment.

**Rubric entry:** `ccgm/mcp-tool-annotations`

#### Fixture

**True positive** (`src/server.ts` with MCP SDK):

```ts
// FINDS: tool registered without any safety annotations
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';

const server = new McpServer({ name: 'my-server', version: '1.0.0' });

server.tool(
  'search_files',
  { query: z.string() },
  async ({ query }) => {
    return { content: [{ type: 'text', text: await searchFiles(query) }] };
  }
  // Missing: readOnlyHint, destructiveHint, idempotentHint, openWorldHint
);
```

**True negative** (should produce NO finding):

```ts
// OK: all four annotations present
server.tool(
  'search_files',
  { query: z.string() },
  async ({ query }) => {
    return { content: [{ type: 'text', text: await searchFiles(query) }] };
  },
  {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false
  }
);
```

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
