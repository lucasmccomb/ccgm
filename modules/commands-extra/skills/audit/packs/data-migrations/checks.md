# Data & Migrations Audit

## Scope

This pack audits SQL migration files for PostgreSQL-specific dangerous patterns. It
targets files under known migration directories (`supabase/migrations`, `prisma/migrations`,
`db/migrate`, `db/migrations`, `database/migrations`). Checks cover reserved-keyword
quoting, locking risks from non-concurrent index creation, missing row-level security on
new tables, invalid ON CONFLICT usage, and SECURITY DEFINER functions that require
reviewer attention. This pack does NOT audit application-level query code, ORM model
definitions, or non-SQL config files.

**Pack ID:** `ccgm/data-migrations`
**Applies when:** `["has_migrations"]`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `has_migrations` | Pack is only useful when a recognised migration directory exists; running on repos without migrations produces zero signal and wastes tool invocations. |

---

## Checks

---

### `dm/unquoted-reserved-keyword`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction:**

```
Scan every SQL file under the project's migration directories
(supabase/migrations/, prisma/migrations/, db/migrate/, db/migrations/,
database/migrations/) for PostgreSQL reserved keywords used as unquoted
column, table, or parameter names.

Reserved keywords to check (per PostgreSQL documentation and the CCGM
code-quality rule): position, order, user, offset, limit, key, value,
type, name, check, default, time, index, comment.

Flag each occurrence where the keyword appears as an identifier WITHOUT
double-quotes. Example bad patterns:
  ADD COLUMN position INTEGER
  ADD COLUMN order TEXT
  CREATE TABLE key (...)
  ALTER TABLE t ADD COLUMN index INT

Do NOT flag:
  - Keywords already wrapped in double-quotes: "position", "order", "user"
  - Keywords appearing inside SQL comments (-- comment or /* comment */)
  - Keywords appearing inside string literals ('literal value')
  - Keywords used as SQL syntax (e.g. ORDER in ORDER BY, INDEX in CREATE INDEX)

For each finding report: file path, line number, the unquoted keyword, and
the surrounding SQL line.
```

#### Spine Wiring

```yaml
check_id: dm/unquoted-reserved-keyword
detection: llm
# squawk does NOT emit this check_id. squawk has no built-in rule that maps to
# dm/unquoted-reserved-keyword; parse-squawk.py only maps
# "require-concurrent-index-creation" -> dm/index-without-concurrently, and
# everything else falls to the generic dm/squawk-violation catch-all.
# This check is detected by LLM+grep against the reserved-keyword list above.
# squawk findings appear under dm/squawk-violation or dm/index-without-concurrently,
# not under this check_id.
```

#### Severity / Confidence

**Severity rationale:** An unquoted PostgreSQL reserved keyword causes a syntax error
that prevents the migration from running, directly breaking deployments. This is a HIGH
severity blocker with no runtime fallback — if the migration fails, the deployment rolls
back or stalls.

**Confidence rationale:** The reserved keyword list is finite and deterministic, which
makes LLM+grep detection reliable for clear cases. However, LLM analysis can produce
false positives when a keyword appears in context that looks like an identifier but is
actually valid SQL syntax. MEDIUM confidence reflects this LLM-inherent uncertainty;
tool-backed detection (which would yield HIGH) is not available for this specific pattern
since squawk does not have a dedicated reserved-keyword-as-identifier rule.

**Rubric entry:** `dm/unquoted-reserved-keyword`

#### Fixture

**True positive** (`db/migrations/0001_create_events.sql`):

```sql
-- FINDS: "position" is a reserved keyword, used unquoted as a column name.
ALTER TABLE events ADD COLUMN position INTEGER;
-- FINDS: "order" is reserved, used as column name without quotes.
ALTER TABLE items ADD COLUMN order TEXT;
```

**True negative** (should produce NO finding):

```sql
-- OK: "position" is double-quoted — safe identifier.
ALTER TABLE events ADD COLUMN "position" INTEGER;
-- OK: ORDER BY is SQL syntax, not an identifier.
SELECT * FROM events ORDER BY created_at;
-- OK: appears only in a comment.
-- We decided not to use "order" as a column name.
```

---

### `dm/index-without-concurrently`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `hybrid`

#### Detection

**Tool (detection = hybrid):**
`squawk`

Rule / rule-id: `require-concurrent-index-creation` — squawk's built-in rule for this
pattern. The parser maps this rule to `dm/index-without-concurrently`.

Fallback when tool absent: `llm`

**LLM instruction (hybrid fallback):**

```
Scan every SQL file under the project's migration directories for CREATE INDEX
statements that do NOT use the CONCURRENTLY option.

Flag each occurrence of:
  CREATE INDEX (without CONCURRENTLY)
  CREATE UNIQUE INDEX (without CONCURRENTLY)

Do NOT flag:
  - CREATE INDEX CONCURRENTLY (safe)
  - CREATE UNIQUE INDEX CONCURRENTLY (safe)
  - Index creation inside a transaction block BEGIN...COMMIT — CONCURRENTLY
    is not allowed inside transactions, so this is not a false-positive scenario
    to suppress; flag it and note that a schema change strategy review is needed.
  - Commented-out CREATE INDEX lines

For each finding report: file path, line number, and the full CREATE INDEX statement.
```

#### Spine Wiring

```yaml
check_id: dm/index-without-concurrently
detection: hybrid
tool: squawk
rule: require-concurrent-index-creation
fallback: llm
# parse-squawk.py maps squawk rule "require-concurrent-index-creation"
# -> check_id "dm/index-without-concurrently"
```

#### Severity / Confidence

**Severity rationale:** A non-concurrent index creation on a large table acquires an
`ACCESS EXCLUSIVE` lock, blocking all reads and writes until the index is built. This
can cause multi-minute outages on production tables. The risk is HIGH: real downtime,
not a theoretical vulnerability.

**Confidence rationale:** The squawk rule `require-concurrent-index-creation` has no
false positives for standard PostgreSQL DDL. HIGH confidence for tool-backed detection;
HIGH for LLM fallback (pattern is syntactically unambiguous).

**Rubric entry:** `dm/index-without-concurrently`

#### Fixture

**True positive** (`db/migrations/0002_add_email_index.sql`):

```sql
-- FINDS: CREATE INDEX without CONCURRENTLY locks the table.
CREATE INDEX idx_users_email ON users(email);
CREATE UNIQUE INDEX idx_users_username ON users(username);
```

**True negative** (should produce NO finding):

```sql
-- OK: CONCURRENTLY keyword is present.
CREATE INDEX CONCURRENTLY idx_users_email ON users(email);
CREATE UNIQUE INDEX CONCURRENTLY idx_users_username ON users(username);
```

---

### `dm/missing-rls`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction:**

```
Scan every SQL file under the project's migration directories for CREATE TABLE
statements that create new PostgreSQL tables WITHOUT a corresponding
ENABLE ROW LEVEL SECURITY (RLS) statement.

For each CREATE TABLE found, check whether the same migration file (or any
earlier migration file in the same directory) contains:
  ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;

Flag tables where RLS is NOT enabled anywhere in the migration set. Focus on
Supabase-style projects (supabase/migrations/) where RLS is the primary access
control mechanism. For non-Supabase projects, still flag but note that RLS may
be intentionally absent if another access control layer is in use.

Do NOT flag:
  - System or extension tables (pg_*, information_schema)
  - Temporary tables (CREATE TEMP TABLE / CREATE TEMPORARY TABLE)
  - Tables that have ENABLE ROW LEVEL SECURITY in the same or any migration file
  - Tables where the CREATE TABLE is inside a CREATE SCHEMA or EXTENSION block

For each finding report: the migration file path, the line number of the
CREATE TABLE statement, the table name, and whether any migration file in the
set contains ENABLE ROW LEVEL SECURITY for this table (to distinguish new tables
from inherited ones).
```

#### Spine Wiring

```yaml
check_id: dm/missing-rls
detection: llm
# No spine tool; pure LLM cross-file analysis.
# The LLM must scan all migration files in the directory to check for
# ENABLE ROW LEVEL SECURITY statements across the set.
```

#### Severity / Confidence

**Severity rationale:** A table without RLS in a Supabase (or PostgREST-backed) project
is accessible to any authenticated user with the anon/service role, bypassing all
application-level access control. This is a HIGH severity data-exposure risk.

**Confidence rationale:** MEDIUM confidence because: (1) the LLM must reason cross-file
about whether RLS was enabled in a prior migration, which introduces false positives for
tables where an earlier migration enables RLS; (2) non-Supabase projects may
intentionally omit RLS. Tool detection is not available for this check.

**Rubric entry:** `dm/missing-rls`

#### Fixture

**True positive** (`supabase/migrations/0003_create_documents.sql`):

```sql
-- FINDS: table created without ENABLE ROW LEVEL SECURITY anywhere in migrations.
CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users(id),
  content text
);
-- No ALTER TABLE documents ENABLE ROW LEVEL SECURITY in any migration file.
```

**True negative** (should produce NO finding):

```sql
-- OK: RLS is enabled in the same migration.
CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users(id),
  content text
);
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
```

---

### `dm/on-conflict-without-unique`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction:**

```
Scan every SQL file under the project's migration directories for INSERT statements
or upsert patterns that use ON CONFLICT targeting a specific column or set of
columns WITHOUT a corresponding UNIQUE constraint or UNIQUE INDEX on those columns.

Patterns to flag:
  INSERT INTO t (...) VALUES (...) ON CONFLICT (col1) DO UPDATE ...
  INSERT INTO t (...) VALUES (...) ON CONFLICT (col1, col2) DO UPDATE ...

For each ON CONFLICT clause, check whether the same or any earlier migration file
defines:
  - UNIQUE (col1) as a column constraint or table constraint
  - CREATE UNIQUE INDEX on col1 (or the combined column set)

Do NOT flag:
  - ON CONFLICT ON CONSTRAINT <constraint_name> — this explicitly names a constraint
  - ON CONFLICT DO NOTHING without a column list — no constraint required
  - Cases where a UNIQUE constraint is clearly visible in the same file

For each finding report: the migration file path, the line number of the ON CONFLICT
clause, the targeted column(s), and a note that a UNIQUE constraint or index is
needed on those columns for the ON CONFLICT to be valid.
```

#### Spine Wiring

```yaml
check_id: dm/on-conflict-without-unique
detection: llm
# No spine tool; pure LLM cross-file analysis.
# The LLM must cross-reference ON CONFLICT column lists against
# UNIQUE constraints and indexes across all migration files.
```

#### Severity / Confidence

**Severity rationale:** An ON CONFLICT clause without a backing UNIQUE constraint causes
a runtime PostgreSQL error (`there is no unique or exclusion constraint matching the ON
CONFLICT specification`) that will fail every INSERT/UPSERT operation, breaking
application logic. MEDIUM severity because this is a runtime logic error rather than a
security issue or data-loss risk.

**Confidence rationale:** MEDIUM confidence because: (1) the LLM must reason cross-file
about whether a UNIQUE constraint is defined in an earlier migration; (2) the pattern
`ON CONFLICT ON CONSTRAINT <name>` legitimately exists and must be excluded. Tool
detection is not available for this check.

**Rubric entry:** `dm/on-conflict-without-unique`

#### Fixture

**True positive** (`db/migrations/0004_add_upsert.sql`):

```sql
-- FINDS: ON CONFLICT (email) but no UNIQUE constraint on email.
INSERT INTO users (email, name) VALUES ($1, $2)
ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name;
-- (No CREATE UNIQUE INDEX or UNIQUE(email) anywhere in migration files)
```

**True negative** (should produce NO finding):

```sql
-- OK: UNIQUE constraint is present in the same migration.
ALTER TABLE users ADD CONSTRAINT users_email_unique UNIQUE (email);
INSERT INTO users (email, name) VALUES ($1, $2)
ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name;
```

---

### `dm/security-definer-function`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `hybrid`

#### Detection

**Tool (detection = hybrid):**
`sqlfluff`

Rule / rule-id: sqlfluff parses SQL files; the parser detects `SECURITY DEFINER` in
function definitions by matching the description string against a pattern. When sqlfluff
is absent, the LLM fallback below applies.

Fallback when tool absent: `llm`

**LLM instruction (hybrid fallback):**

```
Scan every SQL file under the project's migration directories for PostgreSQL
function or procedure definitions that include the SECURITY DEFINER clause.

Pattern to match (case-insensitive):
  CREATE [OR REPLACE] FUNCTION ...
  ...
  SECURITY DEFINER
  ...

Flag each SECURITY DEFINER function as requiring explicit reviewer attention.
SECURITY DEFINER functions run as the function owner (typically a superuser),
not the calling user. Misuse allows privilege escalation. Every instance should
be reviewed to confirm:
  1. The privilege elevation is intentional and necessary.
  2. The function validates input to prevent SQL injection at the elevated
     privilege level.
  3. The function is not callable by untrusted roles without appropriate REVOKE/GRANT.

Do NOT suppress findings — every SECURITY DEFINER function should be flagged
for review. This is an "always review" check, not a "definitely a bug" check.

For each finding report: the migration file path, the line number of the
SECURITY DEFINER clause or the CREATE FUNCTION statement, and the function name.
```

#### Spine Wiring

```yaml
check_id: dm/security-definer-function
detection: hybrid
tool: sqlfluff
fallback: llm
# parse-sqlfluff.py maps violations whose description matches
# /security[\s_-]*definer/i -> check_id "dm/security-definer-function"
# All other sqlfluff violations map to dm/sqlfluff-violation.
```

#### Severity / Confidence

**Severity rationale:** SECURITY DEFINER functions run as the owning role, typically a
superuser. An incorrectly scoped or input-validating SECURITY DEFINER function can be
exploited for privilege escalation. MEDIUM severity because: (1) not every SECURITY
DEFINER function is a bug — some are intentional; (2) this is a "flag for review" check
rather than a definitive vulnerability.

**Confidence rationale:** HIGH confidence because the `SECURITY DEFINER` keyword is
syntactically unambiguous and cannot appear as a false positive in well-formed SQL.
Both sqlfluff detection and LLM detection are reliable for this pattern.

**Rubric entry:** `dm/security-definer-function`

#### Fixture

**True positive** (`supabase/migrations/0005_add_rpc.sql`):

```sql
-- FINDS: SECURITY DEFINER function — flagged for review.
CREATE OR REPLACE FUNCTION admin_get_all_users()
RETURNS SETOF auth.users
LANGUAGE sql
SECURITY DEFINER
AS $$
  SELECT * FROM auth.users;
$$;
```

**True negative** (should produce NO finding):

```sql
-- OK: no SECURITY DEFINER — function runs as caller.
CREATE OR REPLACE FUNCTION get_my_profile(user_id uuid)
RETURNS TABLE(id uuid, email text)
LANGUAGE sql
AS $$
  SELECT id, email FROM profiles WHERE id = user_id;
$$;
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

## Migration Mapping

| check_id | spine namespace | detection | tool (spine) | notes |
|----------|----------------|-----------|--------------|-------|
| `dm/unquoted-reserved-keyword` | `dm/` | `llm` | none | squawk has no rule mapping to this id; detected by LLM+grep against the reserved-keyword list. squawk findings appear as `dm/squawk-violation` or `dm/index-without-concurrently`. |
| `dm/index-without-concurrently` | `dm/` | `hybrid` | squawk (`require-concurrent-index-creation`) | `parse-squawk.py` maps this rule directly to this check_id. |
| `dm/missing-rls` | `dm/` | `llm` | none | pure LLM cross-file analysis; no spine tool. |
| `dm/on-conflict-without-unique` | `dm/` | `llm` | none | pure LLM cross-file analysis; no spine tool. |
| `dm/security-definer-function` | `dm/` | `hybrid` | sqlfluff (description pattern match) | `parse-sqlfluff.py` maps violations matching `/security[\s_-]*definer/i` to this id. All other sqlfluff violations map to `dm/sqlfluff-violation`. |
| `dm/squawk-violation` (catch-all) | `dm/` | `tool` | squawk (fallback for all unmapped rules) | emitted by `parse-squawk.py` for any squawk rule not explicitly mapped. NOT a declared pack check; surfaces in findings under its rubric entry. |
| `dm/sqlfluff-violation` (catch-all) | `dm/` | `tool` | sqlfluff (fallback for non-SECURITY-DEFINER violations) | emitted by `parse-sqlfluff.py` for any sqlfluff violation whose description does not match the SECURITY DEFINER pattern. NOT a declared pack check; surfaces in findings under its rubric entry. |
