# checks.md Template

Copy this file to `packs/{your-pack-name}/checks.md` and fill in each section.
Remove all `<!-- ... -->` comments before shipping the pack.

---

## Scope

<!-- One paragraph: what this pack audits and what it does NOT cover.
     Be specific. "This pack audits SQL migration files for PostgreSQL reserved-keyword
     quoting. It does not audit Go source files or application-level queries." -->

**Pack ID:** `<!-- e.g. ccgm/data-migrations -->`
**Applies when:** `<!-- mirror the applies_when[] array from pack.json -->`

---

## applies_when Rationale

<!-- Explain why each gating condition in pack.json's applies_when[] is necessary
     and sufficient. One sentence per condition.

     Example:
       - `has_migrations`: Pack is only useful when migration files exist; running on
         repos without migrations produces zero signal.
       - `language:sql`:   All checks target SQL syntax; no signal without SQL files.
-->

| Condition | Reason |
|-----------|--------|
| `<!-- condition -->` | `<!-- why this condition gates the pack -->` |

---

## Checks

<!-- One block per check declared in pack.json's checks[].
     The check-id here MUST match the id field in pack.json exactly. -->

---

### `<!-- check-id, e.g. dm/unquoted-reserved-keyword -->`

**Severity:** `<!-- critical | high | medium | low | info -->`
**Confidence:** `<!-- high | medium | low -->`
**Detection:** `<!-- tool | llm | hybrid -->`

#### Detection

<!-- How this check produces findings. -->

**Tool (if detection = tool or hybrid):**
`<!-- Spine tool invoked, e.g. semgrep, gitleaks, gosec, govulncheck -->`

Rule / rule-id: `<!-- e.g. semgrep rule ID, ESLint rule name, or "n/a" -->`

Fallback when tool absent: `<!-- e.g. llm, grep, or "none — skip check" -->`

**LLM instruction (if detection = llm or hybrid):**

```
<!-- Full prompt given to the LLM agent for this check.
     Be specific: what to look for, what constitutes a finding,
     what NOT to flag (false-positive exclusions), and the exact
     output format expected.

     Example:
       Scan every SQL file under db/migrations/ for PostgreSQL reserved
       keywords used as unquoted identifiers. Reserved keywords include:
       position, order, user, offset, limit, key, value, type, name,
       check, default, time, index, comment.

       Flag each occurrence as a finding. Do NOT flag occurrences that
       are already double-quoted (e.g. "position"). Do NOT flag keywords
       that appear in SQL comments or string literals.

       Report: file path, line number, the keyword, the surrounding line.
-->
```

#### Spine Wiring

<!-- How the spine invokes this check. Copy the relevant snippet from the
     spine contract or describe the integration point. -->

```yaml
# Example entry in the spine's check dispatch table:
check_id: dm/unquoted-reserved-keyword
detection: hybrid
tool: semgrep
rule: ccgm.migrations.reserved-keyword
fallback: llm
```

#### Severity / Confidence

<!-- Justify the severity and confidence values declared above.
     Reference the severity rubric if available.

     Example:
       Severity HIGH: An unquoted reserved keyword causes a syntax error that
       blocks the migration from running, directly breaking deployments.

       Confidence HIGH: The set of PostgreSQL reserved keywords is finite and
       deterministic; a regex match on an unquoted token is precise.
-->

**Severity rationale:** `<!-- ... -->`

**Confidence rationale:** `<!-- ... -->`

**Rubric entry:** `<!-- check-id as it appears in severity-rubric.json, or "pending Epic 1.5" -->`

#### Fixture

<!-- A minimal, self-contained example that demonstrates both a TRUE POSITIVE
     (should produce a finding) and a TRUE NEGATIVE (should NOT produce a finding).

     Keep fixtures small — 10-20 lines. Name the hypothetical file clearly. -->

**True positive** (`<!-- e.g. db/migrations/0001_create_users.sql -->`):

```sql
-- FINDS: "position" is a reserved keyword, used unquoted as a column name.
ALTER TABLE events ADD COLUMN position INTEGER;
```

**True negative** (should produce NO finding):

```sql
-- OK: "position" is double-quoted — safe to use as an identifier.
ALTER TABLE events ADD COLUMN "position" INTEGER;
```

---

<!-- Repeat the block above for each additional check in this pack. -->

---

## Quality Checklist

Before submitting a pack PR, confirm every item:

- [ ] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [ ] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [ ] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [ ] Each fixture has both a true positive AND a true negative
- [ ] Severity / confidence rationale is present for every check
- [ ] `applies_when` rationale table is complete
- [ ] `scripts/lint-pack.py` passes on this pack
