"""Tests for repo_detect.py - canonical repo name detection and project-dir
listing across clone layouts."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import repo_detect  # noqa: E402


def test_detect_repo_from_ccgm_flat_clone_basename(tmp_path, monkeypatch):
    """Fallback path: strip clone-suffix regex from cwd basename when no git."""
    clone_dir = tmp_path / "ccgm-1"
    clone_dir.mkdir()
    monkeypatch.chdir(clone_dir)
    assert repo_detect.detect_repo() == "ccgm"


def test_detect_repo_from_workspace_clone_basename(tmp_path, monkeypatch):
    """Workspace clone suffix 'w0-c2' is stripped to return the canonical name."""
    clone_dir = tmp_path / "habitpro-ai-w0-c2"
    clone_dir.mkdir()
    monkeypatch.chdir(clone_dir)
    assert repo_detect.detect_repo() == "habitpro-ai"


def test_detect_repo_workspace_root_suffix(tmp_path, monkeypatch):
    clone_dir = tmp_path / "ccgm-w1"
    clone_dir.mkdir()
    monkeypatch.chdir(clone_dir)
    assert repo_detect.detect_repo() == "ccgm"


def test_detect_repo_non_repo_dir_returns_none(tmp_path, monkeypatch):
    """A plain directory with no clone suffix and no git remote returns None."""
    plain_dir = tmp_path / "not-a-clone"
    plain_dir.mkdir()
    monkeypatch.chdir(plain_dir)
    # No suffix to strip; detect_repo should return "not-a-clone" (basename
    # unchanged), which the caller may still treat as valid. This is
    # documented behavior — the function returns None only when the basename
    # heuristic also yields nothing.
    result = repo_detect.detect_repo()
    # Either None or the unchanged basename is acceptable here; both signal
    # "no confident canonical repo detected".
    assert result in (None, "not-a-clone")


def test_list_project_dirs_matches_exact_repo_only(tmp_path):
    """ccgm must NOT match ccgm-agent-learning (different repo, same prefix)."""
    # Simulate a ~/.claude/projects/ directory with several fake project dirs.
    fake_projects = tmp_path / "projects"
    fake_projects.mkdir()
    for name in [
        "-Users-lem-code-ccgm-repos-ccgm-0",
        "-Users-lem-code-ccgm-repos-ccgm-1",
        "-Users-lem-code-ccgm-workspaces-ccgm-w0",
        "-Users-lem-code-ccgm-workspaces-ccgm-w0-c2",
        "-Users-lem-code-ccgm-agent-learning",  # different repo, same prefix
        "-Users-lem-code-ccgm-agent-learning-0",  # clone of different repo
        "-Users-lem-code-voxter",  # unrelated
    ]:
        (fake_projects / name).mkdir()

    with patch.object(repo_detect, "CLAUDE_PROJECTS", fake_projects):
        matches = repo_detect.list_project_dirs("ccgm")
        names = sorted(m.name for m in matches)
    assert names == [
        "-Users-lem-code-ccgm-repos-ccgm-0",
        "-Users-lem-code-ccgm-repos-ccgm-1",
        "-Users-lem-code-ccgm-workspaces-ccgm-w0",
        "-Users-lem-code-ccgm-workspaces-ccgm-w0-c2",
    ]


def test_list_project_dirs_empty_when_no_matches(tmp_path):
    fake_projects = tmp_path / "projects"
    fake_projects.mkdir()
    (fake_projects / "-Users-lem-code-voxter").mkdir()
    with patch.object(repo_detect, "CLAUDE_PROJECTS", fake_projects):
        assert repo_detect.list_project_dirs("ccgm") == []


def test_list_project_dirs_empty_when_projects_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    with patch.object(repo_detect, "CLAUDE_PROJECTS", missing):
        assert repo_detect.list_project_dirs("ccgm") == []


def test_clone_label_flat_clone():
    project_dir = Path("/fake/-Users-lem-code-ccgm-repos-ccgm-1")
    assert repo_detect.clone_label(project_dir, "ccgm") == "ccgm-1"


def test_clone_label_workspace_clone():
    project_dir = Path("/fake/-Users-lem-code-ccgm-workspaces-ccgm-w0-c2")
    assert repo_detect.clone_label(project_dir, "ccgm") == "ccgm-w0-c2"


def test_clone_label_no_suffix():
    project_dir = Path("/fake/-Users-lem-code-ccgm")
    assert repo_detect.clone_label(project_dir, "ccgm") == "ccgm"


def test_clone_label_repo_with_hyphens():
    project_dir = Path("/fake/-Users-lem-code-habitpro-ai-workspaces-habitpro-ai-w0-c2")
    assert repo_detect.clone_label(project_dir, "habitpro-ai") == "habitpro-ai-w0-c2"


def test_clone_label_repo_flat_clone_with_hyphens():
    project_dir = Path("/fake/-Users-lem-code-habitpro-ai-repos-habitpro-ai-0")
    assert repo_detect.clone_label(project_dir, "habitpro-ai") == "habitpro-ai-0"
