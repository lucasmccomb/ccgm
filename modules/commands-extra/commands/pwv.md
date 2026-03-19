# /pwv - Playwright Visual Verification

Launch a Playwright browser session to visually verify UI changes with screenshots and interaction testing.

## Workflow

### 1. Determine What to Verify
- Ask the user what URL/page to verify (or infer from recent changes)
- Identify specific elements, states, or flows to check
- Determine required auth state (logged in vs logged out)

### 2. Ensure Dev Server is Running
- Check if a dev server is already running on the expected port
- If not, start it in the background
- Wait for the server to be ready before proceeding

### 3. Navigate and Verify
- Open the target URL in Playwright
- Take a full-page screenshot as baseline
- Check for console errors and network failures
- Verify expected elements are present and visible

### 4. Debug Loop
If issues are found:
1. Take a targeted screenshot of the problem area
2. Check the browser console for errors
3. Inspect network requests for failed API calls
4. Report findings with evidence (screenshots + error messages)
5. If the fix is obvious, apply it and re-verify

### 5. Close Browser
- Close the Playwright browser session
- Stop the dev server if it was started for this verification

### 6. Report
- Present screenshots showing the verified state
- List any issues found and their status (fixed or needs attention)
- Confirm pass/fail for each verification point

## Key Rules

- **Always take screenshots** - visual evidence is the whole point of this command
- **Check multiple viewports** - desktop (1280x720) and mobile (375x667) at minimum
- **Check both themes** - if the project supports light/dark mode, verify both
- **Be specific about failures** - include the exact element, expected state, and actual state
- **Don't skip error checks** - always check console and network before declaring success

## Usage

```
/pwv                           # Verify current page / recent changes
/pwv https://localhost:5173    # Verify specific URL
/pwv /dashboard --mobile       # Verify specific route on mobile viewport
/pwv --dark                    # Verify dark mode specifically
```
