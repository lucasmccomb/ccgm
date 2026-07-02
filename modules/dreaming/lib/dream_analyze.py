#!/usr/bin/env python3
"""Nightly dreaming analyzer: evidence bundle -> map -> reduce -> proposals.

Orchestrates Epic 3 of the CCGM durable-memory plan (plan.md §5 Epic 3):
mines due session transcripts per project slug (Epic 2's transcript_miner),
maps each slug's evidence bundle to candidate learnings via one Messages API
call per slug, reduces every slug's candidates plus a current-store
projection into per-change proposal rows in a single call, then writes those
rows to ~/.claude/dreaming/proposals/{date}.jsonl.

Mirrors autoheal's capture-analyze-propose pipeline (curl invocation, daily
cost cap, rejected/cost-log bookkeeping) WITHOUT importing autoheal code --
this is a deliberate, documented duplication (decisions.md bizlogic-006),
not an oversight. autoheal targets permission events; this targets session
transcripts. The two pipelines are close cousins, not the same code.

No nested Claude Code agent runtime: every model call goes over `curl` to
the Anthropic Messages API directly (same rationale as autoheal -- no
process-exec attack surface, a pure prompt -> JSON pipeline that runs
headless under launchd where an interactive agent runtime is unavailable).

Pipeline shape:
    1. Resolve candidate project slugs (CLI --slugs > config `scopes` >
       learnings_store.list_project_slugs() auto-discovery). `_global` is
       never a mining target -- it has no transcripts of its own.
    2. For each candidate slug, discover() + mine_to_evidence_bundle() any
       transcripts newer than that slug's watermark (state/last-dreamed.json).
       Mining is free (deterministic, offline) -- done for every due slug
       up front so the cost preflight (next step) has real bundle sizes to
       plan against. schema_canary() firing for a slug excludes it from
       this run (never silently mined) and records a durable incident
       (state/canary.json) rather than crashing the whole run (adrev-002 /
       adrev-014 / the #753 handoff note on the canary-visibility gap).
    3. Preflight cost estimate (arch-4): walk due slugs LEAST-RECENTLY-
       DREAMED FIRST (state/last-dreamed.json watermark ascending, missing
       treated as oldest), accumulating estimated map+reduce cost, and stop
       BEFORE adding a slug that would exceed the remaining daily budget.
       This determines the FULL run plan before any API call is made --
       never a mid-run cutoff. A persistently over-cap fleet rotates
       coverage across nights because slugs left out this run keep their
       old (unadvanced) watermark and sort first next time.
    4. Map: one call per planned slug (model `map_model`, system prompt
       dreaming-prompt-map.md, bounded 429 retry-with-backoff -- bizlogic-009).
    5. Reduce: one call across every planned slug's map candidates plus a
       store projection for those slugs + `_global` (model `reduce_model`,
       system prompt dreaming-prompt-reduce.md). Retries once on unparseable
       JSON with a "return only JSON" nudge.
    6. Every raw proposal is validated, sanitized (sec-3), fingerprinted
       (dedup against every prior proposals/*.jsonl, excluding the target
       day's own file under --force-day -- adrev-013), breadth-flagged for
       under-prevalence `_global` proposals (adrev-009/adrev-405), and
       compaction-guarded for `learning_supersede` (sec-11) before it is
       ever written to disk.
    7. Watermarks advance only for slugs actually mined this run, to the
       newest mined transcript line's timestamp -- never on a canary-fired
       or preflight-excluded slug.

`--offline <dir>` replaces every curl call with a canned Messages API
response read from `<dir>/map-<slug>.json` (falling back to
`map-default.json`) and `<dir>/reduce.json`. No network, no ANTHROPIC_API_KEY
required. Preflight cost math still runs in offline mode (it is a pure
function of estimated tokens + configured pricing, independent of transport)
so a --offline test can still exercise the cost-cap abort path.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import transcript_miner as tm  # noqa: E402  (sibling module, same lib/ dir)

# learnings_store lives in a DIFFERENT module's lib/ dir (self-improving).
# Reuse transcript_miner's own cross-module import helper rather than
# re-implementing it -- dream_analyze.py and transcript_miner.py are
# sibling files INSIDE the same `dreaming` module, so sharing this small
# helper between them is ordinary intra-module code reuse, not the
# cross-MODULE duplication decisions.md bizlogic-006 deliberately keeps
# separate from autoheal.
learnings_store = tm._import_sibling_module(  # noqa: SLF001
    "self-improving", "learnings_store", "store projection, sanitize_content, compact_preserves_facts"
)

SchemaDriftError = tm.SchemaDriftError
validate_against_schema = tm.validate_against_schema

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAP_MODEL = "claude-sonnet-5"
DEFAULT_REDUCE_MODEL = "claude-opus-4-8"
DEFAULT_MAX_INPUT_TOKENS = 200_000
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_DAILY_COST_CAP_USD = 10.0
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_PROMOTION_MIN_SESSIONS = 3
DEFAULT_PROMOTION_MIN_AGENTS = 2

DEFAULT_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# 429 retry/backoff (bizlogic-009). Kept short: the daily job has a whole
# night to run, but an interactive/manual invocation should not hang.
MAX_429_RETRIES = 3
BACKOFF_SCHEDULE_SECONDS = (2, 4, 8)

# Fallback per-model pricing (USD per million tokens), used only when
# config.json has no `cost_pricing` entry for the configured model. Mirrors
# autoheal's own FALLBACK_PRICING shape and posture (bin/autoheal-analyze.sh)
# -- a documented, deliberate duplication (bizlogic-006), not a shared import.
FALLBACK_PRICING: dict[str, dict[str, float]] = {
    DEFAULT_MAP_MODEL: {"input_per_million": 3.0, "output_per_million": 15.0},
    DEFAULT_REDUCE_MODEL: {"input_per_million": 15.0, "output_per_million": 75.0},
}

VALID_PROPOSAL_KINDS = {
    "learning_add",
    "learning_verify",
    "learning_contradict",
    "learning_supersede",
    "learning_deprecate",
}
KINDS_REQUIRING_TARGET = {"learning_verify", "learning_contradict", "learning_supersede", "learning_deprecate"}
KINDS_REQUIRING_CONTENT = {"learning_add", "learning_supersede"}

GLOBAL_SLUG = learnings_store.GLOBAL_SLUG


# ---------------------------------------------------------------------------
# Paths (env-overridable; mirrors autoheal's autoheal_dir()/events_dir()/...)
# ---------------------------------------------------------------------------


def dreaming_dir() -> Path:
    return Path(os.environ.get("CCGM_DREAMING_DIR", os.path.expanduser("~/.claude/dreaming")))


def proposals_dir() -> Path:
    return dreaming_dir() / "proposals"


def digests_dir() -> Path:
    return dreaming_dir() / "digests"


def state_dir() -> Path:
    return dreaming_dir() / "state"


def runs_dir() -> Path:
    return state_dir() / "runs"


def config_path() -> Path:
    return Path(os.environ.get("CCGM_DREAMING_CONFIG", str(dreaming_dir() / "config.json")))


def cost_log_path() -> Path:
    return dreaming_dir() / "cost.log"


def canary_state_path() -> Path:
    return state_dir() / "canary.json"


def instructions_path() -> Path:
    return dreaming_dir() / "instructions.md"


def env_file_path() -> Path:
    return Path(os.environ.get("CCGM_DREAMING_ENV_FILE", str(dreaming_dir() / ".env")))


def autoheal_env_file_path() -> Path:
    """§3.5 auth-flow fallback: ~/.claude/autoheal/.env when dreaming's own
    .env has no ANTHROPIC_API_KEY. Independently overridable for tests."""
    return Path(os.environ.get(
        "CCGM_DREAMING_AUTOHEAL_ENV_FILE",
        os.path.expanduser("~/.claude/autoheal/.env"),
    ))


def today_iso() -> str:
    override = os.environ.get("CCGM_DREAMING_TODAY")
    if override:
        return override
    return datetime.now(timezone.utc).date().isoformat()


def _utc_now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Config (§3.3 config keys; falls open to defaults exactly like
# learnings_store.load_config() -- never creates the file, Epic 6's
# dream-install.sh owns bootstrapping a real config.json)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "map_model": DEFAULT_MAP_MODEL,
    "reduce_model": DEFAULT_REDUCE_MODEL,
    "max_input_tokens": DEFAULT_MAX_INPUT_TOKENS,
    "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
    "daily_cost_cap_usd": DEFAULT_DAILY_COST_CAP_USD,
    "lookback_days": DEFAULT_LOOKBACK_DAYS,
    "auto_apply_counters": False,
    "promotion_min_sessions": DEFAULT_PROMOTION_MIN_SESSIONS,
    "promotion_min_agents": DEFAULT_PROMOTION_MIN_AGENTS,
    # §3.3 shows a literal "<slug>" placeholder in its example -- that is
    # documentation shorthand, not a real default (adrev-l9). The real
    # default is an empty list, which means "auto-discover" (see
    # resolve_candidate_slugs()): every slug that already has a learnings
    # store. Set an explicit list here to pin dreaming to specific projects.
    "scopes": [],
    "cost_pricing": {},
}


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    path = config_path()
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            cfg.update(loaded)
    return cfg


# ---------------------------------------------------------------------------
# .env loading (§3.5 auth flow) -- never overrides an already-set env var,
# so a caller/test that exported ANTHROPIC_API_KEY always wins.
# ---------------------------------------------------------------------------


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_env() -> None:
    """§3.5: dreaming's own .env first, falling back to autoheal's .env for
    ANTHROPIC_API_KEY when dreaming's copy does not set it. Never read from
    shell rc (autoheal rule) -- both paths are explicit files under
    ~/.claude, never ~/.zshrc or ~/.bash_profile."""
    _load_env_file(env_file_path())
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _load_env_file(autoheal_env_file_path())


# ---------------------------------------------------------------------------
# Pricing + cost estimation
# ---------------------------------------------------------------------------


def resolve_pricing(cfg: dict[str, Any], model: str) -> dict[str, float]:
    pricing_map = cfg.get("cost_pricing")
    if isinstance(pricing_map, dict) and model in pricing_map:
        entry = pricing_map[model]
        if isinstance(entry, dict) and "input_per_million" in entry and "output_per_million" in entry:
            return {
                "input_per_million": float(entry["input_per_million"]),
                "output_per_million": float(entry["output_per_million"]),
            }
    if model in FALLBACK_PRICING:
        return FALLBACK_PRICING[model]
    # Unknown model with no configured pricing: fall back to the map
    # model's pricing (cheaper of the two defaults) rather than guessing
    # high or crashing -- a preflight estimate that is slightly low is
    # still far better than refusing to run at all.
    return FALLBACK_PRICING[DEFAULT_MAP_MODEL]


def estimate_call_cost_usd(input_tokens: int, output_tokens: int, pricing: dict[str, float]) -> float:
    return (
        input_tokens * pricing["input_per_million"] + output_tokens * pricing["output_per_million"]
    ) / 1_000_000.0


def _read_cost_spent_today(path: Path, today: str) -> float:
    """Tab-separated cost.log, same shape as autoheal's: date, in_tok,
    out_tok, cost_usd, model. Skipped in --offline mode (no real spend)."""
    if not path.is_file():
        return 0.0
    total = 0.0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4 and parts[0] == today:
                try:
                    total += float(parts[3])
                except ValueError:
                    continue
    return total


def _append_cost(path: Path, today: str, in_tok: int, out_tok: int, cost_usd: float, model: str) -> None:
    line = f"{today}\t{in_tok}\t{out_tok}\t{cost_usd:.6f}\t{model}"
    learnings_store.file_locked_append(str(path), line)


# ---------------------------------------------------------------------------
# Small JSON state files (canary durable marker, per-day run summary)
# ---------------------------------------------------------------------------


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _default_canary_state() -> dict[str, Any]:
    return {"active_incidents": {}, "untested_versions_observed": {}, "reduce_failures": {}}


def record_canary_incident(slug: str, date: str, detail: str) -> None:
    """Durable marker (adrev-014 + the #753 handoff note): a schema_canary
    firing is easy to miss in a log line swallowed by an exit-tolerant
    chain (Epic 6's dream-daily.sh). Keyed by slug (latest incident wins)
    so a persistently-drifted slug does not pile up duplicate rows -- the
    banner stays loud until Epic 6 adds an explicit ack/clear action."""
    state = _read_json(canary_state_path(), _default_canary_state())
    state.setdefault("active_incidents", {})
    state["active_incidents"][slug] = {"date": date, "detail": detail}
    state["last_updated"] = _utc_now_iso()
    _write_json_atomic(canary_state_path(), state)


def record_untested_versions(untested_versions: list[str]) -> None:
    if not untested_versions:
        return
    state = _read_json(canary_state_path(), _default_canary_state())
    state.setdefault("untested_versions_observed", {})
    for v in untested_versions:
        state["untested_versions_observed"][v] = int(state["untested_versions_observed"].get(v, 0)) + 1
    state["last_updated"] = _utc_now_iso()
    _write_json_atomic(canary_state_path(), state)


def record_reduce_failure_incident(slug: str, date: str, detail: str) -> None:
    """Durable marker for a reduce-phase parse failure (#769 Stage-2 P1
    #1): when the reduce model never returns parseable JSON even after the
    retry nudge, main() aborts WITHOUT writing proposals or advancing
    watermarks for the planned slugs -- an abort that would otherwise only
    be visible as a stderr line an unattended launchd job never surfaces.
    Recorded in the SAME durable-incident file dream-digest.sh already
    renders as a loud banner (mirrors record_canary_incident's shape and
    per-slug, latest-incident-wins keying)."""
    state = _read_json(canary_state_path(), _default_canary_state())
    state.setdefault("reduce_failures", {})
    state["reduce_failures"][slug] = {"date": date, "detail": detail}
    state["last_updated"] = _utc_now_iso()
    _write_json_atomic(canary_state_path(), state)


# ---------------------------------------------------------------------------
# Candidate slug resolution (§3.3 `scopes`)
# ---------------------------------------------------------------------------


def resolve_candidate_slugs(cli_slugs: list[str] | None, cfg: dict[str, Any]) -> list[str]:
    """CLI --slugs > config `scopes` (non-empty) > auto-discovery via
    learnings_store.list_project_slugs(). `_global` is always excluded --
    it has no transcripts of its own to mine (arch-1: mining targets are
    real learnings-store project slugs, never the promotion-only scope)."""
    if cli_slugs:
        candidates = list(dict.fromkeys(cli_slugs))  # de-dup, preserve order
    else:
        scopes = cfg.get("scopes") or []
        if isinstance(scopes, list) and scopes:
            candidates = list(dict.fromkeys(scopes))
        else:
            candidates = learnings_store.list_project_slugs()
    return [s for s in candidates if s and s != GLOBAL_SLUG]


# ---------------------------------------------------------------------------
# Mining + preflight planning (arch-4)
# ---------------------------------------------------------------------------


def mine_due_slugs(
    slugs: list[str],
    *,
    cfg: dict[str, Any],
    projects_root: str | None,
    today: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Mine every candidate slug that has new transcripts since its
    watermark. Returns (bundles_by_slug, skip_reasons) -- skip_reasons maps
    a slug to a human-readable reason it was excluded (no due transcripts,
    or a schema_canary firing). Mining itself never costs money -- this
    runs for every candidate slug up front so the cost preflight has real
    bundle sizes to plan against."""
    watermark = tm.read_watermark()
    lookback_days = int(cfg.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    max_input_tokens = int(cfg.get("max_input_tokens", DEFAULT_MAX_INPUT_TOKENS))

    bundles: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}

    for slug in slugs:
        paths = tm.discover(
            [slug], since_watermark=watermark, projects_root=projects_root, lookback_days=lookback_days,
        )
        if not paths:
            skipped[slug] = "no due transcripts"
            continue
        try:
            bundle = tm.mine_to_evidence_bundle(paths, max_input_tokens=max_input_tokens)
        except SchemaDriftError as exc:
            detail = str(exc)
            print(f"dream_analyze: schema_canary fired for slug {slug!r}: {detail}", file=sys.stderr)
            record_canary_incident(slug, today, detail)
            skipped[slug] = "schema_canary fired"
            continue

        errors = validate_against_schema(bundle, _load_evidence_bundle_schema())
        if errors:
            # A trusted, just-built bundle failing its own schema is an
            # internal bug, not a data problem -- surface it loudly but do
            # not crash the whole night's run over one slug.
            print(
                f"dream_analyze: evidence bundle for slug {slug!r} failed schema validation: {errors}",
                file=sys.stderr,
            )
            skipped[slug] = "evidence bundle schema validation failed"
            continue

        record_untested_versions(bundle.get("canary", {}).get("untested_versions", []))
        bundles[slug] = bundle

    return bundles, skipped


def _load_evidence_bundle_schema() -> dict[str, Any]:
    path = _HERE / "evidence-bundle-schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_proposal_schema() -> dict[str, Any]:
    path = _HERE / "proposal-schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def order_due_slugs_by_watermark(due_slugs: list[str], watermark: dict[str, str]) -> list[str]:
    """LRU rotation (arch-4): least-recently-dreamed first. A slug with no
    watermark entry (never dreamed) sorts first (empty string sorts before
    any ISO 8601 timestamp)."""
    return sorted(due_slugs, key=lambda s: watermark.get(s, ""))


def _bundle_map_input_tokens(bundle: dict[str, Any], map_system_prompt: str) -> int:
    return int(bundle.get("token_estimate", 0)) + len(map_system_prompt) // 4


def plan_run(
    bundles: dict[str, dict[str, Any]],
    *,
    cfg: dict[str, Any],
    remaining_budget_usd: float,
    map_system_prompt: str,
    reduce_system_prompt: str,
    store_projection_token_estimate_fn,
) -> tuple[list[str], dict[str, Any]]:
    """Preflight cost planning (arch-4): decide, BEFORE any API call, which
    due slugs this run can afford. Walks slugs least-recently-dreamed
    first, adding one at a time, recomputing the FULL plan's estimated cost
    (every included slug's map call, worst-case at max_output_tokens, plus
    ONE reduce call whose input is the sum of those worst-case map outputs
    plus the store projection for the slugs included so far). Stops before
    adding a slug that would push the total over budget. Returns
    (planned_slugs, cost_breakdown)."""
    watermark = tm.read_watermark()
    ordered = order_due_slugs_by_watermark(list(bundles.keys()), watermark)

    map_model = cfg.get("map_model", DEFAULT_MAP_MODEL)
    reduce_model = cfg.get("reduce_model", DEFAULT_REDUCE_MODEL)
    max_output_tokens = int(cfg.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS))
    map_pricing = resolve_pricing(cfg, map_model)
    reduce_pricing = resolve_pricing(cfg, reduce_model)

    planned: list[str] = []
    map_cost_total = 0.0

    for slug in ordered:
        bundle = bundles[slug]
        this_map_input = _bundle_map_input_tokens(bundle, map_system_prompt)
        this_map_cost = estimate_call_cost_usd(this_map_input, max_output_tokens, map_pricing)

        trial_planned = planned + [slug]
        trial_map_cost_total = map_cost_total + this_map_cost
        trial_reduce_cost = _reduce_cost_estimate_for(trial_planned, max_output_tokens, store_projection_token_estimate_fn, reduce_pricing, reduce_system_prompt)
        trial_total = trial_map_cost_total + trial_reduce_cost

        if trial_total > remaining_budget_usd:
            break

        planned = trial_planned
        map_cost_total = trial_map_cost_total

    final_reduce_cost = _reduce_cost_estimate_for(planned, max_output_tokens, store_projection_token_estimate_fn, reduce_pricing, reduce_system_prompt)
    breakdown = {
        "ordered_candidates": ordered,
        "planned_slugs": planned,
        "estimated_map_cost_usd": round(map_cost_total, 6),
        "estimated_reduce_cost_usd": round(final_reduce_cost, 6),
        "estimated_total_cost_usd": round(map_cost_total + final_reduce_cost, 6),
        "remaining_budget_usd": round(remaining_budget_usd, 6),
    }
    return planned, breakdown


def _reduce_cost_estimate_for(planned, max_output_tokens, store_projection_token_estimate_fn, reduce_pricing, reduce_system_prompt) -> float:
    reduce_input = len(planned) * max_output_tokens + store_projection_token_estimate_fn(planned)
    reduce_input += len(reduce_system_prompt) // 4
    return estimate_call_cost_usd(reduce_input, max_output_tokens, reduce_pricing)


# ---------------------------------------------------------------------------
# Store projection (reduce input) -- reuses the already-tested
# learnings_store.search() ranking/budgeting rather than re-deriving
# projection logic here.
# ---------------------------------------------------------------------------


def build_store_projection(
    scopes: list[str], *, max_input_tokens: int
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, dict[str, Any]]]]:
    """Returns (payload, by_id). `payload` is the compact, JSON-serializable
    projection handed to the reduce call. `by_id` is project -> id -> full
    row, used for target_id resolution and the compaction guard's "old
    content" lookup. Built from the SAME learnings_store.search() results
    for both, so "what we told the model exists" and "what we accept as a
    valid target_id" can never diverge."""
    scopes = list(dict.fromkeys(scopes + [GLOBAL_SLUG]))
    per_scope_token_budget = max(200, (max_input_tokens // 4) // max(1, len(scopes)))

    payload: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for scope in scopes:
        rows = learnings_store.search(
            slug=scope,
            cross_project=False,
            max_results=200,
            token_budget=per_scope_token_budget,
            include_stale=True,
            include_superseded=False,
        )
        by_id[scope] = {r["id"]: r for r in rows}
        payload[scope] = [
            {
                "id": r["id"],
                "type": r.get("type"),
                "content": r.get("content"),
                "confidence": r.get("confidence"),
                "tags": r.get("tags", []),
                "key": r.get("key"),
            }
            for r in rows
        ]
    return payload, by_id


def _store_projection_token_estimate(scopes: list[str], *, max_input_tokens: int) -> int:
    payload, _ = build_store_projection(scopes, max_input_tokens=max_input_tokens)
    return len(json.dumps(payload, ensure_ascii=False)) // 4


# ---------------------------------------------------------------------------
# Messages API transport (curl, or offline canned-file replay)
# ---------------------------------------------------------------------------


class ApiCallError(RuntimeError):
    pass


def _extract_assistant_text(response: dict[str, Any]) -> str:
    if not isinstance(response, dict):
        return ""
    content = response.get("content")
    if not isinstance(content, list):
        return ""
    parts = []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
            parts.append(c["text"])
    return "".join(parts)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _call_curl_with_retry(
    *, api_url: str, api_key: str, model: str, system_prompt: str, user_content: str, max_output_tokens: int,
) -> dict[str, Any]:
    """POST to the Messages API via curl, with bounded 429 retry-with-backoff
    (bizlogic-009). Raises ApiCallError on any non-recoverable failure."""
    request_body = {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }
    payload = json.dumps(request_body)

    for attempt in range(MAX_429_RETRIES + 1):
        proc = subprocess.run(
            [
                "curl", "-s", "-S",
                "-H", f"x-api-key: {api_key}",
                "-H", f"anthropic-version: {ANTHROPIC_VERSION}",
                "-H", "content-type: application/json",
                "--max-time", "90",
                "-w", "\n%{http_code}",
                api_url,
                "--data-binary", "@-",
            ],
            input=payload,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise ApiCallError(f"curl failed (exit {proc.returncode}): {proc.stderr.strip()[:400]}")

        stdout = proc.stdout
        body, _, code = stdout.rpartition("\n")
        if code == "429":
            if attempt < MAX_429_RETRIES:
                delay = BACKOFF_SCHEDULE_SECONDS[min(attempt, len(BACKOFF_SCHEDULE_SECONDS) - 1)]
                print(f"dream_analyze: 429 from Messages API, retrying in {delay}s (attempt {attempt + 1})", file=sys.stderr)
                time.sleep(delay)
                continue
            raise ApiCallError("Messages API returned 429 after exhausting retries")
        if code != "200":
            raise ApiCallError(f"Messages API returned HTTP {code}: {body.strip()[:400]}")

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ApiCallError(f"Messages API response was not valid JSON: {exc}") from exc

    raise ApiCallError("Messages API call did not complete")  # pragma: no cover - unreachable


def _read_offline_response(fixture_dir: Path, *candidates: str) -> dict[str, Any]:
    """Read the first existing fixture file among `candidates` (in order)
    from `fixture_dir`. Never touches the network or curl."""
    for name in candidates:
        path = fixture_dir / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    print(
        f"dream_analyze: no offline fixture found among {list(candidates)} in {fixture_dir}; "
        "treating as an empty response",
        file=sys.stderr,
    )
    return {"content": [{"type": "text", "text": "{}"}], "usage": {"input_tokens": 0, "output_tokens": 0}}


def get_model_response(
    *,
    model: str,
    system_prompt: str,
    user_obj: dict[str, Any],
    max_output_tokens: int,
    api_key: str | None,
    api_url: str,
    offline_dir: Path | None,
    offline_candidates: tuple[str, ...],
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """Returns (parsed_json_object_or_None, usage). Shared by map and
    reduce -- identical transport, different prompt/payload/parse target."""
    user_content = json.dumps(user_obj, ensure_ascii=False)
    if offline_dir is not None:
        response = _read_offline_response(offline_dir, *offline_candidates)
    else:
        response = _call_curl_with_retry(
            api_url=api_url, api_key=api_key or "", model=model, system_prompt=system_prompt,
            user_content=user_content, max_output_tokens=max_output_tokens,
        )
    usage = response.get("usage") if isinstance(response, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    usage_out = {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
    }
    text = _extract_assistant_text(response)
    parsed = _parse_json_object(text)
    return parsed, usage_out


# ---------------------------------------------------------------------------
# Map phase
# ---------------------------------------------------------------------------

_VALID_CANDIDATE_TYPES = learnings_store.VALID_TYPES


def _validate_map_candidate(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("type") not in _VALID_CANDIDATE_TYPES:
        return None
    content = raw.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    evidence = raw.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return None
    clean_evidence = []
    for e in evidence:
        if isinstance(e, dict) and isinstance(e.get("excerpt"), str) and e.get("excerpt").strip():
            clean_evidence.append({"session_id": e.get("session_id"), "excerpt": e["excerpt"]})
    if not clean_evidence:
        return None
    return {
        "type": raw["type"],
        "content": content,
        "evidence": clean_evidence,
        "occurrence_count": raw.get("occurrence_count") if isinstance(raw.get("occurrence_count"), int) else len(clean_evidence),
        "notes": raw.get("notes") if isinstance(raw.get("notes"), str) else None,
    }


def run_map(
    slug: str,
    bundle: dict[str, Any],
    *,
    cfg: dict[str, Any],
    map_system_prompt: str,
    api_key: str | None,
    api_url: str,
    offline_dir: Path | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    max_output_tokens = int(cfg.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS))
    parsed, usage = get_model_response(
        model=cfg.get("map_model", DEFAULT_MAP_MODEL),
        system_prompt=map_system_prompt,
        user_obj=bundle,
        max_output_tokens=max_output_tokens,
        api_key=api_key,
        api_url=api_url,
        offline_dir=offline_dir,
        offline_candidates=(f"map-{slug}.json", "map-default.json"),
    )
    if parsed is None:
        print(f"dream_analyze: map response for slug {slug!r} was not parseable JSON; treating as empty", file=sys.stderr)
        return [], usage
    raw_candidates = parsed.get("candidates")
    if not isinstance(raw_candidates, list):
        return [], usage
    candidates = [c for c in (_validate_map_candidate(r) for r in raw_candidates) if c is not None]
    return candidates, usage


# ---------------------------------------------------------------------------
# Reduce phase
# ---------------------------------------------------------------------------


def run_reduce(
    map_results: dict[str, list[dict[str, Any]]],
    store_projection: dict[str, list[dict[str, Any]]],
    *,
    cfg: dict[str, Any],
    reduce_system_prompt: str,
    api_key: str | None,
    api_url: str,
    offline_dir: Path | None,
    instructions: str | None,
) -> tuple[list[dict[str, Any]], dict[str, int], bool]:
    """Returns (raw_proposals, usage, ok). `ok` is False ONLY when the
    reduce phase never obtained a parseable {"proposals": [...]} object,
    even after the one JSON-only retry nudge (#769 Stage-2 P1 #1) -- the
    caller MUST treat that as a failed run (no watermark advance, no
    proposals write) rather than a legitimate zero-proposal night, since
    both attempts fail identically and deterministically when the model's
    output truncates against max_output_tokens."""
    max_output_tokens = int(cfg.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS))
    user_obj: dict[str, Any] = {
        "map_candidates": [{"slug": slug, "candidates": cands} for slug, cands in map_results.items()],
        "store_projection": store_projection,
    }
    if instructions:
        user_obj["instructions"] = instructions

    parsed, usage = get_model_response(
        model=cfg.get("reduce_model", DEFAULT_REDUCE_MODEL),
        system_prompt=reduce_system_prompt,
        user_obj=user_obj,
        max_output_tokens=max_output_tokens,
        api_key=api_key,
        api_url=api_url,
        offline_dir=offline_dir,
        offline_candidates=("reduce.json",),
    )
    total_usage = dict(usage)

    if parsed is None or not isinstance(parsed.get("proposals"), list):
        # Retry once with a "return only JSON" nudge (spec: reduce phase
        # only -- map failures are treated as empty, no retry).
        print("dream_analyze: reduce response was not parseable JSON; retrying once with a JSON-only nudge", file=sys.stderr)
        nudge_obj = dict(user_obj)
        nudge_obj["_retry_note"] = (
            "Your previous response could not be parsed as JSON. Return ONLY the JSON "
            "object described in the system prompt -- no commentary, no code fences."
        )
        parsed, usage2 = get_model_response(
            model=cfg.get("reduce_model", DEFAULT_REDUCE_MODEL),
            system_prompt=reduce_system_prompt,
            user_obj=nudge_obj,
            max_output_tokens=max_output_tokens,
            api_key=api_key,
            api_url=api_url,
            offline_dir=offline_dir,
            offline_candidates=("reduce-retry.json", "reduce.json"),
        )
        total_usage["input_tokens"] += usage2.get("input_tokens", 0)
        total_usage["output_tokens"] += usage2.get("output_tokens", 0)
        if parsed is None or not isinstance(parsed.get("proposals"), list):
            print(
                "dream_analyze: reduce response still unparseable after retry; the mined+mapped "
                "evidence for this run is NOT consumed (see the reduce-failure handling in main())",
                file=sys.stderr,
            )
            return [], total_usage, False

    raw_proposals = [p for p in parsed["proposals"] if isinstance(p, dict)]
    return raw_proposals, total_usage, True


# ---------------------------------------------------------------------------
# Proposal finalization: validate, sanitize (sec-3), fingerprint, breadth
# marker (adrev-009/adrev-405), compaction guard (sec-11), schema-validate.
# ---------------------------------------------------------------------------


def _compute_fingerprint(kind: str, project: str, key_basis: str) -> str:
    return hashlib.sha256(f"{kind}:{project}:{key_basis}".encode("utf-8")).hexdigest()


def finalize_proposal(
    raw: dict[str, Any],
    *,
    store_by_id: dict[str, dict[str, dict[str, Any]]],
    cfg: dict[str, Any],
    proposal_schema: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (row, None) on success or (None, reason) on rejection. Never
    raises on malformed model output -- a bad proposal is dropped with a
    reason, not a crash."""
    kind = raw.get("kind")
    if kind not in VALID_PROPOSAL_KINDS:
        return None, f"invalid kind: {kind!r}"

    project = raw.get("project")
    if not isinstance(project, str) or not project.strip():
        return None, "missing/invalid project"

    target_id = raw.get("target_id")
    content = raw.get("content")
    type_ = raw.get("type")

    if kind in KINDS_REQUIRING_TARGET:
        if not isinstance(target_id, str) or not target_id:
            return None, f"{kind} requires a non-null target_id"
        if target_id not in store_by_id.get(project, {}):
            return None, f"target_id {target_id!r} does not resolve in the store projection for project {project!r}"
    else:
        # learning_add never carries a target, so it never gets the
        # project-membership check the other four kinds get for free via
        # target_id resolution above (#769 Stage-1 concern 1 / arch-1
        # defense-in-depth: "never let a wrong slug reach a proposal" was
        # enforced by prompt instruction alone for this one kind). Reject
        # any project the reduce phase was not actually given a store
        # projection for -- store_by_id's keys are EXACTLY
        # planned_slugs union {GLOBAL_SLUG} (see build_store_projection()).
        target_id = None
        if project not in store_by_id:
            return None, f"learning_add project {project!r} is not a known project scope"

    if kind in KINDS_REQUIRING_CONTENT:
        if not isinstance(content, str) or not content.strip():
            return None, f"{kind} requires non-empty content"
        if type_ not in learnings_store.VALID_TYPES:
            return None, f"{kind} requires a valid type, got {type_!r}"
    else:
        content = None
        type_ = None

    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not (1 <= confidence <= 10):
        return None, f"invalid confidence: {confidence!r}"
    confidence = int(confidence)

    evidence_raw = raw.get("evidence")
    if not isinstance(evidence_raw, list) or not evidence_raw:
        return None, "evidence must be a non-empty list"
    evidence = []
    for e in evidence_raw:
        if isinstance(e, dict) and isinstance(e.get("excerpt"), str) and e["excerpt"].strip():
            # sec-3 (#769 Stage-2 P1): the prompts instruct the reduce
            # model to reuse `excerpt` verbatim -- already redacted
            # upstream by the transcript miner -- rather than paraphrase
            # it like content/justification, so this was previously the
            # one written proposal field that skipped sanitize_content().
            # That exemption was enforced by prompt compliance alone, with
            # no code-level check that a written excerpt is actually
            # byte-identical to its source, and the reduce phase is a
            # second LLM hop that re-emits its own evidence array. Treat
            # it like every other free-text field at the write path; a
            # genuinely verbatim, already-redacted excerpt is unaffected
            # (sanitize_content is a no-op unless it matches an
            # injection-shaped pattern).
            evidence.append({
                "session_id": e.get("session_id"),
                "excerpt": learnings_store.sanitize_content(e["excerpt"]),
            })
    if not evidence:
        return None, "evidence contained no usable excerpts"

    justification = raw.get("justification")
    if not isinstance(justification, str) or not justification.strip():
        return None, "missing/invalid justification"

    prevalence_raw = raw.get("prevalence")
    if prevalence_raw is None:
        distinct_sessions = len({e["session_id"] for e in evidence if e.get("session_id")})
        prevalence = {"sessions": max(distinct_sessions, 1), "agents": 1}
    elif (
        isinstance(prevalence_raw, dict)
        and isinstance(prevalence_raw.get("sessions"), int)
        and not isinstance(prevalence_raw.get("sessions"), bool)
        and isinstance(prevalence_raw.get("agents"), int)
        and not isinstance(prevalence_raw.get("agents"), bool)
        and prevalence_raw["sessions"] >= 0
        and prevalence_raw["agents"] >= 0
    ):
        prevalence = {"sessions": prevalence_raw["sessions"], "agents": prevalence_raw["agents"]}
    else:
        return None, f"invalid prevalence: {prevalence_raw!r}"

    # Sanitize every model-influenceable free-text field BEFORE it is ever
    # written to disk (sec-3) -- nothing downstream (digest, /dream-apply,
    # a human) reads this row before sanitization.
    sanitized_content = learnings_store.sanitize_content(content) if content else None
    sanitized_justification = learnings_store.sanitize_content(justification)

    if sanitized_content:
        # learning_add / learning_supersede: the proposed content itself is
        # the correct dedup key -- a re-run with the SAME proposed change
        # collides with itself (idempotent), and a DIFFERENT proposed
        # change for the same target gets its own fingerprint via its own
        # content hash.
        key_basis = learnings_store.content_sha256(sanitized_content)
    else:
        # learning_verify / learning_contradict / learning_deprecate carry
        # no content -- they act on target_id alone. A bare target_id key
        # (#769 Stage-2 P1) permanently defines the FIRST verify/
        # contradict fingerprint ever written for a target: every later
        # night's re-verification or re-contradiction of the same target,
        # however different its supporting evidence, collides with that
        # first row and is silently deduped forever across every prior
        # proposals/*.jsonl file (existing_fingerprints() has no expiry) --
        # the opposite of the store's own repeated-reinforcement design
        # (self-improving/rules/learnings-store.md: "Each successful
        # reuse... slightly boosts effective confidence and refreshes
        # last_verified"). Fold in a component that varies with the
        # supporting evidence (distinct session ids + the sanitized
        # justification) so an identical re-run of the SAME inputs still
        # dedupes, but genuinely new evidence produces a new fingerprint.
        evidence_session_ids = sorted({e["session_id"] for e in evidence if e.get("session_id")})
        evidence_key = learnings_store.content_sha256(
            "|".join(evidence_session_ids) + "\n" + sanitized_justification
        )
        key_basis = f"{target_id or ''}:{evidence_key}"
    fingerprint = _compute_fingerprint(kind, project, key_basis)

    row: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "project": project,
        "target_id": target_id,
        "content": sanitized_content,
        "type": type_,
        "confidence": confidence,
        "prevalence": prevalence,
        "evidence": evidence,
        "justification": sanitized_justification,
        "fingerprint": fingerprint,
        "generated_at": _utc_now_iso(),
        "status": "pending",
    }

    # Breadth marker (adrev-009/adrev-405): under-prevalence `_global`
    # proposals are downgraded to a visible marker, never dropped. The
    # marker points at /dream-apply (its accept path IS promote_to_global())
    # -- never at the CCGM_LEARNINGS_ADMIN terminal hatch.
    if project == GLOBAL_SLUG:
        min_sessions = int(cfg.get("promotion_min_sessions", DEFAULT_PROMOTION_MIN_SESSIONS))
        min_agents = int(cfg.get("promotion_min_agents", DEFAULT_PROMOTION_MIN_AGENTS))
        if prevalence["sessions"] < min_sessions or prevalence["agents"] < min_agents:
            row["needs_manual_promotion"] = (
                f"sessions={prevalence['sessions']}, agents={prevalence['agents']} -- breadth gate "
                f"(sessions>={min_sessions}, agents>={min_agents}) not met; promote via /dream-apply if warranted"
            )

    # Compaction guard (sec-11): a learning_supersede that would silently
    # drop fact-bearing tokens from the target's current content is flagged,
    # not applied-as-normal.
    if kind == "learning_supersede":
        old_row = store_by_id.get(project, {}).get(target_id, {})
        old_content = old_row.get("content", "")
        ok, dropped = learnings_store.compact_preserves_facts(old_content, sanitized_content or "")
        if not ok:
            row["compaction_guard_failed"] = {"dropped_tokens": dropped}

    errors = validate_against_schema(row, proposal_schema)
    if errors:
        return None, f"proposal-schema validation failed: {errors}"

    return row, None


# ---------------------------------------------------------------------------
# Fingerprint dedup across prior proposal files (--force-day excludes its
# own target-day file from the corpus -- adrev-013)
# ---------------------------------------------------------------------------


def existing_fingerprints(exclude_path: Path | None = None) -> set[str]:
    seen: set[str] = set()
    pdir = proposals_dir()
    if not pdir.is_dir():
        return seen
    for path in sorted(pdir.glob("*.jsonl")):
        if exclude_path is not None and path.resolve() == exclude_path.resolve():
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    fp = row.get("fingerprint") if isinstance(row, dict) else None
                    if fp:
                        seen.add(fp)
        except OSError:
            continue
    return seen


# ---------------------------------------------------------------------------
# Proposals file write
# ---------------------------------------------------------------------------


def write_proposals(rows: list[dict[str, Any]], target_path: Path, *, overwrite: bool) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite:
        tmp = target_path.with_suffix(target_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        tmp.replace(target_path)
    else:
        for row in rows:
            learnings_store.file_locked_append(str(target_path), json.dumps(row, sort_keys=True))


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CCGM dreaming: nightly map->reduce analyzer (Epic 3).")
    p.add_argument("--force-day", metavar="YYYY-MM-DD", help="overwrite exactly this day's proposals file; excluded from the dedup corpus (adrev-013)")
    p.add_argument("--offline", metavar="DIR", help="read canned Messages API responses from DIR instead of calling curl")
    p.add_argument("--dry-run", action="store_true", help="compute the full plan and print a summary; write nothing")
    p.add_argument("--slugs", metavar="A,B,C", help="comma-separated project slugs to consider (overrides config `scopes` / auto-discovery)")
    p.add_argument("--projects-root", metavar="DIR", help="override the transcript discovery root (default ~/.claude/projects)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    load_env()
    cfg = load_config()

    if not cfg.get("enabled", True):
        print("dream_analyze: disabled (enabled: false in config.json)", file=sys.stderr)
        return 0

    offline_dir = Path(args.offline).resolve() if args.offline else None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if offline_dir is None and not api_key:
        print("dream_analyze: ANTHROPIC_API_KEY not set; skipping (local-only deployment is fine).", file=sys.stderr)
        return 0

    today = args.force_day or today_iso()
    cli_slugs = [s.strip() for s in args.slugs.split(",") if s.strip()] if args.slugs else None

    candidate_slugs = resolve_candidate_slugs(cli_slugs, cfg)
    if not candidate_slugs:
        print("dream_analyze: no candidate project slugs (nothing configured, nothing auto-discovered); nothing to do.", file=sys.stderr)
        return 0

    bundles, skip_reasons = mine_due_slugs(
        candidate_slugs, cfg=cfg, projects_root=args.projects_root, today=today,
    )
    if not bundles:
        print(f"dream_analyze: no due transcripts across {len(candidate_slugs)} candidate slug(s); nothing to do.", file=sys.stderr)
        return 0

    daily_cap = float(cfg.get("daily_cost_cap_usd", DEFAULT_DAILY_COST_CAP_USD))
    spent_today = 0.0 if offline_dir is not None else _read_cost_spent_today(cost_log_path(), today)
    remaining_budget = daily_cap - spent_today

    map_system_prompt = (_HERE / "dreaming-prompt-map.md").read_text(encoding="utf-8")
    reduce_system_prompt = (_HERE / "dreaming-prompt-reduce.md").read_text(encoding="utf-8")
    max_input_tokens = int(cfg.get("max_input_tokens", DEFAULT_MAX_INPUT_TOKENS))

    def _proj_tokens(scopes: list[str]) -> int:
        return _store_projection_token_estimate(scopes, max_input_tokens=max_input_tokens) if scopes else 0

    planned_slugs, cost_breakdown = plan_run(
        bundles, cfg=cfg, remaining_budget_usd=remaining_budget,
        map_system_prompt=map_system_prompt, reduce_system_prompt=reduce_system_prompt,
        store_projection_token_estimate_fn=_proj_tokens,
    )

    if not planned_slugs:
        print(
            f"dream_analyze: daily cost cap reached (spent ${spent_today:.4f} of ${daily_cap:.4f}; "
            f"even the cheapest due slug's estimated cost exceeds the remaining ${remaining_budget:.4f} budget); "
            "skipping this run.",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "date": today,
            "candidate_slugs": candidate_slugs,
            "skip_reasons": skip_reasons,
            "cost_breakdown": cost_breakdown,
        }, indent=2, sort_keys=True))
        return 0

    api_url = os.environ.get("CCGM_DREAMING_API_URL", DEFAULT_API_URL)

    # Neither this loop's run_map() call nor run_reduce() below is wrapped
    # in a try/except around ApiCallError: a transport failure partway
    # through aborts main() before the watermark-advance loop, discarding
    # already-paid-for map results with no partial credit (a retry re-mines
    # slug 1 from scratch). This is a deliberate fail-safe-over-fail-lossy
    # tradeoff (#769 Stage-2 Recommend, accepted as-is) -- it never falsely
    # advances a watermark, unlike the reduce-parse-failure case handled
    # below, so it does not share that case's data-loss property.
    map_results: dict[str, list[dict[str, Any]]] = {}
    total_input_tokens = 0
    total_output_tokens = 0
    map_calls = 0
    for slug in planned_slugs:
        candidates, usage = run_map(
            slug, bundles[slug], cfg=cfg, map_system_prompt=map_system_prompt,
            api_key=api_key, api_url=api_url, offline_dir=offline_dir,
        )
        map_results[slug] = candidates
        map_calls += 1
        total_input_tokens += usage["input_tokens"]
        total_output_tokens += usage["output_tokens"]
        if offline_dir is None:
            cost = estimate_call_cost_usd(usage["input_tokens"], usage["output_tokens"], resolve_pricing(cfg, cfg.get("map_model", DEFAULT_MAP_MODEL)))
            _append_cost(cost_log_path(), today, usage["input_tokens"], usage["output_tokens"], cost, cfg.get("map_model", DEFAULT_MAP_MODEL))

    total_candidates = sum(len(c) for c in map_results.values())
    raw_proposals: list[dict[str, Any]] = []
    reduce_calls = 0
    reduce_ok = True
    store_payload: dict[str, list[dict[str, Any]]] = {}
    store_by_id: dict[str, dict[str, dict[str, Any]]] = {}

    if total_candidates > 0:
        store_payload, store_by_id = build_store_projection(planned_slugs, max_input_tokens=max_input_tokens)
        instructions = None
        if instructions_path().is_file():
            try:
                instructions = instructions_path().read_text(encoding="utf-8").strip() or None
            except OSError:
                instructions = None

        raw_proposals, usage, reduce_ok = run_reduce(
            map_results, store_payload, cfg=cfg, reduce_system_prompt=reduce_system_prompt,
            api_key=api_key, api_url=api_url, offline_dir=offline_dir, instructions=instructions,
        )
        reduce_calls = 1
        total_input_tokens += usage["input_tokens"]
        total_output_tokens += usage["output_tokens"]
        if offline_dir is None:
            cost = estimate_call_cost_usd(usage["input_tokens"], usage["output_tokens"], resolve_pricing(cfg, cfg.get("reduce_model", DEFAULT_REDUCE_MODEL)))
            _append_cost(cost_log_path(), today, usage["input_tokens"], usage["output_tokens"], cost, cfg.get("reduce_model", DEFAULT_REDUCE_MODEL))
    else:
        # Still build a store_by_id so finalize_proposal has somewhere
        # consistent to look up against, even though there is nothing to
        # reduce -- keeps the code path uniform for the (empty) loop below.
        store_by_id = {}

    if not reduce_ok:
        # Reduce phase never produced parseable output, even after the
        # retry nudge (#769 Stage-2 P1 #1: both attempts fail identically
        # and deterministically when the model's output truncates against
        # max_output_tokens). The mined + mapped evidence for every
        # planned slug is real, already-paid-for work; consuming it
        # requires a parseable reduce response, so on failure:
        #   - do NOT advance any watermark (the mined evidence would be
        #     permanently lost -- it would never be re-mined);
        #   - do NOT write or overwrite the target day's proposals file
        #     (an existing valid file, e.g. under --force-day, must
        #     survive a failed re-run instead of being silently wiped);
        #   - record a durable, digest-visible marker so the loss is
        #     visible instead of a stderr line an unattended launchd job
        #     will not surface;
        #   - exit non-zero.
        detail = "reduce phase produced no parseable proposal array, even after the retry nudge"
        for slug in planned_slugs:
            record_reduce_failure_incident(slug, today, detail)
        run_summary = {
            "date": today,
            "generated_at": _utc_now_iso(),
            "offline": offline_dir is not None,
            "candidate_slugs": candidate_slugs,
            "slugs_considered": list(bundles.keys()),
            "slugs_planned": planned_slugs,
            "skip_reasons": skip_reasons,
            "map_calls": map_calls,
            "reduce_calls": reduce_calls,
            "proposals_written": 0,
            "proposals_rejected": 0,
            "proposals_deduped": 0,
            "reduce_failed": True,
            "reduce_failure_detail": detail,
            "cost_breakdown": cost_breakdown,
            "actual_input_tokens": total_input_tokens,
            "actual_output_tokens": total_output_tokens,
            "untested_versions": [],
        }
        runs_dir().mkdir(parents=True, exist_ok=True)
        _write_json_atomic(runs_dir() / f"{today}.json", run_summary)
        print(
            f"dream_analyze: {detail}; NOT writing proposals or advancing watermarks for "
            f"{len(planned_slugs)} planned slug(s) -- see state/canary.json (reduce_failures).",
            file=sys.stderr,
        )
        return 1

    proposal_schema = _load_proposal_schema()
    target_path = proposals_dir() / f"{today}.jsonl"
    dedup_corpus = existing_fingerprints(exclude_path=target_path if args.force_day else None)

    written_rows: list[dict[str, Any]] = []
    rejected = 0
    deduped = 0
    for raw in raw_proposals:
        row, reason = finalize_proposal(raw, store_by_id=store_by_id, cfg=cfg, proposal_schema=proposal_schema)
        if row is None:
            rejected += 1
            print(f"dream_analyze: dropped proposal: {reason}", file=sys.stderr)
            continue
        if row["fingerprint"] in dedup_corpus:
            deduped += 1
            continue
        dedup_corpus.add(row["fingerprint"])
        written_rows.append(row)

    write_proposals(written_rows, target_path, overwrite=bool(args.force_day))

    for slug in planned_slugs:
        sessions = bundles[slug].get("sessions", [])
        timestamps = [s.get("ended_at") or s.get("started_at") for s in sessions]
        timestamps = [t for t in timestamps if t]
        if timestamps:
            tm.write_watermark(slug, max(timestamps))

    untested_versions = sorted({
        v for slug in planned_slugs for v in bundles[slug].get("canary", {}).get("untested_versions", [])
    })

    run_summary = {
        "date": today,
        "generated_at": _utc_now_iso(),
        "offline": offline_dir is not None,
        "candidate_slugs": candidate_slugs,
        "slugs_considered": list(bundles.keys()),
        "slugs_planned": planned_slugs,
        "skip_reasons": skip_reasons,
        "map_calls": map_calls,
        "reduce_calls": reduce_calls,
        "proposals_written": len(written_rows),
        "proposals_rejected": rejected,
        "proposals_deduped": deduped,
        "cost_breakdown": cost_breakdown,
        "actual_input_tokens": total_input_tokens,
        "actual_output_tokens": total_output_tokens,
        "untested_versions": untested_versions,
    }
    runs_dir().mkdir(parents=True, exist_ok=True)
    _write_json_atomic(runs_dir() / f"{today}.json", run_summary)

    print(json.dumps({k: run_summary[k] for k in ("date", "proposals_written", "proposals_rejected", "proposals_deduped", "map_calls", "reduce_calls")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
