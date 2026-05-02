# AGENTS.md

<!-- AGENTS.md is machine-readable ops docs.
     Each section is a labeled command block. No narrative prose.
     An agent reads the label, pastes the block, runs it.
     Replace all YOUR_VALUE_HERE placeholders with real values.

     This template uses "pagegen" (a fictional static-site CLI) as the example project.
     Delete this comment block before shipping. -->

## Install

```bash
# Clone and enter the repo
git clone git@github.com:your-org/your-repo.git
cd your-repo

# Install dependencies
npm install

# Copy env template and fill in values
cp .env.example .env
# Required vars (see .env.example for descriptions):
#   PAGEGEN_API_KEY=YOUR_VALUE_HERE
#   PAGEGEN_SITE_ID=YOUR_VALUE_HERE
#   DATABASE_URL=YOUR_VALUE_HERE

# Run database migrations
npx pagegen migrate up

# Verify the setup
npx pagegen doctor
```

<!-- Install: list every step in order. Missing steps cause mid-run failures.
     Include env vars even if the agent cannot fill them — it will pause and ask. -->

## Build

```bash
# Build all output (runs type-check + bundler)
npm run build

# Output lands in ./dist/
```

<!-- Build: the single command that produces the deployable artifact.
     If you have multiple targets, label them:
       # client
       npm run build:client
       # server
       npm run build:server -->

## Test

```bash
# Full test suite (unit + integration)
npm test

# Watch mode (development)
npm run test:watch

# E2E tests (requires a running dev server — see Debug: dev server below)
npm run test:e2e
```

<!-- Test: one command per suite. Include the watch-mode command labeled separately.
     If a suite requires a precondition (running server, seeded DB), say so with a comment. -->

## Deploy

```bash
# Build first
npm run build

# Deploy to production (uses PAGEGEN_API_KEY from .env)
npx pagegen deploy --env production

# Run post-deploy migrations
npx pagegen migrate up --env production

# Verify deployment is live
curl -I https://your-site.example.com
```

<!-- Deploy: list every step in order, including post-deploy steps like migrations.
     If a step requires a secret the agent does not have, name the env var.
     Never say "click Deploy" — if that is the only path, say so explicitly and
     note it requires a human with browser access. -->

## Debug

### Debug: build fails

```bash
# See full type errors
npx tsc --noEmit

# See bundler errors with verbose output
npm run build -- --verbose

# Check for missing env vars
npx pagegen doctor
```

### Debug: tests fail

```bash
# Run only the failing test file
npx jest path/to/failing.test.ts --verbose

# Show last 50 lines of test output
npm test 2>&1 | tail -50
```

### Debug: deploy fails

```bash
# Check deploy logs
npx pagegen deploy:logs --env production --lines 100

# Check whether the API key is valid
npx pagegen auth:verify

# Roll back to the previous deployment
npx pagegen rollback --env production
```

### Debug: dev server

```bash
# Start the dev server (needed for E2E tests)
npm run dev
# Server starts at http://localhost:3000

# Check whether the server is up
curl -s http://localhost:3000/health | jq .
```

<!-- Debug: add one subsection per common failure mode.
     Label each "Debug: <symptom>" so agents can jump to the right block.
     Prefer tailable logs, CLI status checks, and diagnostic queries
     over "open the dashboard." If the dashboard is the only option, say so. -->
