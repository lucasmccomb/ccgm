# checks.md — CCGM Hygiene Pack

---

## Scope

This pack audits source repositories for three hygiene issues that the CCGM conventions
identify as common and costly: committed TODO/FIXME/XXX/HACK markers that signal deferred
work shipped to production; environment-variable drift between code and `.env.example`
(variables referenced in code but undocumented, or documented but no longer referenced);
and Cloudflare Pages projects created as direct-upload (non-Git-connected) deployments,
which cannot be retrofitted with Git integration and must be deleted and recreated to fix.

All three checks gate themselves to applicable repos inside their detection instructions
(self-scoping). A repo with no `.env.example` and no env-var references produces no
`ccgm/env-example-drift` findings. A repo with no Wrangler/Cloudflare config produces no
`ccgm/cloudflare-pages-no-git` findings.

This pack does NOT cover project-rule conformance (`ccgm-standards` pack), MCP server
annotation gaps, security vulnerabilities, or general code quality — those belong in their
respective packs.

**Pack ID:** `ccgm/ccgm-hygiene`
**Applies when:** `always`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | All three checks are language-agnostic and self-scope internally. Running on any repo incurs at most a grep with zero findings; no false negatives from ecosystem-gating on repos that happen to lack a `package.json`. |

---

## Checks

---

### `ccgm/shipped-todo-marker`

**Severity:** `info`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

Grep-based. The spine or fallback grep searches source files for the patterns TODO, FIXME,
XXX, and HACK in a case-insensitive pass. All four patterns are commonly used to mark
deferred work or known problems. Finding them in committed code is low-risk but informational:
the code was accepted with known debt.

**Self-scoping:** This check runs on every repo. On repos with no TODO/FIXME markers the
result is an empty finding list; no special gate is needed.

**Tool (if detection = tool or hybrid):**
grep (built-in to all POSIX systems; no additional tool required)

Rule / rule-id: n/a (grep pattern: `\b(TODO|FIXME|XXX|HACK)\b`)

Fallback when tool absent: grep is always available; no fallback needed.

**LLM instruction (if detection = llm or hybrid):**
n/a — detection is grep-only.

#### Spine Wiring

```yaml
check_id: ccgm/shipped-todo-marker
detection: tool
tool: grep
fallback: grep
```

Grep command (for reference):

```bash
grep -rn --include="*.{js,ts,jsx,tsx,py,go,rb,sh,rs,java,kt,swift,cs}" \
  -E '\b(TODO|FIXME|XXX|HACK)\b' \
  --exclude-dir="{node_modules,.git,dist,build,vendor}" \
  .
```

#### Severity / Confidence

**Severity rationale:** A TODO marker is not a bug; it is deferred work. The presence of
markers in committed code is informational — it indicates known technical debt but does not
indicate a runtime failure. Info severity: useful for tracking but requires no immediate action.

**Confidence rationale:** The grep pattern is deterministic. Any line containing TODO/FIXME/XXX/HACK
in a source file matches. False positives are rare (comments referencing third-party TODOs are
still valid findings); false negatives require only that the pattern is present. High confidence.

**Rubric entry:** `ccgm/shipped-todo-marker`

#### Fixture

**True positive** (`src/auth/session.ts`):

```ts
// FINDS: TODO marker in committed source — deferred work
export function refreshToken(token: string) {
  // TODO: add rate limiting before calling this in production
  return fetchNewToken(token);
}
```

**True negative** (should produce NO finding):

```ts
// OK: no TODO/FIXME/XXX/HACK marker present
export function refreshToken(token: string) {
  return fetchNewToken(token);
}
```

---

### `ccgm/env-example-drift`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent checks for drift between environment variables referenced in source code and
variables documented in `.env.example`. Drift takes two forms:

1. **Undocumented**: `process.env.X`, `import.meta.env.X`, `os.environ['X']`, or
   `os.getenv('X')` appear in source but `X` is absent from `.env.example`.
2. **Stale**: `X` is listed in `.env.example` but no reference to it appears in source
   or configuration files.

**Self-scoping:** If the repo has no `.env.example` file AND no env-var access patterns
in source, produce zero findings. If `.env.example` exists but is empty, report any
referenced vars as undocumented. If env-var references exist but no `.env.example` exists,
report the missing `.env.example` as a single informational finding.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
You are checking for environment-variable drift in this repository.

Step 1 — Self-scope:
  - Check whether a .env.example file exists at the repo root.
  - Grep for env-var access patterns across source files:
      JavaScript/TypeScript: process.env.VARNAME or import.meta.env.VARNAME
      Python: os.environ['VARNAME'], os.environ.get('VARNAME'), os.getenv('VARNAME')
      Shell: $VARNAME or ${VARNAME} in scripts that export or use env vars
  - If neither .env.example nor any env-var access patterns exist, produce ZERO findings.
    Stop here.

Step 2 — Collect referenced vars:
  - List every unique variable name referenced via env-var access patterns in source files
    (JS/TS/Python/shell). Exclude:
    - Variables accessed inside test files (*.test.ts, *.spec.ts, *.test.js, __tests__/)
    - Variables that are clearly runtime-only system vars (PATH, HOME, USER, SHELL, etc.)
    - Variables that are interpolated dynamically: process.env[key] (no fixed name)

Step 3 — Collect documented vars:
  - Parse .env.example: each non-blank, non-comment line in the form KEY=... contributes
    KEY to the documented set.
  - If .env.example does not exist, the documented set is empty.

Step 4 — Report drift:
  For each referenced var NOT in the documented set:
    FINDING: ccgm/env-example-drift (undocumented)
    file: the first source file referencing this var
    message: "process.env.{VARNAME} referenced in code but absent from .env.example"

  For each documented var NOT in the referenced set:
    FINDING: ccgm/env-example-drift (stale)
    file: .env.example
    message: "{VARNAME} documented in .env.example but not referenced in any source file"

  If source references env vars but .env.example does not exist:
    FINDING: ccgm/env-example-drift (missing-file)
    file: (repo root)
    message: "Code references env vars but .env.example does not exist"

Do NOT flag:
- Variables prefixed with NEXT_PUBLIC_, VITE_, or REACT_APP_ where the framework
  convention makes the intent clear — but DO flag if still absent from .env.example.
- Test-only variables accessed exclusively in test files.
- System environment variables (PATH, HOME, USER, SHELL, NODE_ENV, CI).
```

#### Spine Wiring

```yaml
check_id: ccgm/env-example-drift
detection: llm
```

#### Severity / Confidence

**Severity rationale:** An undocumented env var means the next developer to clone the
repo will not know the variable is required. This causes "works on my machine" failures
and deployment breakage. Stale entries mislead developers into setting variables that do
nothing. Medium severity: breaks developer workflows and onboarding but does not directly
cause runtime failures in an already-deployed environment.

**Confidence rationale:** The grep-based variable collection is reliable for static
references (`process.env.FOO`). Dynamic access (`process.env[key]`) cannot be statically
inferred and is correctly excluded. The `.env.example` parse is simple line-by-line. The
main FP risk is variables injected by a CI system that legitimately have no `.env.example`
entry; this requires judgment. Medium confidence.

**Rubric entry:** `ccgm/env-example-drift`

#### Fixture

**True positive** (`src/api/client.ts` with partial `.env.example`):

```ts
// FINDS: STRIPE_SECRET_KEY referenced but not in .env.example
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
const supabaseUrl = process.env.SUPABASE_URL!;
```

```bash
# .env.example (incomplete — STRIPE_SECRET_KEY is missing)
SUPABASE_URL=https://your-project.supabase.co
```

**True negative** (should produce NO finding):

```ts
// OK: both vars are documented in .env.example
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
const supabaseUrl = process.env.SUPABASE_URL!;
```

```bash
# .env.example (complete)
SUPABASE_URL=https://your-project.supabase.co
STRIPE_SECRET_KEY=sk_test_your_key_here
```

---

### `ccgm/cloudflare-pages-no-git`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

Grep-based. Searches scripts, CI workflow files, and `package.json` scripts for invocations
of `wrangler pages deploy <project-name>` where the project name is a new name argument —
the signature of creating a direct-upload Cloudflare Pages project rather than deploying
to an existing Git-connected one. Per the CCGM cloudflare rules, this pattern is the single
most expensive Cloudflare mistake: a direct-upload project cannot be retrofitted with Git
integration; it must be deleted and recreated.

**Self-scoping:** If the repo has no `wrangler.toml`, no `wrangler.json`, no `wrangler.jsonc`,
no `.cloudflare/` directory, and no reference to `wrangler` or `cloudflare` in `package.json`
scripts, the check produces zero findings. The grep will simply return no matches.

**Tool (if detection = tool or hybrid):**
grep (built-in; no additional tool required)

Rule / rule-id: n/a (grep pattern: `wrangler pages deploy`)

Fallback when tool absent: grep is always available; no fallback needed.

**LLM instruction (if detection = llm or hybrid):**
n/a — primary detection is grep-based. An LLM clarification step is optional: if grep
finds a `wrangler pages deploy` invocation, the LLM may inspect context to determine
whether the invocation targets an existing Git-connected project (acceptable) vs. creates
a new project name (flagged). When in doubt, flag and note for human review.

#### Spine Wiring

```yaml
check_id: ccgm/cloudflare-pages-no-git
detection: tool
tool: grep
fallback: grep
```

Grep command (for reference):

```bash
grep -rn \
  --include="*.sh" --include="*.yml" --include="*.yaml" \
  --include="*.json" --include="*.jsonc" --include="Makefile" \
  --exclude-dir="{node_modules,.git}" \
  'wrangler pages deploy' \
  .
```

A finding is any match of `wrangler pages deploy`. Matches in comments or documentation
(e.g., inside a Markdown code block in a README) may be excluded by inspection.

#### Severity / Confidence

**Severity rationale:** Creating a Cloudflare Pages project via `wrangler pages deploy
<new-name>` produces a direct-upload project that auto-deploys from Git can never be
added to. Fixing it requires deleting the project (disrupting production traffic), migrating
custom domains, environment variables, and bindings, and recreating through the dashboard.
This is multi-session production work that has burned multiple development sessions. High
severity: the mistake is documented as the most expensive recurring Cloudflare error in the
CCGM rules.

**Confidence rationale:** The grep for `wrangler pages deploy` is deterministic on the
string match. The main FP case is a CI job that deliberately uses direct-upload for an
artifact-only deployment that is not expected to have Git integration (rare, and should be
commented). The main FN case is a project newly added but not yet committed to a CI file.
High confidence overall because the pattern is unambiguous in the vast majority of cases.

**Rubric entry:** `ccgm/cloudflare-pages-no-git`

#### Fixture

**True positive** (`.github/workflows/deploy.yml`):

```yaml
# FINDS: wrangler pages deploy with a new project name — creates direct-upload project
- name: Deploy to Cloudflare Pages
  run: npx wrangler pages deploy dist --project-name my-app
```

**True negative** (should produce NO finding):

```yaml
# OK: no wrangler pages deploy — project uses Git integration via dashboard
- name: Build
  run: npm run build
# (No deploy step; Cloudflare Pages auto-deploys on push via connected GitHub repo)
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
