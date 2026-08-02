# Latent vs Deterministic Work

Agent bugs often come from doing **deterministic work in latent space** — the model reasoning about something a script could compute exactly.

Before acting on any step, classify it:

- **Latent** — judgment, synthesis, open-ended choice. Needs the model. No single right answer.
- **Deterministic** — same input always gives the same output. A short script can produce it exactly, faster, cheaper, and without risk of fabrication.

Mixing the two is the bug. A script that tries to weigh tradeoffs is over-engineered; a model that adds timestamps in its head is wrong on the first DST boundary.

## Examples

| Work | Class | Belongs in |
|------|-------|-----------|
| Is this PR ready to merge? | Latent | Model |
| Summarizing an error log | Latent | Model |
| Picking which test suite to run | Latent | Model |
| Computing `now - event_time` in minutes | Deterministic | Script |
| Converting UTC to local time | Deterministic | Script |
| Grepping for a keyword across files | Deterministic | Script |
| Counting lines, files, matches | Deterministic | Script |
| Parsing a URL, a date, a path | Deterministic | Script |
| Reading the contents of a known file | Deterministic | Tool (Read) |

## Red Flags That Deterministic Work Is Sneaking Into Latent Space

Stop and reach for a script (or an existing tool) if you catch yourself:

- Doing arithmetic in your head when the numbers came from data
- Converting timezones, durations, or units manually
- "Eyeballing" whether a regex matches without running it
- Inferring file existence from naming patterns instead of checking
- Counting items in a list without `wc -l` or equivalent
- Remembering a value from earlier in the session instead of reading it fresh
- Computing a hash, a diff, or a checksum mentally
- Parsing structured output (JSON, CSV, TSV) by scanning the text

Each of these is a deterministic computation. If it gets the wrong answer once, it will get the wrong answer again. Push it into code where the test can pin it.

## The Same Rule Applies to Claims, Not Just Computations

Everything above is about arithmetic the model does in its head. The identical mistake happens one level up, with **assertions about how a system behaves** — and it is harder to see, because the output is an argument rather than a number.

"Does `X` work here?" is not a judgment call. It is a question with a determinate answer that a short experiment returns exactly. Reasoning about it produces a confident paragraph; running it produces the answer.

| Claim | Class | Belongs in |
|-------|-------|-----------|
| Is this the right architecture? | Latent | Model |
| Which of these tradeoffs matters more to us? | Latent | Model |
| Does this flag / mechanism / config actually work here? | **Deterministic** | An experiment |
| Does this suite pass? | **Deterministic** | Run it |
| Can this alternative do the thing we said it can't? | **Deterministic** | Try it |
| Is that field / file / option really there? | **Deterministic** | Read, grep, `--help` |
| Do these two approaches produce the same output? | **Deterministic** | Diff them |

### Dismissed Alternatives Are the Worst Case

A rejected alternative — in a plan, a design doc, a risk register, an "options considered" list — is an **untested claim wearing the costume of a settled decision**. It gets written once, early, under time pressure, and then every later reader inherits it as fact. Nobody re-opens it, because it looks decided.

This is measured, not hypothetical: a dismissal in one plan survived **six reviews** — three constructive and three adversarial at maximum effort — with two reviewers citing it directly. None ran it. A two-minute experiment then falsified half of it and changed the plan materially. Six expensive reviews lost to one cheap test.

**When a decision rests on a dismissal, run the dismissed thing before defending the decision.**

### The Cost Gate

This is bounded on purpose, or it becomes a mandate to prototype every road not taken. A claim is worth testing when the experiment is **minutes, needs no permanent change, and is fully reversible.**

- **Testable:** does this flag scope that file, does this command accept that argument, does this suite pass, does that API return that shape.
- **Not testable here:** would a different database have been better, will users like this, does this scale to 100x. Record these as **untested assumptions and label them as such** — an assumption that says "unverified" is still better than one that reads as settled.

If you must touch shared state to get an answer: make the change inert by construction (scope it to a name nothing else uses), remove it immediately, and verify the removal.

### Red Flags That a Claim Is Being Argued Instead of Tested

Stop and run it if you catch yourself:

- Writing a paragraph defending whether a mechanism works, with a shell available
- Carrying a rejected alternative through a second review without anyone having run it
- Saying "the docs don't mention it, so presumably…" when a canary would settle it in two minutes
- Reviewing a claim again because the last review didn't resolve it
- Treating "three reviewers agreed" as evidence about behavior — agreement is not observation
- Writing "should work" / "shouldn't be affected" / "presumably fine" about something runnable

## Why This Rule Exists

Two classes of failure disappear when deterministic work moves to scripts:

1. **Hallucinated math and parsing.** The model is confident and wrong. Users trust the answer and act on it.
2. **Non-reproducible bugs.** Nothing is pinned, so the same task produces different output on different runs and no test can catch the drift.

Pushing deterministic steps into code flips both: the answer is exact, and a unit test makes the skill's behavior regressable.

## The Loop

When authoring a new skill, hook, or command:

1. List the steps the agent will perform.
2. Mark each step latent or deterministic.
3. For every deterministic step, write (or find) a script that produces the answer.
4. Have the skill invoke the script instead of describing the computation in prose.
5. Write a test that pins the script's behavior on a representative input.

The script constrains the model. The test constrains the script. The skill is the contract between them.

## When to Leave Work in Latent Space

Not every deterministic-looking task is worth extracting. Skip the extraction when:

- The computation runs once in a whole session (cost of writing the script exceeds the win)
- The inputs are themselves latent (e.g., "summarize, then count the key points" — the summary is the real work)
- The script would be longer than the prose and no clearer

The rule is: if the model is doing the same deterministic computation more than twice across sessions, that computation belongs in a script.
