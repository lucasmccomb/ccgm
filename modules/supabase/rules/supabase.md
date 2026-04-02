# Supabase Rules

## API Key Terminology (IMPORTANT)

Supabase updated their dashboard UI. **Use the current terminology**:

| Current Term | Old/Deprecated Term | Use Case |
|--------------|---------------------|----------|
| **Publishable key** | anon key | Client-side (browser), safe to expose |
| **Secret key** | service_role key | Server-side only, never expose |

**Never use deprecated terms** like "anon key" or "service_role key" when giving instructions - they no longer appear in the Supabase UI.

## Where to Find Keys

1. Go to Supabase Dashboard -> **Settings** -> **API**
2. Select the **"Publishable and secret API keys"** tab (not the legacy tab)
3. Copy the appropriate key:
   - **Publishable key** -> client-side environment variable (e.g., `VITE_SUPABASE_PUBLISHABLE_KEY`)
   - **Secret key** -> server-side environment variable (e.g., `SUPABASE_SECRET_KEY`)

## Environment Variable Naming

```bash
# Client (.env.local) - safe to expose in browser
VITE_SUPABASE_URL=https://<project-id>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...

# Server (.env) - never expose to client
SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
```

The `VITE_` prefix (or framework-equivalent like `NEXT_PUBLIC_`) exposes the variable to the client bundle. Only the publishable key should use this prefix.

## CLI Connection - Circuit Breaker Prevention (CRITICAL)

The Supabase connection pooler has a circuit breaker that locks out a user after repeated failed auth attempts. Once tripped, ALL CLI database operations (`db push`, `migration up`, `db reset`) fail for an extended cooldown period (5-30+ minutes). This blocks all migration work.

**Rules to prevent tripping the circuit breaker:**

1. **Never retry a failing `db push` or `migration up` more than once.** If it fails on the first attempt with an auth error, STOP. Do not retry. Each retry counts as a failed auth attempt against the circuit breaker.
2. **If the first attempt fails with auth error:** Tell the user to re-authenticate immediately: `! npx supabase login`. Wait for confirmation before trying again.
3. **Never run multiple CLI database commands in parallel.** Each spawns its own connection attempt and multiplies failures.
4. **If you see "Circuit breaker open":** Stop all CLI database attempts immediately. Tell the user to re-authenticate (`! npx supabase login`) and wait for the cooldown (a few minutes). Only after they confirm re-auth, try once more.
5. **After a failed auth, wait for user confirmation** that they've re-authenticated before trying again. Do not optimistically retry hoping it will work.

**Fallback order for applying migrations:**
1. `npx supabase db push --linked --include-all` (one attempt only)
2. If auth fails: **always default to asking user to re-authenticate** (`! npx supabase login`), then retry once
3. If circuit breaker is tripped: ask user to re-authenticate, wait a few minutes for cooldown, then retry once
4. **Last resort only** (if CLI is completely unusable after re-auth): give the user the raw SQL to run in the Dashboard SQL Editor as a backup option

## Database Migration Workflow

For detailed migration validation rules (reserved keyword quoting, idempotent patterns, local testing, common gotchas), see the **code-quality** module's migration validation section.

Key reminders:
- New migrations require regenerating TypeScript types
- Document schema changes in the migration file comments
- After merging a PR with migrations, run them immediately via the Supabase MCP `apply_migration` tool or CLI
- Test migrations locally before committing using `supabase migration up` (preferred) or `supabase db reset`
