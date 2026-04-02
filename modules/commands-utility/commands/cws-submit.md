Walk me through submitting a Chrome extension to the Chrome Web Store.

## Context

Read `docs/cws-submission-process.md` for the full step-by-step process. Use it as the source of truth for all steps.

## What to do

1. **Identify the extension** — determine which extension package is being submitted (gmail-darkly, sheets-darkly, docs-darkly, or darkly-suite)

2. **Check prerequisites** — verify landing page, payment API, Stripe config, and E2E testing are complete

3. **Prepare store assets** — check if `packages/{extension}/store-assets/` exists with all required files. If any are missing, create them using Gmail Darkly's store assets as a template (`packages/gmail-darkly/store-assets/`)

4. **Create reviewer promo code** — use Stripe CLI to create a 100% off coupon and promo code. Also create a second one for the user to test with.

5. **Build production zip** — `pnpm --filter {extension} build` then zip the dist directory

6. **Walk through dashboard** — guide the user through each CWS dashboard tab one step at a time using the walkthrough pattern (one step, wait for confirmation, then next)

## Important

- Use `/walkthrough` behavior: one step at a time, wait for user confirmation
- Put all copy-paste text in `.txt` files so the user can copy without formatting
- Max 500 characters for test instructions
- Test instructions MUST include the test card number (4242 4242 4242 4242) — Stripe requires a card even with 100% off promo codes on subscriptions
- Test instructions can be edited after submission without resubmitting
- Always recommend **unchecking** auto-publish (stage for manual publish)
- Remind about live Stripe promo code recreation after approval
- Update the submissions log in `docs/cws-submission-process.md` after submission
- CRITICAL: Test the extension yourself (or ask the user to describe the actual UI) before writing test instructions. Do NOT assume UI behavior — describe exactly what happens.

$ARGUMENTS
