# Dependencies Audit Pack

## Scope

This pack audits npm dependency health for JavaScript and TypeScript repositories. It covers known CVE vulnerabilities, outdated packages (both minor and major), unused dependencies, and duplicate packages hoisted into the dependency tree. It relies on npm's built-in audit tooling and the knip unused-export analyser. It does NOT audit license compliance (covered by the tos-compliance pack), Python/Go/Rust dependency trees, or indirect peer-dependency conflicts beyond what npm audit reports.

**Pack ID:** `ccgm/dependencies`
**Applies when:** `language:js`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `language:js` | All checks target npm's package.json ecosystem; the dep-audit and knip spine tools require a package.json to function. The `language:js` predicate is emitted by the ecosystem detector for any repository containing a package.json, which covers both JavaScript and TypeScript projects. Wave 4.1 will broaden coverage to Python (pip-audit) and Go (govulncheck) under separate packs. |

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

Rule / rule-id: knip `unlisted` and `unresolved` export/dependency reports

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

## Migration Mapping

Every bullet from the original Agent 2 Dependencies Audit category prompt is mapped to its owning check-id:

| Original prompt bullet | Check-id |
|------------------------|----------|
| npm audit vulnerabilities (auto-fixable: npm audit fix for non-breaking) | `dependencies/npm-audit-vulnerability` |
| Outdated packages - minor versions (auto-fixable: npm update) | `dependencies/outdated-minor` |
| Outdated packages - major versions (NOT auto-fixable - breaking changes) | `dependencies/outdated-major` |
| Unused dependencies (auto-fixable: npm uninstall) | `dependencies/unused-dependency` |
| Duplicate dependencies (NOT auto-fixable - needs investigation) | `dependencies/duplicate-dependency` |

All 5 original bullets are covered. No bullet dropped. The original `Run: npm audit --json, npm outdated --json` instruction is preserved in the individual check LLM instructions.

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
