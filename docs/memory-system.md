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

Nightly, the analyzer mines the day's session transcripts into a redacted evidence bundle → proposes per-change deltas against the same learnings store → writes them to `~/.claude/dreaming/proposals/{date}.jsonl`. From there, one of two things happens:

- **Human-gated (default)** — you review the digest and accept/reject with `/dream-apply`. Nothing reaches the store until you do.
- **Optimistic auto-integration (opt-in)** — a per-op-kind engine writes the change immediately, holds it behind a dwell window before it can reach agent context, and reports it in the next digest for a post-hoc `/dream-review` or one-command rollback. See "Safety posture" below.

Either way, the change feeds the same read path above once it's live.

## Components

| Component | Where | Role |
|-----------|-------|------|
| Learnings store | `~/.claude/learnings/` (git repo) | Append-only, per-agent-sharded JSONL: confidence decay, staleness, supersede chains, prompt-injection sanitization |
| Store CLI | `ccgm-learnings-log` / `-search` / `-sync` | Write/verify/supersede/deprecate; query + inject; git init/commit/pull/push |
| Reflection | `/reflect`, `/consolidate`, `/retro` | Capture and maintain learnings |
| Injection hook | `learnings-inject.py` (SessionStart) | Gated on `CCGM_LEARNINGS_INJECT` **and** `source == "startup"`; emits one `<ccgm-learnings-injection>` block of top-ranked learnings for the current project |
| Nightly analyzer | `dreaming` LaunchAgent | Mines transcripts → evidence → proposals (direct Anthropic API, no nested agent) |
| Digest | `/dream-digest` | Renders the day's proposals, plus tonight's auto-integrated batch, for human review |
| Apply | `/dream-apply` | The always-available, human-gated write path from a proposal into the store |
| Optimistic engine | `optimistic_integration.enabled` (opt-in) | Per-op-kind posture engine: writes immediately behind a dwell window, bounded by per-slug caps, a batch-anomaly check, and a circuit breaker |
| Post-hoc review | `/dream-review` | Surfaces auto-integrated and still-dwelling rows for a veto; `ccgm-learnings-sync revert <sha>` rolls back a bad batch |
| Eval gate | `dream-eval.sh --gate` | With/without-memory A/B regression gate that optimistic auto-integration must pass every night |
| Scorecard | `/dream-scorecard` | Weekly, read-only observability: captured / injected / reused / applied, plus auto-integrated / mid-dwell / reverted / breaker-trips + store health |

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

3. **Optimistic mode** — if `dreaming` is installed, it also asks directly: "enable auto-integration with a 24h dwell window + daily report?" On yes it sets `optimistic_integration.enabled = true` in `~/.claude/dreaming/config.json` — the only way this ever turns on; there is no separate manual JSON edit required, and the shipped default stays `false` until you say yes. Re-run the script any time to change your answer; an already-`true` config reports as such and makes no change.

The read path alone is a complete, useful configuration. Add `dreaming` only when you want automated nightly capture and accept the token cost; add optimistic mode only when you want that capture to reach the store without running `/dream-apply` yourself.

## Safety posture: optimistic, dwell-bounded, and reversible

By default, nothing a model proposes reaches your store automatically. Every dreaming proposal is **human-gated** — it stays `pending` until you run `/dream-apply` and accept it. This is still true today and remains available regardless of anything below.

`optimistic_integration.enabled` in `~/.claude/dreaming/config.json` is an opt-in second path, **`false` by default** (the shipped-module posture — a public module must not silently start auto-writing on install). Turning it on is a deliberate choice, never a buried JSON edit: `memory-setup.sh` asks directly — "enable auto-integration with a 24h dwell window + daily report?" — and only a `y` flips the flag (see "Enabling it" above). A config that already had the OLD verify-only `auto_apply_counters` flag set `true` is migrated automatically (the same conservative defaults apply) so a prior opt-in survives the rename, without you having to re-consent by hand.

When it's on, a per-op-kind **posture** decides what happens to each proposal instead of a single blanket rule:

- **`learning_verify`** integrates immediately — no dwell. It is purely additive (confidence rises, capped) and reversible by a later contradict, so there is nothing to hold back.
- **`learning_add` / `learning_supersede`** integrate behind a **24h dwell window** (configurable): written to the store right away, but excluded from search/injection until the window elapses.
- **`learning_contradict` / `learning_deprecate`** — the eviction-shaped ops — get the same dwell treatment, capped tighter per run, since these are the ops most worth a second look before they suppress something.
- Any change to the shared `_global` store stays **fully human-gated**, unchanged — the optimistic engine never touches it.

Every run is bounded whether or not you ever read the report: a per-slug cap on how many adds/supersedes/evictions can land in one night, a batch-anomaly check that flags eviction concentration, a cross-night signal that catches a slow drip an attacker might use to stay under any single night's cap, and a windowed circuit breaker that trips on repeated anomalies (and later resumes on its own once things are quiet again). The nightly eval/regression gate (`dream-eval.sh --gate`) must also pass — missing or red fails closed, no integration that night, full stop.

**Why this is safe even if you never read the report.** Prevention (the caps, the anomaly check, the eval gate, confidence floors, decay) and exposure-bounding (the dwell window) both work with zero human reads — nothing above depends on you looking at anything. Only *correction* needs a read, and only for timeliness: the daily report, `/dream-review`, and `ccgm-learnings-sync revert <sha>` let you catch and undo a bad integration. If you never read the report, nothing worse happens than what the caps already bounded — the row just decays on its usual schedule or gets caught by a later eval run.

**The honest residual.** The dwell window shrinks the *pre-exposure* blind spot to zero — a bad row cannot reach a live agent session before the window elapses. It does **not** shrink the *post-exposure* one: once the window has passed and a session has already read a row into its frozen SessionStart context (see "Injection applies to new sessions only" below), that session keeps it for its own lifetime. A revert or `/dream-review` veto stops *future* sessions from seeing it; an already-running session must be restarted to actually drop it. Nothing shortens this except a shorter dwell window (more report lead time) and ordinary confidence decay.

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
- [`learnings-store.md`](../modules/self-improving/rules/learnings-store.md) — store schema, confidence decay, supersede chains, the dwell window, git sync, and rollback
- [`dreaming.md`](../modules/dreaming/rules/dreaming.md) — the nightly pipeline, the proposal / evidence / gate contract, and the optimistic auto-integration engine
