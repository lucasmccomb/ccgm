# dreaming

Nightly, cost-capped dreaming service that mines Claude Code session
transcripts for cross-session failure patterns and proposes evidence-tagged
memory-store changes behind a human gate. Extends the `self-improving`
learnings store with an out-of-band analyzer -- `autoheal`'s
capture-analyze-propose pipeline, retargeted at session transcripts instead
of permission events.

Status: **beta**. This module ships incrementally; see "What's implemented
so far" below.

## Why this module exists

`self-improving` gives agents an in-band way to log a learning as they work.
`autoheal` proves out-of-band mining works for permission events. Neither
mines the richer session-transcript JSONL directly -- tool errors, hook
errors, user corrections, token/cache economics, PR links. `dreaming` closes
that gap: a nightly job reads the transcripts every session already writes,
extracts patterns a single in-session agent cannot see, and proposes
per-change memory-store updates for a human to accept or reject.

Full design: `~/code/plans/ccgm-durable-memory-system/plan.md` (§5 Epic 2 for
this module's first landing).

## What's implemented so far (Epic 2)

The **deterministic transcript miner** -- pure Python stdlib, no network
calls, no LLM calls, no scheduling:

- `discover(slugs, since_watermark)` -- enumerate transcript files under
  `~/.claude/projects/*/` whose owning learnings-store slug (re-derived from
  each transcript's own `cwd` field) is in the wanted set.
- `mine(path)` -- extract friction events (tool errors, hook errors,
  prevented-continuation), user-correction sequences, PR links, token
  totals + cache-read ratio, and session identity from one transcript.
- `cluster(events)` -- group events by `(event_kind, tool_name,
  command_prefix)`.
- `budget(clusters, max_input_tokens)` -- trim to a token cap without ever
  dropping a friction cluster entirely.
- `schema_canary(mined_sessions)` -- fail loud (raise) if the transcript
  schema appears to have drifted since this miner was last validated.

Not yet built (later epics, same module): the map-reduce analyzer that
turns evidence into proposals (Epic 3), the apply path / slash commands /
scheduler (Epic 6), the eval harness (Epic 7), and MEMORY.md reconciliation
(Epic 8).

## Slug identity (read this before touching project-identity code)

Every transcript's owning learnings-store slug is re-derived from the
transcript's own `cwd` field via `learnings_store.detect_project_slug()` --
**never** via `session-history`'s `repo_detect.py`. Those two functions
compute *different* strings for the same repo (verified live on the
development machine: `repo_detect.py` returns the bare repo-directory
name, while `detect_project_slug()` returns the canonical `owner-repo`
form derived from the git remote). Using the wrong one silently mines
into an orphaned namespace no read path ever queries. `session-history`'s
`discover-sessions.sh` / `repo_detect.py` exist only to locate transcript
*files* by directory-name heuristic; this module
never imports or consults them for identity.

## Evidence bundle format

`mine_to_evidence_bundle(paths, max_input_tokens=...)` is the function that
wires `mine()` + `schema_canary()` + `cluster()` + `budget()` together into
the **evidence bundle** -- the frozen contract Epic 3's analyzer consumes.
The shape is pinned in `lib/evidence-bundle-schema.json` (a real JSON
Schema, validated by both this module's `--self-check` and, in Epic 3,
`dream_analyze.py` on load, via the same stdlib-only
`transcript_miner.validate_against_schema()`). At a glance:

```json
{
  "generated_at": "<ISO 8601 UTC>",
  "slugs": ["<learnings-store slug>", "..."],
  "session_count": 4,
  "sessions": [
    {
      "session_id": "<uuid or null>",
      "slug": "<learnings-store slug>",
      "git_branch": "<str or null>",
      "started_at": "<ISO or null>",
      "ended_at": "<ISO or null>",
      "token_totals": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
      "cache_read_ratio": 0.0,
      "user_corrections": [{"excerpt": "...", "timestamp": "...", "session_id": "...", "line": 5, "turns_after_failure": 2, "friction_line": 3}],
      "pr_links": [{"pr_number": 9001, "pr_repository": "org/repo", "pr_url": "https://..."}],
      "malformed_line_count": 0,
      "tool_use_count": 1,
      "friction_field_presence": 4
    }
  ],
  "clusters": [
    {
      "event_kind": "tool_error",
      "tool_name": "Bash",
      "command_prefix": "./deploy.sh --env prod",
      "count": 1,
      "is_friction": true,
      "sample_session_ids": ["<uuid>"],
      "exemplars": [{"session_id": "<uuid>", "excerpt": "<redacted, <=400 chars>", "timestamp": "..."}]
    }
  ],
  "friction_cluster_count": 4,
  "routine_cluster_count": 0,
  "token_estimate": 1234,
  "max_input_tokens": 200000,
  "over_budget": false,
  "malformed_line_total": 0,
  "canary": {"observed_versions": {"2.1.198": 4}, "untested_versions": []}
}
```

Every `excerpt` field has already been through `redact_secrets()` (17 secret
token shapes, `hooks` module) and `redact_pii()` (email/phone/address, this
module's own addition -- `hook_utils` has no PII coverage) and truncated to
400 chars, redaction always applied *before* truncation so a boundary can
never lop a redaction marker in half.

## Redaction: two layers

- `hook_utils.redact_secrets()` -- 17 vendor secret-token shapes (API keys,
  GitHub tokens, etc.), shared with `autoheal`.
- `redact_pii()` (this module) -- email, phone, and street-address shapes.
  Transcripts are prose and routinely carry the operator's own PII;
  `redact_secrets()` alone does not cover that class.

Both run on every excerpt before it is stored anywhere or would leave the
machine (Epic 3's API calls).

## Schema drift canary

The transcript JSONL is an undocumented, internal Claude Code format that
has already drifted once (a `queue-operation` line type absent from earlier
research). `schema_canary()` distinguishes "genuinely quiet week" (friction
*fields* present, just reporting no problems) from "the miner no longer
recognizes this transcript version's field names" (fields absent despite
`tool_use` activity) and raises loudly in the second case rather than
silently returning an empty evidence bundle. It also records the observed
`version` distribution so an untested version is visible even when it
doesn't (yet) trip the canary.

## Quick checks

```bash
# Run the miner's own test suite (offline, fixture-only).
python3 -m pytest modules/dreaming/tests/test_transcript_miner.py -q

# End-to-end fixture pipeline + schema validation + JSON summary.
python3 modules/dreaming/lib/transcript_miner.py --self-check
```

## When NOT to use this module (yet)

- There is no scheduler, analyzer, or apply path in this landing --
  `dreaming` does not write to the learnings store or call any API. If you
  need memory to actually change based on transcript patterns today, that
  is a later epic.
- Do not call `mine()`/`discover()` against real transcripts expecting
  proposals; the miner only produces the bounded, redacted evidence bundle
  that a *future* analyzer will read.

## Manual installation (development clone)

```bash
# From a CCGM development clone (not the canonical):
bash start.sh --add dreaming
```

## Cross-references

- Plan: `~/code/plans/ccgm-durable-memory-system/plan.md` (§5 Epic 2; §3.3
  for the runtime-dir and config-key contract later epics build on).
- Decision log: `~/code/plans/ccgm-durable-memory-system/decisions.md`.
- `modules/self-improving/` -- the learnings store this module's future
  analyzer will propose changes into.
- `modules/autoheal/` -- the capture-analyze-propose pipeline this module's
  later epics mirror (not import).
