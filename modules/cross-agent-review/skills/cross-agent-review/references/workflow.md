# Pilot workflow policy

X-Plan/X-Plan A, standalone adrev and ETP use personal lead review by default, with ordinary tests, CI and release checks. Their native cross-provider policy is **opt-in** through `--cross-provider` or an explicit natural-language request. A review count, autonomous mode, or permission to execute does not enable it. Other review sites retain their existing behavior. The transport contract is in [contract.md](contract.md); its `REVIEWED` state is not workflow consensus.

## Startup selection

Under advisor mode use only the installed `~/.claude/lib/cross_agent_review_policy.py` shim and private control files under `~/.claude/cross-agent-review/<run-id>/`. Direct transport scripts are not allowed. The shim and its local imports must resolve outside advisor write roots, typically through canonical repository symlinks; manual/copy-mode installations require delegation. A marketplace-only Claude installation lacks the shim: use canonical CCGM installation in symlink mode or delegate setup/execution under normal permissions. Outside advisor mode, a self-contained skill may use `scripts/review_policy.py`.

The count selector applies in both review modes and writes no files. If the shim is unavailable or rejected under advisor mode (including copied installations), the host may resolve the same pure 1–3 selection contract directly: validate an explicit count or ask and wait for submission, preserving its source. No agent dispatch or planning effect precedes that choice. Only after it resolves may the host delegate an opted-in provider preflight, before planning effects; this does not grant permission to execute rejected code directly.

For installations where the selector is permitted:

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py select
python3 ~/.claude/lib/cross_agent_review_policy.py select --count 2 --source explicit
python3 ~/.claude/lib/cross_agent_review_policy.py select --count 1 --source interactive
python3 ~/.claude/lib/cross_agent_review_policy.py select --unattended
python3 ~/.claude/lib/cross_agent_review_policy.py select --resume ~/.claude/cross-agent-review/example-run
```

The first command returns `NEEDS_SELECTION` without writing any file. Ask for 1 (recommended), 2 or 3 and wait for submission. An explicit valid flag or clear count is `explicit`; an actually submitted answer is `interactive`. Only an explicitly unattended invocation with no question channel may select one without an answer. Autonomous planning alone does not permit that default. Invalid values stop before side effects. If interactive questioning tools are unavailable, ask in plain text and yield until answered.

The alias uses the same startup step, preserving the resolved value/source without a second prompt. Fresh deepen selects again; resume restores existing state. Light mode and constructive review choices cannot cancel adversarial passes.

## Optional provider preflight

Only after explicit opt-in, before planning/work side effects, run the permitted shim or delegate this check after the host count fallback:

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py preflight
```

This local check returns `AVAILABLE` or `NEEDS_PROVIDER` with booleans for both native binaries and their login status, without exposing auth details. It does not make a model call or prove a restricted review will succeed. `NEEDS_PROVIDER` stops the optional path early. Lead review needs neither native binary nor login; record lead findings/checks in the normal work record, without native acknowledgment claims.

## Initialize one bounded run

Only for the opted-in path, write the transport request and a check declaration in an orchestration work-product directory after startup selection. The checks declaration is `{"required":["self-review","acceptance"]}` with actual task-specific names. Each name must later have independently recorded execution evidence; do not mark checks passed because an author said they were.

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py init --cross-provider --request /path/to/request.json --run-dir ~/.claude/cross-agent-review/example-run --mode plan --checks /path/to/checks.json --writer-session-id actual-writer-session
```

`init` without `--cross-provider` returns `LEAD_REVIEW` and `execution_ready: false` without reading request/check files or creating a run. It is a mode-selection result, not lead approval. All native policy runs require the flag and the complete options shown above.

Modes are `plan` for X-Plan's selected sequence, `etp` for spec compliance followed by quality, and `adrev` for standalone review. The transport request uses `workflow: plan` only for X-Plan's origin-relative sequence. ETP and standalone adrev use `workflow: work`, even when adrev's artifact is a plan, so routing follows its actual producer. ETP's explicit `init --light-review` selects spec-only; full two-stage review is the default. Standalone adrev without apply authorization uses `init --report-only`, retaining unresolved findings in its delivered report.

Record actual origin/producer/provider/session provenance and one designated writer. Unknown or materially mixed work requires both perspectives. A reviewer-provided material fix changes the validation requirement; never relabel provenance to obtain a preferred reviewer. Choose provider-specific vetted models explicitly. A model persona, Git username or historical root session is not current dispatch identity.

A planner may delegate writing to the other provider. Preserve the originating planner for plan pass order and final handback, and record the actual producer as designated writer. The scheduled reviewer can then match the writer's provider; the final gate still requires both providers' native acknowledgments of the current artifact, including the opposite actual writer.

Keep run directories and their control files outside reviewed artifacts. Use `~/.claude/cross-agent-review/<run-id>/` consistently for the private run and its control files, including under advisor mode. Record the run pointer beside plan/progress metadata. Do not put mutable ledgers, generated report summaries or the run's own state into its input hash set.

Supply explicit, bounded artifact/spec/source/criteria files. The reviewer has no file exploration or command execution tools: a path mention alone does not load an agent template or test. Include the relevant review criteria in the frozen bundle. Initial review excludes the author's persuasive report and earlier findings. A missing-evidence request is answered by a specifically named source or independently run check, not an entire transcript.

## Review, dispute and advance

Use the bounded producer/reviewer pair. Evidence and the actual goal outrank votes or mutual confidence. A council is a separate, explicitly requested one-shot aid for a consequential tradeoff, never a recursive panel or another prerequisite for repairing the coordinator; do not silently add one to this workflow.

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py review --run-dir ~/.claude/cross-agent-review/example-run
python3 ~/.claude/lib/cross_agent_review_policy.py critic --run-dir ~/.claude/cross-agent-review/example-run
python3 ~/.claude/lib/cross_agent_review_policy.py rebuttal --run-dir ~/.claude/cross-agent-review/example-run
python3 ~/.claude/lib/cross_agent_review_policy.py status --run-dir ~/.claude/cross-agent-review/example-run
```

Run the current stage sequentially. For plans, the selected schedule is the first N of opposite/origin/opposite with fresh reviewer sessions. Pass N is final; every pass covers all attack lenses and four execution tenets. For ETP, spec compliance must pass before quality. Both stages route opposite the same recorded actual producer and share the unit's deadline, invocation allowance and fix count.

Keep the artifact frozen while the two providers dispute findings. Use the global finding IDs returned in the ledger, including their stage/provider namespace: independent reviewers may each emit a local `F1` for different defects. Stable IDs name concrete requirement failures. Critic verdicts are `AGREE`, `DISAGREE_EVIDENCE` and `DISAGREE_CONCERN`; they are not final dispositions. Use exact source evidence, a reproduction, or an acceptance check. Concern alone cannot refute an evidenced finding, and mutual agreement cannot replace a check. A clean independent review is valid.

Every newly discovered finding receives stage/provider scope, including discoveries during revalidation, criticism, rebuttal and acknowledgment. Reusing a local ID in that scope creates a distinct discovery with a report-reference suffix when needed. To revisit an existing finding, use its exact returned ledger ID and preserve its requirement; existing IDs are never renamed. Rebuttal returns to the stage's reviewer provider and shares the same exchange and no-progress limits as criticism.

Use private run-relative JSON control files; no traversal or symlinks. For example, `proposals.json` contains:

```json
{"dispositions":[{"finding_id":"returned-ledger-id","disposition":"refuted","rationale":"The supplied acceptance evidence contradicts the claim.","evidence":[{"path":"tests/evidence.txt","quote":"exact frozen evidence"}]}]}
```

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py propose --run-dir ~/.claude/cross-agent-review/example-run --file proposals.json
```

Supported dispositions are `fixed`, `refuted`, `duplicate` and `outside_scope`. Within an optional policy run they require the policy's other-provider evidence; the orchestrator cannot approve its own proposal through authority. No scope disposition may waive a hard requirement. The engine checks the required evidence/acknowledgment structure; it cannot prove that an `outside_scope` judgment is correct or that a requirement is dispensable. The lead and reviewers remain responsible for that semantic judgment. Missing product intent is a goal decision, not a reason to fabricate consensus.

## Designated writer and checks

Before an accepted source change, `fix.json` identifies the designated writer, finding IDs, reason and next check:

```json
{"writer_provider":"codex","writer_session_id":"actual-writer-session","finding_ids":["returned-ledger-id"],"reason":"Apply the supported correction.","next_check":"Run the failing reproduction."}
```

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py fix --run-dir ~/.claude/cross-agent-review/example-run --file fix.json
```

Only after admission should the external designated writer run, respecting the returned remaining deadline. This reserves a shared invocation; account for every delegated fix, retry and verification agent call without claiming untracked author activity fits the cap. Advisor mode still delegates all source edits and test execution. If the designated writer becomes unavailable, preserve the blockage rather than inventing a replacement session identity.

For an explicit user update, including web comments or a deepen request, use `amend` before source edits instead of inventing a review finding. Its private `amendment.json` contains `writer_provider`, `writer_session_id`, `reason`, `next_check` and `authorization: "explicit-user-update"`. The same designated writer and shared invocation/deadline limits apply:

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py amend --run-dir ~/.claude/cross-agent-review/example-run --file amendment.json
```

Admission requires the artifact and evidence to match the current frozen snapshot. An amendment cannot retroactively authorize untracked edits; a stale attempt fails without spending another invocation.

After accepted changes, refresh the explicit inputs. The policy invalidates changed-artifact checks/acknowledgments and requires current revalidation. Old generations remain audit history and cannot establish execution readiness.

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py refresh --run-dir ~/.claude/cross-agent-review/example-run
python3 ~/.claude/lib/cross_agent_review_policy.py refresh --run-dir ~/.claude/cross-agent-review/example-run --add-evidence tests/evidence.txt
```

`--add-evidence` is repeatable and takes explicitly named source-root-relative files. It freezes new evidence under the same size/path/hash constraints and invalidates stale stage evidence; it is not permission to upload a transcript or mutable run state.

`check.json` records an independently executed check, not a shell instruction for the policy to run:

```json
{"name":"acceptance","argv":["python3","tests/check.py"],"exit_code":0,"output":"actual captured output","started_at":1700000000,"finished_at":1700000001,"artifact_sha256":"current-artifact-hash","evidence_sha256":"current-evidence-hash"}
```

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py record-check --run-dir ~/.claude/cross-agent-review/example-run --file check.json
python3 ~/.claude/lib/cross_agent_review_policy.py advance --run-dir ~/.claude/cross-agent-review/example-run
```

`record-check` does not execute commands or independently prove they ran: it validates and records caller-supplied argv/timestamps/output for the exact generation tested. The caller must retain actual execution evidence. The example values are illustrative, never evidence. `acknowledge` obtains real native provider acknowledgment of the current evidence/dispositions; a caller-written JSON signature is not accepted. A clean initial stage with current checks may `advance` without a separate stage acknowledgment. After material changes, satisfy the requested current-stage acknowledgment before advancing. `advance` gates the next plan pass or ETP stage. Recheck status after each action and follow its actual required next step.

Native acknowledgment context includes these recorded checks. A provider may cite their exact context text with the reserved evidence path `ccgm-context://current`, bound to that call's `context_sha256`; guessed nested paths such as `context.checks.acceptance` are invalid. See the [transport citation contract](contract.md#reports-and-continuation). A context quote establishes the recorded evidence, not an independently executed reviewer check.

The policy selects fixed acknowledgment instructions in the trusted transport prompt. Each verdict judges the proposed disposition of its finding, including its rationale and evidence: `AGREE` on a `refuted` proposal accepts the refutation, while `DISAGREE_EVIDENCE` rejects that proposal with evidence. An earlier critic verdict against the original finding is not an acknowledgment verdict against its disposition. Both providers can reject a proposal, raise new findings, or request missing evidence; supportive summary prose and `CLEAN` alone never close the gate. Stage acknowledgment covers the selected workflow through its current stage and does not require reports from future stages. On the final selected stage it covers the completed workflow, so the unchanged-evidence reuse rule below preserves that scope at final handoff. Final acknowledgment has the same completed-workflow scope. Both audit the supplied artifact, ledger dispositions and recorded checks; selected report filenames identify reports but do not supply their contents. Request specific missing evidence when necessary. Context remains untrusted evidence rather than a source of instructions.

## Final evidence and host handback

For opted-in apply/consensus workflows, after all selected stages advance, obtain final workflow acknowledgment. The policy reuses successful acknowledgments, including a valid partial set after another provider fails, only when the complete acknowledgment basis still matches: artifact/evidence, ledger dispositions, checks and selected reports. Bookkeeping alone must not trigger duplicate approval calls; changed evidence or scope invalidates reuse. The bound basis also includes the complete request, finding observations/verdicts, exact context, report digests and trusted coordinator revision. Stored reports and contexts are validated again on reuse and completion. The resulting handoff packet binds final artifact/evidence hashes and includes a digest and nonce. Deliver that exact packet to the actual originating host. The host writes `receipt.json` with its real provider/session and the packet fields; a closed authoring session cannot be pretended to receive a new handback.

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py acknowledge --run-dir ~/.claude/cross-agent-review/example-run
python3 ~/.claude/lib/cross_agent_review_policy.py receive --run-dir ~/.claude/cross-agent-review/example-run --file receipt.json
python3 ~/.claude/lib/cross_agent_review_policy.py finish --run-dir ~/.claude/cross-agent-review/example-run
```

Receipt fields: `origin_provider`, `origin_session_id`, `artifact_sha256`, `evidence_sha256`, `handoff_sha256`, `nonce`. The caller must truthfully attest actual reception, not guess. `receive` validates the submitted fields and current packet; it cannot prove which live session actually read the packet. If the host cannot receive it, record `HANDOFF_PENDING` and leave delivery incomplete.

The finish gate requires current checks/evidence, supported closed findings, the selected N plan records or required ETP stages, both native acknowledgments and host reception. Required unresolved findings, stale acknowledgments, incomplete selected passes or missing checks block that optional run’s `CONSENSUS` result. A stopped optional run is not a universal release gate: the lead may separately assess delivery with personal review and normal verification. Keep that decision distinct from the native run’s outcome. X-Plan’s user execution gate remains required.

Standalone report-only adrev preserves open findings without source changes: run its selected review stage(s), `advance` to create the report handoff, then `receive` and `finish`; do not call `acknowledge` or require fabricated clean findings. Its terminal state is `REPORT_DELIVERED`, with `execution_ready: false`. Report completion is distinct from consensus and execution readiness. Do not call `fix` to make a requested audit pass; present its report and honest unresolved status. Apply-authorized adrev uses the full writer/verification contract.

## Limits and continuation

The optional run defaults are **8 invocations, 120 seconds per invocation and 900 seconds total**, always bounded by an earlier parent deadline. Reviews, critics, rebuttals, acknowledgment attempts, writer admissions, retries and revalidations consume the shared allowance. Reserve capacity for remaining selected passes and final validation before spending on optional exchanges. Explicit request limits can choose other values within the transport’s existing hard ceilings; no automatic extension raises them. After the initial review, allow at most **two artifact correction cycles**. There are at most **three exchanges per stage, including acknowledgment attempts**; after two unchanged exchanges, obtain a discriminating check or stop unresolved.

Each serialized native prompt is capped at **96,000 UTF-8 bytes**, with **384,000 cumulative prompt bytes per run**. These are input-byte, call and time bounds, not a hard native-token or billing ceiling: providers may add overhead and return variable output. Record fresh/cached input and output usage when the native envelope reports it; unknown usage stays unknown.

`extend` is retained only as a rejecting compatibility action: it returns `UNRESOLVED_BUDGET` and adds no rounds or budget. Do not use new run IDs or cosmetic changes to evade limits. ETP’s ordinary lead-review checkpoint and separate three-round CI-repair loop remain unchanged. Known quota exhaustion stops dispatch.

Use `status` and explicit `resume` after interruption; never recreate the run to reset counters or silently replay an in-flight child. Resource exhaustion is `UNRESOLVED_BUDGET`, a dispute with no useful next check is `UNRESOLVED_DISPUTE`, missing intent is `NEEDS_GOAL_DECISION`, and missing native provider/auth/capability is `NEEDS_PROVIDER`. Save evidence, both positions, best current artifact and the next action. Independent authorized units may continue.

## Stop Without Rewriting the Outcome

Provider errors stop the optional operation; there are no automatic retries. A supported retry requires explicit `resume`. At most two identical provider requests are admitted for an unchanged prompt, model and coordinator revision; do not recreate runs or make cosmetic changes to evade that bound. Existing overall call/deadline limits still apply.

To abandon an optional run, write a private run-relative `stop.json` containing `{"reason":"Concrete reason for stopping this optional run."}` and invoke:

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py stop --run-dir ~/.claude/cross-agent-review/example-run --file stop.json
```

`STOPPED` preserves reports, findings and spent counters. It cannot be resumed or finished into approval. The lead can separately review the delivery against its actual goal, resolve supported findings and use normal tests/CI/release checks; record that decision separately and never label the stopped run approved. Repairs to this coordinator do not require recursive provider consensus.

The policy validates identity consistency, freshness, exact citations and structured acknowledgment. It does not establish authorship independently, execute recorded checks, prove semantic scope decisions, or verify actual host reading. Successful native reports are reviewer evidence, not proof of correctness or blanket release authorization.

An interrupted native child must be confirmed exited before `stop`; a live or unidentified child requires investigation. An expired run with a confirmed dead child can stop without renewing its deadline. Stopping records the workflow outcome and preserves its historical calls; it is not a claim that a remote provider request was cancelled.
