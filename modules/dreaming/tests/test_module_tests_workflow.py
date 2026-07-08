"""Lint the module-tests CI workflow (composite-eligibility plan.md §5 Epic E6
test bullet: "CI workflow lints (actionlint if available, else
python3 -c yaml.safe_load)").

Prefers actionlint when it is on PATH (full GitHub Actions schema check);
otherwise falls back to a PyYAML structural parse; skips only if neither is
available. The workflow ALSO self-proves by running on this very PR -- this
test is the fast local/CI signal that it is at least well-formed.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "module-tests.yml"


class ModuleTestsWorkflowLintTest(unittest.TestCase):
    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WORKFLOW.is_file(), msg=f"missing workflow: {WORKFLOW}")

    def test_workflow_lints(self) -> None:
        actionlint = shutil.which("actionlint")
        if actionlint:
            proc = subprocess.run(
                [actionlint, str(WORKFLOW)],
                capture_output=True, text=True, timeout=60, check=False,
            )
            self.assertEqual(
                proc.returncode, 0,
                msg=f"actionlint failed:\n{proc.stdout}\n{proc.stderr}",
            )
            return

        try:
            import yaml  # noqa: PLC0415 -- optional, fallback path only
        except ImportError:
            self.skipTest("neither actionlint nor PyYAML available")

        data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        # YAML 1.1 folds the bare key `on` to boolean True; GitHub reads it
        # fine. Assert on the parts unaffected by that quirk.
        self.assertIn("jobs", data)
        self.assertIn("module-tests", data["jobs"])
        job = data["jobs"]["module-tests"]
        self.assertIn("steps", job)
        # The four §8.3 commands are present as named steps.
        step_names = [s.get("name", "") for s in job["steps"]]
        joined = "\n".join(step_names)
        for token in ("pytest", "disabled-mode", "enabled-mode", "eval"):
            self.assertIn(token, joined, msg=f"missing step for {token!r} in {step_names}")


if __name__ == "__main__":
    unittest.main()
