"""Tests for bin/ccgm-output-metrics.

Transcripts are synthetic but follow the record shapes Claude Code writes:
human prompts carry origin.kind == "human", task notifications carry another
origin, skill expansions carry isMeta, tool results carry no origin, and an
AskUserQuestion answer arrives in toolUseResult.answers.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

MODULES = Path(__file__).resolve().parents[2]
SCRIPT = MODULES / "output-formatting" / "bin" / "ccgm-output-metrics"
PATTERNS = MODULES / "output-formatting" / "lib" / "comprehension-patterns.json"

BASE_MINUTE = [0]


def _ts(minute):
    return f"2026-10-01T{minute // 60:02d}:{minute % 60:02d}:00.000Z"


class Session:
    """Builds one transcript file, one JSON object per line."""

    def __init__(self, project_dir, name="s1", model="model-a"):
        self.path = project_dir / f"{name}.jsonl"
        self.model = model
        self.minute = 0
        self.lines = []
        self.n = 0

    def _add(self, rec):
        self.minute += 1
        rec.setdefault("isSidechain", False)
        rec.setdefault("timestamp", _ts(self.minute))
        self.lines.append(rec)

    def human(self, text, source="typed"):
        self._add({"type": "user", "origin": {"kind": "human"}, "promptSource": source,
                   "message": {"role": "user", "content": text}})

    def command(self, name):
        self.human(f"<command-message>{name}</command-message>\n<command-name>/{name}</command-name>")

    def task_notification(self):
        self._add({"type": "user", "origin": {"kind": "task-notification"}, "promptSource": "system",
                   "message": {"role": "user", "content": "<task-notification>job done</task-notification>"}})

    def skill_expansion(self):
        self._add({"type": "user", "isMeta": True,
                   "message": {"role": "user", "content": [
                       {"type": "text", "text": "Base directory for this skill: /x\n\nwhat do you mean"}]}})

    def tool_result(self, tool_id, answers=None):
        rec = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]}}
        if answers is not None:
            rec["toolUseResult"] = {"questions": [], "answers": answers}
        self._add(rec)

    def tool_use(self, name, tool_input=None, tool_id=None):
        self.n += 1
        tool_id = tool_id or f"toolu_{self.n}"
        self._add({"type": "assistant", "message": {"model": self.model, "role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input or {}}]}})
        return tool_id

    def text(self, text):
        self._add({"type": "assistant", "message": {"model": self.model, "role": "assistant", "content": [
            {"type": "text", "text": text}]}})

    def write(self):
        self.path.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in self.lines) + "\n")
        return self.path


@pytest.fixture
def env(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "prose_lint.py").symlink_to(MODULES / "writing-system" / "lib" / "prose_lint.py")
    (lib / "transcript_miner.py").symlink_to(MODULES / "dreaming" / "lib" / "transcript_miner.py")
    projects = tmp_path / "projects"
    projects.mkdir()
    e = dict(os.environ, CCGM_LIB=str(lib), CCGM_PROJECTS=str(projects))
    return {"env": e, "projects": projects, "lib": lib, "tmp": tmp_path}


def run(env, *args, expect=0):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], env=env["env"],
                       capture_output=True, text=True)
    assert r.returncode == expect, r.stderr
    return r


def metrics(env, *args):
    return json.loads(run(env, "--json", *args).stdout)


def project(env, slug):
    d = env["projects"] / slug
    d.mkdir(exist_ok=True)
    return d


ASCII_ONE = "Layout:\n```\n┌──────┐\n│ box  │\n└──────┘\n```"
ASCII_THREE = "Flow:\n```\n┌────┐ ┌────┐ ┌────┐\n│ a  │ │ b  │ │ c  │\n└────┘ └────┘ └────┘\n```"
MERMAID_TWO = "Flow:\n```mermaid\nflowchart LR\n  A[start] --> B[end]\n```"
BRIEF = "what do you mean " + "x" * 2000


def build_main_session(env):
    d = project(env, "-proj-a")
    s = Session(d, model="model-a")
    # T1: final text after tool calls, a task notification mid-turn
    s.human("build it")
    tid = s.tool_use("Bash")
    s.tool_result(tid)
    s.task_notification()
    s.text("Built. Tests pass.")
    # T2: slash command, skill expansion, mermaid with 2 nodes
    s.command("explain")
    s.skill_expansion()
    s.text(MERMAID_TWO)
    # T3: no text at all
    s.human("look around")
    s.tool_use("Read")
    # T4: Artifact page with a short final message
    s.human("make a page")
    s.tool_use("Artifact")
    s.text("Page is at /nonexistent/report.html")
    # T5: ASCII diagram with one box
    s.human("draw it")
    s.text(ASCII_ONE)
    # T6: ASCII diagram with three boxes
    s.human("draw more")
    s.text(ASCII_THREE)
    # T7: AskUserQuestion answered with free text that matches
    s.human("pick one")
    qid = s.tool_use("AskUserQuestion", {"questions": [
        {"question": "Which?", "options": [{"label": "Alpha"}, {"label": "Beta, v2"}]}]})
    s.tool_result(qid, {"Which?": "what context?"})
    s.text("Explained.")
    # T8: AskUserQuestion answered with offered options (including a comma label)
    s.human("pick again")
    qid = s.tool_use("AskUserQuestion", {"questions": [
        {"question": "Which?", "options": [{"label": "Alpha"}, {"label": "Beta, v2"}]}]})
    s.tool_result(qid, {"Which?": "Alpha, Beta, v2"})
    s.text("Picked.")
    # T9 then T10: short confused follow-up after T9
    s.human("summarize")
    s.text("Summary text.")
    s.human("what do you mean?")
    s.text("Meaning text.")
    # T11: 2,000-char brief that starts with a pattern
    s.human(BRIEF)
    s.text("Ok.")
    s.write()

    d2 = project(env, "-proj-b")
    b = Session(d2, name="s2", model="model-b")
    b.human("explain")
    long_sentence = " ".join(["word"] * 40) + "."
    b.text(long_sentence + " Short one.")
    b.write()


def test_script_exists_and_is_executable():
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)


def test_turn_counts_exclude_harness_records(env):
    build_main_session(env)
    m = metrics(env)
    o = m["overall"]
    # 11 prompts in proj-a (one is a slash command) + 1 in proj-b.
    # Task notification, isMeta expansion and tool results start no turn.
    assert o["turns"] == 11
    assert o["slash_turns"] == 1


def test_final_message_is_last_text_block_and_no_text_turn_has_none(env):
    build_main_session(env)
    o = metrics(env)["overall"]
    # proj-a: 11 turns, T3 has no text -> 10; proj-b: 1
    assert o["final_messages"] == 11


def test_medium_counts(env):
    build_main_session(env)
    med = metrics(env)["overall"]["medium"]
    assert med["mermaid_blocks"] == 1
    assert med["ascii_diagrams"] == 2
    assert med["artifact_uses"] == 1
    assert med["html_paths"] == 1
    assert med["mp4_paths"] == 0


def test_over_climbing_counts_small_diagrams_and_thin_pages(env):
    build_main_session(env)
    oc = metrics(env)["overall"]["over_climbing"]
    # mermaid with 2 nodes, ASCII with 1 box, page with a short final message
    assert oc["events"] == 3


def test_over_climbing_page_with_long_source_is_not_flagged(env):
    d = project(env, "-proj-a")
    src = env["tmp"] / "page.md"
    src.write_text("\n".join(f"line {i}" for i in range(60)))
    s = Session(d)
    s.human("page")
    s.tool_use("Artifact")
    s.text(f"Page: {env['tmp']}/page.html (source {src})")
    s.write()
    assert metrics(env)["overall"]["over_climbing"]["events"] == 0


def test_over_climbing_page_with_short_source_is_flagged(env):
    d = project(env, "-proj-a")
    src = env["tmp"] / "page.md"
    src.write_text("\n".join(f"line {i}" for i in range(10)))
    s = Session(d)
    s.human("page")
    s.tool_use("Artifact")
    s.text(f"Page: {env['tmp']}/page.html (source {src})")
    s.write()
    assert metrics(env)["overall"]["over_climbing"]["events"] == 1


def test_comprehension_counts_followup_and_ask_answers_only(env):
    build_main_session(env)
    c = metrics(env)["overall"]["comprehension"]
    assert c["followup_events"] == 1   # "what do you mean?" after T9
    assert c["ask_events"] == 1        # "what context?" as an Other answer
    assert c["events"] == 2
    # The skill expansion text and the 2,000-char brief never count.


def test_long_brief_with_pattern_phrase_does_not_count(env):
    d = project(env, "-proj-a")
    s = Session(d)
    s.human("first")
    s.text("One.")
    s.human(BRIEF)
    s.text("Two.")
    s.write()
    assert metrics(env)["overall"]["comprehension"]["events"] == 0


def test_slash_command_followup_does_not_count(env):
    d = project(env, "-proj-a")
    s = Session(d)
    s.human("first")
    s.text("One.")
    s.command("explain")
    s.text("Two.")
    s.write()
    assert metrics(env)["overall"]["comprehension"]["events"] == 0


def test_slash_turn_ask_answer_is_excluded(env):
    d = project(env, "-proj-a")
    s = Session(d)
    s.command("explain")
    qid = s.tool_use("AskUserQuestion", {"questions": [{"question": "Q", "options": [{"label": "A"}]}]})
    s.tool_result(qid, {"Q": "huh"})
    s.text("Done.")
    s.write()
    assert metrics(env)["overall"]["comprehension"]["events"] == 0


def test_prose_stats(env):
    build_main_session(env)
    p = metrics(env)["overall"]["prose"]
    assert p["sentences_over_limit"] >= 1
    assert p["sentences"] > p["sentences_over_limit"]
    assert p["p90_sentence_words"] >= 1
    assert set(p["by_rule"]) == {"sentence-length", "paragraph-length", "two-actions"}


def test_prose_sentence_over_limit_isolated_by_project(env):
    build_main_session(env)
    m = metrics(env, "--project=-proj-b")
    p = m["overall"]["prose"]
    assert p["sentences"] == 2
    assert p["sentences_over_limit"] == 1
    assert p["pct_over_limit"] == 50.0
    assert p["p90_sentence_words"] == 40


def test_length_stats(env):
    d = project(env, "-proj-a")
    s = Session(d)
    for lines in (1, 3, 5):
        s.human("q")
        s.text("\n".join(f"Line {i}." for i in range(lines)))
    s.write()
    ln = metrics(env)["overall"]["length"]
    assert ln["lines_median"] == 3
    assert ln["lines_p90"] == 5
    assert ln["words_median"] == 6


def test_splits_by_model_and_project(env):
    build_main_session(env)
    m = metrics(env)
    assert set(m["by_model"]) == {"model-a", "model-b"}
    assert set(m["by_project"]) == {"-proj-a", "-proj-b"}
    assert m["by_model"]["model-b"]["turns"] == 1
    assert m["by_project"]["-proj-a"]["turns"] == 10
    assert m["by_model"]["model-a"]["comprehension"]["events"] == 2


def test_insufficient_data_below_20_events(env):
    build_main_session(env)
    c = metrics(env)["overall"]["comprehension"]
    assert c["insufficient_data"] is True
    out = run(env).stdout
    assert re.search(r"comprehension.*insufficient data", out)


def test_enough_events_reports_the_rate(env):
    d = project(env, "-proj-a")
    s = Session(d)
    for _ in range(25):
        s.human("do a thing")
        s.text("Done.")
        s.human("tl;dr")
        s.text("Short.")
    s.write()
    c = metrics(env)["overall"]["comprehension"]
    assert c["followup_events"] == 25
    assert c["insufficient_data"] is False
    assert c["per_100_turns"] == 50.0


def test_since_until_window_filters_turns(env):
    d = project(env, "-proj-a")
    s = Session(d)
    s.human("early")      # 00:01
    s.text("One.")
    s.human("middle")     # 00:03
    s.text("Two.")
    s.human("late")       # 00:05
    s.text("Three.")
    s.write()
    m = metrics(env, "--since", "2026-10-01T00:02:00Z", "--until", "2026-10-01T00:04:00Z")
    assert m["overall"]["turns"] == 1


def test_subagent_transcripts_are_ignored(env):
    d = project(env, "-proj-a")
    sub = d / "subagents"
    sub.mkdir()
    s = Session(sub, name="agent-1")
    s.human("hello")
    s.text("Hi.")
    s.write()
    assert metrics(env)["overall"]["turns"] == 0


def test_missing_library_exits_2_and_names_it(env):
    (env["lib"] / "prose_lint.py").unlink()
    r = subprocess.run([sys.executable, str(SCRIPT), "--json"], env=env["env"],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "prose_lint" in r.stderr
    assert "writing-system" in r.stderr


def test_json_schema_is_pinned(env):
    build_main_session(env)
    m = metrics(env)
    assert set(m) == {"schema_version", "window", "project", "files_scanned",
                      "overall", "by_model", "by_project"}
    assert m["schema_version"] == 1
    assert set(m["window"]) == {"since", "until"}
    group_keys = {"turns", "slash_turns", "final_messages", "prose", "length", "medium",
                  "over_climbing", "comprehension", "long_no_medium"}
    assert set(m["overall"]) == group_keys
    assert set(m["overall"]["prose"]) == {
        "sentences", "sentences_over_limit", "pct_over_limit", "p90_sentence_words", "by_rule",
        "insufficient_data"}
    assert set(m["overall"]["length"]) == {"lines_median", "lines_p90", "words_median", "words_p90"}
    assert set(m["overall"]["medium"]) == {
        "ascii_diagrams", "mermaid_blocks", "artifact_uses", "html_paths", "mp4_paths",
        "prose_lines_total"}
    assert set(m["overall"]["over_climbing"]) == {"events", "per_100_turns", "insufficient_data"}
    assert set(m["overall"]["comprehension"]) == {
        "events", "followup_events", "ask_events", "per_100_turns", "insufficient_data"}
    assert set(m["overall"]["long_no_medium"]) == {"events", "per_100_turns", "insufficient_data"}
    for g in m["by_model"].values():
        assert set(g) == group_keys


def test_help_documents_definitions():
    r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    for word in ("over-climbing", "comprehension", "insufficient data"):
        assert word in r.stdout.lower()


# --- comprehension-patterns.json ---------------------------------------------

def _patterns():
    return json.loads(PATTERNS.read_text())["patterns"]


def test_patterns_file_has_one_fixture_per_pattern():
    pats = _patterns()
    names = {p["name"] for p in pats}
    assert {"what_do_you_mean", "dont_understand", "what_context", "huh", "lost_me",
            "too_long", "tldr"} <= names
    for p in pats:
        assert p["regex"] and p["description"] and p["examples"], p["name"]


@pytest.mark.parametrize("pattern", _patterns() if PATTERNS.exists() else [], ids=lambda p: p["name"])
def test_each_pattern_matches_its_examples_in_a_followup(env, pattern):
    for example in pattern["examples"]:
        d = project(env, f"-p-{abs(hash(example)) % 10000}")
        s = Session(d)
        s.human("start")
        s.text("Answer.")
        s.human(example)
        s.text("More.")
        s.write()
    c = metrics(env)["overall"]["comprehension"]
    assert c["followup_events"] == len(pattern["examples"])


def test_ordinary_followups_do_not_match(env):
    d = project(env, "-proj-a")
    s = Session(d)
    for prompt in ("ok go ahead", "what does the config file say", "make it shorter and push",
                   "huge diff, run the tests"):
        s.human("start")
        s.text("Answer.")
        s.human(prompt)
        s.text("More.")
    s.write()
    assert metrics(env)["overall"]["comprehension"]["events"] == 0
