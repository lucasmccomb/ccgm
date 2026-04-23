# Utility Commands

Miscellaneous utility commands for common Claude Code workflows.

## Commands

### `/cws-submit` - Chrome Web Store Submission

Step-by-step walkthrough for submitting a Chrome extension to the Chrome Web Store. Uses walkthrough mode (one step at a time, waits for confirmation).

Handles: extension identification, prerequisites check, store assets preparation, Stripe promo code creation, production build, CWS dashboard walkthrough.

```
/cws-submit
/cws-submit gmail-darkly
```

Note: Reads `docs/cws-submission-process.md` in the repo for step-by-step instructions.

### `/ccgm-sync` - Sync Local Config to CCGM + lem-deepresearch

Delegates to a Haiku agent to reverse-sync local `~/.claude/` changes back to source repos. Syncs CCGM-managed files to the CCGM repo and deepresearch files to the lem-deepresearch repo. Shows a dry run first, then applies changes.

```
/ccgm-sync
```

Reads CCGM root from `~/.claude/.ccgm-manifest.json`. Checks `~/code/lem-deepresearch` for deepresearch sync.

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
cp commands/cws-submit.md ~/.claude/commands/cws-submit.md
cp commands/ccgm-sync.md ~/.claude/commands/ccgm-sync.md
cp commands/user-test.md ~/.claude/commands/user-test.md

# Statusline
cp statusline-command.sh ~/.claude/statusline-command.sh
chmod +x ~/.claude/statusline-command.sh

# Scripts
mkdir -p ~/.claude/scripts
cp scripts/ccgm-sync.sh ~/.claude/scripts/ccgm-sync.sh
cp scripts/agent-team ~/.claude/scripts/agent-team
chmod +x ~/.claude/scripts/ccgm-sync.sh
chmod +x ~/.claude/scripts/agent-team
```
