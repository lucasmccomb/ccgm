#!/usr/bin/env python3
"""
One-off backlog close (#1098 item 2.4): bin/dream-close-backlog.sh.

Replays every pending proposal, plain and gzipped, through the current
Phase 3 filters: the loaded-context prefilter (`already_encoded`, #1116),
hook-error routing (`routed_to_autoheal`, #1118) and trigger validation
(`trigger_invalid` / `trigger_unverified`, #1114). A row a filter drops is
discarded with that reason; the rest are discarded `expired` with detail
`pre-redesign`. --dry-run is the default and writes nothing; --apply writes
the statuses and the audit records.

Every path is a temp dir; the real ~/.claude is never touched.

Run with: python3 -m pytest modules/dreaming/tests/test_close_backlog.py -q
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "bin" / "dream-close-backlog.sh"

RULE = "Always double-quote PostgreSQL reserved words such as order and user when used as identifiers in migrations."
HOOK_ERROR = "PreToolUse hook error: [python3 /home/x/.claude/hooks/branch-guard.py]: blocked edit on main"


def _row(pid: str, *, kind="learning_add", content=None, evidence=None, trigger=None, status="pending",
         project="widget") -> dict:
    return {
        "id": pid, "kind": kind, "project": project, "target_id": None if kind == "learning_add" else "t1",
        "content": content if content is not None else f"Distinct learning number {pid} about widget builds",
        "type": "pattern" if kind == "learning_add" else None, "confidence": 7,
        "prevalence": {"sessions": 1, "agents": 1},
        "evidence": evidence or [{"session_id": None, "excerpt": f"excerpt for {pid} widget build failed"}],
        "justification": "backlog fixture", "trigger": trigger, "fingerprint": f"fp-{pid}",
        "generated_at": "2026-08-01T00:00:00.000Z", "status": status,
    }


class CloseBacklogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.dreaming = self.tmp / "dreaming"
        self.pdir = self.dreaming / "proposals"
        self.pdir.mkdir(parents=True)
        home = self.tmp / "claude-home"
        (home / "rules").mkdir(parents=True)
        (home / "rules" / "migrations.md").write_text(f"# Migrations\n\n{RULE}\n", encoding="utf-8")
        (home / "hooks").mkdir()
        (home / "hooks" / "branch-guard.py").write_text('"""Branch guard."""\n', encoding="utf-8")
        self.env = {
            **os.environ, "CCGM_DREAMING_DIR": str(self.dreaming), "CCGM_DREAMING_CLAUDE_HOME": str(home),
            "CCGM_LEARNINGS_DIR": str(self.tmp / "learnings"), "CCGM_CLAUDE_PROJECTS_DIR": str(self.tmp / "projects"),
            "HOME": str(self.tmp / "home"),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, rows: list, *, gz: bool = False) -> Path:
        text = "".join(json.dumps(r) + "\n" for r in rows)
        path = self.pdir / (f"{name}.jsonl.gz" if gz else f"{name}.jsonl")
        if gz:
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def _fixture(self) -> None:
        """228 pending rows over 8 files (4 gzipped) plus 5 already-terminal rows."""
        special = [
            _row("enc-1", content=RULE),
            _row("hook-1", evidence=[{"session_id": None, "excerpt": HOOK_ERROR}]),
            _row("trig-1", trigger={"kind": "phrase_set", "value": ["kubernetes"]}),
            _row("trigbad-1", trigger={"kind": "regex", "value": "("}),
            _row("trigok-1", trigger={"kind": "phrase_set", "value": ["widget build"]}),
            _row("verify-1", kind="learning_verify", content=None),
        ]
        plain = special + [_row(f"p{i}") for i in range(222)]
        chunks = [plain[i::8] for i in range(8)]
        for n, chunk in enumerate(chunks):
            chunk = chunk + ([_row(f"done-{n}", status="accepted")] if n < 5 else [])
            self._write(f"2026-08-{n + 1:02d}", chunk, gz=n % 2 == 1)

    def _run(self, *args: str):
        proc = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def _digest(self) -> str:
        h = hashlib.sha256()
        for p in sorted(self.pdir.iterdir()):
            h.update(p.name.encode())
            h.update(p.read_bytes())
        return h.hexdigest()

    def _all_rows(self) -> dict:
        rows = {}
        for p in sorted(self.pdir.iterdir()):
            opener = gzip.open if p.name.endswith(".gz") else open
            with opener(p, "rt", encoding="utf-8") as fh:
                for ln in fh:
                    if ln.strip():
                        r = json.loads(ln)
                        rows[r["id"]] = r
        return rows

    def _audit(self) -> list:
        path = self.dreaming / "state" / "apply-audit.jsonl"
        if not path.is_file():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def test_dry_run_is_the_default_plans_228_terminal_records_and_writes_nothing(self):
        self._fixture()
        before = self._digest()
        out = self._run()
        self.assertEqual(out["mode"], "dry-run")
        self.assertEqual((out["pending"], out["planned"]), (228, 228), out["by_reason"])
        self.assertEqual(len(out["records"]), 228)
        self.assertTrue(all(r["reason"] for r in out["records"]))
        self.assertEqual(self._digest(), before)
        self.assertEqual(self._audit(), [])

    def test_filters_assign_their_reasons_and_the_rest_expire_pre_redesign(self):
        self._fixture()
        by_id = {r["proposal_id"]: r for r in self._run("--dry-run")["records"]}
        self.assertEqual(by_id["enc-1"]["reason"], "already_encoded")
        self.assertIn("migrations.md", by_id["enc-1"]["detail"])
        self.assertEqual(by_id["hook-1"]["reason"], "routed_to_autoheal")
        self.assertEqual(by_id["trig-1"]["reason"], "trigger_unverified")
        self.assertEqual(by_id["trigbad-1"]["reason"], "trigger_invalid")
        for pid in ("trigok-1", "verify-1", "p0", "p221"):
            self.assertEqual((by_id[pid]["reason"], by_id[pid]["detail"]), ("expired", "pre-redesign"), pid)

    def test_apply_writes_every_record_and_leaves_nothing_pending(self):
        self._fixture()
        out = self._run("--apply")
        self.assertEqual((out["mode"], out["discarded"], out["pending_after"]), ("apply", 228, 0))
        rows = self._all_rows()
        self.assertFalse([r for r in rows.values() if r["status"] == "pending"])
        self.assertEqual(rows["done-0"]["status"], "accepted")
        self.assertEqual(rows["p5"]["discard_reason"], "expired")
        self.assertEqual(rows["p5"]["discard_detail"], "pre-redesign")
        audit = [r for r in self._audit() if r.get("outcome") == "discarded"]
        self.assertEqual(len(audit), 228)
        self.assertEqual(sum(1 for r in audit if r["reason"] == "expired"), 228 - 4)
        self.assertTrue(all(r["method"] == "backlog-close" for r in audit))

    def test_second_apply_is_a_no_op(self):
        self._fixture()
        self._run("--apply")
        out = self._run("--apply")
        self.assertEqual((out["pending"], out["discarded"]), (0, 0))
        self.assertEqual(len([r for r in self._audit() if r.get("outcome") == "discarded"]), 228)

    def test_empty_dreaming_dir_is_fine(self):
        out = self._run()
        self.assertEqual((out["pending"], out["planned"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
