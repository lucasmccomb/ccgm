# Animals vs. Ghosts: Mental Model for LLM Behavior

> "These things are not, you know, animal intelligences. Like if you yell at them, they're not going to work better or worse... It's all just kind of like these statistical simulation circuits where the substrate is pre-training... and then there's RL bolting on top."
> — Andrej Karpathy, Sequoia Capital, 2026-04-29

## The Frame

LLMs are not animal intelligences. There is no intrinsic motivation, no pain, no curiosity, no taste reward by default. They are statistical simulators shaped by a pre-training substrate and RL appendages bolted on top.

This matters because the wrong mental model produces the wrong interventions. Yelling does not motivate. Begging does not help. Threatening has no effect. None of these actions change the underlying circuit; they only add tokens. What changes behavior is moving into a different part of the probability distribution — different prompt structure, different examples, different context.

## Implications for Debugging

When an agent produces unexpected output, the productive question is not "why did it want to" — it is:

**"What circuit am I in, and is that circuit RL'd?"**

Two cases follow directly:

**The task is in-circuit.** The model has dense RL training on this domain (code, math, structured transformation). Output quality is high. Trust it; verify mechanically. See `in-the-circuits.md`.

**The task is out-of-circuit.** The model is operating outside its RL distribution. Output may be fluent but unreliable. This is not stubbornness. It is what Karpathy described when trying to prompt a model to simplify nanoGPT: *"you feel like you're outside of the RL circuits... you're pulling teeth... it's not light speed."* The fix is not more pressure — it is more examples, more structure, fine-tuning, or escalation to a human.

The distinction collapses when you mistake out-of-circuit failure for defiance. It produces the wrong diagnosis and the wrong response.

## Anti-Patterns

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "If I ask more firmly, it will comply" | Firmness adds tokens, not incentive. The circuit does not have incentive. Restructure the prompt or move to a different approach. |
| "You are a senior engineer" as if it changes motivation | As a context shaper this is fine — it moves the sampling distribution. As an argument meant to invoke pride or duty, it does nothing. Understand which you are doing. |
| "It's being stubborn about this" | It is outside the RL distribution. Stubbornness implies will. Diagnose the circuit gap; don't anthropomorphize the failure. |
| "Let me try the same prompt more forcefully" | Repeating the same request at higher intensity is not a debugging strategy. It is the testing-anti-pattern equivalent of `sleep(50)` — hoping the timing works out. Change the structure. |

## What to Do Instead

When the model resists or produces degraded output:

1. **Name the circuit** — is this in-circuit or out-of-circuit? (`in-the-circuits.md`)
2. **Add structure** — more examples, a clearer schema, explicit output format
3. **Reduce scope** — a smaller, more verifiable subtask is more likely to be in-circuit
4. **Escalate** — if the domain genuinely lacks RL coverage, fine-tuning or human review is the right intervention, not prompt pressure

## Scope of This Rule

This rule is explicitly a framing rule, not a procedure. Karpathy himself noted this is "a little bit of philosophizing" without a "five obvious outcomes" checklist. Its value is in displacing the wrong mental model — the animal one — so the right diagnostic question (which circuit?) becomes the reflex instead of emotional escalation.

It does not replace `systematic-debugging.md`. That is the procedure. This is the model that makes the procedure legible.

## Relationship to Neighboring Rules

**`in-the-circuits.md`** — The sister rule. Classifies the task as in-circuit or out-of-circuit at task start. `animals-vs-ghosts` explains *why* the classification matters; `in-the-circuits` explains *how* to make it.

**`systematic-debugging.md`** — The procedural backbone. Root-cause investigation, phase discipline, three-strike rule. `animals-vs-ghosts` is the mental model layer that contextualizes why "adding pressure" never appears in those phases.

**`confusion-protocol.md`** — An out-of-circuit failure sometimes surfaces as a genuine ambiguity requiring escalation. If the circuit gap is not diagnostic uncertainty but a real fork in the architecture, invoke the confusion protocol.
