# In-the-Circuits: Verifiable-Domain Self-Classification

Before starting any task, name the circuit you are in. One sentence. This sets confidence mode, review cadence, and escalation threshold for everything that follows.

> "If you're in the circuits that were part of the RL, you fly. And if you're in the circuits that are out of the data distribution, you're going to struggle and you have to figure out which circuits you're in in your application."
> — Andrej Karpathy, Sequoia Capital, 2026-04-29

## The Classification

| Circuit | What it means | How to proceed |
|---------|--------------|----------------|
| **In-circuit** | The task sits in a domain where frontier models have dense RL training: code, math, refactoring, testing, structured data transformation. Output quality is high and verifiable. | Ride the wave. Trust output. Move at full speed. Standard verification applies. |
| **Out-of-circuit** | The task touches taste, UX copy, novel architecture, brand voice, domain-specific reasoning the labs did not RL on, or any domain where there is no ground-truth verifier. Output may be fluent but unreliable. | Slow down. Human-in-loop. Expect to fine-tune or escalate. Flag explicitly before proceeding. |

If the circuit is unclear, treat it as **out-of-circuit**. The cost of unnecessary caution on an in-circuit task is low. The cost of overconfidence on an out-of-circuit task is high.

## The Protocol

At task start, write one sentence:

```
Circuit: in-circuit — refactoring the auth middleware to extract token validation.
```

or

```
Circuit: out-of-circuit — writing onboarding copy for a healthcare app. Flagging for human review.
```

That is the entire protocol. No elaborate analysis. If you cannot name the circuit in one sentence, it is out-of-circuit.

## Examples

| Task | Circuit | Reason |
|------|---------|--------|
| Implement a CSV parser | In-circuit | Code; dense RL training; output is mechanically verifiable |
| Refactor this function for clarity | In-circuit | Code; RL'd on refactoring patterns; output is diff-reviewable |
| Write a failing test for this bug | In-circuit | Testing; pass/fail is a verifier |
| Convert this schema to TypeScript types | In-circuit | Structured transformation; types are checkable |
| Fix this SQL query | In-circuit | Code; query result is verifiable |
| Name this product | Out-of-circuit | Taste; no verifier; labs not RL'd on brand naming |
| Decide whether to use Postgres or DynamoDB | Out-of-circuit | Novel architecture choice; context-dependent; no ground-truth verifier |
| Write empathetic onboarding copy for a healthcare app | Out-of-circuit | UX copy + healthcare domain knowledge; taste-dependent; high stakes if wrong |
| Choose the right color palette for this brand | Out-of-circuit | Aesthetic taste; subjective; no verifier |
| Summarize this legal contract | Out-of-circuit | Domain-specific (legal); hallucination risk is high-stakes |

## When to Apply

Apply this classification at the start of every non-trivial task. "Non-trivial" means anything that will take more than one tool call or produce output the user will act on.

## When NOT to Apply

Do not apply it to:

- Single-line changes with obvious correct form (no judgment involved)
- Tasks where the circuit is obvious and the classification would be noise (e.g., every `git status` call does not need a circuit announcement)

## Relationship to Neighboring Rules

**`confusion-protocol.md`** — A mid-task escape hatch when you hit an architectural fork and cannot proceed without a decision. In-the-circuits is a pre-task classification, not a mid-task interrupt. They are complementary: classify first, then if you hit a fork while executing, invoke the confusion protocol.

**`verification.md`** — Evidence is required either way. Being in-circuit does not exempt output from verification. It only tells you the output is likely trustworthy enough to verify rather than discard. Out-of-circuit output should be verified AND reviewed by a human before acting on it.

**`latent-vs-deterministic.md`** — Different axis. The latent/deterministic split asks: *who should compute the answer* (model vs. script)? The in-circuit split asks: *has the model been RL'd on this domain*? A task can be latent (needs the model) and out-of-circuit (model is unreliable here) at the same time. Example: "choose a product name" is latent (no script can do it) and out-of-circuit (model is unreliable at naming). Both rules apply independently.

## Anti-Patterns

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "The model is generally smart, it will figure this out" | General intelligence does not equal domain RL. Fluency is not reliability. |
| "The copy looks good, ship it" | Out-of-circuit output looks fluent. Fluency is not accuracy or appropriateness. |
| "I'll classify mid-task if something feels off" | By then you have already committed to an approach. Classify before you start. |
| "This is mostly code, so it's probably fine" | "Mostly code" that also involves novel architecture or domain-specific logic is mixed-circuit. Name it. |
| "The user can review it later" | That transfers the classification burden to the user without warning them it exists. Name the circuit; let them decide how much to trust. |

## Red Flags

Stop and reclassify if you catch yourself:

- Outputting architectural recommendations with the same confidence as a function refactor
- Writing UX copy without flagging that taste-based output needs human sign-off
- Treating "it compiles" as evidence that out-of-circuit reasoning was correct
- Making a domain-specific judgment (legal, medical, financial, brand) without noting the circuit
- Presenting options in an out-of-circuit domain without flagging that none of them may be correct
