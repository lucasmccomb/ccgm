# Cross-agent review protocol — pilot

> Historical rollout specification. The mandatory cross-provider release prerequisite below is superseded: current workflows use personal lead review by default and explicit cross-provider opt-in. See the [current workflow contract](../../../modules/cross-agent-review/skills/cross-agent-review/references/workflow.md). This document preserves the original delivery requirements, not current execution instructions.

Updated September 5, 2026. Proposed contract for CR-01 and CR-02. A documented capability is not an installed capability.

## Ownership and provider identity

Record `origin_provider` and `origin_session_id` for the initiating workflow, and `producer_provider` with contribution provenance for each artifact/work unit. Provider means the actual Claude Code or Codex runtime. Derive identity from launch metadata, not a persona, prose, Git username, or the orchestrator's preferred model.

For completed work, `review_provider = opposite(producer_provider)`. A Claude orchestrator using a Codex implementer therefore gets a Claude reviewer for that unit. Route spec and quality stages independently from the same recorded producer, retaining their order. A material reviewer-authored fix requires validation from the other provider. Unknown provenance requires reconstruction from run records or independent review by both providers; it cannot be relabeled to pass routing.

One designated writer edits the target. Reviewers receive immutable snapshots and restricted read access; the coordinator writes their returned reports into an isolated run directory. Review children cannot launch further reviewer jobs. No same-provider substitute may report successful cross-agent review.

## Startup choice: X-Plan and X-Plan A

Before starting a fresh planning or deepening pipeline, ask how many adversarial reviews to run: one, two, or three, with one recommended/preselected. The startup choice occurs before research, source sync, directory creation, or planning-agent dispatch. It applies to default, light, and autonomous modes. X-Plan A is autonomous after this setup choice and still retains its final execution gate.

An explicit `--adversarial-reviews <1|2|3>` or clear count in the invocation satisfies the choice. The alias forwards the resolved value; it does not prompt twice. Validate malformed/out-of-range values before side effects. If interactive, wait for the answer; a preselected default never submits itself. If the invocation is explicitly unattended with no question channel, use one and record `unattended-default`. Persist the chosen count and its source.

A resumed run restores the saved choice, limits, completed passes, and reviewed hashes. Do not assume a legacy run used one or three: use its explicit recorded policy or require a new choice if it cannot be recovered. Material edits after a completed pass invalidate affected acknowledgments. A new deepen request gets its startup selection and reviews the updated plan; a pure resume does not re-ask.

Constructive review options remain separate. Skipping constructive review or selecting light mode must not discard the selected adversarial count. The count is the number of independently started adversarial passes, not a limit of one response or one fix per pass.

## Alternating sequence and handback

For origin `O`, opposite provider `P`, and selected count `N`, schedule the first N entries of `[P, O, P]`. Each entry is a fresh reviewer session, including a same-provider middle pass. Reviewer selection remains relative to the original planner, not whoever last edited the plan.

- N=1: P reviews; original O receives handback.
- N=2: P reviews, then a fresh O reviewer; original O receives handback.
- N=3: P reviews, then a fresh O reviewer, then a fresh P reviewer; original O receives handback.

Every pass covers premises, execution, failure modes, expensive-to-reverse decisions, whole-plan coherence, and the existing execution tenets. With multiple passes, use those areas as differing emphases rather than mutually exclusive checklists. The final pass is pass N, even when N is one. Numbered passes are sequential: incorporate validated fixes and complete the self-check before the next pass starts. A clean early pass does not waive a later pass the user selected.

Return the final artifact hash, N reports, findings ledger, evidence, resource usage, and terminal status to the original host. If the original session cannot receive the handoff, record `HANDOFF_PENDING` separately from review status; do not claim delivery occurred. The execution gate verifies exactly N completed current-artifact pass records. Unresolved required findings or invalidated evidence cannot be marked execution-ready.

## Evidence-grounded disagreement

1. Fix the decision basis: actual user goal, acceptance criteria, hard constraints, source anchor, and artifact hash. The initial review reads the spec and artifact, without the implementer's persuasive self-report. Later exchanges may inspect rebuttals. Keep the artifact frozen while the findings are disputed.
2. Record each substantive finding with stable ID, severity, requirement reference, artifact hash, concrete evidence, proposed remedy, and disposition. An independent clean review is valid; do not manufacture objections to fill a quota. Keep optional preferences within the stated scope.
3. The other provider audits each finding with `AGREE` (evidence supports it), `DISAGREE_EVIDENCE` (cited code, reproduction, or requirement contradicts it), or `DISAGREE_CONCERN` (uncertainty requiring a specific discriminating check). Concern alone cannot refute a supported finding; agreement alone cannot establish it. These verdicts are separate from final finding dispositions.
4. Use a targeted test, primary-source check, or comparison against acceptance criteria to resolve disputed facts. Log command/output references or exact source evidence. Confidence, provider prestige, repeated assertions, and majority votes are not sufficient. Both agents must consider a better alternative regardless of its author.
5. Once the review signal stabilizes, send accepted changes to the designated writer. Record dispositions as `fixed`, `refuted`, `duplicate`, or `outside_scope`, with evidence and both providers' acknowledgment. Scope changes cannot waive a hard requirement. Re-run affected deterministic checks and obtain opposite-provider validation of material changes. Unaffected findings can retain their evidence when the dependency mapping justifies it.
6. Close as `CONSENSUS` only when both providers acknowledge the final artifact and substantive dispositions, all selected passes completed, required checks pass, and no required finding remains open. A mutual signature is not a proof of optimality; the evidence and scope are independently checked. The coordinator proposes and records dispositions but cannot close a disputed finding unilaterally.

Distinguish independently discovered findings from post-discussion agreement. `both`, `claude_only`, and `codex_only` discovery labels describe original independent observations only. Do not add a second full independent review to every ETP stage just to populate overlap metrics; collect them where the selected workflow actually supplies both perspectives.

## Bounded continuation

The pilot serializes review runs, so a single persisted counter is sufficient; a concurrent global budget allocator is outside scope. Before every provider invocation, check the run status, remaining deadline, invocation allowance, per-unit fix count, and any known quota exhaustion. Native transport cancellation/time limits handle the child call; the coordinator records the outcome and remaining allowance.

Proposed defaults: at most 24 provider invocations for a plan-review sequence or completed-work unit; at most 10 minutes per invocation; 45 minutes overall for a plan-review sequence, 30 minutes for a work unit. The parent deadline takes precedence. All reviews, critics, rebuttals, delegated fixes, retries, and revalidations launched for this review count. Author activity that cannot be accounted or bounded must not be presented as covered by the limit.

Within a frozen-artifact dispute, use at most five reviewer/critic exchanges. After two exchanges with no new evidence or changed disposition, switch to a concrete discriminating check; stop if none is useful. Retain three artifact-fix rounds per unit as the default checkpoint. A further batch requires an explicit recorded extension and a viable evidence-producing next action; it retains the original overall deadline and spent invocation count. There is no automatic extension, counter reset on resume, or guarantee that finite resources always produce agreement. Keep ETP's separate CI-fix policy unchanged.

The old 100k/40k/250k token pools are removed. Record input/output/cache/reasoning usage when supplied by the provider, avoiding double-counting, and mark missing telemetry. Measure quota signals through supported interfaces only. Quota unknown is not quota available; use the conservative local limits and report uncertainty. Known exhaustion stops dispatch. Do not claim subscription capacity is interchangeable with a token count or guarantee that cancellation reverses already-incurred usage.

At an overall limit or fix checkpoint without extension, save `UNRESOLVED_BUDGET` with open findings, evidence, both positions, best current artifact, counters, and the next useful check. A repeated dispute without a viable next check becomes `UNRESOLVED_DISPUTE`. Missing product intent becomes `NEEDS_GOAL_DECISION`; missing provider/auth/capability becomes `NEEDS_PROVIDER`. These states never pass review or permit the affected unit to merge. An unresolved unit need not block independent work that still has authorization and resources.

## Minimal transport and result contract

CR-01 evaluates `openai/codex-plugin-cc` before building equivalent functionality. Use its supported interface if it meets the review request/result needs; otherwise document the gap and select the Codex MCP agent endpoint or CLI. Use one primary path per direction. Codex-hosted Claude review requires an actual `claude -p` agent; `claude mcp serve` provides tools and is not that agent.

The request contains: run ID, original host session/provider, actual producer provenance, shared goal/spec paths, frozen artifact/hash and source anchor, role/lenses, workflow mode, selected pass count and current pass, permitted tool scope, effective limits, and output schema version. Pass narrow file references rather than an entire transcript.

The result contains: launch-verified provider/model/session identity, reviewed artifact/hash, structured findings and evidence references, verification results, proposed dispositions, usage completeness, and explicit status. The coordinator owns the result files and final ledger. Validate JSON parsing, required fields, enums, hashes, provider identity, and terminal status locally. An exit-zero process or a `--output-schema` flag does not establish validity. Distinguish a CLI event stream from its final structured payload. Invalid/truncated/YAML-like output is `INVALID_RESULT`, never an empty clean review; any retry consumes the existing allowance.

Persist request, state, reports, evidence references, limits/counters, and final result in the workflow's review directory or a gitignored `.context/cross-agent-review/<run-id>/`. Checkpoint before dispatch and after result handling. An interrupted in-flight call stays incomplete; do not silently replay it on restart. First delivery supports explicit continuation using recorded state and native session facilities where available, not automatic recovery of arbitrary running jobs.

## Permissions, authentication, and advisor compatibility

Use immutable input snapshots and read-only repository access. For Codex, require the effective read-only sandbox and no-prompt approval policy; explicitly restrict unrelated MCP and execution capabilities because filesystem sandboxing does not make every remote tool read-only. For Claude, configure and test its effective read/tool restrictions instead of assuming Codex flags exist there. Return review text through the transport; the coordinator writes outputs. No reviewer receives general apply, commit, push, credential-reading, or provider-dispatch tools.

Each unmodified provider binary uses its own native authentication. CCGM must not read, copy, log, or proxy subscription tokens. Do not introduce API credentials silently where a selected CLI mode cannot use the intended authentication. This is a local individual workflow; any later hosted/resold service requires a separate design and applicable provider agreement. See the linked official authentication/usage documentation in the plan.

Read the current advisor guard before changing dispatch permissions. Permit only the specific orchestration interface needed by the pilot, without relaxing implementation-write restrictions on the main agent. Reconcile its adjudication and three-fix-round text with this shared pilot policy. Do not treat the mere existence of an MCP transport as proof it is blocked or exempt from capability checks.

## Coverage and release evidence

Pilot sites: X-Plan/X-Plana plus resume/status consumers, standalone adrev, and ETP's two review stages. Shared reviewer instructions, advisor-mode, manifests, docs, and status interpretation receive only necessary pilot compatibility changes. Other review sites remain recorded as later batches; no global switch claims they are migrated.

CR-01/CR-02 are complete only with deterministic CI contract coverage, small real-provider smoke evidence, the six origin/count sequences, startup and resume behavior, valid/refuted/uncertain finding cases, required-write-denial checks, timeout/cancel persistence, and current repository checks. Test the language-agent behavior separately from parsing and routing fixtures. Same-provider fallback, stale acknowledgments, malformed results, missed required checks, and unresolved findings must all fail the completion gate.

Live-provider checks stay small and attributable. Browser artifact checks stay headless; any later visible app/input/device test needs a dedicated runner and recorded grant. Missing mandatory evidence is an incomplete release prerequisite, not a successful test. Record in-scope follow-ups and complete them before closing the delivery.
