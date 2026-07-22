---
description: Rewrite prose under the six writing rules - list every violation first, then rewrite, keeping every fact, number, and name unchanged
allowed-tools: Read, Edit, Glob, Grep, AskUserQuestion
argument-hint: "[file-path or pasted text] [mode:landing] [--apply]"
---

# /rewrite - Apply the Six Writing Rules

Single-pass rewrite of existing prose under the six writing rules in `~/.claude/rules/writing-system.md`. Violations first, then the rewrite. Facts, numbers, and names survive untouched.

For a deep multi-lens review (argument, structure, data, impact), use `/editorial-critique` instead. This command is the cheap pass: one read, one list, one rewrite.

## Step 1: Resolve the Target

- If `$ARGUMENTS` contains a file path, Read it. Critique the prose only: skip frontmatter, fenced code blocks, inline code, and command output.
- If `$ARGUMENTS` contains pasted text, use it directly.
- If neither, ask what to rewrite.

Parse flags from `$ARGUMENTS` before treating the rest as the target: `mode:landing` and `--apply`.

## Step 2: List Every Violation

Go through the text and list each violation, grouped by rule, quoting the exact original text:

1. **Stale figures of speech** (rule 1): each print-worn metaphor or simile, with a fresh or literal replacement.
2. **Long words** (rule 2): each long word with its short replacement ("utilize" -> "use", "approximately" -> "about").
3. **Cuttable words** (rule 3): each word or phrase that can go without losing meaning ("in order to" -> "to", "it's worth noting that" -> cut).
4. **Passive constructions** (rule 4): each passive with its active rewrite, where the actor is known.
5. **Jargon** (rule 5): each jargon or foreign phrase with an everyday equivalent, only where precision survives the swap. A technical term with no accurate plain substitute stays.

If a category has no violations, skip it. Do not pad the list.

## Step 3: Rewrite

Produce the full rewrite applying every fix from Step 2.

Hard constraints:

- Keep every fact, number, and name unchanged.
- Keep code blocks, identifiers, commands, links, and frontmatter byte-for-byte.
- Keep the document's structure (headings, lists, tables) unless a violation lives in the structure itself.
- Rule 6 wins conflicts: if a fix makes the sentence worse, leave the original and say so.

Output the rewrite in a fenced code block so it pastes clean (see `copy-paste-output.md`).

## Step 4: mode:landing

For marketing or landing-page copy, add two checks on top of Steps 2-3:

- **One concrete claim per line.** Flag any line that makes two claims or none.
- **The swap test.** For every line, ask: could a competitor paste this unchanged onto their page? If yes, the line says nothing about this product. Rewrite it around a concrete, specific claim, or delete it.

List swap-test failures in Step 2's output as their own group.

## Step 5: Apply

- If the target was a file and `--apply` was passed, apply the rewrite with Edit.
- If the target was a file without `--apply`, show the violations and rewrite, then ask whether to apply.
- If the target was pasted text, the fenced rewrite is the deliverable; there is nothing to apply.
