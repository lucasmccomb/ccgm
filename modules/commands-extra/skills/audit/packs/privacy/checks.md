# checks.md — Privacy & PII Handling Pack

---

## Scope

This pack audits source code for data-handling patterns that put Personally Identifiable Information (PII) at risk: analytics or tracking SDKs wired without a user consent gate, PII stored or persisted with no documented retention or deletion path, and PII passed in URL query strings or GET parameters where it leaks into server logs, browser history, and referrer headers. All three checks target code behavior — what the application does with personal data — not legal documents or license terms. This pack does NOT audit license compliance, terms-of-service adherence, or the presence of a privacy policy document; those are covered by the `ccgm/tos-compliance` pack. Checks produce nothing when no data-handling code is present (`applies_when: always` is self-scoping by design).

**Pack ID:** `ccgm/privacy`
**Applies when:** `always`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | PII handling defects can appear in any language and any project type (web, mobile, CLI, library). Gating on a language or ecosystem flag would miss server-side PII leaks in Go/Python repos or mobile apps with no JavaScript. The pack is self-scoping: all three checks instruct the LLM agent to produce no findings when no data-handling code is present. |

---

## Checks

---

### `privacy/pii-without-consent`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for analytics or tracking SDK initialisation calls (Segment, Mixpanel, Amplitude, Google Analytics, Facebook Pixel, Intercom, Heap, Hotjar, Posthog, Sentry user identification, etc.) and PII collection forms or endpoints that capture email, name, phone, address, or government ID — where no consent gate (cookie banner, opt-in dialog, permission check, or feature flag controlled by consent) is visible in the same code path. The check targets code patterns, not privacy policy documents.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard tool rule exists for consent-gate presence)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan the repository for analytics or tracking SDK initialisation and PII collection
code paths where no consent gate is present.

A consent gate is any of:
- An explicit opt-in check (e.g. if (user.hasConsented), if (cookieConsent.analytics))
- A call to a consent management library (OneTrust, Cookiebot, Osano, usercentrics,
  react-cookie-consent, etc.) that must resolve before the tracking call executes
- A feature flag or environment variable that requires affirmative user opt-in
- A documented TODO or comment explicitly referencing pending consent integration
  (flag as a finding with lower confidence — the code will be live without consent)

Flag as a finding when:
- A tracking or analytics SDK (Segment, Mixpanel, Amplitude, Google Analytics,
  gtag, fbq, Intercom, Heap, Hotjar, Posthog, Sentry.setUser, etc.) is initialised
  or called with user-identifiable data (userId, email, name, phone) and no consent
  gate is visible in the same code path or in the file that calls this code
- A form submission or API handler collects PII fields (email, name, phone, address,
  national ID, date of birth) and forwards them to a third-party service with no
  prior consent check

Do NOT flag:
- Server-side error logging that does NOT include user PII (stack traces, error codes
  without user identifiers are fine)
- SDK calls that pass only anonymous identifiers (random UUIDs, session tokens with
  no connection to real-world identity in context)
- SDK initialisation without any user data attached (anonymous mode)
- Test files (*.test.ts, *.spec.ts, *.test.js, __tests__/, test/)

For each finding report: file:line, the tracking/collection call, and what PII or
identifying data is passed without a visible consent gate.
```

#### Spine Wiring

```yaml
check_id: privacy/pii-without-consent
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Collecting and transmitting user PII to third-party analytics services without consent is a violation of GDPR, CCPA, and similar regulations, exposing the organisation to regulatory fines and reputational harm. High severity: direct legal and ethical risk.

**Confidence rationale:** Detecting the *absence* of a consent gate requires understanding the control flow around a tracking call. The LLM must reason about what is NOT present, which is harder than detecting a present pattern. Consent gates can be implemented in many ways (middleware, HOCs, feature flags, build-time conditions). Medium confidence accounts for false positives where consent is handled in an unconventional way not visible in the immediate code path.

**Rubric entry:** `privacy/pii-without-consent`

#### Fixture

**True positive** (`src/analytics/init.ts`):

```ts
// FINDS: Segment analytics initialised with user email on login — no consent check
import analytics from '@segment/analytics-next';

export function identifyUser(user: User) {
  analytics.identify(user.id, {
    email: user.email,
    name: user.displayName,
  });
}
```

**True negative** (should produce NO finding):

```ts
// OK: consent check gates the identify call
import analytics from '@segment/analytics-next';
import { getConsentState } from '@/lib/consent';

export function identifyUser(user: User) {
  if (!getConsentState().analytics) return;
  analytics.identify(user.id, {
    email: user.email,
    name: user.displayName,
  });
}
```

---

### `privacy/pii-no-retention`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for database schema definitions, ORM models, or data-store writes that persist PII fields (email, phone, name, address, national/government ID, date of birth, IP address, device fingerprint) with no evidence of a documented retention policy or deletion path — no TTL, no scheduled cleanup job, no soft-delete field with a noted deletion window, and no code comment or migration referencing a data retention requirement.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard tool rule exists for retention documentation)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan the repository for database schema definitions, ORM model files, or persistent
data-store write operations that store Personally Identifiable Information (PII) with
no documented retention or deletion path.

PII fields to look for: email, phone, phone_number, name, first_name, last_name,
address, street_address, postal_code, zip_code, national_id, ssn, date_of_birth,
dob, ip_address, device_id, fingerprint, passport_number, tax_id, credit_card,
payment_info.

A documented retention/deletion path is any of:
- A TTL or expiry field on the model (expires_at, deleted_at with a cleanup job
  visible elsewhere in the codebase, ttl, purge_after)
- A migration or comment explicitly stating a retention window
  (e.g. "-- retained for 90 days per privacy policy")
- A scheduled job or cron that deletes records older than N days
- A soft-delete pattern (is_deleted, archived_at) where a purge job exists

Flag as a finding when:
- A SQL schema (CREATE TABLE), ORM model class (TypeORM @Entity, Prisma model,
  Django model, ActiveRecord), or NoSQL document schema contains one or more PII
  fields and there is no evidence in the file or in any related migration/job
  that these records are ever deleted or anonymised after a stated period

Do NOT flag:
- Logging or audit tables that only store event metadata with no user PII fields
- Models that store only non-identifying system data
- Models where PII fields have a comment referencing a retention policy (even if
  the policy duration is not stated — the reference is sufficient)
- Test fixture files or seed files

For each finding report: file:line or model name, the PII field(s) present, and
the absence of any documented retention/deletion path.
```

#### Spine Wiring

```yaml
check_id: privacy/pii-no-retention
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Storing PII indefinitely without a documented retention policy violates GDPR Article 5(1)(e) (storage limitation) and equivalent regulations. The risk is real but secondary to active disclosure without consent. Medium severity: compliance gap that creates long-term liability rather than immediate harm.

**Confidence rationale:** Detecting the absence of a retention policy requires searching across schema files, migration files, and background job definitions. A retention policy may be documented outside the codebase (in a README, GDPR register, or comment in a different file). The LLM cannot be certain retention is undocumented just because it is not visible in one file. Medium confidence.

**Rubric entry:** `privacy/pii-no-retention`

#### Fixture

**True positive** (`db/schema.sql`):

```sql
-- FINDS: email and phone stored with no TTL, no deleted_at, no comment about retention
CREATE TABLE user_profiles (
  id          UUID PRIMARY KEY,
  email       TEXT NOT NULL,
  phone       TEXT,
  full_name   TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

**True negative** (should produce NO finding):

```sql
-- OK: deleted_at column documents the soft-delete retention path
CREATE TABLE user_profiles (
  id          UUID PRIMARY KEY,
  email       TEXT NOT NULL,
  phone       TEXT,
  full_name   TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  deleted_at  TIMESTAMPTZ  -- purged after 90 days by nightly cleanup job (see jobs/purge_users.ts)
);
```

---

### `privacy/pii-in-url`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans for URL construction, routing definitions, or API client calls where PII values (email address, full name, national/government ID, phone number, date of birth) are appended as GET query parameters or embedded as path segments. PII in URLs leaks into server access logs, browser history, CDN request logs, referrer headers, and third-party analytics that capture full URLs.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a (no standard tool rule exists for PII-in-URL detection)

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan the repository for URL construction or API calls where Personally Identifiable
Information (PII) is passed in URL query parameters (GET params) or as path segments.

PII values to look for: email address, full name, first name + last name together,
national ID / SSN, phone number, date of birth, passport number, tax ID.

Note: opaque identifiers (UUID, numeric user IDs with no direct PII meaning) are
acceptable in URL paths. The concern is PII values themselves (e.g. email=user@example.com
or /search?name=John+Smith&dob=1990-01-01).

Flag as a finding when:
- A URL is constructed using string interpolation, template literals, URLSearchParams,
  or query-string builders that include email, name, phone, or other PII fields as
  parameter values (not as opaque IDs)
- An API endpoint definition (Express route, FastAPI path, Rails route) defines a
  route parameter that accepts PII directly: /users/:email, /verify/:ssn
- A redirect or navigation call embeds PII in the destination URL

Do NOT flag:
- URLs that include only opaque identifiers (UUIDs, numeric IDs, session tokens)
- Internal routing between microservices where no PII value is serialised into
  the URL path or query string
- Test files (*.test.ts, *.spec.ts, *.test.js, __tests__/, test/)
- URLs where the PII field is clearly in a POST body, not a query param

For each finding report: file:line, the URL construction pattern, and which PII
field is being embedded in the URL.
```

#### Spine Wiring

```yaml
check_id: privacy/pii-in-url
detection: llm
```

#### Severity / Confidence

**Severity rationale:** PII in URLs leaks into server logs, CDN logs, browser history, and referrer headers whenever the user navigates away or the page includes third-party resources. This is a well-known OWASP and GDPR risk. High severity: passive, hard-to-detect data leakage that persists across log retention periods.

**Confidence rationale:** Distinguishing PII values from opaque IDs in URL parameters requires reading variable names and context. A field named `userId` is fine; `userEmail` or `email` is a finding. LLMs can make this distinction with reasonable accuracy for clearly named fields, but ambiguous naming (e.g., `q`, `id`) reduces precision. Medium confidence.

**Rubric entry:** `privacy/pii-in-url`

#### Fixture

**True positive** (`src/api/verify.ts`):

```ts
// FINDS: email address passed as a GET query parameter — leaks into server logs
async function sendVerificationLink(email: string, token: string) {
  const url = `https://app.example.com/verify?email=${encodeURIComponent(email)}&token=${token}`;
  await sendEmail(email, 'Verify your account', `Click here: ${url}`);
}
```

**True negative** (should produce NO finding):

```ts
// OK: only opaque token in URL — no PII exposed
async function sendVerificationLink(email: string, token: string) {
  const url = `https://app.example.com/verify?token=${token}`;
  await sendEmail(email, 'Verify your account', `Click here: ${url}`);
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
