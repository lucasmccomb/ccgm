#!/usr/bin/env python3
"""
Tests for modules/dreaming/lib/loaded_context.py (#1098 Phase 3.3): the
deterministic loaded-context corpus, the similarity prefilter, and the
evidence-based fingerprint key.

Every root is a temp dir; nothing here reads the real ~/.claude.

Run with: python3 -m pytest modules/dreaming/tests/test_loaded_context.py -q
"""

from __future__ import annotations

import gzip
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

import loaded_context as lc  # noqa: E402

RULE_PARAGRAPH = (
    "No edits, staging, or commits while HEAD is on a repo's default branch. "
    "Branch first, then work. A PreToolUse hook hard-blocks these operations "
    "before the first edit rather than at commit time."
)


class TmpTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ccgm-loaded-context-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.claude = self.root / "claude"
        (self.claude / "rules").mkdir(parents=True)
        (self.claude / "hooks").mkdir()
        (self.claude / "projects").mkdir()
        self.roots = lc.Roots(
            claude_home=self.claude,
            rules_dir=self.claude / "rules",
            hooks_dir=self.claude / "hooks",
            projects_root=self.claude / "projects",
            proposals_dir=self.root / "proposals",
        )

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TokenizerTests(unittest.TestCase):
    def test_tokens_ignore_case_stopwords_and_plural_endings(self):
        self.assertEqual(lc.tokenize("The Hooks are BLOCKING commits"), lc.tokenize("hook block commit"))

    def test_hyphenated_and_dotted_terms_split_into_parts(self):
        self.assertIn("business", lc.tokenize("business-hours"))
        self.assertIn("deploy", lc.tokenize("./deploy.sh"))


class CorpusSourceTests(TmpTestCase):
    def test_rules_follow_symlinks_and_are_split_into_paragraphs_with_source_paths(self):
        real = self.write(
            self.root / "elsewhere" / "branch-guard.md",
            f"# Branch Guard\n\n{RULE_PARAGRAPH}\n\nSecond paragraph about escape hatches and allowlists.\n",
        )
        (self.claude / "rules" / "branch-guard.md").symlink_to(real)
        corpus = lc.build_corpus("repo", cwds=[], roots=self.roots)
        sources = {u.source for u in corpus.units if u.category == "rule"}
        self.assertEqual(sources, {str(self.claude / "rules" / "branch-guard.md")})
        self.assertTrue(any("default branch" in u.text for u in corpus.units))

    def test_claude_md_chain_walks_up_from_each_cwd_and_includes_user_file(self):
        top = self.write(self.root / "code" / "CLAUDE.md", "Workspace guidance paragraph about directories and clones for agents.")
        proj = self.write(self.root / "code" / "app" / "CLAUDE.md", "Project guidance paragraph about commit message format and branches.")
        user = self.write(self.claude / "CLAUDE.md", "Global guidance paragraph about communication style and terse output.")
        cwd = self.root / "code" / "app" / "pkg"
        cwd.mkdir(parents=True)
        corpus = lc.build_corpus("app", cwds=[str(cwd)], roots=self.roots)
        sources = {u.source for u in corpus.units if u.category == "claude_md"}
        self.assertEqual(sources, {str(top), str(proj), str(user)})

    def test_claude_md_walk_works_for_a_cwd_that_no_longer_exists(self):
        proj = self.write(self.root / "code" / "app" / "CLAUDE.md", "Project guidance paragraph about commit message format and branches.")
        gone = self.root / "code" / "app" / ".claude" / "worktrees" / "agent-gone"
        corpus = lc.build_corpus("app", cwds=[str(gone)], roots=self.roots)
        self.assertIn(str(proj), {u.source for u in corpus.units})

    def test_auto_memory_dir_is_found_through_the_encoded_cwd(self):
        cwd = "/work/some.repo/pkg"
        mem = self.write(
            self.claude / "projects" / lc.encode_cwd(cwd) / "memory" / "MEMORY.md",
            "- Never run git add -A in a clone because the env file is untracked.",
        )
        corpus = lc.build_corpus("repo", cwds=[cwd], roots=self.roots)
        self.assertEqual({u.source for u in corpus.units if u.category == "auto_memory"}, {str(mem)})

    def test_hook_python_strings_and_docstrings_become_units_but_code_does_not(self):
        hook = self.write(
            self.claude / "hooks" / "force-guard.py",
            '"""Blocks force deletes of git branches."""\n'
            "import sys\n"
            "def main():\n"
            '    print("Force-deleting a branch is blocked. Re-run the other segments without it.", file=sys.stderr)\n'
            "    return 2\n",
        )
        corpus = lc.build_corpus("repo", cwds=[], roots=self.roots)
        texts = [u.text for u in corpus.units if u.category == "hook"]
        self.assertTrue(any("Force-deleting a branch is blocked" in t for t in texts))
        self.assertFalse(any("import sys" in t for t in texts))
        self.assertEqual({u.source for u in corpus.units if u.category == "hook"}, {str(hook)})

    def test_installed_hook_names_lists_py_files_only(self):
        self.write(self.claude / "hooks" / "a-guard.py", "x = 1\n")
        self.write(self.claude / "hooks" / "a-guard.py.bak", "x = 1\n")
        self.assertEqual(lc.installed_hook_names(self.roots.hooks_dir), {"a-guard.py"})

    def test_store_rows_are_corpus_units_for_the_slug_and_global(self):
        rows = {"repo": [{"id": "abc123", "content": "Quote reserved words in SQL migrations before applying them."}], "_global": []}
        corpus = lc.build_corpus("repo", cwds=[], roots=self.roots, store_rows=rows)
        units = [u for u in corpus.units if u.category == "store"]
        self.assertEqual([u.source for u in units], ["store:repo:abc123"])

    def test_pending_and_rejected_proposals_are_units_and_gz_files_are_read(self):
        pdir = self.roots.proposals_dir
        pdir.mkdir()
        pending = {"id": "p1", "kind": "learning_add", "project": "repo", "status": "pending", "content": "Pending claim about retry backoff on rate limits for the API client."}
        rejected = {"id": "p2", "kind": "learning_add", "project": "repo", "status": "rejected", "content": "Rejected claim about stale cache invalidation in the build step."}
        accepted = {"id": "p3", "kind": "learning_add", "project": "repo", "status": "accepted", "content": "Accepted claim already living in the store as a row."}
        (pdir / "2026-09-30.jsonl").write_text(json.dumps(pending) + "\n", encoding="utf-8")
        with gzip.open(pdir / "2026-09-29.jsonl.gz", "wt", encoding="utf-8") as fh:
            fh.write(json.dumps(rejected) + "\n" + json.dumps(accepted) + "\n")
        corpus = lc.build_corpus("repo", cwds=[], roots=self.roots, today="2026-10-01")
        by_cat = {u.category: u.source for u in corpus.units}
        self.assertTrue(by_cat["pending_proposal"].endswith("2026-09-30.jsonl#p1"))
        self.assertTrue(by_cat["discarded_proposal"].endswith("2026-09-29.jsonl.gz#p2"))
        self.assertNotIn("p3", " ".join(u.source for u in corpus.units))

    def test_old_proposal_files_are_skipped_and_the_excluded_path_is_honored(self):
        pdir = self.roots.proposals_dir
        pdir.mkdir()
        row = {"id": "p1", "kind": "learning_add", "project": "repo", "status": "pending", "content": "Claim text that is long enough to be tokenised into a unit."}
        (pdir / "2026-01-01.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        (pdir / "2026-09-30.jsonl").write_text(json.dumps(dict(row, id="p2")) + "\n", encoding="utf-8")
        corpus = lc.build_corpus(
            "repo", cwds=[], roots=self.roots, today="2026-10-01", recent_days=30,
            exclude_proposal_path=pdir / "2026-09-30.jsonl",
        )
        self.assertEqual([u for u in corpus.units if u.category.endswith("_proposal")], [])

    def test_missing_roots_yield_an_empty_corpus_not_an_error(self):
        gone = self.root / "nope"
        roots = lc.Roots(
            claude_home=gone, rules_dir=gone / "rules", hooks_dir=gone / "hooks",
            projects_root=gone / "projects", proposals_dir=gone / "proposals",
        )
        self.assertEqual(lc.build_corpus("repo", cwds=["/x/y"], roots=roots).units, [])

    def test_roots_from_env_honor_the_claude_home_override(self):
        roots = lc.Roots.from_env({"CCGM_DREAMING_CLAUDE_HOME": str(self.claude)})
        self.assertEqual(roots.rules_dir, self.claude / "rules")
        self.assertEqual(roots.hooks_dir, self.claude / "hooks")
        self.assertEqual(roots.projects_root, self.claude / "projects")


class ProposalReaderTests(TmpTestCase):
    def test_read_proposal_rows_reads_plain_and_gzipped_files(self):
        pdir = self.root / "p"
        pdir.mkdir()
        (pdir / "2026-09-30.jsonl").write_text(json.dumps({"id": "a"}) + "\n\nnot json\n", encoding="utf-8")
        with gzip.open(pdir / "2026-09-29.jsonl.gz", "wt", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "b"}) + "\n")
        ids = [row["id"] for path in lc.proposal_files(pdir) for row in lc.read_proposal_rows(path)]
        self.assertEqual(sorted(ids), ["a", "b"])


class PendingForReduceTests(TmpTestCase):
    def test_pending_rows_for_the_wanted_projects_come_back_compact_newest_first_and_capped(self):
        pdir = self.root / "p"
        pdir.mkdir()
        old = {"id": "old", "kind": "learning_add", "project": "repo", "status": "pending", "content": "x" * 500, "evidence": [{"session_id": "s1", "excerpt": "e"}]}
        new = {"id": "new", "kind": "learning_verify", "project": "_global", "status": "pending", "target_id": "t1", "content": None, "evidence": []}
        other = {"id": "other", "kind": "learning_add", "project": "elsewhere", "status": "pending", "content": "y", "evidence": []}
        done = {"id": "done", "kind": "learning_add", "project": "repo", "status": "accepted", "content": "z", "evidence": []}
        (pdir / "2026-09-01.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")
        with gzip.open(pdir / "2026-09-02.jsonl.gz", "wt", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r) for r in (new, other, done)) + "\n")
        rows = lc.pending_proposals_for_reduce(pdir, ["repo", "_global"], limit=10)
        self.assertEqual([r["id"] for r in rows], ["new", "old"])
        self.assertEqual(len(rows[1]["content"]), 240)
        self.assertEqual(rows[1]["sessions"], ["s1"])
        self.assertEqual([r["id"] for r in lc.pending_proposals_for_reduce(pdir, ["repo", "_global"], limit=1)], ["new"])


class PrefilterTests(TmpTestCase):
    def corpus(self):
        self.write(self.claude / "rules" / "branch-guard.md", f"# Branch Guard\n\n{RULE_PARAGRAPH}\n")
        return lc.build_corpus("repo", cwds=[], roots=self.roots)

    def cand(self, content, *excerpts):
        return {
            "type": "pitfall", "content": content,
            "evidence": [{"session_id": "s1", "excerpt": e} for e in (excerpts or ("x",))],
            "occurrence_count": 1, "notes": None,
        }

    def test_paraphrase_of_a_rule_paragraph_is_dropped_already_encoded_with_its_path(self):
        corpus = self.corpus()
        para = self.cand(
            "Commits and edits are blocked while HEAD sits on the repo default branch; branch first, then work. "
            "A PreToolUse hook blocks these before the first edit."
        )
        kept, dropped = lc.prefilter_candidates([para], corpus, threshold=0.6, hook_names=set())
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["reason"], lc.ALREADY_ENCODED)
        self.assertEqual(dropped[0]["source"], str(self.claude / "rules" / "branch-guard.md"))
        self.assertEqual(dropped[0]["category"], "rule")

    def test_novel_candidate_passes_and_carries_top_snippets(self):
        corpus = self.corpus()
        novel = self.cand("The Postgres pooler drops idle connections after 30 seconds, so long migrations need keepalive settings.")
        kept, dropped = lc.prefilter_candidates([novel], corpus, threshold=0.6, hook_names=set())
        self.assertEqual(dropped, [])
        self.assertEqual(len(kept), 1)
        self.assertLessEqual(len(kept[0]["corpus_snippets"]), 3)

    def test_threshold_is_configurable(self):
        corpus = self.corpus()
        partial = self.cand("Edits are blocked on the default branch.")
        kept_hi, _ = lc.prefilter_candidates([partial], corpus, threshold=0.95, hook_names=set())
        _, dropped_lo = lc.prefilter_candidates([partial], corpus, threshold=0.2, hook_names=set())
        self.assertEqual(len(kept_hi), 1)
        self.assertEqual(len(dropped_lo), 1)

    def test_store_match_is_kept_so_the_reduce_can_verify_it(self):
        text = "The Postgres pooler drops idle connections after 30 seconds, so long migrations need keepalive settings."
        corpus = lc.build_corpus("repo", cwds=[], roots=self.roots, store_rows={"repo": [{"id": "abc123", "content": text}]})
        kept, dropped = lc.prefilter_candidates([self.cand(text)], corpus, threshold=0.6, hook_names=set())
        self.assertEqual(dropped, [])
        self.assertEqual(kept[0]["corpus_snippets"][0]["source"], "store:repo:abc123")

    def test_candidate_whose_evidence_is_all_installed_hook_errors_is_dropped(self):
        corpus = self.corpus()
        hook_err = "PreToolUse:Bash hook error: [$HOME/.claude/hooks/auto-approve-bash.py]: Force-deleting a branch is blocked."
        c = self.cand("Totally novel wording about squirrels and walnuts in the cache layer.", hook_err, hook_err + " again")
        kept, dropped = lc.prefilter_candidates([c], corpus, threshold=0.6, hook_names={"auto-approve-bash.py"})
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["reason"], lc.HOOK_FRICTION)

    def test_mixed_evidence_or_foreign_hook_is_not_dropped_as_hook_friction(self):
        corpus = self.corpus()
        hook_err = "PreToolUse:Bash hook error: [$HOME/.claude/hooks/auto-approve-bash.py]: blocked."
        mixed = self.cand("Totally novel wording about squirrels and walnuts in the cache layer.", hook_err, "the user said: use the cache layer")
        foreign = self.cand(
            "Totally novel wording about squirrels and walnuts in the cache layer.",
            "PreToolUse:Bash hook error: [/opt/vendor/hooks/other.py]: blocked.",
        )
        kept, dropped = lc.prefilter_candidates([mixed, foreign], corpus, threshold=0.6, hook_names={"auto-approve-bash.py"})
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, [])


class FingerprintKeyTests(unittest.TestCase):
    def test_key_basis_ignores_wording_order_and_session_order(self):
        ev_a = [
            {"session_id": "s2", "excerpt": "retry the deploy script after the pooler timeout"},
            {"session_id": "s1", "excerpt": "pooler timeout again"},
        ]
        ev_b = list(reversed(ev_a))
        a = lc.evidence_key_basis("pooler timeout kills the deploy script retry", ev_a)
        b = lc.evidence_key_basis("retry the deploy script: pooler timeout kills it", ev_b)
        self.assertEqual(a, b)

    def test_different_sessions_give_a_different_key(self):
        ev = [{"session_id": "s1", "excerpt": "pooler timeout"}]
        other = [{"session_id": "s9", "excerpt": "pooler timeout"}]
        self.assertNotEqual(lc.evidence_key_basis("pooler timeout", ev), lc.evidence_key_basis("pooler timeout", other))


if __name__ == "__main__":
    unittest.main()
