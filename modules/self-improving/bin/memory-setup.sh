#!/usr/bin/env bash
# CCGM memory-setup — interactive, idempotent activation for the durable-memory
# system (issue #796).
#
# A fresh CCGM install ships the memory *code* but leaves it dormant: the
# SessionStart injection hook is env-gated off, the learnings store is not yet a
# git repo, and `dreaming` (if installed at all) has no scheduled job. This
# script is the "install code + run a setup script" activation step, matching
# autoheal-install.sh / dream-install.sh — NOT an auto-run postInstall.
#
# It turns on the READ PATH and, when the `dreaming` module is also installed,
# OFFERS the WRITE PATH:
#
#   Read path   self-improving learnings store + SessionStart injection.
#               Sets CCGM_LEARNINGS_INJECT=true in ~/.claude/settings.json (jq
#               deep-merge, existing env keys preserved) and runs
#               `ccgm-learnings-sync init` for git durability. Local + free.
#
#   Write path  the `dreaming` nightly analyzer. Costs Anthropic API tokens and
#               installs a nightly LaunchAgent. Prompts for an API key, writes it
#               to ~/.claude/dreaming/.env (mode 0600, never echoed), then runs
#               dream-install.sh.
#
# Safety posture:
#   * Idempotent — re-running reports current state and no-ops what is already on.
#   * Confirms before every write; a non-interactive / closed stdin defaults to NO.
#   * The API key is read with input hidden and never printed back.
#   * Commits to NO git repo. `ccgm-learnings-sync init` bootstraps its own
#     separate repo (~/.claude/learnings); this script never commits to CCGM or
#     any existing checkout.
#
# Usage: memory-setup.sh [--help]

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLAUDE_DIR="${HOME}/.claude"
SETTINGS="${CLAUDE_DIR}/settings.json"
DREAMING_DIR="${CLAUDE_DIR}/dreaming"
DREAM_ENV="${DREAMING_DIR}/.env"
DREAM_INSTALL="${CLAUDE_DIR}/bin/dream-install.sh"

# ---------------------------------------------------------------------------
# Output helpers (plain bash — no color/TUI dependency, matching the other
# self-improving/dreaming bin scripts).
# ---------------------------------------------------------------------------
say()  { printf '%s\n' "$*"; }
ok()   { printf '\xe2\x9c\x85 %s\n' "$*"; }   # ✅
skip() { printf '\xe2\x8f\xad\xef\xb8\x8f %s\n' "$*"; }  # ⏭️
warn() { printf '\xe2\x9a\xa0\xef\xb8\x8f %s\n' "$*"; }  # ⚠️

# Yes/No prompt. Returns 0 for yes, 1 for no. Defaults to NO on EOF / closed
# stdin so a non-interactive run never silently writes.
confirm() {
    local prompt="$1" reply=""
    printf '%s [y/N] ' "$prompt"
    read -r reply || return 1
    case "$reply" in
        [yY] | [yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

usage() {
    cat <<'EOF'
memory-setup.sh — activate the CCGM durable-memory system (issue #796).

Interactive and idempotent. Turns on the local, free READ PATH and — when the
`dreaming` module is installed — OFFERS the token-costing WRITE PATH. Every
write is confirmed first; the script commits to no git repo.

  Read path   self-improving learnings store + SessionStart injection.
              Sets CCGM_LEARNINGS_INJECT=true in ~/.claude/settings.json and
              runs `ccgm-learnings-sync init` for git durability. Local + free.
              Injection applies to sessions started AFTER activation.

  Write path  the `dreaming` nightly analyzer (opt-in). Costs Anthropic API
              tokens and installs a nightly LaunchAgent. Prompts for an API key,
              writes it to ~/.claude/dreaming/.env (mode 0600, never echoed).

Options:
  -h, --help  Show this help and exit.

See docs/memory-system.md for the full guide.
EOF
}

# ---------------------------------------------------------------------------
# Locate ccgm-learnings-sync. Prefer the sibling next to this script (works
# both in the source tree and once installed to ~/.claude/bin), then the
# installed copy, then anything on PATH.
# ---------------------------------------------------------------------------
find_sync() {
    if [ -x "${SCRIPT_DIR}/ccgm-learnings-sync" ]; then
        printf '%s\n' "${SCRIPT_DIR}/ccgm-learnings-sync"
        return 0
    fi
    if [ -x "${CLAUDE_DIR}/bin/ccgm-learnings-sync" ]; then
        printf '%s\n' "${CLAUDE_DIR}/bin/ccgm-learnings-sync"
        return 0
    fi
    command -v ccgm-learnings-sync 2>/dev/null && return 0
    return 1
}

# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

# Echo the current CCGM_LEARNINGS_INJECT value: "true", "unset", or "invalid"
# (settings.json present but unparseable).
current_inject_flag() {
    if [ ! -f "$SETTINGS" ]; then
        printf 'unset\n'
        return
    fi
    jq -r '.env.CCGM_LEARNINGS_INJECT // "unset"' "$SETTINGS" 2>/dev/null || printf 'invalid\n'
}

# Deep-merge CCGM_LEARNINGS_INJECT=true into ~/.claude/settings.json, preserving
# every existing env key (and every other top-level key). Never clobbers on a
# jq failure.
write_inject_flag() {
    mkdir -p "$CLAUDE_DIR"
    if [ -f "$SETTINGS" ]; then
        local tmp
        tmp="$(mktemp)"
        if jq '.env.CCGM_LEARNINGS_INJECT = "true"' "$SETTINGS" >"$tmp" 2>/dev/null; then
            mv "$tmp" "$SETTINGS"
            ok "Set CCGM_LEARNINGS_INJECT=true in ${SETTINGS} (existing env keys preserved)."
        else
            rm -f "$tmp"
            warn "Could not merge into ${SETTINGS}; left untouched. Fix its JSON and re-run."
            return 1
        fi
    else
        printf '{\n  "env": {\n    "CCGM_LEARNINGS_INJECT": "true"\n  }\n}\n' >"$SETTINGS"
        ok "Created ${SETTINGS} with CCGM_LEARNINGS_INJECT=true."
    fi
}

# Ensure the learnings store is a git repo for durability.
#   $1 = "auto" to init without a second prompt (already confirmed upstream),
#        "ask"  to confirm before initializing.
sync_init_if_needed() {
    local mode="$1" sync learnings_dir
    if ! sync="$(find_sync)"; then
        warn "ccgm-learnings-sync not found; skipped git-durability init."
        warn "Install the self-improving module, then re-run."
        return
    fi
    learnings_dir="${CCGM_LEARNINGS_DIR:-${CLAUDE_DIR}/learnings}"
    if [ -d "${learnings_dir}/.git" ]; then
        ok "Learnings store git durability already initialized (${learnings_dir})."
        return
    fi
    if [ "$mode" = "ask" ]; then
        if ! confirm "Initialize git durability for the learnings store now?"; then
            skip "Skipped git-durability init. Injection stays enabled regardless."
            return
        fi
    fi
    if "$sync" init >/dev/null 2>&1; then
        ok "Ran ccgm-learnings-sync init — ${learnings_dir} is now versioned."
    else
        warn "ccgm-learnings-sync init did not complete; injection is still enabled."
        warn "Run '${sync} init' by hand later for git durability."
    fi
}

enable_read_path() {
    say ""
    say "── Read path (local, free) ────────────────────────────────"
    say "Surfaces this project's durable learnings (patterns, pitfalls,"
    say "preferences the store has accumulated) into each NEW session at"
    say "startup, so an agent begins already aware of what it learned before."
    say "Nothing leaves your machine. It applies to sessions started AFTER"
    say "activation — an already-open session will not gain it."
    say ""

    local state
    state="$(current_inject_flag)"
    case "$state" in
        true)
            ok "Injection already enabled (CCGM_LEARNINGS_INJECT=true) — no change."
            sync_init_if_needed ask
            ;;
        invalid)
            warn "${SETTINGS} is not valid JSON; leaving it untouched."
            warn "Fix the file, then re-run to enable injection."
            ;;
        *)
            say "Enabling makes two writes:"
            say "  1. set CCGM_LEARNINGS_INJECT=true in ${SETTINGS}"
            say "  2. run 'ccgm-learnings-sync init' (git durability for the store)"
            say ""
            if confirm "Enable the read path now?"; then
                if write_inject_flag; then
                    sync_init_if_needed auto
                fi
            else
                skip "Left the read path disabled. Re-run any time to enable it."
            fi
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Write path (dreaming) — only offered when the module is installed.
# ---------------------------------------------------------------------------

# Prompt for the API key (hidden) and write it to ~/.claude/dreaming/.env at
# mode 0600. The key is never echoed and is scrubbed from memory after the write.
write_dream_env() {
    mkdir -p "$DREAMING_DIR"
    say ""
    say "Paste your Anthropic API key (input hidden), or press Enter to skip and"
    say "add it later to ${DREAM_ENV}:"
    local api_key=""
    read -r -s api_key || api_key=""
    say ""   # terminate the hidden-input line
    if [ -z "$api_key" ]; then
        skip "No key entered — dream-install.sh will write an empty template."
        skip "Add ANTHROPIC_API_KEY=<your-key> to ${DREAM_ENV} (mode 0600) later."
        return
    fi
    if ! confirm "Write the key to ${DREAM_ENV} (mode 0600)?"; then
        skip "Key not written."
        api_key=""
        return
    fi
    local old_umask
    old_umask="$(umask)"
    umask 077
    {
        printf '# dreaming API key — scoped to the dreaming LaunchAgent ONLY.\n'
        printf '# Do NOT export this from ~/.zshrc / ~/.bash_profile — the Anthropic\n'
        printf '# SDK auto-picks up ANTHROPIC_API_KEY and would bill against the API\n'
        printf '# key instead of your Claude Max subscription. Mode 0600.\n'
        printf 'ANTHROPIC_API_KEY=%s\n' "$api_key"
    } >"$DREAM_ENV"
    umask "$old_umask"
    chmod 0600 "$DREAM_ENV" 2>/dev/null || true
    api_key=""   # scrub
    ok "Wrote API key to ${DREAM_ENV} (mode 0600, key not shown)."
}

offer_dreaming() {
    say ""
    say "── Write path: dreaming (opt-in, costs tokens) ────────────"
    if [ ! -e "$DREAM_INSTALL" ]; then
        skip "The 'dreaming' module is not installed — write path unavailable."
        say  "   Add it with:   bash start.sh --add dreaming"
        say  "   Then re-run this script to activate the nightly analyzer."
        return
    fi

    say "Dreaming mines your session transcripts nightly into memory proposals"
    say "you approve by hand. It COSTS Anthropic API tokens and installs a nightly"
    say "LaunchAgent. Auto-apply stays OFF by default — nothing is written to the"
    say "store without your explicit /dream-apply."
    say ""
    if ! confirm "Activate dreaming (nightly analyzer + LaunchAgent) now?"; then
        skip "Left dreaming inactive. Re-run any time to activate it."
        return
    fi

    write_dream_env

    say ""
    say "Running dream-install.sh…"
    if "$DREAM_INSTALL"; then
        ok "Dreaming installed — nightly LaunchAgent scheduled. See /dream for status."
    else
        warn "dream-install.sh reported an error (see its output above)."
    fi
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
main() {
    case "${1:-}" in
        -h | --help)
            usage
            exit 0
            ;;
        "") ;;
        *)
            warn "Unknown argument: $1"
            say ""
            usage
            exit 2
            ;;
    esac

    if ! command -v jq >/dev/null 2>&1; then
        warn "jq is required (settings.json is edited via jq). Install jq and re-run."
        exit 1
    fi

    say "CCGM durable-memory activation"
    say "=============================="
    say "Interactive and idempotent — nothing is written without a confirmation."

    enable_read_path
    offer_dreaming

    say ""
    say "Done. Full guide: docs/memory-system.md"
}

main "$@"
