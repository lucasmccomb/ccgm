**Prose check.** Before publishing, run these steps as separate commands:

1. Write the document's prose (no code blocks, no Mermaid block) to a temp file in the session scratchpad or temp directory.
2. Run `test -x "$HOME/.claude/bin/ccgm-prose-lint"` as its own command. If it exits non-zero, print `ccgm-prose-lint not installed; skipping the prose check` and continue.
3. Otherwise run `"$HOME/.claude/bin/ccgm-prose-lint" --strict <temp file>` as its own command. Exit 1 means a sentence or paragraph is over the limit: fix it and run again until it exits 0. Warnings do not fail the run; fix the ones that are cheap to fix.
