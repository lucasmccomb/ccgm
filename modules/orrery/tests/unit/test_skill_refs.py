"""Drift gate for SKILL.md and packs.md (plan Epic 4).

Extracts every module path (scripts/, references/, agents/) named in SKILL.md and
references/packs.md and asserts each exists in the module, so the orchestration doc
can never name a script that is not shipped.

Two deliberate carve-outs:
- The labeled "Update flow" stub section of SKILL.md is skipped ONLY while Epic 5's
  scripts/diff_since.py does not exist yet. The moment Epic 5 ships the script, the
  extractor covers the whole file automatically.
- Also asserts BOTH .github/workflows/test.yml orrery steps still set ORRERY_STRICT=1
  (plan section 4): the flag is the only thing making the suite required rather than
  skippable, so it needs a drift gate of its own.
"""

import re
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = MODULE_DIR.parents[1]
SKILL_MD = MODULE_DIR / "skills" / "orrery" / "SKILL.md"
PACKS_MD = MODULE_DIR / "skills" / "orrery" / "references" / "packs.md"
DIFF_SINCE = MODULE_DIR / "skills" / "orrery" / "scripts" / "diff_since.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"

# Module-relative path tokens: scripts/x.sh, scripts/toolchain/package.json,
# references/x.json, agents/x.md - with optional intermediate segments.
PATH_RE = re.compile(
    r"\b(?:agents|scripts|references)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+"
    r"\.(?:sh|py|json|md)\b"
)


def _skill_text_for_extraction():
    """SKILL.md text, minus the labeled update-flow stub while Epic 5 is pending."""
    text = SKILL_MD.read_text(encoding="utf-8")
    if DIFF_SINCE.exists():
        return text
    lines = []
    skipping = False
    for line in text.splitlines():
        if line.startswith("## "):
            skipping = "update flow" in line.lower()
        if not skipping:
            lines.append(line)
    return "\n".join(lines)


def _resolve(ref):
    """A scripts/ or references/ ref is relative to the skill dir; agents/ to the module."""
    if ref.startswith("agents/"):
        return MODULE_DIR / ref
    return MODULE_DIR / "skills" / "orrery" / ref


def _extract_refs():
    text = _skill_text_for_extraction() + "\n" + PACKS_MD.read_text(encoding="utf-8")
    return sorted(set(PATH_RE.findall(text)))


def test_docs_exist():
    assert SKILL_MD.is_file(), "SKILL.md missing"
    assert PACKS_MD.is_file(), "references/packs.md missing"


def test_every_named_path_exists():
    refs = _extract_refs()
    assert refs, "extractor found no path references - it has gone vacuous"
    missing = [r for r in refs if not _resolve(r).is_file()]
    assert not missing, (
        "paths named in SKILL.md/packs.md that do not exist in the module: %s"
        % ", ".join(missing)
    )


def test_core_references_are_actually_named():
    """Anti-vacuity: the flow's load-bearing paths must all be referenced by name."""
    refs = set(_extract_refs())
    expected = {
        "scripts/anchor_repo.sh",
        "scripts/enumerate_repo.py",
        "scripts/merge_fragments.py",
        "scripts/emit_likec4.py",
        "scripts/validate_map.py",
        "scripts/render_map.sh",
        "scripts/likec4.sh",
        "scripts/toolchain/package.json",
        "references/fragment.schema.json",
        "references/packs.md",
        "agents/orrery-scout.md",
    }
    missing = sorted(expected - refs)
    assert not missing, "expected references not named in SKILL.md/packs.md: %s" % (
        ", ".join(missing)
    )


def test_diff_since_stays_inside_the_update_stub_until_epic5():
    """diff_since.py is Epic 5's. Until it exists, SKILL.md may name it only inside
    the labeled update-flow stub (which the extractor skips), and the stub heading
    must still be present so the skip actually applies."""
    if DIFF_SINCE.exists():
        return  # Epic 5 landed; the plain existence gate above covers it now
    text = SKILL_MD.read_text(encoding="utf-8")
    stub_headings = [
        ln for ln in text.splitlines()
        if ln.startswith("## ") and "update flow" in ln.lower()
    ]
    assert stub_headings, "SKILL.md lost its labeled update-flow stub heading"
    assert "diff_since" not in _skill_text_for_extraction(), (
        "diff_since.py is referenced outside the labeled update-flow stub, "
        "but Epic 5 has not shipped it yet"
    )
    assert "diff_since" not in PACKS_MD.read_text(encoding="utf-8"), (
        "packs.md references diff_since.py, which Epic 5 has not shipped yet"
    )


def test_both_ci_jobs_still_set_orrery_strict():
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            current = m.group(1)
            jobs[current] = []
        elif current is not None:
            jobs[current].append(line)
    for job in ("test", "test-macos"):
        assert job in jobs, "test.yml job missing: %s" % job
        body = "\n".join(jobs[job])
        assert "ORRERY_STRICT=1 bash modules/orrery/tests/test-orrery.sh" in body, (
            "the %s job no longer runs the orrery suite with ORRERY_STRICT=1 - "
            "without the flag every skippable layer silently passes (plan section 4)"
            % job
        )
