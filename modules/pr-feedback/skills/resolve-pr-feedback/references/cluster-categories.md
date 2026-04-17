# Cluster Categories

Eleven fixed concern categories used by `/resolve-pr-feedback` to classify review threads before grouping. Keep the set small and stable so a cluster over three runs is still a cluster; do not add ad-hoc categories.

Each category has a short definition and sample phrases. When a thread plausibly fits more than one, pick the most specific. When it fits none, use `other` and flag the thread for manual review - do not invent a new category in-flight.

| Category | Definition | Sample phrases a reviewer would use |
|---|---|---|
| `error-handling` | Missing, swallowed, or over-broad error handling. Includes unhandled promise rejections, bare `except`, silent fallbacks, and missing logging on failure paths. | "this can throw and we lose it", "catching Exception is too broad", "no retry", "silently returning null" |
| `validation` | Missing or incorrect input validation at an API/function/form boundary. Includes type checks, range checks, enum guards, and sanitization gaps that are not security-critical. | "what if this is empty", "should reject negative N", "no length limit", "enum not narrowed" |
| `type-safety` | TypeScript or equivalent static-type issues. Includes `any`, unsafe casts, missing generics, nullable-not-narrowed, and assertion-as-truth. | "remove the any", "cast is unsound", "this can be undefined here", "missing discriminated union" |
| `testing` | Missing tests, weak coverage, wrong test style, or tests that pass for the wrong reason. Includes "add a test for X", "mock is testing the mock", "no failing case." | "no test for this path", "test should fail first", "flaky", "missing edge case" |
| `naming` | Identifier quality - variable, function, file, or type names that obscure meaning. | "rename to", "this name is misleading", "shadows outer", "too generic" |
| `style-consistency` | Repo/house-style divergence where a convention exists and this code diverges. Includes formatter output, import order, file layout, comment style. | "we use X here", "matches codebase pattern?", "reorder imports", "house style" |
| `architecture` | Layering, coupling, module boundaries, and pattern-fit concerns that go beyond one symbol. Includes "wrong layer", "leak across boundary", "duplicate responsibility." | "belongs in service", "why is this in the controller", "couples these modules", "duplicates the resolver" |
| `performance` | Algorithmic complexity, N+1 queries, avoidable re-renders, synchronous blocking on hot paths, oversized payloads. | "O(n^2) on the whole list", "unnecessary render", "blocks the event loop", "missing index" |
| `security` | Authentication, authorization, input sanitization for untrusted data, secret handling, RLS gaps. Escalate immediately; never auto-apply fixes without explicit confirm. | "unsanitized", "RLS missing", "injection", "authorization check" |
| `documentation` | Missing, stale, or incorrect comments, docstrings, READMEs, or inline rationale on non-obvious decisions. | "why does this", "document the contract", "doc says X but code does Y", "add example" |
| `other` | Legitimately does not fit any of the above. Use sparingly. A thread tagged `other` is always surfaced for manual review; the orchestrator does not auto-fix `other` clusters. | (catch-all) |

## Spatial Proximity

After category classification, the orchestrator groups threads by:

1. **Exact-file match** - two or more threads in the same category on the same `path`.
2. **Subtree match** - two or more in the same category under a shared directory prefix that is not the repo root (e.g., `src/auth/` but not `src/`).
3. **Cross-cutting** - same category across three or more disparate files. This signals a systemic issue and becomes a single finding, not N one-off fixes.

A cluster is the intersection of a category and a proximity bucket. Emit one fix plan per cluster.

## Cluster Gate

The cluster analysis phase only activates when:

- **3 or more new unresolved threads** exist after triage, OR
- A **cross-invocation signal** is present (e.g., `cluster:force` token in arguments, or a prior run's artifact in `.claude/pr-feedback/` indicates unfinished clusters).

For 1-2 new threads, skip clustering and dispatch individual resolvers. Overhead of category + proximity analysis is not justified at that volume.

## Confidence and Autofix Routing

For each cluster, the orchestrator tags an `autofix_class`:

- `safe_auto` - unambiguous fix, mechanical, well-covered by tests. Examples: rename, extract constant, add type annotation, obvious missing validation with a single correct answer.
- `gated_auto` - fix is clear but has a small judgment call. Dispatch with confirmation.
- `manual` - taste question, architectural choice, or cross-cutting design decision. Batch for human review.
- `advisory` - reviewer was flagging context, not requesting a change (e.g., "nit, up to you"). Reply acknowledging, do not modify code.

`security` clusters are always at least `gated_auto` regardless of heuristic score. `other` clusters are always `manual`.
