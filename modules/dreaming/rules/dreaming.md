# Dreaming: Nightly Durable-Memory Mining

Dreaming is CCGM's nightly, cost-capped, out-of-band pipeline that mines Claude Code session transcripts for cross-session failure patterns and turns them into **evidence-tagged proposals** against the `self-improving` learnings store — behind a human gate. It is `autoheal`'s capture-analyze-propose pipeline, retargeted at session transcripts instead of permission events. See `modules/self-improving/rules/learnings-store.md` for the store this module proposes changes to.

## What dreaming does

1. **Deterministic mining** (`lib/transcript_miner.py`). `discover()` enumerates session-transcript JSONLs under `~/.claude/projects/*/`, re-deriving each transcript's owning learnings-store slug from its own `cwd` field via `learnings_store.detect_project_slug()` — never from a directory-name heuristic (arch-1: the two slug spaces are different and do not agree for the same repo). `mine()` extracts friction events, user-correction sequences, PR links, and token economics; `cluster()` groups them; `budget()` trims to a token cap without ever dropping a friction cluster entirely; `schema_canary()` fails loud (never silently mines zero friction) if the transcript schema drifts.
2. **Map-reduce analysis** (`lib/dream_analyze.py`, `bin/dream-analyze.sh`). One map call per due project slug (evidence bundle → candidate learnings), then one reduce call across every planned slug's candidates plus a current store projection (candidates → per-change proposals). Every model call goes over `curl` to the Anthropic Messages API directly — no nested Claude Code agent runtime, no exec-escape surface, runs headless under launchd. `--offline <dir>` replaces every curl call with a canned fixture response for fully deterministic, no-network testing.
3. **Digest** (`bin/dream-digest.sh`). Renders `~/.claude/dreaming/digests/{date}.md`: today's proposals grouped by project/kind with evidence excerpts, a run summary, a durable canary banner for schema-drift/reduce-failure incidents, and yesterday's applied/rejected tally.
4. **Reconciliation** (`lib/reconcile_automemory.py`, `bin/dream-reconcile.sh`). Read-only comparison between Claude Code's own harness auto-memory (`~/.claude/projects/*/memory/`) and the learnings store, appended to the same digest as a "## Reconciliation" section. Never writes to either store — see "Reconciliation is read-only" below.
5. **Human-gated apply** (`lib/apply_dream_proposal.py`, `/dream-apply`). The **only** write path from a mined proposal into the learnings store, including the only path a `_global` proposal can ever be promoted through (`learnings_store.promote_to_global()`, invoked after your accept).
6. **Scheduler** (`bin/dream-daily.sh`, `bin/dream-install.sh`). A macOS `launchd` LaunchAgent chains analyze → digest → reconcile → auto-apply → retention once nightly. Each step is exit-tolerant — one step's failure never kills the rest of the chain or trips a launchd cooldown.
7. **Eval harness** (`eval/memory_eval.py`, `bin/dream-eval.sh`). With/without-memory A/B on a seed task suite (including one task that exercises the pipeline's own mined output end-to-end) with four-bucket outcome classification. `dream-eval.sh --gate` is the regression gate auto-apply must pass before it is ever allowed to act.

## The proposal/evidence/gate contract

Every proposal (`~/.claude/dreaming/proposals/{date}.jsonl`) is a per-change delta against the learnings store — `learning_add|verify|contradict|supersede|deprecate` — never a whole-store swap. Each carries: the evidence sessions that support it (redacted, ≤400-char excerpts), a prevalence count (sessions/agents), a confidence score, and a justification. Nothing is ever applied silently: a proposal starts `pending` and stays that way until a human runs `/dream-apply <id>` (or the narrow, gated auto-apply path below acts on it). Untrusted content — proposal text, evidence excerpts, justifications — is sanitized (`learnings_store.sanitize_content()`) before it ever reaches a digest a human or agent reads, and before it is ever handed to a live agent session.

## Poisoning defenses

The "promote what's prevalent" heuristic dreaming is built on is its own top attack surface (MemoryGraft/MINJA-class memory poisoning). Three defenses, in the order they matter for a solo/single-clone user:

- **Origin binding is transcript-verified, not caller-supplied.** A proposal's cited evidence sessions must resolve to real transcript files under `~/.claude/projects/**`; `writer` is derived from that transcript's own recorded `cwd`, never from a freely-exportable env var like `CCGM_AGENT_ID`. A supersede can never *raise* an entry's `source` tier (e.g. `inferred` → `user-stated`) without an independently-verified new session backing it.
- **Breadth is informational, not a bypass.** `promotion_min_sessions`/`promotion_min_agents` gate what the *digest* labels `needs_manual_promotion` for an under-prevalence `_global` proposal — it is never dropped, and it never becomes a silent, automated write. Per the plan's own honesty note (plan.md §1.4): the `agents ≥ 2` breadth condition is realistically unsatisfiable for a solo, single-clone user (every transcript inside one project slug carries exactly one writer), so treat "fleet-wide automated promotion" as a latent capability for genuine multi-agent usage, not a V1 solo-user outcome.
- **`_global` is promotion-only, through exactly one path.** `learnings_store.promote_to_global()`, invoked only by `apply_dream_proposal.py` after a recorded human accept in `/dream-apply`. No automated `_global` add exists anywhere in this module. The `CCGM_LEARNINGS_ADMIN=1` hatch (see `learnings-store.md`) is a terminal-only manual one-off, never the intended accept path — a digest never points a human at it.

## Auto-apply posture: default OFF, counters-only, eval-gated

`auto_apply_counters` (`~/.claude/dreaming/config.json`) is **`false` by default**. When flipped on, `dream-daily.sh`'s auto-apply step still requires **both**:

1. `bin/dream-eval.sh --gate` exits 0 (the regression gate — missing or red fails closed, no auto-apply that run).
2. The individual proposal is `kind == learning_verify`, `confidence ≥ 9`, and `status == pending`.

**`learning_contradict` is never auto-applied, at any confidence.** A contradict cuts effective confidence hard (−1.5) and enough of them deprecate a row; an automated, model-proposed contradict is a silent-suppression/memory-eviction vector. `learning_add`, `learning_supersede`, and `learning_deprecate` are likewise never auto-applied — `verify` is the only counter-op that is purely additive (bounded `min(uses*0.25, 2.0)` cap) and therefore the only one safe to automate. Auto-apply creates a feature branch and commits; it never pushes.

## Reconciliation is read-only

`lib/reconcile_automemory.py` compares Claude Code's own harness auto-memory against the learnings store and reports two signals: auto-memory facts absent from the store (import candidates) and store rows that dispute a topic auto-memory still presents as current (deprecated/superseded/contradicted — flagged for `/consolidate`). It **never** writes to `~/.claude/projects/` — the harness's own `autoDream` consolidator owns that file, and colliding writers on it is exactly the failure class this whole system exists to prevent (decisions.md #10). Do not extend this module to write auto-memory facts, "helpfully" sync a reconciled fact back into `MEMORY.md`, or otherwise take ownership of that file. If bidirectional sync is ever wanted, it is a deliberate, separately-reviewed design change — not a natural extension of the report.

## Quick checks

```bash
# Verify the module's own tests pass (never against the real store).
python3 -m pytest modules/dreaming/tests/ -q

# Offline end-to-end chain smoke, no network, no ANTHROPIC_API_KEY:
CCGM_DREAMING_DIR=$(mktemp -d) CCGM_LEARNINGS_DIR=$(mktemp -d) \
  bash modules/dreaming/bin/dream-daily.sh \
    --offline modules/dreaming/tests/fixtures/offline-responses \
    --force-day 2026-01-02

# Status + config (real environment):
/dream
cat ~/.claude/dreaming/config.json
```

## Slash commands

| Command | Purpose |
|---------|---------|
| `/dream` | Status overview + subcommand surface. Read-only. |
| `/dream-digest [date]` | Render today's (or a specific date's) digest. |
| `/dream-apply [id\|list]` | List pending proposals, or accept/reject one by id — the only write path into the store. |

## When NOT to invoke

- **Do not hand-edit `~/.claude/dreaming/proposals/*.jsonl`.** Proposals are write-once by the analyzer and mutated only through `/dream-apply`'s status transitions; hand-editing breaks the fingerprint-dedup and audit trail.
- **Do not flip `auto_apply_counters` to `true` without first running a live `dream-eval.sh` pass and confirming zero regression-bucket entries.** The gate exists specifically to keep this off until the eval harness has demonstrated the pipeline is trustworthy on your own data.
- **Do not treat a `needs_manual_promotion` proposal as already applied.** It is still `pending`; the label only changes how the digest presents it.
- **Do not extend `reconcile_automemory.py` (or anything in this module) to write to `~/.claude/projects/`.** See "Reconciliation is read-only" above.
- **Do not enable this module expecting fleet-wide cross-agent memory on day one.** For a solo or single-clone setup, the near-term value is per-slug cross-*session* mining (Epics 1/4/5's store hardening + injection + git durability); the dreaming service itself earns its cost as multi-agent usage grows.

## Cross-references

- `modules/self-improving/rules/learnings-store.md` — the store every proposal here targets; schema, confidence decay, supersede chains, git sync.
- `modules/autoheal/rules/autoheal.md` — the sibling pipeline this module's capture-analyze-propose shape is modeled on (permission events, not transcripts).
- Plan: `~/code/plans/ccgm-durable-memory-system/plan.md` §3 (architecture), §5 Epics 1–8 (per-epic specs), §11 (risk register — origin binding, promotion guard, and auto-apply gating each have a dedicated row).
