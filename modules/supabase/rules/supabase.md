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

## Database Migration Workflow

For detailed migration validation rules (reserved keyword quoting, idempotent patterns, local testing, common gotchas), see the **code-quality** module's migration validation section.

Key reminders:
- New migrations require regenerating TypeScript types
- Document schema changes in the migration file comments
- After merging a PR with migrations, run them immediately via the Supabase MCP `apply_migration` tool or CLI
- Test migrations locally before committing using `supabase migration up` (preferred) or `supabase db reset`
