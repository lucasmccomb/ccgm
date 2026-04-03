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

## Phase 1: Domain Availability (All TLDs)

Check the name across ALL specified TLDs.

### 1.1 Instant Domain Search MCP (Preferred)

If `instant-domain-search` MCP tools are available:

1. Use `search_domains` with the name to get availability across all TLDs
2. Use `check_domain_availability` for definitive verification on available ones
3. Also use `generate_domain_variations` to surface creative alternatives

### 1.2 Fallback: DNS + Whois

If MCP is unavailable:

```bash
# Check these TLDs
TLDS=(ai io com life work app co dev org net me us xyz)

for tld in "${TLDS[@]}"; do
    # DNS pre-check
    result=$(dig +short "$NAME.$tld" A 2>/dev/null)
    ns=$(dig +short "$NAME.$tld" NS 2>/dev/null)
    if [ -z "$result" ] && [ -z "$ns" ]; then
        echo "MAYBE_AVAIL|$NAME.$tld"
    else
        echo "TAKEN|$NAME.$tld"
    fi
done
```

For "MAYBE_AVAIL" results, verify with whois:

```bash
# .com
whois -h whois.verisign-grs.com "$NAME.com" 2>/dev/null | grep -q "No match" && echo "AVAIL" || echo "TAKEN"

# .io
whois -h whois.nic.io "$NAME.io" 2>/dev/null | grep -qi "NOT FOUND" && echo "AVAIL" || echo "TAKEN"

# .ai
whois -h whois.nic.ai "$NAME.ai" 2>/dev/null | grep -qi "not registered" && echo "AVAIL" || echo "TAKEN"

# .work
whois -h whois.nic.work "$NAME.work" 2>/dev/null | grep -qi "DOMAIN NOT FOUND" && echo "AVAIL" || echo "TAKEN"
```

### 1.3 Check Pricing

For available domains, note approximate pricing:
- `.com`: ~$10/yr
- `.io`: ~$30-50/yr
- `.ai`: ~$70-90/yr (Anguilla, premium)
- `.life`: ~$5-15/yr
- `.work`: ~$5-10/yr
- `.app`: ~$15-20/yr
- `.dev`: ~$12-15/yr
- `.co`: ~$25-35/yr

Also check if any available domains are "premium" priced by the registry (common for short/dictionary words).

---

## Phase 2: Trademark Search

### 2.1 USPTO (United States)

Search for the name in the US trademark database:

```bash
# WebSearch for USPTO TESS results
WebSearch: "NAME" trademark USPTO
```

Also search the Marker API if credentials are available:
```bash
curl -s "https://markerapi.com/api/v2/trademarks/trademark/NAME/username/USER/password/PASS"
```

Report:
- **Exact matches**: Any live or dead trademarks with this exact name?
- **Similar marks**: Any confusingly similar marks?
- **Relevant classes**: Focus on Nice Class 9 (software), Class 42 (SaaS/cloud), Class 41 (education)
- **Risk assessment**: Clear / Low Risk / Caution / High Risk

### 2.2 International (WIPO)

```bash
WebSearch: "NAME" site:branddb.wipo.int OR "NAME" WIPO trademark
```

Note any international registrations in key markets (US, EU, UK, AU, CA).

---

## Phase 3: App Store Check

### 3.1 Apple App Store

```bash
# Search for exact and close matches
curl -s "https://itunes.apple.com/search?term=NAME&entity=software&limit=10" | \
  python3 -c "import sys,json; data=json.load(sys.stdin); [print(f'{r[\"trackName\"]} by {r[\"artistName\"]}') for r in data.get('results',[])]"
```

Report:
- Exact name match? (deal-breaker)
- Close matches? (confusing but not blocking)
- Name available for use? (likely yes / caution / likely no)

### 3.2 Google Play Store

```bash
WebSearch: "NAME" site:play.google.com/store/apps
```

Same analysis as App Store.

---

## Phase 4: Social Media Handle Check

Check handle availability on major platforms:

### Direct URL Probing

```bash
# GitHub (404 = available)
curl -s -o /dev/null -w "%{http_code}" "https://github.com/NAME"

# Twitter/X (unreliable via URL, use web search)
WebSearch: "twitter.com/NAME" OR "x.com/NAME"

# Reddit (404 = available for subreddit)
curl -s -o /dev/null -w "%{http_code}" "https://www.reddit.com/r/NAME"
curl -s -o /dev/null -w "%{http_code}" "https://www.reddit.com/user/NAME"

# YouTube
curl -s -o /dev/null -w "%{http_code}" "https://www.youtube.com/@NAME"

# TikTok
curl -s -o /dev/null -w "%{http_code}" "https://www.tiktok.com/@NAME"

# Instagram (use web search, direct URL unreliable)
WebSearch: "instagram.com/NAME"

# LinkedIn (company page)
WebSearch: "linkedin.com/company/NAME"

# Product Hunt
curl -s -o /dev/null -w "%{http_code}" "https://www.producthunt.com/products/NAME"
```

Interpret HTTP codes:
- 404 = likely available
- 200 = taken
- 301/302 = taken (redirect to profile)
- 429 = rate limited (note as "unknown")

### Agent Reach: Direct Twitter Search

```bash
bird search "NAME" -n 5
bird search "from:NAME OR @NAME" -n 5
# Fallback if bird CLI unavailable:
# mcporter call 'exa.web_search_exa(query: "site:twitter.com NAME", numResults: 3)'
```

Check for active accounts, brands, or influencers using the name.

### Agent Reach: Direct Reddit Search

```bash
curl -s "https://www.reddit.com/search.json?q=NAME&limit=5" -H "User-Agent: agent-reach/1.0" | jq '.data.children[].data | {title, selftext: .selftext[:300], subreddit, score}'
```

Look for subreddits, communities, or products with the name.

### Agent Reach: Direct YouTube Search

```bash
~/.agent-reach-venv/bin/yt-dlp --dump-json "ytsearch3:NAME" 2>/dev/null | jq '[.[] | {title, channel, view_count, webpage_url}]'
```

Check for channels or prominent content using the name.

### Agent Reach: Direct GitHub Search

```bash
gh search repos "NAME" --limit 5
```

Check for repos, orgs, or notable projects using the name (supplements the URL probe above).

---

## Phase 5: Existing Business Check

### 5.1 Web Presence

```bash
WebSearch: "NAME" company OR startup OR app -site:github.com
```

Is there an existing company, product, or notable entity using this name?

### Agent Reach: Deep Web Presence Check

```bash
mcporter call 'exa.web_search_exa(query: "NAME company startup app product", numResults: 5)'
```

Exa provides semantic search results that surface companies, products, and startups that may not rank highly in traditional search. Compare with WebSearch results above for completeness.

### 5.2 Business Registration (if Cobalt Intelligence credentials available)

Check US business entity registration. Otherwise, note as "not checked - verify manually at your state's Secretary of State website."

---

## Phase 6: Report

Present results as a clean summary:

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
  Apple:   {clear/collision} - {details}
  Google:  {clear/collision} - {details}

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

If the user provided comma-separated names, run all checks for each and present a comparison table at the end:

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
