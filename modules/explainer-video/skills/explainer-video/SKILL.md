---
name: explainer-video
description: Turn a topic into a narrated, Manim-rendered .mp4, rendered headless with deterministic checks. Use when the operator asks for a video explanation (`/explain <topic> as video`). Writes the file and prints its path; never plays it.
disable-model-invocation: false
---

# Explainer Video

Rung 4 of the output ladder. Turn a topic into a 60 to 180 second narrated animation. Everything is headless: no preview window, no audio playback, no focus change. Write the file, print the path, and let the operator open it.

The prose answer still leads the final message. The video adds to it.

## Steps

### 1. Check the tools

Run each check as its own command.

```bash
test -x "$HOME/.claude/bin/ccgm-explainer-render"
```

If it fails, say the `explainer-video` module is not installed and offer a page instead (`/explain <topic> as page`). Stop.

```bash
command -v uv
```

If `uv` is missing, `ffmpeg` is missing, or Manim fails to build, `ccgm-explainer-render` names the missing piece. On macOS, `brew install cairo pango pkg-config` provides the libraries Manim builds against.

### 2. Research the topic

Read the code and docs the topic covers. Pick the three to six ideas a newcomer needs, in the order they build on each other.

### 3. Write `script.json`

Work in a new directory, for example `explainer-<topic>/`. Write `script.json`:

```json
{
  "title": "How the queue works",
  "scenes": [
    {
      "id": "intro",
      "scene": "Intro",
      "narration": "A queue holds work until a worker is free.",
      "description": "Title, then a box labeled queue."
    }
  ]
}
```

- `id`: letters, digits, and underscores. Names the build files and the frame.
- `scene`: the Manim class in `scenes.py`.
- `narration`: spoken text. One short sentence per beat. Follow the STE-lite limits in `writing-system`. Spell out symbols and acronyms the way a person says them. The render script runs `ccgm-prose-lint` on it when the linter is installed and prints the findings; fix them.
- `description`: what is on screen. Only you read it.
- Total narration: 60 to 180 seconds, about 150 words per minute. The render script prints a note outside that range.

### 4. Write `scenes.py`

Manim Community Edition. Use `Text`, shapes, and arrows only. No `MathTex`, `Tex`, or any LaTeX. No audio calls.

Each scene reads its length from the `SCENE_DURATION` environment variable (seconds, set from the measured narration) and holds until then.

```python
import os
from manim import Scene, Text, FadeIn

DURATION = float(os.environ.get("SCENE_DURATION", "4"))

class Intro(Scene):
    def construct(self):
        self.play(FadeIn(Text("Queue", font_size=48)), run_time=1)
        self.wait(max(0.0, DURATION - 1))
```

Keep the animations in a scene shorter than its duration. Keep every object inside the frame (about 14 units wide, 8 high): use `font_size` 24 or larger, call `.scale_to_fit_width(12)` on long text, and space objects so labels do not overlap. Start each scene from a clean frame.

### 5. Render

```bash
"$HOME/.claude/bin/ccgm-explainer-render" explainer-<topic>
```

The script picks a voice (ElevenLabs when `ELEVENLABS_API_KEY` is set and the text is within `ELEVENLABS_MAX_CHARS`, Kokoro when vetted, else macOS `say -o`) and prints which. It measures each narration, renders each scene to that length, joins them, and checks the result: one video stream, one audio stream, total length within 10 percent of the narration. It exits non-zero and names the failed check. It writes `explainer.mp4` and one frame per scene to `frames/`.

### 6. Inspect the frames

Read every PNG in `frames/`. Look for overlapping text, text or shapes off screen, and scenes that are empty. Fix `scenes.py`, then rebuild only the broken scenes:

```bash
"$HOME/.claude/bin/ccgm-explainer-render" explainer-<topic> --scenes intro,flow
```

Repeat until the frames are clean.

### 7. Report

Print the absolute path of `explainer.mp4`, then three lines: what the video covers, its length, and the voice used. Do not open or play the file.
