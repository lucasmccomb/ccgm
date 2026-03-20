# mcp-development

Guide for building Model Context Protocol (MCP) servers.

## What It Does

Installs a rules file covering MCP server development:

- **Project setup** - Language choice (TypeScript recommended), transport selection (stdio vs HTTP)
- **Tool design** - Naming conventions, input schemas with Zod/Pydantic, output design, error messages
- **Tool annotations** - readOnlyHint, destructiveHint, idempotentHint, openWorldHint
- **Implementation patterns** - Shared utilities, authentication, rate limiting
- **Testing** - MCP Inspector usage, build verification, input validation
- **Quality checklist** - Pre-ship verification steps

## Manual Installation

```bash
# Global (all projects)
cp rules/mcp-development.md ~/.claude/rules/mcp-development.md

# Project-level
cp rules/mcp-development.md .claude/rules/mcp-development.md
```

## Files

| File | Description |
|------|-------------|
| `rules/mcp-development.md` | MCP server development guide with tool design patterns and quality checklist |
