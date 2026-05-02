#!/usr/bin/env bash
# grab-transcript.sh — Phase 1 of the /transcript skill.
#
# Pulls the auto-generated (or manual) captions for a YouTube video via yt-dlp,
# cleans the VTT into prose with `>>` speaker turns, and writes a markdown file
# with YAML frontmatter to the chosen output directory.
#
# Pure bash + yt-dlp + awk + sed + tr. No Python, Node, or jq.
#
# Usage:
#   grab-transcript.sh <youtube-url>
#     [--out <dir>]    default: ~/code/docs/transcripts
#     [--name <slug>]  default: derived from video title (kebab-case)
#     [--lang <code>]  default: en
#     [--force]        overwrite existing output file
#
# Exits nonzero on:
#   - no captions available
#   - age-gated / private / region-locked video
#   - missing yt-dlp binary
#   - existing output file without --force

set -euo pipefail

# --- defaults ---
OUT_DIR="${HOME}/code/docs/transcripts"
NAME=""
LANG="en"
FORCE=0
URL=""

# --- parse args ---
while [ $# -gt 0 ]; do
  case "$1" in
    --out)        OUT_DIR="$2"; shift 2 ;;
    --name)       NAME="$2"; shift 2 ;;
    --lang)       LANG="$2"; shift 2 ;;
    --force)      FORCE=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    --) shift; URL="$1"; break ;;
    -*) echo "Unknown flag: $1" >&2; exit 2 ;;
    *)
      if [ -z "$URL" ]; then URL="$1"; else
        echo "Multiple URLs not supported (got: $URL and $1)" >&2; exit 2
      fi
      shift
      ;;
  esac
done

if [ -z "$URL" ]; then
  echo "Usage: grab-transcript.sh <youtube-url> [--out <dir>] [--name <slug>] [--lang <code>] [--force]" >&2
  exit 2
fi

# --- preflight ---
if ! command -v yt-dlp >/dev/null 2>&1; then
  echo "Error: yt-dlp not found in PATH. Install with 'brew install yt-dlp' or 'pipx install yt-dlp'." >&2
  exit 3
fi

mkdir -p "$OUT_DIR"

# --- workspace ---
TMPDIR_WORK=$(mktemp -d -t grab-transcript.XXXXXX)
trap 'rm -rf "$TMPDIR_WORK"' EXIT
cd "$TMPDIR_WORK"

# --- step 1: metadata (title, uploader, upload_date, duration, video id) ---
META_FILE="meta.txt"
if ! yt-dlp --skip-download --no-warnings \
    --print "%(id)s" \
    --print "%(title)s" \
    --print "%(uploader)s" \
    --print "%(upload_date)s" \
    --print "%(duration_string)s" \
    "$URL" >"$META_FILE" 2>meta.err; then
  echo "Error: yt-dlp metadata fetch failed." >&2
  sed 's/^/  yt-dlp: /' meta.err >&2 || true
  exit 4
fi

VIDEO_ID=$(sed -n '1p' "$META_FILE")
RAW_TITLE=$(sed -n '2p' "$META_FILE")
UPLOADER=$(sed -n '3p' "$META_FILE")
UPLOAD_DATE_RAW=$(sed -n '4p' "$META_FILE")
DURATION=$(sed -n '5p' "$META_FILE")

if [ -z "$VIDEO_ID" ] || [ -z "$RAW_TITLE" ]; then
  echo "Error: yt-dlp returned empty metadata for $URL" >&2
  exit 4
fi

# --- step 2: download captions (manual preferred, auto as fallback) ---
# yt-dlp prefers --write-sub (manual) and falls back to --write-auto-sub (ASR).
if ! yt-dlp --skip-download --write-auto-sub --write-sub \
    --sub-lang "${LANG}.*,${LANG}" --sub-format vtt --no-warnings \
    -o "yt-%(id)s.%(ext)s" "$URL" >dl.out 2>dl.err; then
  echo "Error: yt-dlp caption download failed." >&2
  sed 's/^/  yt-dlp: /' dl.err >&2 || true
  exit 5
fi

# Find the .vtt that matches our video id and language.
VTT_FILE=""
CAPTION_SOURCE="auto"
# Prefer manual subs (no .auto. in filename) over auto-generated.
for candidate in yt-"${VIDEO_ID}".*"${LANG}"*.vtt; do
  [ -e "$candidate" ] || continue
  case "$candidate" in
    *auto*) [ -z "$VTT_FILE" ] && VTT_FILE="$candidate" ;;
    *)      VTT_FILE="$candidate"; CAPTION_SOURCE="manual"; break ;;
  esac
done

# Last-resort fallback: any .vtt for this video.
if [ -z "$VTT_FILE" ]; then
  for candidate in yt-"${VIDEO_ID}"*.vtt; do
    [ -e "$candidate" ] || continue
    VTT_FILE="$candidate"
    echo "Warning: no captions in lang=${LANG}; falling back to $candidate" >&2
    break
  done
fi

if [ -z "$VTT_FILE" ]; then
  echo "Error: no captions available for $URL (lang=${LANG} or any fallback)." >&2
  echo "       The video may have captions disabled, or yt-dlp could not access them." >&2
  exit 6
fi

# --- step 3: clean the VTT into prose ---
# - Strip WEBVTT/Kind/Language/NOTE headers
# - Strip timestamp lines (with -->)
# - Strip blank lines
# - Strip inline tags like <c> and <00:00:00.000>
# - Dedupe adjacent identical lines (ASR repeats every cue)
awk '
  /^WEBVTT/ || /^Kind:/ || /^Language:/ || /^NOTE/ { next }
  /-->/ { next }
  /^[[:space:]]*$/ { next }
  { gsub(/<[^>]*>/, ""); print }
' "$VTT_FILE" | awk '!seen[$0]++' > cleaned.txt

# - Decode &gt;&gt; entities back to >>
# - Collapse newlines into a single spaced line
# - Squash runs of spaces
# - Re-split on speaker turns ( >> ) into paragraphs
sed 's/&gt;&gt;/>>/g' cleaned.txt \
  | tr '\n' ' ' \
  | sed 's/  */ /g' \
  | sed 's/ >> /\n\n>> /g' > body.txt

# Trim leading/trailing whitespace.
sed -i.bak '1{/^[[:space:]]*$/d}' body.txt 2>/dev/null || true
rm -f body.txt.bak

if [ ! -s body.txt ]; then
  echo "Error: cleaned transcript was empty (something went wrong with $VTT_FILE)." >&2
  exit 7
fi

# --- step 4: derive slug + filename ---
slugify() {
  # Lowercase, replace non-alnum with hyphens, collapse hyphens, trim hyphens.
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g' \
    | sed -E 's/^-+|-+$//g'
}

if [ -z "$NAME" ]; then
  SLUG=$(slugify "$RAW_TITLE")
  # Truncate aggressively — slugs longer than ~60 chars are unwieldy.
  SLUG=$(printf '%s' "$SLUG" | cut -c1-60 | sed -E 's/-+$//')
else
  SLUG=$(slugify "$NAME")
fi

if [ -z "$SLUG" ]; then
  SLUG="transcript-${VIDEO_ID}"
fi

# Reformat YYYYMMDD → YYYY-MM-DD; fall back to today if upload_date missing.
if [ -n "$UPLOAD_DATE_RAW" ] && [ "${#UPLOAD_DATE_RAW}" -eq 8 ]; then
  UPLOAD_DATE="${UPLOAD_DATE_RAW:0:4}-${UPLOAD_DATE_RAW:4:2}-${UPLOAD_DATE_RAW:6:2}"
else
  UPLOAD_DATE=$(date -u +%Y-%m-%d)
fi

SAVED_AT=$(date -u +%Y-%m-%d)

OUT_FILE="${OUT_DIR}/${SLUG}-${UPLOAD_DATE}.md"

if [ -e "$OUT_FILE" ] && [ "$FORCE" -ne 1 ]; then
  echo "Error: $OUT_FILE already exists. Re-run with --force to overwrite." >&2
  exit 8
fi

# --- step 5: classify type by duration heuristic ---
# Default to interview-transcript if we can't infer.
TYPE="interview-transcript"
if [ -n "$DURATION" ]; then
  # Convert MM:SS or HH:MM:SS to seconds.
  case "$(printf '%s' "$DURATION" | tr -cd ':' | wc -c | tr -d ' ')" in
    1) # MM:SS
      MIN=$(printf '%s' "$DURATION" | cut -d: -f1)
      SECS=$(( ${MIN:-0} * 60 ))
      ;;
    2) # HH:MM:SS
      H=$(printf '%s' "$DURATION" | cut -d: -f1)
      M=$(printf '%s' "$DURATION" | cut -d: -f2)
      SECS=$(( ${H:-0} * 3600 + ${M:-0} * 60 ))
      ;;
    *) SECS=0 ;;
  esac
  if [ "$SECS" -ge 3600 ]; then
    TYPE="podcast-transcript"
  elif [ "$SECS" -ge 1800 ]; then
    TYPE="interview-transcript"
  else
    TYPE="talk-transcript"
  fi
fi

# --- step 6: assemble frontmatter ---
# Escape any embedded double-quote in title/uploader for YAML.
yaml_escape() { printf '%s' "$1" | sed 's/"/\\"/g'; }

ESC_TITLE=$(yaml_escape "$RAW_TITLE")
ESC_UPLOADER=$(yaml_escape "$UPLOADER")

NOTE_TEXT="Auto-generated YouTube captions; spelling errors expected."
[ "$CAPTION_SOURCE" = "manual" ] && NOTE_TEXT="Manual subtitles from YouTube."

{
  printf -- '---\n'
  printf 'title: "%s"\n' "$ESC_TITLE"
  printf 'source: %s\n' "$ESC_UPLOADER"
  printf 'url: %s\n' "$URL"
  printf 'uploader: %s\n' "$ESC_UPLOADER"
  printf 'upload_date: %s\n' "$UPLOAD_DATE"
  printf 'duration: "%s"\n' "$DURATION"
  printf 'saved_at: %s\n' "$SAVED_AT"
  printf 'type: %s\n' "$TYPE"
  printf 'caption_source: %s\n' "$CAPTION_SOURCE"
  printf 'note: "%s"\n' "$NOTE_TEXT"
  printf -- '---\n\n'
  cat body.txt
  printf '\n'
} > "$OUT_FILE"

# --- done ---
printf '%s\n' "$OUT_FILE"
