#!/usr/bin/env python3
"""
Back-compat safety net for the composite-eligibility gate (composite-eligibility
plan.md Epic E4). Proves, against a synthetic corpus + the §3.9 worked cases,
that the shipped defaults reproduce today's behavior and that the enabled-mode
gate widens (never silently narrows) admission for legitimate, evidence-
resolving proposals.

Five properties (plan.md §5 E4):
  1. Parity theorem (decisions.md #27): for every corpus row with RESOLVABLE
     evidence, the enabled-mode decision under {weights: confidence=1.0,
     threshold=0.8, legacy_floor_admits=true} equals the legacy admit/reject
     BOOLEAN -- except the enumerated user-corrected single-session widening
     rows (legacy rejects, enabled admits), the mirror of the forged-evidence
     exceptions.
  2. True-default parity: eligibility.enabled=false produces outcome records
     byte-identical to legacy (no eligibility block at all).
  3. Target-behavior matrix: §3.9 (a)-(i) reproduced end-to-end through
     _process_one_proposal().
  4. Widening-only proof: no resolvable row admitted by legacy is rejected by
     the enabled defaults; the forged-evidence exceptions (legacy admits,
     enabled rejects) are enumerated and asserted.
  5. Red regression: an inferred-once conf-9 add is rejected in BOTH modes.

Runs in isolation: CCGM_LEARNINGS_DIR + CCGM_DREAMING_DIR + CCGM_CLAUDE_PROJECTS_DIR
+ HOME redirected to tempdirs BEFORE import (module-level constants freeze at
import; #793). No network, no ANTHROPIC_API_KEY, never the real store/dreaming/
transcripts. Every transcript is synthetic (transcript_fixtures.py).

Run with: python3 -m pytest modules/dreaming/tests/test_eligibility_parity.py -q
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "lib"))

sys.modules.pop("learnings_store", None)
sys.modules.pop("dream_analyze", None)
sys.modules.pop("apply_dream_proposal", None)
sys.modules.pop("transcript_miner", None)

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-elig-parity-learnings-")
_TMP_DREAMING = tempfile.mkdtemp(prefix="ccgm-elig-parity-dreaming-")
_TMP_PROJECTS = tempfile.mkdtemp(prefix="ccgm-elig-parity-projects-")
_TMP_HOME = tempfile.mkdtemp(prefix="ccgm-elig-parity-home-")
_ORIG = {
    "CCGM_LEARNINGS_DIR": os.environ.get("CCGM_LEARNINGS_DIR"),
    "CCGM_DREAMING_DIR": os.environ.get("CCGM_DREAMING_DIR"),
    "CCGM_CLAUDE_PROJECTS_DIR": os.environ.get("CCGM_CLAUDE_PROJECTS_DIR"),
    "HOME": os.environ.get("HOME"),
}
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS
os.environ["CCGM_DREAMING_DIR"] = _TMP_DREAMING
os.environ["CCGM_CLAUDE_PROJECTS_DIR"] = _TMP_PROJECTS
os.environ["HOME"] = _TMP_HOME

import apply_dream_proposal as adp  # noqa: E402
import dream_analyze as da  # noqa: E402
import eligibility as elig  # noqa: E402
import learnings_store as ls  # noqa: E402
import transcript_fixtures as tf  # noqa: E402


def tearDownModule() -> None:
    for key, orig in _ORIG.items():
        if orig is not None:
            os.environ[key] = orig
        else:
            os.environ.pop(key, None)


CORPUS_DIR = HERE / "fixtures" / "eligibility-parity"

# Corroboration sentence the "canon" transcript carries; excerpt variants are
# verbatim/paraphrase/sanitized/garbage of it (adrev-001 excerpt-tolerance span).
CANON = ("The Edit tool does not follow symlinks so read the workspace path first "
         "before editing the file")
PARAPHRASE = ("The Edit tool doesn't follow symlinks, so read the workspace path first "
              "before editing the file")
SANITIZED = ("[neutralized]The Edit tool[/neutralized] does not follow symlinks so read the "
             "workspace path first before editing the file")
GARBAGE = "completely unrelated zzzqqq wubwub payload nowhere present in this transcript at all today"

# Redaction: placeholder length comparable to the raw secret it replaces, so the
# excerpt-sized window still spans the raw source (realistic CLEARING shape --
# the #846 residual is the OPPOSITE case, exercised by add_forged rows' notes).
RAW_SECRET = ("the deploy key ghp_ABCD1234SECRETVAL must be set in the settings file before "
              "running the migration script now")
REDACTED_EXCERPT = ("the deploy key [REDACTED:github_token] must be set in the settings file before "
                    "running the migration script now")

# Supersede target + its near-dup refinement (one fact flipped) + a substantive
# rewrite. Novelty-vs-target drives §3.9 (h)/(i).
SUP_TARGET = "Deploy to production on port 8080 using the blue pipeline after the nightly build completes"
SUP_NEARDUP = "Deploy to production on port 9090 using the blue pipeline after the nightly build completes"
SUP_SUBSTANTIVE = ("Roll back the deployment entirely and switch every service to the green pipeline "
                   "permanently because blue is deprecated")

_CONTENT_MAP = {"canon": CANON, "substantive": SUP_SUBSTANTIVE, "neardup": SUP_NEARDUP}


def _load_corpus() -> list[dict]:
    rows: list[dict] = []
    for name in ("add.jsonl", "supersede.jsonl", "evictions.jsonl"):
        path = CORPUS_DIR / name
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class ParityBase(unittest.TestCase):
    def setUp(self) -> None:
        self._pin("CCGM_LEARNINGS_DIR", str(ls.LEARNINGS_ROOT))
        self._pin("CCGM_DREAMING_DIR", _TMP_DREAMING)
        self._pin("CCGM_CLAUDE_PROJECTS_DIR", str(ls.CLAUDE_PROJECTS_ROOT))
        self._pin("HOME", _TMP_HOME)
        adp.proposals_dir().mkdir(parents=True, exist_ok=True)
        adp.state_dir().mkdir(parents=True, exist_ok=True)
        adp._write_optimistic_state_atomic(adp._default_optimistic_state())

    def _pin(self, key: str, value: str) -> None:
        had = key in os.environ
        prior = os.environ.get(key)
        os.environ[key] = value
        self.addCleanup(lambda: os.environ.__setitem__(key, prior) if had else os.environ.pop(key, None))

    # ---- world construction ------------------------------------------------

    def _slug(self) -> str:
        return f"parity-{uuid.uuid4().hex[:8]}"

    def _cwd_for(self, slug: str) -> str:
        return f"/synthetic-nonexistent/code/{slug}"

    def _content_str(self, selector) -> str:
        return _CONTENT_MAP.get(selector, CANON) if selector else CANON

    def _excerpt_for(self, variant: str, content: str) -> str:
        return {
            "verbatim": CANON, "paraphrase": PARAPHRASE, "sanitized": SANITIZED,
            "garbage": GARBAGE, "redacted": REDACTED_EXCERPT, "content": content,
        }[variant]

    def _transcript_sentence(self, key: str, content: str) -> str:
        return {"canon": CANON, "redacted_raw": RAW_SECRET, "content": content}.get(key, CANON)

    def _write_session(self, session_id: str, *, cwd_slug: str, sentence: str,
                       correction: bool, days_ago: float) -> None:
        base = datetime.now(timezone.utc) - timedelta(days=days_ago)
        turns: list = []
        if correction:
            turns.extend(tf.correction_sequence(
                request="Please reformat the config file.",
                correction="No, that's wrong, revert that change to the config entirely.",
            ))
        turns.append(tf.user_turn(sentence, human=True))
        path = ls.CLAUDE_PROJECTS_ROOT / f"proj-{uuid.uuid4().hex[:6]}" / f"{session_id}.jsonl"
        tf.write_transcript(path, turns, session_id=session_id, cwd=self._cwd_for(cwd_slug),
                            base_ts=tf.iso(base))

    def build_world(self, row: dict) -> tuple[dict, str, dict]:
        """Materialize a corpus row's world (transcripts + store heads) under
        unique runtime ids and return (clean_proposal, slug, heads)."""
        proposal = row["proposal"]
        world = row["world"]
        kind = proposal["kind"]
        slug = self._slug()
        content = self._content_str(proposal.get("content"))

        # Seed the store: novelty heads (add) + supersede target.
        for head_content in world.get("existing_heads") or []:
            e = ls.build_entry(type_="pattern", content=head_content, confidence=5)
            e["project"] = slug
            ls.append_entry(e, slug=slug)
        target_id = None
        if world.get("target"):
            te = ls.build_entry(type_="pattern", content=SUP_TARGET, confidence=8)
            te["project"] = slug
            ls.append_entry(te, slug=slug)
            target_id = te["id"]

        # Write a transcript per logical session; map logical key -> runtime id.
        # For supersede, the corroborating text is always the NEW content, so its
        # sessions always carry the content transcript regardless of the fixture's
        # transcript key (the single source of correctness for the supersede case).
        sid_map: dict[str, str] = {}
        for key, spec in (world.get("sessions") or {}).items():
            rid = f"sess-{uuid.uuid4().hex[:10]}"
            sid_map[key] = rid
            if spec.get("resolvable", True):
                cwd_slug = slug if spec.get("slug_matches", True) else self._slug()
                transcript_key = "content" if kind == "learning_supersede" else spec.get("transcript", "canon")
                self._write_session(
                    rid, cwd_slug=cwd_slug,
                    sentence=self._transcript_sentence(transcript_key, content),
                    correction=spec.get("correction", False),
                    days_ago=spec.get("days_ago", 2),
                )

        evidence = []
        for ev in proposal.get("evidence") or []:
            key = ev["session"]
            rid = sid_map.get(key, f"sess-{uuid.uuid4().hex[:10]}")  # unresolvable keys still get a distinct id
            evidence.append({"session_id": rid, "excerpt": self._excerpt_for(ev["excerpt_variant"], content)})

        needs_content = kind in ("learning_add", "learning_supersede")
        clean = {
            "id": f"p-{uuid.uuid4().hex[:10]}",
            "kind": kind,
            "project": slug,
            "target_id": target_id if kind != "learning_add" else None,
            "content": content if needs_content else None,
            "type": proposal.get("type") if needs_content else None,
            "confidence": proposal["confidence"],
            "prevalence": {"sessions": proposal.get("prevalence_sessions", 1), "agents": 1},
            "evidence": evidence or [{"session_id": f"sess-{uuid.uuid4().hex[:8]}", "excerpt": "x"}],
            "justification": "parity corpus",
            "fingerprint": f"fp-{uuid.uuid4().hex[:10]}",
            "generated_at": "2026-01-01T00:00:00.000Z",
            "status": "pending",
        }
        # contradict/deprecate/verify require a target_id; give a placeholder
        # (the legacy branch never resolves it -- apply is stubbed in these tests).
        if kind in ("learning_contradict", "learning_deprecate", "learning_verify") and clean["target_id"] is None:
            clean["target_id"] = f"tgt-{uuid.uuid4().hex[:8]}"

        heads = {h["id"]: h for h in ls.load_all(slug)}
        return clean, slug, heads

    # ---- config builders ---------------------------------------------------

    def _base_optimistic(self) -> dict:
        return dict(da.DEFAULT_OPTIMISTIC_INTEGRATION)

    def legacy_cfg(self) -> dict:
        # No eligibility block at all == today's behavior.
        return self._base_optimistic()

    def disabled_cfg(self) -> dict:
        cfg = self._base_optimistic()
        cfg["eligibility"] = elig.default_eligibility()  # enabled: False
        return cfg

    def parity_cfg(self) -> dict:
        cfg = self._base_optimistic()
        ec = elig.default_eligibility()
        ec["enabled"] = True
        ec["weights"] = {"confidence": 1.0, "prevalence": 0.0, "recency": 0.0, "novelty": 0.0}
        ec["threshold"] = 0.8
        ec["legacy_floor_admits"] = True
        cfg["eligibility"] = ec
        return cfg

    def default_cfg(self) -> dict:
        cfg = self._base_optimistic()
        ec = elig.default_eligibility()
        ec["enabled"] = True
        cfg["eligibility"] = ec
        return cfg

    # ---- gate driver -------------------------------------------------------

    def run_gate(self, proposal: dict, slug: str, heads: dict, optimistic: dict) -> tuple[bool, dict]:
        """Drive _process_one_proposal with apply_proposal stubbed to a no-op
        success, so the observed admit/reject boolean is the GATE decision and
        the store is never mutated. Returns (admit_bool, result_dict)."""
        with mock.patch.object(adp, "apply_proposal",
                               return_value={"ok": True, "outcome": "auto_applied"}):
            result = adp._process_one_proposal(
                proposal, slug=slug, cfg=optimistic, live_count=100,
                anomaly_slugs=set(), add_supersede_counts={slug: 0}, eviction_counts={slug: 0},
                batch_id=f"batch-{uuid.uuid4().hex[:6]}", heads=heads,
                session_cache={}, session_citation_counts={},
            )
        return result.get("applied") is True, result


# ---------------------------------------------------------------------------
# Authored-expectation pin: the real gate matches each corpus row's hand-authored
# legacy/parity/default booleans. Catches both a gate regression AND a mis-
# authored fixture (either fails loudly rather than silently agreeing).
# ---------------------------------------------------------------------------


class AuthoredExpectationTests(ParityBase):
    def test_every_corpus_row_matches_its_authored_expectations(self):
        for row in _load_corpus():
            with self.subTest(case=row["case_id"]):
                exp = row["expect"]
                for label, cfg_fn, key in (
                    ("legacy", self.legacy_cfg, "legacy_admit"),
                    ("parity", self.parity_cfg, "parity_admit"),
                    ("default", self.default_cfg, "default_admit"),
                ):
                    proposal, s, heads = self.build_world(row)
                    admit, result = self.run_gate(proposal, s, heads, cfg_fn())
                    self.assertEqual(
                        admit, exp[key],
                        f"{row['case_id']} [{label}]: gate admit={admit} but fixture expects "
                        f"{exp[key]} (outcome={result.get('outcome')})",
                    )


# ---------------------------------------------------------------------------
# Property 1: Parity theorem (decisions.md #27).
# ---------------------------------------------------------------------------


class ParityTheoremTests(ParityBase):
    def test_conf_only_config_equals_legacy_boolean_for_resolvable_rows(self):
        checked = 0
        exceptions = 0
        for row in _load_corpus():
            exp = row["expect"]
            if not exp["resolvable_evidence"]:
                continue
            with self.subTest(case=row["case_id"]):
                p_l, s_l, h_l = self.build_world(row)
                legacy_admit, _ = self.run_gate(p_l, s_l, h_l, self.legacy_cfg())
                p_p, s_p, h_p = self.build_world(row)
                parity_admit, res = self.run_gate(p_p, s_p, h_p, self.parity_cfg())

                if exp["parity_widening_exception"]:
                    # The deliberate widening: legacy rejects, enabled admits via
                    # the user-corrected single-session origin-gate pass.
                    exceptions += 1
                    self.assertFalse(legacy_admit, f"{row['case_id']}: widening exception must reject under legacy")
                    self.assertTrue(parity_admit, f"{row['case_id']}: widening exception must admit under parity config")
                else:
                    self.assertEqual(
                        parity_admit, legacy_admit,
                        f"{row['case_id']}: parity-config boolean ({parity_admit}) must equal legacy "
                        f"({legacy_admit}) for a resolvable, non-widening row (outcome={res.get('outcome')})",
                    )
                checked += 1
        self.assertGreaterEqual(checked, 15, "parity theorem must exercise a substantial resolvable subset")
        self.assertGreaterEqual(exceptions, 2, "the user-corrected single-session widening exceptions must be present")


# ---------------------------------------------------------------------------
# Property 2: True-default parity -- enabled:false is byte-identical to legacy.
# ---------------------------------------------------------------------------


class TrueDefaultParityTests(ParityBase):
    def test_disabled_block_outcome_record_identical_to_legacy(self):
        for row in _load_corpus():
            with self.subTest(case=row["case_id"]):
                p1, s1, h1 = self.build_world(row)
                _, legacy_result = self.run_gate(p1, s1, h1, self.legacy_cfg())
                p2, s2, h2 = self.build_world(row)
                _, disabled_result = self.run_gate(p2, s2, h2, self.disabled_cfg())
                # The proposal_id differs per rebuild; compare the decision-shape
                # fields that define the "outcome record" (plan.md §5 E4 property 2).
                self.assertEqual(
                    {k: legacy_result.get(k) for k in ("outcome", "applied", "attempted")},
                    {k: disabled_result.get(k) for k in ("outcome", "applied", "attempted")},
                    f"{row['case_id']}: eligibility.enabled=false must be byte-identical to legacy",
                )


# ---------------------------------------------------------------------------
# Property 4: Widening-only proof + enumerated forged-evidence exceptions.
# ---------------------------------------------------------------------------


class WideningOnlyTests(ParityBase):
    def test_no_resolvable_legacy_admit_is_rejected_by_enabled_defaults(self):
        widened = 0
        for row in _load_corpus():
            exp = row["expect"]
            if not exp["resolvable_evidence"] or not exp["legacy_admit"]:
                continue
            with self.subTest(case=row["case_id"]):
                pl, sl, hl = self.build_world(row)
                legacy_admit, _ = self.run_gate(pl, sl, hl, self.legacy_cfg())
                self.assertTrue(legacy_admit, f"{row['case_id']}: fixture says legacy admits")
                pd, sd, hd = self.build_world(row)
                default_admit, res = self.run_gate(pd, sd, hd, self.default_cfg())
                self.assertTrue(
                    default_admit,
                    f"{row['case_id']}: legacy admits a resolvable row that enabled defaults REJECT "
                    f"(outcome={res.get('outcome')}) -- widening-only violated",
                )
                widened += 1
        self.assertGreaterEqual(widened, 4, "widening-only must exercise several legacy-admit resolvable rows")

    def test_forged_evidence_exceptions_are_enumerated(self):
        forged = 0
        for row in _load_corpus():
            exp = row["expect"]
            if not exp["forged_widening_exception"]:
                continue
            with self.subTest(case=row["case_id"]):
                pl, sl, hl = self.build_world(row)
                legacy_admit, _ = self.run_gate(pl, sl, hl, self.legacy_cfg())
                pd, sd, hd = self.build_world(row)
                default_admit, res = self.run_gate(pd, sd, hd, self.default_cfg())
                self.assertTrue(legacy_admit, f"{row['case_id']}: forged exception must admit under legacy")
                self.assertFalse(
                    default_admit,
                    f"{row['case_id']}: forged exception must be REJECTED under enabled defaults "
                    f"(got outcome={res.get('outcome')}); enabled is strictly harder on forged evidence",
                )
                forged += 1
        self.assertGreaterEqual(forged, 2, "the forged-evidence exceptions must be present in the corpus")


# ---------------------------------------------------------------------------
# Property 5: Red regression -- inferred-once conf-9 add rejected in BOTH modes.
# ---------------------------------------------------------------------------


class RedRegressionTests(ParityBase):
    def test_red_rows_rejected_in_both_modes(self):
        red = 0
        for row in _load_corpus():
            if not row["expect"].get("red_regression"):
                continue
            with self.subTest(case=row["case_id"]):
                pl, sl, hl = self.build_world(row)
                legacy_admit, _ = self.run_gate(pl, sl, hl, self.legacy_cfg())
                pd, sd, hd = self.build_world(row)
                default_admit, res = self.run_gate(pd, sd, hd, self.default_cfg())
                self.assertFalse(legacy_admit, f"{row['case_id']}: must be rejected under legacy")
                self.assertFalse(
                    default_admit,
                    f"{row['case_id']}: inferred-once conf-9 add must be rejected under enabled defaults "
                    f"(got {res.get('outcome')})",
                )
                red += 1
        self.assertGreaterEqual(red, 1, "the red-regression case must be present")


# ---------------------------------------------------------------------------
# Property 3: Target-behavior matrix (§3.9 (a)-(i)) end-to-end via
# run_optimistic_integrate() -> _process_one_proposal(). Signals that CAN be
# controlled precisely (verified_sessions, tier) are asserted exactly; novelty
# is store-state-dependent (adrev-009), so novelty-sensitive cases assert the
# OUTCOME the §3.9 novelty produces (near-dup vs substantive for supersede;
# empty-store novelty=1.0 for the adds, whose outcomes are novelty-insensitive
# at the stated confidences).
# ---------------------------------------------------------------------------


class TargetBehaviorMatrixTests(ParityBase):
    _LONG = CANON

    def _elig_default_cfg(self) -> dict:
        ec = elig.default_eligibility()
        ec["enabled"] = True
        return ec

    def _write_config(self, elig_cfg: dict) -> None:
        p = da.dreaming_dir() / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        opt = dict(da.DEFAULT_OPTIMISTIC_INTEGRATION)
        opt["enabled"] = True
        opt["eligibility"] = elig_cfg
        p.write_text(json.dumps({"optimistic_integration": opt}), encoding="utf-8")

    def _day(self) -> str:
        return f"2026-mtx-{uuid.uuid4().hex[:8]}"

    def _pid(self, label: str) -> str:
        return f"{label}-{uuid.uuid4().hex[:10]}"

    def _session(self, *, slug: str, sentence: str, correction: bool, days_ago: float) -> str:
        sid = f"sess-{uuid.uuid4().hex[:10]}"
        base = datetime.now(timezone.utc) - timedelta(days=days_ago)
        turns: list = []
        if correction:
            turns.extend(tf.correction_sequence(
                request="Please reformat the config file.",
                correction="No, that's wrong, revert that change to the config entirely.",
            ))
        turns.append(tf.user_turn(sentence, human=True))
        path = ls.CLAUDE_PROJECTS_ROOT / f"proj-{uuid.uuid4().hex[:6]}" / f"{sid}.jsonl"
        tf.write_transcript(path, turns, session_id=sid, cwd=self._cwd_for(slug), base_ts=tf.iso(base))
        return sid

    def _add_row(self, *, pid, slug, sessions, confidence, content=None, claimed=None):
        content = content or self._LONG
        evidence = [{"session_id": s, "excerpt": self._LONG} for s in sessions]
        return {
            "id": pid, "kind": "learning_add", "project": slug, "target_id": None,
            "content": content, "type": "pitfall", "confidence": confidence,
            "prevalence": {"sessions": claimed if claimed is not None else len(sessions), "agents": 1},
            "evidence": evidence, "justification": "matrix", "fingerprint": f"fp-{pid}",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }

    def _run_day(self, rows: list) -> dict:
        self._write_config(self._elig_default_cfg())
        day = self._day()
        path = adp.proposals_dir() / f"{day}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
        summary = adp.run_optimistic_integrate(day)
        return {"day": day, "summary": summary}

    def _elig_audit_for(self, pid: str) -> dict | None:
        path = adp.apply_audit_path()
        if not path.is_file():
            return None
        found = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("audit_kind") == "eligibility" and rec.get("proposal_id") == pid:
                found = rec
        return found

    def _status(self, day: str, pid: str) -> str | None:
        for r in adp._read_jsonl(adp.proposals_dir() / f"{day}.jsonl"):
            if r.get("id") == pid:
                return r.get("status")
        return None

    # --- adds (a)-(f) ---

    def test_a_user_corrected_conf6_1sess_eligible_composite(self):
        slug = self._slug()
        sid = self._session(slug=slug, sentence=self._LONG, correction=True, days_ago=2)
        pid = self._pid("a")
        self._run_day([self._add_row(pid=pid, slug=slug, sessions=[sid], confidence=6)])
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "eligible")
        self.assertEqual(rec["decision_basis"], "composite")
        self.assertEqual(rec["evidence_tier"], "user-corrected")
        self.assertEqual(rec["verified_sessions"], 1)

    def test_b_inferred_conf6_3sess_eligible_composite(self):
        slug = self._slug()
        sids = [self._session(slug=slug, sentence=self._LONG, correction=False, days_ago=7) for _ in range(3)]
        pid = self._pid("b")
        self._run_day([self._add_row(pid=pid, slug=slug, sessions=sids, confidence=6)])
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "eligible")
        self.assertEqual(rec["decision_basis"], "composite")
        self.assertEqual(rec["evidence_tier"], "inferred")
        self.assertEqual(rec["verified_sessions"], 3)

    def test_c_inferred_conf6_1sess_skipped_origin(self):
        slug = self._slug()
        sid = self._session(slug=slug, sentence=self._LONG, correction=False, days_ago=2)
        pid = self._pid("c")
        self._run_day([self._add_row(pid=pid, slug=slug, sessions=[sid], confidence=6)])
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "skipped_origin")

    def test_d_inferred_conf6_2sess_10d_eligible_composite(self):
        slug = self._slug()
        sids = [self._session(slug=slug, sentence=self._LONG, correction=False, days_ago=10) for _ in range(2)]
        pid = self._pid("d")
        self._run_day([self._add_row(pid=pid, slug=slug, sessions=sids, confidence=6)])
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "eligible")
        self.assertEqual(rec["decision_basis"], "composite")
        self.assertEqual(rec["verified_sessions"], 2)

    def test_e_conf5_2sess_stale_skipped_composite(self):
        slug = self._slug()
        sids = [self._session(slug=slug, sentence=self._LONG, correction=False, days_ago=60) for _ in range(2)]
        pid = self._pid("e")
        self._run_day([self._add_row(pid=pid, slug=slug, sessions=sids, confidence=5)])
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "skipped_composite")
        self.assertIsNotNone(rec["margin"])

    def test_f_conf9_1sess_inferred_skipped_origin(self):
        slug = self._slug()
        sid = self._session(slug=slug, sentence=self._LONG, correction=False, days_ago=2)
        pid = self._pid("f")
        self._run_day([self._add_row(pid=pid, slug=slug, sessions=[sid], confidence=9, claimed=1)])
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "skipped_origin",
                         "inferred-once conf-9 add stays rejected exactly as today (§3.9 (f))")

    # --- eviction (g): legacy path bit-for-bit ---

    def test_g_eviction_takes_legacy_path_both_confidences(self):
        # conf8 contradict applies; conf6 contradict rejects on the floor -- and
        # the eligibility module is never consulted for evictions. Two DISTINCT
        # targets (+ filler heads) so the batch-anomaly eviction-concentration
        # check never fires and the eviction fraction cap stays comfortable.
        slug = self._slug()
        targets = []
        for i in range(2):
            e = ls.build_entry(type_="pattern", content=f"evict target content number {i} here", confidence=8)
            e["project"] = slug
            ls.append_entry(e, slug=slug)
            targets.append(e["id"])
        for i in range(4):  # filler live heads so live_count is healthy
            f = ls.build_entry(type_="pattern", content=f"unrelated filler head {i}", confidence=5)
            f["project"] = slug
            ls.append_entry(f, slug=slug)
        self._write_config(self._elig_default_cfg())
        day = self._day()
        hi, lo = self._pid("g-hi"), self._pid("g-lo")

        def _contradict(pid, conf, target_id):
            return {
                "id": pid, "kind": "learning_contradict", "project": slug, "target_id": target_id,
                "content": None, "type": None, "confidence": conf,
                "prevalence": {"sessions": 2, "agents": 1},
                "evidence": [{"session_id": "sess-x", "excerpt": "x"}],
                "justification": "t", "fingerprint": f"fp-{pid}",
                "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
            }
        path = adp.proposals_dir() / f"{day}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_contradict(hi, 8, targets[0]), sort_keys=True) + "\n")
            fh.write(json.dumps(_contradict(lo, 6, targets[1]), sort_keys=True) + "\n")
        with mock.patch.object(adp.eligibility, "evaluate_eligibility",
                               wraps=adp.eligibility.evaluate_eligibility) as spy:
            adp.run_optimistic_integrate(day)
        self.assertEqual(spy.call_count, 0, "evictions must never route through the composite")
        self.assertEqual(self._status(day, hi), "auto_applied")
        self.assertEqual(self._status(day, lo), "pending")

    # --- supersede (h)/(i): novelty-vs-target drives the split ---

    def _supersede_day(self, *, new_content, confidence, days_ago, n_sessions):
        slug = self._slug()
        target = ls.build_entry(type_="pattern", content=SUP_TARGET, confidence=8)
        target["project"] = slug
        ls.append_entry(target, slug=slug)
        sids = [self._session(slug=slug, sentence=new_content, correction=False, days_ago=days_ago)
                for _ in range(n_sessions)]
        pid = self._pid("sup")
        row = {
            "id": pid, "kind": "learning_supersede", "project": slug, "target_id": target["id"],
            "content": new_content, "type": "pattern", "confidence": confidence,
            "prevalence": {"sessions": n_sessions, "agents": 1},
            "evidence": [{"session_id": s, "excerpt": new_content} for s in sids],
            "justification": "matrix", "fingerprint": f"fp-{pid}",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }
        self._run_day([row])
        return pid

    def test_h_supersede_near_dup_skipped_composite(self):
        pid = self._supersede_day(new_content=SUP_NEARDUP, confidence=6, days_ago=5, n_sessions=2)
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "skipped_composite",
                         "§3.9 (h): near-dup conf6 refinement routes to pending")
        self.assertTrue(rec.get("near_duplicate_supersede"))

    def test_i_supersede_substantive_eligible_composite(self):
        pid = self._supersede_day(new_content=SUP_SUBSTANTIVE, confidence=6, days_ago=5, n_sessions=2)
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "eligible")
        self.assertEqual(rec["decision_basis"], "composite")
        self.assertFalse(rec.get("near_duplicate_supersede"))


if __name__ == "__main__":
    unittest.main()
