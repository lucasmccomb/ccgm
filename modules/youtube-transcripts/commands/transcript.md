---
description: Grab a YouTube transcript via yt-dlp AND dispatch a subagent to produce an opinionated implications doc against your project memory. One slug+date, two saved files (transcript + analysis).
allowed-tools: Bash, Read, Write, Agent
argument-hint: <youtube-url> [--no-analysis] [--out-transcripts <dir>] [--out-analysis <dir>] [--name <slug>] [--lang <code>] [--force] [mode:headless]
---

# /transcript - Extract YouTube transcript and analyze against project context

A two-phase skill. Phase 1 is deterministic (a bash script calling `yt-dlp`). Phase 2 is latent (a subagent dispatched to read the transcript + project memory and write an opinionated implications doc).

```
/transcript <youtube-url>
```

produces both files and prints both saved paths. `--no-analysis` runs Phase 1 only.

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Arguments

Extract from `$ARGUMENTS`:

- **`<youtube-url>`** (required) — must contain `youtube.com/` or `youtu.be/`. If missing or malformed, print usage and stop.
- **`--no-analysis`** — skip Phase 2; print only the transcript path
- **`--out-transcripts <dir>`** — default `~/code/docs/transcripts`
- **`--out-analysis <dir>`** — default `~/code/docs/transcript-analysis`
- **`--name <slug>`** — override the auto-derived slug
- **`--lang <code>`** — default `en`
- **`--force`** — overwrite existing output files
- **`mode:headless`** — no prompts; on success print exactly the saved paths (one per line) on stdout, nothing else; errors to stderr; exits nonzero on any failure

Default behavior runs **both phases**. The slug + upload-date is computed by Phase 1 and reused for Phase 2 so the pair correlates by name.

---

## Phase 1: Extract (deterministic, script)

Invoke the extraction script:

```bash
~/.claude/lib/grab-transcript.sh \
  --out "<out-transcripts>" \
  ${name:+--name "<name>"} \
  ${lang:+--lang "<lang>"} \
  ${force:+--force} \
  -- "<url>"
```

The script:

- pulls the auto-generated (or manual) captions via `yt-dlp`
- cleans the VTT into prose with `>>` speaker turns
- writes a markdown file with YAML frontmatter
- prints the absolute saved path on stdout
- exits nonzero on any failure (no captions, age-gated, network error, existing-file-without-force, missing yt-dlp)

**Capture both stdout and the exit code.** The transcript path is the last line of stdout.

If exit code is nonzero:

- In **interactive mode**: report the error from stderr to the user and stop. Do not write any files (the script already declined to).
- In **`mode:headless`**: forward stderr to the user and exit nonzero. Do not proceed to Phase 2.

If `--no-analysis` was passed:

- Print the transcript path
- Stop. Do not dispatch the subagent.

---

## Phase 2: Analyze (latent, subagent)

After extraction succeeds, dispatch a subagent in headless mode (per the `subagent-patterns` "Skill Invocation Modes" rule).

### Compute the analysis output path

The analysis filename uses **the same slug + upload-date as the transcript**, so the pair correlates by name.

```bash
TRANSCRIPT_PATH="<from Phase 1 stdout>"
TRANSCRIPT_BASENAME="$(basename "$TRANSCRIPT_PATH")"   # e.g. karpathy-2026-04-29.md
ANALYSIS_PATH="<out-analysis>/$TRANSCRIPT_BASENAME"
```

If `$ANALYSIS_PATH` already exists and `--force` was not passed:

- In interactive mode: ask whether to overwrite
- In headless mode: forward an error to stderr ("analysis already exists at $ANALYSIS_PATH; pass --force to overwrite") and exit nonzero (the transcript is already saved, so this is a partial-success state)

### Subagent dispatch

Use the `Agent` tool. Pass **paths, not contents** — the subagent reads the files itself, which keeps the dispatch prompt cheap and lets the analysis pick up edits to `MEMORY.md` made between sessions.

Suggested subagent_type: `general-purpose` (or any model that has Read + Write + Bash).

Prompt (verbatim template, fill in the placeholders):

```
You are running in mode:headless as the analysis phase of /transcript. Read the
analysis template at /Users/<user>/.claude/lib/analyze-transcript.md and follow
it exactly.

Inputs (paths — read each file directly, do not work from pasted excerpts):

  TRANSCRIPT_PATH=<absolute path from Phase 1>
  MEMORY_PATH=/Users/<user>/.claude/projects/-Users-<user>-code/memory/MEMORY.md
  WORKSPACE_PATH=/Users/<user>/code/CLAUDE.md
  OUTPUT_PATH=<computed analysis path>
  SOURCE_URL=<the original URL passed to /transcript>

Discover MEMORY_PATH dynamically: it lives under
  ~/.claude/projects/<project-slug>/memory/MEMORY.md
where <project-slug> is the kebab-cased absolute path to ~/code (the user's
workspace root). If you cannot find it, look at the analysis template's
guidance and proceed without it (note this in section 6 confidence).

Per the template:
  - Read the transcript, MEMORY.md, and CLAUDE.md
  - Write the analysis file at OUTPUT_PATH with the 6-section structure
  - The relative path in the source_transcript: frontmatter field should be
    computed correctly for the actual transcript and analysis output dirs
  - Verify the file exists and is > 1KB after writing

End your response with:
  - One line: the absolute OUTPUT_PATH
  - One line: a four-state status (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT)
```

### Verify the subagent's claim

A subagent reporting DONE is a claim, not evidence. After it returns:

```bash
ls -la "$ANALYSIS_PATH"
wc -c "$ANALYSIS_PATH"
```

If the file is missing or under 1KB, treat the result as failed regardless of what the subagent reported.

If the subagent returns BLOCKED or NEEDS_CONTEXT:

- The transcript is **still saved** — do not delete it
- In interactive mode: report the status to the user, print the transcript path, and offer to re-dispatch with whatever context is missing
- In headless mode: forward the status reason to stderr, print the transcript path on stdout, exit nonzero

If the subagent returns DONE_WITH_CONCERNS:

- Read the concerns (they are part of the subagent's last lines)
- Print them to the user above the saved paths in interactive mode
- In headless mode: still print both paths on stdout and exit zero (the file is saved and structurally valid)

---

## Phase 3: Report

### Interactive mode (default)

```
Saved transcript: <transcript_path>
Saved analysis:   <analysis_path>

[any DONE_WITH_CONCERNS notes here, indented]
```

### `--no-analysis`

```
Saved transcript: <transcript_path>
```

### `mode:headless` (success)

```
<transcript_path>
<analysis_path>
```

Exactly two lines on stdout. Nothing else. Errors go to stderr.

### `mode:headless` + `--no-analysis` (success)

```
<transcript_path>
```

One line on stdout.

### Failure modes (any mode)

| State | Transcript saved? | Analysis saved? | Exit | Stderr message |
|-------|---|---|---|---|
| No captions | no | no | nonzero | "No captions available for <url> (lang=<lang> or any fallback)." |
| Age-gated / private / region-locked | no | no | nonzero | yt-dlp's error, prefixed `yt-dlp:` |
| Output file already exists, no --force | no | no | nonzero | "<path> already exists. Re-run with --force to overwrite." |
| Phase 1 OK, Phase 2 BLOCKED/NEEDS_CONTEXT | yes | no | nonzero | subagent's reason, transcript path on stdout |
| Phase 1 OK, Phase 2 file missing or tiny | yes | no | nonzero | "Analysis subagent reported success but file is missing/empty at <path>." |

---

## Why this is one skill, not two

Extraction and analysis are phases of one intent. The default value is "what does this transcript imply for what I'm building?" — the bare transcript is a building block, not the deliverable. Splitting them across two skills would make the common case require two invocations and leave a pile of unanalyzed transcripts.

`--no-analysis` exists for the rare case where you only want the raw text.

---

## Implementation notes for the slash-command runner

- The script path is `~/.claude/lib/grab-transcript.sh`. The analysis template is at `~/.claude/lib/analyze-transcript.md`. Both are installed by the `youtube-transcripts` module.
- The script is the source of truth for slug + upload-date computation. Do not re-derive them in the slash command — read the path the script printed and reuse it.
- The script handles `--force` itself (refuses to overwrite without it). The slash command does NOT need to pre-check.
- The subagent's task includes reading the user's MEMORY.md. The path to MEMORY.md is project-slug-derived; if you cannot resolve it, the subagent should proceed without it and note the gap in section 6 of the analysis. Do not block extraction on missing MEMORY.md.
