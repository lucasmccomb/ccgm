# Bounded cross-provider review

The default is personal lead review plus repository tests, CI and release checks. Cross-provider review is an explicit option for a plan or work unit. This design replaces the original pilot's mandatory provider-consensus delivery gate. Historical native reports retain their original meanings.

## Decision

Use one designated writer and an independent reviewer from the opposite provider. Give the reviewer the frozen artifact, requirements and relevant evidence before sharing the author's assessment. For selected plan passes, preserve the upfront count of 1–3, recommending one, and the opposite/origin/opposite schedule. Count selection alone does not enable native dispatch.

A clean pass needs no ceremonial critic exchange. For material findings, batch the disputed points, identify the affected requirement and request a discriminating check. Accept the best supported solution regardless of who proposed it. A concrete counterexample outranks a popularity vote; a failing test must be investigated, including whether its oracle reflects the requirement. Preferences between valid alternatives should be judged against the user's priorities and reversibility.

An optional run cannot guarantee unanimity within a finite budget. Stop honestly when further discussion lacks new evidence or exceeds its allowance. Preserve the best artifact, findings, reports and next check. Personal lead review may then govern a separate delivery decision; it cannot rewrite the stopped run as approved, dismiss supported defects or bypass CI.

## Enforced boundaries

| Boundary | Policy |
|---|---|
| Activation | Native policy initialization requires `--cross-provider`; default initialization returns `LEAD_REVIEW`, without a run or approval. |
| Planning passes | Upfront selection of 1–3, default recommendation one; selected passes cannot be silently skipped. |
| Correction cycles | At most two artifact correction cycles per optional run. |
| Dispute exchanges | At most three per stage, including acknowledgment attempts; failed attempts spend the allowance. |
| Unchanged requests | At most two identical serialized requests to a provider; no automatic retry. Two unchanged substantive exchanges also require a new check or stop. |
| Shared calls | Eight by default, including writer admissions; explicit limits cannot exceed 24. |
| Time | 120 seconds per invocation and 900 seconds per run by default. Configured ceilings remain 600 per invocation and 2700 per plan or 1800 per work unit. Respect any earlier parent deadline. |
| Native input | 96,000 UTF-8 bytes per serialized prompt; 384,000 cumulative per run, including failed calls. Oversized input is refused before dispatch, never truncated. |
| Continuation | Preserve spent calls and the original deadline. No automatic extensions or replacement runs to evade limits. |
| Trust | Restricted reviewers receive frozen evidence; no filesystem exploration, shell execution, nested agents or remote mutations. |

These are engineering defaults, not experimentally proven optima. Call, time and byte limits are **not a guaranteed token or billing ceiling**. Native overhead, output and reasoning usage can vary; preserve reported usage and mark unavailable usage unknown. Unmetered historical native calls are not assigned invented zero-byte costs and cannot acquire a fresh input allowance.

A successful acknowledgment is reusable only while the complete request, artifact/evidence, checks, finding observations/verdicts/proposals, selected reports, trusted coordinator revision and exact acknowledgment context match. Persist each provider separately, but close findings only after both valid acceptances. Revalidate stored report/context integrity at reuse and completion. Fixed trusted instructions distinguish judging a finding from judging its proposed disposition. Exact identity constraints do not constrain substantive agreement.

## Councils and voting

A council is a possible **future explicit option**, not implemented or automatically launched by this repair. Consider a one-shot independent panel only for a consequential decision with multiple viable alternatives or a named specialist evidence need. Save initial judgments before sharing them. Use the same requirements and rubric, avoid unnecessary author/provider labels, and preserve minority counterexamples.

Votes summarize preferences; they do not establish correctness. Another persona from the same provider is not an independent third vote, and the author's own position is not independent corroboration. No recursive panels or extra calls outside an explicit shared allowance. A tied preference should lead to an evidence-based lead decision or a required user priority decision, not indefinite voting.

## Research basis and limits

- [Smit et al., ICML 2024](https://proceedings.mlr.press/v235/smit24a.html) found tested debate methods unreliable against simpler self-consistency alternatives without tuning. This motivates selective exchanges and a cost-matched baseline.
- [Choi et al., NeurIPS 2025](https://arxiv.org/abs/2508.17536) found voting explained most gains in seven NLP benchmarks. Its homogeneous-agent theory and protocol assumptions limit transfer to sequential Claude/Codex software review.
- [Kaesberg et al., Findings ACL 2025](https://aclanthology.org/2025.findings-acl.606/) found task-dependent benefits of voting versus consensus and independent initial drafts. Its same-model experiments and noisy StrategyQA round-count trend do not establish that every extra round reduces accuracy.
- [Verga et al., PoLL, 2024](https://arxiv.org/abs/2404.18796) found diverse judge panels useful in tested evaluation settings. This supports evaluating selective councils, not making panels mandatory for every change.
- [Kim et al., ICML 2025](https://arxiv.org/abs/2506.07962) found correlated model errors across providers. Cross-provider agreement is not a correctness certificate.
- [Liu et al., EvalPlus, NeurIPS 2023](https://proceedings.neurips.cc/paper_files/paper/2023/hash/43e9d647ccd3e4b7b5baab53f0368686-Abstract.html) showed stronger tests expose wrong code missed by existing suites. Tests improve evidence but do not prove every requirement.

None of these papers evaluates this exact CCGM implementation or identifies an optimal current Claude/Codex pairing. Before expanding council support, compare lead review, lead plus conditional critic, and an independent panel on held-out cases at matched budgets. Measure verified defect recall, false positives, unnecessary edits, goal-relative decision quality, unresolved rate, calls, latency and available usage. Include valid minority findings and correlated-error traps. Independent human adjudication and reproducible checks should ground the evaluation; the panel must not grade itself. This repair does not claim that evaluation has been run.
