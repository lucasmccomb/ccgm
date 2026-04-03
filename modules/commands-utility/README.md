# Utility Commands

Miscellaneous utility commands for common Claude Code workflows.

## Commands

### `/cgr` - Clear + Git Rebase

Delegates to a Haiku agent to clear the conversation and reset to the default branch with latest origin. Detects default branch automatically (main/master).

```
/cgr
```

After completing, the conversation resets to a fresh state.

### `/cws-submit` - Chrome Web Store Submission

Step-by-step walkthrough for submitting a Chrome extension to the Chrome Web Store. Uses walkthrough mode (one step at a time, waits for confirmation).

Handles: extension identification, prerequisites check, store assets preparation, Stripe promo code creation, production build, CWS dashboard walkthrough.

```
/cws-submit
/cws-submit gmail-darkly
```

Note: Reads `docs/cws-submission-process.md` in the repo for step-by-step instructions.

### `/dotsync` - Sync Local Config to CCGM

Delegates to a Haiku agent to reverse-sync local `~/.claude/` changes back to the CCGM repo. Shows a dry run first, then applies changes.

```
/dotsync
```

Reads CCGM root from `~/.claude/.ccgm-manifest.json`.

### `/user-test` - Browser-Based User Testing

Simulates real user testing of a deployed web app using Chrome automation. Generates a problem-space doc and solution-space doc. Optionally auto-iterates to fix issues.

```
/user-test <url>
/user-test https://myapp.com --flows "login, search, checkout" --persona "new user"
/user-test https://myapp.com --iterate 3
```

Produces `docs/user-test-problems.md` and `docs/user-test-solutions.md` in the project directory.

## Manual Installation

```bash
cp commands/cgr.md ~/.claude/commands/cgr.md
cp commands/cws-submit.md ~/.claude/commands/cws-submit.md
cp commands/dotsync.md ~/.claude/commands/dotsync.md
cp commands/user-test.md ~/.claude/commands/user-test.md
```
