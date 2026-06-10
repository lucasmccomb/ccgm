# API & Contract Audit Pack

## Scope

This pack audits JavaScript and TypeScript HTTP route handlers and API endpoints for
contract-level defects: missing input validation, mass-assignment vulnerabilities,
unbounded list endpoints, and absent API versioning. It targets the surface area where
untrusted caller data enters a backend handler and where the API contract lacks
structural controls. Checks are LLM-based (no spine tool) because the defects require
understanding handler intent, not just syntactic patterns. This pack does NOT cover SQL
injection or XSS (owned by `ccgm/security`), authentication bypass (also
`ccgm/security`), or dependency vulnerabilities (`ccgm/dependencies`).

**Pack ID:** `ccgm/api-contract`
**Applies when:** `["language:javascript"]`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `language:javascript` | All four checks target JavaScript/TypeScript route handlers using Node.js frameworks (Express, Fastify, Next.js API routes, SvelteKit endpoints, Koa). They produce zero signal in Go, Python, or Ruby codebases that use different routing conventions. Restricting to `language:javascript` avoids false-positive noise and keeps the pack focused on the ecosystem where these patterns are idiomatic. TypeScript repos are detected as `javascript` by the ecosystem detector (`.ts` files trigger the JS ecosystem flag). |

---

## Checks

---

### `api/missing-input-validation`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Scan all route handler files (Express/Fastify/Koa/Next.js API routes/SvelteKit endpoints)
for handlers that read from req.body, req.query, req.params, event.body, context.params,
request.json(), or equivalent framework-specific input accessors AND then use the value
directly in business logic, a database query, an ORM call, a file-system operation, or
an HTTP response — WITHOUT first passing the value through a schema validation library.

Schema validation libraries to recognize as satisfying the check (NOT a finding):
  - zod (z.parse, z.safeParse, z.object().parse, schema.parseAsync)
  - joi (schema.validate, joi.object().validate)
  - yup (schema.validate, schema.validateSync, schema.cast)
  - class-validator (validate(), validateOrReject(), @IsString(), @IsEmail(), etc.)
  - superstruct (assert(), is(), create())
  - valibot (parse(), safeParse())
  - express-validator (validationResult(), body(), param(), query())
  - ajv (ajv.validate(), ajv.compile())
  - Any other library that clearly performs schema or type validation on the input

Do NOT flag:
  - Handlers that call any of the above validators before using the input.
  - Handlers that only read a typed path parameter that is narrowed by a router (e.g.
    Next.js dynamic route [id] used as a string UUID that is then passed directly to
    a parameterized query — the router guarantees string type, but business-logic
    validation is still missing; flag it unless a UUID format check is present).
  - Middleware that validates at a higher level (e.g. a global validateBody middleware
    applied to all routes in the same file) — only skip if the middleware is clearly
    present in the same handler chain.
  - Test files (*.test.ts, *.spec.ts, __tests__/, test/).
  - Pure pass-through proxies that forward the body unchanged to a downstream trusted service.

For each finding: file path, handler name or route path, the specific input field
accessed without validation, and the first use of that field that triggers the issue.
auto_fixable=false — fix requires choosing and applying a schema validation library.
```

#### Spine Wiring

```yaml
check_id: api/missing-input-validation
detection: llm
```

#### Severity / Confidence

**Severity rationale:** A route handler that trusts unvalidated input is the direct
precursor to injection attacks, type-coercion bugs, and business-logic abuse. An
attacker can send a crafted payload (extra fields, wrong types, oversized strings) that
the handler passes straight to a database or downstream service. HIGH because the
missing control is a fundamental API contract obligation, not a defence-in-depth layer.

**Confidence rationale:** Determining whether validation is present requires reading the
full handler and its middleware chain; the LLM may miss a validator applied in an outer
middleware file or through a decorator. MEDIUM to account for these false-positive and
false-negative risks.

**Rubric entry:** `api/missing-input-validation`

#### Fixture

**True positive** (`src/routes/users.ts`):

```typescript
// FINDS: req.body.email used directly without schema validation
import express from "express";
const router = express.Router();

router.post("/users", async (req, res) => {
  const { email, role } = req.body;
  const user = await db.user.create({ data: { email, role } });
  res.json(user);
});
```

**True negative** (should produce NO finding):

```typescript
// OK: zod validates the body before any use
import express from "express";
import { z } from "zod";
const router = express.Router();

const CreateUserBody = z.object({
  email: z.string().email(),
  role: z.enum(["user", "admin"]),
});

router.post("/users", async (req, res) => {
  const { email, role } = CreateUserBody.parse(req.body);
  const user = await db.user.create({ data: { email, role } });
  res.json(user);
});
```

---

### `api/mass-assignment`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Scan all route handler files for mass-assignment vulnerabilities: places where the entire
request body (or a spread of it) is passed directly into an ORM or database create/update
call without an explicit allow-list of safe fields.

Patterns that constitute a finding:
  - Prisma: prisma.model.create({ data: req.body }) or
            prisma.model.create({ data: { ...req.body } })
  - Prisma: prisma.model.update({ where: ..., data: req.body })
  - Mongoose/Sequelize: Model.create(req.body), instance.update(req.body)
  - TypeORM: repository.save(req.body), repository.update(id, req.body)
  - Drizzle: db.insert(table).values(req.body)
  - knex: db('table').insert(req.body), db('table').where(...).update(req.body)
  - Any ORM where the entire untrusted body or a spread of it reaches a write operation

The risk: an attacker can include extra fields (e.g. `isAdmin: true`, `role: "admin"`,
`credits: 99999`) that the ORM writes to protected columns.

Do NOT flag:
  - Code that destructures only specific fields from req.body before the ORM call,
    e.g. const { name, email } = req.body; Model.create({ name, email }) — only the
    named fields are used, not the full spread.
  - Code that passes req.body through a schema validator (zod, joi, yup, class-validator)
    that strips unknown fields via .strip(), .unknown(false), or equivalent, then passes
    the validated (and sanitised) output to the ORM.
  - Read-only operations (SELECT/find/findMany) — mass-assignment only affects writes.
  - Test files (*.test.ts, *.spec.ts, __tests__/, test/).

For each finding: file path, handler name or route path, the ORM call with the
mass-assignment, and the specific req.body reference.
auto_fixable=false — fix requires explicit field allow-listing or a validating schema.
```

#### Spine Wiring

```yaml
check_id: api/mass-assignment
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Mass assignment lets an unauthenticated or under-privileged
caller promote their own role, override protected fields, or corrupt data. This maps
directly to OWASP API Security Top 10 — API6:2023 (Unrestricted Access to Sensitive
Business Flows) and was the root cause of the GitHub Rails mass-assignment exploit
(2012) and numerous similar incidents. HIGH because the impact is privilege escalation
or data corruption with low attacker effort.

**Confidence rationale:** The LLM must distinguish between a safe destructured-field
pattern and a genuine spread of the full body. This is usually clear from source but
requires understanding the shape of the input and the ORM call context. MEDIUM to
account for cases where the spread is indirect (via a helper function) or the
validation/stripping is in a non-obvious location.

**Rubric entry:** `api/mass-assignment`

#### Fixture

**True positive** (`src/api/profile.ts`):

```typescript
// FINDS: entire req.body spread into Prisma update — attacker can include `isAdmin: true`
router.put("/profile/:id", async (req, res) => {
  const updated = await prisma.user.update({
    where: { id: req.params.id },
    data: { ...req.body },
  });
  res.json(updated);
});
```

**True negative** (should produce NO finding):

```typescript
// OK: only specific allow-listed fields forwarded to ORM
router.put("/profile/:id", async (req, res) => {
  const { name, bio } = req.body;
  const updated = await prisma.user.update({
    where: { id: req.params.id },
    data: { name, bio },
  });
  res.json(updated);
});
```

---

### `api/unbounded-list`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Scan all route handler files for list or collection endpoints that return a potentially
unbounded result set — no pagination, no LIMIT/take/top, and no maximum enforced either
in the query or via a validated query parameter.

Patterns that constitute a finding:
  - Prisma: prisma.model.findMany() with no `take` argument (or with a `take` derived
    from an unvalidated req.query parameter with no maximum cap).
  - Mongoose: Model.find() with no .limit() call.
  - Sequelize: Model.findAll() with no `limit` option.
  - TypeORM: repository.find() with no `take` option.
  - knex: db('table').select() with no .limit() call.
  - Any ORM/query where a GET /collection endpoint returns rows without a finite cap.

Do NOT flag:
  - Endpoints that enforce a hardcoded LIMIT / take / top (e.g. take: 100).
  - Endpoints that read a `limit` or `pageSize` query parameter AND cap it with a
    Math.min(limit, MAX_PAGE_SIZE) or equivalent guard.
  - Internal admin-only endpoints clearly not exposed to public callers (look for auth
    middleware that restricts to admin role).
  - findFirst / findOne / findUnique / findById calls — these return at most one row.
  - Test files (*.test.ts, *.spec.ts, __tests__/, test/).

For each finding: file path, handler name or route path, the ORM call with no limit,
and whether the handler accepts any pagination query parameters (for context).
auto_fixable=false — fix requires adding pagination logic and a maximum page size.
```

#### Spine Wiring

```yaml
check_id: api/unbounded-list
detection: llm
```

#### Severity / Confidence

**Severity rationale:** An unbounded list endpoint is a DoS vector: an attacker (or
runaway client) can repeatedly call it to force the database to scan the full table,
saturate the event loop, exhaust connection-pool slots, and degrade the service for all
users. It also leaks potentially large volumes of data in a single response. MEDIUM
rather than HIGH because it requires repeated calls or a large dataset for meaningful
impact, and many staging/dev environments are low-traffic enough that the issue is
latent.

**Confidence rationale:** Determining whether a cap is present requires reading the
full query options and any upstream middleware that might inject a LIMIT. The LLM may
miss an indirect cap applied via a utility function. MEDIUM to reflect this context
sensitivity.

**Rubric entry:** `api/unbounded-list`

#### Fixture

**True positive** (`src/routes/posts.ts`):

```typescript
// FINDS: findMany with no take — returns all rows on every request
router.get("/posts", async (req, res) => {
  const posts = await prisma.post.findMany({
    where: { published: true },
    orderBy: { createdAt: "desc" },
  });
  res.json(posts);
});
```

**True negative** (should produce NO finding):

```typescript
// OK: take is capped at 100 regardless of caller input
router.get("/posts", async (req, res) => {
  const limit = Math.min(Number(req.query.limit) || 20, 100);
  const posts = await prisma.post.findMany({
    where: { published: true },
    orderBy: { createdAt: "desc" },
    take: limit,
  });
  res.json(posts);
});
```

---

### `api/missing-versioning`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Scan route definitions for HTTP API endpoints that lack a version indicator. An API is
considered versioned when EITHER:
  (a) the route path includes a version segment, e.g. /v1/, /v2/, /api/v1/,
      /api/2024-01-01/, etc., OR
  (b) the handler reads an API-Version header (or Accept-Version, or a custom
      version header) and branches on it.

This check is informational/low severity. Flag only definite absences:
  - Route files where all public API routes share a common prefix that has no version
    segment (e.g. all routes under /api/users, /api/posts — no /v1/ segment anywhere
    in the router or parent router mount point).
  - Express Router mounted without a version segment:
    app.use('/api', router) where the router itself has no versioned sub-routes.

Do NOT flag:
  - Routes where at least one parent mount or path segment contains a version
    (e.g. app.use('/api/v1', router) — even if individual router paths omit /v1/).
  - GraphQL endpoints — versioning through URL paths is not idiomatic for GraphQL.
  - WebSocket upgrade endpoints.
  - Internal service-to-service routes that are not part of the public API contract.
  - Webhook receiver endpoints (e.g. /webhooks/stripe) — these are dictated by
    the caller's URL, not the API's own versioning policy.
  - Test files (*.test.ts, *.spec.ts, __tests__/, test/).
  - Routes that clearly handle versioning via the Accept header (Content Negotiation).

For each finding: file path, the route or router mount that lacks a version indicator,
and a brief note on the recommended fix (add /v1/ prefix or version header routing).
This is an informational finding — severity LOW. Do not escalate.
auto_fixable=false — requires route restructuring.
```

#### Spine Wiring

```yaml
check_id: api/missing-versioning
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Missing API versioning does not cause an immediate security or
reliability failure, but it makes it impossible to evolve the API contract without
breaking existing callers. LOW because the impact is operational and long-term
(technical debt, breaking changes at deprecation) rather than an exploitable
vulnerability.

**Confidence rationale:** Versioning conventions vary widely; a router mounted at
`/api` with sub-routes that include `/v1/` elsewhere still satisfies the intent. The
LLM must inspect the full router tree to correctly classify the presence or absence of
versioning. MEDIUM to reflect this traversal risk.

**Rubric entry:** `api/missing-versioning`

#### Fixture

**True positive** (`src/routes/index.ts`):

```typescript
// FINDS: all routes mounted under /api with no version segment
import express from "express";
const app = express();

app.use("/api/users", userRouter);
app.use("/api/posts", postRouter);
app.use("/api/comments", commentRouter);
```

**True negative** (should produce NO finding):

```typescript
// OK: all routes share a /v1/ version prefix at the mount point
import express from "express";
const app = express();

app.use("/api/v1/users", userRouter);
app.use("/api/v1/posts", postRouter);
app.use("/api/v1/comments", commentRouter);
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
