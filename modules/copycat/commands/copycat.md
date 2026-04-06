---
description: Analyze external Claude Code config repos to find useful patterns, rules, and techniques worth adopting into CCGM
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, WebSearch, WebFetch, AskUserQuestion
argument-hint: <github-url-or-local-path>
---

# /copycat - Analyze External Claude Config Repos

Analyzes a Claude Code configuration repo (CLAUDE.md collections, dotfiles, modular config systems) and identifies patterns, rules, commands, and techniques worth incorporating into CCGM. Walks you through findings interactively.

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Arguments and Acquire Repo

Extract the target from arguments. Accepts:
- **GitHub URL**: `https://github.com/owner/repo` or `owner/repo` shorthand
- **Local path**: `/path/to/repo` or `~/path/to/repo`

If no argument is provided, use AskUserQuestion to ask:

> "What Claude Code config repo should I analyze? Provide a GitHub URL (e.g., `owner/repo`) or a local path."

### Acquire the Repo

**If GitHub URL or shorthand:**

```bash
# Clone to a temp directory
TMPDIR=$(mktemp -d)
git clone --depth 1 "https://github.com/${OWNER_REPO}.git" "$TMPDIR/target-repo" 2>&1
TARGET="$TMPDIR/target-repo"
```

**If local path:**

```bash
TARGET="<provided-path>"
# Verify it exists
ls "$TARGET" >/dev/null 2>&1
```

Store the target path for all subsequent phases. Note the repo name for display purposes.

---

## Phase 1: Structural Discovery

Map the target repo's structure. Run these in parallel using Bash:

### 1a. Find Configuration Files

```bash
# CLAUDE.md files (root and nested)
find "$TARGET" -name "CLAUDE.md" -o -name "claude.md" 2>/dev/null

# Rules files
find "$TARGET" -name "*.md" -path "*/rules/*" 2>/dev/null
find "$TARGET" -name "*.md" -path "*/.claude/rules/*" 2>/dev/null

# Command files
find "$TARGET" -name "*.md" -path "*/commands/*" 2>/dev/null
find "$TARGET" -name "*.md" -path "*/.claude/commands/*" 2>/dev/null

# Hook files
find "$TARGET" -name "*.py" -path "*/hooks/*" -o -name "*.sh" -path "*/hooks/*" -o -name "*.js" -path "*/hooks/*" 2>/dev/null

# Settings files
find "$TARGET" -name "settings.json" -o -name "settings.local.json" 2>/dev/null

# MCP config
find "$TARGET" -name "mcp.json" -o -name ".mcp.json" 2>/dev/null

# Any module manifests (if modular like CCGM)
find "$TARGET" -name "module.json" -o -name "manifest.json" 2>/dev/null
```

### 1b. Get Repo Metadata

```bash
# README for context
cat "$TARGET/README.md" 2>/dev/null | head -200

# Repo structure overview
find "$TARGET" -maxdepth 3 -not -path "*/.git/*" -not -path "*/node_modules/*" | head -100

# Any install/setup scripts
find "$TARGET" -maxdepth 2 \( -name "install*" -o -name "setup*" -o -name "start*" -o -name "init*" \) -not -path "*/.git/*" 2>/dev/null
```

### 1c. Inventory CCGM's Current State

Read the current CCGM module list for comparison:

```bash
# List all CCGM modules
ls ~/code/ccgm-repos/ccgm-1/modules/ 2>/dev/null || ls modules/ 2>/dev/null

# List all CCGM rule files
find ~/.claude/rules/ -name "*.md" 2>/dev/null | sort

# List all CCGM commands
find ~/.claude/commands/ -name "*.md" 2>/dev/null | sort
```

Build a mental model of:
- **Target repo type**: monolithic CLAUDE.md, dotfile collection, modular system, or hybrid
- **Content categories**: rules, commands, hooks, MCP configs, settings, prompts
- **Scale**: how many files, how much content

---

## Phase 2: Deep Analysis (Parallel Agents)

Launch analysis agents in parallel using the Task tool. Set model to **sonnet** for all agents.

Each agent receives:
1. The target repo path
2. A specific analysis focus
3. The list of existing CCGM modules/rules for comparison

### Agent 1: Rules and Behavioral Instructions

Read ALL rule files, CLAUDE.md files, and behavioral instruction files in the target repo.

For each rule/instruction found, extract:
- **Topic**: What area does it cover? (git workflow, code quality, debugging, testing, etc.)
- **Content summary**: 2-3 sentence summary of the rule
- **Novelty**: Does CCGM already cover this topic? If yes, which module?
- **Quality assessment**: Is this rule well-written, specific, and actionable? Or is it vague/generic?
- **Adoption recommendation**: One of:
  - **NEW** - CCGM has no coverage of this topic. Worth adding.
  - **BETTER** - CCGM covers this, but the target repo's version is better or has useful additions
  - **MERGE** - Both have good content. Best approach is combining insights from both.
  - **SKIP** - CCGM's existing coverage is equal or better. Nothing to gain.
  - **INTERESTING** - Not directly applicable but contains a novel idea worth noting

For CCGM comparison, read the corresponding CCGM rule files when they exist to make an informed comparison. Do not guess - read the actual content.

Return a structured list sorted by recommendation (NEW first, then BETTER, then MERGE, then INTERESTING, then SKIP).

### Agent 2: Commands and Skills

Read ALL command/skill files in the target repo.

For each command found, extract:
- **Command name**: The slash command or skill name
- **Purpose**: What it does in 1-2 sentences
- **Implementation approach**: How it works (single agent, parallel agents, interactive, etc.)
- **Novelty**: Does CCGM have an equivalent? If yes, which command?
- **Quality assessment**: Is the prompt well-structured? Does it handle edge cases?
- **Adoption recommendation**: NEW / BETTER / MERGE / SKIP / INTERESTING (same criteria as Agent 1)

Return a structured list sorted by recommendation.

### Agent 3: Hooks, Settings, and MCP Configuration

Analyze all hook files, settings configurations, and MCP server configs.

For hooks:
- **Trigger**: What event fires this hook?
- **Behavior**: What does it do?
- **Novelty**: Does CCGM have equivalent hook behavior?

For settings:
- **Permissions model**: What tool permissions are configured?
- **Notable patterns**: Any unusual or clever permission configurations?

For MCP:
- **Servers configured**: What MCP servers are included?
- **Novel servers**: Any MCP servers CCGM doesn't reference?

Return findings with adoption recommendations.

### Agent 4: Novel Patterns and Architecture

Look at the target repo holistically for patterns CCGM could learn from:

- **Organization approach**: How is config organized? Any structural improvements over CCGM's module system?
- **Onboarding experience**: How easy is it to get started? Better or worse than CCGM?
- **Modularity**: Is it more or less modular? Any good ideas about composability?
- **Documentation patterns**: Any clever documentation approaches?
- **Unique concepts**: Anything genuinely novel that doesn't fit the other categories?
- **Anti-patterns**: Anything the target repo does poorly that CCGM should avoid?

Return a narrative analysis, not a list.

---

## Phase 3: Synthesize and Rank

Once all agents return, compile findings into a ranked report.

### Ranking Criteria

Score each finding on two axes:
1. **Impact** (1-5): How much would this improve CCGM?
   - 5: Fills a major gap or significantly improves a core workflow
   - 3: Useful addition that improves a specific area
   - 1: Minor tweak or stylistic preference
2. **Effort** (1-5): How much work to incorporate?
   - 1: Copy/adapt a single rule file
   - 3: Requires creating a new module with multiple files
   - 5: Requires architectural changes to CCGM

### Priority Groups

Sort findings into:

**High Priority** (Impact >= 4, any Effort):
Items that would meaningfully improve CCGM. These are worth the effort regardless.

**Quick Wins** (Impact >= 2, Effort <= 2):
Easy to adopt with clear benefit. Do these as a batch.

**Worth Considering** (Impact >= 3, Effort >= 3):
Good ideas that need more thought or design work before adopting.

**Reference Only** (Impact <= 2 or SKIP/INTERESTING):
Not worth acting on now, but good to know about.

---

## Phase 4: Interactive Walkthrough

Present findings to the user group by group, starting with High Priority.

For each group, present a summary table:

```
## High Priority Findings

| # | Topic | Source | Recommendation | Impact | Effort |
|---|-------|--------|----------------|--------|--------|
| 1 | {topic} | {file in target repo} | NEW | 5 | 2 |
| 2 | {topic} | {file in target repo} | BETTER | 4 | 1 |
```

Then for each finding, show:
1. **What the target repo does** (relevant excerpt, 5-15 lines max)
2. **What CCGM currently does** (if applicable, brief summary)
3. **Proposed action**: Exactly what to do (create module, edit existing rule, add to existing module)

After presenting each group, ask with AskUserQuestion:

> "Which of these should I act on? (Enter numbers, 'all', 'none', or 'next' to see the next group)"

Options:
- Specific numbers (e.g., "1, 3, 5")
- "all" - act on everything in this group
- "none" - skip this group
- "next" - skip to the next priority group
- "done" - stop the walkthrough, act on what was already approved

---

## Phase 5: Implementation

For each approved finding, create a GitHub issue in the CCGM repo:

```bash
gh issue create \
  --title "copycat: {brief description of the improvement}" \
  --body "$(cat <<'ISSUE_EOF'
## Source

Identified by `/copycat` analysis of `{target-repo-name}`.

## Finding

{Description of what the target repo does and why it's worth adopting}

## Current CCGM State

{What CCGM currently does in this area, or "No coverage"}

## Proposed Change

{Specific action: new module, edit to existing rule, new command, etc.}

## Source Reference

{Path to the relevant file in the target repo}
ISSUE_EOF
)"
```

After creating all issues, present a summary:

```
## Copycat Analysis Complete

**Source**: {target-repo-name} ({url-or-path})
**Findings**: {total count}
**Issues created**: {count} ({list issue numbers})
**Skipped**: {count}

### Created Issues
- #{number}: {title}
- #{number}: {title}
...

These issues are ready for implementation. Run them through the normal workflow
(branch, implement, PR, merge) or batch them with `/mawf`.
```

---

## Cleanup

If a temp directory was created for cloning:

```bash
rm -rf "$TMPDIR"
```

---

## Edge Cases

### Target repo is a single CLAUDE.md file
Some repos are just one large CLAUDE.md. Treat it as a monolithic rules file - Agent 1 does the heavy lifting, other agents may have nothing to analyze. That's fine.

### Target repo uses a different config structure
Not all repos follow `.claude/` conventions. Adapt discovery to whatever structure exists. Common patterns:
- `.cursorrules` or `.windsurfrules` files (Cursor/Windsurf config - still useful, different format)
- Root-level `CLAUDE.md` only
- `prompts/` or `instructions/` directories
- YAML-based configuration

### Target repo is very large
If the repo has > 50 config files, limit Agent analysis to the 30 most recently modified files. Note the truncation in the output.

### No useful findings
If analysis reveals nothing worth adopting, say so directly. Don't fabricate recommendations to fill space.
