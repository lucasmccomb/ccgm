---
description: Maintain the learnings store - dedup, retire stale entries, reconcile with legacy MEMORY.md
allowed-tools: Agent
---

# /consolidate - Learnings Maintenance

Use the Agent tool to execute this workflow:

- **model**: sonnet
- **description**: learnings consolidation

Pass the agent all workflow instructions below.

After the agent completes, relay its report to the user exactly as received.

---

## Workflow Instructions

Review the JSONL learnings store AND any legacy MEMORY.md files. Dedup, flag contradictions, retire stale entries, and keep the store tight.

### 1. Snapshot the Store

```bash
# Projects with learnings
ccgm-learnings-search --list-projects

# Dump current project (incl stale)
ccgm-learnings-search --include-stale --max 200 --budget 100000 --format jsonl
```

Also read any legacy MEMORY.md at `~/.claude/projects/*/memory/MEMORY.md` and the linked topic files. Note which entries exist only in MEMORY.md (not yet migrated).

### 2. Categorize Issues

For each entry, check:

**Duplicates** — Same pattern, different ids. Keep the highest-confidence or most recently verified, `deprecate` the others (do not delete; the JSONL is append-only).

**Contradictions** — Two entries give conflicting guidance. Determine which is correct (check the codebase). Record a contradiction on the incorrect one (`ccgm-learnings-log contradict <id>`) or deprecate it outright.

**Stale anchors** — Entry has `files[]` but one or more files no longer exist. Verify the pattern still applies. If yes, update anchors via a new entry (append; mark old one deprecated). If no, deprecate.

**Below threshold** — Effective confidence < 2.0 after decay. If the pattern is still true, reinforce (`verify`). If obsolete, `deprecate` to remove from reads without losing history.

**Too specific** — One-incident entries that will not recur. Deprecate.

**Too vague** — Entries that provide no actionable guidance. Deprecate and (if the underlying insight is real) log a concrete replacement.

### 3. Apply Changes

Use the CLI, not direct file edits (append-only log):

```bash
ccgm-learnings-log verify <id>
ccgm-learnings-log contradict <id>
ccgm-learnings-log deprecate <id>

# For new entries replacing a deprecated one
ccgm-learnings-log --type <type> --content "<replacement>" ...
```

For MEMORY.md entries worth keeping, port them via `ccgm-learnings-log --from-json '...'` and then remove the stale markdown.

### 4. Report

```
## Learnings Consolidation Report

- **Entries reviewed**: N (JSONL) + N (MEMORY.md)
- **Deprecated**: N (list ids + one-line reason)
- **Contradictions recorded**: N
- **Verifications**: N (refreshed last_verified)
- **Migrated from MEMORY.md**: N
- **New replacements written**: N (list ids)
- **Unresolved**: (any patterns that need human input)
```
