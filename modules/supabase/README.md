# supabase

Supabase-specific rules for API key terminology, environment variable naming, and database workflow.

## What It Does

This module installs a rules file that instructs Claude to:

- Use current Supabase terminology (publishable key / secret key) instead of deprecated terms (anon key / service_role key)
- Follow correct environment variable naming conventions for client and server keys
- Find keys in the correct location in the Supabase Dashboard
- Follow proper database migration workflow with validation

## Manual Installation

Copy `rules/supabase.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/supabase.md ~/.claude/rules/supabase.md

# Project-level
cp rules/supabase.md .claude/rules/supabase.md
```

## Files

| File | Description |
|------|-------------|
| `rules/supabase.md` | Rule file covering Supabase API key terminology, environment variables, and migration workflow |
