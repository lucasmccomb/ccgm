# checks.md — Observability & Logging Quality Pack

---

## Scope

This pack audits source code for observability anti-patterns: logging calls that emit user objects or PII fields directly (leaking personal data into log infrastructure), raw `console.log` statements used in server-side code where a structured logger is expected, and caught errors that are silently swallowed with no telemetry or error-reporting call. All checks use LLM detection targeting code behavior. This pack does NOT audit privacy policy compliance, consent gates, or data retention — those belong in the `ccgm/privacy` pack. It also does NOT audit general empty-catch patterns without considering the observability context (that overlaps `code-quality/empty-catch-block`); the `observability/missing-error-reporting` check is specifically scoped to cases where an error is caught and no reporting or telemetry call follows.

**Pack ID:** `ccgm/observability`
**Applies when:** `always`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | PII leakage into logs, absent structured logging, and swallowed errors can occur in any language and project type. Gating on `language:javascript` would miss Python/Go/Ruby server-side log calls. The pack is self-scoping: checks instruct the LLM agent to produce no findings when no relevant logging or error-handling code is present. |

---

## Checks

---

### `observability/pii-in-logs`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for logging calls (`console.log`, `console.error`, `console.warn`, `console.info`, `logger.info`, `logger.error`, `logger.warn`, `logger.debug`, `log.info`, `winston`, `pino`, `bunyan`, Python `logging.*`, Go `log.*`, `zerolog`, `zap`, etc.) that pass a user object, request body, or field known to contain PII directly as a log argument, without redaction.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard tool rule exists for PII-in-log detection)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan the repository for logging calls that emit user objects, request bodies, or
Personally Identifiable Information (PII) fields directly as log arguments without
redaction.

Logging calls include: console.log, console.error, console.warn, console.info,
logger.info, logger.error, logger.warn, logger.debug, log.info, log.error,
winston logger methods, pino logger methods, bunyan logger methods, Python
logging.info/error/warning/debug, Go log.Printf/Println/Fatal, zerolog, zap.

Flag as a finding when:
- A logging call receives a whole user object: console.log(user), logger.info(req.body),
  logger.debug({ user }), log.Printf("%+v", user)
- A logging call receives a field name that is clearly PII: console.log(user.email),
  logger.info({ email: user.email }), logger.error('Failed for ' + req.body.ssn)
- A logging call receives the raw request body without redaction:
  console.log(req.body), logger.info(request.body), log.Printf("%v", r.Body)

Do NOT flag:
- Logging calls that use a redact/sanitize helper before logging:
  logger.info(redactPII(user)), logger.info(sanitize(req.body))
- Logging calls that reference only opaque identifiers: logger.info({ userId: user.id })
  where id is a UUID or numeric ID with no PII meaning
- Test files (*.test.ts, *.spec.ts, *.test.js, __tests__/, test/)
- Debug-only log calls clearly gated by a NODE_ENV !== 'production' or equivalent
  development-mode check

For each finding report: file:line, the logging call, and what PII or user data
is being passed unredacted.
```

#### Spine Wiring

```yaml
check_id: observability/pii-in-logs
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Log aggregation systems (Datadog, Splunk, CloudWatch, Loki) often retain logs for months or years. Emitting user objects or PII fields into logs means personal data is stored in log infrastructure with different access controls and retention policies than the primary database, violating GDPR and similar regulations and creating a secondary data-breach surface. High severity: passive, long-lived PII leakage.

**Confidence rationale:** Detecting whole-object log calls (`console.log(user)`) is highly reliable. Detecting specific PII field references requires reading variable and field names. LLMs can identify obvious cases (`.email`, `.phone`, `.ssn`) reliably; ambiguous field names reduce precision. Medium confidence.

**Rubric entry:** `observability/pii-in-logs`

#### Fixture

**True positive** (`src/routes/auth.ts`):

```ts
// FINDS: entire user object logged — includes email, name, and other PII
async function handleLogin(req: Request, res: Response) {
  const user = await findUser(req.body.email);
  console.log(user);   // logs PII: email, name, phone, etc.
  if (!user) return res.status(404).json({ error: 'Not found' });
  // ...
}
```

**True negative** (should produce NO finding):

```ts
// OK: only opaque user ID logged — no PII
async function handleLogin(req: Request, res: Response) {
  const user = await findUser(req.body.email);
  logger.info({ userId: user?.id }, 'login attempt');
  if (!user) return res.status(404).json({ error: 'Not found' });
  // ...
}
```

---

### `observability/missing-structured-logging`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans server-side source files for raw `console.log` / `console.error` / `console.warn` calls used in place of a structured logger (winston, pino, bunyan, morgan, Python `logging` module, Go `zerolog`/`zap`/`slog`, etc.). Unstructured log output cannot be parsed, filtered, aggregated, or alerted on reliably in production log systems. This check targets server-side code only; browser/client-side `console.log` usage is expected and not flagged.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard tool rule exists for this cross-project pattern)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan server-side source files for raw console.log, console.error, console.warn,
console.info, or console.debug calls in production code paths, in projects where
a structured logger library is also present.

Server-side files include: files under src/server/, src/api/, src/routes/, src/handlers/,
server.ts, app.ts, index.ts (when the project is a Node.js server), or any non-browser
context. Python server files (views.py, routes.py, handlers.py), Go server files
(main.go, handlers.go).

A structured logger is present when the project imports winston, pino, bunyan, morgan,
@nestjs/common Logger, Python logging module, Go zerolog/zap/slog, or similar.

Flag as a finding when:
- A server-side file uses console.log/error/warn as the primary logging mechanism
  in a project that also imports a structured logger elsewhere (inconsistent use)
- A server-side file uses console.log/error/warn in any capacity when no structured
  logger is present anywhere in the project (missing logging infrastructure entirely)

Do NOT flag:
- console.log in browser/client-side files (*.client.ts, files under src/components/,
  src/pages/, src/app/ in Next.js context, etc.)
- console.log statements that are clearly temporary debug statements with a TODO/FIXME
  comment attached
- Test files (*.test.ts, *.spec.ts, *.test.js, __tests__/, test/)
- console.error used as an error handler of last resort (process.on('uncaughtException'))

For each finding report: file:line, the console call, and whether a structured logger
is present in the project (explain if not).
```

#### Spine Wiring

```yaml
check_id: observability/missing-structured-logging
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Using raw `console.log` in server code prevents structured log aggregation, alerting, and correlation. Log noise increases, signal-to-noise ratio drops, and production debugging becomes harder. Low severity: a hygiene/operational issue that does not cause immediate runtime failures but degrades production observability over time.

**Confidence rationale:** Detecting console.log in server-side context is reliable when the file's server-side nature is clear from path or imports. Distinguishing intentional debug console.log from accidental ones requires some judgment. Whether a structured logger is "present" in the project can be ambiguous in monorepos. Medium confidence.

**Rubric entry:** `observability/missing-structured-logging`

#### Fixture

**True positive** (`src/api/users.ts` in a project that imports `pino` in `src/lib/logger.ts`):

```ts
// FINDS: raw console.log in server route; pino logger exists in the project
import { db } from '../db';

export async function getUser(req: Request, res: Response) {
  console.log('Getting user', req.params.id);   // should use structured logger
  const user = await db.users.findById(req.params.id);
  console.log('Found user', user?.email);       // also logs PII
  res.json(user);
}
```

**True negative** (should produce NO finding):

```ts
// OK: structured logger used consistently
import { logger } from '../lib/logger';
import { db } from '../db';

export async function getUser(req: Request, res: Response) {
  logger.info({ userId: req.params.id }, 'fetching user');
  const user = await db.users.findById(req.params.id);
  res.json(user);
}
```

---

### `observability/missing-error-reporting`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for `catch` blocks (and equivalent error handlers in Python/Go) that catch an error but do not forward it to any telemetry or error-reporting system — no `Sentry.captureException`, no `logger.error`, no `reportError`, no `captureError`, no re-throw, no error metric increment. Silently swallowed errors mean production failures go undetected. This check differs from `code-quality/empty-catch-block` (which flags syntactically empty catch blocks) by specifically targeting non-empty catch blocks that do have code but that code never reports or re-throws the error.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard tool rule exists for this pattern)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan the repository for catch blocks (or equivalent error-handling constructs in
Python/Go) that catch an error but neither report it to any telemetry system nor
re-throw it, causing the error to be silently swallowed in production.

Flag as a finding when a catch block:
- Contains code that does NOT include any of the following:
    * A call to an error-reporting service: Sentry.captureException(err),
      Bugsnag.notify(err), Rollbar.error(err), reportError(err), captureException(err)
    * A structured log call at error level: logger.error(err), log.error(err),
      console.error(err) (console.error is acceptable here as a minimum)
    * A re-throw: throw err, throw new Error(..., { cause: err })
    * A return of an error-typed value clearly propagating the failure up the call chain
- The catch block instead only: sets a local variable, calls a UI-only function
  (setError, showToast, setLoading(false)), logs a custom user-facing message with
  no error object attached, or is empty/comment-only

Do NOT flag:
- Catch blocks that call console.error(err) — this is an acceptable minimum reporting
- Catch blocks that re-throw the error
- Catch blocks at the top-level application boundary that display user-facing error
  messages — these are an acceptable last resort when combined with any logging
- Test files (*.test.ts, *.spec.ts, *.test.js, __tests__/, test/)
- Catch blocks that return a typed error Result/Either value (functional error handling)

For each finding report: file:line, the catch block contents, and what reporting
mechanism is missing.
```

#### Spine Wiring

```yaml
check_id: observability/missing-error-reporting
detection: llm
```

#### Severity / Confidence

**Severity rationale:** A catch block that swallows an error with no reporting means production failures are invisible. Database failures, API timeouts, and validation errors that would normally alert on-call engineers go unnoticed until a user complains or data corruption is discovered. Medium severity: operational blindness that delays incident response but does not directly expose data or cause immediate user harm.

**Confidence rationale:** Identifying that a catch block has code but no reporting or re-throw requires reading the catch block body and understanding what each call does. UI state setters (`setError(true)`) do not count as error reporting. The LLM must distinguish error-reporting calls from UI calls, which is generally reliable for named functions but requires judgment for project-specific utilities. Medium confidence.

**Rubric entry:** `observability/missing-error-reporting`

#### Fixture

**True positive** (`src/services/payment.ts`):

```ts
// FINDS: error caught and only used to update UI state — no reporting to telemetry
async function processPayment(orderId: string) {
  try {
    await stripe.charges.create({ amount: getOrderAmount(orderId) });
  } catch (err) {
    setPaymentError(true);   // only UI state — error is invisible to monitoring
    setLoading(false);
  }
}
```

**True negative** (should produce NO finding):

```ts
// OK: Sentry captures the error before updating UI state
async function processPayment(orderId: string) {
  try {
    await stripe.charges.create({ amount: getOrderAmount(orderId) });
  } catch (err) {
    Sentry.captureException(err);
    setPaymentError(true);
    setLoading(false);
  }
}
```

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
