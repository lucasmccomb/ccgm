---
name: debugging-techniques
description: >
  Root-cause tracing up the call chain, defense-in-depth validation at every layer a bad value crossed, and the animals-vs-ghosts model for LLM misbehavior. Load during any debugging that goes past a one-line fix.
---

# Debugging Techniques

Companions to `systematic-debugging.md`: how to investigate when the symptom is far from the cause, where to put the fix once the origin is known, and how to read a model that seems to resist.

## Root Cause Tracing

A concrete technique for Phase 1 and Phase 2 of the systematic-debugging methodology. When a bug surfaces deep in a call chain, do not fix where the error appears. Trace backward until you find the original trigger, then fix at the source.

This is a companion to `systematic-debugging.md`. That rule tells you to investigate before fixing. This rule tells you *how* to investigate when the symptom is far from the cause.

### The Core Move

Errors surface where broken invariants finally fail a check. The code that raises the exception is rarely the code that produced the bad value. Tracing means following the bad value backward up the call stack to the place it was first introduced.

**Never fix only where the error appears.** Fixing the symptom leaves the originating code free to produce the same bad value again, through a different path.

### When to Use This Technique

- The stack trace is long and the failure happens far from any user input
- The immediate cause is clear but the reason that cause occurred is not
- The same symptom keeps reappearing after previous fixes
- Instrumentation or logs show a bad value, but not where it came from
- You catch yourself about to wrap the failing operation in a try/catch

### The Tracing Process

1. **Observe the symptom.** Read the full error, including the exact value that caused it (empty string, null, wrong path, unexpected state).
2. **Find the immediate cause.** What line of code raised the error? What argument or state was wrong at that point?
3. **Walk one frame up.** What called this code? What value did the caller pass in?
4. **Repeat.** Keep walking until the bad value stops being passed in and starts being *produced*. That is the origin.
5. **Fix at the origin.** Correct the place that first produced the bad value, not every place that forwarded it.

If the call chain crosses module boundaries, instrument each boundary with structured logging (value, caller, timestamp) rather than guessing. A captured stack trace at the suspicious operation is usually enough to collapse the search.

### When Manual Tracing Stalls

If you cannot trace manually because the chain is asynchronous, event-driven, or dynamically dispatched:

- Log `new Error().stack` (or the language equivalent) at the suspicious operation so the full call path is captured at runtime
- Use `console.error` (or stderr) rather than a logger that may be suppressed in the failing context
- Log the actual value, the environment, and the call path together - one of them is the clue
- For test-pollution bugs ("something gets created that should not exist"), bisect the test suite: run subsets until the offending test is identified

The goal of instrumentation is to *discover* where the bad value originated, not to confirm a theory you already have.

### Pair With Defense-in-Depth

Finding the origin tells you where to fix. But a single fix at the origin can be bypassed by a new code path, a refactor, or a mock. Once the origin is identified and fixed, add validation at the other layers the value passed through. See the `debugging-techniques` skill.

### Anti-Patterns

- **Fixing at the symptom and declaring victory.** The bug returns through a different path.
- **Adding a try/catch around the failing operation.** Swallowing the error hides the next occurrence and leaves the origin untouched.
- **Guessing upward without instrumentation.** If the chain is not obvious from reading, add logging before speculating.
- **Stopping at the first plausible-looking cause.** Keep asking "what called this?" until the bad value has no caller - only then are you at the origin.

## Defense-in-Depth Validation

Once root-cause-tracing has identified where a bad value originated, a single fix at that point is necessary but not sufficient. A single validation is a check a future refactor can remove. Layered validation makes the bug structurally impossible.

This is a companion to `systematic-debugging.md` and the `debugging-techniques` skill. Use it in Phase 4 (Implementation), after you have found the origin and are deciding where to put the fix.

### The Core Move

One validation is "we fixed this bug." Validation at every layer the bad value passed through is "we made this bug impossible." Each layer catches different cases - entry validation blocks bad input, business-logic validation blocks bad state, environment guards block dangerous context, and instrumentation captures anything the first three missed.

**The goal is not redundancy. It is independence.** Four layers each with one weakness catch more bugs than one layer with four weaknesses.

### The Four Layers

#### Layer 1 - Entry Point Validation

Reject obviously invalid input at the API boundary. Empty strings, nulls, wrong types, missing required fields.

- Validate at the public entry point so callers see failures early
- Throw with a specific message that names the invalid value
- This layer catches most real-world bugs and prevents bad values from entering the system

#### Layer 2 - Business Logic Validation

Within the operation, assert that the data makes sense for the specific action about to occur. Entry-level validation accepts any non-empty string; business-logic validation rejects a string that is syntactically valid but semantically wrong (a path that does not exist, a user without the required role, a state that forbids this transition).

- Use guard clauses at the top of the operation, not deep inside it
- Fail with context: what operation, what input, what invariant was violated
- This layer catches what entry validation cannot, because it depends on runtime state

#### Layer 3 - Environment Guards

Forbid dangerous operations in the wrong context. Refuse to run destructive code outside a test sandbox. Refuse to write to production tables from a development build. Refuse to call a paid API without the expected feature flag.

- Gate the dangerous operation on an invariant about the environment, not the input
- Prefer "refuse unless proven safe" over "allow unless proven dangerous"
- This layer catches bugs that entry and business validation cannot see, because the bad context comes from the wrong machine, wrong process, or wrong mode

#### Layer 4 - Debug Instrumentation

Structured logging immediately before the dangerous operation, capturing the value, the caller, the environment, and a stack trace. This layer does not prevent bugs; it makes the *next* bug fast to diagnose.

- Log enough context that a stack trace alone would identify the broken caller
- Use stderr or an unfiltered channel so the log survives when the operation fails
- Leave the instrumentation in for some period after the fix ships; remove it only when the code path has been stable

### How to Apply the Pattern

1. Trace the data flow from origin to failure point (see the `debugging-techniques` skill)
2. List every layer the bad value passed through
3. Add a layer-appropriate check at each boundary, not only the one closest to the symptom
4. Test that each layer fires independently by temporarily disabling the others

Four weak layers of independent validation catch more bugs than one strong layer.

### Anti-Patterns

- **Fixing only at the origin.** The fix is correct but fragile; a future code path can re-introduce the bad value without tripping any check.
- **Fixing only at the symptom.** The origin continues to produce bad values; the same class of bug reappears through different paths.
- **Duplicating the same validation at every layer.** Each layer should catch a different class of failure. If all four layers check "non-empty string," you have one layer, repeated.
- **Skipping instrumentation because "the fix is enough."** Future debugging will be slower without it, and the next bug in this area will have no leverage.

## Animals vs. Ghosts: Mental Model for LLM Behavior

> "These things are not, you know, animal intelligences. Like if you yell at them, they're not going to work better or worse... It's all just kind of like these statistical simulation circuits where the substrate is pre-training... and then there's RL bolting on top."
> — Andrej Karpathy, Sequoia Capital, 2026-04-29

### The Frame

LLMs are not animal intelligences. There is no intrinsic motivation, no pain, no curiosity, no taste reward by default. They are statistical simulators shaped by a pre-training substrate and RL appendages bolted on top.

This matters because the wrong mental model produces the wrong interventions. Yelling does not motivate. Begging does not help. Threatening has no effect. None of these actions change the underlying circuit; they only add tokens. What changes behavior is moving into a different part of the probability distribution — different prompt structure, different examples, different context.

### Implications for Debugging

When an agent produces unexpected output, the productive question is not "why did it want to" — it is:

**"What circuit am I in, and is that circuit RL'd?"**

Two cases follow directly:

**The task is in-circuit.** The model has dense RL training on this domain (code, math, structured transformation). Output quality is high. Trust it; verify mechanically. See `in-the-circuits.md`.

**The task is out-of-circuit.** The model is operating outside its RL distribution. Output may be fluent but unreliable. This is not stubbornness. It is what Karpathy described when trying to prompt a model to simplify nanoGPT: *"you feel like you're outside of the RL circuits... you're pulling teeth... it's not light speed."* The fix is not more pressure — it is more examples, more structure, fine-tuning, or escalation to a human.

The distinction collapses when you mistake out-of-circuit failure for defiance. It produces the wrong diagnosis and the wrong response.

### Anti-Patterns

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "If I ask more firmly, it will comply" | Firmness adds tokens, not incentive. The circuit does not have incentive. Restructure the prompt or move to a different approach. |
| "You are a senior engineer" as if it changes motivation | As a context shaper this is fine — it moves the sampling distribution. As an argument meant to invoke pride or duty, it does nothing. Understand which you are doing. |
| "It's being stubborn about this" | It is outside the RL distribution. Stubbornness implies will. Diagnose the circuit gap; don't anthropomorphize the failure. |
| "Let me try the same prompt more forcefully" | Repeating the same request at higher intensity is not a debugging strategy. It is the testing-anti-pattern equivalent of `sleep(50)` — hoping the timing works out. Change the structure. |

### What to Do Instead

When the model resists or produces degraded output:

1. **Name the circuit** — is this in-circuit or out-of-circuit? (`in-the-circuits.md`)
2. **Add structure** — more examples, a clearer schema, explicit output format
3. **Reduce scope** — a smaller, more verifiable subtask is more likely to be in-circuit
4. **Escalate** — if the domain genuinely lacks RL coverage, fine-tuning or human review is the right intervention, not prompt pressure

### Scope of This Rule

This rule is explicitly a framing rule, not a procedure. Karpathy himself noted this is "a little bit of philosophizing" without a "five obvious outcomes" checklist. Its value is in displacing the wrong mental model — the animal one — so the right diagnostic question (which circuit?) becomes the reflex instead of emotional escalation.

It does not replace `systematic-debugging.md`. That is the procedure. This is the model that makes the procedure legible.

### Relationship to Neighboring Rules

**`in-the-circuits.md`** — The sister rule. Classifies the task as in-circuit or out-of-circuit at task start. `animals-vs-ghosts` explains *why* the classification matters; `in-the-circuits` explains *how* to make it.

**`systematic-debugging.md`** — The procedural backbone. Root-cause investigation, phase discipline, three-strike rule. `animals-vs-ghosts` is the mental model layer that contextualizes why "adding pressure" never appears in those phases.

**`confusion-protocol.md`** — An out-of-circuit failure sometimes surfaces as a genuine ambiguity requiring escalation. If the circuit gap is not diagnostic uncertainty but a real fork in the architecture, invoke the confusion protocol.
