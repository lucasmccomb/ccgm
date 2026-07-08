"""Non-interactive test for memory-setup.sh's composite eligibility opt-in
(composite-eligibility plan.md §5 Epic E6, adrev2-001).

memory-setup.sh's write functions are normally reached through interactive
confirm() prompts. The script gained a `BASH_SOURCE[0] == $0` guard so a test
can SOURCE it (main suppressed) and drive one writer directly -- here
write_eligibility_flag against a HOME-redirected dreaming dir -- with no
prompts.

The test asserts the two invariants Epic E6 owns:
  1. The write forces BOTH optimistic_integration.enabled=true AND
     optimistic_integration.eligibility.enabled=true (adrev2-001: eligibility
     must never land on with the outer engine off).
  2. The minimal on-disk block, once dream_analyze.load_config() deep-merges
     the defaults from eligibility.DEFAULT_ELIGIBILITY, PASSES
     eligibility.validate_eligibility_config().
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SETUP = REPO_ROOT / "modules" / "self-improving" / "bin" / "memory-setup.sh"
DREAMING_LIB = REPO_ROOT / "modules" / "dreaming" / "lib"


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@unittest.skipUnless(_have("jq"), "jq is required by memory-setup.sh")
@unittest.skipUnless(_have("bash"), "bash is required to source memory-setup.sh")
class MemorySetupEligibilityTest(unittest.TestCase):
    def test_write_eligibility_flag_produces_valid_enabled_block(self) -> None:
        sandbox = Path(tempfile.mkdtemp(prefix="ccgm-memsetup-elig-"))
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        home = sandbox / "home"
        dreaming_dir = home / ".claude" / "dreaming"
        dreaming_dir.mkdir(parents=True)

        env = dict(os.environ)
        env["HOME"] = str(home)
        # Let the script derive DREAMING_DIR from HOME (its top-level default).
        env.pop("CCGM_DREAMING_DIR", None)

        # Source the script (main suppressed by its BASH_SOURCE guard) and call
        # the writer directly. No confirm() prompt is reached, so this is fully
        # non-interactive.
        proc = subprocess.run(
            ["bash", "-c", f'source "{SETUP}"; write_eligibility_flag'],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(
            proc.returncode, 0,
            msg=f"write_eligibility_flag failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}",
        )

        cfg_path = dreaming_dir / "config.json"
        self.assertTrue(cfg_path.is_file(), msg="config.json was not written")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

        # Invariant 1: both flags true on disk (adrev2-001).
        self.assertIs(cfg["optimistic_integration"]["enabled"], True)
        self.assertIs(cfg["optimistic_integration"]["eligibility"]["enabled"], True)

        # Invariant 2: the deep-merged block passes validate_eligibility_config().
        # Run in a subprocess with CCGM_DREAMING_DIR + PYTHONPATH so load_config()
        # reads the file just-written and eligibility.py resolves as a sibling.
        check_src = (
            "import eligibility, dream_analyze\n"
            "cfg = dream_analyze.load_config()\n"
            "opt = cfg['optimistic_integration']\n"
            "ok, errs = eligibility.validate_eligibility_config(opt)\n"
            "assert ok, errs\n"
            "assert opt['enabled'] is True\n"
            "assert opt['eligibility']['enabled'] is True\n"
            "print('VALID')\n"
        )
        check = subprocess.run(
            [sys.executable, "-c", check_src],
            env={**env, "PYTHONPATH": str(DREAMING_LIB), "CCGM_DREAMING_DIR": str(dreaming_dir)},
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertIn(
            "VALID", check.stdout,
            msg=f"validate_eligibility_config rejected the written block:\n{check.stdout}\n{check.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
