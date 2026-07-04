# Memory System

CCGM's durable, cross-session memory. It comes in two halves:

- **Read path** — the [`self-improving`](../modules/self-improving/rules/self-improving.md) learnings store plus a SessionStart hook that surfaces what you've learned at the start of each new session. Local and free.
- **Write path** — the [`dreaming`](../modules/dreaming/rules/dreaming.md) module: a nightly analyzer that mines your session transcripts and proposes new learnings behind a human gate. Opt-in; spends Anthropic API tokens.

The read path is the valuable, always-safe half and works on its own. The write path is an optional layer on top that automates capture — you never need it to benefit from memory.

| Half | Module | Storage | Cost | Network |
|------|--------|---------|------|---------|
| Read path | `self-improving` | `~/.claude/learnings/` (local git repo) | free | none |
| Write path | `dreaming` | `~/.claude/dreaming/` | Anthropic API tokens | analyzer only, opt-in |

## The end-to-end loop

**Read path (manual/assisted capture → reuse):**

1. **Capture** — `/reflect`, `/consolidate`, `/retro`, or a direct `ccgm-learnings-log` call write a learning (a pattern, pitfall, preference, architecture fact, tool gotcha, or ops fact).
2. **Store** — it lands in the append-only JSONL learnings store, ranked by confidence with time-based decay and staleness detection.
3. **Inject** — at the *next* fresh session start, the injection hook surfaces the project's top-ranked learnings into context.
4. **Reuse** — when a learning proves useful again, a `verify` op reinforces it, which raises its effective confidence and refreshes its freshness.

**Write path (dreaming, automated capture):**

Nightly, the analyzer mines the day's session transcripts into a redacted evidence bundle → proposes per-change deltas against the same learnings store → writes them to `~/.claude/dreaming/proposals/{date}.jsonl` → you review the digest and accept/reject with `/dream-apply`. Accepted proposals feed the same read path above.

## Components

| Component | Where | Role |
|-----------|-------|------|
| Learnings store | `~/.claude/learnings/` (git repo) | Append-only, per-agent-sharded JSONL: confidence decay, staleness, supersede chains, prompt-injection sanitization |
| Store CLI | `ccgm-learnings-log` / `-search` / `-sync` | Write/verify/supersede/deprecate; query + inject; git init/commit/pull/push |
| Reflection | `/reflect`, `/consolidate`, `/retro` | Capture and maintain learnings |
| Injection hook | `learnings-inject.py` (SessionStart) | Gated on `CCGM_LEARNINGS_INJECT` **and** `source == "startup"`; emits one `<ccgm-learnings-injection>` block of top-ranked learnings for the current project |
| Nightly analyzer | `dreaming` LaunchAgent | Mines transcripts → evidence → proposals (direct Anthropic API, no nested agent) |
| Digest | `/dream-digest` | Renders the day's proposals for human review |
| Apply | `/dream-apply` | The only human-gated write path from a proposal into the store |
| Eval gate | `dream-eval.sh --gate` | With/without-memory A/B regression gate that auto-apply must pass |
| Scorecard | `/dream-scorecard` | Weekly, read-only observability: captured / injected / reused / applied counts + store health |

The read path uses only the first four rows. The rest ship with `dreaming`.

## Enabling it

Run the activation script (idempotent — re-running reports current state and changes nothing already set):

```bash
bash ~/.claude/bin/memory-setup.sh
```

It confirms before every write and:

1. **Read path** — explains it, then on your yes sets `CCGM_LEARNINGS_INJECT=true` in `~/.claude/settings.json` (via a deep merge that preserves your existing `env` keys) and runs `ccgm-learnings-sync init` so the store is a versioned git repo. Local, free, no network.
2. **Write path** — if `dreaming` is installed, it offers to activate it: this costs Anthropic API tokens and installs a nightly LaunchAgent. It prompts for your API key, writes it to `~/.claude/dreaming/.env` (mode `0600`, never echoed), and runs `dream-install.sh`. If `dreaming` isn't installed, it prints how to add it:

   ```bash
   bash start.sh --add dreaming
   ```

The read path alone is a complete, useful configuration. Add `dreaming` only when you want automated nightly capture and accept the token cost.

## Safety posture: auto-apply is OFF by default

Nothing a model proposes reaches your store automatically. Every dreaming proposal is **human-gated** — it stays `pending` until you run `/dream-apply` and accept it.

There is one optional automated write path, `auto_apply_counters` in `~/.claude/dreaming/config.json`, and it is **`false` by default**. Even when enabled it is deliberately narrow:

- It must clear the eval/regression gate (`dream-eval.sh --gate`) — missing or red fails closed.
- It only ever applies `verify` counter-ops — **never** add / supersede / deprecate / contradict (a model-proposed contradict is a silent memory-eviction vector, so it is never automated at any confidence).
- The proposal must be `confidence ≥ 9` and still `pending`.
- It commits to a feature branch and **never pushes**.

Honest current state: the eval gate is the safety mechanism, and it stays closed by design. The harness has not yet demonstrated that auto-apply is trustworthy for capable models, so **auto-apply does not run today** — treat `/dream-apply` (human review) as the real write path. Do not enable `auto_apply_counters` without first running a live `dream-eval.sh` pass and confirming zero regressions.

## Injection applies to new sessions only

The injection hook fires on `SessionStart` **only when `source == "startup"`** — never on resume or compact. The injected block is frozen into the session's prompt prefix at start (this prefix-cache safety is deliberate; re-injecting per turn is the exact anti-pattern the hook avoids).

Consequences:

- An **already-open session will not gain** newly-logged learnings. Start a *fresh* session to pick them up.
- A learning you log **during** a session is not visible to that same session's injected block — it appears at the next fresh start.

## Observability

- **Scorecard** — `/dream-scorecard` renders a deterministic weekly report to `~/.claude/dreaming/scorecards/{date}.md`: how many learnings were **captured**, **injected**, **reused**, and **applied**, plus store-health confidence bands. Every number is a count of something already on disk (read-only; it never touches the store). Reuse (`verify` events) is the key signal that memory is paying off across sessions.
- **Injection telemetry** — each surfacing appends one record (memory **IDs + counts + a token estimate only — never memory content**) to `~/.claude/dreaming/injection-log/{date}.jsonl`. It is per-machine, lives outside the synced learnings store, and is best-effort (any failure is swallowed and never blocks or alters the injected block). The scorecard's "Injected" section reads this log.

The injection telemetry is written by the read-path hook itself, so it accrues even without `dreaming` installed; the `/dream-scorecard` command that renders it ships with `dreaming`.

## Troubleshooting

**Injection isn't firing.** Check, in order:

1. **The flag.** `CCGM_LEARNINGS_INJECT` must be truthy (`true` / `1` / `yes`) in the environment the session starts with — look in `~/.claude/settings.json` under `env` (this is what `memory-setup.sh` sets). With the flag unset the hook is a strict no-op.
2. **A fresh session.** The hook only runs on `source == "startup"`. Resuming or continuing an existing session will not inject; open a new session.
3. **Learnings for this project.** Injection surfaces the *current project's* store. A brand-new project with nothing logged has nothing to inject — confirm with `ccgm-learnings-search --query <topic>`.
4. **Conflicted rows are suppressed.** A learning flagged as conflicted (two competing edits racing the same entry) is withheld from injection because it isn't settled truth — run `/consolidate` to resolve it.

## Privacy

- Learnings stay **on your machine**. `~/.claude/learnings/` is a local git repo with no remote by default — nothing leaves the machine.
- **Cross-machine sync is opt-in.** Add a *private* git remote and `ccgm-learnings-sync push`. This repo holds personal memory — keep it private; never point it at a public repo.

  ```bash
  git -C ~/.claude/learnings remote add origin git@github.com:<you>/ccgm-learnings.git
  ccgm-learnings-sync commit && ccgm-learnings-sync push
  ```

- Injection telemetry records IDs + counts only, never content, and is never committed to the synced store.
- When you opt into `dreaming`, the analyzer sends **redacted** transcript evidence to the Anthropic API. The read path makes no network calls of its own; use your own API key (`<your-anthropic-api-key>`), which the setup script stores in `~/.claude/dreaming/.env`.

## Reference

The rule files below are the authoritative, agent-facing specs this guide distills:

- [`self-improving.md`](../modules/self-improving/rules/self-improving.md) — the reflection loop and capture triggers
- [`learnings-store.md`](../modules/self-improving/rules/learnings-store.md) — store schema, confidence decay, supersede chains, git sync
- [`dreaming.md`](../modules/dreaming/rules/dreaming.md) — the nightly pipeline and the proposal / evidence / gate contract
