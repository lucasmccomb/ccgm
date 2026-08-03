#!/usr/bin/env python3
"""Unit tests for rules_scope.py -- /rules-scope generator (Epic 0.5, issue #952).

Covers the deliverables named in plan.md's Epic 0.5 test list:

  - propose_excludes() never returns a PINNED_FLOOR rule, asserted against
    the full installed set (including an adversarial manifest that tries
    to mislabel a PINNED_FLOOR module as "tech-specific")
  - A repo with Cargo.toml and no package.json gets the web/tech-specific
    set proposed; a repo with tailwind.config.ts does not (for tailwind)
  - write_settings() preserves pre-existing unrelated keys and is
    idempotent (running twice yields a byte-identical file)
  - detect_repo_profile() per-signal marker + dependency detection
  - the niche category never proposes self-improving's high-stakes
    learnings-store.md
  - path resolution: claudeMdExcludes entries must be the REAL,
    symlink-resolved path, not the ~/.claude/rules/ symlink path (the
    load-bearing empirical finding this generator depends on)

Pure library; no I/O beyond temp directories this suite builds itself.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import rules_scope  # noqa: E402


def _write_module(modules_dir, name, *, category=None, rule_files=None, applicability=None):
    """Create modules/<name>/module.json with optional category + rule files."""
    mod_dir = os.path.join(modules_dir, name)
    os.makedirs(mod_dir, exist_ok=True)
    files = {}
    for rf in rule_files or []:
        files[rf] = {"target": rf, "type": "rule", "template": False}
    manifest = {"name": name, "files": files}
    if category is not None:
        manifest["category"] = category
    if applicability is not None:
        manifest["applicability"] = applicability
    with open(os.path.join(mod_dir, "module.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)


class PinnedFloorTests(unittest.TestCase):
    def test_pinned_floor_is_the_seven_safety_core_plus_four_named(self):
        expected = {
            "git-workflow", "hooks", "autonomy", "test-driven-development",
            "verification", "systematic-debugging", "subagent-patterns",
            "identity", "live-testing-guard", "git-worktrees",
            "model-vetting", "branch-guard",
        }
        self.assertEqual(set(rules_scope.PINNED_FLOOR), expected)

    def test_propose_excludes_never_returns_a_pinned_floor_module(self):
        """Adversarial: every PINNED_FLOOR module is ALSO mislabeled
        category="tech-specific" here, so this is a real assertion on the
        exclusion guard -- not just "the fixture never tried."
        """
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as repo:
            all_modules = list(rules_scope.PINNED_FLOOR) + list(rules_scope.NICHE_MODULE_RULE_TARGETS)
            for mod in rules_scope.PINNED_FLOOR:
                _write_module(
                    modules_dir, mod,
                    category="tech-specific",
                    rule_files=[f"rules/{mod}.md"],
                )
            for mod in rules_scope.NICHE_MODULE_RULE_TARGETS:
                _write_module(modules_dir, mod, category="workflow", rule_files=[f"rules/{mod}.md"])

            profile = {}  # nothing detected -> everything tech-specific would be proposed
            proposed = rules_scope.propose_excludes(
                profile, modules_dir, all_modules, home=repo
            )
            proposed_modules = {row["module"] for row in proposed}
            for mod in rules_scope.PINNED_FLOOR:
                self.assertNotIn(mod, proposed_modules, f"{mod} is PINNED_FLOOR but was proposed")

    def test_only_installed_modules_are_considered(self):
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as repo:
            _write_module(modules_dir, "tailwind", category="tech-specific", rule_files=["rules/tailwind.md"])
            proposed = rules_scope.propose_excludes({}, modules_dir, installed_modules=[], home=repo)
            self.assertEqual(proposed, [])


class TechSpecificDetectionTests(unittest.TestCase):
    """A repo with Cargo.toml and no package.json gets the tech-specific set
    proposed; a repo with tailwind.config.ts does not (for tailwind)."""

    def _modules_dir_with_all_tech_specific(self):
        modules_dir = tempfile.mkdtemp()
        _write_module(modules_dir, "tailwind", category="tech-specific",
                      rule_files=["rules/tailwind.md", "rules/frontend-css.md"])
        _write_module(modules_dir, "shadcn", category="tech-specific", rule_files=["rules/shadcn.md"])
        _write_module(modules_dir, "supabase", category="tech-specific", rule_files=["rules/supabase.md"])
        _write_module(modules_dir, "cloudflare", category="tech-specific", rule_files=["rules/cloudflare.md"])
        _write_module(modules_dir, "mcp-development", category="tech-specific",
                      rule_files=["rules/mcp-development.md"])
        return modules_dir

    def test_rust_only_repo_gets_the_full_tech_specific_set_proposed(self):
        modules_dir = self._modules_dir_with_all_tech_specific()
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            with open(os.path.join(repo, "Cargo.toml"), "w", encoding="utf-8") as fh:
                fh.write("[package]\nname = \"x\"\n")
            self.assertFalse(os.path.exists(os.path.join(repo, "package.json")))

            profile = rules_scope.detect_repo_profile(repo)
            self.assertFalse(any(profile.values()), profile)

            proposed = rules_scope.propose_excludes(
                profile, modules_dir,
                installed_modules=["tailwind", "shadcn", "supabase", "cloudflare", "mcp-development"],
                home=home,
            )
            proposed_rules = {(row["module"], row["rule"]) for row in proposed}
            self.assertEqual(
                proposed_rules,
                {
                    ("tailwind", "rules/tailwind.md"),
                    ("tailwind", "rules/frontend-css.md"),
                    ("shadcn", "rules/shadcn.md"),
                    ("supabase", "rules/supabase.md"),
                    ("cloudflare", "rules/cloudflare.md"),
                    ("mcp-development", "rules/mcp-development.md"),
                },
            )
            self.assertTrue(all(row["category"] == "tech-specific" for row in proposed))

    def test_tailwind_config_present_excludes_tailwind_from_the_proposal(self):
        modules_dir = self._modules_dir_with_all_tech_specific()
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            with open(os.path.join(repo, "tailwind.config.ts"), "w", encoding="utf-8") as fh:
                fh.write("export default {}\n")

            profile = rules_scope.detect_repo_profile(repo)
            self.assertTrue(profile["tailwind"])

            proposed = rules_scope.propose_excludes(
                profile, modules_dir,
                installed_modules=["tailwind", "shadcn", "supabase", "cloudflare", "mcp-development"],
                home=home,
            )
            proposed_modules = {row["module"] for row in proposed}
            self.assertNotIn("tailwind", proposed_modules)
            # The other four tech-specific modules are still undetected in
            # this repo and should still be proposed.
            self.assertIn("shadcn", proposed_modules)
            self.assertIn("supabase", proposed_modules)
            self.assertIn("cloudflare", proposed_modules)
            self.assertIn("mcp-development", proposed_modules)


class DetectRepoProfileTests(unittest.TestCase):
    def test_empty_repo_detects_nothing(self):
        with tempfile.TemporaryDirectory() as repo:
            profile = rules_scope.detect_repo_profile(repo)
            self.assertEqual(profile, {
                "tailwind": False, "shadcn": False, "supabase": False,
                "cloudflare": False, "mcp-development": False,
            })

    def test_components_json_detects_shadcn(self):
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, "components.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            self.assertTrue(rules_scope.detect_repo_profile(repo)["shadcn"])

    def test_supabase_directory_detects_supabase(self):
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, "supabase"))
            self.assertTrue(rules_scope.detect_repo_profile(repo)["supabase"])

    def test_wrangler_toml_detects_cloudflare(self):
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, "wrangler.toml"), "w", encoding="utf-8") as fh:
                fh.write("name = \"x\"\n")
            self.assertTrue(rules_scope.detect_repo_profile(repo)["cloudflare"])

    def test_mcp_json_detects_mcp_development(self):
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, ".mcp.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
            self.assertTrue(rules_scope.detect_repo_profile(repo)["mcp-development"])

    def test_package_json_dependency_detects_tailwind(self):
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, "package.json"), "w", encoding="utf-8") as fh:
                json.dump({"devDependencies": {"tailwindcss": "^4.0.0"}}, fh)
            self.assertTrue(rules_scope.detect_repo_profile(repo)["tailwind"])

    def test_dependency_inside_node_modules_is_ignored(self):
        """A tailwindcss package.json nested under node_modules must not
        count as a repo-level signal -- node_modules is a pruned directory."""
        with tempfile.TemporaryDirectory() as repo:
            nested = os.path.join(repo, "node_modules", "some-lib")
            os.makedirs(nested)
            with open(os.path.join(nested, "package.json"), "w", encoding="utf-8") as fh:
                json.dump({"dependencies": {"tailwindcss": "^4.0.0"}}, fh)
            self.assertFalse(rules_scope.detect_repo_profile(repo)["tailwind"])

    def test_nested_package_json_within_walk_depth_is_detected(self):
        """Monorepo-shaped: package.json a few levels deep, not at root."""
        with tempfile.TemporaryDirectory() as repo:
            nested = os.path.join(repo, "apps", "web")
            os.makedirs(nested)
            with open(os.path.join(nested, "package.json"), "w", encoding="utf-8") as fh:
                json.dump({"dependencies": {"tailwindcss": "^4.0.0"}}, fh)
            self.assertTrue(rules_scope.detect_repo_profile(repo)["tailwind"])


class NicheCategoryTests(unittest.TestCase):
    def test_self_improving_only_proposes_self_improving_md_not_learnings_store(self):
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as home:
            _write_module(
                modules_dir, "self-improving", category="workflow",
                rule_files=["rules/self-improving.md", "rules/learnings-store.md"],
            )
            proposed = rules_scope.propose_excludes(
                {}, modules_dir, installed_modules=["self-improving"], home=home
            )
            proposed_rules = {row["rule"] for row in proposed}
            self.assertIn("rules/self-improving.md", proposed_rules)
            self.assertNotIn("rules/learnings-store.md", proposed_rules)

    def test_niche_module_not_installed_is_never_proposed(self):
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as home:
            _write_module(modules_dir, "dreaming", category="workflow", rule_files=["rules/dreaming.md"])
            proposed = rules_scope.propose_excludes({}, modules_dir, installed_modules=[], home=home)
            self.assertEqual(proposed, [])

    def test_niche_category_is_not_gated_on_repo_profile(self):
        """Unlike tech-specific, niche modules are proposed regardless of
        what detect_repo_profile() found -- there is no per-repo signal for
        "will this session touch the nightly dreaming pipeline."""
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as home:
            _write_module(modules_dir, "dreaming", category="workflow", rule_files=["rules/dreaming.md"])
            full_profile = {"tailwind": True, "shadcn": True, "supabase": True,
                             "cloudflare": True, "mcp-development": True}
            proposed = rules_scope.propose_excludes(
                full_profile, modules_dir, installed_modules=["dreaming"], home=home
            )
            self.assertEqual({row["rule"] for row in proposed}, {"rules/dreaming.md"})


class PathResolutionTests(unittest.TestCase):
    """Regression test for the empirical finding that claudeMdExcludes must
    reference the REAL (symlink-resolved) path, not the ~/.claude/rules/
    symlink path CCGM's installer creates under linkMode."""

    def test_resolved_rule_path_follows_a_symlink(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as canonical:
            real_file = os.path.join(canonical, "tailwind.md")
            with open(real_file, "w", encoding="utf-8") as fh:
                fh.write("# tailwind rule\n")

            rules_dir = os.path.join(home, ".claude", "rules")
            os.makedirs(rules_dir)
            symlink_path = os.path.join(rules_dir, "tailwind.md")
            os.symlink(real_file, symlink_path)

            resolved = rules_scope._resolved_rule_path("rules/tailwind.md", home)
            self.assertEqual(resolved, os.path.realpath(real_file))
            self.assertNotEqual(resolved, symlink_path)

    def test_resolved_rule_path_is_stable_for_a_plain_copy_install(self):
        """Under a --copy install there is no symlink; realpath() of a
        plain file is the file itself, so the same code path is correct."""
        with tempfile.TemporaryDirectory() as home:
            rules_dir = os.path.join(home, ".claude", "rules")
            os.makedirs(rules_dir)
            plain_path = os.path.join(rules_dir, "tailwind.md")
            with open(plain_path, "w", encoding="utf-8") as fh:
                fh.write("# tailwind rule\n")

            resolved = rules_scope._resolved_rule_path("rules/tailwind.md", home)
            self.assertEqual(resolved, os.path.realpath(plain_path))

    def test_propose_excludes_returns_resolved_paths(self):
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as canonical:
            _write_module(modules_dir, "tailwind", category="tech-specific", rule_files=["rules/tailwind.md"])

            real_file = os.path.join(canonical, "tailwind.md")
            with open(real_file, "w", encoding="utf-8") as fh:
                fh.write("# tailwind\n")
            rules_dir = os.path.join(home, ".claude", "rules")
            os.makedirs(rules_dir)
            os.symlink(real_file, os.path.join(rules_dir, "tailwind.md"))

            proposed = rules_scope.propose_excludes(
                {}, modules_dir, installed_modules=["tailwind"], home=home
            )
            self.assertEqual(len(proposed), 1)
            self.assertEqual(proposed[0]["path"], os.path.realpath(real_file))


class WriteSettingsTests(unittest.TestCase):
    def test_creates_file_and_parent_dir_when_missing(self):
        with tempfile.TemporaryDirectory() as repo:
            settings_path = os.path.join(repo, ".claude", "settings.json")
            self.assertFalse(os.path.exists(settings_path))
            result = rules_scope.write_settings(settings_path, ["/a.md", "/b.md"])
            self.assertTrue(os.path.exists(settings_path))
            self.assertEqual(result["claudeMdExcludes"], ["/a.md", "/b.md"])

    def test_preserves_pre_existing_unrelated_keys(self):
        with tempfile.TemporaryDirectory() as repo:
            settings_path = os.path.join(repo, ".claude", "settings.json")
            os.makedirs(os.path.dirname(settings_path))
            with open(settings_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
                        "someOtherSetting": True,
                        "permissions": {"allow": ["Bash(git status)"]},
                    },
                    fh,
                )
            result = rules_scope.write_settings(settings_path, ["/new.md"])
            self.assertEqual(
                result["hooks"],
                {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
            )
            self.assertEqual(result["someOtherSetting"], True)
            self.assertEqual(result["permissions"], {"allow": ["Bash(git status)"]})
            self.assertIn("/new.md", result["claudeMdExcludes"])

    def test_extends_existing_claude_md_excludes_rather_than_overwriting(self):
        with tempfile.TemporaryDirectory() as repo:
            settings_path = os.path.join(repo, ".claude", "settings.json")
            os.makedirs(os.path.dirname(settings_path))
            with open(settings_path, "w", encoding="utf-8") as fh:
                json.dump({"claudeMdExcludes": ["/already/excluded.md"]}, fh)
            result = rules_scope.write_settings(settings_path, ["/new.md"])
            self.assertEqual(
                sorted(result["claudeMdExcludes"]),
                ["/already/excluded.md", "/new.md"],
            )

    def test_is_idempotent_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as repo:
            settings_path = os.path.join(repo, ".claude", "settings.json")
            rules_scope.write_settings(settings_path, ["/a.md", "/b.md"])
            with open(settings_path, "rb") as fh:
                first = fh.read()
            rules_scope.write_settings(settings_path, ["/a.md", "/b.md"])
            with open(settings_path, "rb") as fh:
                second = fh.read()
            self.assertEqual(first, second)

    def test_deduplicates_excludes(self):
        with tempfile.TemporaryDirectory() as repo:
            settings_path = os.path.join(repo, ".claude", "settings.json")
            os.makedirs(os.path.dirname(settings_path))
            with open(settings_path, "w", encoding="utf-8") as fh:
                json.dump({"claudeMdExcludes": ["/a.md"]}, fh)
            result = rules_scope.write_settings(settings_path, ["/a.md", "/b.md"])
            self.assertEqual(sorted(result["claudeMdExcludes"]), ["/a.md", "/b.md"])

    def test_malformed_existing_json_raises_rather_than_clobbering(self):
        with tempfile.TemporaryDirectory() as repo:
            settings_path = os.path.join(repo, ".claude", "settings.json")
            os.makedirs(os.path.dirname(settings_path))
            with open(settings_path, "w", encoding="utf-8") as fh:
                fh.write("{not valid json")
            with self.assertRaises(ValueError):
                rules_scope.write_settings(settings_path, ["/a.md"])
            # The malformed file must survive untouched.
            with open(settings_path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "{not valid json")


class CliDryRunTests(unittest.TestCase):
    """The default CLI invocation must never write anything (Epic 0.5's own
    safety-rules contract: "Always print the proposed list and require
    --write")."""

    def test_main_without_write_flag_does_not_touch_settings_json(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as ccgm_root:
            modules_dir = os.path.join(ccgm_root, "modules")
            os.makedirs(modules_dir)
            _write_module(modules_dir, "tailwind", category="tech-specific", rule_files=["rules/tailwind.md"])

            manifest_path = os.path.join(ccgm_root, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump({"ccgmRoot": ccgm_root, "modules": ["tailwind"]}, fh)

            rc = rules_scope.main([repo, "--manifest", manifest_path])
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(os.path.join(repo, ".claude", "settings.json")))

    def test_main_with_write_flag_writes_settings_json(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as ccgm_root:
            modules_dir = os.path.join(ccgm_root, "modules")
            os.makedirs(modules_dir)
            _write_module(modules_dir, "tailwind", category="tech-specific", rule_files=["rules/tailwind.md"])

            manifest_path = os.path.join(ccgm_root, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump({"ccgmRoot": ccgm_root, "modules": ["tailwind"]}, fh)

            rc = rules_scope.main([repo, "--manifest", manifest_path, "--write"])
            self.assertEqual(rc, 0)
            settings_path = os.path.join(repo, ".claude", "settings.json")
            self.assertTrue(os.path.exists(settings_path))
            with open(settings_path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(len(data["claudeMdExcludes"]), 1)

    def test_main_with_missing_manifest_reports_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as repo:
            rc = rules_scope.main([repo, "--manifest", "/does/not/exist.json"])
            self.assertEqual(rc, 1)
            self.assertFalse(os.path.exists(os.path.join(repo, ".claude", "settings.json")))


if __name__ == "__main__":
    unittest.main()
