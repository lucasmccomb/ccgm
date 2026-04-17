# Config Change Detection

**Iron Law:** RE-VERIFY WHEN CONFIG CHANGES. NEVER ASSUME LAST RUN'S RESULT STILL APPLIES.

This is a specialization of the verification discipline for automation that is dangerous on first run or after configuration drift. Deploys, migrations, new integrations, any workflow that depends on an external contract (env file, deploy config, wrangler.toml, CI secrets) must re-verify when that contract changes. A green run last week does not prove anything about today's config.

## The Hash-of-Config Pattern

Record a hash of the relevant config section. Before running the automation, compare the stored hash against a fresh hash. If they differ (or no hash exists), the automation is in one of two states:

- **FIRST_RUN**: no marker file exists. The config has never been verified on this machine.
- **CONFIG_CHANGED**: marker file exists, but the current hash does not match. The config drifted since last verification.

In either state, run a dry-run or full verification step before the destructive/expensive action, then update the marker.

### Minimal Implementation

```bash
# Hash the relevant config slice (section of CLAUDE.md, plus workflow files)
CONFIG_HASH=$(
  {
    sed -n '/^## Deploy/,/^## /p' CLAUDE.md
    cat .github/workflows/deploy.yml 2>/dev/null
    cat wrangler.toml 2>/dev/null
  } | shasum -a 256 | awk '{print $1}'
)

MARKER="$HOME/.claude/projects/${PROJECT_SLUG}/deploy-confirmed"

if [ ! -f "$MARKER" ] || [ "$(cat "$MARKER")" != "$CONFIG_HASH" ]; then
  # FIRST_RUN or CONFIG_CHANGED - run dry-run / verification
  echo "Config changed or never verified. Running dry-run..."
  run_dry_run_and_await_user_confirmation
  echo "$CONFIG_HASH" > "$MARKER"
fi

# Config verified, proceed with automation
run_real_action
```

## Marker File Strategy

Store markers under `~/.claude/projects/{slug}/{operation}-confirmed`, one file per operation. The file contains the hash only. The directory structure isolates per-project state without polluting the repo.

Rules:

- **One marker per operation**, not per project. `deploy-confirmed`, `migrate-confirmed`, `env-sync-confirmed` are separate.
- **Never commit markers to git**. They are local trust state, not shared truth.
- **Include every file that affects the outcome** in the hash input. Missing a file (a new workflow step, a new env var) defeats the pattern.
- **Order the hash input deterministically**. Sort file paths or use a fixed concatenation order so identical configs always produce identical hashes.

## What to Hash

For each operation type, define the config surface that actually controls behavior:

| Operation | Hash Input |
|-----------|-----------|
| Deploy | Deploy section of CLAUDE.md + deploy workflow files + platform config (wrangler.toml, vercel.json, fly.toml) |
| Migration | Schema directory + `package.json` db scripts + migration runner config |
| Integration | `.env.example` + integration config file + any setup scripts |
| Package rebuild | `package.json` + lockfile + build script section of CLAUDE.md |

If you cannot name the files that control the operation, the operation is not safe to automate yet. Identify them first.

## When to Apply

Use this pattern when all of the following are true:

- The automation is **expensive** (deploy, migration, large build) or **destructive** (drops data, rewrites history, charges money)
- The automation depends on **external config** that a human might edit without re-running
- A **dry-run or verification step** exists that costs less than the real run

Do not apply it to:

- Idempotent read-only checks (tests, lints, type checks) - these are already cheap to re-run fresh
- One-off scripts that never run twice
- Operations where the config IS the command (e.g., `rm -rf dist` has no external config to drift)

## Integration with the Verification Discipline

The base verification rule ("Evidence before claims") requires fresh proof every time. Config change detection is the mechanism that tells you **when fresh proof needs to include a full dry-run**, not just a check of the last run's artifact.

Without this mechanism, agents default to one of two failure modes:

- **Always dry-run** (slow, defeats automation) or
- **Never dry-run after first success** (ships config drift to production)

The hash marker resolves the tradeoff: automated when safe, interactive when the contract changed.

## Rationalizations That Mean You Are About to Skip Re-Verification

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "The deploy worked last week, it will work now" | Config can drift without you touching the deploy script. A new env var, a changed secret, a workflow edit. |
| "I only changed docs, not the deploy config" | If the hash input includes only deploy files, the docs change will not trigger re-verify. If it does include CLAUDE.md, re-verify anyway - you might have documented a change that is not yet reflected in code. |
| "The dry-run is annoying" | Annoying is cheaper than a broken production deploy or a migration run against the wrong database. |
| "I can eyeball the config diff" | Eyeballing is not verification. A hash comparison is deterministic; human memory is not. |

## Red Flags

Stop and re-run the dry-run if you catch yourself:

- Running a deploy command without checking whether the marker exists
- Copying a hash check from another project without updating the hash input list for this operation
- Deleting or ignoring a marker file to "just get past it"
- Committing a marker file to the repo (it is local trust state, not shared truth)
