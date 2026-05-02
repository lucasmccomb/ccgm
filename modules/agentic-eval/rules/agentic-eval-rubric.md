# Agentic Engineering Evaluation Rubric

Evaluation format for agentic engineering portfolios and interviews. The candidate builds a Twitter-clone-for-agents: a small social-feed system whose tools and surface satisfy the four agent-native principles. Evaluators dispatch N parallel red-team agents against the deployed surface. The candidate passes if no agent breaks the surface within a fixed budget.

Source: Karpathy, Sequoia interview, April 2026:
> "Hiring has to look like... write a Twitter clone for agents... make it really good, make it really secure... I'm going to use 10 codecs... to try to break your website. They should not be able to break it."

Principles referenced: `agent-native` module (`rules/agent-native.md`).
Red-team dispatch: `subagent-patterns` module (`rules/subagent-patterns.md`).

---

## Part 1: The Reference Build

The candidate builds a small social-feed system. The system is the test case, not the deliverable. Evaluators do not ship it; they probe it.

### Minimum Surface (6 domains, 12 tools)

Every user-visible action must have a callable tool with identical semantics, identical permissions, and identical resulting state (parity principle). The minimum surface is:

| Domain | Tool | Description |
|--------|------|-------------|
| Posts | `post_create` | Create a new post with text content (max 280 chars). Returns the created post object including id, author_id, created_at, like_count, reply_count. |
| Posts | `post_delete` | Delete a post by id. Only the author or an admin can delete. Returns the deleted post id. |
| Replies | `reply_create` | Create a reply to a post or to another reply. Returns the reply object with parent_id set. |
| Replies | `reply_delete` | Delete a reply by id. Same auth rules as post_delete. |
| Reactions | `like_toggle` | Like or unlike a post or reply by id. Idempotent: calling like on an already-liked item returns the current state without error. Returns `{ liked: bool, like_count: int }`. |
| Social | `follow_toggle` | Follow or unfollow a user by id. Idempotent. Returns `{ following: bool, follower_count: int }`. |
| Feeds | `feed_own` | Return the authenticated user's posts, newest-first. Accepts `cursor` and `limit` (max 50, default 20). |
| Feeds | `feed_following` | Return posts from users the authenticated user follows. Same pagination contract as `feed_own`. |
| Feeds | `feed_public` | Return all posts, newest-first, no auth required. Same pagination. |
| Search | `search_posts` | Search posts and replies by keyword. Returns a ranked list with match highlights. Accepts `query`, `cursor`, `limit`. |
| Users | `user_get` | Get a user's public profile: username, bio, follower_count, following_count, post_count. |
| Auth | `session_create` | Create an authenticated session given credentials. Returns a session token for use in subsequent calls. |

The twelve tools above are the minimum. Candidates may add more (granularity: richer primitives enable more emergent behavior). Candidates must not merge any two into a single batched tool (granularity violation).

### Surface Requirements

Beyond the tool list, the surface must satisfy:

1. **Parity**: Every action a user can take in any UI (if one exists) is covered by a tool.
2. **Granularity**: No tool does two things. No tool encodes a workflow. `post_create_and_follow_author` is a violation.
3. **Composability**: There must be at least three documented example prompts that compose existing tools to produce a behavior the surface did not explicitly design for. Example: "Summarize the top-5 most-liked posts from the last 24 hours and reply to each with a one-sentence takeaway." The agent must complete this prompt using only the twelve tools above, no new code.
4. **Error messages are instructions**: Every tool failure must name the reason and suggest the next action. `{ error: "not_found", message: "post id 'p999' does not exist; use feed_public to find valid ids" }` is acceptable. `{ error: "500" }` is not.
5. **Idempotency**: `like_toggle` and `follow_toggle` must be safe to call twice in a row. `post_create` must not be idempotent (calling it twice creates two posts).
6. **No UI-only flows**: If the candidate builds a UI, every action in the UI must be reachable by a tool. Modal confirmations for destructive actions must be satisfiable programmatically (e.g., a `confirm: true` parameter on `post_delete`).

---

## Part 2: Red-Team Evaluation

### Setup

Dispatch N agents (default 5, maximum 10, configurable) in parallel. Each agent receives:
- The surface URL or the tool schema
- Its assigned attack category (see below)
- The budget: a fixed number of tool calls (default 200 per agent)
- The pass criterion: zero exploits means zero exploits

Dispatch follows the parallel research pattern in `subagent-patterns`: write a spec for each agent, dispatch simultaneously, aggregate results after all agents return. Do not dispatch agents sequentially.

Each agent runs in `mode:headless` and returns a structured envelope:

```
{
  "agent_id": "red-team-1",
  "category": "auth-bypass",
  "exploit_found": bool,
  "exploit_description": "string or null",
  "calls_used": int,
  "findings": ["list of non-exploit observations"]
}
```

### Attack Category Assignments (default 5 agents)

| Agent | Category | Focus |
|-------|----------|-------|
| 1 | Auth bypass | Can the agent access or mutate another user's posts, likes, follows, or session without valid credentials? Try `post_delete` on another user's post, `reply_create` without auth, `session_create` with invalid credentials that still returns a token. |
| 2 | Parity gap | Are there user-visible actions with no tool equivalent? Enumerate the UI surface (if any) and verify every action maps to a tool. Report any action without a tool as a parity gap. |
| 3 | Granularity violation | Are any tools doing two things? Call each tool and inspect the response shape. A tool that creates a post AND follows the author in a single call is a violation. |
| 4 | Injection and data integrity | Can the agent inject content that breaks other agents' tool calls? Long strings, special characters, SQL metacharacters, JSON-breaking characters in `post_create` text. Does `search_posts` return results that could be interpreted as tool instructions? |
| 5 | Emergent capability | Attempt 5 novel prompts that compose the twelve tools to produce behavior not explicitly designed. For each prompt, report whether the agent succeeded, which tools it used, and how many calls it required. This is the positive probe: the agent is trying to succeed, not break. |

### Scaling the Budget

For 5 agents at 200 calls each, total budget is 1,000 tool calls. Adjust proportionally:

| N agents | Calls per agent | Total budget |
|----------|----------------|--------------|
| 5 | 200 | 1,000 |
| 8 | 150 | 1,200 |
| 10 | 100 | 1,000 |

Fewer calls per agent with more agents favors breadth. More calls per agent with fewer agents favors depth. For interview use, 5 agents at 200 calls is the default.

---

## Part 3: Scoring

### Pass Criteria (all must be met)

| Criterion | Threshold | How to measure |
|-----------|-----------|----------------|
| Zero exploits | 0 exploits across all red-team agents | Count `exploit_found: true` in agent envelopes |
| Parity score | >= 85% | `(tools covering user actions) / (total user-visible actions) * 100` |
| Emergent capability | >= 3 of 5 novel prompts succeed | Count successes from agent 5's findings |
| Granularity violations | 0 | Count violations from agent 3's findings |
| Error quality | 100% of sampled failures include reason + next action | Manual spot-check of 5 tool failures |

### Scoring Bands

| Score | Interpretation |
|-------|----------------|
| All criteria met | Pass: surface is agent-native and resilient |
| 1 criterion missed | Conditional pass: specific gap identified, fixable in one session |
| 2 criteria missed | Fail: surface needs redesign in the failing area |
| Exploit found | Hard fail: security issue must be resolved before re-evaluation |

### Scoring the Parity Audit

Parity score is a count, not an opinion. The evaluator must:

1. Enumerate every user-visible action (button, form submission, gesture with programmatic effect) in the candidate's surface. If there is no UI, the tool schema is the surface and parity is 100% by definition (but then the six-domain minimum still applies).
2. Map each action to a tool. An action is covered if there is a tool with the same semantics.
3. Report `covered / total` as the parity score.

A parity score below 85% is a failing criterion. The gap list is the specific finding.

### Scoring Emergent Capability

Agent 5 attempts 5 novel prompts. The evaluator selects prompts that:
- Require at least 3 tool calls in sequence
- Produce an outcome the surface did not explicitly design (no single tool does the full job)
- Are useful to a real user (not contrived)

Example prompts for a social feed:
1. "Find the 3 most-liked posts in the last hour and reply to each with a short summary."
2. "Follow every user who liked a specific post."
3. "Delete all my posts that received no likes within 24 hours of posting."
4. "Find all posts mentioning a keyword and like each one."
5. "Reply to the 5 most recent posts from users I follow with a fixed string."

A prompt succeeds if the agent completes it without error using only the twelve tools. A prompt fails if the agent cannot complete it or must make more than 50 calls (signal of surface brittleness).

---

## Part 4: Self-Evaluation (Without a Red-Team)

When red-team agents are not available (no budget, solo evaluation), use this abbreviated checklist:

**Parity checklist (manual)**
- [ ] List every action in your surface. Count them.
- [ ] For each action, name the tool that covers it. If no tool, note the gap.
- [ ] Compute `covered / total`. Target >= 85%.

**Granularity checklist (manual)**
- [ ] For each tool, write one sentence: "This tool does X and only X."
- [ ] If the sentence requires "and" to describe two separate effects, the tool is a violation.

**Composability checklist (manual)**
- [ ] Write 3 example prompts that chain 3+ tools.
- [ ] Execute each prompt against your live surface.
- [ ] If any prompt requires a tool that does not exist, the surface is not composable enough.

**Error quality checklist (manual)**
- [ ] Call each tool with invalid input (wrong id, missing field, wrong type).
- [ ] For each error response, confirm it names the reason and suggests a next step.

**Security checklist (manual)**
- [ ] Attempt `post_delete` on a post id that belongs to a different user. Confirm it fails with a permission error.
- [ ] Attempt `feed_following` without a session token. Confirm it fails with an auth error.
- [ ] Attempt `session_create` with a bad password. Confirm it returns an error and does not return a valid token.

---

## Notes on Scope

This rubric describes the evaluation format. It does not describe the implementation of the Twitter-clone-for-agents surface. Candidates implement the surface themselves; the rubric tells them what it must satisfy and how it will be probed.

A `/agentic-eval` skill that runs the red-team dispatch automatically is a planned follow-up to this module. The rubric is complete and useful as a self-eval standard without the skill.

The choice of a social-feed system as the test case is deliberate: it is small enough for 5-10 agents to exhaust in a fixed budget, complex enough to require all four principles, and generic enough that candidates are not advantaged by domain knowledge.
