"""Tests for recall.py - session summary extraction and query filtering."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import recall  # noqa: E402
import repo_detect  # noqa: E402


def _make_jsonl(path: Path, turns: list[dict]) -> None:
    """Write a list of turn-dicts to a JSONL file."""
    with path.open("w") as f:
        for turn in turns:
            f.write(json.dumps(turn) + "\n")


def _user_turn(text: str, branch: str = "main", ts: str = "2026-04-18T12:00:00Z") -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "gitBranch": branch,
        "message": {"role": "user", "content": text},
    }


def _assistant_turn(text: str, ts: str = "2026-04-18T12:00:01Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _tool_result_user_turn(ts: str = "2026-04-18T12:00:02Z") -> dict:
    """A user-role message that wraps only a tool_result — common in Claude API
    but should be excluded from human-readable summaries."""
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
        },
    }


def test_summarize_session_extracts_first_and_last_user_msgs(tmp_path):
    jsonl = tmp_path / "session-abc.jsonl"
    _make_jsonl(
        jsonl,
        [
            _user_turn("What is the plan?"),
            _assistant_turn("The plan is X."),
            _user_turn("Explain X."),
            _assistant_turn("X means..."),
        ],
    )
    project_dir = tmp_path
    meta = recall._summarize_session(jsonl, "testrepo", project_dir)
    assert meta is not None
    assert meta.first_user_msg == "What is the plan?"
    assert meta.last_user_msg == "Explain X."
    assert meta.turn_count == 2  # two real user turns
    assert meta.branch == "main"
    assert meta.session_id == "session-abc"


def test_summarize_session_skips_tool_result_user_turns(tmp_path):
    """tool_result-only user turns must not pollute the summary."""
    jsonl = tmp_path / "session-xyz.jsonl"
    _make_jsonl(
        jsonl,
        [
            _user_turn("Run the build"),
            _assistant_turn("running..."),
            _tool_result_user_turn(),  # should be skipped for summary
            _assistant_turn("Build complete"),
        ],
    )
    meta = recall._summarize_session(jsonl, "testrepo", tmp_path)
    assert meta is not None
    assert meta.first_user_msg == "Run the build"
    assert meta.last_user_msg == "Run the build"  # tool_result did not override
    assert meta.turn_count == 1


def test_summarize_session_skips_system_reminders(tmp_path):
    """System-injected user turns starting with <...> tags must be excluded."""
    jsonl = tmp_path / "session-sys.jsonl"
    _make_jsonl(
        jsonl,
        [
            _user_turn("<system-reminder>do not expose</system-reminder>"),
            _user_turn("Real question here"),
        ],
    )
    meta = recall._summarize_session(jsonl, "testrepo", tmp_path)
    assert meta is not None
    assert meta.first_user_msg == "Real question here"
    assert meta.turn_count == 1


def test_summarize_session_handles_empty_file(tmp_path):
    jsonl = tmp_path / "empty.jsonl"
    jsonl.touch()
    assert recall._summarize_session(jsonl, "testrepo", tmp_path) is None


def test_summarize_session_handles_malformed_lines(tmp_path):
    jsonl = tmp_path / "broken.jsonl"
    with jsonl.open("w") as f:
        f.write("{ not valid json\n")
        f.write(json.dumps(_user_turn("survived")) + "\n")
        f.write("also broken {\n")
    meta = recall._summarize_session(jsonl, "testrepo", tmp_path)
    assert meta is not None
    assert meta.first_user_msg == "survived"


def test_find_sessions_filters_by_mtime(tmp_path, monkeypatch):
    """Sessions older than the cutoff are excluded."""
    fake_projects = tmp_path / "projects"
    project_dir = fake_projects / "-fake-testrepo"
    project_dir.mkdir(parents=True)
    recent = project_dir / "recent.jsonl"
    old = project_dir / "old.jsonl"
    _make_jsonl(recent, [_user_turn("recent")])
    _make_jsonl(old, [_user_turn("old")])

    # Set old to 30 days ago
    old_mtime = time.time() - 30 * 86400
    import os
    os.utime(old, (old_mtime, old_mtime))

    with patch.object(repo_detect, "CLAUDE_PROJECTS", fake_projects):
        sessions = recall._find_sessions("testrepo", days=7)

    names = [s.session_id for s in sessions]
    assert "recent" in names
    assert "old" not in names


def test_extract_text_string_content():
    assert recall._extract_text("hello") == "hello"


def test_extract_text_list_content_with_tool_use():
    content = [
        {"type": "text", "text": "I'll run a command"},
        {"type": "tool_use", "name": "Bash"},
    ]
    assert "I'll run a command" in recall._extract_text(content)
    assert "tool_use: Bash" in recall._extract_text(content)


def test_extract_text_without_tool_markers():
    content = [
        {"type": "text", "text": "here is the answer"},
        {"type": "tool_result", "content": "..."},
    ]
    text = recall._extract_text(content, include_tool_markers=False)
    assert "here is the answer" in text
    assert "tool_result" not in text


def test_truncate():
    assert recall._truncate("short") == "short"
    long = "x" * 200
    assert len(recall._truncate(long, n=50)) == 50


def test_fmt_date():
    # Use a known epoch value: 2026-04-18 00:00:00 UTC is approximately 1771891200
    # Use a controlled value and check format pattern instead.
    result = recall._fmt_date(time.time())
    assert len(result) == 10  # YYYY-MM-DD
    assert result[4] == "-" and result[7] == "-"
