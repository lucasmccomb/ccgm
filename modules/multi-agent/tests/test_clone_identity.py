#!/usr/bin/env python3
"""Unit tests for clone_identity: path -> identity -> ports must be pinned.

This derivation is pure deterministic computation. It is exactly the thing
that must never be re-decided by an agent reading prose, so the mapping from
a clone path to its agent id and ports is nailed down here.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_TEST_DIR, "..", "lib")))
import clone_identity as ci  # noqa: E402


REGISTRY = {
    "_block_size": 16,
    "repos": {
        # 3 clones per workspace -- the case that broke: the default of 4
        # would have produced different ports for every w>=1 clone.
        "lem-work": {"frontend": 5221, "backend": 8835, "clones_per_workspace": 3},
        # No clones_per_workspace -> default 4.
        "evothos": {"frontend": 5173, "backend": 8787},
        "lem-photo": {"frontend": 5205, "backend": 8819},
    },
}


class TestParseClonePath(unittest.TestCase):
    def test_workspace_model(self):
        self.assertEqual(
            ci.parse_clone_path("/code/lem-work-workspaces/lem-work-w1/lem-work-w1-c0"),
            ("workspace", "lem-work", 1, 0),
        )
        self.assertEqual(
            ci.parse_clone_path("/code/evothos-workspaces/evothos-w3/evothos-w3-c2"),
            ("workspace", "evothos", 3, 2),
        )

    def test_flat_model(self):
        self.assertEqual(
            ci.parse_clone_path("/code/lem-photo-repos/lem-photo-2"),
            ("flat", "lem-photo", None, 2),
        )

    def test_multi_word_repo_name(self):
        self.assertEqual(
            ci.parse_clone_path(
                "/code/habitpro-ai-native-workspaces/habitpro-ai-native-w2"
                "/habitpro-ai-native-w2-c3"
            ),
            ("workspace", "habitpro-ai-native", 2, 3),
        )

    def test_rejects_wrong_layout(self):
        # Right basename, wrong parents: must not be adopted as a clone.
        self.assertIsNone(ci.parse_clone_path("/tmp/scratch/thing-w1-c0"))
        self.assertIsNone(
            ci.parse_clone_path("/code/lem-work-workspaces/wrong/lem-work-w1-c0")
        )
        self.assertIsNone(ci.parse_clone_path("/code/lem-photo-repos/notes"))

    def test_rejects_standalone_checkout(self):
        self.assertIsNone(ci.parse_clone_path("/code/nadaproof"))
        self.assertIsNone(ci.parse_clone_path("/code/ccgm"))


class TestDeriveIdentity(unittest.TestCase):
    def test_the_regression_case(self):
        """lem-work-w1-c0 is workspace 1 clone 0 -- never w0-c1/5222."""
        ident = ci.derive_identity(
            "/code/lem-work-workspaces/lem-work-w1/lem-work-w1-c0", REGISTRY
        )
        self.assertEqual(ident.agent_id, "agent-w1-c0")
        self.assertEqual(ident.workspace, 1)
        self.assertEqual(ident.clone, 0)
        self.assertEqual(ident.port_offset, 3)   # 1 * 3 + 0
        self.assertEqual(ident.frontend_port, 5224)
        self.assertEqual(ident.backend_port, 8838)

    def test_offset_uses_registry_clones_per_workspace(self):
        cases = {
            "lem-work-w0/lem-work-w0-c0": (0, 5221),
            "lem-work-w0/lem-work-w0-c2": (2, 5223),
            "lem-work-w1/lem-work-w1-c2": (5, 5226),
            "lem-work-w2/lem-work-w2-c0": (6, 5227),
            "lem-work-w3/lem-work-w3-c2": (11, 5232),
        }
        for suffix, (offset, frontend) in cases.items():
            ident = ci.derive_identity(f"/code/lem-work-workspaces/{suffix}", REGISTRY)
            self.assertEqual((ident.port_offset, ident.frontend_port), (offset, frontend), suffix)

    def test_default_clones_per_workspace_is_four(self):
        ident = ci.derive_identity(
            "/code/evothos-workspaces/evothos-w1/evothos-w1-c0", REGISTRY
        )
        self.assertEqual(ident.port_offset, 4)   # 1 * 4 + 0
        self.assertEqual(ident.frontend_port, 5177)

    def test_flat_offset_is_clone_number(self):
        ident = ci.derive_identity("/code/lem-photo-repos/lem-photo-3", REGISTRY)
        self.assertEqual(ident.agent_id, "agent-3")
        self.assertEqual(ident.port_offset, 3)
        self.assertEqual((ident.frontend_port, ident.backend_port), (5208, 8822))
        self.assertIsNone(ident.workspace)

    def test_unregistered_repo_gets_identity_but_no_ports(self):
        ident = ci.derive_identity(
            "/code/mystery-workspaces/mystery-w0/mystery-w0-c1", REGISTRY
        )
        self.assertEqual(ident.agent_id, "agent-w0-c1")
        self.assertFalse(ident.registered)
        self.assertIsNone(ident.frontend_port)
        self.assertIsNone(ident.backend_port)

    def test_block_overflow_flagged(self):
        ident = ci.derive_identity(
            "/code/evothos-workspaces/evothos-w4/evothos-w4-c0", REGISTRY
        )
        self.assertEqual(ident.port_offset, 16)
        self.assertTrue(ident.block_overflow)

    def test_unmanaged_path_returns_none(self):
        self.assertIsNone(ci.derive_identity("/code/nadaproof", REGISTRY))

    def test_derivation_is_pure(self):
        """Same path, same answer -- no disk, clock, or cwd involvement."""
        path = "/nonexistent/lem-work-workspaces/lem-work-w2/lem-work-w2-c1"
        first = ci.derive_identity(path, REGISTRY).to_dict()
        os.chdir(tempfile.gettempdir())
        self.assertEqual(ci.derive_identity(path, REGISTRY).to_dict(), first)


class TestRender(unittest.TestCase):
    def test_workspace_render_shape(self):
        ident = ci.derive_identity(
            "/code/lem-work-workspaces/lem-work-w1/lem-work-w1-c0", REGISTRY
        )
        values, _ = ci.parse_env_clone(ci.render_env_clone(ident))
        self.assertEqual(values, {
            "WORKSPACE_NUMBER": "1", "CLONE_NUMBER": "0", "AGENT_ID": "agent-w1-c0",
            "PORT_OFFSET": "3", "FRONTEND_PORT": "5224", "BACKEND_PORT": "8838",
        })

    def test_flat_render_omits_workspace_number(self):
        ident = ci.derive_identity("/code/lem-photo-repos/lem-photo-2", REGISTRY)
        values, _ = ci.parse_env_clone(ci.render_env_clone(ident))
        self.assertNotIn("WORKSPACE_NUMBER", values)
        self.assertEqual(values["AGENT_ID"], "agent-2")

    def test_unknown_keys_are_preserved(self):
        ident = ci.derive_identity("/code/lem-photo-repos/lem-photo-2", REGISTRY)
        existing = {"AGENT_ID": "agent-9", "ARGUS_SIM_UDID": "ABC-123"}
        values, _ = ci.parse_env_clone(ci.render_env_clone(ident, existing))
        self.assertEqual(values["ARGUS_SIM_UDID"], "ABC-123")
        self.assertEqual(values["AGENT_ID"], "agent-2")

    def test_legacy_keys_are_dropped(self):
        ident = ci.derive_identity(
            "/code/lem-work-workspaces/lem-work-w1/lem-work-w1-c0", REGISTRY
        )
        existing = {"WORKSPACE": "0", "CLONE": "1", "WORKSPACE_NUM": "0", "CLONE_NUM": "1"}
        values, _ = ci.parse_env_clone(ci.render_env_clone(ident, existing))
        for legacy in ci.LEGACY_KEYS:
            self.assertNotIn(legacy, values)

    def test_render_is_idempotent(self):
        ident = ci.derive_identity(
            "/code/lem-work-workspaces/lem-work-w2/lem-work-w2-c1", REGISTRY
        )
        once = ci.render_env_clone(ident)
        twice = ci.render_env_clone(ident, ci.parse_env_clone(once)[0])
        self.assertEqual(once, twice)
        self.assertEqual(ci.diff_env_clone(ident, ci.parse_env_clone(once)[0]), {})


class TestRepairOnDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clone = self.root / "lem-work-workspaces" / "lem-work-w1" / "lem-work-w1-c0"
        self.clone.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, text):
        (self.clone / ".env.clone").write_text(text)

    def _read(self):
        return ci.parse_env_clone((self.clone / ".env.clone").read_text())[0]

    def test_repairs_the_observed_drift(self):
        self._write(
            "# Auto-generated by workspace-setup. Do not edit.\n"
            "WORKSPACE_NUMBER=0\nCLONE_NUMBER=1\nAGENT_ID=agent-w0-c1\n"
            "PORT_OFFSET=1\nFRONTEND_PORT=5222\nBACKEND_PORT=8836\n"
        )
        result = ci.repair_clone(self.clone, REGISTRY)
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(self._read(), {
            "WORKSPACE_NUMBER": "1", "CLONE_NUMBER": "0", "AGENT_ID": "agent-w1-c0",
            "PORT_OFFSET": "3", "FRONTEND_PORT": "5224", "BACKEND_PORT": "8838",
        })

    def test_repair_is_idempotent(self):
        self._write("AGENT_ID=agent-w0-c1\n")
        ci.repair_clone(self.clone, REGISTRY)
        self.assertEqual(ci.repair_clone(self.clone, REGISTRY)["status"], "ok")

    def test_missing_file_is_created(self):
        self.assertEqual(ci.repair_clone(self.clone, REGISTRY)["status"], "repaired")
        self.assertEqual(self._read()["AGENT_ID"], "agent-w1-c0")

    def test_dry_run_does_not_write(self):
        self._write("AGENT_ID=agent-w0-c1\n")
        self.assertEqual(ci.repair_clone(self.clone, REGISTRY, dry_run=True)["status"], "repaired")
        self.assertEqual(self._read(), {"AGENT_ID": "agent-w0-c1"})

    def test_unregistered_repo_is_not_rewritten(self):
        clone = self.root / "mystery-workspaces" / "mystery-w0" / "mystery-w0-c0"
        clone.mkdir(parents=True)
        (clone / ".env.clone").write_text("AGENT_ID=agent-w9-c9\n")
        result = ci.repair_clone(clone, REGISTRY)
        self.assertEqual(result["status"], "unregistered")
        self.assertEqual((clone / ".env.clone").read_text(), "AGENT_ID=agent-w9-c9\n")

    def test_unmanaged_dir_is_untouched(self):
        other = self.root / "nadaproof"
        other.mkdir()
        self.assertEqual(ci.repair_clone(other, REGISTRY)["status"], "unmanaged")

    def test_repair_preserves_unknown_keys_on_disk(self):
        self._write("AGENT_ID=agent-w0-c1\nARGUS_SIM_UDID=DEAD-BEEF\n")
        ci.repair_clone(self.clone, REGISTRY)
        values = self._read()
        self.assertEqual(values["ARGUS_SIM_UDID"], "DEAD-BEEF")
        self.assertEqual(values["AGENT_ID"], "agent-w1-c0")


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _clone(self, rel, text=None):
        path = self.root / rel
        path.mkdir(parents=True)
        if text is not None:
            (path / ".env.clone").write_text(text)
        return path

    def test_discovers_both_models(self):
        self._clone("lem-work-workspaces/lem-work-w0/lem-work-w0-c0")
        self._clone("lem-photo-repos/lem-photo-1")
        self._clone("lem-photo-repos/README-notes")
        found = {p.name for p in ci.discover_clones([self.root])}
        self.assertEqual(found, {"lem-work-w0-c0", "lem-photo-1"})

    def test_reports_drift_without_writing(self):
        clone = self._clone(
            "lem-work-workspaces/lem-work-w1/lem-work-w1-c0", "AGENT_ID=agent-w0-c1\n"
        )
        report = ci.audit([self.root], REGISTRY)
        row = next(r for r in report["clones"] if r["path"] == str(clone))
        self.assertEqual(row["status"], "repaired")
        self.assertEqual((clone / ".env.clone").read_text(), "AGENT_ID=agent-w0-c1\n")

    def test_detects_cross_model_port_collision(self):
        # Flat clone 3 and workspace w1-c0 both derive frontend 5224.
        self._clone("lem-work-repos/lem-work-3")
        self._clone("lem-work-workspaces/lem-work-w1/lem-work-w1-c0")
        collisions = ci.audit([self.root], REGISTRY)["collisions"]
        ports = {(c["service"], c["port"]) for c in collisions}
        self.assertIn(("frontend_port", 5224), ports)
        self.assertIn(("backend_port", 8838), ports)

    def test_clean_tree_has_no_collisions(self):
        for c in range(3):
            self._clone(f"lem-work-workspaces/lem-work-w0/lem-work-w0-c{c}")
        report = ci.audit([self.root], REGISTRY)
        self.assertEqual(report["collisions"], [])


class TestWorkspaceTable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "lem-work-workspaces" / "lem-work-w1"
        for c in range(3):
            (self.ws / f"lem-work-w1-c{c}").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_table_matches_derivation(self):
        table = ci.workspace_table(self.ws, REGISTRY)
        self.assertIn("| c0 | lem-work-w1-c0/ | agent-w1-c0 | 5224 | 8838 |", table)
        self.assertIn("| c2 | lem-work-w1-c2/ | agent-w1-c2 | 5226 | 8840 |", table)

    def test_write_replaces_between_markers_and_keeps_prose(self):
        (self.ws / "CLAUDE.md").write_text(
            f"# Workspace 1\n\nintro\n\n## Structure\n\n{ci.TABLE_BEGIN}\n"
            f"| stale |\n{ci.TABLE_END}\n\n## Coordinator Role\n\nkeep me\n"
        )
        self.assertEqual(
            ci.write_workspace_table(self.ws, REGISTRY)["status"], "updated"
        )
        text = (self.ws / "CLAUDE.md").read_text()
        self.assertIn("| c1 | lem-work-w1-c1/ | agent-w1-c1 | 5225 | 8839 |", text)
        self.assertNotIn("| stale |", text)
        self.assertIn("intro", text)
        self.assertIn("keep me", text)

    def test_write_adopts_an_unmarked_table_under_structure(self):
        (self.ws / "CLAUDE.md").write_text(
            "# Workspace 1\n\n## Structure\n\n"
            "| Clone | Directory |\n|---|---|\n| c0 | old |\n\n## Coordinator Role\n\nkeep me\n"
        )
        self.assertEqual(
            ci.write_workspace_table(self.ws, REGISTRY)["status"], "updated"
        )
        text = (self.ws / "CLAUDE.md").read_text()
        self.assertIn(ci.TABLE_BEGIN, text)
        self.assertNotIn("| c0 | old |", text)
        self.assertIn("| c0 | lem-work-w1-c0/ | agent-w1-c0 | 5224 | 8838 |", text)
        self.assertIn("keep me", text)

    def test_write_is_idempotent(self):
        (self.ws / "CLAUDE.md").write_text("# W\n\n## Structure\n\n## Coordinator Role\n")
        ci.write_workspace_table(self.ws, REGISTRY)
        self.assertEqual(ci.write_workspace_table(self.ws, REGISTRY)["status"], "ok")

    def test_write_refuses_without_an_anchor(self):
        (self.ws / "CLAUDE.md").write_text("# Workspace 1\n\nno structure heading here\n")
        before = (self.ws / "CLAUDE.md").read_text()
        self.assertEqual(
            ci.write_workspace_table(self.ws, REGISTRY)["status"], "no-anchor"
        )
        self.assertEqual((self.ws / "CLAUDE.md").read_text(), before)

    def test_write_refuses_for_an_unregistered_repo(self):
        """Never trade a documented port for the word "unregistered"."""
        ws = Path(self.tmp.name) / "mystery-workspaces" / "mystery-w0"
        for c in range(2):
            (ws / f"mystery-w0-c{c}").mkdir(parents=True)
        original = (
            "# Workspace 0\n\n## Structure\n\n"
            "| Clone | Frontend Port |\n|---|---|\n| c0 | 5177 |\n\n## Coordinator Role\n"
        )
        (ws / "CLAUDE.md").write_text(original)
        result = ci.write_workspace_table(ws, REGISTRY)
        self.assertEqual(result["status"], "unregistered")
        self.assertEqual(result["repo"], "mystery")
        self.assertEqual((ws / "CLAUDE.md").read_text(), original)

    def test_write_reports_missing_file(self):
        self.assertEqual(
            ci.write_workspace_table(self.ws, REGISTRY)["status"], "missing"
        )

    def test_dry_run_does_not_write(self):
        (self.ws / "CLAUDE.md").write_text("# W\n\n## Structure\n\n## Coordinator Role\n")
        before = (self.ws / "CLAUDE.md").read_text()
        self.assertEqual(
            ci.write_workspace_table(self.ws, REGISTRY, dry_run=True)["status"], "updated"
        )
        self.assertEqual((self.ws / "CLAUDE.md").read_text(), before)


class TestRegistryLoading(unittest.TestCase):
    def test_missing_registry_is_empty_not_fatal(self):
        self.assertEqual(ci.load_registry("/nonexistent/port-registry.json"), {})

    def test_malformed_registry_is_empty_not_fatal(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
            path = fh.name
        try:
            self.assertEqual(ci.load_registry(path), {})
        finally:
            os.unlink(path)

    def test_real_shipped_registry_parses_and_derives(self):
        shipped = Path(_TEST_DIR).parent / "port-registry.json"
        registry = json.loads(shipped.read_text())
        self.assertIn("repos", registry)
        for repo, entry in registry["repos"].items():
            cpw = ci.clones_per_workspace(registry, repo)
            self.assertGreater(cpw, 0)
            ident = ci.derive_identity(
                f"/code/{repo}-workspaces/{repo}-w0/{repo}-w0-c0", registry
            )
            self.assertEqual(ident.frontend_port, entry["frontend"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
