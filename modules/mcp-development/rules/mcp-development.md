# MCP Server Development

Guidelines for building Model Context Protocol (MCP) servers that enable LLMs to interact with external services.

## Project Setup

### Language Choice

- **TypeScript** (recommended): Better SDK quality, type safety, and LLM compatibility. Use `@modelcontextprotocol/sdk`.
- **Python**: Use `fastmcp` for rapid development.

### Transport

- **stdio**: For local servers (CLI tools, desktop integrations)
- **Streamable HTTP**: For remote/shared servers

## Tool Design

### Naming

- Use clear, descriptive names with consistent prefixes per service
- Pattern: `{service}_{action}_{resource}` (e.g., `github_create_issue`, `slack_send_message`)
- Avoid ambiguous names - the LLM reads these to decide which tool to call

### Input Schemas

- Define strict schemas with Zod (TypeScript) or Pydantic (Python)
- Include constraints (min/max, enums, patterns) in the schema itself
- Add descriptions to every field - these become the tool's documentation for the LLM
- Include examples in field descriptions for complex types

### Output Design

- Return focused, relevant data (not raw API dumps)
- Support filtering and pagination for list operations
- Use structured output schemas when the consumer needs to parse results programmatically

### Error Messages

- Make errors actionable: tell the LLM what went wrong AND what to try next
- Include the specific constraint that was violated
- Suggest alternative tool calls when appropriate
- Never return raw stack traces or internal error details

## Tool Annotations

Annotate every tool to help clients make safety decisions:

```typescript
{
  readOnlyHint: true,      // Does not modify external state
  destructiveHint: false,  // Does not delete or overwrite
  idempotentHint: true,    // Safe to retry
  openWorldHint: false     // Interacts with external services
}
```

## Implementation Patterns

### Shared Utilities

Create reusable modules for:
- API client with auth, rate limiting, and retry logic
- Error formatting (consistent structure across all tools)
- Response formatting (pagination, truncation, summarization)
- Input validation helpers

### Authentication

- Support environment variables for API keys/tokens
- Document required credentials clearly in the README
- Never log or expose credentials in error messages

### Rate Limiting

- Implement client-side rate limiting to stay within API quotas
- Return clear errors when rate limited (include retry-after timing if available)

## Testing

### MCP Inspector

Use `npx @modelcontextprotocol/inspector` to:
- Verify tool schemas are correctly defined
- Test tool execution with sample inputs
- Confirm error handling works as expected

### Build Verification

- Run the build (`npm run build` / type checking) before testing
- Test every tool with both valid and invalid inputs
- Verify error messages are helpful and actionable

## Quality Checklist

Before shipping an MCP server:

- [ ] Every tool has a clear description and annotated inputs
- [ ] Error messages guide the LLM toward resolution
- [ ] Authentication is via environment variables (not hardcoded)
- [ ] Rate limiting prevents API quota exhaustion
- [ ] Tool annotations (readOnly, destructive, idempotent) are set correctly
- [ ] README documents all tools, required credentials, and setup steps
- [ ] Inspector testing confirms all tools work
