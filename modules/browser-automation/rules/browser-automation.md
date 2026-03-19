# Browser Automation

## MCP Plugins & Tool Permissions

### Installed Plugins Are Pre-Authorized

**All installed MCP plugins and tools are pre-authorized for use.** Do not ask permission to use tools that are already installed and available. This includes:

- Browser automation tools (Chrome, Playwright)
- Database MCP tools (Supabase, etc.)
- Any other plugin that appears in the available tools list

**Rationale**: If a plugin is installed, the user has already decided to grant access. Asking "Can I use X tool?" for every operation wastes time and creates friction.

---

## Browser Automation: Tool Selection

### WebMCP Tools (Preferred for Structured Interaction)

**Use WebMCP tools first** when interacting with websites that expose `navigator.modelContext` tools. The `webmcp-bridge` MCP server surfaces these as standard MCP tools. This replaces fragile screenshot-click-type workflows with structured function calls.

**How to check**: Use the Chrome extension's `javascript_tool` to query `navigator.modelContext.request({ tools: true })` on the current page. If tools are registered, prefer calling them over visual interaction.

**When adding WebMCP to web apps**: Register tools via the Imperative API (`navigator.modelContext.registerTool()`) for key user actions (search, create, export, etc.). Use the Declarative API (`toolname` attribute on forms) for standard form submissions.

### Chrome Extension (Visual + Authenticated)

**Use Chrome extension tools** when:
- The page requires authentication (OAuth, etc.)
- You need to test as the logged-in user
- The site has no WebMCP tools registered
- Visual verification is needed (layout, styling)

### Playwright (Headless + Unauthenticated)

**Use Playwright tools** when:
- Testing unauthenticated pages
- Taking automated screenshots for documentation
- Running headless browser operations
- The Chrome extension is unavailable or disconnected

---

## Verification & Debugging: CLI/API First, Browser Last

**Always prefer CLI tools, APIs, and MCP servers over browser automation.** Browser automation is slow, brittle, and should be a last resort for things that genuinely require visual verification.

### Verification Priority (Use This Order)

1. **CLI tools** - `curl`, `wrangler`, `gh`, `npx`, `supabase`, `npm`, etc. Fast, scriptable, reliable.
2. **MCP server tools** - Database MCP (`execute_sql`, `get_logs`), GitHub MCP, etc. Purpose-built and direct.
3. **API calls** - `gh api`, `curl` to REST/GraphQL endpoints, `wrangler d1 execute`, etc.
4. **WebMCP tools** - Structured interaction with live sites via `webmcp-bridge`. Use when a site exposes `navigator.modelContext` tools. Faster and more reliable than visual browser automation.
5. **Browser automation** - Chrome/Playwright. **Only when you need to verify something visual** that no API can confirm, or the site has no WebMCP tools.

### Common Scenarios

| Need to verify... | Use | NOT |
|---|---|---|
| API returns correct data | `curl` / `gh api` | Browser devtools |
| Database has expected records | Database MCP / `wrangler d1 execute` | Browser network tab |
| Deployment is live | `curl -I https://site.com` + check headers/response | Navigate in browser |
| GitHub PR/issue state | `gh pr view` / `gh issue view` | Open GitHub in browser |
| DNS/SSL configured | `dig` / `curl -vI` | Browser address bar |
| Cloudflare settings | `wrangler` CLI | Cloudflare dashboard in browser |
| Build output correct | `ls dist/` + read files | Serve and open in browser |
| Page renders correctly (visual) | **Browser automation** (this is the right use case) | N/A |
| Site interaction (forms, search) | **WebMCP tools** (if site exposes them via `navigator.modelContext`) | Screenshot-click-type workflow |
| Your own web apps | **WebMCP tools** (register tools in your apps) | Manual browser testing |

### When Browser Automation IS Appropriate

- Verifying visual layout, styling, responsive design
- Testing client-side interactivity (click flows, form behavior)
- Confirming OAuth/auth flows that require a real browser session
- Taking screenshots for documentation or bug reports
- Sites that don't expose WebMCP tools (most sites, for now)

---

## UI Verification (Browser Automation)

**IMPORTANT**: When working on UI features or bug fixes, verify the changes work in the actual browser after deployment. Don't rely solely on tests passing.

**Note**: This section covers **verification** (confirming fixes work). For **debugging** (diagnosing what's wrong), prefer MCP tools and CLI over browser automation.

### When to Use Browser Verification

Use Chrome automation tools to verify:
- **After deploying UI fixes** - Confirm the fix works in production
- **After implementing new UI features** - Test the actual user experience
- **Client-side debugging** - Only after MCP tools confirm server/database are working

### Verification Workflow

#### 0. Ask About Auth State (REQUIRED)

Before browser verification, **ask the user** about the required auth state:
- **Logged-in verification** - Proceed normally (user's session is active)
- **Logged-out verification** - Ask user to log out first, or open an incognito window manually

**Why this matters**:
- The Chrome plugin cannot open incognito windows - it only works in the normal browser
- Testing a logged-in feature while logged out will fail
- Testing a public feature while logged in may hide bugs visible to anonymous users

#### 1. Get Browser Context
```
tabs_context_mcp (createIfEmpty: true)
```

#### 2. Navigate to the Page
```
navigate (url, tabId)
```

#### 3. Wait for Load
```
computer (action: "wait", duration: 2-3)
```

#### 4. Check for Errors
```
# Check network requests for API errors
read_network_requests (tabId, urlPattern: "api")

# Check console for JavaScript errors
read_console_messages (tabId, pattern: "error|Error")
```

#### 5. Take Screenshot (if needed)
```
computer (action: "screenshot", tabId)
```

### Key Checks

| Check | Tool | What to Look For |
|-------|------|------------------|
| API Errors | `read_network_requests` | Status codes 4xx, 5xx |
| JS Errors | `read_console_messages` | Error stack traces |
| Page Content | `read_page` | Expected elements present |
| Visual State | `computer` (screenshot) | UI renders correctly |

---

## Deployment Verification (CRITICAL)

**NEVER claim changes are deployed or test them until deployment is actually complete.**

### Deployment Timing
- **After merge**: Changes are NOT immediately available
- **Platform deployments**: Typically take 1-3 minutes for static sites, 2-5 minutes for services
- **Do NOT test until deployment finishes**: Wait for deploy hooks to complete

### How to Verify Deployment Status
1. **Check the deployment dashboard** if accessible
2. **Monitor deployment logs** if available
3. **Test an API endpoint** to confirm new code is live (check for new behavior)
4. **When in doubt, wait longer** - testing against old code wastes debugging time

### After Each UI Fix
1. Merge the PR
2. **Wait for deployment to complete** (not just the merge)
3. Verify deployment succeeded by checking an indicator (timestamp, version, new behavior)
4. THEN use browser automation to verify the fix
5. Report success/failure to the user with evidence

**Common mistake**: Saying "changes deployed, testing now" when the merge just happened. The merge and deployment are separate events.

**Never assume a fix worked just because tests passed.** Production environments can have different data, missing migrations, or other issues that unit tests don't catch.
