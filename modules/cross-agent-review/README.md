# cross-agent-review

A local, synchronous review coordinator for Claude Code and Codex. It selects the actual opposite provider, supplies a frozen evidence bundle to that provider's native agent, validates structured findings locally, and saves bounded invocation state for explicit continuation. The transport does not edit reviewed files or decide consensus. The pilot policy supplies separate startup, stage, evidence and final acknowledgment gates for X-Plan, adrev and ETP.

## Install

Requires Python 3.9+, macOS/Linux, native Claude Code and Codex CLIs, and each provider's own authenticated login. The Codex profile was exercised with CLI 0.153.4; unsupported flags fail explicitly instead of weakening restrictions.

Run the following from the CCGM repository root after an existing global CCGM installation. `--add` extends that installation. For a fresh installation, complete the normal global setup with `bash start.sh` first, or use [Manual Installation](#manual-installation) below.

```bash
bash start.sh --add cross-agent-review
python3 ~/.claude/bin/cross-agent-review-setup.py install
```

The first command installs the Claude entry point and runtime through CCGM's existing ownership manifest. The second optionally copies only the self-contained `cross-agent-review` skill into `${CODEX_HOME:-$HOME/.codex}/skills/`, with a per-file ownership/hash manifest. It does not modify Codex configuration, MCP registrations, authentication, or other skills. Restart or refresh the relevant host to discover the skill.

To update, first update the CCGM checkout and reinstall the Claude-side files through the [CCGM update flow](../../docs/installer.md#updating), including `cross-agent-review` in the module selection, or repeat the manual copies from the updated source. `--add` skips modules already installed; it is for additions, not upgrades. Then update the separate owned Codex copy:

```bash
python3 ~/.claude/bin/cross-agent-review-setup.py install
```

Restart or refresh Codex after the copy succeeds. Updating the Claude files or restarting Codex alone does not update that copy.

Remove the Codex entry point before removing the Claude-side setup script:

```bash
python3 ~/.claude/bin/cross-agent-review-setup.py remove
```

Removal preserves unrelated files and refuses changed module-owned files or unowned existing skills. The ordinary CCGM uninstall path owns the Claude files. Review run records are user evidence and are not deleted by skill removal.

## Use

Invoke the `cross-agent-review` skill from either host, or use the stable CLI:

```bash
python3 ~/.claude/lib/cross_agent_review.py schema request
python3 ~/.claude/lib/cross_agent_review.py init --request request.json --run-dir /path/to/private/review-run
python3 ~/.claude/lib/cross_agent_review.py invoke --run-dir /path/to/private/review-run --role reviewer --pass 1
python3 ~/.claude/lib/cross_agent_review.py status --run-dir /path/to/private/review-run
```

Read the [request/result and continuation contract](skills/cross-agent-review/references/contract.md). Work routes from the actual producer, not the orchestrator. Plans use the selected prefix of opposite/origin/opposite. Unknown or mixed work requires both explicit perspectives. The [pilot workflow policy](skills/cross-agent-review/references/workflow.md) supplies X-Plan's upfront 1–3 review choice (default one), ETP's spec-before-quality stages, bounded evidence resolution, current-artifact acknowledgments and original-host reception. It does not activate other review sites.

A `REVIEWED` state means a structurally valid, attributable report. It never means `CONSENSUS`, execution readiness, or merge permission. Reports retain `HANDOFF_PENDING` until the calling workflow actually delivers them to the original host. Errors and missing evidence are never converted into clean reviews.

## Effective restrictions and evidence boundary

Claude uses native print mode with safe mode, restricted mode, an empty tool allowlist, empty strict MCP configuration, no Chrome, no persisted session, and structured output. Codex uses native `exec` with ignored user/rule configuration, strict config, an isolated temporary working directory, read-only sandbox, no-prompt approvals, disabled web/MCP/apps/plugins/hooks, disabled execution tools, and `agents.enabled=false` plus disabled multi-agent feature flags. The coordinator forwards a small environment allowlist and deliberately excludes ambient API credentials and inherited parent permission/session overrides. Native login stays with each unmodified binary.

Codex may expose its patch tool even with execution disabled; the read-only sandbox denies actual writes. Pure computation/time utilities can remain available. This is why capability restrictions and filesystem sandboxing are separate controls. Native capability probes, rather than a model's statement that it is read-only, verify denied writes and the absence of execution/remote/child-agent capability. See the [transport decision](../../docs/plans/cross-agent-review/transport-decision.md).

Reviewers receive only explicitly listed, bounded UTF-8 artifact/spec/source/test-evidence contents. They do not explore the repository or read private machine configuration. More than 64 files or 512 KB fails without truncation; supply a narrower meaningful unit, or respond to a precise missing-evidence request. This boundary is useful for reproducible small reviews, but does not substitute for repository-wide investigation or independently executing tests. The designated author/coordinator supplies independently recorded test evidence as needed.

## Validation

```bash
python3 -m unittest discover -s modules/cross-agent-review/tests -v
bash tests/test-modules.sh
bash tests/test-no-personal-data.sh
bash tests/test-installer.sh
```

Deterministic tests invoke fake native envelopes in isolated temporary directories, covering routing, invalid output, immutable hashes, authentication selection, limits, interruption, reversible installation, and deterministic workflow gates. They run in both existing required `module-tests` CI jobs. Tiny authenticated provider tasks and mechanical capability probes are separate release evidence; fixtures do not establish actual agent behavior.

## Manual installation

From the module directory, without the CCGM installer:

```bash
mkdir -p ~/.claude/lib ~/.claude/bin ~/.claude/skills
cp lib/cross_agent_review.py lib/cross_agent_review_policy.py ~/.claude/lib/
cp bin/cross-agent-review-setup.py ~/.claude/bin/
cp -R skills/cross-agent-review ~/.claude/skills/
python3 ~/.claude/bin/cross-agent-review-setup.py install
```

Manual copies are operator-owned; preserve any existing files before copying. Use the setup script for the optional Codex copy so removal can verify ownership. A marketplace install exposes the self-contained skill directly from its plugin root; the bash installer is the canonical path for the additional stable library/setup locations.
