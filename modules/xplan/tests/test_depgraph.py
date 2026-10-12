"""Tests for xplan-depgraph and the pinned scripts in xplan-web-review."""
import importlib.machinery
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
TOOL = LIB.parent / "bin" / "xplan-depgraph"
FIX = Path(__file__).resolve().parent / "fixtures" / "depgraph"


def run(plan, *args):
    p = subprocess.run([str(TOOL), str(plan), *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def plan_of(tmp_path, epics):
    """epics: list of (n, wave_line, deps_line) -> plan file."""
    text = "# P\n\n## 5. Agent-Epics\n"
    for n, wave, deps in epics:
        text += f"\n### Epic {n}: Title {n}\n- {wave}\n- {deps}\n- **Scope**: x\n"
    f = tmp_path / "plan.md"
    f.write_text(text)
    return f


def W(n):
    return f"**Wave:** {n}"


def D(s):
    return f"**Dependencies:** {s}"


def load_module():
    loader = importlib.machinery.SourceFileLoader("xplan_depgraph", str(TOOL))
    spec = importlib.util.spec_from_loader("xplan_depgraph", loader)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def deps_of(path):
    m = load_module()
    return {e.num: e.deps for e in m.parse(Path(path).read_text())}


def test_output_ladder_plan_checks_clean():
    code, out, err = run(FIX / "output-ladder.md", "--check")
    assert code == 0, err
    waves = re.findall(r"^Wave (\d+)", out, re.M)
    assert waves == ["1", "2", "3", "4"]
    assert "E8" in out.splitlines()[-1]


def test_output_ladder_dependencies():
    d = deps_of(FIX / "output-ladder.md")
    assert d[1] == [] and d[2] == []
    assert d[8] == [2]
    assert d[7] == [1, 2, 3, 4, 5, 6]
    assert d[3] == [1, 2]


def test_output_line_format(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None")), (2, W(1), D("None")),
                           (3, W(2), D("Epic 1, Epic 2")), (5, W(2), D("Epic 2"))])
    code, out, _ = run(f, "--check")
    assert code == 0
    assert "Wave 2  E3 Title 3 ← E1,E2 · E5 Title 5 ← E2" in out


def test_none_with_parenthetical_has_no_deps(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None")),
                           (2, W(1), D("None (disjoint files from Epic 1)"))])
    assert deps_of(f)[2] == []


def test_optimistic_memory_phrasings():
    d = deps_of(FIX / "optimistic-memory.md")
    assert d[2] == []          # "None (parallel-safe with Epic 1 — ...)"
    assert d[3] == [1, 2]      # "Epic 1 (...), Epic 2 (...)"
    assert d[4] == [2]         # "Epic 2 (posture) — parallel-safe with Epic 3"
    assert d[5] == [3]
    assert d[6] == [1, 3]      # note bullet naming Epic 5/7 is ignored
    assert d[7] == [1, 3]
    assert d[8] == [1, 2, 3, 4, 5, 6, 7]
    code, _, err = run(FIX / "optimistic-memory.md", "--check")
    assert code == 0, err


@pytest.mark.parametrize("text,expected", [
    ("Epic 3", [3]),
    ("Epics 2–4", [2, 3, 4]),
    ("Epics 2-4", [2, 3, 4]),
    ("Epics 1, 2 and 4", [1, 2, 4]),
    ("Epic 1/2", [1, 2]),
    ("Epic 1; also needs the DB", [1]),
    ("parallel-safe with Epic 1", []),
    ("Epic 2, parallel-safe with Epic 3", [2]),
    ("Epic 1, after Wave 2 merges", [1]),
    ("Epic 4 (see PR #12)", [4]),
    ("Epic 4, PR #12", [4]),
    ("Epic 4, pr 12 and issue #40", [4]),
    ("issue #40", []),
    ("Epic 2, #7", [2]),
])
def test_dependency_grammar(tmp_path, text, expected):
    epics = [(n, W(1), D("None")) for n in range(1, 5)] + [(9, W(2), D(text))]
    assert deps_of(plan_of(tmp_path, epics))[9] == expected


def test_template_wave_colon_outside(tmp_path):
    f = plan_of(tmp_path, [(1, "**Wave**: 1", "**Dependencies**: None"),
                           (2, "**Wave**: 2", "**Dependencies**: Epic 1")])
    code, out, err = run(f, "--check")
    assert code == 0, err
    assert "Wave 2  E2 Title 2 ← E1" in out


def test_optional_wave_value(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None")), (2, W("4 (optional)"), D("Epic 1"))])
    code, out, _ = run(f, "--check")
    assert code == 0
    assert "Wave 4  E2" in out


def test_cycle_fails(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("Epic 2")), (2, W(2), D("Epic 1"))])
    code, out, err = run(f, "--check")
    assert code == 1
    assert "cycle" in (out + err) and "E1" in (out + err) and "E2" in (out + err)


def test_unknown_ref_fails(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None")), (2, W(2), D("Epic 1, Epic 7"))])
    code, out, err = run(f, "--check")
    assert code == 1
    assert "E2" in err and "unknown" in err and "Epic 7" in err


def test_same_wave_fails(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None")), (2, W(1), D("Epic 1"))])
    code, _, err = run(f, "--check")
    assert code == 1
    assert "E2" in err and "E1" in err and "same wave" in err


def test_later_wave_fails(tmp_path):
    f = plan_of(tmp_path, [(1, W(3), D("None")), (2, W(1), D("Epic 1"))])
    code, _, err = run(f, "--check")
    assert code == 1
    assert "later wave" in err


def test_duplicate_epic_number_fails(tmp_path):
    f = plan_of(tmp_path, [(3, W(1), D("None")), (3, W(1), D("None")),
                           (3, W(1), D("None"))])
    code, out, err = run(f, "--check")
    assert code == 1
    assert err.count("E3: duplicate epic number") == 1
    assert out.count("E3 Title 3") == 3


def test_without_check_prints_graph_and_exits_zero(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("Epic 9"))])
    code, out, _ = run(f)
    assert code == 0 and "Wave 1  E1" in out


def test_checklist_only_plan_skips(tmp_path):
    f = tmp_path / "plan.md"
    f.write_text("# Plan\n\n- [ ] do a thing\n- [ ] do another\n")
    code, out, _ = run(f, "--check")
    assert code == 0
    assert out.strip() == "no epics; skipped"


def test_prose_mentioning_fields_does_not_override_bullets(tmp_path):
    f = tmp_path / "plan.md"
    f.write_text(
        "### Epic 1: A\n- **Wave:** 1\n- **Dependencies:** None\n\n"
        "### Epic 2: B\n- **Wave:** 2\n- **Dependencies:** Epic 1\n"
        "- **Outputs:**\n  - Grammar: Wave from `**Wave:** 9`, deps come only from the\n"
        "    `**Dependencies:**` bullet's text before the first `(`.\n")
    m = load_module()
    e2 = {e.num: e for e in m.parse(f.read_text())}[2]
    assert e2.wave == 2 and e2.deps == [1]


def test_status_marks_epics(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None")), (2, W(2), D("Epic 1")),
                           (3, W(2), D("Epic 1"))])
    code, out, err = run(f, "--status", "E1=done,E2=run,E3=blocked")
    assert code == 0, err
    assert "E1 Title 1 [done]" in out
    assert "E2 Title 2 [run] ← E1" in out
    assert "E3 Title 3 [blocked] ← E1" in out


def test_status_unlisted_is_todo(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None")), (2, W(2), D("Epic 1"))])
    _, out, _ = run(f, "--status", "E1=done")
    assert "E2 Title 2 [todo] ← E1" in out


def test_status_unknown_epic_is_error(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None"))])
    code, _, err = run(f, "--status", "E9=done")
    assert code != 0 and "E9" in err


def test_status_bad_state_is_error(tmp_path):
    f = plan_of(tmp_path, [(1, W(1), D("None"))])
    code, _, err = run(f, "--status", "E1=finished")
    assert code != 0 and "finished" in err


def test_web_review_html_pins_and_sanitizes():
    spec = importlib.util.spec_from_file_location("xwr", LIB / "xplan-web-review.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    html = m.INDEX_HTML
    tags = re.findall(r"<script[^>]*src=[^>]*>", html)
    assert len(tags) == 2
    want = {
        "https://cdnjs.cloudflare.com/ajax/libs/marked/18.0.13/lib/marked.umd.min.js":
            "sha384-EDNybkEeN9yYwIqheQpxHmn7Xdh180RKiMROtjDRy+SVH8Sl0EqpmIPOolCUbdyE",
        "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.4.15/purify.min.js":
            "sha384-uUMu9JDY09vBzRf9SPcK2VgUj+W/70J6Soc+Dded5P474ElQ63iv9j5N3DE7Kp3N",
    }
    for url, integrity in want.items():
        tag = next(t for t in tags if url in t)
        assert f'integrity="{integrity}"' in tag
        assert 'crossorigin="anonymous"' in tag
    assert "DOMPurify.sanitize(marked.parse(" in html
    assert "jsdelivr" not in html
