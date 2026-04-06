---
description: Comprehensive documentation audit and update - checks README, docs, TOC, onboarding, packages, and modules against actual codebase state
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, WebSearch, WebFetch, AskUserQuestion
argument-hint: [--scope readme|docs|toc|onboarding|all] [--dry-run]
---

# /docupdate - Comprehensive Documentation Update

Audits all documentation in a repository against its actual codebase state, then makes targeted updates. Works in any codebase type.

**What it checks:**
- README accuracy (packages, commands, setup steps, feature list)
- Table of contents vs actual headings
- Onboarding/setup flow vs actual requirements
- Package/dependency lists vs what is installed
- Module/feature docs vs what exists in source
- Available scripts vs what is documented

---

## Phase 0: Parse Arguments and Discover Repo

Extract from arguments:
- **`--scope <areas>`**: Limit to specific areas. Default: `all`
- **`--dry-run`**: Report gaps without making changes

Run the discovery script to gather all repo metadata in parallel:

```bash
bash ~/.claude/lib/docupdate-discover.sh
```

This outputs structured `=== SECTION ===` blocks: PROJECT, DOC_FILES, DOC_DIRS, ONBOARDING, STRUCTURE, SCRIPTS.

Build a **repo manifest** from the output - a mental model of:
- Project type (npm, Cargo, Python, Ruby, Go, monorepo, etc.)
- All documentation files and their purposes
- Key source directories (src/, lib/, packages/, modules/, apps/, etc.)
- Package manager and dependency files

---

## Phase 1: Parallel Audit

Launch all applicable audit agents in parallel using the Task tool. Each agent returns a structured list of **gaps** - things that are wrong, missing, or stale.

Pass each agent: the repo manifest from Phase 0.

---

### Audit Agent 1: README Accuracy

Read the README thoroughly. Cross-reference against the actual codebase.

**Check each of the following:**

**Feature/capability claims:**
- List every feature or capability mentioned in the README
- For each, verify it actually exists in source (grep for key identifiers, check file presence)
- Flag: features mentioned that no longer exist, features that exist but aren't mentioned

**Package/dependency tables:**
- Extract every package name mentioned in README
- Compare against actual `package.json` dependencies, `requirements.txt`, `Cargo.toml`, etc.
- Flag: packages in README that aren't installed, packages installed that aren't documented (major ones only - skip dev utilities)

**Installation/setup commands:**
- Extract every `npm install`, `pip install`, `brew install`, `cargo build`, etc. command
- Verify each command would still work (package names, flags, paths)
- Flag: commands that reference packages/tools not in dependencies, outdated flags

**Version references:**
- Check any pinned versions (Node 18, Python 3.11, etc.)
- Flag: versions that conflict with lockfiles, engines field, or .nvmrc/.python-version

**Links and URLs:**
- Check internal links point to files that exist
- Flag: broken internal links (external links: skip unless obviously dead)

Return: List of gaps with file path, line number, current text, and what's wrong.

---

### Audit Agent 2: Table of Contents

Find every document that has a table of contents (look for `## Contents`, `## Table of Contents`, lists of anchor links at the top of files).

For each document with a TOC:

```bash
# Extract TOC entries
grep -n "^\s*[-*]\s*\[" FILE | head -50

# Extract actual headings
grep -n "^##\|^###\|^####" FILE
```

**Check:**
- Every TOC entry has a matching heading (same text, same level)
- Every `##` and `###` heading has a TOC entry (if TOC exists)
- Anchor links in TOC match the heading slugs (lowercase, hyphens, no special chars)
- TOC order matches document order

Return: List of gaps with file path, TOC line, and what's mismatched/missing.

---

### Audit Agent 3: Onboarding and Setup Flow

Find any document describing how to get started, set up the project, or run it for the first time.

```bash
# Common onboarding locations
find . -maxdepth 4 -name "*.md" -not -path "*/node_modules/*" -not -path "*/.git/*" | xargs grep -l -i "getting started\|installation\|setup\|first run\|quick start" 2>/dev/null

# Check for interactive setup scripts
find . -maxdepth 2 -name "*.sh" -o -name "setup*" -o -name "install*" -o -name "bootstrap*" 2>/dev/null | grep -v node_modules
```

For each onboarding document:

**Prerequisites section:**
- List every tool/runtime the docs say to install (Node, Python, Docker, etc.)
- Cross-check against: `.nvmrc`, `.python-version`, `Dockerfile`, `docker-compose.yml`, `engines` in `package.json`
- Flag: prerequisites mentioned that aren't actually required, required tools not mentioned

**Environment variables:**
- List every env var mentioned in docs
- Compare against `.env.example`, `.env.template`, or any `process.env.X` / `os.environ.get("X")` patterns
- Flag: vars in docs not in example file, vars in example file not in docs

**Setup steps:**
- Walk through each numbered/bulleted setup step
- Verify each command/file/step is still valid
- Flag: steps that reference missing files, removed scripts, or changed command names

**Scripts documented:**
- Compare `npm run` / `make` / `rake` commands in docs against `package.json scripts`, `Makefile`, `Rakefile`
- Flag: documented scripts that no longer exist, commonly-used scripts not documented

Return: List of gaps with file path, section, and what's wrong.

---

### Audit Agent 4: Module and Feature Coverage

Understand the project's internal structure - what modules, features, packages, or components exist - and check if they're documented.

```bash
# For monorepos: find workspace packages
cat package.json 2>/dev/null | jq '.workspaces // empty'
ls packages/ apps/ libs/ modules/ 2>/dev/null

# For single packages: find major source areas
ls src/ lib/ app/ 2>/dev/null

# Find any internal module documentation
find . -name "module.json" -o -name "MODULE.md" -not -path "*/node_modules/*" 2>/dev/null | head -20
```

**Check:**
- For each top-level package/module, is there a corresponding section in README or docs/?
- For each documented module/package, does the source actually exist?
- Are there major new directories (added recently to git) that aren't documented?

```bash
# Check recently added top-level dirs (rough proxy for "new and undocumented")
git log --diff-filter=A --name-only --format="" --since="6 months ago" -- "src/*" "packages/*" "apps/*" "modules/*" 2>/dev/null | grep "/" | cut -d/ -f1-2 | sort -u | head -20
```

Return: List of modules/packages that are undocumented or have stale docs.

---

## Phase 2: Synthesize Audit Results

Once all agents return, compile a **Documentation Gap Report**:

```
## Documentation Gap Report

### Critical (incorrect - would mislead users)
- [file:line] Description of the problem
- ...

### Missing (exists in code, not in docs)
- [file] Section/item that needs to be added
- ...

### Stale (in docs, removed from code)
- [file:line] Content that should be removed or updated
- ...

### TOC Issues
- [file] Missing/mismatched entries
- ...

### Minor (cleanup, formatting, broken links)
- ...
```

If `--dry-run` was passed, print the report and stop here.

---

## Phase 3: Confirm Scope

Present the gap report to the user.

Ask with AskUserQuestion:

> "I found N documentation gaps. Which should I fix now?"

Options:
- **Fix all** - Apply all fixes (recommended if gaps are small)
- **Critical and missing only** - Skip minor cleanup
- **Show me each fix first** - Walk through interactively
- **Just the report** - Stop here, I'll fix manually

If "Show me each fix first": present each proposed change and wait for approval before applying.

---

## Phase 4: Apply Updates

For each approved fix, make **targeted edits** - do not rewrite sections that are correct.

### Principles

- **Surgical edits only**: change the specific line/paragraph that's wrong, not the surrounding text
- **Match the existing voice**: if the README is terse, keep it terse; if it's detailed, match that
- **Add, don't replace**: when adding missing items, insert them in the logical place rather than restructuring
- **Preserve formatting**: match existing table format, list style, header level
- **No padding**: don't add filler text, marketing copy, or AI-sounding prose

### TOC updates

When updating a TOC, regenerate only the entries that changed. Preserve anchor format exactly:
- GitHub: `[Heading Text](#heading-text)` (lowercase, hyphens, strip special chars)
- Check the existing TOC format and match it exactly

### Package list updates

When updating package tables, match the existing column structure. Don't add columns that weren't there.

### Onboarding updates

When adding missing prerequisites or env vars, insert them in the correct section in the logical order (alphabetical for env vars, install-order for prerequisites).

---

## Phase 5: Summary

After applying all updates:

1. List every file changed with a one-line description of what changed
2. Note any gaps that were identified but NOT fixed (and why)
3. Suggest follow-up: "Run `/docupdate --scope toc` after adding new sections"
