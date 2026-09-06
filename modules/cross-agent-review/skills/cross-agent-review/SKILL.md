---
name: cross-agent-review
description: Request a restricted adversarial review from the opposite Claude Code or Codex runtime, with frozen evidence and attributable findings. Use for cross-provider review of a plan or completed agent work.
---

# Cross-agent review

Use the local coordinator in [scripts/cross_agent_review.py](scripts/cross_agent_review.py). Read [references/contract.md](references/contract.md) for the request fields, commands, and failure states. This is a review capability; the designated author applies changes under the existing task authorization.

Derive the initiating and producing providers from actual session/dispatch metadata. For work, review opposite the actual producer. For a planning sequence, start opposite the original planner and alternate for the selected number of passes. Mixed or unknown work requires both perspectives. A provider persona does not establish runtime identity.

Prepare a narrow, explicit set of artifact, specification, and relevant source/test-evidence files. The coordinator supplies immutable contents; reviewers cannot explore the machine or execute tests. Keep the initial review independent of the author's self-report. If evidence is missing, supply the specifically requested files and refresh before continuing. Never truncate a large input silently or include credentials/private configuration.

Create one run, invoke the needed provider through the coordinator, and preserve its run directory for continuation. Use `status` after interruption, then explicit `resume`; never recreate the run to reset spent calls or deadlines. Respect the caller's selected review count and workflow gates. No recursive review dispatch or same-provider substitute may claim cross-provider success.

`REVIEWED` means a locally validated report. It is not consensus or authorization to execute or merge. Return the report, frozen hashes, open findings, and resource state to the originating workflow/session. Actual delivery must be acknowledged separately; the transport initially records `HANDOFF_PENDING`. Use concrete evidence and the caller's acceptance criteria to resolve objections, and keep incomplete evidence, disagreements, and exhausted limits explicit.
