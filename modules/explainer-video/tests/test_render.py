"""Tests for ccgm-explainer-render.

Backend selection, the missing-tool check, and the lint hook run everywhere.
The render test needs macOS `say`, `uv`, ffmpeg, and cairo/pango, so it skips
with a printed note when any is missing (CI has none of them).
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "bin" / "ccgm-explainer-render"
FIXTURE = HERE / "fixtures" / "two-scene"


def load_module():
    loader = importlib.machinery.SourceFileLoader("ccgm_explainer_render", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def tools(*names):
    """A fake `which` that finds only the named tools."""
    return lambda name: f"/stub/{name}" if name in names else None


# --- backend chain -----------------------------------------------------------


def test_say_is_the_default_when_nothing_else_is_configured():
    r = load_module()
    name, _ = r.choose_backend({}, tools("say", "uv"), chars=100)
    assert name == "say"


def test_elevenlabs_wins_when_key_is_set():
    r = load_module()
    name, _ = r.choose_backend({"ELEVENLABS_API_KEY": "k"}, tools("say", "uv"), chars=100)
    assert name == "elevenlabs"


def test_elevenlabs_over_char_cap_falls_back_and_says_so():
    r = load_module()
    env = {"ELEVENLABS_API_KEY": "k", "ELEVENLABS_MAX_CHARS": "50"}
    name, note = r.choose_backend(env, tools("say", "uv"), chars=51)
    assert name == "say"
    assert "ELEVENLABS_MAX_CHARS" in note and "51" in note


def test_elevenlabs_default_cap_is_5000():
    r = load_module()
    env = {"ELEVENLABS_API_KEY": "k"}
    assert r.choose_backend(env, tools("say", "uv"), chars=5000)[0] == "elevenlabs"
    assert r.choose_backend(env, tools("say", "uv"), chars=5001)[0] == "say"


def test_kokoro_needs_vetting_flag_espeak_and_uv():
    r = load_module()
    env = {"CCGM_KOKORO_VETTED": "1"}
    assert r.choose_backend(env, tools("say", "uv", "espeak-ng"), chars=10)[0] == "kokoro"
    assert r.choose_backend({}, tools("say", "uv", "espeak-ng"), chars=10)[0] == "say"
    assert r.choose_backend(env, tools("say", "uv"), chars=10)[0] == "say"


def test_elevenlabs_beats_kokoro():
    r = load_module()
    env = {"ELEVENLABS_API_KEY": "k", "CCGM_KOKORO_VETTED": "1"}
    assert r.choose_backend(env, tools("say", "uv", "espeak-ng"), chars=10)[0] == "elevenlabs"


def test_no_backend_is_an_error():
    r = load_module()
    with pytest.raises(r.RenderError) as e:
        r.choose_backend({}, tools("uv"), chars=10)
    assert "narration backend" in str(e.value)


# --- fail fast ---------------------------------------------------------------


def fake_tool(directory, name):
    p = directory / name
    p.write_text("#!/bin/sh\nexit 0\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def run_with_tools(tmp_path, names):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for t in names:
        fake_tool(bindir, t)
    proj = tmp_path / "proj"
    shutil.copytree(FIXTURE, proj)
    env = {"PATH": str(bindir), "HOME": str(tmp_path)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(proj)], env=env, capture_output=True, text=True
    )


def test_missing_uv_fails_fast_with_named_error(tmp_path):
    res = run_with_tools(tmp_path, ("ffmpeg", "ffprobe", "say"))
    assert res.returncode == 2
    assert "missing required tool: uv" in res.stderr


def test_missing_ffmpeg_fails_fast_with_named_error(tmp_path):
    res = run_with_tools(tmp_path, ("uv", "ffprobe", "say"))
    assert res.returncode == 2
    assert "missing required tool: ffmpeg" in res.stderr


# --- narration lint hook -----------------------------------------------------


def test_lint_output_is_returned_when_linter_is_installed(tmp_path):
    r = load_module()
    linter = tmp_path / ".claude" / "bin" / "ccgm-prose-lint"
    linter.parent.mkdir(parents=True)
    linter.write_text("#!/bin/sh\ncat >/dev/null\necho 'warn: sentence too long'\n")
    linter.chmod(0o755)
    assert "sentence too long" in r.lint_narration(["One.", "Two."], home=tmp_path)


def test_lint_is_skipped_when_linter_is_missing(tmp_path):
    r = load_module()
    assert r.lint_narration(["One."], home=tmp_path) is None


# --- full render (macOS only) ------------------------------------------------


def render_prereqs_missing():
    missing = [t for t in ("say", "uv", "ffmpeg", "ffprobe") if not shutil.which(t)]
    has_cairo = any(
        Path(p).exists() for p in ("/opt/homebrew/opt/cairo", "/usr/local/opt/cairo")
    ) or (
        shutil.which("pkg-config") is not None
        and subprocess.run(["pkg-config", "--exists", "cairo", "pangocairo"]).returncode == 0
    )
    if not has_cairo:
        missing.append("cairo/pango")
    return missing


def probe(path, *args):
    out = subprocess.run(
        ["ffprobe", "-v", "error", *args, "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def duration(path):
    return float(probe(path, "-show_entries", "format=duration")["format"]["duration"])


def test_two_scene_render_with_say(tmp_path):
    missing = render_prereqs_missing()
    if missing:
        print(f"SKIP: render test needs {', '.join(missing)}")
        pytest.skip(f"missing: {', '.join(missing)}")
    proj = tmp_path / "proj"
    shutil.copytree(FIXTURE, proj)
    env = {k: v for k, v in os.environ.items() if k not in ("ELEVENLABS_API_KEY", "CCGM_KOKORO_VETTED")}
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(proj)],
        env=env, capture_output=True, text=True, timeout=900,
    )
    assert res.returncode == 0, res.stderr + res.stdout
    assert "voice: say" in res.stdout

    video = proj / "explainer.mp4"
    streams = probe(video, "-show_entries", "stream=codec_type")["streams"]
    assert sorted(s["codec_type"] for s in streams) == ["audio", "video"]

    narration = sum(duration(w) for w in (proj / "build").glob("*.wav"))
    total = duration(video)
    assert abs(total - narration) <= 0.10 * narration

    assert sorted(p.name for p in (proj / "frames").glob("*.png")) == ["flow.png", "intro.png"]
