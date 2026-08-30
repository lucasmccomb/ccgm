#!/usr/bin/env python3
"""
PreToolUse hook that HARD-BLOCKS direct implementation by an advisor-mode
orchestrator.

Why: an expensive orchestrator session (Fable/Opus) in advisor mode delegates
implementation to cheaper agents and reviews their work. Advisory-only "you
never implement" prompts demonstrably fail under pressure — the documented
failure mode is the orchestrator drifting into hands-on patching exactly at
friction moments (integration fixes, small "one-liners"). This gate makes the
posture mechanical: while this session's flag file exists, the MAIN agent
cannot mutate source; a denial is steering ("delegate this"), not an obstacle.

Classification: bypass-retained. Denials use exit 2 (hard_block semantics,
inlined so the hook is dependency-free). A JSON `permissionDecision: deny`
does not survive bypass mode (GitHub issue #39344); exit 2 does — same
contract as branch-guard.py.

State is PER SESSION: the flag is ~/.claude/advisor-mode/<session_id>, keyed
by the session_id every hook input carries (falling back to the
CLAUDE_CODE_SESSION_ID environment variable). One session's mode never binds
another's.

BLOCKS while this session's flag file exists, for the MAIN agent only:
  - Edit / MultiEdit / Write / NotebookEdit and the filesystem-MCP write
    tools, unless the target is an orchestrator work-product path (below)
  - Bash outside a default-deny allowlist of read-only inspection commands
    and orchestration verbs (read-only git; branch/worktree lifecycle;
    gh PR/issue/run management including merge), with redirection and
    scratch file-ops confined to the allowed write roots

ALLOWS:
  - Everything when this session's flag file is absent (mode off)
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
  - Input with no resolvable session id (fail open, the same asymmetric-drift
    class as the subagent discriminator: if the field ever disappears the
    guard goes inert and visibly denies nothing, instead of denying every
    session at once)

Command substitution (`$(...)`, backticks) is checked recursively: the
inner command runs through this same allowlist, so `echo "$(git rev-parse
HEAD)"` passes while `echo $(git commit -m x)` is denied. A backtick body is
unescaped first, the way the shell does before running it, so a nested
`\\`...\\`` is checked rather than read as literal text. A verified span
collapses to SUBST_PLACEHOLDER, which only a READ_ONLY command may take as an
argument — knowing the inner command is read-only says nothing about whether
its OUTPUT is a dangerous flag (`sed $(echo -i)`). Process substitution stays
denied outright. Shell grouping tokens (`{`, `(`) are structure, not
commands. A known dev-tool binary is allowed when its only arguments are
version/identity probes (`node -v`, `wrangler whoami`).

One quote/escape rule serves the whole file: scan_states() is the single
scanner, and a backslash escapes the next character everywhere except inside
single quotes. Earlier versions carried that rule in three places, and both
holes found in review were those copies disagreeing.

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

SESSION_ID_ENV = "CLAUDE_CODE_SESSION_ID"

# Session ids are uuids; anything else cannot name a flag file. Rejecting
# separators and dot-entries keeps the flag inside the state directory.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9._-]+")

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
    "exit", "return", ":",
}
# find and sort are allowed too, but through flag-checked branches in
# bash_segment_allowed (write/exec predicates and -o denied), not this set.

# Dev-tool binaries that run builds, installs, and deploys — allowed only as
# version/identity probes (every argument in PROBE_ARGS). `node build.js`,
# `pnpm install`, and `wrangler deploy` stay denied.
TOOL_PROBES = {
    "node", "npm", "npx", "pnpm", "yarn", "bun", "deno", "python", "python3",
    "pip", "pip3", "ruby", "gem", "bundle", "go", "cargo", "rustc", "java",
    "swift", "xcodebuild", "docker", "kubectl", "terraform", "wrangler",
    "supabase", "vercel", "netlify", "flyctl", "aws", "gcloud", "brew",
    "make", "claude", "code",
}
PROBE_ARGS = {"-v", "-V", "--version", "-version", "version", "--help", "-h",
              "whoami"}

# Redirection words inside a segment (`2>&1`, `2>/dev/null`, `>>out`). Their
# targets are path-checked by the redirect scan; the probe check ignores them
# so `wrangler --version 2>&1` still reads as a bare probe.
REDIRECT_TOKEN_RE = re.compile(r"^(\d*[<>]{1,2}&?\d*|&>{1,2})\S*$")

# Substitution recursion: how deep `$( $( ... ) )` may nest before the command
# is denied, and the word an already-checked substitution collapses to.
MAX_SUBST_DEPTH = 4
SUBST_PLACEHOLDER = "__SUBST__"
SUBST_PREFIX = "inside a substitution"

# The shell removes one level of backslash from a backtick body before
# running it, so a checker must do the same before reading the body.
BACKTICK_UNESCAPE_RE = re.compile(r"\\([\\`$])")

BACKTICK_HINT = (
    "Backticks inside a double-quoted argument are real command substitution "
    "to the shell, markdown or not — pass long bodies with `--body-file` "
    "(gh issue create / gh pr create)."
)

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


def session_id(data):
    """This call's session id: hook input first, environment as fallback."""
    for candidate in (data.get("session_id"), os.environ.get(SESSION_ID_ENV)):
        if not isinstance(candidate, str):
            continue
        candidate = candidate.strip()
        if candidate in (".", "..") or not SESSION_ID_RE.fullmatch(candidate):
            continue
        return candidate
    return None


def flag_path(sid):
    return os.path.join(
        os.path.expanduser("~"), ".claude", "advisor-mode", sid)


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
    if SUBST_PLACEHOLDER in raw_path:
        # The path is a substitution's output, so it cannot be resolved and
        # checked. Covers scratch-op arguments and redirect targets alike.
        return False
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


def scan_states(cmd):
    """Per-character `(quote, escaped)` for `cmd` — the file's only scanner.

    `quote` is the quoted span a character belongs to (None, `'` or `"`),
    delimiters included, so every character of `"a"` reports `"`. `escaped`
    is True for a backslash that escapes and for the character it escapes,
    under one rule: a backslash escapes the next character everywhere except
    inside single quotes, where nothing escapes.

    Yielded lazily so a caller that stops early pays only for what it read;
    find_substitutions, which needs to jump over spans, materializes a list.

    mask_quotes, find_substitutions and match_paren all read these states.
    Keeping the rule here is the point: when each of them carried its own
    copy, `mask_quotes` disagreed with the span finder about `\\"` and a
    trailing command went unchecked (issue #1012), and `match_backtick`
    disagreed about `\\`` and a nested command ran unchecked.
    """
    quote = None
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if quote == "'":
            yield ("'", False)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            yield (quote, True)
            yield (quote, True)
            i += 2
            continue
        if quote is None and c in ("'", '"'):
            quote = c
        elif c == quote:
            yield (quote, False)
            quote = None
            i += 1
            continue
        yield (quote, False)
        i += 1


def mask_quotes(cmd):
    """Replace quoted spans with spaces so metacharacter scans skip them.

    Single-quoted spans are fully masked (the shell treats them literally).
    Double-quoted spans are masked except an unescaped `$` or backtick, which
    still expand there and must stay visible to the scans. An escape pair is
    masked wherever it sits — an escaped `$` expands nothing.
    """
    out = []
    for c, (quote, escaped) in zip(cmd, scan_states(cmd)):
        if escaped or quote == "'":
            out.append(" ")
        elif quote == '"':
            out.append(c if c in ("$", "`") else " ")
        else:
            out.append(c)
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


def strip_grouping(segment):
    """Drop shell grouping tokens: `{ echo hi` reads as `echo hi`.

    `{` and `(` are structure, not commands. What the group contains is still
    checked as an ordinary segment, so `(git push)` reads as `git push` and
    stays denied; a segment that was pure structure (a lone `}`) empties out.
    """
    s = segment.strip()
    while s and s[0] in "{(":
        s = s[1:].lstrip()
    while s and s[-1] in "})":
        s = s[:-1].rstrip()
    return s


def probe_segment_allowed(words):
    """A dev-tool binary is allowed only as a version/identity probe."""
    args = [w for w in words[1:] if not REDIRECT_TOKEN_RE.match(w)]
    return bool(args) and all(a in PROBE_ARGS for a in args)


def bash_segment_allowed(segment):
    words = strip_env_assignments(strip_grouping(segment).split())
    if not words:
        return True
    first = words[0]
    first = first.rsplit("/", 1)[-1]  # /usr/bin/git → git
    if first not in READ_ONLY and any(SUBST_PLACEHOLDER in w for w in words):
        # A verified substitution collapses to a placeholder, and the shell
        # word-splits its output into real argv: `sed $(echo -i) …` IS
        # `sed -i …`. Checking the inner command read-only says nothing about
        # its output, so only plain read-only consumers may take one — every
        # branch below decides on literal argument text (`-i`, `-delete`,
        # `-o`, `-X`, a path) that a placeholder silently slips past.
        return False
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
    if first in TOOL_PROBES:
        return probe_segment_allowed(words)
    return False


def match_paren(cmd, start):
    """Index of the `)` closing a `$(` whose body starts at `start`, or None.

    The body is scanned on its own states: quoting restarts inside a
    substitution, so `echo $(echo ")")` ends at the last paren, not the
    quoted one.
    """
    body = cmd[start:]
    depth = 1
    for j, (c, (quote, escaped)) in enumerate(zip(body, scan_states(body))):
        # scan_states is lazy, so this stops at the closing paren rather than
        # scanning the rest of the command for every span.
        if escaped or quote is not None:
            continue
        if c == "(":
            depth += 1  # a nested $( counts through its own paren
        elif c == ")":
            depth -= 1
            if depth == 0:
                return start + j
    return None


def match_backtick(cmd, i):
    """Index of the backtick closing one opened before i, or None.

    Escaped backticks are skipped, because that is how the shell finds the
    end of the span — which means the body this delimits still holds those
    escapes. A caller must unescape the body (BACKTICK_UNESCAPE_RE) before
    checking it, or a nested `\\`…\\`` reads as literal text while the shell
    runs it.
    """
    n = len(cmd)
    while i < n:
        if cmd[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if cmd[i] == "`":
            return i
        i += 1
    return None


def find_substitutions(cmd):
    """Outermost `$(...)` and backtick spans in the RAW command.

    Returns (spans, unterminated); each span is
    (start, end, inner_start, inner_end, kind).

    This scans the raw string rather than the quote-masked one on purpose:
    masking drops the `(` inside double quotes, so a masked scan misses
    `"$(git commit -m x)"` — which the shell does expand.
    """
    spans = []
    states = list(scan_states(cmd))  # indexed: this loop jumps over spans
    i, n = 0, len(cmd)
    while i < n:
        quote, escaped = states[i]
        if escaped or quote == "'":
            i += 1  # nothing expands in single quotes, or when escaped
            continue
        c = cmd[i]
        if c == "$" and i + 1 < n and cmd[i + 1] == "(":
            end = match_paren(cmd, i + 2)
            if end is None:
                return spans, "dollar"
            kind = "arith" if cmd[i + 2:i + 3] == "(" else "dollar"
            spans.append((i, end + 1, i + 2, end, kind))
            i = end + 1
            continue
        if c == "`":
            end = match_backtick(cmd, i + 1)
            if end is None:
                return spans, "backtick"
            spans.append((i, end + 1, i + 1, end, "backtick"))
            i = end + 1
            continue
        i += 1
    return spans, None


def check_command(command, depth=0):
    """None when the command is allowed, else the denial reason."""
    masked = mask_quotes(command)
    if "<(" in masked or ">(" in masked:
        return ("process substitution is blocked for the main agent (the "
                "inner command cannot be verified read-only). Split the "
                "command, or delegate it.")
    spans, unterminated = find_substitutions(command)
    if unterminated == "dollar":
        return ("this command has an unterminated `$(` substitution, so its "
                "inner command cannot be checked. Split the command, or "
                "delegate it.")
    if unterminated == "backtick":
        return ("this command has an unpaired backtick, so the substitution "
                "it opens cannot be checked. " + BACKTICK_HINT)
    if spans and depth >= MAX_SUBST_DEPTH:
        return ("command substitution nests deeper than %d levels, past what "
                "this gate checks. Split the command, or delegate it."
                % MAX_SUBST_DEPTH)
    for start, end, inner_start, inner_end, kind in reversed(spans):
        if kind == "arith":
            return ("arithmetic expansion `$((...))` is not checked by this "
                    "gate — its body can carry a command substitution. "
                    "Compute the value another way, or delegate the command.")
        inner = command[inner_start:inner_end]
        if kind == "backtick":
            # The shell strips one level of backslash before running a
            # backtick body, so `\\`` in there opens a real nested
            # substitution. Unescape first or the nested command is read as
            # literal text and never checked.
            inner = BACKTICK_UNESCAPE_RE.sub(r"\1", inner)
        reason = check_command(inner, depth + 1)
        if reason is not None:
            if not reason.startswith(SUBST_PREFIX):
                reason = "%s %d level%s deep, %s" % (
                    SUBST_PREFIX, depth + 1, "" if depth == 0 else "s", reason)
            if kind == "backtick" and BACKTICK_HINT not in reason:
                reason = "%s %s" % (reason, BACKTICK_HINT)
            return reason
        # Checked and read-only: collapse it to a plain word so the outer
        # scan reads it as an ordinary argument.
        command = command[:start] + SUBST_PLACEHOLDER + command[end:]
    if spans:
        masked = mask_quotes(command)
    ok, target = redirects_allowed(command, masked)
    if not ok:
        return ("redirecting output into `%s` writes outside the "
                "orchestrator's work-product paths." % target)
    for segment in split_segments(command, masked):
        if not bash_segment_allowed(segment):
            return ("`%s` is not on the orchestrator's read-only/"
                    "orchestration allowlist." % segment.strip())
    return None


def check_bash(command):
    if re.search(r"\bADVISOR_DIRECT=1\b", command):
        return
    reason = check_command(command)
    if reason is not None:
        hard_block("advisor mode: %s %s" % (reason, RECIPE))


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
    sid = session_id(data)
    if not sid or not os.path.isfile(flag_path(sid)):
        sys.exit(0)  # mode off here (or no session id — fail open)
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
