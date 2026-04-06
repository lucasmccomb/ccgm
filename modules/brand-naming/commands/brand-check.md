---
description: Deep verification of a single brand name - domains, trademarks, app stores, social handles
allowed-tools: Agent
argument-hint: <name> [--tlds ai,io,com,life,work]
---

# /brand-check - Single Name Deep Verification

Use the Agent tool to execute this workflow on a cheaper model:

- **model**: sonnet
- **description**: brand name verification

Pass the agent all workflow instructions below. Include the received arguments: `$ARGUMENTS`

After the agent completes, relay its report to the user exactly as received.

---

Run comprehensive availability checks on a single brand name candidate across domains, trademarks, app stores, and social media platforms.

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Input

Extract from `$ARGUMENTS`:
- **Name**: The brand name to check (required). Can include multiple names separated by commas.
- **`--tlds <list>`**: (Optional) Comma-separated TLDs to check. Default: `ai,io,com,life,work,app,co,dev,org,net`

If no name provided, use AskUserQuestion to ask.

---

## Phase 1: Gather Bash-Based Data

Run the gather script to check domains, social media, app store, and GitHub/Reddit in parallel:

```bash
bash ~/.claude/lib/brand-check-gather.sh "{name}" "{tlds}"
```

For multiple names, run the script once per name. If checking 2+ names, run the bash calls in parallel tool calls.

The script outputs structured `=== SECTION ===` blocks: DOMAINS, SOCIAL, APPSTORE, GH_REPOS, REDDIT.

Interpret HTTP codes from SOCIAL section:
- 404 = likely available
- 200 = taken
- 301/302 = taken (redirect)
- 429 = rate limited (report as "unknown")

---

## Phase 2: Web Search Checks (parallel tool calls)

Run ALL of the following WebSearch/WebFetch calls **in parallel tool calls** (batch them into a single response, do not run sequentially):

1. **USPTO trademark**: `WebSearch: "{name}" trademark USPTO`
2. **WIPO trademark**: `WebSearch: "{name}" site:branddb.wipo.int OR "{name}" WIPO trademark`
3. **Google Play**: `WebSearch: "{name}" site:play.google.com/store/apps`
4. **Twitter/X**: `WebSearch: "{name}" site:twitter.com OR site:x.com`
5. **Instagram**: `WebSearch: "instagram.com/{name}"`
6. **LinkedIn**: `WebSearch: "linkedin.com/company/{name}"`
7. **Existing business**: `WebSearch: "{name}" company OR startup OR app -site:github.com`

If Instant Domain Search MCP tools are available, also call `search_domains` and `generate_domain_variations` in the same parallel batch.

If `mcporter` / Exa is available, add: `bash: mcporter call 'exa.web_search_exa(query: "{name} company startup app product", numResults: 5)'`

---

## Phase 3: Domain Pricing Reference

For available domains from Phase 1, note approximate pricing:
- `.com`: ~$10/yr, `.io`: ~$30-50/yr, `.ai`: ~$70-90/yr, `.life`: ~$5-15/yr
- `.work`: ~$5-10/yr, `.app`: ~$15-20/yr, `.dev`: ~$12-15/yr, `.co`: ~$25-35/yr

---

## Phase 4: Analyze and Report

Synthesize all data into this report format:

```
--------------------------------------------
  BRAND CHECK: {NAME}
  {date}
--------------------------------------------

DOMAINS
  .ai      {available/taken}  {~$XX/yr}
  .com     {available/taken}  {~$XX/yr}
  .io      {available/taken}  {~$XX/yr}
  .life    {available/taken}  {~$XX/yr}
  .work    {available/taken}  {~$XX/yr}
  .app     {available/taken}  {~$XX/yr}
  .co      {available/taken}  {~$XX/yr}
  .dev     {available/taken}  {~$XX/yr}

TRADEMARKS
  USPTO:   {clear/caution/conflict} - {details}
  WIPO:    {clear/caution/conflict} - {details}

APP STORES
  Apple:   {clear/collision} - {details from gather + any WebSearch context}
  Google:  {clear/collision} - {details from WebSearch}

SOCIAL HANDLES
  GitHub:      {available/taken}
  Twitter/X:   {available/taken/unknown}
  Instagram:   {available/taken/unknown}
  Reddit:      {available/taken}
  YouTube:     {available/taken}
  TikTok:      {available/taken}
  LinkedIn:    {available/taken/unknown}
  ProductHunt: {available/taken}

EXISTING BUSINESSES
  {any notable entities using this name}

OVERALL ASSESSMENT
  {1-2 sentence summary: strong candidate / proceed with caution / significant conflicts}
```

### If Multiple Names

Run all checks for each name and present a comparison table at the end:

```
COMPARISON: {name1} vs {name2} vs {name3}

                    {name1}     {name2}     {name3}
Domains (of N TLDs) {X avail}   {X avail}   {X avail}
.com available?     {yes/no}    {yes/no}    {yes/no}
.ai available?      {yes/no}    {yes/no}    {yes/no}
Trademark clear?    {yes/no}    {yes/no}    {yes/no}
App Store clear?    {yes/no}    {yes/no}    {yes/no}
Social handles      {X/8}       {X/8}       {X/8}

Recommendation: {name}
```
