#!/usr/bin/env python3
"""
PreToolUse hook that HARD-BLOCKS direct implementation by an advisor-mode
orchestrator.

Why: an expensive orchestrator session (Fable/Opus) in advisor mode delegates
implementation to cheaper agents and reviews their work. Advisory-only "you
never implement" prompts demonstrably fail under pressure — the documented
failure mode is the orchestrator drifting into hands-on patching exactly at
friction moments (integration fixes, small "one-liners"). This gate makes the
posture mechanical: while the flag file exists, the MAIN agent cannot mutate
source; a denial is steering ("delegate this"), not an obstacle.

Classification: bypass-retained. Denials use exit 2 (hard_block semantics,
inlined so the hook is dependency-free). A JSON `permissionDecision: deny`
does not survive bypass mode (GitHub issue #39344); exit 2 does — same
contract as branch-guard.py.

BLOCKS while ~/.claude/advisor-mode exists, for the MAIN agent only:
  - Edit / MultiEdit / Write / NotebookEdit and the filesystem-MCP write
    tools, unless the target is an orchestrator work-product path (below)
  - Bash outside a default-deny allowlist of read-only inspection commands
    and orchestration verbs (read-only git; branch/worktree lifecycle;
    gh PR/issue/run management including merge), with redirection and
    scratch file-ops confined to the allowed write roots

ALLOWS:
  - Everything when the flag file is absent (mode off)
  - SUBAGENT tool calls — their hook input carries a non-empty `agent_id`
    (and usually `agent_type`); the main agent's carries neither. These are
    documented common hook-input fields. Discriminator drift is asymmetric:
    if main-agent inputs ever start carrying the fields, the guard goes
    inert (fails open, visibly denies nothing); if subagent inputs ever
    stopped carrying them, subagents would be denied too — loud, immediate,
    and recoverable with /advisor off, never a silent misroute.
  - ADVISOR_DIRECT=1 — in the environment or inline on a Bash command —
    the one-off escape hatch (mirrors ALLOW_MAIN_COMMIT)
  - Orchestrator work-product writes: under ~/.claude/ (memory, todos, the
    flag file itself), the system temp roots (session scratchpads),
    ~/code/plans/ and ~/code/docs/ (specs, plans, research), any path inside
    a worktree checkout (/.claude/worktrees/, /.worktrees/), and plan-mode
    plan files (/.claude/plans/) which only the main agent may write
  - Unparseable input, unknown tools, missing paths (fail open — this is a
    workflow gate, not a data-loss guard)

KNOWN GAPS (documented in rules/advisor-mode.md): awk/heredoc bodies can
smuggle writes past the segment scan; wrapper commands are denied outright
rather than unwrapped (env/xargs/shells). Over-denial is the accepted
direction: the recipe in every denial names the delegation path.
"""

import json
import os
import re
import sys
import tempfile

FLAG_ENV = "CCGM_ADVISOR_FLAG"

FILE_TOOLS = {
    "Edit",
    "MultiEdit",
    "Write",
    "NotebookEdit",
    "mcp__filesystem__write_file",
    "mcp__filesystem__edit_file",
    "mcp__filesystem__move_file",
}

# First words allowed unconditionally: read-only inspection.
READ_ONLY = {
    "ls", "tree", "pwd", "wc", "du", "df", "file", "stat", "head", "tail",
    "cat", "less", "more", "grep", "egrep", "fgrep", "rg", "which",
    "whereis", "date", "diff", "cmp", "echo", "printf", "true", "false",
    "test", "[", "sleep", "jq", "uniq", "cut", "tr", "column",
    "basename", "dirname", "realpath", "readlink", "shasum", "sha256sum",
    "md5", "cksum", "strings", "nl", "od", "hexdump", "xxd", "uname",
    "hostname", "id", "whoami", "type", "man", "cd", "awk", "comm", "tac",
}
# find and sort are allowed too, but through flag-checked branches in
# bash_segment_allowed (write/exec predicates and -o denied), not this set.

# Scratch file-ops: allowed only when every path argument resolves inside an
# allowed write root.
SCRATCH_OPS = {"mkdir", "touch", "rm", "rmdir", "mv", "cp", "ln", "chmod"}

# find predicates that execute commands or write to disk (pure traversal
# stays allowed). Without this, `find -exec` is a general escape from the
# entire allowlist — the functional twin of the already-denied xargs.
FIND_WRITE_PREDICATES = {"-exec", "-execdir", "-ok", "-okdir", "-delete",
                         "-fprint", "-fprintf", "-fls", "-fprint0"}

# git subcommands allowed for every argument combination.
GIT_ALLOWED = {
    "status", "diff", "log", "show", "blame", "remote", "fetch", "ls-files",
    "ls-remote", "ls-tree", "rev-parse", "rev-list", "describe",
    "check-ignore", "shortlog", "reflog", "grep", "var", "version", "help",
    "switch", "pull", "worktree", "for-each-ref", "cat-file", "merge-base",
    "symbolic-ref", "show-ref", "name-rev",
}
GIT_BRANCH_MUTATORS = {"-d", "-D", "-m", "-M", "-f", "--delete", "--move",
                       "--force", "-c", "-C", "--copy"}

# gh: allowed (group, verb) pairs; verb None means the bare group.
# `gh pr create` is deliberately absent: the orchestrator's own work never
# becomes a PR (implementer subagents open PRs from their worktrees), and
# main-agent `git push` is denied anyway.
GH_ALLOWED = {
    "pr": {"list", "view", "checks", "diff", "status", "merge",
           "update-branch", "comment", "ready", "edit", "close", "reopen"},
    "issue": {"list", "view", "create", "comment", "close", "reopen",
              "edit", "status"},
    "run": {"list", "view", "watch", "rerun", "cancel"},
    "label": {"list", "create"},
    "repo": {"view"},
    "workflow": {"list", "view"},
    "release": {"list", "view"},
    "auth": {"status"},
    "search": None,  # every search verb is read-only
    "status": None,
}
GH_API_MUTATION_FLAGS = {"-X", "--method", "-f", "-F", "--field",
                         "--raw-field", "--input"}

RECIPE = (
    "advisor mode is ON — the orchestrator delegates instead of "
    "implementing. Dispatch an implementer subagent with a spec (objective, "
    "context, constraints, deliverable; isolation: worktree), or batch this "
    "into an existing unit. One-off hatch: ADVISOR_DIRECT=1. Turn the mode "
    "off with /advisor off."
)


def hard_block(reason):
    sys.stderr.write(reason + "\n")
    sys.exit(2)


def flag_path():
    return os.environ.get(FLAG_ENV) or os.path.join(
        os.path.expanduser("~"), ".claude", "advisor-mode")


def allowed_write_roots():
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, ".claude"),
        os.path.join(home, "code", "plans"),
        os.path.join(home, "code", "docs"),
    ]
    tmp = [tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders"]
    env_tmp = os.environ.get("TMPDIR")
    if env_tmp:
        tmp.append(env_tmp)
    return [os.path.realpath(r) for r in roots], [os.path.realpath(t) for t in tmp]


ALLOWED_SEGMENTS = ("/.claude/worktrees/", "/.worktrees/", "/.claude/plans/")


def path_allowed(raw_path):
    """True when the path is an orchestrator work-product location."""
    if not raw_path or not isinstance(raw_path, str):
        return True  # fail open: nothing to judge
    path = os.path.realpath(os.path.expanduser(
        os.path.expandvars(raw_path.strip().strip("'\""))))
    marked = path if path.endswith("/") else path + "/"
    if any(seg in marked for seg in ALLOWED_SEGMENTS):
        return True
    home_roots, tmp_roots = allowed_write_roots()
    home = os.path.realpath(os.path.expanduser("~"))
    if path == home or path.startswith(home + os.sep):
        # Under HOME, the HOME rules alone decide — even when HOME itself
        # sits under a temp root (the test sandbox does exactly that).
        return any(path == r or path.startswith(r + os.sep) for r in home_roots)
    return any(path == t or path.startswith(t + os.sep) for t in tmp_roots)


def mask_quotes(cmd):
    """Replace quoted spans with spaces so metacharacter scans skip them.

    Single-quoted spans are fully masked (the shell treats them literally).
    Double-quoted spans are masked except `$` and backtick, which still
    expand inside double quotes and must stay visible to the scans.
    """
    out = []
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == "\\" and i + 1 < n:
            out.append("  ")
            i += 2
            continue
        if c in ("'", '"'):
            quote = c
            out.append(" ")
            i += 1
            while i < n and cmd[i] != quote:
                keep = quote == '"' and cmd[i] in ("$", "`")
                out.append(cmd[i] if keep else " ")
                i += 1
            if i < n:
                out.append(" ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def split_segments(cmd, masked):
    """Split on unquoted && || ; | & and newline boundaries.

    Newlines and single `&` are command separators too — without them a
    second command hides in the first segment's tail. A `&` that is part of
    an fd-dup or `&>` redirect operator is not a separator.
    """
    i, n = 0, len(masked)
    cuts = []
    while i < n:
        two = masked[i:i + 2]
        if two in ("&&", "||"):
            cuts.append((i, i + 2))
            i += 2
            continue
        if masked[i] in (";", "|", "\n"):
            cuts.append((i, i + 1))
            i += 1
            continue
        if masked[i] == "&":
            prev_c = masked[i - 1] if i > 0 else ""
            next_c = masked[i + 1] if i + 1 < n else ""
            if prev_c in "<>" or next_c == ">":
                i += 1  # part of 2>&1 / <&- / &> — not a separator
                continue
            cuts.append((i, i + 1))
            i += 1
            continue
        i += 1
    segments = []
    start = 0
    for a, b in cuts:
        segments.append(cmd[start:a])
        start = b
    segments.append(cmd[start:])
    return [s for s in (seg.strip() for seg in segments) if s]


REDIRECT_RE = re.compile(r"(\d*>{1,2}&?\d*|&>{1,2})[ \t]*([^\s;|&<>]*)")


def redirects_allowed(cmd, masked):
    """Every >-family redirection target must be an allowed write path."""
    for m in REDIRECT_RE.finditer(masked):
        op = m.group(1)
        if "&" in op and op[-1].isdigit():
            continue  # fd duplication (2>&1, >&2)
        # Recover the raw (unmasked) target text at the same offsets.
        target = cmd[m.start(2):m.end(2)].strip()
        if not target and not m.group(2):
            # Target was entirely quoted; take the raw text after the operator.
            tail = cmd[m.end(1):].lstrip()
            target = tail.split()[0] if tail.split() else ""
        if not target or target.startswith("&"):
            continue
        if target in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"):
            continue
        if not path_allowed(target):
            return False, target
    return True, None


def strip_env_assignments(words):
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", words[0]):
        words = words[1:]
    return words


def git_segment_allowed(words):
    args = words[1:]
    # Skip global flags; -C and -c consume a value.
    while args and args[0].startswith("-"):
        if args[0] in ("-C", "-c") and len(args) > 1:
            args = args[2:]
        else:
            args = args[1:]
    if not args:
        return True  # bare `git` prints help
    sub, rest = args[0], args[1:]
    if sub == "checkout":
        # Branch movement only. `checkout -- <path>` (and the pathspec form)
        # restores files — a working-tree mutation, not orchestration.
        return "--" not in rest
    if sub in GIT_ALLOWED:
        return True
    if sub == "branch":
        return not any(w in GIT_BRANCH_MUTATORS for w in rest)
    if sub == "tag":
        return not rest or any(w in ("-l", "--list") for w in rest)
    if sub == "config":
        return bool(rest) and rest[0] in ("--get", "--get-all",
                                          "--get-regexp", "-l", "--list")
    return False


def gh_segment_allowed(words):
    args = words[1:]
    if not args:
        return True
    group, rest = args[0], args[1:]
    if group == "api":
        return not any(w in GH_API_MUTATION_FLAGS for w in rest)
    if group not in GH_ALLOWED:
        return False
    verbs = GH_ALLOWED[group]
    if verbs is None:
        return True
    verb = next((w for w in rest if not w.startswith("-")), None)
    return verb in verbs if verb else True  # bare group prints help


def scratch_op_allowed(words):
    for w in words[1:]:
        if w.startswith("-"):
            continue
        if not path_allowed(w):
            return False
    return True


def bash_segment_allowed(segment):
    words = strip_env_assignments(segment.split())
    if not words:
        return True
    first = words[0]
    first = first.rsplit("/", 1)[-1]  # /usr/bin/git → git
    if first == "sed":
        # -i in any form: bare, with attached suffix (-i.bak), inside a
        # single-dash flag cluster (-ni), or --in-place[=suffix].
        return not any(
            re.match(r"^-[a-zA-Z]*i", w) or w.startswith("--in-place")
            for w in words[1:])
    if first == "find":
        return not any(w in FIND_WRITE_PREDICATES for w in words[1:])
    if first == "sort":
        # `sort -o FILE` writes/truncates FILE — in bare, attached (-oFILE),
        # and clustered (-ro) forms, like the sed -i handling. `sort > FILE`
        # goes through the path-checked redirect scan instead.
        return not any(
            re.match(r"^-[a-zA-Z]*o", w) or w.startswith("--output")
            for w in words[1:])
    if first in READ_ONLY:
        return True
    if first in SCRATCH_OPS:
        return scratch_op_allowed(words)
    if first == "git":
        return git_segment_allowed(words)
    if first == "gh":
        return gh_segment_allowed(words)
    return False


def check_bash(command):
    if re.search(r"\bADVISOR_DIRECT=1\b", command):
        return
    masked = mask_quotes(command)
    if "$(" in masked or "`" in masked or "<(" in masked or ">(" in masked:
        hard_block(
            "advisor mode: command/process substitution is blocked for the "
            "main agent (the inner command cannot be verified read-only). "
            "Split the command, or delegate it. " + RECIPE)
    ok, target = redirects_allowed(command, masked)
    if not ok:
        hard_block(
            "advisor mode: redirecting output into `%s` writes outside the "
            "orchestrator's work-product paths. %s" % (target, RECIPE))
    for segment in split_segments(command, masked):
        if not bash_segment_allowed(segment):
            hard_block(
                "advisor mode: `%s` is not on the orchestrator's read-only/"
                "orchestration allowlist. %s" % (segment.strip(), RECIPE))


def check_file_tool(tool, tool_input):
    paths = []
    if tool == "mcp__filesystem__move_file":
        paths = [tool_input.get("source"), tool_input.get("destination")]
    else:
        paths = [tool_input.get("file_path") or tool_input.get("notebook_path")
                 or tool_input.get("path")]
    for p in paths:
        if p and not path_allowed(p):
            hard_block(
                "advisor mode: direct edits to `%s` are blocked for the main "
                "agent. %s" % (p, RECIPE))


def main():
    if not os.path.isfile(flag_path()):
        sys.exit(0)
    if os.environ.get("ADVISOR_DIRECT") == "1":
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail open
    if not isinstance(data, dict):
        sys.exit(0)
    if data.get("agent_id") or data.get("agent_type"):
        sys.exit(0)  # subagent call — the guard only binds the main agent
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        sys.exit(0)
    if tool in FILE_TOOLS:
        check_file_tool(tool, tool_input)
    elif tool == "Bash":
        command = tool_input.get("command")
        if command and isinstance(command, str):
            check_bash(command)  # non-string command: fail open like any
            # other malformed shape — never an uncaught traceback
    sys.exit(0)


if __name__ == "__main__":
    main()
