# Condition-Based Waiting

Most "flaky test" bugs are timing bugs. The test guesses at how long an async operation should take, the guess is right on the developer's machine, and wrong under CI load. The fix is almost never "increase the timeout." The fix is to wait for the actual condition, not a duration.

This is a companion to `systematic-debugging.md`. Use it when the symptom is intermittent failure in async code, parallel tests, or anything that involves `sleep`, `setTimeout`, `time.sleep`, or `await new Promise(r => setTimeout(r, N))`.

## The Core Move

Replace arbitrary sleeps with a polling helper that checks the condition you actually care about, with a bounded timeout that fails loudly when the condition never becomes true.

- `sleep(50)` asserts "50ms is enough" - a fact about the machine, not the system
- `waitFor(() => ready)` asserts "the system reached the expected state" - a fact about the system

The second is always the intent. The first is a shortcut that produces flakiness.

## When to Replace a Sleep

Any sleep in a test or verification step is a candidate unless it meets **all** of these:

- It waits for a fixed-duration side effect (a debounce interval, a rate-limit window, a tick-based scheduler)
- The duration is derived from a known, documented interval - not guessed
- A comment immediately above the sleep explains why a sleep is correct here

If any of those fail, the sleep is a bug waiting to fire. Replace it.

## Quick Patterns

| Waiting for... | Pattern |
|----------------|---------|
| An event to fire | `waitFor(() => events.some(e => e.type === "DONE"))` |
| State to change | `waitFor(() => machine.state === "ready")` |
| A count to be reached | `waitFor(() => items.length >= 5)` |
| A file to appear | `waitFor(() => fs.existsSync(path))` |
| A compound condition | `waitFor(() => obj.ready && obj.value > 10)` |

## A Minimal Polling Helper

```typescript
async function waitFor<T>(
  condition: () => T | undefined | null | false,
  description: string,
  timeoutMs = 5000,
): Promise<T> {
  const start = Date.now();
  while (true) {
    const result = condition();
    if (result) return result;
    if (Date.now() - start > timeoutMs) {
      throw new Error(`Timeout waiting for ${description} after ${timeoutMs}ms`);
    }
    await new Promise((r) => setTimeout(r, 10));
  }
}
```

Three things make this helper safe:
- **A bounded timeout.** It cannot hang forever.
- **A descriptive error.** A failure message names what was being awaited, not just "timeout."
- **A reasonable poll interval.** 10ms polling is responsive without pegging the CPU.

Most test frameworks ship an equivalent (`waitFor`, `eventually`, `poll_until`). Use the built-in when one exists.

## Common Mistakes

- **Polling every millisecond.** Wastes CPU, sometimes starves the code under test. Poll at ~10ms.
- **No timeout.** A broken condition becomes an infinite hang in CI. Always bound the wait.
- **Caching state outside the loop.** The condition must call the getter each iteration to see fresh state.
- **Increasing the sleep instead of replacing it.** Longer sleeps reduce flakiness statistically but do not fix the race; they make the test slower and still flaky on a bad day.
- **Waiting on a timer when you can wait on an event.** If the system exposes an event or promise that resolves when the operation completes, subscribe to that instead of polling.

## When an Arbitrary Timeout Is Actually Correct

Occasionally you do need to wait a specific duration - e.g., verifying that a debounced function only emits after 200ms of silence. In that case:

1. First wait on a condition (e.g., the first event fires) to synchronize the start
2. Then sleep for the known interval
3. Then assert on the expected outcome
4. Comment the sleep with the exact reason ("debounce is 200ms; wait 1 full interval to verify no emission")

A commented, condition-anchored sleep is not flaky. An uncommented sleep-and-pray is.

## Why This Belongs in Debugging

Flaky tests waste debugging time twice: once when they fail and once when they pass on rerun and hide a real bug. Treating a flake as a timing bug and fixing it with condition-based waiting eliminates both failure modes. Retrying a flaky test until it passes is the testing equivalent of swallowing an exception.
