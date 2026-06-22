# Subagent Concurrency and Rate Limits

**Iron Law:** A FAN-OUT IS BOUNDED BY THE SERVER'S RATE LIMIT, NOT BY HOW MANY AGENTS YOU CAN NAME.

Launching too many heavy subagents at once trips a **server-side** throttle that fails the entire burst - not just the marginal agent. This applies to both ways you fan out work: the **Workflow tool** (`parallel()` / `pipeline()`) and **direct parallel Agent-tool dispatch** (multiple Agent calls in one message). Cap peak concurrency by launching in bounded waves; default fan-out agents to cheaper, lower-effort settings unless thoroughness is explicitly requested.

This is a companion to `subagent-patterns.md`. That rule tells you *how* to decompose and delegate. This one tells you *how fast* you are allowed to launch what you decomposed.

## The Error and Why It Happens

The throttle surfaces as this exact string (HTTP 429):

```
Server is temporarily limiting requests (not your usage limit) · Rate limited
```

Read it literally: **"not your usage limit."** This is NOT your account quota, your token budget, or a bug in your code. It is an org-level, server-side throttle on the *rate* of requests and input tokens per minute (ITPM). Nothing is wrong with the workflow - you launched it too aggressively.

### Root cause

- **Heavy agents burst huge input-token volume at launch.** An Opus agent, or any agent at high/max reasoning effort, or any agent that loads a large reference context, sends a large prompt the instant it starts. N of them starting in the same few seconds = N x (large context) input tokens in one window.
- **The burst, not the steady state, trips the limit.** Observed failure: ~10 max-effort Opus agents launched simultaneously attempted **~1.4M tokens in 27 seconds** (a ~3.1M tokens/min pace). That pace exceeded the org ITPM ceiling and **every agent in the burst failed**, returning empty.
- **The Workflow concurrency cap does not save you.** A workflow caps concurrent `agent()` calls at `min(16, cpu cores - 2)` - typically ~10-14. That bounds *local* parallelism but still fires ~10-14 heavy requests at once, which is already enough to trip the throttle.
- **Naive retries make it worse.** Internal retries fire *during* the same overload window and hit the same wall, prolonging the throttle instead of clearing it.

## Justified Defaults

A "heavy" agent is any one of: **Opus model**, **reasoning effort >= high**, or **a large reference context** loaded at launch. Everything else (Sonnet/Haiku at effort <= medium with a small prompt) is "light."

| Lever | Default | Why |
|-------|---------|-----|
| Max **heavy** agents running simultaneously | **4** (never exceed **5**) | Validated safe band: waves of 3-5 heavy Opus agents complete with zero failures; ~10-at-once fails every time. |
| Default **wave / batch size** for heavy agents | **4** | Launch in waves of 4; let a wave drain before starting the next. Keeps the per-window token burst well under the ITPM ceiling. |
| Max **light** agents running simultaneously | **~8** | Small prompts + cheaper models burst far less; the workflow cap (`min(16, cores-2)`) is the real ceiling here. |
| Default model for fan-out agents | **Sonnet** | Unless thoroughness is explicitly requested, fan-out work does not need Opus. Cheaper, smaller burst, faster. Reserve Opus for the few agents that genuinely need depth (final synthesis, the hardest adversarial verify). |
| Default reasoning effort for fan-out agents | **medium or low** | Same logic. Escalate effort only for the stages that demonstrably need it. |
| Retry on transient 429 | **3 attempts, backoff 30s -> 60s -> 120s** | Gives the overload window time to clear before re-dispatch. |

**Reduce agent count first, then throttle launches.** The cheapest fix is fewer, fatter agents: batch the work-list so one agent handles 5 items instead of one (65 items -> 13 agents). Fewer agents = smaller burst, and you may not need waves at all.

## Applying It: the Workflow Tool

The workflow concurrency cap is not low enough for heavy agents. Add your own throttle.

**Prefer `pipeline()` over `parallel()` for heavy stages.** Items flow through a pipeline at staggered times, so the launch burst is naturally spread out. A `parallel()` of heavy agents launches the whole (capped) batch at `t=0` - the worst case for the throttle.

**Chunk heavy fan-outs into sequential waves.** Do not hand a 50-item array straight to `parallel()` of Opus agents. Wave it:

```javascript
// Sequential waves of `size` - peak concurrency stays at `size`, not min(16, cores-2).
async function runChunked(items, fn, size = 4) {
  const out = []
  for (let i = 0; i < items.length; i += size) {
    const wave = items.slice(i, i + size)
    out.push(...await parallel(wave.map((item, j) => () => fn(item, i + j))))
    log(`wave ${i / size + 1}: ${out.filter(Boolean).length}/${items.length} done`)
  }
  return out
}

// Heavy fan-out, throttled:
const results = await runChunked(targets, t =>
  agent(t.prompt, { schema: FINDINGS, phase: 'Review' }), 4)
```

**Or just make the agents lighter.** Often simpler than waving - set `model` and `effort` on the fan-out stage and let the full batch run:

```javascript
const results = await parallel(targets.map(t => () =>
  agent(t.prompt, { model: 'sonnet', effort: 'medium', schema: FINDINGS })))
```

Reserve `model: 'opus'` / `effort: 'high'` for the synthesis or hardest-verify stage, which is usually a single agent or a small handful - well under the cap.

## Applying It: Direct Parallel Agent Dispatch

When you put multiple Agent tool calls in one message, they run concurrently - there is no automatic throttle.

- **Send at most 4 heavy Agent calls per message.** Wait for them to return before sending the next batch of 4. Do not put 10 Opus Agent calls in one response.
- **Light research agents: up to ~8 per message is fine.**
- **Default fan-out Agent calls to a cheaper model / lower effort** (pass `model: "sonnet"` and keep prompts lean) unless the task explicitly demands Opus-grade depth.
- **Stagger naturally by batching:** batch 1 (4 agents) -> read results -> batch 2 (4 agents). The read step between batches is itself the cooldown.

## Recovery: What To Do When You Get Throttled Mid-Run

1. **Recognize it.** The error contains `Server is temporarily limiting requests` / `Rate limited` / HTTP 429, and it hit many or all agents at once. This is the server throttle, **not** your usage cap and **not** a code bug. Do not start "fixing" the workflow.
2. **Stop launching.** Do NOT immediately re-dispatch the same burst. Retries during the overload window hit the same wall and extend the throttle.
3. **Cool down 30-60s.** Let the overload window clear before sending anything.
4. **Re-dispatch only the failed agents, in smaller waves.** Drop to waves of <=3-4 heavy agents, or switch the failed agents to Sonnet / medium effort. In a Workflow, the failed `agent()` calls returned `null` - filter for them and re-run that subset.
5. **If it trips again, halve the wave size and double the cooldown.** Waves of 2, 120s cooldown. Keep halving until it lands.
6. **For Workflow runs, resume from the journal.** Relaunch with `Workflow({ scriptPath, resumeFromRunId })`. Completed agents return cached results instantly; only the failed tail re-runs - so you are not re-bursting the agents that already succeeded.

## Rationalizations That Mean You Are About To Trip the Throttle

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "The workflow caps concurrency at 16, so I'm safe" | The cap bounds local parallelism, not the token burst. ~10-14 heavy agents at once still trips the server limit. |
| "More agents at once = faster" | A burst that 429s is infinitely slower than four clean waves - it fails everything and you start over. |
| "I'll just retry the whole batch immediately" | Immediate retries hit the same overload window and prolong the throttle. Cool down first. |
| "These all need Opus / max effort" | Almost never true for fan-out. Default to Sonnet/medium and escalate only the stages that need depth. |
| "It's a 429, my code must be wrong" | The string says "not your usage limit." It is a launch-rate problem, not a logic bug. |
| "One big `parallel()` is cleaner than waving" | Cleaner to write, worse to run. For heavy agents, `runChunked()` or `pipeline()` is the correct shape. |

## Red Flags

Stop and throttle if you catch yourself:

- Putting more than 4 heavy (Opus / high-effort / large-context) Agent calls in a single message
- Passing a large array straight to `parallel()` where every item spawns a heavy agent
- Defaulting fan-out agents to Opus / high effort without the task asking for that depth
- Re-dispatching a failed burst with no cooldown
- Treating a 429 "Server is temporarily limiting requests" as a code bug instead of a launch-rate problem
- Scaling agent *count* up to be thorough when you could scale *items-per-agent* up instead

## Cross-Reference

- `subagent-patterns.md` - decomposition and dispatch methodology (the *what* and *how* of delegation)
- `multi-agent.md` - the multi-clone "Parallel Work Preference" carries the same concurrency caveat
- The Workflow tool's own docs cover `parallel()` vs `pipeline()`, the `min(16, cores-2)` cap, and `resumeFromRunId` resume
