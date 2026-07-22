# Writing System

**Iron Law:** PROSE FOLLOWS THE SIX RULES. FIX THE SYSTEM, NOT ONE WORD AT A TIME.

These rules govern prose: docs, READMEs, PR descriptions, commit messages, issue comments, session reports, chat responses, marketing copy. They never touch code, identifiers, API names, error strings someone will grep for, or a technical term whose plain-word swap would change the meaning ("idempotent" stays "idempotent").

## The Six Rules (Orwell, 1946)

1. Never use a metaphor, simile or other figure of speech which you are used to seeing in print.
2. Never use a long word where a short one will do.
3. If it is possible to cut a word out, always cut it out.
4. Never use the passive where you can use the active.
5. Never use a foreign phrase, a scientific word or a jargon word if you can think of an everyday English equivalent.
6. Break any of these rules sooner than say anything outright barbarous.

Check deliverable prose (a README, a PR body, a doc page, a report) against these rules before delivering it.

## What the Rules Do to a Sentence

Before: "Comprehensive error handling has been implemented across all API endpoints to ensure robust and reliable performance."

After: "We added error handling to every API endpoint."

Comprehensive, robust, reliable, and ensure are gone. Passive turned active. 16 words down to 8. Same facts.

## Commit Messages and PR Descriptions

State what changed and why in plain words. No achievement language: no "comprehensive", no "robust", no "seamless". A reviewer should know what the change does in one read. Value-first structure (what the change enables, then the evidence) comes from the git-workflow rules and the `pr-description` skill; these rules govern the words inside that structure.

## Session Reports and Summaries

Report progress in plain sentences: what changed, what failed, what comes next. No emoji checkmarks, no "Successfully", no "Perfect", no wall of bullets. Start with three lines; add detail only when it changes the reader's next action.

This governs free-form summaries. When a command or skill mandates an exact output format (a JSON envelope, `/sds`'s final report, a statusline, a structured findings artifact), that format wins.

## Why There Is No Word Blacklist

Banning words one at a time ("no delve", "no em dashes") treats symptoms. The six rules are the system; a banned-word list is what you fall back on without one. For a deep, line-by-line review of long-form writing, run `/editorial-critique`; its detectors (AI-tell vocabulary, filler phrases) apply these rules at review time. For a quick single pass over existing text, run `/rewrite`.

## Red Flags

Stop and rewrite if you catch yourself:

- Writing "comprehensive", "robust", "seamless", or "cutting-edge" in prose
- Opening a report with an emoji checkmark or the word "Successfully"
- Writing a sentence whose subject performs no action ("error handling has been implemented")
- Padding a summary with bullets that restate the diff
- Swapping a precise technical term for a folksy one and losing the meaning; rule 6 exists for this
