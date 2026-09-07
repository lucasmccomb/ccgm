# cross-agent-review

A local, synchronous review coordinator for Claude Code and Codex. It selects the actual opposite provider, supplies a frozen evidence bundle to that provider's native agent, validates structured findings locally, and saves bounded invocation state for explicit continuation. The transport does not edit reviewed files or decide consensus. X-Plan, adrev and ETP use personal lead review by default, with ordinary tests/CI/release checks. Explicit `--cross-provider` or natural-language opt-in enables the pilot’s separate startup, stage, evidence and acknowledgment gates.

## Install

Local helpers require Python 3.9+ and macOS/Linux. Optional native review additionally requires Claude Code and Codex CLIs and each provider’s own authenticated login; default lead review does not. The Codex profile was exercised with CLI 0.153.4; unsupported flags fail explicitly instead of weakening restrictions.

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

Explicitly request the `cross-agent-review` skill, or add `--cross-provider` to X-Plan, X-Plan A, adrev or ETP. The local selector still asks X-Plan users for 1–3 passes (default recommendation one) in lead mode. Before optional planning/work, check both native binaries and login readiness:

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py preflight
```

`AVAILABLE` is local readiness, not a successful model review. `NEEDS_PROVIDER` stops the optional path. Follow the [workflow commands](skills/cross-agent-review/references/workflow.md) for `init --cross-provider` and its required arguments. Without that flag, `init` returns `LEAD_REVIEW`, creates no run and grants no execution approval.

Keep private run/control files under `~/.claude/cross-agent-review/<run-id>/`. Advisor mode permits only the trusted installed policy shim, not direct transport scripts. Outside advisor mode, the lower-level stable `cross_agent_review.py` CLI remains available for explicit transport requests; its direct `init` creates a native-review run and is not the lead-mode selector.

Read the [request/result and continuation contract](skills/cross-agent-review/references/contract.md). Work routes from the actual producer, not the orchestrator. Plans use the selected prefix of opposite/origin/opposite. Unknown or mixed work requires both explicit perspectives. The [pilot workflow policy](skills/cross-agent-review/references/workflow.md) supplies X-Plan's upfront 1–3 review choice (default one), ETP's spec-before-quality stages, bounded evidence resolution, current-artifact acknowledgments and original-host reception. These native gates apply only to opted-in runs; they do not activate other review sites.

A `REVIEWED` state means a structurally valid, attributable report. It never means `CONSENSUS`, execution readiness, or merge permission. Reports retain `HANDOFF_PENDING` until the calling workflow actually delivers them to the original host. Errors and missing evidence are never converted into clean reviews.

Native generation schemas constrain all six identity fields to the invocation's exact expected values; local validation still checks them independently. Rejected identity output remains `INVALID_RESULT` with no validated report. Failed calls retain native usage and bounded identity mismatch evidence, without copying arbitrary returned values into diagnostics; see the [runtime contract](skills/cross-agent-review/references/contract.md#reports-and-continuation).

## Effective restrictions and evidence boundary

Claude uses native print mode with safe mode, restricted mode, an empty tool allowlist, empty strict MCP configuration, no Chrome, no persisted session, and structured output. Codex uses native `exec` with ignored user/rule configuration, strict config, an isolated temporary working directory, read-only sandbox, no-prompt approvals, disabled web/MCP/apps/plugins/hooks, disabled execution tools, and `agents.enabled=false` plus disabled multi-agent feature flags. The coordinator forwards a small environment allowlist and deliberately excludes ambient API credentials and inherited parent permission/session overrides. Native login stays with each unmodified binary.

Codex may expose its patch tool even with execution disabled; the read-only sandbox denies actual writes. Pure computation/time utilities can remain available. This is why capability restrictions and filesystem sandboxing are separate controls. Capability claims require mechanical probes, not a model’s statement that it is read-only. Earlier transport probes are historical evidence for their tested versions; they do not establish that this repair or every installed provider/version has been natively verified. See the [transport decision](../../docs/plans/cross-agent-review/transport-decision.md).

Reviewers receive only explicitly listed, bounded UTF-8 artifact/spec/source/test-evidence contents. They do not explore the repository or read private machine configuration. More than 64 files or 512 KB fails without truncation; supply a narrower meaningful unit, or respond to a precise missing-evidence request. This boundary is useful for reproducible small reviews, but does not substitute for repository-wide investigation or independently executing tests. The designated author/coordinator supplies independently recorded test evidence as needed.

## Validation

```bash
python3 -m unittest discover -s modules/cross-agent-review/tests -v
bash tests/test-modules.sh
bash tests/test-no-personal-data.sh
bash tests/test-installer.sh
```

Deterministic tests invoke fake native envelopes in isolated temporary directories, covering routing, exact identity schemas on both launch paths, safe mismatch diagnostics, invalid output, immutable hashes, authentication selection, limits, interruption, reversible installation, and deterministic workflow gates. They run in both existing required `module-tests` CI jobs. Tiny authenticated provider tasks and mechanical capability probes are separate release evidence; fixtures do not establish actual agent behavior.

## Manual installation

From the module directory, without the CCGM installer:

```bash
mkdir -p ~/.claude/lib ~/.claude/bin ~/.claude/skills
cp lib/cross_agent_review.py lib/cross_agent_review_policy.py ~/.claude/lib/
cp bin/cross-agent-review-setup.py ~/.claude/bin/
cp -R skills/cross-agent-review ~/.claude/skills/
python3 ~/.claude/bin/cross-agent-review-setup.py install
```

Manual copies are operator-owned; preserve any existing files before copying. Use the setup script for the optional Codex copy so removal can verify ownership. A marketplace install exposes the self-contained skill directly from its plugin root and does not install the trusted advisor policy shim. Under advisor mode, use the canonical bash installer/manual stable locations or delegate setup/execution under normal permissions; do not weaken the guard to run a marketplace path.

## Stopping and Interpreting Results

Optional runs default to 8 invocations, 120 seconds per invocation and 900 seconds total; two artifact correction cycles and three exchanges per stage (including acknowledgments). Serialized prompts are capped at 96,000 UTF-8 bytes each and 384,000 cumulative bytes per run. These bounds do not promise a hard native-token or billing ceiling. Explicit request limits may vary only within the contract’s hard ceilings; `extend` rejects expansion.

Provider errors stop the optional run and preserve its reports/findings. Supported retries require explicit resume and are bounded to two identical requests for an unchanged prompt/model/coordinator revision, within the existing total limits. Policy `stop --run-dir ... --file stop.json` records a terminal `STOPPED` reason and preserves counters; it cannot later finish as approved. The lead may separately assess delivery using personal review and normal checks. That decision never labels the stopped native run `CONSENSUS`, and coordinator repairs need no recursive consensus.

`record-check` records caller-supplied execution evidence; it does not run the check. `receive` validates a host-receipt attestation; it cannot prove a particular session read the packet. Evidence-backed scope dispositions still require human/lead/reviewer judgment. The engine checks structural identity, hashes, citations and acknowledgment, not the semantic truth of every claim.

## Why bounded review

See the [research and design decision](../../docs/plans/cross-agent-review/bounded-review-design.md) for the limits, evidence-based adjudication, and why councils and voting remain an explicit future option.
