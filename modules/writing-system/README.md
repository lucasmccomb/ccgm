# writing-system

Orwell's six writing rules (1946) as an always-on prose standard, plus a `/rewrite` command that applies them to existing text.

## What It Does

Most setups ban AI-sounding words one at a time ("no delve", "no em dashes") and still ship every README and PR description in the same AI voice. The missing piece is a writing system, not a longer blacklist. This module installs one:

- **`rules/writing-system.md`** loads in every session and governs prose: docs, READMEs, PR descriptions, commit messages, issue comments, session reports, chat responses, marketing copy. The six rules:
  1. Never use a metaphor, simile or other figure of speech which you are used to seeing in print.
  2. Never use a long word where a short one will do.
  3. If it is possible to cut a word out, always cut it out.
  4. Never use the passive where you can use the active.
  5. Never use a foreign phrase, a scientific word or a jargon word if you can think of an everyday English equivalent.
  6. Break any of these rules sooner than say anything outright barbarous.
- The rule adds two workflow subsections: commit/PR prose (plain words, no achievement language, one-read test) and session reports (plain sentences, no emoji checkmarks, no "Successfully").
- **`commands/rewrite.md`** adds `/rewrite [file] [mode:landing] [--apply]`: lists every violation (stale phrase, long word with its short replacement, cuttable word, passive construction, jargon), then rewrites, keeping every fact, number, and name unchanged. `mode:landing` adds the swap test for marketing copy: if a competitor could paste the line unchanged onto their page, rewrite or delete it.

The rules never touch code, identifiers, API names, or technical terms whose plain-word swap would change the meaning.

## Relationship to editorial-critique

`/editorial-critique` is the deep review: 8 parallel lenses over long-form writing. `/rewrite` is the cheap pass: one read, one violations list, one rewrite. The rule file is the standard both work from.

## Manual Installation

```bash
# Global (all projects)
cp rules/writing-system.md ~/.claude/rules/writing-system.md
cp commands/rewrite.md ~/.claude/commands/rewrite.md
```

## Files

| File | Description |
|------|-------------|
| `rules/writing-system.md` | The six rules, scope carve-outs, commit/PR and report subsections |
| `commands/rewrite.md` | `/rewrite`: violations list, then rewrite; `mode:landing` for copy |
