# CR-01 transport decision

Decision date: September 6, 2026. Baseline: default branch `6255bc1ad8cab245362372d998142051a4fbda18`. Implementation issue: #1041; pilot workflow wiring: #1042.

## Reuse evaluation

The official [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) was inspected at upstream commit `db52e28f4d9ded852ab3942cea316258ae4ef346`. Its supported review tool accepts Git review scope/base/model/cwd and owns a fixed findings schema (`scripts/codex-companion.mjs`, review schema and tool definition). It does not accept an arbitrary frozen plan/spec bundle, caller result schema, or the required per-invocation MCP/tool restrictions through that interface. Its broader delegation interface does not supply those restrictions either.

Choose native `codex exec` for Claude-to-Codex and native `claude --print` for Codex-to-Claude. Both are actual reasoning-agent invocations with their own login. Do not register a duplicate plugin/MCP route or reimplement background service management. `claude mcp serve` exposes tools, so it cannot replace the reverse reasoning-agent call. The runtime is synchronous with one local file lock and saved counters; no daemon or token-reservation service is introduced.

## Capability fit

Codex CLI 0.153.4 accepts `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--strict-config`, `--sandbox read-only`, `--json`, `--output-schema`, and an isolated `--cd`. Explicit config disables web search, MCP, execution, hooks, plugins/apps, browser/computer/image tools, memory, and nested agents. `agents.enabled=false` is necessary in addition to disabling multi-agent feature flags: the installed source otherwise allows a model-selected multi-agent mode. Keep code-mode hosting enabled when the selected model requires it; pure computation utilities are compatible with this evidence-only profile.

Codex's patch handler can remain exposed independently of shell tools. The actual native write probe attempted a patch under the read-only profile; the router denied it and the target sentinel remained absent. A corrected native probe with `agents.enabled=false` completed with no child-agent launch and a valid native terminal event. These checks establish distinct controls: tool removal prevents execution/remote dispatch, while the sandbox denies patch writes.

Claude's supported profile is `--safe-mode --restricted --print --tools '' --strict-mcp-config --mcp-config '{"mcpServers":{}}' --permission-mode dontAsk --no-chrome --no-session-persistence --output-format json --json-schema ...`. The authenticated readiness event exposed only structured output, no MCP servers, and primary model `claude-sonnet-5`. The native JSON response can be an event array ending in a result, or a result object; model attribution must not pick the first auxiliary model-usage key.

The coordinator's child environment retains native login locations but excludes ambient provider API keys/base URLs/tokens and parent session/permission overrides. It neither reads nor copies subscription credentials. Unsupported flags, unavailable login, missing native session identity, invalid schema output, and any permission failure keep the review incomplete. No weaker profile or same-provider fallback is attempted.

## Evidence and release boundary

Every input is explicitly listed and frozen by content hash. Reviewers cannot fetch further evidence themselves; they request precise missing source or test results. This deliberately limits the first delivery to bounded review units while avoiding general-purpose command or remote-tool access. A model's self-reported restriction is supporting evidence only; actual write denial and inspected effective tool configuration are the mechanical checks.

Deterministic contract tests are committed and run in both required `module-tests` jobs. Small real-provider runs, exact command/version records, hashes, timing, native session metadata, and failed attempts remain in private local audit records because they contain machine/session information. A failed smoke is retained as failure and cannot substitute for release evidence. Final authenticated integration checks are recorded against the reviewed implementation before installation and merge; no static document alone marks that gate passed.

## Authenticated integration evidence

The CR-01 execution used Claude Code 2.1.263 and Codex CLI 0.153.4. A Codex-origin fixture received an attributable Claude review that found a seeded multiplication defect against the specification; the native primary model was `claude-sonnet-5`. In the reverse case, an actual Claude host authored a small plan, invoked the restricted coordinator, and personally received the Codex `CLEAN` result and matching frozen hash back in the same initiating session. That Codex reviewer used the explicit `gpt-6-astra` launch argument. Native session IDs and fixture hashes are retained in private execution evidence.

The first reverse integration attempt exposed a strict output-schema incompatibility: Codex rejected enum/const properties without explicit types before inference. The adapter now emits explicit types at every schema node, validates results locally, and preserves bounded redacted stderr/stdout error diagnostics. The failed cases remain recorded; the successful reverse smoke used the corrected schema and unchanged capability restrictions. Deterministic tests include this regression, both envelope forms, counter/deadline persistence, and copied-install CLI/setup execution.
