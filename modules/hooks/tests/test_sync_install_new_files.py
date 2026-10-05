#!/usr/bin/env python3
"""Fixture-repo tests: sync-ccgm-canonical installs new module files and
reports unregistered hooks and refused pulls (#1131). All state lives in temp
dirs with HOME overridden; the real ~/.claude and ~/code/ccgm are never touched."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOK_PATH = os.path.abspath(os.path.join(_TEST_DIR, '..', 'hooks', 'sync-ccgm-canonical.py'))

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                   env={**os.environ, **_GIT_ENV})


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def module_json(files):
    return json.dumps({"name": "mod", "scope": ["global"], "files": files})


def entry(target, **kw):
    return {"target": target, "type": "lib", "template": False, **kw}


class Fixture:
    """origin (bare) <- canonical clone <- pusher clone, plus a fake HOME."""

    def __init__(self, tmp):
        self.home = os.path.join(tmp, "home")
        self.claude = os.path.join(self.home, ".claude")
        self.origin = os.path.join(tmp, "origin.git")
        self.canonical = os.path.join(tmp, "canonical")
        self.pusher = os.path.join(tmp, "pusher")
        self.cwd = os.path.join(tmp, "workspace")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.pusher], check=True)
        git(self.pusher, "remote", "add", "origin", self.origin)
        write(os.path.join(self.pusher, "modules/mod/lib/old.py"), "old\n")
        write(os.path.join(self.pusher, "modules/mod/module.json"),
              module_json({"lib/old.py": entry("lib/old.py")}))
        self.commit("init")
        git(self.pusher, "push", "-q", "origin", "main")
        subprocess.run(["git", "clone", "-q", self.origin, self.canonical],
                       check=True, capture_output=True)
        # cwd is a repo whose origin is named ccgm so the hook's repo check passes
        os.makedirs(self.cwd)
        subprocess.run(["git", "init", "-q", self.cwd], check=True)
        git(self.cwd, "remote", "add", "origin", "git@github.com:testuser/ccgm.git")
        # installed state: old.py symlinked, manifest in link mode
        os.makedirs(os.path.join(self.claude, "lib"))
        os.symlink(os.path.join(self.canonical, "modules/mod/lib/old.py"),
                   os.path.join(self.claude, "lib/old.py"))
        self.write_manifest()

    def write_manifest(self, link_mode=True, modules=("mod",)):
        write(os.path.join(self.claude, ".ccgm-manifest.json"), json.dumps({
            "version": "1.0.0", "linkMode": link_mode, "scope": "global",
            "ccgmRoot": self.canonical, "modules": list(modules),
            "files": [os.path.join(self.claude, "lib/old.py")],
            "mergedFiles": [], "backups": [],
        }))

    def commit(self, msg):
        git(self.pusher, "add", "-A")
        git(self.pusher, "commit", "-q", "-m", msg)

    def push_files(self, files, extra=None):
        """Add files (module.json entries) to module 'mod' and push."""
        mj = {"lib/old.py": entry("lib/old.py")}
        for rel, e in files.items():
            write(os.path.join(self.pusher, "modules/mod", rel), "new\n")
            mj[rel] = e
        write(os.path.join(self.pusher, "modules/mod/module.json"), module_json(mj))
        for rel, text in (extra or {}).items():
            write(os.path.join(self.pusher, rel), text)
        self.commit("add")
        git(self.pusher, "push", "-q", "origin", "main")

    def run_hook(self):
        env = {**os.environ, "HOME": self.home, "CCGM_CANONICAL_DIR": self.canonical}
        return subprocess.run(
            [sys.executable, _HOOK_PATH],
            input=json.dumps({"tool_name": "Bash", "cwd": self.cwd,
                              "tool_input": {"command": "gh pr merge 1 --squash"}}),
            capture_output=True, text=True, env=env, timeout=60)

    def path(self, rel):
        return os.path.join(self.claude, rel)


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(os.path.realpath(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()


class TestInstallNewFiles(FixtureCase):
    def test_new_file_gets_symlink_and_manifest_entry(self):
        self.fx.push_files({"lib/new.py": entry("lib/new.py")})
        r = self.fx.run_hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.fx.path("lib/new.py")
        self.assertTrue(os.path.islink(p))
        self.assertEqual(os.readlink(p), os.path.join(self.fx.canonical, "modules/mod/lib/new.py"))
        self.assertEqual(open(p).read(), "new\n")
        manifest = json.load(open(self.fx.path(".ccgm-manifest.json")))
        self.assertIn(p, manifest["files"])
        self.assertIn("lib/new.py", r.stdout + r.stderr)

    def test_templated_file_not_symlinked(self):
        self.fx.push_files({"lib/tpl.py": entry("lib/tpl.py", template=True)})
        self.fx.run_hook()
        self.assertFalse(os.path.lexists(self.fx.path("lib/tpl.py")))

    def test_merge_target_not_symlinked(self):
        self.fx.push_files({"settings.partial.json": entry("settings.json", merge=True)})
        self.fx.run_hook()
        self.assertFalse(os.path.lexists(self.fx.path("settings.json")))

    def test_existing_file_untouched(self):
        mine = self.fx.path("lib/new.py")
        write(mine, "mine\n")
        self.fx.push_files({"lib/new.py": entry("lib/new.py")})
        self.fx.run_hook()
        self.assertFalse(os.path.islink(mine))
        self.assertEqual(open(mine).read(), "mine\n")

    def test_copy_mode_installs_nothing(self):
        self.fx.write_manifest(link_mode=False)
        self.fx.push_files({"lib/new.py": entry("lib/new.py")})
        self.fx.run_hook()
        self.assertFalse(os.path.lexists(self.fx.path("lib/new.py")))

    def test_uninstalled_module_not_installed(self):
        self.fx.write_manifest(modules=("other",))
        self.fx.push_files({"lib/new.py": entry("lib/new.py")})
        self.fx.run_hook()
        self.assertFalse(os.path.lexists(self.fx.path("lib/new.py")))

    def test_missing_manifest_is_harmless(self):
        os.remove(self.fx.path(".ccgm-manifest.json"))
        self.fx.push_files({"lib/new.py": entry("lib/new.py")})
        r = self.fx.run_hook()
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.lexists(self.fx.path("lib/new.py")))


class TestPathContainment(FixtureCase):
    """module.json paths are untrusted: nothing may be created outside claude_dir,
    and a source may not leave its module directory."""

    def outside(self):
        # sibling of fake HOME, still inside the temp dir
        return os.path.join(os.path.dirname(self.fx.home), "outside")

    def assert_refused(self, files, needle):
        self.fx.push_files(files)
        r = self.fx.run_hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("refused unsafe", r.stdout + r.stderr)
        self.assertIn(needle, r.stdout + r.stderr)
        self.assertFalse(os.path.lexists(self.outside()))
        self.assertFalse(os.path.lexists(os.path.join(self.fx.home, ".zshrc")))
        self.assertFalse(os.path.lexists(os.path.join(self.fx.home, "evil.plist")))

    def test_dotdot_target_refused(self):
        self.assert_refused({"lib/a.py": entry("../.zshrc")}, "../.zshrc")

    def test_nested_dotdot_target_refused(self):
        self.assert_refused({"lib/a.py": entry("hooks/../../evil.plist")}, "evil.plist")

    def test_absolute_target_refused(self):
        abs_target = os.path.join(self.outside(), "x")
        self.assert_refused({"lib/a.py": entry(abs_target)}, abs_target)

    def test_symlinked_parent_escaping_claude_dir_refused(self):
        os.makedirs(self.outside())
        os.symlink(self.outside(), self.fx.path("escape"))
        self.fx.push_files({"lib/a.py": entry("escape/a.py")})
        r = self.fx.run_hook()
        self.assertIn("refused unsafe target escape/a.py", r.stdout + r.stderr)
        self.assertEqual(os.listdir(self.outside()), [])

    def test_dotdot_source_refused(self):
        # push_files writes pusher/secret.txt (outside modules/mod), which the pull brings in
        self.fx.push_files({"../../secret.txt": entry("lib/s.txt")})
        r = self.fx.run_hook()
        self.assertIn("refused unsafe source", r.stdout + r.stderr)
        self.assertFalse(os.path.lexists(self.fx.path("lib/s.txt")))

    def test_safe_entry_still_installed_alongside_refused_one(self):
        self.fx.push_files({"lib/a.py": entry("../.zshrc"), "lib/ok.py": entry("lib/ok.py")})
        self.fx.run_hook()
        self.assertTrue(os.path.islink(self.fx.path("lib/ok.py")))


def partial(*cmds):
    return json.dumps({"hooks": {"PostToolUse": [{"hooks": [
        {"type": "command", "command": c} for c in cmds]}]}})


class TestUnregisteredHooks(FixtureCase):
    def test_unregistered_hook_reported(self):
        write(self.fx.path("settings.json"), partial("python3 $HOME/.claude/hooks/a.py"))
        self.fx.push_files({}, extra={"modules/mod/settings.partial.json": partial(
            "python3 $HOME/.claude/hooks/a.py", "python3 $HOME/.claude/hooks/b.py")})
        out = (lambda r: r.stdout + r.stderr)(self.fx.run_hook())
        self.assertIn("hooks/b.py", out)
        self.assertNotIn("hooks/a.py", out)
        self.assertIn("not registered", out)
        self.assertNotIn("b.py", open(self.fx.path("settings.json")).read())  # never auto-merged

    def test_all_registered_no_report(self):
        write(self.fx.path("settings.json"), partial("python3 $HOME/.claude/hooks/a.py"))
        self.fx.push_files({}, extra={"modules/mod/settings.partial.json":
                                      partial("python3 $HOME/.claude/hooks/a.py")})
        r = self.fx.run_hook()
        self.assertNotIn("not registered", r.stdout + r.stderr)


class TestRefusedPull(FixtureCase):
    def test_dirty_canonical_reports_commits_behind(self):
        # A local edit to a file the next commits change makes the ff-only pull refuse.
        write(os.path.join(self.fx.canonical, "modules/mod/lib/old.py"), "dirty\n")
        write(os.path.join(self.fx.pusher, "modules/mod/lib/old.py"), "changed\n")
        self.fx.commit("c1")
        write(os.path.join(self.fx.pusher, "modules/mod/lib/old.py"), "changed2\n")
        self.fx.commit("c2")
        git(self.fx.pusher, "push", "-q", "origin", "main")
        r = self.fx.run_hook()
        self.assertIn("canonical CCGM clone is 2 commits behind origin/main:", r.stdout + r.stderr)
        self.assertEqual(r.returncode, 0)

    def test_success_has_no_behind_line(self):
        self.fx.push_files({"lib/new.py": entry("lib/new.py")})
        r = self.fx.run_hook()
        self.assertNotIn("commits behind", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
