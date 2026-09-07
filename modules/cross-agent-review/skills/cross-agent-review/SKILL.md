---
name: cross-agent-review
description: Request a restricted adversarial review from the opposite Claude Code or Codex runtime, with frozen evidence and attributable findings. Use only when cross-provider review of a plan or completed agent work is explicitly requested.
---

# Cross-agent review

Cross-provider review is opt-in: require `--cross-provider` in a calling workflow or an explicit natural-language request. Default X-Plan/X-Plan A, adrev and ETP review is personal lead review with ordinary tests/CI/release checks; no native dispatch or consensus prerequisite is implied by invoking those workflows.

Read [references/workflow.md](references/workflow.md) for optional startup, stages, bounded resolution and completion. Use the installed `~/.claude/lib/cross_agent_review_policy.py` shim under advisor mode, with private runs at `~/.claude/cross-agent-review/<run-id>/`. Run its `preflight` before optional planning/work to check both binaries and native login status; readiness is not proof of a successful model call. A marketplace-only Claude install lacks this trusted shim: use the canonical CCGM installer or delegate setup/execution under normal permissions, never weaken the advisor guard.

Outside advisor mode, a self-contained skill may use [scripts/review_policy.py](scripts/review_policy.py). The lower-level [scripts/cross_agent_review.py](scripts/cross_agent_review.py) is an advanced transport interface described by [references/contract.md](references/contract.md); its report cannot substitute for optional policy completion. The designated author applies changes under existing task authorization.

Derive the initiating and producing providers from actual session/dispatch metadata. For work, review opposite the actual producer. For a planning sequence, start opposite the original planner and alternate for the selected number of passes. Mixed or unknown work requires both perspectives. A provider persona does not establish runtime identity.

Prepare a narrow, explicit set of artifact, specification, and relevant source/test-evidence files. The coordinator supplies immutable contents; reviewers cannot explore the machine or execute tests. Keep the initial review independent of the author's self-report. If evidence is missing, supply the specifically requested files and refresh before continuing. Never truncate a large input silently or include credentials/private configuration.

Create one run, invoke the needed provider through the coordinator, and preserve its run directory for continuation. Use `status` after interruption, then explicit `resume` only when a supported continuation exists; never recreate the run to reset spent calls or deadlines. Respect the caller's selected review count and workflow gates. No recursive review dispatch or same-provider substitute may claim cross-provider success.

`REVIEWED` means a locally validated report. It is not consensus or authorization to execute or merge. Return the report, frozen hashes, open findings, and resource state to the originating workflow/session. Actual delivery must be acknowledged separately; the transport initially records `HANDOFF_PENDING`. Use concrete evidence and the caller's acceptance criteria to resolve objections, and keep incomplete evidence, disagreements, and exhausted limits explicit.

Provider failures stop the optional run. Preserve reports/findings/counters and use policy `stop` with a reason when abandoning it. The lead may separately review delivery without calling the stopped run approved; repairs to this coordinator do not require recursive cross-provider consensus. Check records and host receipts are caller attestations, not independent proof that checks ran or a particular session read the packet.
