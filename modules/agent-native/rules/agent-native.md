# Agent-Native Architecture

Principles for building applications where an LLM agent is a first-class user, not an afterthought. Use these when designing product surfaces (APIs, tools, data models, workflows) that an agent must drive on behalf of a human.

An application is "agent-native" when an agent can accomplish anything a user can, using structured tools the application exposes, and when the agent can compose those tools to produce behavior the original designers did not explicitly build.

## The Four Principles

### 1. Parity

**Whatever the user can do in the UI, the agent can do via a tool.**

Every user-visible action maps to a callable tool with the same semantics, same permissions, and same resulting state. No "UI-only" flows, no "this one is a button that pops a modal you can only dismiss with a click." If the flow exists in the product, the agent has a tool for it.

Parity is measurable. Count the distinct user actions exposed in the UI. Count the tools an agent can invoke. The ratio tells you whether the agent is a first-class user or a second-class one. A parity of `agent can do X of Y user actions` is a concrete audit output.

Violations to watch for:
- Buttons whose handlers cannot be reached from any tool
- Drag-and-drop or gesture interactions with no programmatic equivalent
- Hidden side effects that fire only on UI events (analytics, optimistic updates, toasts) and that the agent has no way to trigger or observe

### 2. Granularity

**Prefer atomic primitives. Features are outcomes the agent achieves by composing primitives in a loop.**

A product that ships one tool per high-level feature ("create_deck", "publish_deck", "share_deck") is agent-hostile: every new feature request needs a new tool. A product that ships atomic primitives ("add_slide", "update_slide_content", "reorder_slides", "set_visibility") lets the agent compose new features by chaining primitives - no product change required.

The granularity test: could an agent build a feature you did not design by combining existing tools? If no, your tools are too coarse. If the agent must rebuild the same 4-step sequence over and over, you are missing a higher-level primitive. The goal is a balanced vocabulary where most novel workflows are expressible but the common case is concise.

Atomic does not mean trivial. A primitive is atomic when it does one thing the caller can reason about in isolation, returns a stable result, and does not bake in a specific higher-level workflow.

### 3. Composability

**New features become new prompts, not new code.**

When the agent has parity and granularity, a "feature" can often ship as a system prompt that guides the agent through an orchestration of existing primitives. The build queue for product work shrinks; the build queue for tools and primitives grows. You invest once in a durable surface, not repeatedly in one-off flows.

Composability is a culture shift as much as an architecture one. Before writing new feature code, ask: "Can this be a prompt over existing tools?" If yes, ship it as a prompt. Reserve code for new primitives the prompt cannot express.

This is the principle most often violated retroactively. Teams add tools, then when product asks for a complex feature, they add a specialized tool that duplicates logic instead of composing the atomic ones. Audit for duplication between tools - it signals a missed composition.

### 4. Emergent Capability

**The agent accomplishes things you did not design for.**

Parity + granularity + composability together produce a surface where the agent, handed a novel prompt, completes tasks the product team never imagined. A user asks "make the deck feel more playful and move the agenda to after the intro"; the agent reorders slides, rewrites copy, and adjusts theme tokens - all with the same primitives that exist for simpler flows.

Emergent capability is the payoff. You cannot ship it directly; you earn it by doing the first three principles well. When you see the agent solving tasks outside the product's explicit feature set, the architecture is working.

Measure it by tracking prompts that the agent satisfies without adding a new tool. High count = high emergence. Low count = the surface is not yet rich enough.

## Operating Guidance

### Design-time

- Start from tools, not UI. When adding a new capability, write the tool signature first. The UI is a specific client of the tool.
- Expose structured data, not presentation. The agent cannot parse `<div class="price">$12.99</div>`; it can use a `price: { amount: 12.99, currency: "USD" }` field.
- Prefer idempotent operations. `set_slide_title(id, "X")` is safer and more composable than `append_to_title(id, "X")`. The agent can retry without reasoning about prior state.
- Return rich results. A tool that returns `{ ok: true }` is less useful than one that returns the updated resource. The agent can chain without re-fetching.

### Runtime

- Errors are instructions. A tool that fails with `404 not found` is less useful than one that fails with `no slide with id "s12" - existing slide ids: [s1, s2, ... s8]`. The error should tell the agent what to try next.
- Log tool calls as product telemetry. The sequence of tools an agent invokes on a prompt is the product's new analytics surface.
- Gate destructive actions on confirmation tokens the agent can request, not on UI-only confirmations. The confirmation should be a parameter in a tool call, not a modal.

### Audit

- Count user actions. Count tools. Compute parity.
- Read a sample of tools for overlap. Overlap signals missed composition.
- Read tool responses for presentation leaks. Presentation in responses blocks composition.
- Look for recent features and ask whether each one shipped as new code or as a new prompt over existing tools. The trend line is the composability metric.

## Anti-Patterns

- **The Screen-Scraping Tool.** A "tool" that takes a URL and returns rendered HTML is not agent-native; it is a browser in disguise. Real tools expose structured state, not pixels.
- **The God Tool.** One tool with fifteen optional parameters that does "anything about a deck" is not atomic. Split it.
- **The UI-Only Confirmation.** "Are you sure?" modals that gate a destructive action and cannot be satisfied programmatically. Turn them into a `confirm: true` parameter or a two-step `prepare + commit` pair.
- **The Batched Workflow Tool.** A "publish_and_share_and_notify" tool that bundles three primitives. The agent cannot reuse any one of them; the bundle is an opinion frozen into the surface.
- **The Non-idempotent Mutator.** `increment_version()` instead of `set_version(n)`. The agent cannot safely retry.

## When to Apply These Principles

- Designing new product surfaces intended to be driven by an agent.
- Auditing an existing product whose team wants to add an "AI assistant" - the first question is whether the product is agent-native, not whether the assistant is well-prompted.
- Reviewing a pull request that adds a new feature to an agent-first application - use the principles as the review rubric.

## When NOT to Apply

- Internal admin tools with no agent consumers and no plan for one.
- Prototypes being thrown away.
- Surfaces where the security model explicitly excludes programmatic access.

In all three cases, the principles may still produce cleaner design, but the audit is not worth the cost.
