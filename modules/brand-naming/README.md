# Brand Naming Research Module

Comprehensive brand naming research tools that automate the entire naming pipeline - from word exploration through domain, trademark, app store, and social media verification.

## Commands

### `/brand <concept description>`

Full naming research pipeline. Takes a concept description and produces a scored report with 150-250 name candidates.

**Pipeline stages:**
1. **Word Exploration** (4 parallel agents) - Datamuse API (synonyms, semantics, sounds-like), ConceptNet (conceptual relationships), Big Huge Thesaurus (synonym/antonym), LLM philosophical/etymological knowledge
2. **Name Generation** - 6 categories: single words, compounds, vowel-dropped, invented/neo-Latin, philosophical/classical, word+TLD combos
3. **Domain Availability** - Checks all candidates via Instant Domain Search MCP (or DNS/whois fallback)
4. **Trademark Pre-Screen** - USPTO/Marker API search for conflicts
5. **App Store Check** - iTunes Search API + Google Play web search
6. **Social Handle Check** - GitHub, Twitter/X, Instagram, Reddit, YouTube, TikTok, LinkedIn, Product Hunt
7. **Scoring & Report** - Weighted scoring on pronounceability, memorability, scope, domain availability, trademark clearance, social handles, story/meaning

**Example:**
```
/brand "AI-powered life framework for habits, goals, and principles"
/brand "developer tool for API testing" --tlds ai,io,dev,com
```

### `/brand-check <name> [, name2, name3]`

Deep verification of one or more specific brand name candidates. Checks everything in detail for a single name.

**Checks:**
- Domains across 12 TLDs (.ai, .io, .com, .life, .work, .app, .co, .dev, .org, .net, .me, .us) with pricing estimates
- USPTO and WIPO trademark search
- Apple App Store and Google Play name collisions
- Social media handles on 8 platforms
- Existing business/company web presence

**Example:**
```
/brand-check lifebldr
/brand-check lifebldr, lifetenet, prosoche
```

## MCP Server (Optional)

The installer can add the **Instant Domain Search** MCP server to your `mcp.json`:

```json
{
  "mcpServers": {
    "instant-domain-search": {
      "url": "https://instantdomainsearch.com/mcp/sse"
    }
  }
}
```

- Free, no authentication required
- Checks 800+ TLDs in under 25ms
- Tools: `search_domains`, `check_domain_availability`, `generate_domain_variations`
- Without this MCP, commands fall back to DNS + whois (slower but functional)

## Free APIs Used

All APIs used by these commands are free with no authentication required:

| API | Rate Limit | Used For |
|-----|-----------|----------|
| [Datamuse](https://www.datamuse.com/api/) | 100,000/day | Synonyms, semantic similarity, sounds-like, hypernyms |
| [ConceptNet](https://conceptnet.io/) | ~5-10 req/sec | Conceptual relationships, semantic graph |
| [Big Huge Thesaurus](https://words.bighugelabs.com/site/api) | 10,000/day | Synonym/antonym pairs |
| [iTunes Search](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/) | No published limit | Apple App Store name collision check |
| [Instant Domain Search](https://instantdomainsearch.com/mcp) | No published limit | Domain availability (via MCP) |

## Manual Installation

Copy the command files to your Claude Code commands directory:

```bash
cp commands/brand.md ~/.claude/commands/brand.md
cp commands/brand-check.md ~/.claude/commands/brand-check.md
```

Optionally add the MCP server to `~/.claude/mcp.json`:

```bash
# Add instant-domain-search to your mcp.json mcpServers object:
# "instant-domain-search": { "url": "https://instantdomainsearch.com/mcp/sse" }
```
