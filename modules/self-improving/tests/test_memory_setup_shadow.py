"""Non-interactive tests for memory-setup.sh's shadow option (#1087).

Optimistic integration has three modes: off, shadow, active. The activation
prompt offers shadow first. These tests source the script (main suppressed by
its BASH_SOURCE guard) and drive the flag reader, the writers, and the offer.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SETUP = REPO_ROOT / "modules" / "self-improving" / "bin" / "memory-setup.sh"


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@unittest.skipUnless(_have("jq") and _have("bash"), "jq and bash are required")
class MemorySetupShadowTest(unittest.TestCase):
    def setUp(self) -> None:
        sandbox = Path(tempfile.mkdtemp(prefix="ccgm-memsetup-shadow-"))
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        self.home = sandbox / "home"
        self.dreaming = self.home / ".claude" / "dreaming"
        self.dreaming.mkdir(parents=True)
        # offer_optimistic_integration returns early without dream-install.sh.
        (self.home / ".claude" / "bin").mkdir(parents=True)
        (self.home / ".claude" / "bin" / "dream-install.sh").write_text("#!/bin/sh\n")
        self.cfg = self.dreaming / "config.json"
        self.env = {**os.environ, "HOME": str(self.home)}
        self.env.pop("CCGM_DREAMING_DIR", None)

    def _run(self, snippet: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", f'source "{SETUP}"; {snippet}'],
            env=self.env, input=stdin, capture_output=True, text=True, timeout=30, check=False,
        )

    def _enabled(self):
        return json.loads(self.cfg.read_text())["optimistic_integration"]["enabled"]

    def test_current_flag_reports_the_mode(self) -> None:
        cases = [
            (None, "unset"), (False, "unset"), (True, "active"),
            ("active", "active"), ("shadow", "shadow"), ("off", "unset"),
        ]
        for raw, expected in cases:
            if raw is None:
                self.cfg.write_text("{}")
            else:
                self.cfg.write_text(json.dumps({"optimistic_integration": {"enabled": raw}}))
            proc = self._run("current_optimistic_flag")
            self.assertEqual(proc.stdout.strip(), expected, (raw, proc.stderr))

    def test_write_flag_shadow_sets_the_string(self) -> None:
        proc = self._run("write_optimistic_flag shadow")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._enabled(), "shadow")

    def test_write_flag_default_is_active_boolean(self) -> None:
        proc = self._run("write_optimistic_flag")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIs(self._enabled(), True)

    def test_eligibility_write_keeps_shadow(self) -> None:
        self.cfg.write_text(json.dumps({"optimistic_integration": {"enabled": "shadow"}}))
        proc = self._run("write_eligibility_flag")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        cfg = json.loads(self.cfg.read_text())["optimistic_integration"]
        self.assertEqual(cfg["enabled"], "shadow")
        self.assertIs(cfg["eligibility"]["enabled"], True)

    def test_offer_accepting_shadow_writes_shadow(self) -> None:
        # yes to shadow; no to the eligibility gate.
        proc = self._run("offer_optimistic_integration", stdin="y\nn\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._enabled(), "shadow")

    def test_offer_declining_shadow_then_accepting_active(self) -> None:
        proc = self._run("offer_optimistic_integration", stdin="n\ny\nn\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIs(self._enabled(), True)

    def test_offer_declining_both_writes_nothing(self) -> None:
        proc = self._run("offer_optimistic_integration", stdin="n\nn\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(self.cfg.exists())

    def test_offer_in_shadow_can_promote_to_active(self) -> None:
        self.cfg.write_text(json.dumps({"optimistic_integration": {"enabled": "shadow"}}))
        proc = self._run("offer_optimistic_integration", stdin="y\nn\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIs(self._enabled(), True)

    def test_offer_in_shadow_declining_promotion_keeps_shadow(self) -> None:
        self.cfg.write_text(json.dumps({"optimistic_integration": {"enabled": "shadow"}}))
        proc = self._run("offer_optimistic_integration", stdin="n\nn\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._enabled(), "shadow")


if __name__ == "__main__":
    unittest.main()
