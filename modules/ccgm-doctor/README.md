# ccgm-doctor

Audit tool for Claude Code installs. Reports dark or broken entries so they can be fixed before a user hits them.

## What It Does

Installs a `ccgm-doctor` CLI. Current subcommand: `check-resolvable`.

### check-resolvable

Walks a Claude install and reports three classes of issue:

| Check | Severity | What it catches |
|-------|----------|-----------------|
| `hook-refs` | error | settings.json hook command points at a file that does not exist |
| `command-descriptions` | warn | command `.md` has no frontmatter `description:` and no first-line heading (the model will not reliably discover it) |
| `script-refs` | error | a command's bash fenced block invokes a `ccgm-*` script that does not exist on PATH or in `{claude_dir}/bin` |

Each finding includes: check name, severity, path, and a one-line detail.

## Usage

```bash
# Audit the default ~/.claude install
ccgm-doctor check-resolvable

# Audit a specific install
ccgm-doctor check-resolvable --claude-dir /path/to/.claude

# Machine-readable output
ccgm-doctor check-resolvable --json
```

Exit codes:

- `0` — no issues
- `1` — issues found (see output)
- `2` — environment error (e.g., `--claude-dir` does not exist)

## Design Notes

The checks are pure functions of the filesystem. They run in milliseconds and require no model calls. This is intentional: the point of this tool is to catch deterministic reachability problems before they become silent drift. A model-backed check would be appropriate for ambiguous trigger-overlap problems (see `#385` DRY audit and `#386` resolver evals).

### What's covered

- **`hook-refs`**: parses `settings.json`, walks every `hooks[event][].hooks[].command`, extracts path-like tokens, expands `$HOME`/`~`, checks existence.
- **`command-descriptions`**: prefers YAML frontmatter `description:` (how Claude Code advertises commands). Falls back to first-line Markdown heading for CCGM-style commands. Flags absent or suspiciously short (< 10 chars).
- **`script-refs`**: only scans fenced bash/sh blocks, not prose, so directory names like `~/code/ccgm-repos/ccgm-1` do not false-flag. Checks PATH + `{claude_dir}/bin` for executability.

### What's not covered (yet)

- **Orphan detection** — "script in `bin/` that no command or hook references". CCGM does not track install provenance, so detecting orphans from source-module removal is non-trivial. Deferred.
- **DRY overlap** — two commands whose descriptions overlap semantically. See `#385`.
- **Resolver routing evals** — does the model actually pick the right command for a given intent? See `#386`.

## Manual Installation

```bash
cp bin/ccgm-doctor ~/.claude/bin/ccgm-doctor
chmod +x ~/.claude/bin/ccgm-doctor

mkdir -p ~/.claude/lib
cp lib/doctor.py ~/.claude/lib/doctor.py
```

`ccgm-doctor` expects `doctor.py` to sit in `../lib/` relative to the executable. If you install it elsewhere, adjust `sys.path` accordingly or run via `python3 -m doctor` with the lib dir on your PYTHONPATH.

## Files

| File | Description |
|------|-------------|
| `bin/ccgm-doctor` | Python CLI that dispatches subcommands |
| `lib/doctor.py` | Pure check functions — take paths, return findings |
| `tests/test_doctor.py` | 30 unit tests covering all checks with tempdir fixtures |
