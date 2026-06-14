#!/usr/bin/env python3
"""Unit tests for the relevance_select selection library (issue #695).

Pins the four required correctness properties:

  (a) default / no profile == every applicable module selected (no behavior change)
  (b) with a profile, only applicable situational rules are selected
  (c) the safety core is ALWAYS included regardless of profile
  (d) absent `applicability` == treated as always

Plus determinism and helper-level checks. Pure library; no I/O beyond reading
a temp modules/ tree we build per test.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import relevance_select as rs  # noqa: E402


def _write_module(modules_dir, name, *, applicability=None, rule_files=None):
    """Create modules/<name>/module.json with optional applicability + rules."""
    mod_dir = os.path.join(modules_dir, name)
    os.makedirs(mod_dir, exist_ok=True)
    files = {}
    for rf in rule_files or []:
        files[rf] = {"target": rf, "type": "rule", "template": False}
    manifest = {"name": name, "files": files}
    if applicability is not None:
        manifest["applicability"] = applicability
    with open(os.path.join(mod_dir, "module.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)


class SafetyCoreTests(unittest.TestCase):
    def test_core_membership_and_tiers(self):
        self.assertTrue(rs.is_safety_core("git-workflow"))
        self.assertTrue(rs.is_safety_core("autonomy"))
        self.assertTrue(rs.is_safety_core("verification"))
        self.assertFalse(rs.is_safety_core("tailwind"))
        # git-workflow (tier 0) outranks verification (tier 2).
        self.assertLess(rs.safety_core_tier("git-workflow"), rs.safety_core_tier("verification"))

    def test_safety_core_modules_is_precedence_ordered(self):
        core = rs.safety_core_modules()
        self.assertEqual(core[0:2], ["git-workflow", "hooks"])
        self.assertIn("autonomy", core)
        self.assertIn("test-driven-development", core)


class ApplicabilityTests(unittest.TestCase):
    def test_absent_applicability_is_always(self):  # property (d)
        self.assertTrue(rs.module_is_applicable(None, langs=["python"]))
        self.assertTrue(rs.module_is_applicable(None))
        self.assertTrue(rs.module_is_applicable({}))

    def test_explicit_always(self):
        self.assertTrue(rs.module_is_applicable({"always": True}, langs=["go"]))

    def test_lang_match_and_miss(self):
        ap = {"langs": ["python", "typescript"]}
        self.assertTrue(rs.module_is_applicable(ap, langs=["python"]))
        self.assertTrue(rs.module_is_applicable(ap, langs=["PYTHON"]))  # case-insensitive
        self.assertFalse(rs.module_is_applicable(ap, langs=["ruby"]))
        self.assertFalse(rs.module_is_applicable(ap, langs=[]))

    def test_tasktype_match_and_miss(self):
        ap = {"taskTypes": ["frontend"]}
        self.assertTrue(rs.module_is_applicable(ap, task_types=["frontend"]))
        self.assertFalse(rs.module_is_applicable(ap, task_types=["backend"]))

    def test_or_across_dimensions(self):
        ap = {"langs": ["python"], "taskTypes": ["frontend"]}
        # lang matches, task does not -> still applicable
        self.assertTrue(rs.module_is_applicable(ap, langs=["python"], task_types=["backend"]))
        # task matches, lang does not -> still applicable
        self.assertTrue(rs.module_is_applicable(ap, langs=["ruby"], task_types=["frontend"]))
        # neither matches -> excluded
        self.assertFalse(rs.module_is_applicable(ap, langs=["ruby"], task_types=["backend"]))

    def test_malformed_constraints_fail_safe_to_always(self):
        # declares the key but with empty dimensions -> include rather than drop
        self.assertTrue(rs.module_is_applicable({"langs": []}))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.modules_dir = self._tmp.name
        # Safety-core modules present.
        _write_module(self.modules_dir, "git-workflow", rule_files=["rules/git-workflow.md"])
        _write_module(self.modules_dir, "verification", rule_files=["rules/verification.md"])
        _write_module(self.modules_dir, "test-driven-development",
                      rule_files=["rules/test-driven-development.md"])
        # Situational modules.
        _write_module(self.modules_dir, "tailwind",
                      applicability={"langs": ["css", "typescript"], "taskTypes": ["frontend"]},
                      rule_files=["rules/tailwind.md"])
        _write_module(self.modules_dir, "supabase",
                      applicability={"langs": ["sql"], "taskTypes": ["database"]},
                      rule_files=["rules/supabase.md"])
        # Unclassified situational module (no applicability) -> always.
        _write_module(self.modules_dir, "code-quality",
                      rule_files=["rules/code-quality.md"])

    def tearDown(self):
        self._tmp.cleanup()

    @property
    def installed(self):
        return ["git-workflow", "verification", "test-driven-development",
                "tailwind", "supabase", "code-quality"]

    def test_no_profile_selects_all_applicable(self):  # property (a)
        sel = rs.select_modules(self.installed, self.modules_dir)
        # With no profile: core + all unclassified-always + no scoped (scoped miss empty profile)
        self.assertIn("code-quality", sel)        # unclassified -> always
        self.assertIn("git-workflow", sel)        # core
        # Scoped modules with empty profile do NOT match -> excluded.
        self.assertNotIn("tailwind", sel)
        self.assertNotIn("supabase", sel)

    def test_profile_selects_only_applicable(self):  # property (b)
        sel = rs.select_modules(self.installed, self.modules_dir,
                                langs=["css"], task_types=["frontend"])
        self.assertIn("tailwind", sel)            # css/frontend match
        self.assertNotIn("supabase", sel)         # sql/database miss

    def test_safety_core_always_present(self):  # property (c)
        # An adversarial profile that matches nothing situational.
        sel = rs.select_modules(self.installed, self.modules_dir,
                                langs=["brainfuck"], task_types=["nonsense"])
        for core in ("git-workflow", "verification", "test-driven-development"):
            self.assertIn(core, sel)
        # Situational scoped modules excluded.
        self.assertNotIn("tailwind", sel)
        self.assertNotIn("supabase", sel)

    def test_core_module_with_constraint_still_always(self):
        # If a core module somehow declared a constraint, core membership wins.
        _write_module(self.modules_dir, "git-workflow",
                      applicability={"langs": ["nonexistent"]},
                      rule_files=["rules/git-workflow.md"])
        sel = rs.select_modules(self.installed, self.modules_dir, langs=["ruby"])
        self.assertIn("git-workflow", sel)

    def test_output_is_deterministic(self):  # property: determinism
        a = rs.select_modules(self.installed, self.modules_dir, langs=["css"])
        b = rs.select_modules(list(reversed(self.installed)), self.modules_dir, langs=["css"])
        self.assertEqual(a, b)

    def test_core_sorts_ahead_of_situational(self):
        sel = rs.select_modules(self.installed, self.modules_dir)
        core_positions = [sel.index(m) for m in ("git-workflow", "verification") if m in sel]
        situational_positions = [sel.index("code-quality")]
        self.assertTrue(max(core_positions) < min(situational_positions))

    def test_select_rule_files_returns_targets(self):
        pairs = rs.select_rule_files(self.installed, self.modules_dir,
                                     langs=["css"], task_types=["frontend"])
        mods = {m for m, _ in pairs}
        self.assertIn("tailwind", mods)
        self.assertIn(("tailwind", "rules/tailwind.md"), pairs)
        # deterministic ordering
        self.assertEqual(pairs, rs.select_rule_files(self.installed, self.modules_dir,
                                                     langs=["css"], task_types=["frontend"]))

    def test_missing_manifest_treated_as_always(self):
        sel = rs.select_modules(self.installed + ["ghost-module"], self.modules_dir)
        # ghost-module has no manifest -> applicability None -> always-applicable
        self.assertIn("ghost-module", sel)


class RealRepoApplicabilityTests(unittest.TestCase):
    """Validate that the real repo's module.json applicability fields parse and
    that the safety-core modules exist in the repo."""

    def setUp(self):
        self.repo_modules = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )

    def test_safety_core_modules_exist_in_repo(self):
        for mod in rs.safety_core_modules():
            self.assertTrue(
                os.path.isdir(os.path.join(self.repo_modules, mod)),
                f"safety-core module {mod} missing from repo",
            )

    def test_all_applicability_fields_are_valid(self):
        for name in os.listdir(self.repo_modules):
            manifest = rs.read_module_manifest(self.repo_modules, name)
            if not manifest:
                continue
            ap = manifest.get("applicability")
            if ap is None:
                continue
            self.assertIsInstance(ap, dict, f"{name}: applicability must be an object")
            allowed = {"always", "langs", "taskTypes"}
            self.assertTrue(
                set(ap.keys()) <= allowed,
                f"{name}: applicability has unknown keys {set(ap.keys()) - allowed}",
            )


if __name__ == "__main__":
    unittest.main()
