# checks.md — Reliability & Error Handling Pack

---

## Scope

This pack audits JavaScript and TypeScript source files for async reliability defects: floating promises, misused promise return types, unhandled promise chains, sequential `await` inside loops, HTTP calls without a timeout or abort signal, retry loops without backoff or jitter, and incorrect use of `Promise.all` where partial failures should use `Promise.allSettled`. All checks use LLM detection; the worker agent may run the repo's own `npx eslint` advisory (read-only) but the spine's eslint wrapper (`scripts/spine/wrap-eslint.sh`) runs only `no-eval`/`no-implied-eval`/`no-new-func` via `--no-config-lookup` and cannot cover these rule classes. This pack does NOT cover general code quality (empty catch blocks, style, formatting), security vulnerabilities, TypeScript types, or architectural patterns — those belong in their respective packs.

**Pack ID:** `ccgm/reliability`
**Applies when:** `language:javascript`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `language:javascript` | All checks target JavaScript/TypeScript async semantics (Promises, async/await, fetch/axios). The registry derives `language:javascript` from the presence of `package.json`; no signal is produced on Go, Python, or other-language repos. |

---

## Scope Note: empty-catch Not Included

The `code-quality/empty-catch-block` check in the `code-quality` pack already covers syntactically empty or comment-only catch blocks across all languages with `detection:llm`. Adding a `reliability/empty-catch` check that targets async error-swallowing would duplicate the same pattern with slightly different framing, producing overlapping findings. The `code-quality/empty-catch-block` LLM instruction already flags catch blocks with only a comment and no actual error handling. To avoid duplicate signal, `reliability/empty-catch` is intentionally omitted from this pack.

---

## Checks

---

### `reliability/floating-promise`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans JavaScript and TypeScript source files for async function calls or Promise-returning expressions whose return value is neither awaited, nor returned, nor assigned, nor explicitly discarded with `void`. These "floating" promises mean rejection errors are silently lost. The spine's eslint wrapper does not run `@typescript-eslint/no-floating-promises`; detection is LLM-owned.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: `@typescript-eslint/no-floating-promises` (advisory; not run by spine)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for "floating promises" — async function
calls or Promise-returning expressions whose result is neither awaited, nor returned,
nor assigned to a variable, nor explicitly discarded with `void`.

A floating promise means a rejection can go unhandled and the caller has no way to
know the async operation failed.

Flag as a finding:
- An async function call used as a statement with no await: someAsyncFn();
- A method returning a Promise called with no await: obj.save();
- A Promise constructor result that is not returned or assigned

Do NOT flag:
- Calls prefixed with `void` to explicitly discard: void someAsyncFn();
- Promises that are awaited: await someAsyncFn();
- Promises that are returned: return someAsyncFn();
- Promises that are assigned: const p = someAsyncFn();
- Fire-and-forget patterns inside event listeners where documented with a comment
  explaining the intentional discard

You may run `npx eslint --no-config-lookup` with `@typescript-eslint/no-floating-promises`
for advisory results if the project has the plugin installed; treat output as one signal.

For each finding report: file:line, the offending expression, and why it is unhandled.
```

#### Spine Wiring

```yaml
check_id: reliability/floating-promise
detection: llm
```

Note: the spine's `wrap-eslint.sh` runs only `no-eval`/`no-implied-eval`/`no-new-func` via
`--no-config-lookup`. It does NOT run `@typescript-eslint/no-floating-promises` and does NOT
emit `reliability/floating-promise` IDs. The LLM agent handles this check directly.

#### Severity / Confidence

**Severity rationale:** Floating promises silently swallow rejections. In production, async errors (network failures, DB errors, validation errors) go undetected, causing silent data corruption or stale UI state. High severity: directly causes silent runtime failures.

**Confidence rationale:** LLM pattern matching for unadorned async call statements is reliable in straightforward cases but requires judgment for chained calls and indirect promise returns. Medium confidence accounts for false positives on intentional fire-and-forget.

**Rubric entry:** `reliability/floating-promise`

#### Fixture

**True positive** (`src/handlers/user.ts`):

```ts
// FINDS: updateProfile() returns a Promise but result is not awaited or returned
async function handleFormSubmit(data: FormData) {
  validateForm(data);
  updateProfile(data);   // <-- floating promise: rejection silently lost
  showSuccessMessage();
}
```

**True negative** (should produce NO finding):

```ts
// OK: updateProfile is awaited
async function handleFormSubmit(data: FormData) {
  validateForm(data);
  await updateProfile(data);
  showSuccessMessage();
}
```

---

### `reliability/misused-promise`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for Promise-returning functions passed to contexts that expect synchronous boolean or void callbacks — for example, passing an async function to an `if` condition, a `.filter()` callback, or an event handler type that is not declared async-aware. The spine's eslint wrapper does not run `@typescript-eslint/no-misused-promises`; detection is LLM-owned.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: `@typescript-eslint/no-misused-promises` (advisory; not run by spine)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for Promise-returning functions used in
contexts that expect a synchronous result. This causes the async operation to be
silently ignored because the truthy Promise object is evaluated instead of its resolved
value.

Flag as a finding:
- An async function (or one returning a Promise) passed as a .filter() or .find()
  callback: array.filter(async (x) => ...)
- An async function passed as a boolean predicate to an if statement or ternary:
  if (async () => checkCondition())
- An async function assigned to a DOM event handler that expects synchronous void:
  button.addEventListener('click', async () => { ... }) — flag ONLY if the handler
  does work that the caller depends on synchronously

Do NOT flag:
- async forEach callbacks (these are intentionally fire-and-forget in JS)
- Promise-returning functions returned from other async functions
- async map callbacks where the result is Promise.all'd immediately

You may run `npx eslint --no-config-lookup` with `@typescript-eslint/no-misused-promises`
for advisory results if the project has the plugin installed; treat output as one signal.

For each finding report: file:line, the context where the promise is misused, and the
expected synchronous type.
```

#### Spine Wiring

```yaml
check_id: reliability/misused-promise
detection: llm
```

Note: the spine's `wrap-eslint.sh` does not run `@typescript-eslint/no-misused-promises`.
The LLM agent handles this check directly.

#### Severity / Confidence

**Severity rationale:** Passing an async function where a synchronous predicate is expected silently produces wrong results — a filter that always passes, a condition that is always true. These are logic bugs, not style issues. High severity.

**Confidence rationale:** The most egregious cases (async filter callbacks, async if-conditions) are reliably detectable. Edge cases around event handlers require more context. Medium confidence.

**Rubric entry:** `reliability/misused-promise`

#### Fixture

**True positive** (`src/utils/filter.ts`):

```ts
// FINDS: async callback passed to .filter() — always returns a truthy Promise
const admins = users.filter(async (u) => await isAdmin(u));
```

**True negative** (should produce NO finding):

```ts
// OK: results collected with Promise.all, not passed directly to filter
const adminFlags = await Promise.all(users.map((u) => isAdmin(u)));
const admins = users.filter((_, i) => adminFlags[i]);
```

---

### `reliability/unhandled-promise`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for Promise chains that have no `.catch()` handler, no `await` in a `try/catch`, and no `.finally()` that re-throws. These chains drop rejections silently at runtime. The spine's eslint wrapper does not run `promise/catch-or-return`; detection is LLM-owned.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: `promise/catch-or-return` (advisory; not run by spine)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for Promise chains that end without a
.catch() handler and are not inside a try/catch block. Unhandled rejections produce
an UnhandledPromiseRejectionWarning (Node) or are silently dropped (browser).

Flag as a finding:
- A .then() chain with no .catch() at the end: fetch(url).then(process)
- A Promise constructor call that neither awaits nor attaches .catch()
- A Promise.all / Promise.race call whose result is not awaited in try/catch and
  has no .catch() attached

Do NOT flag:
- Chains that end with .catch(): fetch(url).then(process).catch(handleError)
- await expressions inside a try/catch block
- Chains where the final .then() explicitly rethrows: .then(...).catch(e => { throw e; })
- Chains inside test files using test framework matchers (expect(...).rejects.toThrow)

You may run `npx eslint --no-config-lookup` with `promise/catch-or-return` for advisory
results if the project has eslint-plugin-promise installed; treat output as one signal.

For each finding report: file:line, the chain expression, and the missing handler type.
```

#### Spine Wiring

```yaml
check_id: reliability/unhandled-promise
detection: llm
```

Note: the spine's `wrap-eslint.sh` does not run `promise/catch-or-return`.
The LLM agent handles this check directly.

#### Severity / Confidence

**Severity rationale:** Unhandled rejections produce Node.js process crashes (in newer versions) or silent failures in the browser. A network error in an unhanded fetch chain leaves the user in an undefined state with no feedback. High severity.

**Confidence rationale:** Detecting terminal `.then()` calls without `.catch()` is reliable for simple chains. Complex chains and dynamic promise construction require more judgment. Medium confidence.

**Rubric entry:** `reliability/unhandled-promise`

#### Fixture

**True positive** (`src/api/data.ts`):

```ts
// FINDS: .then() chain with no .catch() — rejection is silently dropped
fetch('/api/users')
  .then((res) => res.json())
  .then((data) => setUsers(data));
```

**True negative** (should produce NO finding):

```ts
// OK: .catch() is present
fetch('/api/users')
  .then((res) => res.json())
  .then((data) => setUsers(data))
  .catch((err) => console.error('Failed to load users:', err));
```

---

### `reliability/await-in-loop`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for `await` expressions inside `for`, `while`, or `do...while` loop bodies where the iterations are independent and could be parallelised with `Promise.all`. Sequential awaiting inside a loop serialises what could be concurrent work, severely degrading performance. The spine's eslint wrapper does not run `no-await-in-loop`; detection is LLM-owned.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: `no-await-in-loop` (advisory; not run by spine)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for `await` expressions inside loop bodies
(for, for...of, for...in, while, do...while) where each iteration awaits an independent
async operation that could be parallelised.

Flag as a finding when:
- A `for` or `while` loop body contains `await` on an independent call (e.g. database
  lookup, API call, file read) where each iteration does not depend on the result of
  the previous iteration

Do NOT flag:
- Loops where each iteration MUST complete before the next starts (sequential processing
  where order or side-effects matter, e.g. processing items in a queue that must be
  ordered, migrations run in sequence)
- Loops where the loop variable itself is mutated by the awaited result
- Rate-limiting loops that intentionally delay between iterations

For each finding, suggest the `Promise.all(array.map(async (item) => ...))` pattern
as the fix.

For each finding report: file:line, the loop construct, and the awaited expression.
```

#### Spine Wiring

```yaml
check_id: reliability/await-in-loop
detection: llm
```

Note: the spine's `wrap-eslint.sh` does not run `no-await-in-loop`.
The LLM agent handles this check directly.

#### Severity / Confidence

**Severity rationale:** Sequential awaiting in a loop over N items makes a task take N × latency instead of 1 × latency. For 100 items at 100ms each, this is 10 seconds vs 100ms. Medium severity: a performance defect that may cause timeouts and degraded UX but does not cause incorrect behavior.

**Confidence rationale:** Most `await` calls inside for-loops are genuinely independent and worth flagging. Dependent loops (where each iteration needs the previous result) require reading the loop body carefully; LLM judgment is needed. Medium confidence.

**Rubric entry:** `reliability/await-in-loop`

#### Fixture

**True positive** (`src/services/email.ts`):

```ts
// FINDS: each sendEmail call is independent; all could run concurrently
async function notifyAll(users: User[]) {
  for (const user of users) {
    await sendEmail(user.email, 'Welcome!');  // serialised unnecessarily
  }
}
```

**True negative** (should produce NO finding):

```ts
// OK: parallelised with Promise.all
async function notifyAll(users: User[]) {
  await Promise.all(users.map((user) => sendEmail(user.email, 'Welcome!')));
}
```

---

### `reliability/fetch-without-timeout`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for `fetch()` and `axios` calls that have no timeout or `AbortController` / `AbortSignal` configured. Without a timeout, a slow or unresponsive server will hold the connection open indefinitely, causing the caller to hang or exhaust connection pools. There is no ESLint rule for this pattern; detection is LLM-owned.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard ESLint rule exists for this pattern)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for HTTP calls using the Fetch API or axios
that have no timeout or AbortController/AbortSignal configured.

Flag as a finding:
- fetch(url) or fetch(url, options) where options does not include a `signal` key with
  an AbortController signal
- axios.get/post/put/delete/request calls where the config object does not include a
  `timeout` field or a `signal` field
- Any wrapper around fetch/axios where the underlying call passes no timeout

Do NOT flag:
- fetch calls that include a signal: fetch(url, { signal: controller.signal })
- axios calls that include timeout: axios.get(url, { timeout: 5000 })
- axios instances created with a baseURL and a timeout in the defaults config (if the
  call inherits from a configured instance — use judgment based on the instance creation
  nearby)
- Test files (*.test.ts, *.spec.ts, *.test.js, __tests__/)

For each finding report: file:line, the fetch/axios call, and the missing timeout/signal.
```

#### Spine Wiring

```yaml
check_id: reliability/fetch-without-timeout
detection: llm
```

#### Severity / Confidence

**Severity rationale:** HTTP calls without a timeout can hang indefinitely when a server is slow or unresponsive, exhausting thread pools and causing cascading failures in server-side code, and hanging UIs in browser code. Medium severity: serious reliability risk but not an immediate security issue.

**Confidence rationale:** The pattern is recognisable but requires reading surrounding context (axios instance config, shared abort controllers) to avoid false positives. Medium confidence.

**Rubric entry:** `reliability/fetch-without-timeout`

#### Fixture

**True positive** (`src/api/client.ts`):

```ts
// FINDS: fetch with no signal — hangs indefinitely if server is unresponsive
async function getUser(id: string) {
  const res = await fetch(`/api/users/${id}`);
  return res.json();
}
```

**True negative** (should produce NO finding):

```ts
// OK: AbortController signal provides a timeout
async function getUser(id: string) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(`/api/users/${id}`, { signal: controller.signal });
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}
```

---

### `reliability/retry-without-backoff`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for retry loops or recursive retry patterns that have no exponential backoff or jitter. Retry storms — many clients retrying at the same fixed interval — can amplify outages. There is no standard ESLint rule for this pattern; detection is LLM-owned.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard ESLint rule exists for this pattern)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for retry loops or recursive retry patterns
that have no exponential backoff or jitter.

Flag as a finding when:
- A loop retries an async operation (fetch, axios, DB call) with either no delay at all,
  or a fixed delay (e.g. sleep(1000) always) and no exponential component
- A recursive function calls itself on failure with a fixed or zero delay
- A retry utility is called with a fixed `retryDelay` or `interval` and no backoff factor

Do NOT flag:
- Retry logic that multiplies the delay by a factor (exponential backoff)
- Retry logic using a library known to implement backoff (e.g. `retry`, `p-retry`,
  `axios-retry` with exponentialDelay, `cockatiel`)
- Polling loops that are not retrying on failure (e.g. status polling every N seconds)

For each finding report: file:line, the retry pattern, and the missing backoff/jitter.
```

#### Spine Wiring

```yaml
check_id: reliability/retry-without-backoff
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Fixed-interval retries cause thundering-herd problems under load but are a less immediate issue than unhandled rejections or floating promises. Low severity: poor resilience pattern that matters mostly at scale.

**Confidence rationale:** Detecting the absence of a backoff factor requires reading the retry logic carefully. Many patterns exist (loops, recursion, library calls). Medium confidence.

**Rubric entry:** `reliability/retry-without-backoff`

#### Fixture

**True positive** (`src/utils/retry.ts`):

```ts
// FINDS: retries with a fixed 1-second delay and no backoff factor
async function fetchWithRetry(url: string, retries = 3): Promise<Response> {
  try {
    return await fetch(url);
  } catch (err) {
    if (retries > 0) {
      await sleep(1000);              // fixed delay — no exponential growth
      return fetchWithRetry(url, retries - 1);
    }
    throw err;
  }
}
```

**True negative** (should produce NO finding):

```ts
// OK: delay doubles on each retry (exponential backoff)
async function fetchWithRetry(url: string, retries = 3, delay = 500): Promise<Response> {
  try {
    return await fetch(url);
  } catch (err) {
    if (retries > 0) {
      await sleep(delay);
      return fetchWithRetry(url, retries - 1, delay * 2);
    }
    throw err;
  }
}
```

---

### `reliability/promise-all-vs-allsettled`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for `Promise.all()` calls where one rejection causes all results to be lost, and where the calling context suggests that partial success is acceptable or even expected. In such cases `Promise.allSettled()` with per-result error handling is the appropriate API. There is no standard ESLint rule for this pattern; detection is LLM-owned.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard ESLint rule exists for this pattern)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for Promise.all() calls where a single
rejection would drop all successfully resolved results, and where the context suggests
partial success would be acceptable.

Flag as a finding when:
- Promise.all() is called over a collection of independent operations (fetching multiple
  unrelated resources, sending notifications to multiple users, processing independent
  items) and the caller has no explicit comment or catch that handles partial failure

Do NOT flag:
- Promise.all() calls where ALL operations are truly atomic — partial success is not
  meaningful (e.g. a database transaction where all steps must succeed)
- Promise.all() calls that are wrapped in .catch() and the caller handles the error
  in a way that makes the failure explicit
- Promise.all() inside test files

For each finding, suggest `Promise.allSettled()` with a per-result status check as an
alternative, and note when Promise.all() is actually correct (atomic operations).

For each finding report: file:line, the Promise.all() call, and why partial success
appears acceptable in context.
```

#### Spine Wiring

```yaml
check_id: reliability/promise-all-vs-allsettled
detection: llm
```

#### Severity / Confidence

**Severity rationale:** `Promise.all` rejecting on the first failure loses all other resolved values; this is often a surprising behavior difference from the developer's intent but is not always a bug. Low severity: a design choice that may or may not reflect intent.

**Confidence rationale:** Distinguishing "atomic, all-or-nothing" from "independent, partial-success-ok" requires reading calling context and business logic. False positives are common. Medium confidence.

**Rubric entry:** `reliability/promise-all-vs-allsettled`

#### Fixture

**True positive** (`src/services/notification.ts`):

```ts
// FINDS: sending to multiple users is independent; one failure drops all results
async function notifyUsers(userIds: string[]) {
  const results = await Promise.all(
    userIds.map((id) => sendNotification(id))
  );
  return results;
}
```

**True negative** (should produce NO finding):

```ts
// OK: Promise.allSettled collects each result's status independently
async function notifyUsers(userIds: string[]) {
  const results = await Promise.allSettled(
    userIds.map((id) => sendNotification(id))
  );
  const failed = results.filter((r) => r.status === 'rejected');
  if (failed.length > 0) {
    logger.warn(`${failed.length} notifications failed`);
  }
}
```

---

## Migration / Scope Notes

### empty-catch Not Included

`reliability/empty-catch` was considered but **dropped** to avoid duplicating `code-quality/empty-catch-block`. The `code-quality` pack already detects syntactically empty or comment-only catch blocks for all languages. Adding a narrower async-scoped version in this pack would generate overlapping findings for the same code. If a future wave warrants distinguishing "catch block that swallows async rejection specifically" from "general empty catch", the two checks should be merged under one pack with a migration mapping.

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
