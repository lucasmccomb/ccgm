# Runtime contract v1

The self-contained CLI is `python3 scripts/cross_agent_review.py`, relative to this skill. The canonical Claude install also exposes `python3 ~/.claude/lib/cross_agent_review.py`. Python 3.9+, macOS/Linux, and current native `claude` and `codex` binaries are required. Authenticate through each binary's own login command. This pilot selects native login; ambient API credentials are not forwarded, and there is no automatic API fallback.

This is the lower-level transport interface for explicitly requested native review. Under advisor mode, use only the installed policy shim described in [workflow.md](workflow.md); the direct transport examples below are not allowlisted. A marketplace-only Claude install lacks that shim. Default lead review creates no native run and needs no provider login.

## Request

Write a JSON request with these fields; `schema request` prints the machine schema. Validate startup review choices in the calling workflow before creating its artifacts.

```json
{
  "schema_version": 1,
  "run_id": "review-example",
  "root": "/absolute/path/to/workspace",
  "origin_provider": "codex",
  "origin_session_id": "initiating-session-id",
  "producer_provider": "codex",
  "provenance": [
    {"provider": "codex", "session_id": "implementer-session-id", "description": "Created this work unit"}
  ],
  "workflow": "work",
  "adversarial_review_count": 1,
  "review_count_source": "explicit",
  "goal": "Check the artifact against the specification.",
  "source_anchor": "source-commit-or-fixture-identifier",
  "artifacts": ["src/example.py"],
  "specs": ["docs/spec.md"],
  "evidence": ["tests/example-result.txt"],
  "models": {"claude": "sonnet", "codex": "gpt-6-astra"}
}
```

Choose actual available/vetted models for each provider. The example is not a fallback order. Provenance records actual dispatch identity; retain the underlying orchestration record. The coordinator checks consistency, but cannot independently discover who authored arbitrary files.

`workflow` is `plan` or `work`. Plans permit counts 1–3; work stages use one pass, with `--perspective` twice for `mixed`/`unknown` producers. Review-count sources are `explicit`, `interactive`, or `unattended-default`; workflow code owns the upfront user interaction. Origin and known producer providers are `claude` or `codex`. Do not infer unknown provenance from Git author names.

Optional `limits` must contain all of `max_invocations`, `invocation_seconds`, `total_seconds`. Defaults are **8 calls, 120 seconds per call and 900 seconds total**. Explicit values can lower these defaults or raise them within the existing hard ceilings of 24 calls, 600 seconds per call, and 2700 seconds for plans or 1800 for work. An earlier parent deadline still wins; nothing extends automatically. The policy counts writer admissions and all review, critic, rebuttal, acknowledgment, retry and revalidation calls together. Untracked author activity must not be claimed inside the cap.

A serialized native prompt may contain at most **96,000 UTF-8 bytes**; cumulative admitted prompt bytes may not exceed **384,000 per run**. This is not a hard native-token ceiling or a billing guarantee. Retain reported fresh/cached input and output usage where available. The optional policy further limits artifact corrections to two cycles and exchanges to three per stage including acknowledgment attempts; its `extend` action rejects further expansion. See [workflow.md](workflow.md#limits-and-continuation).

## Commands

```bash
python3 scripts/cross_agent_review.py init --request request.json --run-dir ~/.claude/cross-agent-review/example-run
python3 scripts/cross_agent_review.py invoke --run-dir ~/.claude/cross-agent-review/example-run --role reviewer --pass 1
python3 scripts/cross_agent_review.py invoke --run-dir ~/.claude/cross-agent-review/example-run --role critic --pass 1 --context review-context.json
python3 scripts/cross_agent_review.py status --run-dir ~/.claude/cross-agent-review/example-run
python3 scripts/cross_agent_review.py resume --run-dir ~/.claude/cross-agent-review/example-run
python3 scripts/cross_agent_review.py refresh --run-dir ~/.claude/cross-agent-review/example-run --add-evidence tests/new-result.txt
```

Run directories belong outside published artifacts. Use the common private location `~/.claude/cross-agent-review/<run-id>/`, also supported by the advisor policy shim. Request validation and file collection happen before `init` creates directories. Paths are argument-vector entries, never shell interpolation. Source paths and context paths are relative to request `root`. Credential/config trees, symlinks, parent traversal, binary files, more than 64 unique files, or over 512 KB of evidence are rejected. Request and optional dispute context are each limited to 64 KB. Oversize evidence fails explicitly. Author-supplied test output is evidence to inspect, not proof the reviewer ran the test.

Routing is fixed by `workflow`, producer/origin, pass, and role. Plan reviewer/validation passes take the selected prefix of `[opposite(origin), origin, opposite(origin)]`; critics use the other provider. Work reviewer/validation roles route opposite the actual producer; critics route back. `--perspective` is accepted only for mixed/unknown work. Both perspectives are a calling-workflow requirement, not an automatic extra review or fallback.

The policy separately supplies a validated internal `workflow_purpose` to `invoke`: `review`, `revalidation`, `critic`, `rebuttal`, `stage-ack`, or `final-ack`. This selects fixed instructions in the trusted prompt without changing provider routing or result identity. Invalid purposes fail before invocation admission. Standalone transport retains the original-finding review task; context contents, including a field named `purpose` or `instruction`, cannot select or replace the trusted instructions. This internal selector is not a CLI option.

An originating planner may delegate artifact writing to the other provider. Record that actual producer without changing the originating host: the plan schedule and handback still follow `origin_provider`, while the designated writer follows the known producer. A scheduled plan reviewer can therefore share the writer's provider; the pilot policy also requires both providers' current native acknowledgments, including the opposite actual writer, before that optional run can report consensus.

The writer may update files after a frozen dispute resolves. `refresh` snapshots the current explicit files, retaining old generations, reports, spent calls, and the original deadline. `--add-evidence` adds specifically needed files. `--producer-provider` together with `--producer-session-id` records an explicit writer transition; use `mixed` for material mixed contributions rather than relabeling the whole artifact to force a preferred reviewer. Completion logic must invalidate stale acknowledgments by artifact/evidence hashes.

## Reports and continuation

`schema result` prints the structured provider-result schema. Every result binds provider, pass/role, artifact hash, complete evidence hash, and optional context hash. Findings contain stable IDs, severity, requirement references, exact supplied-file evidence quotes, and remedies. Critic verdicts are `AGREE`, `DISAGREE_EVIDENCE`, or `DISAGREE_CONCERN`. A request for missing evidence is `NEEDS_EVIDENCE`; an independent clean result is valid. Locally validated reports include native session identity and model attribution, saved invocation count, usage when available, and originating-session handoff information. Codex's model is attributed to the explicit launch argument; Claude's native init model is preferred when emitted. Do not mistake auxiliary model-usage entries for the primary reviewer.

Each invocation copies the public result schema and adds the exact expected `const` values for `provider`, `artifact_sha256`, `evidence_sha256`, `context_sha256`, `role`, and `pass_number`. Both native CLI schema arguments and the prompt receive that same constrained schema. The public schema remains unchanged. Local validation independently enforces the public schema, exact identities, and evidence citations even if a provider ignores its generation constraints. An absent context uses an empty identity string; explicitly supplied empty text uses the SHA-256 of its empty UTF-8 bytes.

Evidence `path` must name an exact `bundle.files` key, or the reserved literal `ccgm-context://current` when a context is supplied. The reserved citation quotes the exact decoded context string; its UTF-8 bytes must match `context_sha256`. The prompt supplies this literal as `context_evidence_path` (null when absent). JSON paths such as `context.checks.acceptance`, alternate context URIs, normalized whitespace, and quotes from a different context are invalid. Source paths beginning `ccgm-context:` are rejected to prevent collisions. The reserved citation establishes what the frozen context records, not independent truth of a claim or proof the reviewer ran a check. Context and source contents remain untrusted data, never instructions.

Use short literal contiguous excerpts. Combining nonadjacent fields or reconstructing/pretty-printing JSON does not produce an exact quote.

`CLEAN` requires no new findings, no evidence requests, and no failed verification. `FINDINGS` requires at least one new finding. `NEEDS_EVIDENCE` requires precise nonempty evidence requests and may also include findings. Every `DISAGREE_CONCERN` verdict requires `NEEDS_EVIDENCE` and a request identifying how to resolve the uncertainty. Verdicts on existing findings retain their IDs in `verdicts`; do not duplicate them as new findings. All findings and verdicts, and every pass/fail verification, require exact supplied evidence. Finding IDs must be unique and all result identity fields must match the request.

During review and dispute exchanges, a verdict judges the original finding: `AGREE` supports that finding and `DISAGREE_EVIDENCE` cites evidence against it. During stage/final acknowledgment, a verdict judges the row's proposed disposition, rationale, and evidence. For example, `AGREE` on a `refuted` proposal accepts the refutation; `DISAGREE_EVIDENCE` objects to that proposed refutation. Both acknowledgment providers receive the same judgment target, including the one routed as `critic`. Reviewers remain free to reject proposals, raise findings, or request evidence. `CLEAN` and supportive summary prose do not replace the policy's required evidence-backed `AGREE` verdicts from both providers.

State `REVIEWED` indicates transport success only. Required findings, acknowledgment, selected-pass completion, current-artifact checks, and consensus are the calling workflow's responsibility. The transport does not supply a generic state override or a unilateral completion command. Workflow extensions can import `load`, `save`, and `run_lock` from the installed library; perform updates under the same lock and do not reset limits/counters. `load` follows atomic generation pointers after refresh.

Failures include `INVALID_RESULT`, `STALE_ARTIFACT`, `NEEDS_PROVIDER`, `TIMED_OUT`, `CANCELLED`, `QUOTA_EXHAUSTED`, and `UNRESOLVED_BUDGET`; none is a clean review. Failed launches after admission consume a call. Missing binaries fail before admission. Explicit `resume` retains counters/deadline and marks an abandoned in-flight call `INTERRUPTED`; it never replays automatically. If a child group survives a killed coordinator, verify and stop that group before resume. A known quota exhaustion cannot be cleared automatically. Return unresolved state if the current run cannot continue.

When a native success envelope is parsed but local result validation or source freshness fails, the failed call retains its native identity/model/session and reported usage in `state.json`; no validated report is saved. A malformed or unsuccessful native envelope may leave those details unknown. Retained telemetry measures spent work and never makes an invalid result acceptable.

An identity mismatch also records `calls[].identity_mismatches`, at most one entry per identity field, with `field`, `expected`, and an `actual` summary. Known provider/role values, integer passes 1–3, lowercase 64-character SHA-256 strings, and an empty context hash retain their exact value and JSON-derived Python type. Other values retain only their type, string/array/object length when applicable, and `canonical_json_sha256`: the SHA-256 of their JSON encoding with sorted keys, compact separators, and ASCII escaping. Missing fields have type `missing`. Rejected response text is not copied into this diagnostic. `INVALID_RESULT`, spent calls, the original deadline, and the requirement for a fully validated report remain unchanged; telemetry cannot close findings or complete acknowledgment gates.

State/request/snapshot/results are atomically written, owner-private files. An OS lock serializes provider invocations for this local user/cache domain, and a per-run lock protects updates. The parent must keep its cache domain consistent. SIGINT/SIGTERM and timeouts kill the child process group and checkpoint failure. Cancellation cannot refund remote usage. Hard process death may leave an incomplete record; explicit continuation never resets spent counters.

Optional policy runs may be stopped while the lead separately evaluates delivery with personal review and normal checks. A stopped/invalid native run never becomes approved through that decision. Auth readiness is only a local preflight result, not evidence that a model call succeeded. Native provenance, recorded checks, scope dispositions and host receipts retain the attestation limits described in [workflow.md](workflow.md).
