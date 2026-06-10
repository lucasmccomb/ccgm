# Security Audit Pack

## Scope

This pack audits source code for security vulnerabilities including hardcoded credentials, injection risks, cross-site scripting vectors, missing security headers, and edge function authentication bypasses. It applies OWASP Top 10 guidance and uses tool-assisted detection (gitleaks for secrets, semgrep for injection/XSS patterns) backed by LLM confirmation. It does NOT audit dependency CVEs (covered by the dependencies pack), infrastructure misconfigurations, or runtime security controls.

**Defense-in-depth cross-reference:** The `ccgm/secrets` pack provides deeper coverage of
committed secrets: full git history scanning (`secrets/leaked-credential`), tracked `.env`
files (`secrets/tracked-env-file`), tracked private key material (`secrets/tracked-key-material`),
and history-only credentials (`secrets/history-only-credential`). When both packs run, the
security pack's `security/hardcoded-secret` check covers LLM-originated findings and
live-source-file patterns, while the secrets pack handles tool-detected history and file-tracking
issues. Running both packs is the recommended defense-in-depth posture for comprehensive
secrets coverage.

**Pack ID:** `ccgm/security`
**Applies when:** `always`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | Security vulnerabilities can appear in any repository regardless of language, framework, or runtime; running on all repos maximises coverage and avoids silent blind spots when ecosystems are mixed or non-standard. |

---

## Checks

---

### `security/hardcoded-secret`

**Severity:** `critical`
**Confidence:** `medium`
**Detection:** `hybrid`

#### Detection

**Tool (if detection = tool or hybrid):**
`gitleaks`

Rule / rule-id: gitleaks default ruleset (all built-in secret patterns)

Fallback when tool absent: `llm`

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/security-patterns.md
Use the pattern regexes, severity guidelines, and OWASP Top 10 quick reference from that file
to guide every check below. Do not rely on memory — open and apply the file.

Scan every source file (excluding test fixtures and .gitignore'd paths) for hardcoded secrets,
API keys, tokens, and credentials. Look for:
- Literal strings that look like API keys, tokens, passwords, or private keys assigned to
  variables, constants, or config fields (e.g. const API_KEY = "sk-...", password: "hunter2")
- Base64-encoded or hex-encoded strings that decode to credentials
- Private key material (-----BEGIN ... PRIVATE KEY-----)
- Connection strings with embedded usernames/passwords
- Bearer tokens, JWT secrets, or HMAC secrets hardcoded in source

Do NOT flag:
- Placeholder or example values (e.g. "your-api-key-here", "REPLACE_ME", "TODO")
- Values read from environment variables (process.env.*, os.environ.*, etc.)
- Values clearly in test fixtures or example config files clearly marked as non-production
- SHA hashes used as identifiers (not credentials)

For each finding: file path, line number, the type of secret detected, and whether env var
refactoring is feasible. auto_fixable=false — needs human setup of the correct env var.
```

#### Spine Wiring

```yaml
check_id: security/hardcoded-secret
detection: hybrid
tool: gitleaks
fallback: llm
```

**Spine-namespace note:** When gitleaks runs, the spine parser (`parse-gitleaks.py`) emits
findings with `check_id: secrets/leaked-credential` (rubric entry: critical, confidence: high).
The LLM worker triages these spine candidates via `spine_triage`. The check-id
`security/hardcoded-secret` is the id for LLM-originated findings (detected without gitleaks,
or LLM additions beyond the tool stream). Do not expect the spine to emit `security/hardcoded-secret`.

#### Severity / Confidence

**Severity rationale:** A hardcoded secret gives any reader of the repository (including malicious actors with git history access) direct, persistent access to the protected resource. Impact is immediate and potentially irreversible (revocation + rotation required).

**Confidence rationale:** Gitleaks has a known false-positive rate on patterns that look like secrets but are not (e.g. hashed values, test fixtures). LLM confirmation step reduces but does not eliminate false positives, yielding medium confidence.

**Rubric entry:** `security/hardcoded-secret`

#### Fixture

**True positive** (`src/config.ts`):

```typescript
// FINDS: literal API key assigned to a constant
const STRIPE_KEY = "sk_live_EXAMPLE_DO_NOT_USE_0000000";
```

**True negative** (should produce NO finding):

```typescript
// OK: value is read from environment, not hardcoded
const STRIPE_KEY = process.env.STRIPE_SECRET_KEY;
```

---

### `security/sensitive-console-log`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/security-patterns.md
Use the pattern regexes, severity guidelines, and OWASP Top 10 quick reference from that file
to guide every check below. Do not rely on memory — open and apply the file.

Scan all source files for console.log (and equivalent: console.debug, console.info, console.warn,
console.error, print(), logger.*, log.*, fmt.Print* in Go, System.out.print* in Java) calls that
output sensitive data such as:
- Passwords, tokens, API keys, secrets
- Full user PII (SSNs, credit card numbers, passport numbers)
- Authentication cookies, session tokens, JWTs
- Private key material
- Health or financial record fields

Do NOT flag:
- Logging of error codes, error types, or non-sensitive error messages
- Logging of request IDs, timestamps, or non-sensitive metadata
- Logging inside test files

For each finding: file path, line number, the specific sensitive field being logged.
auto_fixable=true — fix is to remove or redact the sensitive argument from the log call.
```

#### Spine Wiring

```yaml
check_id: security/sensitive-console-log
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Sensitive data in logs leaks to log aggregators, monitoring systems, and anyone with log access. In production environments this can expose credentials or PII to unintended parties. HIGH rather than CRITICAL because exploitability depends on log access controls.

**Confidence rationale:** Identifying whether a logged variable is truly sensitive requires context that a pattern match alone cannot provide; the LLM must interpret variable names and data flows, giving medium confidence.

**Rubric entry:** `security/sensitive-console-log`

#### Fixture

**True positive** (`src/auth/login.ts`):

```typescript
// FINDS: user password logged
console.log("Login attempt", { email, password });
```

**True negative** (should produce NO finding):

```typescript
// OK: only non-sensitive metadata logged
console.log("Login attempt", { email, timestamp: Date.now() });
```

---

### `security/sql-injection`

**Severity:** `critical`
**Confidence:** `medium`
**Detection:** `hybrid`

#### Detection

**Tool (if detection = tool or hybrid):**
`semgrep`

Rule / rule-id: `p/sql-injection` (semgrep registry SQL injection rules)

Fallback when tool absent: `llm`

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/security-patterns.md
Use the pattern regexes, severity guidelines, and OWASP Top 10 quick reference from that file
to guide every check below. Do not rely on memory — open and apply the file.

Scan all source files for SQL injection vulnerabilities: places where user-controlled input
is concatenated directly into a SQL query string rather than passed as a parameterized query
argument. Look for:
- String concatenation/interpolation building a SQL query where any part comes from user input
  (request params, URL parameters, form fields, headers, cookies)
- Raw query execution with template literals or format strings containing untrusted data
- ORM raw() or literal() calls that embed unescaped user input
- Dynamic ORDER BY / column name construction from user input

Do NOT flag:
- Parameterized queries / prepared statements with correct placeholder binding
- Queries where every interpolated value is a hardcoded constant or a server-side enum
- Pure string operations that are not SQL queries

For each finding: file path, line number, the user-controlled variable being interpolated,
and why parameterization is the correct fix. auto_fixable=false — needs query refactor.
```

#### Spine Wiring

```yaml
check_id: security/sql-injection
detection: hybrid
tool: semgrep
rule: p/sql-injection
fallback: llm
```

**Spine-namespace note:** When semgrep runs, the spine parser (`parse-semgrep.py`) emits
findings with dynamic `check_id: sast/<rule-short-name>` (e.g. `sast/sqli-detected`).
These `sast/*` ids are intentionally unrubriced — merge-findings.py forces `confidence: low`
and sets `properties.unrubriced: true` on them. The LLM worker triages these `sast/*` candidates
via `spine_triage`. The check-id `security/sql-injection` is the id for LLM-confirmed or
LLM-originated SQL injection findings. The spine does NOT emit `security/sql-injection` directly.

#### Severity / Confidence

**Severity rationale:** SQL injection allows attackers to read, modify, or delete database contents and can lead to full database exfiltration or authentication bypass. CRITICAL per OWASP Top 10 (A03:2021).

**Confidence rationale:** Semgrep's SQL injection rules have non-trivial false positive rates on complex ORM patterns; LLM confirmation improves precision but data flow analysis is inherently hard, yielding medium confidence.

**Rubric entry:** `security/sql-injection`

#### Fixture

**True positive** (`src/api/users.ts`):

```typescript
// FINDS: user input concatenated into SQL query
const query = `SELECT * FROM users WHERE name = '${req.params.name}'`;
db.execute(query);
```

**True negative** (should produce NO finding):

```typescript
// OK: parameterized query — user input never touches SQL string
const query = "SELECT * FROM users WHERE name = $1";
db.execute(query, [req.params.name]);
```

---

### `security/xss-vulnerability`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `hybrid`

#### Detection

**Tool (if detection = tool or hybrid):**
`semgrep`

Rule / rule-id: `p/xss` (semgrep registry XSS rules)

Fallback when tool absent: `llm`

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/security-patterns.md
Use the pattern regexes, severity guidelines, and OWASP Top 10 quick reference from that file
to guide every check below. Do not rely on memory — open and apply the file.

Scan all source files for cross-site scripting (XSS) vulnerabilities: places where
user-controlled or externally-sourced data is injected into HTML output without sanitization.
Look for:
- dangerouslySetInnerHTML in React with unsanitized content
- innerHTML, outerHTML, document.write, or insertAdjacentHTML assignments from user input
- Vue v-html directives bound to user-controlled data
- Server-side template rendering that injects request parameters without escaping
- eval() or new Function() called with user-supplied strings

Do NOT flag:
- dangerouslySetInnerHTML when the value is produced by a trusted sanitizer (DOMPurify, etc.)
- Static string literals assigned to innerHTML (no user input involved)
- Server-side templates using auto-escaping with clearly constant values

For each finding: file path, line number, the source of the unsanitized data, and which
sanitization library is appropriate. auto_fixable=false — needs sanitization refactor.
```

#### Spine Wiring

```yaml
check_id: security/xss-vulnerability
detection: hybrid
tool: semgrep
rule: p/xss
fallback: llm
```

**Spine-namespace note:** When semgrep runs, the spine parser (`parse-semgrep.py`) emits
findings with dynamic `check_id: sast/<rule-short-name>` (e.g. `sast/xss-detected`).
These `sast/*` ids are intentionally unrubriced — merge-findings.py forces `confidence: low`
and sets `properties.unrubriced: true` on them. The LLM worker triages these `sast/*` candidates
via `spine_triage`. The check-id `security/xss-vulnerability` is the id for LLM-confirmed or
LLM-originated XSS findings. The spine does NOT emit `security/xss-vulnerability` directly.

#### Severity / Confidence

**Severity rationale:** XSS allows attackers to execute arbitrary JavaScript in victims' browsers, enabling session hijacking, credential theft, and DOM manipulation. HIGH rather than CRITICAL because modern browser security controls (CSP, same-origin) partially mitigate impact.

**Confidence rationale:** Semgrep XSS rules detect syntactic patterns; taint tracking is incomplete without full data flow analysis. LLM confirmation improves precision on complex cases, but ambiguous sanitization chains reduce overall confidence to medium.

**Rubric entry:** `security/xss-vulnerability`

#### Fixture

**True positive** (`src/components/UserContent.tsx`):

```tsx
// FINDS: user-supplied HTML injected without sanitization
function UserContent({ html }: { html: string }) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
```

**True negative** (should produce NO finding):

```tsx
// OK: sanitized through DOMPurify before injection
import DOMPurify from "dompurify";
function UserContent({ html }: { html: string }) {
  return <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
}
```

---

### `security/missing-security-headers`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/security-patterns.md
Use the pattern regexes, severity guidelines, and OWASP Top 10 quick reference from that file
to guide every check below. Do not rely on memory — open and apply the file.

Scan HTTP server configuration files and middleware for missing security headers. Look for
absence of the following headers in the server's response configuration:
- Content-Security-Policy (CSP) — missing or overly permissive (e.g. "unsafe-inline" without
  a nonce/hash, "unsafe-eval", or wildcard * source)
- X-Content-Type-Options: nosniff — prevents MIME-type sniffing attacks
- X-Frame-Options: DENY or SAMEORIGIN — prevents clickjacking (or frame-ancestors CSP directive)
- Strict-Transport-Security (HSTS) — missing or missing includeSubDomains / preload
- Referrer-Policy — missing or set to unsafe-url/no-referrer-when-downgrade
- Permissions-Policy — missing (formerly Feature-Policy)

Check: Express/Koa/Fastify middleware setup, next.config.js headers(), nginx/Apache config,
Cloudflare Pages/Workers headers, vercel.json / netlify.toml headers sections.

Do NOT flag:
- Headers that are set and reasonably configured (minor policy looseness is a note, not a finding)
- Development-only servers not exposed publicly
- APIs that return only JSON (CSP and X-Frame-Options less critical, but HSTS and nosniff still apply)

For each finding: config file, missing header, recommended value, and whether the config file
already exists (auto_fixable=true if config file exists and header just needs adding).
```

#### Spine Wiring

```yaml
check_id: security/missing-security-headers
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Missing security headers expose users to MIME sniffing, clickjacking, and downgrade attacks. These are well-documented attack classes with straightforward mitigations. HIGH because headers are defense-in-depth controls; their absence alone rarely enables full compromise.

**Confidence rationale:** Security header presence is deterministic — a header is either declared in the config or it is not. The LLM checks existing config files for specific header declarations, yielding high confidence.

**Rubric entry:** `security/missing-security-headers`

#### Fixture

**True positive** (`next.config.js`):

```javascript
// FINDS: no security headers configured
module.exports = {
  reactStrictMode: true,
};
```

**True negative** (should produce NO finding):

```javascript
// OK: essential security headers declared
module.exports = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
        ],
      },
    ];
  },
};
```

---

### `security/edge-function-auth-bypass`

**Severity:** `critical`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/security-patterns.md
Use the pattern regexes, severity guidelines, and OWASP Top 10 quick reference from that file
to guide every check below. Do not rely on memory — open and apply the file.

Scan edge function and serverless function code (Cloudflare Workers, Supabase Edge Functions,
Vercel Edge Functions, AWS Lambda@Edge, Next.js API routes, SvelteKit endpoints) for
authentication bypass vulnerabilities. Look for:
- Protected routes or endpoints that return data without verifying the caller's identity
  (missing auth token check, missing session validation, or missing RLS enforcement)
- Middleware that skips authentication for certain path patterns in a way that can be
  exploited (e.g. prefix matching that matches too broadly)
- JWT or session token validation that only checks format but not signature or expiry
- RBAC or role checks that use client-supplied role claims without server-side verification
- Supabase RLS policies that are disabled for a table used by an edge function
- Service-role or admin keys used in client-side code or passed through user-controllable paths

Do NOT flag:
- Public endpoints intentionally designed to be unauthenticated
- Health-check or status endpoints that return no user data
- Authentication endpoints themselves (login, signup)

For each finding: file path, line number, the missing or insufficient auth check,
and the recommended fix (add middleware, verify signature, enforce RLS).
auto_fixable=false — needs refactoring of auth logic.
```

#### Spine Wiring

```yaml
check_id: security/edge-function-auth-bypass
detection: llm
```

#### Severity / Confidence

**Severity rationale:** An auth bypass in an edge function exposes protected data or actions to unauthenticated callers, potentially compromising all user data or enabling unauthorized mutations. CRITICAL impact.

**Confidence rationale:** Authentication logic is highly context-dependent; determining whether a given check is sufficient requires understanding the full auth flow, yielding medium confidence with some false positive risk.

**Rubric entry:** `security/edge-function-auth-bypass`

#### Fixture

**True positive** (`supabase/functions/get-user-data/index.ts`):

```typescript
// FINDS: no auth check before returning sensitive user data
Deno.serve(async (req) => {
  const { data } = await supabase.from("profiles").select("*");
  return new Response(JSON.stringify(data));
});
```

**True negative** (should produce NO finding):

```typescript
// OK: auth header verified before returning data
Deno.serve(async (req) => {
  const token = req.headers.get("Authorization")?.replace("Bearer ", "");
  const { data: user, error } = await supabase.auth.getUser(token);
  if (error || !user) return new Response("Unauthorized", { status: 401 });
  const { data } = await supabase.from("profiles").select("*").eq("id", user.user.id);
  return new Response(JSON.stringify(data));
});
```

---

## Migration Mapping

Every bullet from the original Agent 1 Security Audit category prompt is mapped to its owning check-id:

| Original prompt bullet | Check-id |
|------------------------|----------|
| Hardcoded secrets, API keys, tokens (NOT auto-fixable - needs env var setup) | `security/hardcoded-secret` |
| Console.logs with sensitive data (auto-fixable: remove line) | `security/sensitive-console-log` |
| SQL injection risks (NOT auto-fixable - needs refactor) | `security/sql-injection` |
| XSS vulnerabilities (NOT auto-fixable - needs sanitization) | `security/xss-vulnerability` |
| Missing security headers (auto-fixable if config file exists) | `security/missing-security-headers` |
| Edge function auth bypasses (NOT auto-fixable) | `security/edge-function-auth-bypass` |

All 6 original bullets are covered. No bullet dropped.

---

## Defense-in-Depth Guidance

The checks in this pack are designed as a **layered defence**. No single check is sufficient
on its own; together they cover progressively deeper attack surfaces:

| Layer | Check | Coverage |
|-------|-------|----------|
| 1 — Entry point | `security/hardcoded-secret` | Secrets visible in current source files |
| 2 — Runtime logging | `security/sensitive-console-log` | Secrets accidentally logged at runtime |
| 3 — Business logic | `security/sql-injection`, `security/xss-vulnerability` | Input not sanitised before use in queries or HTML |
| 4 — Environment | `security/missing-security-headers` | Browser-level attack surface left open |
| 5 — Auth boundary | `security/edge-function-auth-bypass` | Auth checks absent at the function entry point |

**Cross-pack layering with ccgm/secrets:**
For full secrets coverage, run the `ccgm/secrets` pack alongside this one. The secrets
pack extends Layer 1 with:
- `secrets/leaked-credential` — full git history scan for any committed credential
- `secrets/tracked-env-file` — `.env` files committed to the index
- `secrets/tracked-key-material` — private key files committed to the index
- `secrets/history-only-credential` — credentials removed from HEAD but still in history

These two packs are complementary and do not overlap on check-ids.

**Validation-layering principle:**
When fixing a finding from this pack, apply validation at every layer the unsafe value
passes through — not just at the point of the symptom. For example, fixing
`security/sql-injection` by parameterising the query also warrants adding input validation
at the API entry point (layer 1) and an integration test that sends malicious input and
asserts it is rejected. A single fix is correct but fragile; layered validation makes the
class of bug structurally impossible.

---

## Migration Mapping

Every bullet from the original Agent 1 Security Audit category prompt is mapped to its owning check-id:

| Original prompt bullet | Check-id |
|------------------------|----------|
| Hardcoded secrets, API keys, tokens (NOT auto-fixable - needs env var setup) | `security/hardcoded-secret` |
| Console.logs with sensitive data (auto-fixable: remove line) | `security/sensitive-console-log` |
| SQL injection risks (NOT auto-fixable - needs refactor) | `security/sql-injection` |
| XSS vulnerabilities (NOT auto-fixable - needs sanitization) | `security/xss-vulnerability` |
| Missing security headers (auto-fixable if config file exists) | `security/missing-security-headers` |
| Edge function auth bypasses (NOT auto-fixable) | `security/edge-function-auth-bypass` |

All 6 original bullets are covered. No bullet dropped.

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
