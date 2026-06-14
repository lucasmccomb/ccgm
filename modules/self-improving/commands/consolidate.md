---
description: Maintain the learnings store via delta-first ops (supersede over rewrite) - dedup, retire stale entries, reconcile with legacy MEMORY.md
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

### 0. Delta-First Policy (ACE) — read before touching anything

Consolidation is **additive context curation, not destructive rewriting**. Inspired by Agentic Context Engineering (ACE, arXiv:2510.04618): incremental delta updates that grow and refine context preserve more facts than periodic whole-entry rewrites, which collapse detail and cause "context drift." A monolithic rewrite throws away the entry's `uses`, `contradictions`, and `last_verified` history and severs the audit trail. Avoid it.

Choose the **least destructive** operation that resolves the issue, in this strict order of preference:

1. **Targeted counter delta** — `verify` (still true) or `contradict` (one conflicting data point). Mutates only counters; content untouched. **Preferred whenever the outcome is "is this still right?"**
2. **Supersede (atomic, bidirectional, audit-preserving)** — when an entry's *content* needs to change but the idea persists: refined wording, updated anchors, an evolved pattern, a changed preference. `supersede` links old↔new (`supersedes` / `superseded_by`), keeps both rows, and lets a reader walk the chain. **This is the default for any content change.** It inherits `type` / `confidence` / `tags` / `files` from the old entry unless you override them, so the common "same idea, better wording / new file path" case is a one-liner.
3. **Deprecate** — only when the learning is *outright wrong with no replacement*, or genuinely obsolete (one-off, too vague to salvage). Deprecate says "this is wrong"; supersede says "this was replaced by X." Do not reach for deprecate when a replacement exists — supersede instead.
4. **Whole-entry content rewrite** — last resort, only when supersede genuinely does not fit. **Whenever you rewrite an entry's content, you MUST first run the compaction fact-guard** (see step 3) and abort the rewrite if it fails.

Hard rules:
- **Never `deprecate` + log a fresh replacement when you mean to supersede.** That severs the audit chain and discards reuse history. Use `supersede`.
- **Never rewrite content without running `compact_preserves_facts`.** Model-driven compaction silently drops identifiers, dates, and table names.
- Direct JSONL edits are forbidden (append-only log). Use the CLI / library only.

### 1. Snapshot the Store

```bash
# Projects with learnings
ccgm-learnings-search --list-projects

# Dump current project (incl stale)
ccgm-learnings-search --include-stale --max 200 --budget 100000 --format jsonl
```

Also read any legacy MEMORY.md at `~/.claude/projects/*/memory/MEMORY.md` and the linked topic files. Note which entries exist only in MEMORY.md (not yet migrated).

### 2. Categorize Issues

For each entry, pick the **least destructive** fix from the policy in step 0:

**Duplicates** — Same pattern, different ids. Keep the highest-confidence / most recently verified entry. For each loser whose content is genuinely covered by the keeper, `supersede` the loser *into* the keeper's idea (preserves the chain) — or, if the loser is pure noise, `deprecate` it. Do not invent a brand-new entry; one of the existing ones is the survivor.

**Contradictions** — Two entries give conflicting guidance. Determine which is correct (check the codebase). Record a `contradict` on the incorrect one (cheapest delta). If you have the corrected guidance in hand, `supersede` the wrong entry with the right one rather than deprecating it.

**Stale anchors** — Entry has `files[]` but one or more files no longer exist. Verify the pattern still applies. If yes, **`supersede` the entry with the same content and corrected `files`** (this is the canonical supersede use — it keeps the chain and reuse history; do NOT deprecate + re-log). If the pattern no longer applies, `deprecate`.

**Below threshold** — Effective confidence < 2.0 after decay. If the pattern is still true, reinforce with `verify` (refreshes `last_verified`, slows decay). If obsolete, `deprecate`.

**Too specific** — One-incident entries that will not recur. `deprecate`.

**Too vague** — Entries that provide no actionable guidance. If you can write the concrete version, `supersede` the vague entry with it. If there is no real insight to salvage, `deprecate`.

### 3. Apply Changes

Use the CLI, not direct file edits (append-only log). Apply operations in the delta-first order from step 0.

**Counter deltas (cheapest — content untouched):**

```bash
ccgm-learnings-log verify <id>       # still true: bump uses + refresh last_verified
ccgm-learnings-log contradict <id>   # one conflicting data point
```

**Supersede (default for any content/anchor change — atomic, bidirectional, audit-preserving):**

```bash
# Refine wording (inherits type/confidence/tags/files from the old entry):
ccgm-learnings-log supersede <old_id> \
  --content "<refined guidance>" \
  --reason "<why it changed>"

# Fix stale anchors: same content, corrected files:
ccgm-learnings-log supersede <old_id> \
  --content "<unchanged guidance>" \
  --file <new/path.py> \
  --reason "anchor moved during refactor"
```

`supersede` keeps both rows; default reads hide the old one, `ccgm-learnings-search --include-superseded` walks the chain.

**Deprecate (only when there is no replacement):**

```bash
ccgm-learnings-log deprecate <id>
```

**Whole-entry rewrite (last resort) — run the fact-guard FIRST:**

If supersede genuinely does not fit and you must rewrite content in place, gate the rewrite on `compact_preserves_facts` so model-driven compaction cannot silently drop identifiers, dates, or table names:

```bash
python3 - "$OLD_ID" "$OLD_CONTENT" "$NEW_CONTENT" <<'PY'
import sys
sys.path.insert(0, "modules/self-improving/lib")
import learnings_store as ls
old_id, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
ok, dropped = ls.compact_preserves_facts(old, new)
if not ok:
    print(f"REJECT rewrite of {old_id}: dropped facts {dropped}", file=sys.stderr)
    sys.exit(1)
print(f"OK to rewrite {old_id}")
PY
```

If the guard rejects (exit 1), do **not** rewrite — flag the entry in the report under "Unresolved" for human review.

For MEMORY.md entries worth keeping, port them via `ccgm-learnings-log --from-json '...'` and then remove the stale markdown.

### 4. Report

```
## Learnings Consolidation Report

- **Entries reviewed**: N (JSONL) + N (MEMORY.md)
- **Verifications**: N (counter delta — refreshed last_verified)
- **Contradictions recorded**: N (counter delta)
- **Superseded**: N (list old_id → new_id + one-line reason)   <- prefer this for content/anchor changes
- **Deprecated**: N (list ids + one-line reason; only where no replacement existed)
- **Whole-entry rewrites**: N (each one passed the compact_preserves_facts guard)
- **Migrated from MEMORY.md**: N
- **Rewrites rejected by fact-guard**: N (list ids; flagged for human review)
- **Unresolved**: (any patterns that need human input)
```

A healthy consolidation pass is **supersede- and verify-heavy, deprecate-light**. A run that deprecates many entries and writes many fresh ones is a red flag that you replaced whole entries instead of applying deltas — re-check those against the policy in step 0.
