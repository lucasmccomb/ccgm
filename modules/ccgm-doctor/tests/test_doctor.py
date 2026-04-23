"""
Tests for modules/ccgm-doctor/lib/doctor.py.

Every check function is pure: it takes paths and returns a list of findings.
Tests build up a fake Claude install in a tempdir and assert on the findings.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

import doctor  # noqa: E402


class TestExpandPath(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path("/tmp/fake-home")

    def test_expand_dollar_home(self) -> None:
        result = doctor.expand_path("$HOME/.claude/hooks/x.py", self.home)
        self.assertEqual(result, Path("/tmp/fake-home/.claude/hooks/x.py"))

    def test_expand_brace_home(self) -> None:
        result = doctor.expand_path("${HOME}/.claude/x.py", self.home)
        self.assertEqual(result, Path("/tmp/fake-home/.claude/x.py"))

    def test_expand_tilde(self) -> None:
        result = doctor.expand_path("~/.claude/x.py", self.home)
        self.assertEqual(result, Path("/tmp/fake-home/.claude/x.py"))

    def test_absolute_path_unchanged(self) -> None:
        result = doctor.expand_path("/absolute/path", self.home)
        self.assertEqual(result, Path("/absolute/path"))

    def test_relative_joined_to_home(self) -> None:
        result = doctor.expand_path("relative/path", self.home)
        self.assertEqual(result, Path("/tmp/fake-home/relative/path"))


class TestCheckHookRefs(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-doctor-"))
        self.home = self.tmp / "claude"
        self.home.mkdir()
        self.hooks_dir = self.home / "hooks"
        self.hooks_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_settings(self, data: dict) -> Path:
        p = self.home / "settings.json"
        p.write_text(json.dumps(data))
        return p

    def test_no_settings_file_no_findings(self) -> None:
        findings = doctor.check_hook_refs(self.home / "settings.json", self.home)
        self.assertEqual(findings, [])

    def test_invalid_json_flagged(self) -> None:
        p = self.home / "settings.json"
        p.write_text("{not valid json")
        findings = doctor.check_hook_refs(p, self.home)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "hook-refs")
        self.assertEqual(findings[0]["severity"], "error")

    def test_existing_hook_not_flagged(self) -> None:
        (self.hooks_dir / "real.py").write_text("# real hook")
        self._write_settings({
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [
                        {"type": "command", "command": "python3 $HOME/hooks/real.py"}
                    ]}
                ]
            }
        })
        findings = doctor.check_hook_refs(self.home / "settings.json", self.home)
        self.assertEqual(findings, [])

    def test_missing_hook_flagged(self) -> None:
        self._write_settings({
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [
                        {"type": "command", "command": "python3 $HOME/hooks/missing.py"}
                    ]}
                ]
            }
        })
        findings = doctor.check_hook_refs(self.home / "settings.json", self.home)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "hook-refs")
        self.assertEqual(findings[0]["severity"], "error")
        self.assertIn("missing.py", findings[0]["path"])

    def test_tilde_expansion(self) -> None:
        self._write_settings({
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [
                        {"type": "command", "command": "~/hooks/tilde.py"}
                    ]}
                ]
            }
        })
        findings = doctor.check_hook_refs(self.home / "settings.json", self.home)
        self.assertEqual(len(findings), 1)
        self.assertIn("tilde.py", findings[0]["path"])

    def test_multiple_hooks_across_events(self) -> None:
        (self.hooks_dir / "ok.py").write_text("")
        self._write_settings({
            "hooks": {
                "PreToolUse": [
                    {"hooks": [
                        {"type": "command", "command": "$HOME/hooks/ok.py"},
                        {"type": "command", "command": "$HOME/hooks/missing1.py"},
                    ]}
                ],
                "PostToolUse": [
                    {"hooks": [
                        {"type": "command", "command": "python3 $HOME/hooks/missing2.py"}
                    ]}
                ]
            }
        })
        findings = doctor.check_hook_refs(self.home / "settings.json", self.home)
        self.assertEqual(len(findings), 2)
        flagged = {Path(f["path"]).name for f in findings}
        self.assertEqual(flagged, {"missing1.py", "missing2.py"})

    def test_missing_hooks_section_no_crash(self) -> None:
        self._write_settings({"permissions": {"allow": []}})
        findings = doctor.check_hook_refs(self.home / "settings.json", self.home)
        self.assertEqual(findings, [])


class TestCheckCommandDescriptions(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-doctor-"))
        self.commands = self.tmp / "commands"
        self.commands.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_dir_no_findings(self) -> None:
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(findings, [])

    def test_nonexistent_dir_no_findings(self) -> None:
        findings = doctor.check_command_descriptions(self.tmp / "nope")
        self.assertEqual(findings, [])

    def test_good_heading_no_finding(self) -> None:
        (self.commands / "good.md").write_text("# /good - runs the good workflow\n\nbody\n")
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(findings, [])

    def test_no_heading_flagged(self) -> None:
        (self.commands / "bad.md").write_text("just prose, no heading\n")
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "command-descriptions")
        self.assertEqual(findings[0]["severity"], "warn")

    def test_short_heading_flagged(self) -> None:
        (self.commands / "terse.md").write_text("# /t\n\nbody\n")
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(len(findings), 1)
        self.assertIn("very short", findings[0]["detail"])

    def test_blank_leading_lines_ok(self) -> None:
        (self.commands / "blank-lead.md").write_text("\n\n# /name - the real heading\n")
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(findings, [])

    def test_frontmatter_description_counts_as_trigger(self) -> None:
        # Claude Code commands commonly use YAML frontmatter with `description:`
        # instead of a Markdown heading. That field should satisfy the check.
        (self.commands / "fm.md").write_text(
            "---\n"
            "description: Deep root-cause debugging with Opus 4.6 - reproduce, hypothesize\n"
            "allowed-tools: Bash, Read\n"
            "---\n\n"
            "body content here\n"
        )
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(findings, [])

    def test_frontmatter_missing_description_flagged(self) -> None:
        # Frontmatter exists but has no `description:` field and no heading follows.
        (self.commands / "no-desc.md").write_text(
            "---\n"
            "allowed-tools: Bash\n"
            "---\n\n"
            "body\n"
        )
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(len(findings), 1)

    def test_frontmatter_short_description_flagged(self) -> None:
        (self.commands / "short-desc.md").write_text(
            "---\n"
            "description: hi\n"
            "---\n\n"
            "body\n"
        )
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(len(findings), 1)
        self.assertIn("very short", findings[0]["detail"])

    def test_frontmatter_quoted_description(self) -> None:
        # Description may be quoted in YAML; we should strip quotes before length-checking.
        (self.commands / "quoted.md").write_text(
            '---\n'
            'description: "Deep root-cause debugging with Opus 4.6"\n'
            '---\n\n'
            'body\n'
        )
        findings = doctor.check_command_descriptions(self.commands)
        self.assertEqual(findings, [])


class TestCheckScriptRefs(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-doctor-"))
        self.home = self.tmp / "claude"
        self.home.mkdir()
        self.commands = self.home / "commands"
        self.commands.mkdir()
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self._orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""

    def tearDown(self) -> None:
        os.environ["PATH"] = self._orig_path
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_exec(self, name: str) -> None:
        p = self.bin_dir / name
        p.write_text("#!/bin/sh\n")
        p.chmod(0o755)

    def test_command_with_existing_script_no_finding(self) -> None:
        self._make_exec("ccgm-real-tool")
        (self.commands / "a.md").write_text("# /a - description\n\n```bash\nccgm-real-tool foo\n```\n")
        findings = doctor.check_script_refs(self.commands, self.home)
        self.assertEqual(findings, [])

    def test_command_referencing_missing_script_flagged(self) -> None:
        (self.commands / "b.md").write_text("# /b\n\n```bash\nccgm-phantom\n```\n")
        findings = doctor.check_script_refs(self.commands, self.home)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "script-refs")
        self.assertIn("ccgm-phantom", findings[0]["detail"])

    def test_multiple_refs_dedup(self) -> None:
        # Same script referenced twice inside the bash block should produce
        # one finding, not two.
        (self.commands / "c.md").write_text(
            "# /c\n\n```bash\nccgm-missing one\nccgm-missing two\n```\n"
        )
        findings = doctor.check_script_refs(self.commands, self.home)
        self.assertEqual(len(findings), 1)

    def test_prose_mentions_outside_bash_ignored(self) -> None:
        # A bare ccgm-name in prose is not an invocation and must not flag.
        (self.commands / "prose.md").write_text(
            "# /prose\n\nSee ccgm-not-really-a-command in the docs.\n"
        )
        findings = doctor.check_script_refs(self.commands, self.home)
        self.assertEqual(findings, [])

    def test_path_segments_not_flagged(self) -> None:
        # Directory names like ~/code/ccgm-repos/ccgm-1/ must not flag.
        (self.commands / "paths.md").write_text(
            "# /paths\n\n```bash\nls ~/code/ccgm-repos/ccgm-1/modules/\n```\n"
        )
        findings = doctor.check_script_refs(self.commands, self.home)
        self.assertEqual(findings, [])

    def test_non_executable_flagged(self) -> None:
        # A file exists but is not executable - still counts as missing.
        p = self.bin_dir / "ccgm-not-exec"
        p.write_text("#!/bin/sh\n")
        (self.commands / "d.md").write_text(
            "# /d\n\n```bash\nccgm-not-exec run\n```\n"
        )
        findings = doctor.check_script_refs(self.commands, self.home)
        self.assertEqual(len(findings), 1)


class TestCheckDryOverlap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-doctor-"))
        self.commands = self.tmp / "commands"
        self.commands.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_fm_command(self, name: str, description: str) -> None:
        (self.commands / f"{name}.md").write_text(
            f"---\ndescription: {description}\n---\n\nbody\n"
        )

    def test_distinct_commands_no_findings(self) -> None:
        self._make_fm_command("alpha", "Fetch and summarize upstream news articles")
        self._make_fm_command("beta", "Transform JSON logs into Parquet files")
        findings = doctor.check_dry_overlap(self.commands)
        self.assertEqual(findings, [])

    def test_near_duplicate_commands_flagged(self) -> None:
        # Two descriptions that share most content words - obvious DRY problem.
        self._make_fm_command(
            "calendar-check",
            "Check calendar events for scheduling conflicts tomorrow",
        )
        self._make_fm_command(
            "calendar-recall",
            "Check calendar events for scheduling conflicts historically",
        )
        findings = doctor.check_dry_overlap(self.commands, threshold=0.5)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "dry-overlap")
        self.assertEqual(findings[0]["severity"], "warn")
        self.assertIn("calendar", findings[0]["detail"])

    def test_threshold_respected(self) -> None:
        # Moderate overlap: flagged at low threshold, clean at high.
        self._make_fm_command("one", "Deploy production web service quickly")
        self._make_fm_command("two", "Deploy staging web service quickly")
        findings_low = doctor.check_dry_overlap(self.commands, threshold=0.3)
        self.assertEqual(len(findings_low), 1)
        findings_high = doctor.check_dry_overlap(self.commands, threshold=0.95)
        self.assertEqual(findings_high, [])

    def test_pair_report_uses_basenames(self) -> None:
        self._make_fm_command("left", "Parse emails for unread thread summaries")
        self._make_fm_command("right", "Parse emails for unread thread summaries")
        findings = doctor.check_dry_overlap(self.commands, threshold=0.5)
        self.assertEqual(len(findings), 1)
        self.assertIn("left.md", findings[0]["path"])
        self.assertIn("right.md", findings[0]["path"])

    def test_empty_descriptions_skipped(self) -> None:
        # Commands with no trigger description are skipped; they're already
        # flagged by check_command_descriptions and would produce an empty
        # set intersection.
        (self.commands / "empty.md").write_text("")
        self._make_fm_command("real", "A real command with actual content")
        findings = doctor.check_dry_overlap(self.commands)
        self.assertEqual(findings, [])

    def test_heading_style_commands_also_audited(self) -> None:
        # CCGM-style commands use H1 headings, not frontmatter. Still audited.
        (self.commands / "alpha.md").write_text("# /alpha - parse emails and build thread summaries\n")
        (self.commands / "beta.md").write_text("# /beta - parse emails and build thread summaries\n")
        findings = doctor.check_dry_overlap(self.commands, threshold=0.5)
        self.assertEqual(len(findings), 1)

    def test_no_commands_dir(self) -> None:
        findings = doctor.check_dry_overlap(self.tmp / "nonexistent")
        self.assertEqual(findings, [])


class TestRunAllChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-doctor-"))
        self.home = self.tmp / "claude"
        self.home.mkdir()
        (self.home / "hooks").mkdir()
        (self.home / "commands").mkdir()
        (self.home / "bin").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_install_no_findings(self) -> None:
        (self.home / "settings.json").write_text(json.dumps({"hooks": {}}))
        (self.home / "commands" / "ok.md").write_text("# /ok - a perfectly fine command\n")
        findings = doctor.run_all_checks(self.home)
        self.assertEqual(findings, [])

    def test_aggregates_findings_across_checks(self) -> None:
        (self.home / "settings.json").write_text(json.dumps({
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"type": "command", "command": "$HOME/hooks/missing.py"}]}
                ]
            }
        }))
        (self.home / "commands" / "short.md").write_text("# /s\n")
        (self.home / "commands" / "ghost-ref.md").write_text(
            "# /ghost - does things\n\n```bash\nccgm-ghost-tool\n```\n"
        )
        orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            findings = doctor.run_all_checks(self.home)
        finally:
            os.environ["PATH"] = orig_path
        checks_seen = {f["check"] for f in findings}
        self.assertEqual(checks_seen, {"hook-refs", "command-descriptions", "script-refs"})


if __name__ == "__main__":
    unittest.main()
