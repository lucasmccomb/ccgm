# ccgm-doctor

Audit tool for Claude Code installs. Reports dark or broken entries so they can be fixed before a user hits them.

## What It Does

Installs a `ccgm-doctor` CLI. Subcommands:

- `check-resolvable` — reachability audit (hook refs, command descriptions, script refs)
- `dry` — DRY/overlap audit (pairs of commands whose triggers are lexically similar)

### check-resolvable

Walks a Claude install and reports three classes of issue:

| Check | Severity | What it catches |
|-------|----------|-----------------|
| `hook-refs` | error | settings.json hook command points at a file that does not exist |
| `command-descriptions` | warn | command `.md` has no frontmatter `description:` and no first-line heading (the model will not reliably discover it) |
| `script-refs` | error | a command's bash fenced block invokes a `ccgm-*` script that does not exist on PATH or in `{claude_dir}/bin` |

Each finding includes: check name, severity, path, and a one-line detail.

### dry

Compares every pair of command trigger descriptions using Jaccard similarity over content tokens (stopwords and short tokens filtered out). Pairs above the threshold are flagged as likely ambiguous routing candidates.

| Check | Severity | What it catches |
|-------|----------|-----------------|
| `dry-overlap` | warn | two commands whose trigger descriptions share > threshold tokens (default 0.5) |

Lexical overlap is a conservative signal — it catches copy-paste descriptions and near-duplicates, not semantic synonyms. For semantic routing analysis (e.g., "commit my changes" vs "check in these files"), use the resolver eval harness (#386).

## Usage

```bash
# Reachability audit
ccgm-doctor check-resolvable
ccgm-doctor check-resolvable --claude-dir /path/to/.claude
ccgm-doctor check-resolvable --json

# DRY audit
ccgm-doctor dry
ccgm-doctor dry --threshold 0.3          # flag more overlapping pairs
ccgm-doctor dry --threshold 0.8          # only flag near-duplicates
ccgm-doctor dry --json
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
- **Semantic overlap** — two commands whose descriptions are paraphrases of each other but share few exact tokens. Lexical DRY catches copy-paste; semantic routing needs a model. See `#386`.
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
