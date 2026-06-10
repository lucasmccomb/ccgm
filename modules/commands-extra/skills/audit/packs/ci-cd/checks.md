# CI/CD Hardening Pack

## Scope

This pack audits GitHub Actions workflow files for supply-chain and security issues:
unpinned third-party actions, dangerous trigger configurations, overbroad GITHUB_TOKEN
permissions, expression-injection vulnerabilities, and actionlint syntax/usage errors.
It does NOT audit application source code, Docker images, or non-GitHub CI systems
(e.g. CircleCI, Jenkins). It operates exclusively on files under `.github/workflows/`.

**Pack ID:** `ccgm/ci-cd`
**Applies when:** `has_workflows`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `has_workflows` | The pack audits `.github/workflows/` files exclusively; a repo without that directory has zero workflow files to scan, making all five checks vacuous. |

---

## Checks

---

### `cicd/unpinned-action`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `hybrid`

#### Detection

**Tool (hybrid):**
`pinact`

Rule / rule-id: `pinact/unpinned-uses`

Fallback when tool absent: `llm`

**LLM instruction (hybrid fallback when pinact absent):**

```
Scan every workflow file under .github/workflows/ for third-party actions
referenced by a mutable tag or branch instead of a full 40-character commit SHA.

A third-party action is any `uses:` line where the owner is not the repo itself
(i.e., not `./`). First-party actions (`uses: ./.github/actions/...`) are out
of scope.

Flag each occurrence where the ref after `@` is NOT a 40-char lowercase hex
string (e.g. `@v4`, `@main`, `@master`, `@latest` are all mutable and must be
flagged).

Do NOT flag pinned actions such as `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683`.
Do NOT flag Docker images in `image:` keys.

For each finding report: file path, line number, the full `uses:` value,
and a one-sentence explanation of the supply-chain risk.
```

#### Spine Wiring

```yaml
check_id: cicd/unpinned-action
detection: hybrid
tool: pinact
rule: pinact/unpinned-uses
fallback: llm
```

The spine calls `wrap-pinact.sh <repo_root>` which runs
`pinact run --check <workflow_files...>` and pipes output through
`parse-pinact.py`. The parser normalizes each unpinned-action line into a
`cicd/unpinned-action` finding with `properties.tool = "pinact"`.

#### Severity / Confidence

**Severity rationale:** A mutable action ref (tag, branch) can be hijacked via
a tag-swap or branch-force-push attack; a compromised action runs in the CI
environment with access to secrets and the GITHUB_TOKEN. This is a direct
supply-chain risk rated HIGH by GitHub's security hardening guide.

**Confidence rationale:** The check is deterministic — an action ref that is
not a 40-char hex SHA is factually mutable; there are no false positives from
pinact's analysis.

**Rubric entry:** `cicd/unpinned-action`

#### Fixture

**True positive** (`.github/workflows/ci.yml`):

```yaml
# FINDS: actions/checkout@v4 is a mutable tag, not a pinned SHA.
- uses: actions/checkout@v4
```

**True negative** (should produce NO finding):

```yaml
# OK: full 40-char commit SHA — pinned and reproducible.
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4
```

---

### `cicd/dangerous-trigger`

**Severity:** `critical`
**Confidence:** `high`
**Detection:** `hybrid`

#### Detection

**Tool (hybrid):**
`zizmor`

Rule / rule-id: `zizmor/dangerous-triggers` / `zizmor/pull-request-target`

Fallback when tool absent: `llm`

**LLM instruction (hybrid fallback when zizmor absent):**

```
Scan every workflow file under .github/workflows/ for the dangerous
`pull_request_target` trigger combined with a checkout step that fetches
untrusted code.

A workflow is dangerous when ALL of the following are true:
  1. It uses `on: pull_request_target` (or includes it in a list of triggers).
  2. It contains a `uses: actions/checkout` step that checks out the PR head
     (i.e., `ref: ${{ github.event.pull_request.head.sha }}` or similar), OR
     it does not pass `persist-credentials: false`.

Flag the `on:` line and any corresponding checkout step as findings.
Do NOT flag `pull_request_target` when there is no checkout of external code
(e.g., a workflow that only posts a comment using a static token).
Do NOT flag `on: pull_request` (without `_target`) — it runs in a sandboxed
context and is not affected by this class of vulnerability.

For each finding report: file path, line number of the `on:` declaration,
and a one-sentence explanation of the pwn-request risk.
```

#### Spine Wiring

```yaml
check_id: cicd/dangerous-trigger
detection: hybrid
tool: zizmor
rule: zizmor/dangerous-triggers
fallback: llm
```

The spine calls `wrap-zizmor.sh <repo_root>` which runs
`zizmor --format sarif <workflow_files...>` and pipes output through
`parse-zizmor.py`. The parser maps zizmor rule IDs containing
`dangerous-trigger` or `pull-request-target` to `cicd/dangerous-trigger`.

#### Severity / Confidence

**Severity rationale:** `pull_request_target` with an untrusted checkout gives
attacker-controlled code access to secrets and write permissions on the target
repo — the canonical "pwn-request" vulnerability class, rated CRITICAL by the
GitHub security advisory team and GHSL researchers.

**Confidence rationale:** zizmor performs static analysis that tracks both the
trigger type and checkout patterns; the combined signal is precise and
well-documented. Rated HIGH confidence.

**Rubric entry:** `cicd/dangerous-trigger`

#### Fixture

**True positive** (`.github/workflows/pr-target.yml`):

```yaml
# FINDS: pull_request_target + checkout of PR head = pwn-request
on: pull_request_target
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
```

**True negative** (should produce NO finding):

```yaml
# OK: pull_request (not pull_request_target) — runs in a sandbox.
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
```

---

### `cicd/excessive-permissions`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

**Tool:**
`zizmor`

Rule / rule-id: `zizmor/excessive-permissions` / `zizmor/artipacked`

Fallback when tool absent: none — skip check

**LLM instruction (if detection = llm or hybrid):**

n/a — detection is `tool` only.

#### Spine Wiring

```yaml
check_id: cicd/excessive-permissions
detection: tool
tool: zizmor
rule: zizmor/excessive-permissions
```

The spine calls `wrap-zizmor.sh <repo_root>`. The parser maps zizmor rule IDs
containing `excessive-permissions` or `artipacked` to
`cicd/excessive-permissions` with `properties.tool = "zizmor"`.

#### Severity / Confidence

**Severity rationale:** Overbroad `GITHUB_TOKEN` permissions (e.g. `write-all`
at the workflow or job level) grant more access than needed; a compromised step
can push code, approve PRs, or modify releases. MEDIUM severity because
over-permission is a risk multiplier rather than a direct exploit path.

**Confidence rationale:** zizmor reads the `permissions:` key statically and
flags write-all or explicitly broad write grants; the check is deterministic
with high precision.

**Rubric entry:** `cicd/excessive-permissions`

#### Fixture

**True positive** (`.github/workflows/deploy.yml`):

```yaml
# FINDS: write-all grants unnecessary write permissions across all scopes.
permissions: write-all
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: echo "deploying"
```

**True negative** (should produce NO finding):

```yaml
# OK: minimal permissions declared explicitly.
permissions:
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: echo "deploying"
```

---

### `cicd/script-injection`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

**Tool:**
`zizmor`

Rule / rule-id: `zizmor/template-injection` / `zizmor/expression-injection`

Fallback when tool absent: none — skip check

**LLM instruction (if detection = llm or hybrid):**

n/a — detection is `tool` only.

#### Spine Wiring

```yaml
check_id: cicd/script-injection
detection: tool
tool: zizmor
rule: zizmor/template-injection
```

The spine calls `wrap-zizmor.sh <repo_root>`. The parser maps zizmor rule IDs
containing `template-injection` or `expression-injection` to
`cicd/script-injection` with `properties.tool = "zizmor"`.

#### Severity / Confidence

**Severity rationale:** Interpolating `${{ github.event.* }}` expressions
directly into a `run:` shell script allows a PR author to inject arbitrary
shell commands that execute with the workflow's permissions and token. This is
a well-known attack vector (e.g. CVE-2021-29476 class) rated HIGH.

**Confidence rationale:** zizmor statically traces expression usage into
`run:` scripts; the analysis is taint-based and has low false-positive rates
on the injection patterns it covers.

**Rubric entry:** `cicd/script-injection`

#### Fixture

**True positive** (`.github/workflows/comment.yml`):

```yaml
# FINDS: ${{ github.event.pull_request.title }} interpolated into run: script.
- name: Echo title
  run: echo "${{ github.event.pull_request.title }}"
```

**True negative** (should produce NO finding):

```yaml
# OK: value assigned to env var, not directly interpolated into shell.
- name: Echo title
  env:
    PR_TITLE: ${{ github.event.pull_request.title }}
  run: echo "$PR_TITLE"
```

---

### `cicd/actionlint-error`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

**Tool:**
`actionlint`

Rule / rule-id: `actionlint/<kind>` (the kind field from actionlint JSON output)

Fallback when tool absent: none — skip check

**LLM instruction (if detection = llm or hybrid):**

n/a — detection is `tool` only.

#### Spine Wiring

```yaml
check_id: cicd/actionlint-error
detection: tool
tool: actionlint
rule: actionlint/<kind>
```

**Namespace note:** actionlint findings are produced by the pre-existing
`wrap-actionlint.sh` + `parse-actionlint.py` wrapper pair; they are emitted
under `check_id = "ci/workflow-issue"` (not `cicd/actionlint-error`). The
`cicd/actionlint-error` check in this pack is a logical reference to that
surface: the same actionlint wrapper runs as part of the CI/CD pack, and its
findings appear in the output stream under the `ci/workflow-issue` namespace.
When aggregating pack findings, consumers should treat `ci/workflow-issue`
findings with `properties.tool = "actionlint"` as satisfying
`cicd/actionlint-error`.

#### Severity / Confidence

**Severity rationale:** actionlint catches type errors, undefined contexts,
invalid event names, and shell-script issues in workflows; such errors cause
CI failures or silent misbehavior. MEDIUM severity because these are
correctness errors, not direct security exploits.

**Confidence rationale:** actionlint is a static analysis tool with
well-defined grammar for GitHub Actions; its error reports are precise and
have very low false-positive rates.

**Rubric entry:** `cicd/actionlint-error`

#### Fixture

**True positive** (`.github/workflows/broken.yml`):

```yaml
# FINDS: undefined context "github.nonexistent_field"
- name: Broken step
  run: echo ${{ github.nonexistent_field }}
```

**True negative** (should produce NO finding):

```yaml
# OK: valid expression context.
- name: OK step
  run: echo ${{ github.sha }}
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
