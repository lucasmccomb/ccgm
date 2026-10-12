"""Tests for prose_lint (STE-lite measurements) and the ccgm-prose-lint CLI."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import prose_lint  # noqa: E402

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

def test_bare_reference_warns():
    assert "bare-reference" in rules("See #1138 for details.", "warning")


def test_glossed_reference_does_not_warn():
    assert "bare-reference" not in rules("See PR #1138 (autoheal signature quality) for details.")


def test_reference_warns_once_per_document():
    text = "See #1138 now. Then see #1138 again."
    assert rules(text).count("bare-reference") == 1


def test_other_reference_shapes_warn_and_common_acronyms_do_not():
    for ref in ("adrev-12", "E4", "PR 77", "ZQX"):
        assert "bare-reference" in rules(f"Check {ref} first."), ref
    assert "bare-reference" not in rules("The API returns JSON over HTTP.")


def test_noun_cluster_of_four_warns_and_three_does_not():
    assert "noun-cluster" in rules("The config file schema validator fails.", "warning")
    assert "noun-cluster" not in rules("The config file validator is slow.")


def test_noun_cluster_check_is_removable_through_limits(monkeypatch):
    monkeypatch.delitem(prose_lint.LIMITS, "noun_cluster")
    assert "noun-cluster" not in rules("The config file schema validator fails.")


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
    }
    assert s["sentences"] == 2 and s["paragraphs"] == 2
    assert s["instruction_sentences"] == 1 and s["descriptive_sentences"] == 1
    assert s["words"] == 7 and s["max_sentence_words"] == 4


def test_stats_of_empty_text():
    assert prose_lint.stats("")["sentences"] == 0
    assert prose_lint.stats("")["mean_sentence_words"] == 0


# --- CLI ---------------------------------------------------------------------

def test_cli_strict_exits_1_on_error_and_0_on_warning_only():
    bad = run_cli(["--strict"], sentence("Run", 25) + "\n")
    assert bad.returncode == 1 and "sentence-length" in bad.stdout
    warn = run_cli(["--strict"], "See #1138 now.\n")
    assert warn.returncode == 0 and "bare-reference" in warn.stdout


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


def test_cli_reads_a_file_and_dash(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(sentence("Run", 25) + "\n")
    assert "a.md:1:" in run_cli([str(p)]).stdout
    assert "sentence-length" in run_cli(["-"], p.read_text()).stdout


def test_cli_missing_file_exits_2(tmp_path):
    assert run_cli([str(tmp_path / "nope.md")]).returncode == 2
