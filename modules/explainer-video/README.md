# explainer-video

Turns a topic into a narrated animation. The `explainer-video` skill researches the topic, writes a scene script and Manim scenes, and runs `ccgm-explainer-render`, which narrates, renders, joins, and checks the video. Rung 4 of the output ladder: `/explain <topic> as video` hands off here.

Status: beta. Rendering is headless. Nothing opens a window, plays audio, or takes focus. The tool writes the file and prints the path.

## Install

```bash
bash start.sh --add explainer-video
```

The module is in the `full` preset only.

Prerequisites on the machine that renders:

```bash
brew install cairo pango pkg-config
```

You also need `uv` (it runs Manim without a global install) and `ffmpeg` (with `ffprobe`). The tool exits with `missing required tool: <name>` when one is absent.

## What It Installs

| File | Installed to |
|------|--------------|
| `skills/explainer-video/SKILL.md` | `~/.claude/skills/explainer-video/SKILL.md` |
| `bin/ccgm-explainer-render` | `~/.claude/bin/ccgm-explainer-render` |

Manual install: copy those two files to the targets and make the script executable.

## How a Render Works

`ccgm-explainer-render DIR [--scenes ID,ID]` reads `DIR/script.json` and `DIR/scenes.py`. For each scene it:

1. Synthesizes the narration and measures it with `ffprobe`.
2. Renders the Manim class with `uv run --with manim manim -qm`, passing the measured length as `SCENE_DURATION`.
3. Muxes picture and voice, and extracts one frame to `DIR/frames/<id>.png`.

It then joins the scenes into `DIR/explainer.mp4` and checks it: exactly one video and one audio stream, and a total length within 10 percent of the narration. A failed check exits non-zero and names the check. The skill reads the frames, fixes overlapping or off-screen text, and rebuilds only the broken scenes with `--scenes`.

## Voice Backends

The tool uses the first available backend and prints `voice: <name>`.

| Order | Backend | Used when |
|-------|---------|-----------|
| 1 | ElevenLabs | `ELEVENLABS_API_KEY` is set and the narration is within `ELEVENLABS_MAX_CHARS` (default 5000 per video). Over the cap, the tool says so and uses a local voice. `ELEVENLABS_VOICE_ID` overrides the voice. |
| 2 | Kokoro | `CCGM_KOKORO_VETTED=1`, `uv`, and `espeak-ng` are present. Off by default; see below. |
| 3 | macOS `say` | Always on macOS. Writes to a file with `say -o`, then converts with `ffmpeg`. It never speaks aloud. |

### Kokoro is off by default

The Kokoro-82M weights (`hexgrad/Kokoro-82M`, Apache-2.0) ship as `kokoro-v1_0.pth`, a pickle file, and the voices as `.pt` pickles. The `model-vetting` checklist allows only safetensors or GGUF and refuses pickle formats, so this module downloads nothing and ships Kokoro disabled. Set `CCGM_KOKORO_VETTED=1` only after you have converted or scanned the weights, pinned a revision, and recorded the vetting. The backend path is not exercised by a real run in this module's tests.

## Tests

```bash
python3 -m pytest modules/explainer-video/tests -q
bash modules/explainer-video/tests/test-explainer-video.sh
```

The backend-chain, missing-tool, and lint-hook tests run everywhere. The two-scene render test needs macOS `say`, `uv`, `ffmpeg`, and cairo/pango. It skips with a printed note when any is missing.

## Kill Criterion

The module stays active only if a sample video teaches an unfamiliar topic better than the same topic as a page (`/explain <topic> as page`). The operator decides after Epic 8 merges and records the verdict in the plan's `decisions.md`. If the video loses, this README marks the module parked and it gets no further work.
