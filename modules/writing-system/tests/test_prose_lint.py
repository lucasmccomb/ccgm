"""Tests for prose_lint (STE-lite measurements) and the ccgm-prose-lint CLI."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import prose_lint  # noqa: E402

RULE_NAMES = ("sentence-length", "paragraph-length", "two-actions", "diagram-width")
CLI = ROOT / "bin" / "ccgm-prose-lint"


def sentence(first, n):
    """A sentence of exactly n words starting with `first`."""
    filler = ["alpha", "beta", "gamma"]
    return first + " " + " ".join(filler[i % 3] for i in range(n - 1)) + "."


def errors(text):
    return [f for f in prose_lint.lint(text) if f.level == "error"]


def rules(text, level=None):
    return [f.rule for f in prose_lint.lint(text) if level in (None, f.level)]


def run_cli(args, text=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args], input=text, capture_output=True, text=True
    )


# --- sentence length by kind -------------------------------------------------

def test_instruction_of_20_words_passes():
    assert not errors(sentence("Run", 20))


def test_instruction_of_21_words_is_error():
    found = errors(sentence("Run", 21))
    assert [f.rule for f in found] == ["sentence-length"]


def test_description_of_21_words_passes():
    assert not errors(sentence("The", 21))


def test_description_of_25_words_passes_and_26_is_error():
    assert not errors(sentence("The", 25))
    assert [f.rule for f in errors(sentence("The", 26))] == ["sentence-length"]


def test_descriptive_bullet_starting_with_ambiguous_word_is_not_an_instruction():
    bullet = "- Store layer gains a dwell field that excludes written rows from search until the review window closes and the owner confirms them."
    assert len(bullet[2:].split()) == 22
    assert not errors(bullet)


def test_imperative_bullet_of_21_words_is_error():
    bullet = "- " + sentence("Store", 21).replace("Store alpha", "Store the")
    assert len(bullet[2:].split()) == 21
    assert [f.rule for f in errors(bullet)] == ["sentence-length"]


# --- paragraph length --------------------------------------------------------

def test_seven_sentence_paragraph_is_error_and_six_is_not():
    six = " ".join(["The cat sat."] * 6)
    assert not errors(six)
    assert [f.rule for f in errors(six + " The cat sat.")] == ["paragraph-length"]


def test_seven_item_list_is_not_a_long_paragraph():
    items = "\n".join(f"- Item number {n} is here." for n in range(7))
    assert not errors(items)


def test_blank_line_ends_a_paragraph():
    text = " ".join(["The cat sat."] * 4) + "\n\n" + " ".join(["The cat sat."] * 4)
    assert not errors(text)


# --- stripping ---------------------------------------------------------------

def test_fenced_code_inline_code_tables_urls_and_file_refs_never_produce_findings():
    long = " ".join(["word"] * 40)
    text = "\n".join([
        "---", "title: " + long, "---",
        "# " + long,
        "```python", long, "```",
        "~~~", long, "~~~",
        "| " + long + " | b |", "|---|---|",
        "See https://example.com/" + "a" * 80 + " now.",
        "Edit src/app/main.py:123 and lib/x.py:4:5 today.",
        "Run `" + long + "` now.",
    ])
    assert prose_lint.lint(text) == []


def test_markdown_link_keeps_its_text_and_drops_the_url():
    assert prose_lint.stats("See [the guide](https://example.com/long/path) now.")["words"] == 4


# --- sentence splitting ------------------------------------------------------

def test_abbreviations_versions_and_paths_do_not_split_sentences():
    text = "Use tools, e.g. grep, i.e. fast ones, in v1.2 via lib/prose_lint.py today."
    assert prose_lint.stats(text)["sentences"] == 1


def test_pr_reference_with_period_splits_before_next_sentence():
    assert prose_lint.stats("We fixed it in PR #1138. Next we ship it.")["sentences"] == 2


def test_hard_wrapped_lines_join_into_one_sentence():
    assert prose_lint.stats("The cat\nsat on the\nmat.")["sentences"] == 1


# --- warnings ----------------------------------------------------------------

def test_two_action_step_warns():
    assert "two-actions" in rules("Open the file and edit the header.", "warning")
    assert "two-actions" not in rules("Open the file.")


# --- stats -------------------------------------------------------------------

def test_stats_keys_and_values():
    s = prose_lint.stats("Run the tests.\n\n- The suite is fast.")
    assert set(s) == {
        "words", "sentences", "paragraphs", "instruction_sentences",
        "descriptive_sentences", "max_sentence_words", "mean_sentence_words",
        "max_paragraph_sentences", "errors", "warnings",
        "p90_sentence_words", "sentences_over_limit", "pct_over_limit", "by_rule",
    }
    assert s["p90_sentence_words"] == 4
    assert s["sentences_over_limit"] == 0 and s["pct_over_limit"] == 0
    assert s["by_rule"] == dict.fromkeys(RULE_NAMES, 0)
    assert s["sentences"] == 2 and s["paragraphs"] == 2
    assert s["instruction_sentences"] == 1 and s["descriptive_sentences"] == 1
    assert s["words"] == 7 and s["max_sentence_words"] == 4


def test_stats_of_empty_text():
    s = prose_lint.stats("")
    assert s["sentences"] == 0 and s["mean_sentence_words"] == 0
    assert s["p90_sentence_words"] == 0 and s["pct_over_limit"] == 0
    assert s["sentences_over_limit"] == 0
    assert s["by_rule"] == dict.fromkeys(RULE_NAMES, 0)


def test_stats_over_limit_p90_and_by_rule():
    text = sentence("Run", 25) + " " + " ".join(["The cat sat."] * 9) + " See #1138."
    s = prose_lint.stats(text)
    assert s["sentences"] == 11
    assert s["sentences_over_limit"] == 1
    assert s["pct_over_limit"] == 9.1
    assert s["p90_sentence_words"] == 3  # nearest rank: ceil(0.9 * 11) = 10th of 11 sorted: 2, 3 x9, 25
    assert s["by_rule"]["sentence-length"] == 1
    assert s["by_rule"]["paragraph-length"] == 1


def test_sentence_word_counts_match_stats():
    text = sentence("Run", 25) + " " + " ".join(["The cat sat."] * 9) + " See #1138.\n\n- Fix `a b c` now."
    counts = prose_lint.sentence_word_counts(text)
    s = prose_lint.stats(text)
    assert len(counts) == s["sentences"]
    assert sum(counts) == s["words"]
    assert counts[0] == 25
    ranked = sorted(counts)
    assert ranked[-(-9 * len(counts) // 10) - 1] == s["p90_sentence_words"]
    assert prose_lint.sentence_word_counts("") == []


# --- diagram width -----------------------------------------------------------

def fenced(*lines):
    return "Intro.\n\n```\n" + "\n".join(lines) + "\n```\n"


def test_box_line_of_101_characters_is_error():
    line = "┌" + "─" * 99 + "┐"
    assert len(line) == 101
    found = errors(fenced(line))
    assert [f.rule for f in found] == ["diagram-width"]
    assert found[0].line == 4 and "101" in found[0].message


def test_box_line_of_100_characters_passes():
    assert not errors(fenced("┌" + "─" * 98 + "┐"))


def test_multibyte_box_characters_count_as_one_column():
    line = "│" * 100  # 300 bytes, 100 characters
    assert len(line.encode()) == 300
    assert not errors(fenced(line))


def test_long_line_in_plain_code_block_passes():
    assert not errors(fenced("x = " + "a" * 136))


def test_long_line_outside_fence_is_not_diagram_width():
    assert "diagram-width" not in rules("│" * 101 + "\n")


def test_one_box_character_anywhere_marks_the_block_as_a_diagram():
    assert rules(fenced("a" * 101, "┌─┐"), "error") == ["diagram-width"]


def test_unclosed_fence_at_end_of_file_is_still_checked():
    text = "Intro.\n\n```\n┌" + "─" * 99 + "┐\n"
    assert [f.rule for f in errors(text)] == ["diagram-width"]


def test_diagram_width_counts_in_stats():
    s = prose_lint.stats(fenced("┌" + "─" * 99 + "┐"))
    assert s["by_rule"]["diagram-width"] == 1 and s["errors"] == 1


def test_cli_strict_fails_on_wide_diagram():
    r = run_cli(["--strict"], fenced("┌" + "─" * 99 + "┐"))
    assert r.returncode == 1 and "diagram-width" in r.stdout


def test_instruction_message_uses_an():
    assert "in an instruction" in errors(sentence("Run", 25))[0].message


# --- CLI ---------------------------------------------------------------------

def test_cli_strict_exits_1_on_error_and_0_on_warning_only():
    bad = run_cli(["--strict"], sentence("Run", 25) + "\n")
    assert bad.returncode == 1 and "sentence-length" in bad.stdout
    warn = run_cli(["--strict"], "Open the file and edit the header.\n")
    assert warn.returncode == 0 and "two-actions" in warn.stdout


def test_cli_without_strict_exits_0_on_error():
    assert run_cli([], sentence("Run", 25) + "\n").returncode == 0


def test_cli_json_schema():
    text = sentence("Run", 25) + " See #1138.\n"
    data = json.loads(run_cli(["--json"], text).stdout)
    assert set(data) == {"findings", "stats"}
    assert data["findings"]
    for f in data["findings"]:
        assert set(f) == {"line", "level", "rule", "message", "text"}
        assert isinstance(f["line"], int) and f["level"] in ("error", "warning")
    assert data["stats"] == prose_lint.stats(text)
    assert data["stats"]["by_rule"] == {"sentence-length": 1, "paragraph-length": 0, "two-actions": 0, "diagram-width": 0}
    assert data["stats"]["sentences_over_limit"] == 1
    assert data["stats"]["pct_over_limit"] == 50.0
    assert data["stats"]["p90_sentence_words"] == 25


def test_cli_reads_a_file_and_dash(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(sentence("Run", 25) + "\n")
    assert "a.md:1:" in run_cli([str(p)]).stdout
    assert "sentence-length" in run_cli(["-"], p.read_text()).stdout


def test_cli_missing_file_exits_2(tmp_path):
    assert run_cli([str(tmp_path / "nope.md")]).returncode == 2


# --- precision fixes ---------------------------------------------------------

def test_sentence_starting_with_inline_code_stays_a_separate_sentence():
    text = ("Run the linter on the file. `ccgm-prose-lint` reads stdin when no file is given "
            "and prints one finding per line for each problem it finds.")
    s = prose_lint.stats(text)
    assert s["sentences"] == 2
    assert not errors(text)


def test_inline_code_still_adds_no_words():
    assert prose_lint.stats("Run `foo` now.")["words"] == 2




# --- splitter: lowercase starts, ID lists ------------------------------------

def test_lowercase_word_after_a_full_stop_starts_a_new_sentence():
    assert prose_lint.stats("That is the default. iOS plays that at alarm volume.")["sentences"] == 2
    assert prose_lint.stats("It comes from lem-work. devtrainer stays the drills product.")["sentences"] == 2
    assert prose_lint.stats("Is it done? yes it is.")["sentences"] == 2


def test_abbreviations_and_versions_do_not_split_before_lowercase():
    assert prose_lint.stats("Use tools, e.g. foo bar today.")["sentences"] == 1
    assert prose_lint.stats("Use grep, sed, etc. and more today.")["sentences"] == 1
    assert prose_lint.stats("Version v1.2 is out today.")["sentences"] == 1
    assert prose_lint.stats("Wait... then go on.")["sentences"] == 1


def test_lowercase_start_is_not_classed_as_the_previous_instruction():
    text = "Skip for this purpose. evoglyph has paying users " + " ".join(["alpha"] * 10) + "."
    assert prose_lint.stats(text)["instruction_sentences"] == 1
    assert not errors(text)


def test_id_list_sentence_is_skipped():
    line = ("(XP-3): E0, E1, E2, E4 in parallel; E3 after E0; E5 after E3; E6 after E4; "
            "E7 after E5; E8 after E6; E9 after E7 and E8 then E10 after E9.")
    assert prose_lint.lint(line) == []
    assert prose_lint.stats(line)["sentences"] == 0


def test_removed_checks_produce_no_findings():
    assert prose_lint.lint("See #1138 for details. The config file schema validator fails.") == []
