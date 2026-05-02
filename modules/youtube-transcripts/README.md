# YouTube Transcripts Module

A `/transcript <url>` slash command that grabs a YouTube transcript AND produces a structured analysis pass against your project memory in one invocation.

## What it does

```
/transcript https://www.youtube.com/watch?v=96jN2OCOfLs
```

1. **Phase 1 (deterministic)**: `yt-dlp` pulls the auto-generated captions, awk/sed clean the VTT, save to `~/code/docs/transcripts/<slug>-<upload_date>.md` with YAML frontmatter.
2. **Phase 2 (latent)**: A subagent reads the saved transcript + your `MEMORY.md` + workspace `CLAUDE.md`, runs the analysis template at `~/.claude/lib/analyze-transcript.md`, and writes an opinionated implications doc to `~/code/docs/transcript-analysis/<slug>-<upload_date>.md`.
3. Both saved paths are printed.

The two filenames share the same slug + upload-date so the pair correlates by name.

## Install

This module installs:

| File | Installs to |
|------|-------------|
| `rules/youtube-transcripts.md` | `~/.claude/rules/youtube-transcripts.md` |
| `commands/transcript.md` | `~/.claude/commands/transcript.md` |
| `lib/grab-transcript.sh` | `~/.claude/lib/grab-transcript.sh` |
| `lib/analyze-transcript.md` | `~/.claude/lib/analyze-transcript.md` |

Install via the standard CCGM flow:

```bash
cd ~/code/ccgm-repos/ccgm-1
./start.sh
# select youtube-transcripts in the module picker
```

Manual install (without `./start.sh`):

```bash
mkdir -p ~/.claude/rules ~/.claude/commands ~/.claude/lib
cp modules/youtube-transcripts/rules/youtube-transcripts.md   ~/.claude/rules/
cp modules/youtube-transcripts/commands/transcript.md         ~/.claude/commands/
cp modules/youtube-transcripts/lib/grab-transcript.sh         ~/.claude/lib/
cp modules/youtube-transcripts/lib/analyze-transcript.md      ~/.claude/lib/
chmod +x ~/.claude/lib/grab-transcript.sh
```

## Requirements

- `yt-dlp` (install via `brew install yt-dlp` or `pipx install yt-dlp`)
- Standard POSIX `awk`, `sed`, `tr`

No Python or Node dependencies. The Phase 1 script is pure bash + yt-dlp.

## Usage

```
/transcript <youtube-url>
  [--no-analysis]              skip Phase 2; transcript only
  [--out-transcripts <dir>]    default: ~/code/docs/transcripts/
  [--out-analysis <dir>]       default: ~/code/docs/transcript-analysis/
  [--name <slug>]              default: derived from video title (kebab-case)
  [--lang <code>]              default: en, auto-fallback
  [--force]                    overwrite existing output files
  [mode:headless]              no prompts; print only the saved paths on stdout
```

### The three flags worth knowing

- **`--no-analysis`** — Phase 1 only. Use when you want the transcript itself but not an opinionated read.
- **`--force`** — overwrite existing output files. The script refuses to overwrite by default.
- **`mode:headless`** — for skill-to-skill invocation. No prompts; on success, prints exactly the saved paths (one per line) and nothing else; errors to stderr; exits nonzero on failure.

### Direct script invocation

`grab-transcript.sh` is callable from a shell, not just from the slash command:

```bash
~/.claude/lib/grab-transcript.sh https://www.youtube.com/watch?v=96jN2OCOfLs
~/.claude/lib/grab-transcript.sh --name "karpathy-sequoia" --force <url>
```

This skips Phase 2 entirely (no subagent dispatch from a raw shell call). Use the slash command if you want analysis.

## Failure modes

The skill handles three classes of failure explicitly:

1. **No captions available.** yt-dlp returns no `.vtt` for any language. Exits nonzero with a message; no files written. Pick a different video.
2. **Age-gated / private / region-locked video.** yt-dlp errors out. The error is propagated; no files written.
3. **Analysis subagent fails after extraction succeeded.** The transcript file is still saved. The analysis failure is reported on stderr; the transcript path is printed on stdout. Re-run analysis manually if needed.

Other edge cases:

- Multiple subtitle languages: `--lang` picks one. Default is `en`, falling back to the first available with a printed warning.
- Manual subtitles preferred over auto-captions when both exist.
- Filenames with slashes/quotes/colons in the video title: aggressively sanitized.
- Long videos (>1hr): no special handling, no artificial timeouts.
- Output file already exists: refuse to overwrite unless `--force`.
- Output directory missing: created automatically.

## Output format

### Transcript file

```markdown
---
title: "Andrej Karpathy: From Vibe Coding to Agentic Engineering"
source: Sequoia Capital
url: https://www.youtube.com/watch?v=96jN2OCOfLs
uploader: Sequoia Capital
upload_date: 2026-04-29
duration: "29:49"
saved_at: 2026-05-02
type: interview-transcript
caption_source: auto
note: "Auto-generated YouTube captions; spelling errors expected."
---

We're so excited for our very first special guest...

>> Yeah. Hello. Excited to be here...

>> Okay. So, just a couple months ago, you said...
```

`>>` marks speaker turns. Stage directions like `[laughter]`, `[applause]`, `[clears throat]` are preserved.

### Analysis file

```markdown
---
title: "<source title> — Implications"
analyst: <model name>
date: <today, YYYY-MM-DD>
source_transcript: ../transcripts/<filename>
source_url: <url>
purpose: First-pass synthesis. Intended to be fed to a downstream agent.
context_for_next_agent: |
  <portfolio brief derived from MEMORY.md>
---

# What the speaker actually said
<3-7 highest-bite claims>

# Implications for active projects
<A: strategically aligned / B: accelerations / C: orthogonal>

# Implications for tooling / workflow
<concrete CCGM module, file path, rule additions>

# Where to direct focus
<3-5 ordered actions, biased toward concrete>

# Open questions for the downstream agent
<pressure-test the partition, identify counter-arguments>

# Confidence notes
<high / medium / low / speculative>
```

## Why one skill, not two

Extraction and analysis are phases of the same intent. The default value is *"what does this transcript imply for what I'm building?"* — the bare transcript is a building block, not the deliverable. Splitting the two would make the common case require two invocations and leave a pile of unanalyzed transcripts in the directory.

`--no-analysis` exists for the rare case where you only want the raw text.
