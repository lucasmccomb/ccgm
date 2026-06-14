# Evidence-Tier Gate

**Iron Law:** A COMPLETION CLAIM WITH NO L1 EVIDENCE AUTO-FAILS. PASTE THE FRESH OUTPUT OR DO NOT CLAIM DONE.

This is the mechanical enforcement layer for `verification.md`. That rule says "evidence before claims." This rule defines what counts as evidence, ranks it, and makes a missing-evidence claim a hard failure rather than a judgment call. There is no "I'm confident enough to skip the paste" — the gate is binary.

**Announce at start:** "Applying the evidence-tier gate. Every completion claim ships its L1 artifact or it does not ship."

## The Three Tiers

| Tier | What it is | Counts as proof? |
|------|-----------|------------------|
| **L1** | Fresh artifact captured **this session**: command output with exit code, test run summary, screenshot, log line, HTTP response. The machine produced it, just now. | **Yes.** This is the only tier that satisfies a claim. |
| **L2** | Reasoned argument: "the diff is small," "the types line up," "this can't break X because Y." | **No.** A hypothesis, not a result. |
| **L3** | Bare assertion: "tests pass," "it works," "fixed." No artifact, no argument. | **No.** This is the failure the gate exists to catch. |

L2 and L3 are not evidence. They are the *claim*. The gate requires the claim be backed by L1.

## The Gate

Before emitting any of these phrases — "done," "complete," "it works," "tests pass," "fixed," "deployed," "passing," "green," "verified" — run the gate:

1. **Is there an L1 artifact for this exact claim, captured this session?**
   - No → **AUTO-FAIL.** Do not make the claim. Run the proving command, or downgrade the language to "I changed X; have not yet verified."
   - Yes → continue.
2. **Does the artifact actually show success** (exit code 0, 0 failures, expected content), not just "ran without crashing"?
   - No → the artifact contradicts the claim. Report the failure, do not claim done.
   - Yes → **paste the artifact alongside the claim.** A claim without its pasted L1 artifact is treated as L3.

An unpasted L1 artifact is not L1 to the reader. If you ran it but did not show it, you asserted — that is L3. Paste it.

## Pre-Claim Checklist

For each claim type, the L1 artifact that proves it. This extends the evidence table in `verification.md` — that table names the evidence; this one is the gate you run before speaking.

| Before you say... | Paste this L1 artifact |
|-------------------|------------------------|
| "tests pass" | Fresh test-run tail: pass count + "0 failed" + exit code |
| "lint is clean" | Linter output: "0 errors, 0 warnings" + exit code 0 |
| "build succeeds" | Build command tail + exit code 0 |
| "types check" | Type-checker output: "0 errors" + exit code 0 |
| "bug is fixed" | The repro command's output now succeeding (and ideally the failing run before) |
| "no regressions" | **Full** suite output, not the new tests alone |
| "deployed" | `curl -I` / HTTP response showing the new behavior live |
| "UI renders correctly" | A screenshot captured this session |
| "subagent completed" | The subagent's actual diff / test run / artifact — never its self-report |

If the row you need is not here, the rule still holds: name the command, run it fresh, paste the output.

## Rationalizations That Mean You Are About to Ship an L3 Claim

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "I'm confident the tests pass" | Confidence is L2. The gate takes L1. Run it and paste it. |
| "Re-running just to paste it is wasteful" | The paste *is* the deliverable. An unverifiable claim is worth less than no claim. |
| "I described the output, that's enough" | Describing output is L3. Show the lines, including the exit code. |
| "It passed, I just didn't copy the output" | Then to the reader it is L3. Re-run and paste, or do not claim. |
| "The reasoning is airtight" | Airtight reasoning is still L2. Reasoning predicts; artifacts prove. |
| "I'll paste it if asked" | The gate fires before the claim, not after a challenge. Paste now. |

## Red Flags

Stop and capture L1 if you catch yourself:

- Typing "done" / "passing" / "works" with no command output above it
- Pasting an artifact from earlier in the session and calling it fresh
- Summarizing what an artifact *would* show instead of showing it
- Treating a green exit code you remember but did not re-run as current
- Forwarding a subagent's "DONE" as your own completion without its artifact
