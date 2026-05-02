# YouTube Transcripts

`/transcript <url>` extracts a YouTube transcript via yt-dlp AND dispatches a subagent to produce an opinionated implications doc against the user's project memory. Two files saved, same slug + upload-date, so the pair correlates by name.

## When to invoke

- The user asks to "transcribe", "grab", "pull", "save" a YouTube video
- The user pastes a `youtube.com/watch?v=...` or `youtu.be/...` URL and asks what to do with it
- The user asks for an analysis, summary, or implications of a YouTube talk / interview / podcast

## When NOT to invoke

- The URL is not YouTube (Vimeo, Spotify, Apple Podcasts, etc.) — yt-dlp may handle some of these but the slug/metadata pipeline assumes YouTube
- The user wants live captions or real-time transcription — this is for already-published videos
- The user wants to download the video itself — this skill explicitly skips video download (`--skip-download`)

## ASR caveats — how to read the saved transcript

The transcript is **auto-generated YouTube captions**, not a human transcript. Expect:

- **Misheard proper nouns**: "open AAI" = OpenAI, "openclaw" = Open Code, "Verscell" = Vercel, "Nanobanana" = Nano Banana, "menu genen" = Menu Gen, "spirious" = spurious, "micro GPT" = nanoGPT. The `note:` field in the frontmatter calls these out per-transcript when the analyst can identify them.
- **Run-on sentences**: ASR has no punctuation model; sentences blur. Speaker turns (`>>`) are the most reliable structural signal.
- **Stage directions**: `[laughter]`, `[applause]`, `[clears throat]`, `[snorts]` are preserved. Don't strip them — they're useful context for tone.
- **Repeated phrases**: ASR sometimes double-prints; the dedupe pass collapses adjacent identical lines but verbal stutters ("uh, uh, well") survive.

When quoting from the transcript, paraphrase rather than verbatim-quote unless you're sure the ASR got it right. When summarizing, lead with the speaker's argument, not their literal words.

## How downstream consumers should treat the output

The two files are:

- `~/code/docs/transcripts/<slug>-<upload_date>.md` — raw cleaned transcript with YAML frontmatter (title, source, url, uploader, upload_date, duration, type, caption_source, note).
- `~/code/docs/transcript-analysis/<slug>-<upload_date>.md` — opinionated implications doc with frontmatter pointing back to the transcript via relative path. Six sections: claims / project implications / tooling / focus / open questions / confidence.

The analysis is a **first-pass synthesis intended to be fed to a downstream agent.** It is opinionated, names specific projects from `MEMORY.md`, and explicitly flags low-confidence claims. Treat it as a starting point for pressure-testing, not as authoritative.

When citing either file in later work, prefer the analysis doc — it has the project context. Drop into the transcript only when you need a specific quote or claim verified.

## Failure modes

- **No captions**: yt-dlp returns no `.vtt` for any language. The script exits nonzero with a message; no files written. The user should pick a different video or pull captions another way.
- **Age-gated / private / region-locked**: yt-dlp errors out. The script propagates the error and exits nonzero.
- **Analysis subagent fails**: the transcript file is still saved. The failure is reported but the transcript stays. Re-run analysis manually if needed.
