# ccgm-doctor

Audit tool for Claude Code installs. Reports dark or broken entries so they can be fixed before a user hits them.

## What It Does

Installs a `ccgm-doctor` CLI. Subcommands:

- `check-resolvable` — reachability audit (hook refs, command descriptions, script refs)
- `dry` — DRY/overlap audit (pairs of commands whose triggers are lexically similar)
- `resolver-eval` — run a routing suite of `{intent, expected}` assertions

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

Lexical overlap is a conservative signal — it catches copy-paste descriptions and near-duplicates, not semantic synonyms. For semantic routing analysis, use `resolver-eval` (below) — it is better suited to paraphrase-style overlap.

### resolver-eval

Runs a suite of `{intent, expected}` assertions against the commands dir. For each intent, a keyword-overlap scorer ranks candidate commands by Jaccard similarity between intent tokens and (description + filename stem) tokens. Passes if the expected command appears in the top `k` candidates.

```
[PASS] stage all my changes and commit them
       expected: commit
       top:      commit(0.50)
[FAIL] debug this failing test
       expected: debug
       top:      user-test(0.12)
```

Suite format (JSON array):

```json
[
  {"intent": "stage all my changes and commit them", "expected": "commit"},
  {"intent": "review this pull request",             "expected": "review"}
]
```

The module ships `evals/routing.json` as a default suite covering ~18 common intents. Extend it by pointing at your own file with `--suite`.

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

# Routing assertions
ccgm-doctor resolver-eval                         # uses default bundled suite
ccgm-doctor resolver-eval --suite my-evals.json   # your own suite
ccgm-doctor resolver-eval --top-k 3               # pass if expected is in top 3
ccgm-doctor resolver-eval --json
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
- **Model-backed routing** — the current `resolver-eval` is a structural scorer. The model may choose differently, especially on paraphrases or short intents. A future enhancement can invoke `claude -p` or the API to ask the model directly and compare — the eval file format and pass contract stay the same.

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
| `evals/routing.json` | Default routing suite for `resolver-eval` |
| `tests/test_doctor.py` | 47 unit tests covering all checks with tempdir fixtures |
