# Secrets & Credentials Pack

## Scope

This pack audits git repositories for exposed secrets and credentials: values committed to version
control that should never be tracked. It covers credentials found in the full git history (including
commits that were later reverted or squashed), `.env` files tracked by git, and private key material
checked into the repo. It does NOT audit runtime secret injection, environment variable
configuration, or secrets stored in external vaults. Dependency CVE scanning is covered by the
dependencies pack; runtime misconfigurations are covered by the security pack.

**Pack ID:** `ccgm/secrets`
**Applies when:** `always`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | Secrets can be committed to any repository regardless of language, framework, or purpose. Running on all repos maximises coverage; a single committed credential in a non-JS repo can be just as damaging as one in a production service. |

---

## Checks

---

### `secrets/leaked-credential`

**Severity:** `critical`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

**Tool (if detection = tool or hybrid):**
`gitleaks`

Rule / rule-id: gitleaks default ruleset (all built-in secret patterns)

Fallback when tool absent: none — skip check (emit coverage_gap)

**Scan mode:**
The secrets pack invokes `wrap-gitleaks.sh` with `CCGM_GITLEAKS_HISTORY=1` to perform a
**full git history scan** (`gitleaks git`). This finds credentials that were committed in any
historical commit, including those removed at HEAD. No network calls are made; gitleaks
works entirely from the local git object store.

**Redaction (§3.7):**
`parse-gitleaks.py` redacts every matched secret value before it enters the finding message.
The redaction format is: first 4 characters, then `[redacted:len=N]` where N is the total
length of the matched value. Example: `ghp_AbcXyz...` becomes `ghp_[redacted:len=40]`.
The raw secret value never appears in JSONL output.

**--verify-secrets opt-in contract:**
Live verification (checking whether a detected credential is still active by calling the
issuing service's API) is OFF by default. Enabling it requires setting
`CCGM_GITLEAKS_VERIFY=1` AND obtaining explicit security-review approval (gate C1) because
verification makes outbound network calls to credential issuers. trufflehog provides this
capability as an independent optional wrapper (not installed by default); do not wire a
default-on verification path. The default scan is fully offline.

#### Spine Wiring

```yaml
check_id: secrets/leaked-credential
detection: tool
tool: gitleaks
scan_mode: full-history (CCGM_GITLEAKS_HISTORY=1)
```

**Note:** `secrets/leaked-credential` is the canonical rubric id for all gitleaks findings.
The `security/hardcoded-secret` check-id is reserved for LLM-originated findings in the
security pack. Do not emit `security/hardcoded-secret` from this pack's tool path.

#### Severity / Confidence

**Severity rationale:** Any credential reachable from the git history gives every person
with repo read access (including anyone who cloned it) direct, persistent access to the
protected resource. Revocation and rotation are required. CRITICAL.

**Confidence rationale:** gitleaks uses well-tuned pattern rules with low false-positive
rates for its high-signal detectors (AWS keys, GitHub tokens, Stripe keys). The redaction
step does not affect confidence scoring. HIGH.

**Rubric entry:** `secrets/leaked-credential`

#### Fixture

**True positive** (`config/prod.env` committed in a prior commit):

```bash
# FINDS: AWS access key committed in history
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

**True negative** (should produce NO finding):

```bash
# OK: value is a placeholder, not a real credential
AWS_ACCESS_KEY_ID=your-access-key-here
AWS_SECRET_ACCESS_KEY=your-secret-key-here
```

---

### `secrets/tracked-env-file`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `hybrid`

#### Detection

**Tool (if detection = tool or hybrid):**
`grep`

Rule / rule-id: `git ls-files` piped to grep matching `.env`, `.env.*` patterns with
real-looking key=value assignments (non-placeholder values of length >= 8).

Fallback when tool absent: `llm`

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/security-patterns.md
Use the pattern regexes and severity guidelines from that file to guide detection.

Check whether the git index (tracked files) contains any .env file or .env.* variant
(e.g. .env.local, .env.production, .env.staging, .env.test) that contains real-looking
secret assignments. A "real-looking" assignment is a KEY=value line where the value is
NOT a placeholder (not "your-key-here", "REPLACE_ME", "TODO", "example", or similar).

Also check for private key files tracked by git: files matching *.pem, id_rsa, id_ed25519,
*.p12, *.pfx, *.key when tracked in the git index (not just present on disk).

Look for:
- `git ls-files` output containing .env, .env.local, .env.production, .env.staging, etc.
- File contents containing lines matching KEY=<non-placeholder-value>
- Files with names matching private key patterns tracked in the index

Do NOT flag:
- .env.example or .env.template files (names clearly indicate sample/template)
- Files whose values are all placeholders or environment-variable references
- Files outside the git index (only flag files tracked by git, not .gitignored ones)

For each finding: file path (repo-relative), the type of exposed content, and the
recommended fix (add to .gitignore, rotate any exposed values, use a secrets manager).
auto_fixable=false -- requires human judgment to determine which values need rotation.
```

#### Spine Wiring

```yaml
check_id: secrets/tracked-env-file
detection: hybrid
tool: grep
fallback: llm
```

#### Severity / Confidence

**Severity rationale:** A tracked `.env` file exposes all its assignments to every git
clone recipient. Even if values are rotated, the git history retains the exposure.
HIGH (not CRITICAL) because the presence of the file in the index does not guarantee
the values are active production credentials — they may be development stubs.

**Confidence rationale:** The combination of filename pattern matching and non-placeholder
value detection is deterministic and produces very few false positives. HIGH.

**Rubric entry:** `secrets/tracked-env-file`

#### Fixture

**True positive** (`.env.production` tracked in git):

```bash
# FINDS: production env file committed with real-looking values
DATABASE_URL=postgres://admin:s3cr3tp4ss@db.prod.example.com/app
STRIPE_SECRET_KEY=sk_live_EXAMPLE_DO_NOT_USE_0000000
```

**True negative** (should produce NO finding):

```bash
# OK: .env.example is a template -- values are placeholders
# File: .env.example
DATABASE_URL=postgres://user:password@localhost/myapp
STRIPE_SECRET_KEY=your-stripe-secret-key-here
```

---

### `secrets/tracked-key-material`

**Severity:** `critical`
**Confidence:** `high`
**Detection:** `hybrid`

#### Detection

**Tool (if detection = tool or hybrid):**
`grep`

Rule / rule-id: `git ls-files` output matched against private key filename patterns:
`*.pem`, `id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa`, `*.p12`, `*.pfx`, `*.key`
(excluding `*.pub` public-key counterparts). Also matches file contents containing
`-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----`.

Fallback when tool absent: `llm`

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/security-patterns.md

Scan all git-tracked files for private key material. Flag:

1. Files whose names match private key patterns tracked in the git index:
   - *.pem (certificate/key bundles)
   - id_rsa, id_ed25519, id_ecdsa, id_dsa (SSH private keys)
   - *.p12, *.pfx (PKCS#12 key stores)
   - Files whose names contain "private_key", "privatekey", or "private-key"
     (excluding *.pub public key counterparts)

2. Files whose contents contain a PEM private key header:
   -----BEGIN RSA PRIVATE KEY-----
   -----BEGIN EC PRIVATE KEY-----
   -----BEGIN OPENSSH PRIVATE KEY-----
   -----BEGIN PRIVATE KEY-----

Do NOT flag:
- Public key files (*.pub, files with "public_key" in the name)
- Certificate files that contain ONLY a public certificate (no private key)
- PEM headers inside test fixture directories clearly marked as fake/example
  (e.g. test/fixtures/example.pem containing "EXAMPLE" in the key body)

For each finding: file path (repo-relative), the type of key material found,
and the recommended fix (remove from git history via git filter-repo or
BFG Repo Cleaner, rotate the key immediately).
auto_fixable=false -- key rotation and history rewriting require human action.
```

#### Spine Wiring

```yaml
check_id: secrets/tracked-key-material
detection: hybrid
tool: grep
fallback: llm
```

#### Severity / Confidence

**Severity rationale:** A tracked private key gives any clone recipient the ability to
impersonate the key holder, decrypt traffic, or authenticate as the key's owner. This
is an immediate, irreversible exposure until the key is revoked. CRITICAL.

**Confidence rationale:** Private key PEM headers and standard filename conventions
(`id_rsa`, `*.p12`) are highly precise signals with virtually no false positives when
matched against the git index. HIGH.

**Rubric entry:** `secrets/tracked-key-material`

#### Fixture

**True positive** (`deploy/server.key` tracked in git):

```
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA2a2rwplBQLF29amygykEMmYz0+Kcj3bKBp29R2tXRohGEIiJ
...
-----END RSA PRIVATE KEY-----
```

**True negative** (should produce NO finding):

```
# OK: public key only, no private key material
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2a2rwplBQL...
-----END PUBLIC KEY-----
```

---

### `secrets/history-only-credential`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

**Tool (if detection = tool or hybrid):**
`gitleaks`

Rule / rule-id: gitleaks default ruleset — findings from `gitleaks git` (history scan)
where the reported file path does not exist at HEAD (i.e., the secret was committed and
subsequently removed or renamed).

Fallback when tool absent: none — skip check (emit coverage_gap)

**Scan mode:** Same full-history scan as `secrets/leaked-credential`
(`CCGM_GITLEAKS_HISTORY=1`). This check is a logical refinement: it represents the
subset of gitleaks findings where the leaking file no longer exists at HEAD. The
distinction matters for remediation priority — a history-only credential must be
removed from git history (e.g., via `git filter-repo` or BFG Repo Cleaner) rather than
simply deleting the file.

**Redaction:** Same §3.7 first-4+length redaction as `secrets/leaked-credential`.

#### Spine Wiring

```yaml
check_id: secrets/history-only-credential
detection: tool
tool: gitleaks
scan_mode: full-history (CCGM_GITLEAKS_HISTORY=1)
note: subset of gitleaks findings where the file no longer exists at HEAD
```

#### Severity / Confidence

**Severity rationale:** A credential removed at HEAD is still reachable from any git
clone via `git log` or object inspection. Anyone who cloned the repo before or after the
removal has access to the full history. HIGH rather than CRITICAL because the credential
may already be rotated — but rotation without history rewriting leaves the exposure
permanently accessible to anyone with repo access.

**Confidence rationale:** gitleaks history detection is high-precision for its built-in
patterns. The additional filter (file absent at HEAD) is a deterministic git operation.
HIGH.

**Rubric entry:** `secrets/history-only-credential`

#### Fixture

**True positive** (secret committed in commit A, file deleted in commit B, HEAD has no such file):

```
Commit A: secrets.env contains
  GITHUB_TOKEN=ghp_AbcDefGhiJklMnoPqrStuVwxYz012345

Commit B: git rm secrets.env

HEAD: secrets.env does not exist
-> gitleaks git detects the token in commit A; file absent at HEAD -> history-only-credential
```

**True negative** (should produce NO finding):

```
# OK: the file exists at HEAD -- this is a leaked-credential finding, not history-only
HEAD: secrets.env contains
  GITHUB_TOKEN=ghp_AbcDefGhiJklMnoPqrStuVwxYz012345
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
