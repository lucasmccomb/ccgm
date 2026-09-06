# Pilot workflow policy

This policy is used by X-Plan/X-Plan A, standalone adrev, and ETP. Other review sites retain their existing behavior. The transport contract is in [contract.md](contract.md); its `REVIEWED` state is not workflow consensus.

## Startup selection

Use the installed policy shim, or this skill's `scripts/review_policy.py` when running from a self-contained skill installation:

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py select
python3 ~/.claude/lib/cross_agent_review_policy.py select --count 2 --source explicit
python3 ~/.claude/lib/cross_agent_review_policy.py select --count 1 --source interactive
python3 ~/.claude/lib/cross_agent_review_policy.py select --unattended
python3 ~/.claude/lib/cross_agent_review_policy.py select --resume /path/to/private/run
```

The first command returns `NEEDS_SELECTION` without writing any file. Ask for 1 (recommended), 2 or 3 and wait for submission. An explicit valid flag or clear count is `explicit`; an actually submitted answer is `interactive`. Only an explicitly unattended invocation with no question channel may select one without an answer. Autonomous planning alone does not permit that default. Invalid values stop before side effects. If interactive questioning tools are unavailable, ask in plain text and yield until answered.

The alias uses the same startup step, preserving the resolved value/source without a second prompt. Fresh deepen selects again; resume restores existing state. Light mode and constructive review choices cannot cancel adversarial passes.

## Initialize one bounded run

Write the transport request and a check declaration in an orchestration work-product directory after startup selection. The checks declaration is `{"required":["self-review","acceptance"]}` with actual task-specific names. Each name must later have independently recorded execution evidence; do not mark checks passed because an author said they were.

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py init --request /path/to/request.json --run-dir /path/to/private/run --mode plan --checks /path/to/checks.json --writer-session-id actual-writer-session
```

Modes are `plan` for X-Plan's selected sequence, `etp` for spec compliance followed by quality, and `adrev` for standalone review. The transport request uses `workflow: plan` only for X-Plan's origin-relative sequence. ETP and standalone adrev use `workflow: work`, even when adrev's artifact is a plan, so routing follows its actual producer. ETP's explicit `init --light-review` selects spec-only; full two-stage review is the default. Standalone adrev without apply authorization uses `init --report-only`, retaining unresolved findings in its delivered report.

Record actual origin/producer/provider/session provenance and one designated writer. Unknown or materially mixed work requires both perspectives. A reviewer-provided material fix changes the validation requirement; never relabel provenance to obtain a preferred reviewer. Choose provider-specific vetted models explicitly. A model persona, Git username or historical root session is not current dispatch identity.

A planner may delegate writing to the other provider. Preserve the originating planner for plan pass order and final handback, and record the actual producer as designated writer. The scheduled reviewer can then match the writer's provider; the final gate still requires both providers' native acknowledgments of the current artifact, including the opposite actual writer.

Keep run directories and their control files outside reviewed artifacts. For an advisor host, an existing allowed work-product root such as `~/.claude/cross-agent-review/<run-id>/` avoids needing broad source-write permissions. Record the run pointer beside plan/progress metadata. Do not put mutable ledgers, generated report summaries or the run's own state into its input hash set.

Supply explicit, bounded artifact/spec/source/criteria files. The reviewer has no file exploration or command execution tools: a path mention alone does not load an agent template or test. Include the relevant review criteria in the frozen bundle. Initial review excludes the author's persuasive report and earlier findings. A missing-evidence request is answered by a specifically named source or independently run check, not an entire transcript.

## Review, dispute and advance

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py review --run-dir /path/to/private/run
python3 ~/.claude/lib/cross_agent_review_policy.py critic --run-dir /path/to/private/run
python3 ~/.claude/lib/cross_agent_review_policy.py rebuttal --run-dir /path/to/private/run
python3 ~/.claude/lib/cross_agent_review_policy.py status --run-dir /path/to/private/run
```

Run the current stage sequentially. For plans, the selected schedule is the first N of opposite/origin/opposite with fresh reviewer sessions. Pass N is final; every pass covers all attack lenses and four execution tenets. For ETP, spec compliance must pass before quality. Both stages route opposite the same recorded actual producer and share the unit's deadline, invocation allowance and fix count.

Keep the artifact frozen while the two providers dispute findings. Use the global finding IDs returned in the ledger, including their stage/provider namespace: independent reviewers may each emit a local `F1` for different defects. Stable IDs name concrete requirement failures. Critic verdicts are `AGREE`, `DISAGREE_EVIDENCE` and `DISAGREE_CONCERN`; they are not final dispositions. Use exact source evidence, a reproduction, or an acceptance check. Concern alone cannot refute an evidenced finding, and mutual agreement cannot replace a check. A clean independent review is valid.

Use private run-relative JSON control files; no traversal or symlinks. For example, `proposals.json` contains:

```json
{"dispositions":[{"finding_id":"returned-ledger-id","disposition":"refuted","rationale":"The supplied acceptance evidence contradicts the claim.","evidence":[{"path":"tests/evidence.txt","quote":"exact frozen evidence"}]}]}
```

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py propose --run-dir /path/to/private/run --file proposals.json
```

Supported dispositions are `fixed`, `refuted`, `duplicate` and `outside_scope`. They require the policy's other-provider evidence; the orchestrator cannot approve its own proposal through authority. No scope disposition may waive a hard requirement. Missing product intent is a goal decision, not a reason to fabricate consensus.

## Designated writer and checks

Before an accepted source change, `fix.json` identifies the designated writer, finding IDs, reason and next check:

```json
{"writer_provider":"codex","writer_session_id":"actual-writer-session","finding_ids":["returned-ledger-id"],"reason":"Apply the supported correction.","next_check":"Run the failing reproduction."}
```

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py fix --run-dir /path/to/private/run --file fix.json
```

Only after admission should the external designated writer run, respecting the returned remaining deadline. This reserves a shared invocation; account for every delegated fix, retry and verification agent call without claiming untracked author activity fits the cap. Advisor mode still delegates all source edits and test execution. If the designated writer becomes unavailable, preserve the blockage rather than inventing a replacement session identity.

For an explicit user update, including web comments or a deepen request, use `amend` before source edits instead of inventing a review finding. Its private `amendment.json` contains `writer_provider`, `writer_session_id`, `reason`, `next_check` and `authorization: "explicit-user-update"`. The same designated writer and shared invocation/deadline limits apply:

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py amend --run-dir /path/to/private/run --file amendment.json
```

Admission requires the artifact and evidence to match the current frozen snapshot. An amendment cannot retroactively authorize untracked edits; a stale attempt fails without spending another invocation.

After accepted changes, refresh the explicit inputs. The policy invalidates changed-artifact checks/acknowledgments and requires current revalidation. Old generations remain audit history and cannot establish execution readiness.

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py refresh --run-dir /path/to/private/run
python3 ~/.claude/lib/cross_agent_review_policy.py refresh --run-dir /path/to/private/run --add-evidence tests/evidence.txt
```

`--add-evidence` is repeatable and takes explicitly named source-root-relative files. It freezes new evidence under the same size/path/hash constraints and invalidates stale stage evidence; it is not permission to upload a transcript or mutable run state.

`check.json` records an independently executed check, not a shell instruction for the policy to run:

```json
{"name":"acceptance","argv":["python3","tests/check.py"],"exit_code":0,"output":"actual captured output","started_at":1700000000,"finished_at":1700000001,"artifact_sha256":"current-artifact-hash","evidence_sha256":"current-evidence-hash"}
```

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py record-check --run-dir /path/to/private/run --file check.json
python3 ~/.claude/lib/cross_agent_review_policy.py advance --run-dir /path/to/private/run
```

Record actual argv/timestamps/output and the exact generation tested. The example values are illustrative, never evidence. `acknowledge` obtains real native provider acknowledgment of the current evidence/dispositions; a caller-written JSON signature is not accepted. A clean initial stage with current checks may `advance` without a separate stage acknowledgment. After material changes, satisfy the requested current-stage acknowledgment before advancing. `advance` gates the next plan pass or ETP stage. Recheck status after each action and follow its actual required next step.

Native acknowledgment context includes these recorded checks. A provider may cite their exact context text with the reserved evidence path `ccgm-context://current`, bound to that call's `context_sha256`; guessed nested paths such as `context.checks.acceptance` are invalid. See the [transport citation contract](contract.md#reports-and-continuation). A context quote establishes the recorded evidence, not an independently executed reviewer check.

## Final evidence and host handback

For apply/consensus workflows, after all selected stages advance, obtain final workflow acknowledgment. The policy reuses final-stage acknowledgments only when the artifact, ledger, checks and selected reports still match exactly. The resulting handoff packet binds final artifact/evidence hashes and includes a digest and nonce. Deliver that exact packet to the actual originating host. The host writes `receipt.json` with its real provider/session and the packet fields; a closed authoring session cannot be pretended to receive a new handback.

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py acknowledge --run-dir /path/to/private/run
python3 ~/.claude/lib/cross_agent_review_policy.py receive --run-dir /path/to/private/run --file receipt.json
python3 ~/.claude/lib/cross_agent_review_policy.py finish --run-dir /path/to/private/run
```

Receipt fields: `origin_provider`, `origin_session_id`, `artifact_sha256`, `evidence_sha256`, `handoff_sha256`, `nonce`. Require actual reception evidence, not the coordinator's guess. If the host cannot receive it, record `HANDOFF_PENDING` and leave delivery incomplete.

The finish gate requires current checks/evidence, supported closed findings, the selected N plan records or required ETP stages, both native acknowledgments and host reception. Required unresolved findings, stale acknowledgments, incomplete selected passes or missing checks block execution/merge. X-Plan's separate user execution gate remains afterward.

Standalone report-only adrev preserves open findings without source changes: run its selected review stage(s), `advance` to create the report handoff, then `receive` and `finish`; do not call `acknowledge` or require fabricated clean findings. Its terminal state is `REPORT_DELIVERED`, with `execution_ready: false`. Report completion is distinct from consensus and execution readiness. Do not call `fix` to make a requested audit pass; present its report and honest unresolved status. Apply-authorized adrev uses the full writer/verification contract.

## Limits and continuation

The shared defaults are 24 provider invocations; ten minutes per invocation; 45 minutes for a plan sequence or 30 minutes for a work unit, always bounded by any earlier parent deadline. Reviews, critics, rebuttals, delegated fixes, retries and revalidations consume that same allowance. At most five exchanges occur per frozen dispute. After two unchanged exchanges, produce a discriminating check or stop unresolved.

Three artifact-fix rounds are the default checkpoint. An explicit extension adds a bounded batch only with new evidence and a viable next check. `extension.json` contains `reason`, `next_check` and exact frozen `evidence` references:

```bash
python3 ~/.claude/lib/cross_agent_review_policy.py extend --run-dir /path/to/private/run --file extension.json
```

Extensions preserve the original deadline and spent calls. ETP's separate three-round CI-repair loop remains unchanged. Record available tokens/timing/quota signals without claiming unknown telemetry is available capacity. Known quota exhaustion stops new dispatches.

Use `status` and explicit `resume` after interruption; never recreate the run to reset counters or silently replay an in-flight child. Resource exhaustion is `UNRESOLVED_BUDGET`, a dispute with no useful next check is `UNRESOLVED_DISPUTE`, missing intent is `NEEDS_GOAL_DECISION`, and missing native provider/auth/capability is `NEEDS_PROVIDER`. Save evidence, both positions, best current artifact and the next action. Independent authorized units may continue.
