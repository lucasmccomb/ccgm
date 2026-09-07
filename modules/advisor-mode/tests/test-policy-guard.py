"""Real file/hook regressions for the advisor policy execution exception.

All scripts and victim files live in a temporary fake HOME. No provider runs.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'hooks/advisor-guard.py'
MODULE = ROOT.parent / 'cross-agent-review'
SHIM = Path('lib/cross_agent_review_policy.py')
POLICY = Path('skills/cross-agent-review/scripts/review_policy.py')
RUNTIME = POLICY.with_name('cross_agent_review.py')


class PolicyGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.scratch = Path(self.temporary.name)
        self.home = self.scratch / 'home'
        self.canonical = self.home / 'code/repo/module'
        self.installed = self.home / '.claude' / SHIM
        self.env = dict(os.environ, HOME=str(self.home), TMPDIR=str(self.scratch / 'scratch'))
        for key in ('ADVISOR_DIRECT', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE',
                    'PYTHONINSPECT', 'PYTHONSTARTUP'):
            self.env.pop(key, None)
        Path(self.env['TMPDIR']).mkdir()
        flag = self.home / '.claude/advisor-mode/policy-test'
        flag.parent.mkdir(parents=True)
        flag.touch()
        self.install_tree(self.canonical)
        self.installed.parent.mkdir(parents=True)
        self.installed.symlink_to(self.canonical / SHIM)
        self.victim = self.home / 'code/repo/victim.txt'
        self.victim.write_text('unchanged')

    def install_tree(self, target):
        for relative in (SHIM, POLICY, RUNTIME):
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(MODULE / relative, path)

    def hook(self, tool, payload, **metadata):
        data = dict(tool_name=tool, tool_input=payload, session_id='policy-test', **metadata)
        result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(data),
                                text=True, capture_output=True, env=self.env, cwd=self.canonical)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def command(self, suffix='select', script=None):
        return 'python3 ' + shlex.quote(str(script or self.installed)) + ' ' + suffix

    def check_command(self, expected, command=None, **metadata):
        result = self.hook('Bash', {'command': command or self.command()}, **metadata)
        self.assertEqual(expected, result.returncode, result.stderr)
        if expected == 2:
            self.assertIn('advisor mode:', result.stderr)
        return result

    def mutation(self):
        return 'from pathlib import Path\nPath(%r).write_text("changed")\n' % str(self.victim)

    def execute_if_allowed(self):
        """Simulate the tool gate; old vulnerable guards execute the fixture."""
        result = self.hook('Bash', {'command': self.command()})
        if result.returncode == 0:
            subprocess.run([sys.executable, str(self.installed), 'select'], env=self.env,
                           cwd=self.canonical, capture_output=True, timeout=15)
        self.assertEqual('unchanged', self.victim.read_text(), 'guard allowed arbitrary fixture code')
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn('delegate', result.stderr.lower())

    def test_canonical_symlink_allows_real_selection_and_blocks_source_edits(self):
        self.check_command(0)
        for path in (self.installed, self.canonical / POLICY, self.canonical / RUNTIME):
            self.assertEqual(2, self.hook('Write', {'file_path': str(path)}).returncode)
        result = subprocess.run([sys.executable, str(self.installed), 'select'], env=self.env,
                                cwd=self.canonical, capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('NEEDS_SELECTION', json.loads(result.stdout)['status'])

    def test_copied_shim_write_then_execute_is_blocked(self):
        self.installed.unlink()
        self.install_tree(self.home / '.claude')
        self.assertEqual(0, self.hook('Write', {'file_path': str(self.installed)}).returncode)
        self.installed.write_text(self.mutation())
        self.execute_if_allowed()
        self.check_command(0, agent_id='delegated-worker')

    def test_temp_symlink_write_then_execute_is_blocked(self):
        target = self.scratch / 'temp-module'
        self.install_tree(target)
        self.installed.unlink()
        self.installed.symlink_to(target / SHIM)
        self.assertEqual(0, self.hook('Write', {'file_path': str(self.installed)}).returncode)
        (target / SHIM).write_text(self.mutation())
        self.execute_if_allowed()

    def test_protected_shim_with_writable_policy_import_is_blocked(self):
        target = self.scratch / 'temp-module'
        self.install_tree(target)
        (self.canonical / POLICY).unlink()
        (self.canonical / POLICY).symlink_to(target / POLICY)
        (target / POLICY).write_text(self.mutation() + (target / POLICY).read_text())
        self.assertEqual(2, self.hook('Write', {'file_path': str(self.installed)}).returncode)
        self.assertEqual(0, self.hook('Write', {'file_path': str(self.canonical / POLICY)}).returncode)
        self.execute_if_allowed()

    def test_protected_shim_and_policy_with_writable_runtime_is_blocked(self):
        target = self.scratch / 'runtime.py'
        target.write_text(self.mutation() + (self.canonical / RUNTIME).read_text())
        (self.canonical / RUNTIME).unlink()
        (self.canonical / RUNTIME).symlink_to(target)
        self.assertEqual(0, self.hook('Write', {'file_path': str(self.canonical / RUNTIME)}).returncode)
        self.execute_if_allowed()

    def test_every_existing_writable_root_denies_policy_execution(self):
        roots = [self.home / '.claude/copy', self.home / 'code/plans/copy',
                 self.home / 'code/docs/copy', self.home / 'code/repo/.claude/worktrees/copy',
                 self.home / 'code/repo/.worktrees/copy', self.home / 'code/repo/.claude/plans/copy',
                 self.scratch / 'outside-home', Path(self.env['TMPDIR']) / 'copy']
        for target in roots:
            with self.subTest(root=str(target)):
                self.install_tree(target)
                self.installed.unlink()
                self.installed.symlink_to(target / SHIM)
                self.assertEqual(0, self.hook('Write', {'file_path': str(self.installed)}).returncode)
                self.check_command(2)

    def test_writable_import_package_and_bytecode_are_blocked(self):
        scripts = self.canonical / POLICY.parent
        for name in ('cross_agent_review', '__pycache__'):
            with self.subTest(name=name):
                target = self.scratch / name
                target.mkdir()
                (target / '__init__.py').write_text(self.mutation())
                link = scripts / name
                link.symlink_to(target, target_is_directory=True)
                self.check_command(2)
                link.unlink()
        target = self.scratch / 'json.py'
        target.write_text(self.mutation())
        (scripts / 'json.py').symlink_to(target)
        self.check_command(2)

    def test_missing_and_looping_installations_fail_closed(self):
        self.installed.unlink()
        self.check_command(2)
        self.installed.symlink_to(self.installed)
        self.check_command(2)

    def test_dangling_package_cannot_be_created_before_execution_in_same_command(self):
        package = self.scratch / 'new-package'
        link = self.canonical / POLICY.parent / 'cross_agent_review'
        link.symlink_to(package, target_is_directory=True)
        payload = self.scratch / 'package-init.py'
        payload.write_text(self.mutation())
        command = ('mkdir ' + shlex.quote(str(package)) + ' && cp ' + shlex.quote(str(payload))
                   + ' ' + shlex.quote(str(package / '__init__.py')) + ' && ' + self.command())
        result = self.hook('Bash', {'command': command})
        if result.returncode == 0:
            subprocess.run(['/bin/bash', '-c', command], env=self.env, cwd=self.canonical,
                           capture_output=True, timeout=15)
        self.assertEqual('unchanged', self.victim.read_text(), 'guard allowed a newly populated import package')
        self.assertEqual(2, result.returncode, result.stderr)

    def test_interpreter_script_and_import_path_manipulations_are_blocked(self):
        for command in (
            self.command(script=self.canonical / SHIM),
            self.command(script=self.installed.parent / '../lib/cross_agent_review_policy.py'),
            self.command(script=self.installed.parent / 'missing/../cross_agent_review_policy.py'),
            'python3 -c pass ' + shlex.quote(str(self.installed)) + ' select',
            'PATH=/tmp ' + self.command(),
            'HOME=/tmp ' + self.command(),
            'PYTHONPATH=/tmp ' + self.command(),
            'PYTHONINSPECT=1 ' + self.command(),
        ):
            with self.subTest(command=command):
                self.check_command(2, command)
        self.env['PYTHONPATH'] = str(self.scratch)
        self.check_command(2)


if __name__ == '__main__':
    unittest.main()
