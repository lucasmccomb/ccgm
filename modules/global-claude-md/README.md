# Global CLAUDE.md Module

Installs a slim `~/.claude/CLAUDE.md` that serves as the root configuration reference for Claude Code.

## What it does

The global CLAUDE.md is loaded in every Claude Code session before any other configuration. This module installs a minimal version that describes the configuration structure and points to the actual rule files, commands, hooks, and settings where behavior is defined.

## Why it's slim

All behavioral rules live in their own files under `~/.claude/rules/`. Duplicating rules in CLAUDE.md wastes context tokens (the same instructions load twice) and creates maintenance drift. This module ensures CLAUDE.md is a clean reference, not a monolithic config file.

## Manual installation

```bash
cp CLAUDE.md ~/.claude/CLAUDE.md
```
