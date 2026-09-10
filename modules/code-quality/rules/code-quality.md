# Code Quality Standards

## Simplest Implementation That Fully Meets the Requirements

Choose the simplest implementation that fully meets the current requirements. Both halves carry weight:

- **Simplest**: no abstraction with one implementation, no config option nobody sets, no plugin system for a single plugin, no generic helper called from one place.
- **Fully meets the current requirements**: every stated requirement is handled, edge cases and error paths included. See `completeness.md`.

The requirements that count are the ones that exist now. Build the second case when it arrives; by then its shape is known. Signs the implementation outran the requirements: an interface with one implementer, a config option never set to anything but its default, a layer that only forwards calls, generic type parameters instantiated with the same concrete type everywhere, "we'll need this when we add X" where X is on no roadmap.

## Minimize Dependencies

The ladder: built-in, then established library, then custom implementation, then framework. Check whether the language or platform already provides what you need; when it does not, prefer an established, well-maintained library over hand-rolled code; equal outcome means no dependency.

Built-in wins: pure bash with ANSI escapes over a TUI library for simple menus, `fetch()` over axios, CSS variables over a theming library, shell built-ins over external CLI tools.

Library wins: a maintained date library over hand-written timezone arithmetic, the platform crypto API over a hand-written primitive, a real parser for a real grammar (CSV, YAML, semver, HTML) over regex, a schema validator over per-field checks at every entry point. A hand-rolled implementation is a dependency with no maintainer, no advisories, and no other users finding its bugs. "Established" means released within the last year or explicitly finished, an answered issue tracker, a permissive license, and wide adoption. Twenty lines of obvious logic is not a library's job; anything with a specification behind it (dates, encodings, crypto, grammars, protocols) is.

Justify every new package in the PR description, and justify hand-rolling the same way.

## Code Standards

- When adding env vars, update the corresponding `.env.example`. Never commit secrets.
- Use functional React components with explicit TypeScript prop interfaces.
- New migrations require regenerating TypeScript types; document schema changes in the migration file comments; after merging a PR with migrations, run them immediately rather than deferring to a follow-up.

### Migration Validation

Before committing a migration file:

1. Double-quote PostgreSQL reserved words used as identifiers: `position`, `order`, `user`, `offset`, `limit`, `key`, `value`, `type`, `name`, `check`, `default`, `time`, `index`, `comment`.
2. Use idempotent forms: `CREATE OR REPLACE FUNCTION`; `DROP TRIGGER IF EXISTS` then `CREATE TRIGGER`; `CREATE INDEX IF NOT EXISTS`; `CREATE TABLE IF NOT EXISTS` where appropriate; `ADD COLUMN IF NOT EXISTS`; `DROP POLICY IF EXISTS` then `CREATE POLICY`.
3. Test locally first, preferring `supabase migration up` (keeps local data) over `supabase db reset`.
4. Remember: `ON CONFLICT` needs a unique constraint on the conflict columns; `SECURITY DEFINER` functions run as the owner; RLS policies need `USING` for SELECT/UPDATE/DELETE and `WITH CHECK` for INSERT/UPDATE.

## Testing

Write tests for new features (happy path and key functionality), edge cases (empty states, boundaries, invalid input), bug fixes (a test that reproduces the bug before the fix), and complex logic.

## Error Handling

Frontend: error boundaries around major sections, toast notifications for feedback, inline form validation, explicit loading and error states. Backend: centralized error middleware; generic messages to the client, detailed logs server-side. Fail fast in development, degrade gracefully in production, give users actionable feedback, log errors.

## Security

Sanitize user input before rendering (DOMPurify for HTML), validate uploads (MIME type, size), never commit `.env` files, use Row Level Security for database access, review every user-facing input for injection.

## Build Verification

Do not run lint, type-check, tests, or build after every code change. Run the full verification suite once, immediately before pushing, and never push failing tests, type errors, or lint errors. If the repo has a `.husky/pre-push` hook it runs automatically; otherwise run the same checks CI runs:

```bash
npm run lint
npm run type-check
npm run test:run
npm run build
```

Consider adding a pre-push hook to projects that lack one. Update documentation when requirements or architecture change.

## Living Documents

After every PR merge, check whether `README.md` or `docs/project-story.md` needs a targeted update (5 to 10 minutes, not a rewrite). Update the README when the PR adds or removes a package, changes capabilities or permissions, changes dev commands or the build, changes external services, or changes deployment or payment configuration. Update the project story when the PR represents a notable architectural decision, fixes a non-obvious bug with an interesting root cause, introduces or removes a pattern, changes methodology, starts a new epic, or carries an interesting human decision. Skip typo fixes, dependency bumps, and changes the PR title already describes.
