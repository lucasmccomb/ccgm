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

Every check reads the word bash will actually pass, not the characters as
typed. normalize_word() removes quotes, joins adjacent spans (`-''i` is
`-i`), drops backslash escapes, and decodes `$'...'` bodies, so a flag hidden
behind quoting reaches the flag scans intact (issue #1017). One normalizer
feeds every argument check; there is no per-check special case per carrier.

Expansion is not modeled; it is bounded. A word carrying a `$`-introduced
expansion this process cannot resolve — `${!A}`, `${#A}`, `${A:-x}`, `$1`,
`$@`, `$_`, or an undecodable `$'...'` escape — is denied for a first word
that is not READ_ONLY when the expansion begins the word, or sits before the
first `=` of a flag-shaped word (`-$A`, `--in-pl$A`). The shell expands it
into real argv and the assignment that set it was dropped as an env prefix
(`A=-i; sed $A f` really edits in place), so the letters of the flag are
unknowable. A `$NAME` this process's own environment resolves is checked as
its value, so `rm -rf $TMPDIR/x` still reaches the path check as a path; one
that only follows a flag's `=` (`--title=$T`) is left alone. Any unresolved
expansion in a redirect target or a scratch-op path is denied outright.

One quote/escape rule serves mask_quotes, find_substitutions and
match_paren: scan_states() is their shared scanner, and a backslash escapes
the next character everywhere except inside single quotes — with `$'...'`
(ANSI-C quoting) the one span that looks single-quoted but escapes, which is
what decides where it really ends. Earlier versions
carried that rule in three places, and both holes found in review were those
copies disagreeing. match_backtick keeps its own escape loop and tracks no
quote state — the shell's rule for a backtick span, applied with the unescape
step above.

KNOWN GAPS (documented in rules/advisor-mode.md): awk/heredoc bodies can
smuggle writes past the segment scan; wrapper commands are denied outright
rather than unwrapped (env/xargs/shells); an expansion the normalizer cannot
read is denied rather than modeled. Over-denial is the accepted direction:
the recipe in every denial names the delegation path.
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

SUBST_ARG_REASON = (
    "a `$(...)` or backtick substitution is used as an argument to a command "
    "that is not read-only, and the guard cannot check what it expands to — "
    "an inner command that only reads says nothing about whether its output "
    "is a flag like `-i` or a path. Run the substitution on its own and "
    "inline the value it printed, or delegate the command."
)

SUBST_TARGET_REASON = (
    "a `$(...)` or backtick substitution is used as a redirect target, so the "
    "guard cannot check where the output would land. Run the substitution on "
    "its own and inline the path it printed, or delegate the command."
)

# A `$NAME` / `${NAME}` shape anywhere in a path. path_allowed also judges
# file-tool inputs, which never went through the shell and so never through
# normalize_word; this is its own check on that raw text.
UNRESOLVED_VAR_RE = re.compile(r"\$\{?[A-Za-z_]")
# `$_` is the shell's own last-argument parameter, not an environment
# variable: what this process reads from the environment is not what bash
# will substitute, so it is never resolved here. `: -i` then `sed $_ …` is
# the same bypass as `A=-i` — verified to rewrite a file in place.
SHELL_ONLY_VAR_RE = re.compile(r"\$\{?_\b")

# A shell variable name, and the parameters whose values live in the shell
# rather than in this process's environment (`$1`, `$@`, `$?`, `$$`, `$-`, …).
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SPECIAL_PARAM_CHARS = set("@*#?$!-0123456789")

# bash's ANSI-C (`$'...'`) escape set. The numeric forms (`\nnn`, `\xHH`,
# `\uHHHH`, `\UHHHHHHHH`) and `\cX` are decoded in decode_ansi_c; anything
# else is unrecognized, and an unrecognized escape makes the word
# unresolvable rather than guessed at.
ANSI_C_ESCAPES = {
    "\\": "\\", "'": "'", '"': '"', "?": "?", "a": "\a", "b": "\b",
    "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
    "v": "\v",
}
HEX_DIGITS = "0123456789abcdefABCDEF"

VAR_ARG_REASON = (
    "an argument begins with — or is a flag carrying — a `$VAR`-style "
    "expansion this gate cannot resolve, and a command that is not "
    "read-only may not "
    "take one. The shell splits an expansion into real argv, so an `A=-i` "
    "earlier on the line turns `sed $A …` into an in-place edit and `sed "
    "-$A …` into the same thing. Run the command with the value written "
    "out, or delegate it."
)

ANSI_ARG_REASON = (
    "an argument carries a `$'…'` escape this gate cannot decode, so the "
    "word bash would pass is unknowable — and a command that is not "
    "read-only may not take one. Write the argument out plainly, or "
    "delegate the command."
)

VAR_TARGET_REASON = (
    "an expansion this gate cannot resolve is used as a redirect target, so "
    "the guard cannot check where the output would land. Write the path "
    "out, or delegate the command."
)

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
GIT_BRANCH_MUTATORS = {"--delete", "--move", "--force", "--copy"}
# git's option parser clusters single-dash short flags, so `-Df` IS
# `-D -f` — verified against real git, which parsed `-dr` as `-d -r` and
# attempted the delete. Any single-dash cluster carrying a delete/move/
# copy/force letter mutates; the read-only short flags (-a -r -v -l -q -i
# -t -u) share none of them.
GIT_BRANCH_CLUSTER_RE = re.compile(r"^-[A-Za-z]+$")
GIT_BRANCH_MUTATOR_LETTERS = set("dDmMfcC")

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
# gh accepts the attached forms (`-XPOST`, `--method=POST`, `-fk=v`,
# `--field=k=v`) — verified against the real binary — so these match as
# prefixes, not exact words. No read-only gh api flag starts with any of them.
GH_API_MUTATION_PREFIXES = ("-X", "--method", "-f", "-F", "--field",
                            "--raw-field", "--input")

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


def unresolved_var_in(text):
    """True when `text` still carries a `$VAR` anywhere after expansion."""
    if SHELL_ONLY_VAR_RE.search(text):
        return True
    return bool(UNRESOLVED_VAR_RE.search(os.path.expandvars(text)))


def path_allowed(raw_path):
    """True when the path is an orchestrator work-product location.

    Shell callers hand this the normalized word (quotes already removed by
    normalize_word, which is where bash removes them). File-tool callers hand
    it a literal path that never went through a shell. Either way the text
    arriving here is the path itself, so this does not strip quotes — a
    leftover quote is part of the name.
    """
    if not raw_path or not isinstance(raw_path, str):
        return True  # fail open: nothing to judge
    if SUBST_PLACEHOLDER in raw_path:
        # The path is a substitution's output, so it cannot be resolved and
        # checked. Covers scratch-op arguments and redirect targets alike.
        return False
    raw = raw_path.strip()
    if unresolved_var_in(raw):
        # A variable this process cannot resolve, so where the write lands is
        # unknowable — the same reason a substitution's output cannot be a
        # path. `A=~/code/repo/pwn` then `echo hi > $A` is the redirect twin
        # of `rm $A` (issue #1014).
        return False
    path = os.path.realpath(os.path.expanduser(os.path.expandvars(raw)))
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
    inside a POSIX single-quoted span, where nothing escapes.

    `$'...'` (ANSI-C quoting) is the exception to that exception, and issue
    #1015: the shell DOES process backslash escapes there, so `\\'` does not
    close the span. Read as a POSIX span it closed one character early, the
    next `'` opened a phantom span that swallowed the following separator,
    and the command after it was never checked — `echo $'a\\'' ; touch <repo>`
    ran the touch. The span is reported as `'` (nothing expands inside one
    either way); only where it ENDS changes. `$'` is an opener only outside
    every quote — inside double quotes the shell reads it as `$` then `'`.

    Yielded lazily so a caller that stops early pays only for what it read;
    find_substitutions, which needs to jump over spans, materializes a list.

    mask_quotes, find_substitutions and match_paren all read these states.
    Keeping the rule here is the point: when each of them carried its own
    copy, `mask_quotes` disagreed with the span finder about `\\"` and a
    trailing command went unchecked (issue #1012), and `match_backtick`
    disagreed about `\\`` and a nested command ran unchecked.
    """
    quote = None
    ansi_c = False  # this `'` span was opened by `$'` — backslashes escape
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if quote == "'":
            if ansi_c and c == "\\" and i + 1 < n:
                yield ("'", True)
                yield ("'", True)
                i += 2
                continue
            yield ("'", False)
            if c == "'":
                quote = None
                ansi_c = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            yield (quote, True)
            yield (quote, True)
            i += 2
            continue
        if quote is None and c == "$" and cmd[i + 1:i + 2] == "'":
            quote, ansi_c = "'", True
            yield ("'", False)  # the `$`
            yield ("'", False)  # the `'` it opens with
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


class Word:
    """One shell word of a segment, as bash would hand it to the command.

    `text` is the word after quote removal, escape removal, `$'...'` decoding
    and resolvable-variable substitution — the characters the command really
    receives, which is what every literal check in this file needs to read.
    The three flags name what could NOT be resolved, in the positions where
    that decides the command (issue #1017).
    """

    __slots__ = ("text", "unresolved", "leading_unresolved",
                 "flag_unresolved", "undecodable")

    def __init__(self, text, marks, undecodable):
        self.text = text
        self.undecodable = undecodable
        self.unresolved = bool(marks) or undecodable
        # An expansion at the very start of the word: the whole argument is
        # unknowable, so it can be a flag, a `--`, or a path (issue #1014).
        self.leading_unresolved = 0 in marks
        # A flag-shaped word whose LETTERS are unknowable. An expansion after
        # the first `=` is a value (`--title=$T`), not part of the flag.
        limit = text.find("=")
        if limit < 0:
            limit = len(text)
        self.flag_unresolved = text.startswith("-") and any(
            m < limit for m in marks)


def decode_ansi_c(body):
    """Decode a `$'...'` body. Returns (text, fully_decoded).

    An escape this decoder does not recognize ends the decode and reports
    False: the word bash would pass is then unknowable, and guessing at it is
    how a `-i` sneaks through.
    """
    out = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= n:
            return "".join(out), False  # trailing backslash
        e = body[i]
        if e in ANSI_C_ESCAPES:
            out.append(ANSI_C_ESCAPES[e])
            i += 1
            continue
        if e == "c":  # \cX — control character
            i += 1
            if i >= n:
                return "".join(out), False
            out.append(chr(ord(body[i].upper()) ^ 0x40))
            i += 1
            continue
        if e in "01234567":  # \nnn — up to three octal digits
            j = i
            while j < n and j - i < 3 and body[j] in "01234567":
                j += 1
            out.append(chr(int(body[i:j], 8) & 0xFF))
            i = j
            continue
        if e in ("x", "u", "U"):  # \xHH, \uHHHH, \UHHHHHHHH
            width = {"x": 2, "u": 4, "U": 8}[e]
            i += 1
            j = i
            while j < n and j - i < width and body[j] in HEX_DIGITS:
                j += 1
            if j == i:
                return "".join(out), False  # \x with no digits
            try:
                out.append(chr(int(body[i:j], 16)))
            except ValueError:
                return "".join(out), False  # past the Unicode range
            i = j
            continue
        return "".join(out), False  # unrecognized escape — never guess
    return "".join(out), True


def scan_expansion(s, i):
    """Read the `$` expansion at s[i]. Returns (end, name, is_expansion).

    `name` is set only for the plain `$NAME` / `${NAME}` shapes this process
    may look up in its own environment. Every other `$`-introduced form —
    `${!A}`, `${#A}`, `${A:-x}`, `${A[0]}`, `$1`, `$@`, `$_`, an unterminated
    `${` — returns None and is unresolvable: bash substitutes from state this
    process cannot see. A `$` that introduces nothing is literal text.
    """
    n = len(s)
    j = i + 1
    if j >= n:
        return i + 1, None, False  # trailing `$` is a literal dollar
    c = s[j]
    if c == "{":
        k = s.find("}", j + 1)
        if k < 0:
            return n, None, True  # unterminated `${` — unreadable
        inner = s[j + 1:k]
        if NAME_RE.fullmatch(inner) and inner != "_":
            return k + 1, inner, True
        return k + 1, None, True
    if c == "(":
        # Substitutions are checked and collapsed before any segment reaches
        # here, so a surviving `$(` is not something this gate can read.
        return n, None, True
    m = NAME_RE.match(s, j)
    if m:
        name = m.group(0)
        # `$_` is the shell's last-argument parameter; the environment's copy
        # is not what bash substitutes.
        return m.end(), (None if name == "_" else name), True
    if c in SPECIAL_PARAM_CHARS:
        return j + 1, None, True
    return i + 1, None, False  # `$` before anything else is literal


def expand_run(s, states):
    """Quote-removed text of an unquoted or double-quoted run.

    Returns (text, marks): `marks` are offsets into `text` where an expansion
    this process cannot resolve begins. A resolvable `$NAME` is replaced by
    its value, so the checks downstream read the real argument.
    """
    parts = []
    marks = []
    length = 0
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and states[i][1] and i + 1 < n:
            parts.append(s[i + 1])
            length += 1
            i += 2
            continue
        if c == "$" and not states[i][1]:
            end, name, is_expansion = scan_expansion(s, i)
            if not is_expansion:
                parts.append(s[i:end])
                length += end - i
            elif name is not None and name in os.environ:
                value = os.environ[name]
                parts.append(value)
                length += len(value)
            else:
                marks.append(length)
                parts.append(s[i:end])
                length += end - i
            i = end
            continue
        parts.append(c)
        length += 1
        i += 1
    return "".join(parts), marks


def normalize_word(raw):
    """The Word bash would build from `raw` after quote and escape removal.

    Spans are found with scan_states — the file's one scanner — so this
    agrees with mask_quotes and the substitution finder about where a quoted
    span ends. Adjacent spans concatenate, exactly as the shell joins them:
    `-''i`, `-"i"` and `$'-i'` all normalize to `-i`.
    """
    states = list(scan_states(raw))
    n = len(raw)
    parts = []
    marks = []
    length = 0
    undecodable = False
    i = 0
    while i < n:
        quote = states[i][0]
        if quote is None:
            j = i
            while j < n and states[j][0] is None:
                j += 1
            text, run_marks = expand_run(raw[i:j], states[i:j])
            marks.extend(length + m for m in run_marks)
            parts.append(text)
            length += len(text)
            i = j
            continue
        # A quoted span. Inside one, an unescaped delimiter character can
        # only BE the delimiter, so this finds the end without a second
        # scanner: `'a''b'` is two spans, not one span holding two quotes.
        ansi = quote == "'" and raw[i] == "$"
        i += 2 if ansi else 1  # step over `$'` or the single delimiter
        start = i
        while i < n and not (states[i][0] == quote and not states[i][1]
                             and raw[i] == quote):
            i += 1
        end = i
        body = raw[start:end]
        i += 1  # step over the closing delimiter (or past the end)
        if quote == '"':
            text, run_marks = expand_run(body, states[start:end])
            marks.extend(length + m for m in run_marks)
        elif ansi:
            text, decoded = decode_ansi_c(body)
            if not decoded:
                undecodable = True
        else:
            text = body  # a POSIX single-quoted span is literal
        parts.append(text)
        length += len(text)
    return Word("".join(parts), marks, undecodable)


def split_words(text):
    """Split on UNQUOTED whitespace, the way the shell splits a command."""
    states = list(scan_states(text))
    words = []
    i, n = 0, len(text)
    while i < n:
        quote, escaped = states[i]
        if quote is None and not escaped and text[i].isspace():
            i += 1
            continue
        start = i
        while i < n:
            quote, escaped = states[i]
            if quote is None and not escaped and text[i].isspace():
                break
            i += 1
        words.append(text[start:i])
    return words


def segment_words(segment):
    """The Words a segment passes to its command, env prefixes dropped."""
    return strip_env_assignments(
        [normalize_word(w) for w in split_words(strip_grouping(segment))])


def raw_word_at(cmd, states, start):
    """Raw text of the shell word at or after `start` in `cmd`.

    Redirect targets need this: the masked string a redirect is found in has
    already replaced a quoted target with spaces, so the target has to be cut
    from the raw command before it can be normalized.
    """
    i, n = start, len(cmd)
    while i < n and states[i][0] is None and not states[i][1] \
            and cmd[i] in " \t":
        i += 1
    begin = i
    while i < n:
        quote, escaped = states[i]
        if quote is None and not escaped and (cmd[i].isspace()
                                              or cmd[i] in ";|&<>"):
            break
        i += 1
    return cmd[begin:i]


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
    states = list(scan_states(cmd))
    for m in REDIRECT_RE.finditer(masked):
        op = m.group(1)
        if "&" in op and op[-1].isdigit():
            continue  # fd duplication (2>&1, >&2)
        # The target is cut from the RAW command and normalized: masking has
        # already blanked a quoted target, and `> '-'` or `> $'…'` is a real
        # path to bash.
        raw = raw_word_at(cmd, states, m.end(1))
        if not raw or raw.startswith("&"):
            continue
        target = normalize_word(raw)
        if target.text in ("/dev/null", "/dev/stdout", "/dev/stderr",
                           "/dev/tty"):
            continue
        if target.unresolved or not path_allowed(target.text):
            return False, target
    return True, None


ENV_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*")


def strip_env_assignments(words):
    while words and ENV_ASSIGN_RE.fullmatch(words[0].text):
        words = words[1:]
    return words


def git_segment_allowed(words):
    args = [w.text for w in words[1:]]
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
        return not any(git_branch_mutates(w) for w in rest)
    if sub == "tag":
        return not rest or any(w in ("-l", "--list") for w in rest)
    if sub == "config":
        return bool(rest) and rest[0] in ("--get", "--get-all",
                                          "--get-regexp", "-l", "--list")
    return False


def git_branch_mutates(arg):
    """True when a `git branch` argument deletes, moves, copies, or forces."""
    if arg in GIT_BRANCH_MUTATORS:
        return True
    if GIT_BRANCH_CLUSTER_RE.match(arg):
        return any(ch in GIT_BRANCH_MUTATOR_LETTERS for ch in arg[1:])
    return False


def gh_segment_allowed(words):
    args = [w.text for w in words[1:]]
    if not args:
        return True
    group, rest = args[0], args[1:]
    if group == "api":
        return not any(w.startswith(GH_API_MUTATION_PREFIXES) for w in rest)
    if group not in GH_ALLOWED:
        return False
    verbs = GH_ALLOWED[group]
    if verbs is None:
        return True
    verb = next((w for w in rest if not w.startswith("-")), None)
    return verb in verbs if verb else True  # bare group prints help


def scratch_op_allowed(words):
    for w in words[1:]:
        if w.text.startswith("-"):
            continue
        if w.unresolved or not path_allowed(w.text):
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
    args = [w.text for w in words[1:]
            if not REDIRECT_TOKEN_RE.match(w.text)]
    return bool(args) and all(a in PROBE_ARGS for a in args)


def open_consumer(words):
    """True when this segment's command is a plain read-only consumer.

    Those are the only commands allowed to take an argument the gate cannot
    read: `echo $A`, `grep "$PAT" f`, `cd $DIR` and `printf '%s' $'\\e[0m'`
    cannot write whatever the argument turns out to be.
    """
    return bool(words) and words[0].text.rsplit("/", 1)[-1] in READ_ONLY


def placeholder_misuse(segment):
    """True when a checked substitution stands in for an argument to a
    command that is not read-only.

    A verified substitution collapses to a placeholder, and the shell
    word-splits its output into real argv: `sed $(echo -i) …` IS `sed -i …`.
    Checking the inner command read-only says nothing about its output, so
    only plain read-only consumers may take one — every branch in
    bash_segment_allowed decides on literal argument text (`-i`, `-delete`,
    `-o`, `-X`, a path) that a placeholder silently slips past.

    The deny decision and its message both read this, so the message can name
    what actually happened instead of quoting a token the user never typed.
    """
    words = segment_words(segment)
    if open_consumer(words):
        return False
    return any(SUBST_PLACEHOLDER in w.text for w in words)


def var_misuse(segment):
    """True when a command that is not read-only takes an argument whose
    expansion this gate cannot resolve, in a position that decides the
    command.

    Two positions do: the START of a word (the whole argument is unknowable,
    so it can be `-i`, `--`, or a repo path) and inside a flag-shaped word
    before its first `=` (the flag's LETTERS are unknowable, so `A=i` turns
    `sed -$A f` into an in-place edit). An expansion after a flag's `=`
    (`--title=$T`) is a value, and one in a plain word (`s/a/b/$A`) can
    become neither a flag nor a fresh path — both are left alone.

    The deny decision and its message both read this predicate.
    """
    words = segment_words(segment)
    if open_consumer(words):
        return False
    return any(w.leading_unresolved or w.flag_unresolved for w in words)


def ansi_misuse(segment):
    """True when a command that is not read-only takes a `$'…'` word this
    gate could not fully decode.

    Position does not matter here: a body that stopped decoding could hold
    any character at all, so the word bash passes is unknown wherever it
    sits. Read-only consumers still take one.
    """
    words = segment_words(segment)
    if open_consumer(words):
        return False
    return any(w.undecodable for w in words)


def bash_segment_allowed(segment):
    words = segment_words(segment)
    if not words:
        return True
    first = words[0].text.rsplit("/", 1)[-1]  # /usr/bin/git → git
    args = [w.text for w in words[1:]]
    if placeholder_misuse(segment):
        return False
    if ansi_misuse(segment):
        return False
    if var_misuse(segment):
        return False
    if first == "sed":
        # -i in any form: bare, with attached suffix (-i.bak), inside a
        # single-dash flag cluster (-ni), or --in-place[=suffix].
        return not any(
            re.match(r"^-[a-zA-Z]*i", w) or w.startswith("--in-place")
            for w in args)
    if first == "find":
        return not any(w in FIND_WRITE_PREDICATES for w in args)
    if first == "sort":
        # `sort -o FILE` writes/truncates FILE — in bare, attached (-oFILE),
        # and clustered (-ro) forms, like the sed -i handling. `sort > FILE`
        # goes through the path-checked redirect scan instead.
        return not any(
            re.match(r"^-[a-zA-Z]*o", w) or w.startswith("--output")
            for w in args)
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
        if SUBST_PLACEHOLDER in target.text:
            return SUBST_TARGET_REASON
        if target.unresolved:
            return VAR_TARGET_REASON
        return ("redirecting output into `%s` writes outside the "
                "orchestrator's work-product paths." % target.text)
    for segment in split_segments(command, masked):
        if not bash_segment_allowed(segment):
            if placeholder_misuse(segment):
                return SUBST_ARG_REASON
            if ansi_misuse(segment):
                return ANSI_ARG_REASON
            if var_misuse(segment):
                return VAR_ARG_REASON
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
    # The /advisor on/off recipes carry a `$CLAUDE_CODE_SESSION_ID` in the
    # flag path (`… > ~/.claude/advisor-mode/$CLAUDE_CODE_SESSION_ID`, and the
    # `rm -f` twin). If the hook subprocess does not carry that variable, rule
    # (b) cannot resolve it and would deny the recipe — stranding a user in
    # advisor mode with no documented way out. The guard already knows the id
    # authoritatively: it just matched the flag file with `sid`, which
    # session_id() validated against SESSION_ID_RE. Seed it so the path
    # resolves — only when absent, never overwriting the environment's own
    # value, and only for an id that re-passes that same validation, so a
    # hostile stdin string is never written into the environment. A
    # shell-local attacker var (`A=…`) is still never seeded, so it stays
    # unresolvable and denied.
    if not os.environ.get(SESSION_ID_ENV) and SESSION_ID_RE.fullmatch(sid):
        os.environ[SESSION_ID_ENV] = sid
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
