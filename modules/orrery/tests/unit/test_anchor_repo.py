"""Unit tests for anchor_repo.sh (plan Epic 2).

Hermetic: every test runs against throwaway git repos with local bare origins
under tempdirs, with HOME pointed at a tempdir so ~/code/orrery lands there
too. No network: credentialed remote URLs are rewritten to local paths via
git's url.<base>.insteadOf, and gh is stubbed on PATH.

The fake token below (ghp_fake) is safe to commit ONLY because this file
lives under a tests/ path, which the repo's Class-2 secret scan excludes.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[2]
SCRIPT = MODULE_DIR / "skills" / "orrery" / "scripts" / "anchor_repo.sh"

CRED_URL = "https://x-token:ghp_fake@github.com/o/r.git"
FAKE_TOKEN = "ghp_fake"


# --- helpers -----------------------------------------------------------------
def make_env(home, path_prepend=None):
    home.mkdir(parents=True, exist_ok=True)
    # Scrubbed environment: every inherited GIT_* var dropped (an exported
    # GIT_DIR/GIT_INDEX_FILE/GIT_WORK_TREE would redirect every git call the
    # script makes), then the fixed hermetic set restored below - mirrors the
    # enumerate-side git_env() fix (review finding 9).
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # Hermeticity: an ambient $ORRERY_HOME must not redirect the default-root
    # assertions; the override test sets it explicitly.
    env.pop("ORRERY_HOME", None)
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(home / "gitconfig-does-not-exist"),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.com",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.com",
        }
    )
    if path_prepend is not None:
        env["PATH"] = str(path_prepend) + os.pathsep + env["PATH"]
    return env


def git(repo, env, *args):
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def make_repo(path, env, origin=None):
    """Init a repo at `path` on branch main with one commit. When `origin` is
    a path, create a bare origin there and push main to it."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(path)],
        env=env,
        check=True,
        capture_output=True,
    )
    (path / "hello.txt").write_text("hello\n")
    git(path, env, "add", "hello.txt")
    git(path, env, "commit", "-q", "-m", "c1")
    if origin is not None:
        # -b main: a bare init without it leaves HEAD dangling at
        # refs/heads/master, and a dangling remote HEAD makes
        # `remote set-head --auto` unable to resolve anything.
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(origin)],
            env=env,
            check=True,
            capture_output=True,
        )
        git(path, env, "remote", "add", "origin", str(origin))
        git(path, env, "push", "-q", "origin", "main")
    return path


def run_anchor(env, *args, cwd=None):
    return subprocess.run(
        ["bash", str(SCRIPT)] + [str(a) for a in args],
        env=env,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )


def anchor_json(result):
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, "expected single-line JSON, got: %r" % result.stdout
    return json.loads(lines[0])


def worktree_count(repo, env):
    out = git(repo, env, "worktree", "list", "--porcelain")
    return out.count("worktree ")


def stub_gh(home, body):
    """Install a gh stub on a PATH-prepend dir; returns the dir."""
    stub_dir = home / "stub-bin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    gh = stub_dir / "gh"
    gh.write_text("#!/bin/sh\n" + body + "\n")
    gh.chmod(0o755)
    return stub_dir


def stub_git_subcommand_failure(home, subcommand, exit_code):
    """Install a git stub on a PATH-prepend dir that exits `exit_code` when
    invoked as `git -C <repo> <subcommand> ...` and execs the real git for
    every other invocation. Returns the stub dir. Used to force a specific
    git subcommand to fail without corrupting repo state (reviews finding
    7a/7b need a failure the real git binary won't otherwise produce)."""
    stub_dir = home / "stub-bin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    real_git = shutil.which("git")
    git_stub = stub_dir / "git"
    git_stub.write_text(
        "#!/bin/sh\n"
        'if [ "$3" = "%s" ]; then\n'
        "  exit %d\n"
        "fi\n"
        'exec "%s" "$@"\n' % (subcommand, exit_code, real_git)
    )
    git_stub.chmod(0o755)
    return stub_dir


# --- success path ------------------------------------------------------------
def test_success_fields_worktree_and_teardown(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=tmp_path / "origin.git")

    data = anchor_json(run_anchor(env, repo))
    assert set(data) == {
        "repo_path",
        "remote_url",
        "default_ref",
        "anchor_sha",
        "worktree",
        "slug",
        "behind",
        "dirty",
        "no_remote",
        "visibility",
    }
    assert data["repo_path"] == str(repo.resolve())
    assert data["remote_url"] == str(tmp_path / "origin.git")
    assert data["default_ref"] == "origin/main"
    assert data["slug"] == "repo"
    assert data["behind"] == 0
    assert data["dirty"] is False
    assert data["no_remote"] is False
    # A local file remote is not GitHub: visibility falls back to unknown.
    assert data["visibility"] == "unknown"

    expected_sha = git(repo, env, "rev-parse", "origin/main").strip()
    assert data["anchor_sha"] == expected_sha

    wt = Path(data["worktree"])
    assert wt.is_dir()
    assert git(wt, env, "rev-parse", "HEAD").strip() == expected_sha
    assert worktree_count(repo, env) == 2

    result = run_anchor(env, "--teardown", repo, wt)
    assert result.returncode == 0
    assert worktree_count(repo, env) == 1
    assert not wt.exists()


def test_dirty_repo_flagged(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=tmp_path / "origin.git")
    (repo / "hello.txt").write_text("changed\n")

    data = anchor_json(run_anchor(env, repo))
    assert data["dirty"] is True
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_behind_counts_commits(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=tmp_path / "origin.git")
    (repo / "second.txt").write_text("second\n")
    git(repo, env, "add", "second.txt")
    git(repo, env, "commit", "-q", "-m", "c2")
    git(repo, env, "push", "-q", "origin", "main")
    remote_tip = git(repo, env, "rev-parse", "HEAD").strip()
    git(repo, env, "reset", "-q", "--hard", "HEAD~1")

    data = anchor_json(run_anchor(env, repo))
    assert data["behind"] == 1
    # The anchor pins the fetched origin tip, not the stale local HEAD.
    assert data["anchor_sha"] == remote_tip
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_stale_origin_head_refreshed_after_default_branch_rename(tmp_path):
    """Review finding 1 / probe P5: the remote renamed its default branch
    (main -> trunk with one extra commit, old branch deleted) after the local
    clone recorded origin/HEAD. The anchor must refresh the symref after the
    fetch and pin the NEW default's tip - never the dead branch's old tip."""
    env = make_env(tmp_path / "home")
    origin = tmp_path / "origin.git"
    repo = make_repo(tmp_path / "repo", env, origin=origin)
    git(repo, env, "fetch", "-q", "origin")
    git(repo, env, "remote", "set-head", "origin", "--auto")
    assert (
        git(repo, env, "symbolic-ref", "refs/remotes/origin/HEAD").strip()
        == "refs/remotes/origin/main"
    )

    # Remote-side rename: trunk continues from main plus one commit; main dies.
    (repo / "second.txt").write_text("second\n")
    git(repo, env, "add", "second.txt")
    git(repo, env, "commit", "-q", "-m", "c2")
    git(repo, env, "push", "-q", "origin", "HEAD:refs/heads/trunk")
    new_tip = git(repo, env, "rev-parse", "HEAD").strip()
    old_tip = git(repo, env, "rev-parse", "HEAD~1").strip()
    git(repo, env, "reset", "-q", "--hard", "HEAD~1")
    git(origin, env, "symbolic-ref", "HEAD", "refs/heads/trunk")
    git(origin, env, "branch", "-D", "main")

    data = anchor_json(run_anchor(env, repo))
    assert data["default_ref"] == "origin/trunk"
    assert data["anchor_sha"] == new_tip
    assert data["anchor_sha"] != old_tip
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_no_remote_supported_and_flagged(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=None)

    data = anchor_json(run_anchor(env, repo))
    assert data["no_remote"] is True
    assert data["remote_url"] == ""
    assert data["default_ref"] == "main"
    assert data["visibility"] == "unknown"
    assert data["anchor_sha"] == git(repo, env, "rev-parse", "HEAD").strip()
    run_anchor(env, "--teardown", repo, data["worktree"])


# --- error paths -------------------------------------------------------------
def test_nonexistent_path_exits_2_with_json_error(tmp_path):
    env = make_env(tmp_path / "home")
    result = run_anchor(env, tmp_path / "does-not-exist")
    assert result.returncode == 2
    assert "error" in json.loads(result.stdout.strip())


def test_non_repo_dir_exits_2_with_json_error(tmp_path):
    env = make_env(tmp_path / "home")
    plain = tmp_path / "plain"
    plain.mkdir()
    result = run_anchor(env, plain)
    assert result.returncode == 2
    assert "error" in json.loads(result.stdout.strip())


def test_control_char_repo_path_exits_2_with_valid_json(tmp_path):
    """Review finding 2 / probe P1: a repo dir with an embedded newline must
    never produce invalid JSON with exit 0. It is rejected up front, and the
    error object stays parseable because the offending path is not echoed."""
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "bad\nname", env, origin=None)

    result = run_anchor(env, repo)
    assert result.returncode == 2
    data = json.loads(result.stdout.strip())
    assert "error" in data
    assert worktree_count(repo, env) == 1


def test_control_char_tmpdir_worktree_path_exits_2_with_valid_json(tmp_path):
    """Delta re-review residual: a TMPDIR containing a control character
    flows into the worktree path via mktemp and must not reproduce the
    exit-0-with-invalid-JSON shape the repo-path guard closed (finding 2)."""
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=None)
    bad_tmpdir = tmp_path / "bad\ntmp"
    bad_tmpdir.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(bad_tmpdir)

    result = run_anchor(env, repo)
    assert result.returncode == 2
    data = json.loads(result.stdout.strip())
    assert "error" in data
    assert worktree_count(repo, env) == 1


def test_unreadable_repo_dir_exits_2_with_json_error(tmp_path):
    """Review finding 6: cd into a repo dir with no read/execute permission
    must fail through emit_error (exit 2 + JSON), not abort via set -e with a
    bare non-2 exit and no JSON."""
    env = make_env(tmp_path / "home")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        result = run_anchor(env, locked)
        assert result.returncode == 2
        data = json.loads(result.stdout.strip())
        assert "error" in data
    finally:
        locked.chmod(0o755)


def test_dash_prefixed_repo_arg_not_parsed_as_cd_option(tmp_path):
    """Review finding 6: a repo dir name starting with `-` must not be read
    by `cd` as an option flag; `cd --` fixes this."""
    env = make_env(tmp_path / "home")
    workdir = tmp_path / "somewhere"
    workdir.mkdir()
    repo = make_repo(workdir / "-dashrepo", env, origin=None)

    result = run_anchor(env, "-dashrepo", cwd=workdir)
    data = anchor_json(result)
    assert data["repo_path"] == str(repo.resolve())
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_mktemp_failure_exits_2_with_json_error(tmp_path):
    """Review finding 6: an unwritable TMPDIR makes mktemp fail; the run must
    fail through emit_error, not abort via set -e with a bare non-2 exit."""
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=None)
    readonly_tmp = tmp_path / "readonly-tmp"
    readonly_tmp.mkdir()
    readonly_tmp.chmod(0o500)
    env["TMPDIR"] = str(readonly_tmp)
    try:
        result = run_anchor(env, repo)
        assert result.returncode == 2
        data = json.loads(result.stdout.strip())
        assert "error" in data
        assert worktree_count(repo, env) == 1
    finally:
        readonly_tmp.chmod(0o700)


def test_git_config_read_failure_exits_2_with_json_error(tmp_path):
    """Review finding 7a: a genuine git-config read failure (distinct from
    "no origin configured", exit 1) must fail loudly through emit_error, not
    silently fall into the no-remote path."""
    env_home = tmp_path / "home"
    stub = stub_git_subcommand_failure(env_home, "config", 3)
    env = make_env(env_home, path_prepend=stub)
    repo = make_repo(tmp_path / "repo", env, origin=None)

    result = run_anchor(env, repo)
    assert result.returncode == 2
    data = json.loads(result.stdout.strip())
    assert "error" in data


def test_rev_list_failure_emits_behind_null_not_fabricated_zero(tmp_path):
    """Review finding 7b: a rev-list failure must never fabricate behind: 0 -
    it must be reported as null so callers can tell the count is unknown."""
    env_home = tmp_path / "home"
    stub = stub_git_subcommand_failure(env_home, "rev-list", 128)
    env = make_env(env_home, path_prepend=stub)
    repo = make_repo(tmp_path / "repo", env, origin=None)

    data = anchor_json(run_anchor(env, repo))
    assert data["behind"] is None
    run_anchor(env, "--teardown", repo, data["worktree"])


# --- slug rule (security C7) -------------------------------------------------
def test_slug_sanitizes_messy_name(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "My Repo (v2)!", env, origin=None)
    data = anchor_json(run_anchor(env, repo))
    assert data["slug"] == "my_repo_v2"
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_slug_unsanitizable_unicode_exits_2(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "日本語", env, origin=None)
    result = run_anchor(env, repo)
    assert result.returncode == 2
    assert "error" in json.loads(result.stdout.strip())
    # The failure happens before any worktree is created.
    assert worktree_count(repo, env) == 1


def test_slug_200_char_name_truncated_to_64(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / ("a" * 200), env, origin=None)
    data = anchor_json(run_anchor(env, repo))
    assert data["slug"] == "a" * 64
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_slug_relative_traversal_arg_uses_basename_only(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "evil", env, origin=None)
    workdir = tmp_path / "somewhere"
    workdir.mkdir()

    result = run_anchor(env, "../evil", cwd=workdir)
    data = anchor_json(result)
    assert data["slug"] == "evil"
    assert data["repo_path"] == str(repo.resolve())
    # The output dir stays inside ~/code/orrery - no traversal.
    out_dir = tmp_path / "home" / "code" / "orrery" / "evil"
    assert out_dir.is_dir()
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_slug_absolute_path_shaped_arg_uses_basename_only(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "abs-shaped", env, origin=None)
    data = anchor_json(run_anchor(env, repo.resolve()))
    assert data["slug"] == "abs_shaped"
    run_anchor(env, "--teardown", repo, data["worktree"])


# --- credential stripping (security C6) --------------------------------------
def test_credentialed_remote_url_stripped_in_output(tmp_path):
    env_home = tmp_path / "home"
    stub = stub_gh(env_home, "echo true")
    env = make_env(env_home, path_prepend=stub)
    repo = make_repo(tmp_path / "repo", env, origin=None)
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)],
        env=env,
        check=True,
        capture_output=True,
    )
    git(repo, env, "push", "-q", str(bare), "main")
    git(repo, env, "remote", "add", "origin", CRED_URL)
    # Rewrite the credentialed URL to the local bare so fetch succeeds with no
    # network while `git remote get-url origin` still reports the raw URL.
    git(repo, env, "config", "url.%s.insteadOf" % bare, CRED_URL)

    result = run_anchor(env, repo)
    data = anchor_json(result)
    assert data["remote_url"] == "https://github.com/o/r.git"
    assert FAKE_TOKEN not in result.stdout
    assert FAKE_TOKEN not in result.stderr
    # github.com remote + stubbed `gh` answering isPrivate=true.
    assert data["visibility"] == "private"
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_uppercase_scheme_credential_stripped(tmp_path):
    """Review finding 3 / probe P2: URL schemes are case-insensitive per RFC
    3986, so HTTPS:// userinfo must strip exactly like https://."""
    cred_upper = "HTTPS://x-token:ghp_fake@github.com/o/r.git"
    env_home = tmp_path / "home"
    stub = stub_gh(env_home, "exit 1")
    env = make_env(env_home, path_prepend=stub)
    repo = make_repo(tmp_path / "repo", env, origin=None)
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)],
        env=env,
        check=True,
        capture_output=True,
    )
    git(repo, env, "push", "-q", str(bare), "main")
    git(repo, env, "remote", "add", "origin", cred_upper)
    git(repo, env, "config", "url.%s.insteadOf" % bare, cred_upper)

    result = run_anchor(env, repo)
    data = anchor_json(result)
    assert data["remote_url"] == "HTTPS://github.com/o/r.git"
    assert FAKE_TOKEN not in result.stdout
    assert FAKE_TOKEN not in result.stderr
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_credential_never_leaks_on_fetch_failure(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=None)
    git(repo, env, "remote", "add", "origin", CRED_URL)
    git(
        repo,
        env,
        "config",
        "url.%s.insteadOf" % (tmp_path / "no-such-remote"),
        CRED_URL,
    )

    result = run_anchor(env, repo)
    assert result.returncode == 2
    assert "error" in json.loads(result.stdout.strip())
    assert FAKE_TOKEN not in result.stdout
    assert FAKE_TOKEN not in result.stderr
    assert worktree_count(repo, env) == 1


# --- visibility fallback -----------------------------------------------------
def test_visibility_public_via_gh(tmp_path):
    env_home = tmp_path / "home"
    stub = stub_gh(env_home, "echo false")
    env = make_env(env_home, path_prepend=stub)
    repo = make_repo(tmp_path / "repo", env, origin=None)
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)],
        env=env,
        check=True,
        capture_output=True,
    )
    git(repo, env, "push", "-q", str(bare), "main")
    git(repo, env, "remote", "add", "origin", "https://github.com/o/r.git")
    git(repo, env, "config", "url.%s.insteadOf" % bare, "https://github.com/o/r.git")

    data = anchor_json(run_anchor(env, repo))
    assert data["visibility"] == "public"
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_visibility_unknown_when_gh_fails(tmp_path):
    env_home = tmp_path / "home"
    stub = stub_gh(env_home, "exit 1")
    env = make_env(env_home, path_prepend=stub)
    repo = make_repo(tmp_path / "repo", env, origin=None)
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)],
        env=env,
        check=True,
        capture_output=True,
    )
    git(repo, env, "push", "-q", str(bare), "main")
    git(repo, env, "remote", "add", "origin", "https://github.com/o/r.git")
    git(repo, env, "config", "url.%s.insteadOf" % bare, "https://github.com/o/r.git")

    result = run_anchor(env, repo)
    data = anchor_json(result)
    # gh failure is never fatal: the run succeeds with visibility unknown.
    assert data["visibility"] == "unknown"
    run_anchor(env, "--teardown", repo, data["worktree"])


# --- output dir (security R4) ------------------------------------------------
def test_output_dir_created_chmod_700(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=None)
    data = anchor_json(run_anchor(env, repo))
    out_dir = tmp_path / "home" / "code" / "orrery" / "repo"
    assert out_dir.is_dir()
    assert stat.S_IMODE(out_dir.stat().st_mode) == 0o700
    run_anchor(env, "--teardown", repo, data["worktree"])


def test_output_dir_honors_orrery_home_override(tmp_path):
    """Risk adrev2-014: $ORRERY_HOME overrides the output root without editing
    the module. The dir is created under the override (chmod 700) and the
    default ~/code/orrery root is NOT created."""
    env = make_env(tmp_path / "home")
    custom = tmp_path / "custom-root"
    env["ORRERY_HOME"] = str(custom)
    repo = make_repo(tmp_path / "repo", env, origin=None)

    data = anchor_json(run_anchor(env, repo))
    out_dir = custom / "repo"
    assert out_dir.is_dir()
    assert stat.S_IMODE(out_dir.stat().st_mode) == 0o700
    assert not (tmp_path / "home" / "code" / "orrery" / "repo").exists()
    run_anchor(env, "--teardown", repo, data["worktree"])


# --- teardown contract (plan 3.1 stage 6) ------------------------------------
def test_teardown_idempotent_and_never_fatal(tmp_path):
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=None)
    data = anchor_json(run_anchor(env, repo))
    wt = data["worktree"]

    assert run_anchor(env, "--teardown", repo, wt).returncode == 0
    # Second teardown of the same worktree: idempotent.
    assert run_anchor(env, "--teardown", repo, wt).returncode == 0
    # Teardown against a repo path that does not exist: never fatal.
    assert (
        run_anchor(env, "--teardown", tmp_path / "gone", tmp_path / "gone-wt").returncode
        == 0
    )
    assert worktree_count(repo, env) == 1


def test_mid_run_failure_tears_down_worktree(tmp_path):
    """Simulated mid-run failure AFTER the worktree exists: make the output
    dir uncreatable so the run fails late, then assert the error path called
    teardown and `git worktree list` is clean."""
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=None)
    # ~/code exists as a FILE, so mkdir -p ~/code/orrery/{slug} must fail.
    (tmp_path / "home" / "code").write_text("not a directory\n")

    result = run_anchor(env, repo)
    assert result.returncode == 2
    assert "error" in json.loads(result.stdout.strip())
    assert worktree_count(repo, env) == 1


def test_stale_worktree_metadata_pruned_first(tmp_path):
    """A prior run killed before teardown leaves stale metadata; the prune-
    first rule means the next anchor still succeeds."""
    env = make_env(tmp_path / "home")
    repo = make_repo(tmp_path / "repo", env, origin=None)
    stale = tmp_path / "stale-wt"
    git(repo, env, "worktree", "add", "--detach", str(stale))
    shutil.rmtree(stale)

    data = anchor_json(run_anchor(env, repo))
    assert Path(data["worktree"]).is_dir()
    run_anchor(env, "--teardown", repo, data["worktree"])
    assert worktree_count(repo, env) == 1
