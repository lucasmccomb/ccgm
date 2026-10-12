**Prose check.** Before publishing, write the prose of the document to a temp file (leave out code blocks) and run the linter with `--strict`:

```bash
LINT="${CCGM_BIN:-$HOME/.claude/bin}/ccgm-prose-lint"
if [ -x "$LINT" ]; then "$LINT" --strict "$PROSE_FILE"; else echo "ccgm-prose-lint not installed; skipping the prose check"; fi
```

Exit 1 means an error-level finding (a sentence or paragraph over the length limit). Fix each one and run again until it exits 0. Warnings do not fail the run; fix the ones that are cheap to fix.
