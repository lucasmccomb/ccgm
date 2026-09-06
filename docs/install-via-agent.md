# Install via Agent

Paste a block of text into a fresh Claude Code session. The agent reads your environment, picks a preset, runs the installer, and verifies the result. No bash flags to remember. No decisions to make upfront.

This approach comes from Karpathy's description of OpenClaw's install UX:

> "The open claw installation is a copy paste of a bunch of text that you give to your agent. The agent has its own intelligence... it looks at your environment, your computer and it kind of like performs intelligent actions to make things work."

The blocks below are that text for CCGM.

---

## Default block (agent picks the preset)

Paste this into a fresh `claude` session:

```
Install CCGM (Claude Code God Mode) for me.

Steps:
1. Detect my OS (uname -s), shell ($SHELL), and home directory ($HOME).
2. Clone the repo if it does not already exist:
     git clone https://github.com/lucasmccomb/ccgm.git ~/code/ccgm
   If it already exists, pull the latest main:
     cd ~/code/ccgm && git fetch origin && git checkout main && git pull --ff-only origin main
3. Read the available presets: ls ~/code/ccgm/presets/
   Available presets and what they include:
     - minimal  : global-claude-md, autonomy, git-workflow
     - standard : the above + identity, hooks, branch-guard, ask-context, model-vetting, live-testing-guard, settings, commands-core, commands-utility, self-improving, output-formatting, writing-system, statusline
     - team     : standard core (minus identity, commands-utility, model-vetting, live-testing-guard, self-improving, statusline) + github-protocols, code-quality, systematic-debugging, verification, autoheal, and review/compound-knowledge tooling (ce-review, pr-feedback, document-review, compound-knowledge, skill-authoring, subagent-patterns, pr-review-toolkit)
     - cloud-agent : large set for power users running autonomous agents
     - full     : every stable module
   Based on what you know about my workflow, recommend one preset. Ask me to confirm or pick a different one before continuing. (One question only — do not ask anything else.)
4. Check what is already installed by looking at ~/.claude/rules/, ~/.claude/commands/, ~/.claude/hooks/. List existing CCGM files and inspect ~/.claude/.ccgm-manifest.json. For an existing install, add only the requested missing modules with --add; a preset install can replace selected module-owned files. Preserve unrelated files.
5. Read ~/.claude/settings.json if it exists and note its content. The installer will merge non-destructively — it will not delete keys that are already there.
6. Run from the CCGM repository root. For a new global install:
     cd ~/code/ccgm
     CCGM_NON_INTERACTIVE=1 \
       CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo '')" \
       ./start.sh --preset <chosen-preset> --scope global
   For an existing global install, use ./start.sh --add <missing-module> --scope global for each requested addition instead.
7. Verify the install succeeded by checking that these paths exist:
     ~/.claude/rules/
     ~/.claude/CLAUDE.md   (if global-claude-md was in the preset)
   List the files now present in ~/.claude/rules/ and ~/.claude/commands/.
8. Report: which preset was installed, which existing modules were preserved and which requested modules were added or replaced, and any errors.
```

---

## Per-preset blocks

Use one of these if you already know which preset you want. Paste the block for your preset into a fresh `claude` session.

### minimal

```
Install CCGM (Claude Code God Mode) with the minimal preset.

Steps:
1. Detect my OS (uname -s), shell ($SHELL), and home directory ($HOME).
2. Clone the repo if it does not already exist:
     git clone https://github.com/lucasmccomb/ccgm.git ~/code/ccgm
   If it already exists, pull the latest main:
     cd ~/code/ccgm && git fetch origin && git checkout main && git pull --ff-only origin main
3. Check what is already installed: ls ~/.claude/rules/ ~/.claude/commands/ 2>/dev/null
   Inspect ~/.claude/.ccgm-manifest.json and the requested presets/minimal.json. For an existing global install, add only requested missing modules with --add; a preset reinstall can replace selected module-owned files. Preserve unrelated files.
4. Read ~/.claude/settings.json if it exists and note its content.
5. Run from the CCGM repository root. For a new global install:
     cd ~/code/ccgm
     CCGM_NON_INTERACTIVE=1 \
       CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo '')" \
       ./start.sh --preset minimal --scope global
   For an existing global install, use ./start.sh --add <missing-module> --scope global for each requested addition instead.
6. Verify: confirm ~/.claude/rules/ exists and list its contents.
7. Report: the actual preset or additions installed, existing modules preserved, requested modules added or replaced, and any errors.

Modules in this preset: global-claude-md, autonomy, git-workflow.
```

### standard

```
Install CCGM (Claude Code God Mode) with the standard preset.

Steps:
1. Detect my OS (uname -s), shell ($SHELL), and home directory ($HOME).
2. Clone the repo if it does not already exist:
     git clone https://github.com/lucasmccomb/ccgm.git ~/code/ccgm
   If it already exists, pull the latest main:
     cd ~/code/ccgm && git fetch origin && git checkout main && git pull --ff-only origin main
3. Check what is already installed: ls ~/.claude/rules/ ~/.claude/commands/ 2>/dev/null
   Inspect ~/.claude/.ccgm-manifest.json and the requested presets/standard.json. For an existing global install, add only requested missing modules with --add; a preset reinstall can replace selected module-owned files. Preserve unrelated files.
4. Read ~/.claude/settings.json if it exists and note its content.
5. Run from the CCGM repository root. For a new global install:
     cd ~/code/ccgm
     CCGM_NON_INTERACTIVE=1 \
       CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo '')" \
       ./start.sh --preset standard --scope global
   For an existing global install, use ./start.sh --add <missing-module> --scope global for each requested addition instead.
6. Verify: confirm ~/.claude/rules/ and ~/.claude/commands/ exist and list their contents.
7. Report: the actual preset or additions installed, existing modules preserved, requested modules added or replaced, and any errors.

Modules in this preset: global-claude-md, autonomy, identity, git-workflow, hooks, settings, commands-core, commands-utility.
```

### team

```
Install CCGM (Claude Code God Mode) with the team preset.

Steps:
1. Detect my OS (uname -s), shell ($SHELL), and home directory ($HOME).
2. Clone the repo if it does not already exist:
     git clone https://github.com/lucasmccomb/ccgm.git ~/code/ccgm
   If it already exists, pull the latest main:
     cd ~/code/ccgm && git fetch origin && git checkout main && git pull --ff-only origin main
3. Check what is already installed: ls ~/.claude/rules/ ~/.claude/commands/ ~/.claude/hooks/ 2>/dev/null
   Inspect ~/.claude/.ccgm-manifest.json and the requested presets/team.json. For an existing global install, add only requested missing modules with --add; a preset reinstall can replace selected module-owned files. Preserve unrelated files.
4. Read ~/.claude/settings.json if it exists and note its content.
5. Run from the CCGM repository root. For a new global install:
     cd ~/code/ccgm
     CCGM_NON_INTERACTIVE=1 \
       CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo '')" \
       ./start.sh --preset team --scope global
   For an existing global install, use ./start.sh --add <missing-module> --scope global for each requested addition instead.
6. Verify: confirm ~/.claude/rules/, ~/.claude/commands/, and ~/.claude/hooks/ exist and list their contents.
7. Report: the actual preset or additions installed, existing modules preserved, requested modules added or replaced, and any errors.

Modules in this preset: global-claude-md, autonomy, git-workflow, hooks, settings, commands-core, github-protocols, code-quality, systematic-debugging, verification.
```

### cloud-agent

```
Install CCGM (Claude Code God Mode) with the cloud-agent preset.

Steps:
1. Detect my OS (uname -s), shell ($SHELL), and home directory ($HOME).
2. Clone the repo if it does not already exist:
     git clone https://github.com/lucasmccomb/ccgm.git ~/code/ccgm
   If it already exists, pull the latest main:
     cd ~/code/ccgm && git fetch origin && git checkout main && git pull --ff-only origin main
3. Check what is already installed: ls ~/.claude/rules/ ~/.claude/commands/ ~/.claude/hooks/ ~/.claude/agents/ 2>/dev/null
   Inspect ~/.claude/.ccgm-manifest.json and the requested presets/cloud-agent.json. For an existing global install, add only requested missing modules with --add; a preset reinstall can replace selected module-owned files. Preserve unrelated files.
4. Read ~/.claude/settings.json if it exists and note its content.
5. Run from the CCGM repository root. For a new global install:
     cd ~/code/ccgm
     CCGM_NON_INTERACTIVE=1 \
       CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo '')" \
       ./start.sh --preset cloud-agent --scope global
   For an existing global install, use ./start.sh --add <missing-module> --scope global for each requested addition instead.
6. Verify: confirm ~/.claude/rules/, ~/.claude/commands/, ~/.claude/hooks/, and ~/.claude/agents/ exist and list their contents.
7. Report: the actual preset or additions installed, existing modules preserved, requested modules added or replaced, and any errors.

This is the large preset for users running autonomous Claude Code agents. It includes multi-agent coordination, session history, startup dashboard, xplan, and domain-specific modules (supabase, cloudflare, tailwind, etc.). See presets/cloud-agent.json for the full module list.
```

### full

```
Install CCGM (Claude Code God Mode) with the full preset (every stable module).

Steps:
1. Detect my OS (uname -s), shell ($SHELL), and home directory ($HOME).
2. Clone the repo if it does not already exist:
     git clone https://github.com/lucasmccomb/ccgm.git ~/code/ccgm
   If it already exists, pull the latest main:
     cd ~/code/ccgm && git fetch origin && git checkout main && git pull --ff-only origin main
3. Check what is already installed: ls ~/.claude/rules/ ~/.claude/commands/ ~/.claude/hooks/ ~/.claude/agents/ 2>/dev/null
   Inspect ~/.claude/.ccgm-manifest.json and the requested presets/full.json. For an existing global install, add only requested missing modules with --add; a preset reinstall can replace selected module-owned files. Preserve unrelated files.
4. Read ~/.claude/settings.json if it exists and note its content.
5. Run from the CCGM repository root. For a new global install:
     cd ~/code/ccgm
     CCGM_NON_INTERACTIVE=1 \
       CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo '')" \
       ./start.sh --preset full --scope global
   For an existing global install, use ./start.sh --add <missing-module> --scope global for each requested addition instead.
6. Verify: confirm ~/.claude/rules/, ~/.claude/commands/, ~/.claude/hooks/, and ~/.claude/agents/ exist and list their contents.
7. Report: the actual preset or additions installed, existing modules preserved, requested modules added or replaced, and any errors.

This installs every stable module. See presets/full.json for the complete list.
```

---

## How to test without running it

To verify a paste-block works without touching your real `~/.claude/`:

**Option 1: Temp HOME (macOS/Linux)**

```bash
export HOME_BACKUP=$HOME
export HOME=$(mktemp -d)
mkdir -p "$HOME/.claude"
# Paste the block into a fresh claude session with this HOME active.
# Inspect $HOME/.claude/ when done.
export HOME=$HOME_BACKUP
```

**Option 2: Isolated VM or container**

Spin up a clean Linux VM or Docker container, install Claude Code, and paste the block there. No real config is touched.

**Option 3: Dry-run the installer directly**

The paste-block runs `./start.sh --preset <name>`. You can test that step standalone without the agent scaffolding:

```bash
cd ~/code/ccgm
CCGM_NON_INTERACTIVE=1 ./start.sh --preset minimal
```

Watch the output. If the installer exits 0 and the expected files appear in `~/.claude/`, the block will behave the same when an agent runs it.

**What to check after a test run:**

- `~/.claude/rules/` contains the expected `.md` files for the preset
- `~/.claude/CLAUDE.md` exists (if `global-claude-md` was in the preset)
- `~/.claude/settings.json` was created or merged non-destructively
- No pre-existing files were deleted (compare against a backup if testing in your real HOME)
