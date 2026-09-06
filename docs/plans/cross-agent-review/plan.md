# CCGM cross-agent review: first delivery

Updated September 5, 2026 after external review and the user's review-count correction. Status: implementation plan; integrations and command changes are not installed by this document.

## Outcome and scope

Deliver a small local cross-agent review capability, usable from Claude Code and Codex. Pilot it in standalone adrev, X-Plan / X-Plan A, and ETP. Review agent-produced work with the opposite provider, resolve findings using evidence, and return control to the initiating session. Both providers must support the final disposition; agreement alone never proves correctness.

The first delivery has two changes: a minimal integration module and the pilot workflow wiring. Reuse existing provider integrations before writing equivalent process management. Broader Codex skill projection, memory/history integration, hooks, services, Dreaming, and installer profiles remain a separate follow-on roadmap. They are still part of the intended destination, but are not dependencies of this pilot. Dual implementation and automatic selection between competing implementations are also outside this delivery.

## X-Plan and X-Plan A: choose reviews before planning

Both `/xplan` and `/xplana` ask at startup: "How many adversarial reviews should this plan receive?" Offer `1 (default)`, `2`, and `3`. The user's final correction was default one, not two. Resolve this before research, planning agents, directory setup, or source synchronization begins.

- Add `--adversarial-reviews <1|2|3>` to both commands. An explicit argument or an unambiguous count supplied with the request answers the startup question; do not ask twice. Reject missing flag values, non-integers, zero, and values above three before side effects.
- In an interactive session, show one as the recommended/preselected answer and wait for submission. Preselection and elapsed time are not an answer. If the question tool is unavailable, ask in plain text and wait. In an explicitly unattended invocation with no interaction channel, use one and record `unattended-default`; do not claim the user selected it.
- X-Plan A makes this one setup choice before its autonomous pipeline. After that it retains its no-mid-flow-prompts behavior and final execution gate. The alias forwards the resolved count to X-Plan without a second prompt.
- The count controls adversarial passes only. Constructive review selection is separate; choosing fewer constructive reviews must not silently cancel the selected adversarial passes. The choice applies to light and autonomous planning too.
- A fresh `--deepen` invocation also resolves the choice before starting and runs the selected passes on the updated plan. A resumed interrupted run restores its saved count and completed-pass state instead of asking again or restarting reviews. A later material edit invalidates affected review evidence.
- Persist `adversarial_review_count`, its source, the original provider, policy version, artifact hashes, and completed passes in the run record. Summaries and the final gate require exactly the selected artifacts, not three hardcoded filenames.

The sequence starts opposite the original planning provider and alternates, using a fresh reviewer session for every pass. The last selected pass is always the final pass, followed by handback to the original host:

- Claude-origin, one review: Codex → Claude handback. Two: Codex → Claude → Claude handback. Three: Codex → Claude → Codex → Claude handback.
- Codex-origin, one review: Claude → Codex handback. Two: Claude → Codex → Codex handback. Three: Claude → Codex → Claude → Codex handback.

One pass still checks the whole plan: premises, execution/failure modes, reversal costs, coherence, and the existing execution tenets. Additional passes emphasize different lenses and examine the revised artifact; a lower count must not silently omit a required safety or execution check. The number of selected passes is separate from the bounded exchanges used to resolve findings within a pass.

## Baseline and governing decisions

The original inventory covers checkout `6e2ca8851ba94ae5f1a332e02285337d2cf75e5e`: 78 modules and 508 declared entries. The external review was checked against `origin/main` at `6255bc1ad8cab245362372d998142051a4fbda18`: 79 modules, including advisor-mode, 22 commits ahead. Treat the original catalog and passing test logs as a dated snapshot, not current-main acceptance evidence.

Before implementation, refresh and pin the default-branch SHA in an isolated feature checkout, inspect all changed pilot sources, and record the anchor in the implementation record. Do not pull into another session's working tree. Reconcile the advisor dispatch guard and its three-fix-round rule explicitly with the new shared review policy; do not bypass the guard or assume every MCP tool requires a new allowlist entry.

Decision principles: satisfy the actual goal; prefer a tested existing transport; keep review evidence independent of the implementer's self-report; keep one writer per artifact; choose the supported solution regardless of provider; bound execution mechanically; surface unresolved work honestly. Model choice is provider-specific and follows current model-vetting guidance, not a Claude model name copied into Codex.

The maintained plan sources are this file, `review-protocol.md`, `review-sites.json`, and `review-response.md` in `docs/plans/cross-agent-review/`. The original audit directory remains a local HTML preview and compatibility copy. These maintained sources are eligible for normal version control; the local inventory, machine details, screenshots, and test logs remain excluded.

## Rollout: two reviewable changes

### 1. Minimal local integration — unit CR-01

Owner: integration implementer assigned at execution. Reviewer: opposite provider from that implementer. Deliver as its own issue and PR; allocate the real issue number when execution starts and record it against CR-01. Dependency: refreshed baseline and an inspected transport decision.

Proposed module: `modules/cross-agent-review/`, with a manifest, README/manual setup, one review entry point, a small provider adapter, result schemas, and fixture tests. Add the minimal Codex entry point needed to request this review; do not build a general CCGM exporter. Record installation ownership and keep removal scoped to module-owned files.

Evaluate the official `openai/codex-plugin-cc` first for Claude → Codex. It already provides normal/adversarial review and background operations. Reuse the supported interface when it can satisfy the request/result contract. Otherwise use the documented Codex MCP agent endpoint or local CLI and record the specific missing capability. Pick one primary path per direction instead of registering duplicate plugin/MCP routes. For Codex → Claude, invoke an actual Claude agent through the unmodified `claude -p` interface. `claude mcp serve` exposes tools, so it is not an interchangeable Claude reasoning endpoint.

Keep the coordinator synchronous and local for the pilot: bounded calls, provider selection, validated results, saved run records, timeout and cancellation through the chosen transport. Reuse native background/status/cancel facilities when selected. Do not build a daemon, a general job scheduler, a shared token reservation service, or automatic crash recovery. An interrupted run saves an explicit incomplete state; explicit continuation retains the existing limits and evidence.

Review from immutable snapshots with read-only source access. Scope permitted tools separately from sandboxing and disable unrelated mutating MCP tools; `approval-policy: never` means no approval prompts, not read-only by itself. Reviewers return findings through structured output; the coordinator writes the ledger. A designated implementer applies accepted changes in its workspace. Preserve each binary's native authentication; the adapter must not extract or forward subscription credentials. Specify and test the actual effective restrictions on both transports.

Acceptance: tiny authenticated smoke tasks demonstrate both real provider directions, artifact identity, structured findings, and original-host handback. A capability probe establishes whether the plugin meets plan-file and structured-result requirements. Deterministic fixtures verify explicit producer routing, malformed output despite exit zero, missing provider/authentication, permission denial, quoted paths, timeout, cancellation, stale artifacts, no recursive dispatch, and persistence of counters. A write attempt and unrelated mutating tool call must fail under the reviewer profile. No same-provider fallback or empty/error response may pass as a completed review.

### 2. Pilot workflow policy and review-count setup — unit CR-02

Owner: workflow implementer assigned at execution. Reviewer: opposite provider from that implementer. Deliver as a second issue and PR depending on CR-01; record its real issue number before implementation. Update maintained module sources and their documentation, including the X-Plana alias, X-Plan mode/model tables, Phase 0, Phase 5.7, deepening, resume/status, and final artifact checks.

Implement the startup selection and all six provider/count sequences specified above. Reviewers read the completed plan independently; within each selected pass, freeze the artifact while a reviewer and the other provider settle the findings. Only then apply accepted fixes and revalidate the changed artifact. Return the selected number of reports and the final state to the original host. Unresolved material findings block an execution-ready status; a final presentation is not proof that review passed.

Pilot standalone adrev and ETP's spec-compliance then code-quality stages through the same policy. Route each stage opposite that work unit's actual producer, including fixes and follow-ups. Unknown or materially mixed authorship requires both perspectives. Preserve report-only behavior and the separate CI-repair policy. Limit shared-rule changes to the pilot integration and its necessary advisor-mode compatibility; do not activate untested callers elsewhere by changing a global default.

Replace bare agreement with the evidence protocol in `review-protocol.md`: stable finding IDs; `AGREE`, `DISAGREE_EVIDENCE`, and `DISAGREE_CONCERN`; a frozen artifact during dispute; targeted tests; one designated writer; mutual evidence-backed closure. The orchestrator coordinates and proposes dispositions but cannot overrule a supported objection through authority alone. Missing goal decisions go to the user at the appropriate gate. Resource exhaustion records an unresolved result.

Acceptance: scenarios cover absent/explicit/invalid review counts, the prompt occurring before planning side effects, X-Plana prompting once then remaining autonomous, light and deepen behavior, saved choices on resume, all six alternating sequences, final-pass labeling for N=1/2/3, and exactly N required review artifacts. ETP scenarios cover both producer directions and mixed units. Resolution scenarios cover valid objections, refuted objections, uncertainty without evidence, a clean review with no invented findings, changed-artifact invalidation, and an unresolved limit. Tests must verify behavior rather than only matching instruction text.

## Verification and completion contract

- Add deterministic adapter/contract tests and a fixture end-to-end pilot workflow to the existing CI test workflow. They are required PR checks and use recorded/mock provider responses without credentials. Include must-fail scenarios, not just successful routing. Verify the required check names in repository branch protection; if changing protection is outside execution authority, record the precise remaining administrative step and do not claim merge gating is configured.
- Validate prompt-driven behavior with small authenticated cases for both X-Plan variants, the six provider/count schedules, and one opposite-provider ETP unit per direction. Record the tested provider/CLI/plugin versions and reviewed hashes. Stub tests do not prove a language agent obeys the startup prompt. Live-provider smoke evidence is a separate release prerequisite, not a nondeterministic test on every PR.
- Run the repository's module, personal-data, and installer checks plus applicable existing workflow tests on the implementation branch. Record results for that SHA; do not reuse the initial audit's passing baseline as implementation validation.
- Keep browser artifact verification headless. Any future visible application testing belongs on the dedicated runner with a recorded grant naming the steps and runner. This pilot does not require dictation, input injection, or device testing. Opening the requested HTML for the user is document delivery, not permission to automate their desktop.
- Track discoveries against CR-01/CR-02. Complete in-scope follow-ups with the same opposite-provider review and checks before declaring the delivery done. Wider runtime integration goes into a separately labeled backlog; it must not expand this pilot silently. A blocked mandatory item keeps the delivery incomplete and includes its exact next action.
- After each merge, run `/docupdate` and complete any resulting in-scope documentation fix. Completion requires installed pilot entry points, verified routing, the requested startup choice, current green checks, and no unresolved required follow-up.

## Resource controls and measurement

Use hard elapsed-time and dispatch-count admission limits with a saved run record. Proposed conservative pilot policy: one review run active at a time; at most 24 provider invocations per plan-review sequence or work-unit review; 10 minutes per invocation; 45 minutes for a plan-review sequence and 30 minutes for a work unit. These are explicit policy defaults to calibrate, not claims about expected cost or ideal performance. The smaller remaining deadline always wins.

Retain three artifact-fix rounds per unit as the default checkpoint. Continuing beyond it requires an explicit recorded extension supported by new evidence and a viable next investigation, still within the same overall deadline and invocation allowance. Do not reset spent counters on retry or continuation. Keep at most five reviewer/critic exchanges per frozen-artifact dispute; switch method after two unchanged exchanges, or stop unresolved if no useful discriminating check remains. Update advisor-mode and ETP to reference this rule consistently when the pilot is activated.

Record tokens when available, elapsed time, dispatches, fix rounds, finding validity, and provider quota/rate-limit signals. Remove the former uncalibrated 100k/40k/250k token pools and atomic reservations. Quota can be unavailable: record unknown instead of scraping credentials or inventing remaining capacity. Known quota exhaustion prevents new dispatches. Cancellation stops local work; it does not promise cancellation of already-accounted remote usage.

Evaluate 12 representative pilot tasks across planning and completed work, including clean tasks and seeded defects, then continue observation during normal use. Report confirmed findings per review, false positives, missed seeded defects, regression checks, resolution rate, latency, and measured usage. Tag findings as both / Claude-only / Codex-only only when independent observations justify the label; agreement after discussion is not independent corroboration, and overlap is not a correctness oracle. Decide expansion from useful findings and reliable bounded behavior, not elapsed weeks alone.

## Later expansion

After the pilot passes its acceptance gates, migrate the remaining sites in `review-sites.json` in separate batches: document/ce-review, reusable reviewers/todo flows, visual and agent-native judging, and rule pressure-testing. Preserve each site's evidence boundary and existing stricter stop conditions. Require an explicit coverage classification for new adversarial callsites.

Then scope the broader Codex integration separately: generated skills and capability routing; history and learnings; tested lifecycle/permission adapters; optional services/browser routes; installer/update/uninstall profiles; and Dreaming transcript/evidence support. Preserve existing user configuration choices. The catalog in the local HTML remains background inventory, not a commitment to port every module in this delivery.

## Sources and review disposition

Transport reuse is grounded in the [official Codex plugin](https://github.com/openai/codex-plugin-cc), [Codex MCP agent interface](https://learn.chatgpt.com/docs/mcp-server), and [Claude programmatic CLI](https://code.claude.com/docs/en/headless). The distinction between tools and a reasoning agent comes from [Claude's MCP server documentation](https://code.claude.com/docs/en/mcp#use-claude-code-as-an-mcp-server).

The [Adversarial Review paper](https://arxiv.org/html/2608.18167) motivates structured, evidence-grounded disagreement. Its improved protocol still seeks convergence and uses bounded exchanges; its same-model experiments do not establish the optimal cross-provider review count. The user's choice sets the count here. Keep authentication within the published binaries and follow the applicable [Claude authentication and usage terms](https://code.claude.com/docs/en/legal-and-compliance); this local pilot is not a hosted credential-sharing service.

See `review-response.md` for the disposition of each external-review finding, and `review-protocol.md` for the request/result and resolution contract.
