---
description: Comprehensive brand naming research - word exploration, name generation, domain/trademark/app store/social checks
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, WebSearch, WebFetch, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
argument-hint: <concept description> [--tlds ai,io,com,life] [--output <path>]
---

# /brand - Brand Naming Research Pipeline

A comprehensive naming research system that explores word spaces, generates creative name candidates, and validates availability across domains, trademarks, app stores, and social media.

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Input & Setup

### 0.1 Parse Arguments

Extract from `$ARGUMENTS`:
- **Concept description**: What the product/brand is about. Can be a sentence, paragraph, or set of keywords.
- **`--tlds <list>`**: (Optional) Comma-separated TLDs to check. Default: `ai,io,com,life,work`
- **`--output <path>`**: (Optional) Where to write the final report. Default: current directory as `brand-research-{timestamp}.md`
- If no arguments provided, use AskUserQuestion to ask what the user wants to name.

### 0.2 Gather Preferences

Use AskUserQuestion to ask (skip if concept description is very detailed):

1. **Naming style preference** (can select multiple):
   - Modern/tech (lifebldr, Flickr style)
   - Philosophical/classical (prosoche, entelechia)
   - Abstract/invented (telara, kairara)
   - Descriptive compound (lifealign, dailycraft)
   - Single real word (flint, cadence, meridian)

2. **Any words or themes to include or avoid?**

3. **Primary TLD preference** (which TLD matters most for the final pick?)

### 0.3 Set Up Output

Create a working directory for intermediate results:
```bash
WORK_DIR="/tmp/brand-research-$(date +%s)"
mkdir -p "$WORK_DIR"
```

---

## Phase 1: Word Exploration (Parallel Agents)

Launch 4 parallel agents to explore the word space. Each agent writes results to `$WORK_DIR/`.

### Agent 1: Datamuse Semantic Explorer

Query the Datamuse API for each key concept word in the user's description. Use these endpoints (no auth needed):

```bash
# Synonyms
curl -s "https://api.datamuse.com/words?rel_syn=WORD&max=50"

# Meaning-related (semantic similarity via word2vec)
curl -s "https://api.datamuse.com/words?ml=WORD&max=50"

# Trigger words (statistically associated)
curl -s "https://api.datamuse.com/words?rel_trg=WORD&max=50"

# Sounds like (for creative spelling variants)
curl -s "https://api.datamuse.com/words?sl=WORD&max=20"

# Hypernyms ("kind of")
curl -s "https://api.datamuse.com/words?rel_spc=WORD&max=30"

# Hyponyms ("more specific than")
curl -s "https://api.datamuse.com/words?rel_gen=WORD&max=30"
```

Extract key concept words from the description first. For example, "life operating system for habits, goals, and principles" yields: life, habit, goal, principle, system, routine, discipline, foundation, build, guide, framework.

Write results to `$WORK_DIR/datamuse-results.json`.

### Agent 2: ConceptNet Relationship Explorer

Query ConceptNet for conceptual relationships (no auth needed):

```bash
# Related concepts
curl -s "https://api.conceptnet.io/related/c/en/WORD?limit=30"

# Edges (relationships)
curl -s "https://api.conceptnet.io/c/en/WORD?limit=30"
```

Focus on relationships: IsA, PartOf, HasProperty, RelatedTo, DerivedFrom, EtymologicallyRelatedTo.

Write results to `$WORK_DIR/conceptnet-results.json`.

### Agent 3: Big Huge Thesaurus Deep Synonyms

Query the Big Huge Thesaurus for pure synonym/antonym data (no auth needed for <10k/day):

```bash
curl -s "https://words.bighugelabs.com/api/2/YOUR_API_KEY/WORD/json"
```

Note: If no API key, fall back to Datamuse synonyms (already covered by Agent 1). The API key is free to obtain but optional. Without it, use this alternative for additional synonym coverage:

```bash
# Use the free dictionary API as a supplement
curl -s "https://api.dictionaryapi.dev/api/v2/entries/en/WORD"
```

Write results to `$WORK_DIR/thesaurus-results.json`.

### Agent 4: Philosophical & Etymological Explorer

This agent does NOT call APIs. It uses the LLM's knowledge to generate:

1. **Greek philosophical terms** related to the concept (Stoic, Aristotelian, Platonic, pre-Socratic)
2. **Latin roots** related to the concept
3. **Sanskrit/Pali/Buddhist terms** related to the concept
4. **Japanese concepts** (ikigai, kaizen, etc.) related to the concept
5. **Etymology chains** - trace key words back to their Proto-Indo-European or Latin/Greek roots
6. **Mythological references** - names from Greek, Norse, Hindu, Celtic mythology that embody the concept
7. **Literary/philosophical references** - names from notable works, thinkers, traditions

For each term, include: the word, pronunciation guide, origin language, meaning, and why it maps to the concept.

Write results to `$WORK_DIR/philosophical-results.md`.

---

## Phase 2: Name Generation

After all Phase 1 agents complete, read all result files and generate name candidates.

### 2.1 Compile Word Pool

Merge and deduplicate all words from Phase 1 into a master word pool. Categorize:
- **Core concept words** (from user description)
- **Synonyms & related** (from Datamuse/Thesaurus)
- **Conceptual associations** (from ConceptNet)
- **Philosophical/classical** (from Agent 4)

### 2.2 Generate Name Candidates

Using the word pool and user's style preferences, generate candidates in these categories:

**Category A: Single Real Words**
- Select the strongest single words from the pool that could stand alone as brand names
- Prioritize: short (<10 chars), uncommon but pronounceable, evocative

**Category B: Compound Words**
- Combine pairs from the word pool (e.g., lifethread, truepath, deepwork)
- Prefer: first word is concept anchor, second word is action/quality

**Category C: Vowel-Dropped / Abbreviated**
- Take strong compounds and drop vowels or abbreviate (lifebldr, lifecrft, lifshpr)
- Follow patterns: Flickr (-er to -r), Tumblr (-er to -r), Grindr

**Category D: Invented / Neo-Latin**
- Create novel words rooted in real etymological stems
- Pattern: [root] + [-ara, -is, -ia, -on, -os, -eia, -ium] (e.g., telara from telos, prokopia from prokope)
- Must be pronounceable and suggest meaning

**Category E: Philosophical / Classical**
- Select the best terms from Agent 4's output
- Include pronunciation guide for each
- Prioritize: pronounceable on first read > deeply meaningful but unpronounceable

**Category F: Word + TLD combos**
- Names that work as word.tld (e.g., build.life, deep.work)
- Short words that gain meaning from the TLD

Target: **150-250 total candidates** across all categories.

Write the full candidate list to `$WORK_DIR/candidates.txt` (one per line, no TLD).

---

## Phase 3: Domain Availability Check

### 3.1 Check via Instant Domain Search MCP

If the `instant-domain-search` MCP tools are available, use them:

1. **`search_domains`** - Pass candidate names to get bulk availability across TLDs
2. **`check_domain_availability`** - Verify top candidates definitively

### 3.2 Fallback: DNS + Whois

If MCP tools are unavailable, fall back to the DNS + whois approach:

```bash
# Quick DNS pre-filter (parallel)
dig +short "$NAME.$TLD" A 2>/dev/null

# Whois verification for no-DNS results
whois -h whois.verisign-grs.com "$NAME.com"     # .com
whois -h whois.nic.io "$NAME.io"                 # .io
whois -h whois.nic.ai "$NAME.ai"                 # .ai
whois -h whois.nic.work "$NAME.work"             # .work
# .life - DNS only (whois server unreliable)
```

Run checks in parallel batches of 20 to avoid rate limiting.

Write results to `$WORK_DIR/domain-results.tsv` with format: `name\ttld\tstatus`.

---

## Phase 4: Trademark Pre-Screen

### 4.1 USPTO Search

For the top 30 candidates (those with best domain availability), check for US trademark conflicts:

```bash
# iTunes-style search for similar marks
# Use the Marker API if available, otherwise fall back to web search
curl -s "https://markerapi.com/api/v2/trademarks/trademark/TERM/username/USERNAME/password/PASSWORD"
```

If no Marker API credentials, use WebSearch:
```
WebSearch: "CANDIDATE NAME" site:tsdr.uspto.gov OR site:tmsearch.uspto.gov
```

For each candidate, note:
- Exact match found? (dead or alive mark?)
- Similar marks in same Nice class (Class 9: software, Class 42: SaaS)?
- Risk level: clear / caution / conflict

Write results to `$WORK_DIR/trademark-results.md`.

---

## Phase 5: App Store & Social Check

### 5.1 Apple App Store

```bash
# Search iTunes for name collisions (free, no auth)
curl -s "https://itunes.apple.com/search?term=CANDIDATE&entity=software&limit=5"
```

Check if any results are an exact or very close name match.

### 5.2 Google Play

Use WebSearch as a fallback:
```
WebSearch: "CANDIDATE" site:play.google.com/store/apps
```

### 5.3 Social Handles

Check major platforms for handle availability. Use direct URL probing:

```bash
# GitHub
curl -s -o /dev/null -w "%{http_code}" "https://github.com/CANDIDATE"

# Twitter/X - use WebSearch (direct URL check unreliable)
# Instagram - use WebSearch
# Reddit
curl -s -o /dev/null -w "%{http_code}" "https://www.reddit.com/user/CANDIDATE"
```

Or if FindME CLI is installed:
```bash
findme CANDIDATE
```

Write results to `$WORK_DIR/social-results.md`.

---

## Phase 6: Scoring & Report

### 6.1 Score Each Candidate

Score each name (top 50 with best domain availability) on these criteria:

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Pronounceability | 20% | Can someone say it correctly on first read? |
| Memorability | 15% | Does it stick after hearing once? |
| Scope | 15% | Does the name encompass the full product vision? |
| Domain availability | 20% | How many target TLDs are available? Is .com available? |
| Trademark clearance | 10% | Any conflicts in relevant classes? |
| App store clearance | 5% | Any name collisions on iOS/Android? |
| Social handle availability | 5% | Are @name handles available on major platforms? |
| Story / meaning | 10% | Does "what does the name mean?" lead to a compelling answer? |

### 6.2 Generate Final Report

Write the report to the output path. Structure:

```markdown
# Brand Naming Research Report

**Concept**: {user's description}
**Date**: {YYYY-MM-DD}
**Candidates explored**: {count}
**Domains checked**: {count}

---

## Top 10 Recommendations

{Ranked table with scores, available TLDs, trademark status, pronunciation}

## Tier 2: Strong Alternatives (11-25)

{Same format}

## Full Results by Category

### Modern / Compound
{table}

### Philosophical / Classical
{table with pronunciation guides}

### Invented / Neo-Latin
{table with etymology}

### Single Word
{table}

## Domain Availability Matrix

{Name x TLD grid showing available/taken}

## Trademark Notes

{Any conflicts or cautions for top candidates}

## App Store Collisions

{Any near-matches found}

## Social Handle Availability

{Top 10 candidates across major platforms}

## Methodology

- Word exploration: Datamuse API, ConceptNet, Big Huge Thesaurus, LLM philosophical knowledge
- Domain checks: {Instant Domain Search MCP / DNS+whois fallback}
- Trademark: {USPTO search method used}
- App stores: iTunes Search API, Google Play web search
- Social: {method used}
- All checks performed {date}. Domain availability is ephemeral - verify before purchasing.
```

### 6.3 Present Results

Display the Top 10 to the user with a brief explanation of each name's strengths.

Use AskUserQuestion to ask:
1. Do any of these resonate?
2. Want to explore variations on any specific name?
3. Want to run `/brand-check` on a specific candidate for deeper verification?

---

## Notes

### API Rate Limits
- Datamuse: 100,000/day (no auth)
- ConceptNet: ~5-10 req/sec (no auth)
- Big Huge Thesaurus: 10,000/day (no auth for basic)
- iTunes Search: no published limit (be reasonable)
- Instant Domain Search MCP: no published limit

### Parallelization
- Phase 1 agents run in parallel (4 concurrent)
- Phase 3 domain checks run in parallel batches of 20
- Phase 4-5 can run in parallel with each other
