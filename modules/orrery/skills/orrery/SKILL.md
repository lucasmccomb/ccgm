---
name: orrery
description: >
  Deep-dives a codebase with parallel read-only scout agents and generates an interactive,
  zoomable, embeddable system-design map as a single self-contained HTML file - file-level
  GitHub links pinned to an anchor SHA, external systems, and per-node product-context
  prose. /orrery (no argument) maps the repo you are currently in; /orrery update refreshes
  an existing map incrementally.
disable-model-invocation: true
---

# /orrery - build a system map of a codebase

Six stages around one latent step: anchor (deterministic) -> enumerate (deterministic) ->
investigate (scout fan-out - the only latent stage) -> merge/emit/validate (deterministic) ->
render + report (deterministic) -> teardown (deterministic, ALWAYS runs). Every deterministic
stage is a script under `scripts/`; this skill orchestrates the scripts and the scout waves
and never re-implements what a script owns.

## Hard rules (read before step 1)

- **Every pack dispatch uses the `orrery-scout` agent type** (`agents/orrery-scout.md`) -
  never any other agent type (not Explore, not general-purpose). The scout's restricted
  toolset (Read/Grep/Glob only; no Bash, no Write, no network) is a security boundary
  against the untrusted target repo, not a convenience default. This includes the fixer
  scouts in step 6. There are no exceptions.
- **Teardown always runs** (step 8). Every exit path - success, BLOCKED, validation
  exhaustion, argument errors after the anchor succeeded, any early exit - ends with
  `anchor_repo.sh --teardown`. A run that leaves a worktree in the target repo is a failed
  run, whatever else it produced.
- **Never render an invalid model.** `scripts/validate_map.py` exiting 0 is the
  precondition for step 7. `likec4 build` always exits 0 and is never a gate.
- The pack briefs, budgets, and the published-id contract live in `references/packs.md`;
  the fragment contract is `references/fragment.schema.json`. Read both before step 5.

## Step 1 - parse `$ARGUMENTS`

`[<repo-path-or-name>] [update] [--vision <file>] [--out <dir>]`

- **No argument (the primary form)**: the target is the repo containing the current working
  directory - `git rev-parse --show-toplevel`. If the cwd is not inside a git repo, stop with
  guidance: "run /orrery inside the repo you want mapped, or pass a path: /orrery <repo-path>".
- **Explicit argument**: a path that exists is used as-is; a bare name tries `~/code/{name}`;
  otherwise stop with the same guidance.
- **`update` keyword**: route to the update flow (the "Update flow" section at the
  bottom) instead of the build steps below.
- **`--vision <file>`**: a LOCAL file only - never fetched. If the value looks like a URL,
  stop with an error; do not download anything.
- **`--out <dir>`**: output directory for this map. Default: `$ORRERY_HOME/{slug}` where
  `ORRERY_HOME` defaults to `~/code/orrery`. Honor `$ORRERY_HOME` whenever `--out` is not
  given - the root must be overridable without editing this module.

## Step 2 - anchor

```
bash scripts/anchor_repo.sh <repo-path>
```

Capture stdout and parse the single-line JSON: `repo_path`, `remote_url`
(credential-stripped), `default_ref`, `anchor_sha`, `worktree`, `slug`, `behind` (an integer,
or `null` when the commit count could not be determined), `dirty`, `no_remote`, `visibility`.

- **Exit 2** (unreachable repo, fetch failure, unsanitizable slug): stop and report the
  script's error. Nothing was created, so no teardown is owed yet.
- **Success**: from this moment the teardown obligation exists - record `<repo-path>` and
  `<worktree>` so step 8 can always run, even if a later step fails.
- **`dirty` true, or `behind` a positive count**: proceed - the build runs against the pinned
  anchor, not the working tree - and state the fact in the report (step 9).
- **`behind` is `null`**: proceed the same way, but never treat this as "not behind" - the
  count is undetermined, not zero. Report it as such in step 9.
- **Surface `visibility` immediately** to the user (`public` / `private` / `unknown`). For
  `private` or `unknown`, say now that the report will carry a do-not-publish-without-review
  warning.

Resolve the out dir (`--out`, else `$ORRERY_HOME/{slug}` - the same root
`anchor_repo.sh` itself honors for the dir it creates), create it `chmod 700` if needed,
and save the anchor JSON to `$out/anchor.json`.

## Step 3 - enumerate + announce

```
python3 scripts/enumerate_repo.py --worktree <worktree> --out $out/census.json
```

If `enumerate_repo.py` exits nonzero: report BLOCKED with the script's error and run step 8
- it is a deterministic script, so a failure is an environment or contract bug, never
something to retry.

Read the census and announce the plan before any dispatch: N areas (and "N candidate areas
grouped into M buckets" when the census says `bucketed`), plus the wave layout (wave 0, then
ceil(N/8) area waves).

## Step 4 - vision context

- With `--vision`: read the local file and inline its content into the product-vision
  dispatch (the scout cannot read outside the worktree, so the orchestrator carries it in).
- Without it: the product-vision scout reads, inside the anchor worktree, `README.md`,
  `CLAUDE.md`, and up to 2 `docs/*.md` files - pass those paths in the brief; do not paste
  their contents.

## Step 5 - scout fan-out (wave 0, published ids, area waves)

**Pack naming (load-bearing)**: each census area `{area_id}` is dispatched as the pack
named `area-{area_id}` - census area `web` runs as pack `area-web` and persists to
`fragments/area-web.json`. The scout's `pack` field, the `packs.txt` line, the fragment
filename, and the `--packs` entry all carry that exact `area-` name (element ids keep the
bare `{area_id}__` prefix). The prefix is not cosmetic: `merge_fragments.py` keys its
deterministic `{area_id}__` namespace screen on the pack name starting with `area-` - a
bare pack name silently deactivates that screen.

**Before the first dispatch**: CLEAR `$out/fragments/` (delete and recreate - stale
fragments from an interrupted run must never survive into this build) and record the run's
planned pack list to `$out/packs.txt` (one pack per line: `product-vision`,
`external-systems`, then `area-{area_id}` per census area). Keep `packs.txt` current
through every split/give-up below; step 6 passes exactly this list to
`merge_fragments.py --packs`.

**Wave 0** - dispatch `product-vision` and `external-systems` in parallel, both as
`orrery-scout`, each with its brief from `references/packs.md`, the worktree path,
`$out/census.json`, and `references/fragment.schema.json`. The product-vision reply carries a
top-level `vision_brief` string (300-600 words) alongside the fragment fields; write it to
`$out/vision-brief.md`.

**Persisting a fragment (every pack, every wave)**: the scout's reply contains exactly one
fenced JSON code block (followed by the four-state status line). Parse it and check it
deterministically against the fragment contract: required fields, id pattern
`^[a-z][a-z0-9_]*$`, kind/relation enums, length caps, the per-fragment budget (max 40
elements / max 25 relations), the `pack` field equal to the dispatched pack name (for area
packs: `area-{area_id}`), and - for area packs - the `{area_id}__` prefix on every element
id, every `parent` either own-namespace or a published id, and every relation carrying at
least one own-namespace (`{area_id}__*`) endpoint with the other endpoint own-namespace or
a published id (either direction - a published id may sit at `from` or `to`; two published
endpoints is the violation). Valid: write it to `$out/fragments/{pack}.json`. A reply that
is missing the block, does not parse, or fails the contract is a failed dispatch.

**Published-id set** - after wave 0, resolve the exact id list area packs may attach to or
reference: `system` (the root system element's id), the product-vision `container` ids, the
`actor` ids, and every external-systems element id. Inject this list verbatim into every
area-pack prompt, alongside the path to `$out/vision-brief.md`.

**Area waves** - one `orrery-scout` per census area, in waves of at most 8, each with the
area brief (pack id `area-{area_id}`, element-id prefix `{area_id}__`, `root_paths`,
budget), the published-id set, the vision-brief path, the worktree path,
`$out/census.json`, and `references/fragment.schema.json`.

**Failure protocol (per pack)**:
1. First failure: re-dispatch the same brief ONCE.
2. Second failure: do NOT retry again - a truncated over-budget reply fails identically on a
   plain retry. SPLIT the area's `root_paths` in half and dispatch two packs with suffixed,
   pattern-legal area ids (`{area_id}_a` and `{area_id}_b`, so pack names
   `area-{area_id}_a` / `area-{area_id}_b` and element prefixes `{area_id}_a__` /
   `{area_id}_b__`), updating `packs.txt` (failed pack out, both halves in). Each half gets
   one dispatch plus one re-dispatch.
3. Only after a split half fails twice: proceed without it, remove it from `packs.txt`, and
   record the gap for the report.

Wave-0 packs are never skipped: if `product-vision` or `external-systems` still fails after
its re-dispatch, stop, report BLOCKED (the container tier and the published-id set are
load-bearing for every other pack), and run step 8.

## Step 6 - merge -> emit -> validate (bounded fix loop)

```
python3 scripts/merge_fragments.py \
  --fragments-dir $out/fragments \
  --packs <comma-separated list from packs.txt> \
  --census $out/census.json \
  --anchor $out/anchor.json \
  --out $out/model.json

python3 scripts/emit_likec4.py --model $out/model.json --out-dir $out

python3 scripts/validate_map.py \
  --model $out/model.json \
  --model-dir $out/model \
  --repo <repo-path> \
  --anchor-sha <anchor_sha>
```

Only a `validate_map.py` **exit 1** enters the fix loop - exit 1 is the code path that
freshly writes `errors.json` (exit 0 removes it). If `merge_fragments.py` or
`emit_likec4.py` itself exits nonzero, or validate exits with anything other than 0 or 1
(e.g. exit 2 on unreadable input): that is NOT an element-content error - report BLOCKED
immediately with the tool's stderr, run step 8, and never loop on it.

On validate exit 1, run the bounded fix loop - at most 3 iterations:

1. Read `errors.json`. Apply the deterministic fixes it names directly to the offending
   fragment files: drop a dangling relation, clamp an insane line range, drop a quarantined
   element.
2. For element-content errors a deterministic edit cannot fix: dispatch ONE fixer scout per
   iteration - an `orrery-scout` receiving `errors.json` plus the offending fragment(s),
   correcting only the named elements, returning the corrected fragment(s) in-reply.
3. Delete `errors.json`, then re-run merge -> emit -> validate. Deleting first makes a
   stale file impossible to mistake for a fresh verdict: after the re-run, an `errors.json`
   on disk is always the current iteration's.

After 3 failed iterations: STOP. Report BLOCKED with the `errors.json` path and the
remaining error list, run step 8, and never render the invalid model.

## Step 7 - render + state.json

```
bash scripts/render_map.sh $out <slug>
```

This builds via the pinned toolchain, renames `index.html` to `{slug}.html`, drops the
build's `404.html`/favicon leftovers, and asserts exactly one artifact remains:
`$out/dist/{slug}.html`. If `render_map.sh` (or the state.json write below) fails after a
green validate: report BLOCKED with the error and run step 8 - never retry-loop a render.

Then write `$out/state.json` ATOMICALLY (temp file + rename, never in place):

```
python3 - "$out" "<skill-dir>" <<'PY'
import json, os, sys, time
out, skill_dir = sys.argv[1], sys.argv[2]
anchor = json.load(open(os.path.join(out, "anchor.json")))
census = json.load(open(os.path.join(out, "census.json")))
model = json.load(open(os.path.join(out, "model.json")))
toolchain = json.load(open(os.path.join(skill_dir, "scripts/toolchain/package.json")))
state = {
    "schema_version": 1,
    "slug": anchor["slug"],
    "repo_path": anchor["repo_path"],
    "remote_url": anchor["remote_url"],
    "default_ref": anchor["default_ref"],
    "anchor_sha": anchor["anchor_sha"],
    "visibility": anchor["visibility"],
    "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "likec4_version": toolchain["dependencies"]["likec4"],
    "areas": census["areas"],
    "element_index": {e["id"]: [f["path"] for f in e.get("files", [])]
                      for e in model["elements"]},
    "artifact": "dist/%s.html" % anchor["slug"],
}
tmp = os.path.join(out, "state.json.tmp")
with open(tmp, "w") as fh:
    json.dump(state, fh, indent=2, sort_keys=True)
os.replace(tmp, os.path.join(out, "state.json"))
PY
```

(`<skill-dir>` = this skill's directory, so `likec4_version` is read from the pinned
`scripts/toolchain/package.json` - the single source for the toolchain version.)

## Step 8 - teardown (UNSKIPPABLE)

```
bash scripts/anchor_repo.sh --teardown <repo-path> <worktree>
```

Treat this as a finally block, not a final bullet: the obligation is created the moment
step 2 succeeds, and it is discharged on EVERY exit path - after step 9 on success, before
reporting BLOCKED in steps 5/6, and on any unexpected error. If you are about to end the
run for any reason and the anchor succeeded, run the teardown first. It is idempotent and
never fatal; run it even if you believe a partial cleanup already happened.

## Step 9 - report

State plainly, in this order:

- Artifact path (`$out/dist/{slug}.html`) and its byte size.
- Anchor SHA and default ref; whether the source repo was `dirty` or `behind` at anchor time,
  or - if `behind` was `null` - that the behind-count could not be determined (the map
  reflects the anchor, not the working tree).
- Repo visibility. For `private` or `unknown`: **"do not publish this artifact without
  review - the source repo is not public"** - place the warning directly beside the embed
  snippet below.
- Area count (with "N candidate areas grouped into M buckets" when the census bucketed),
  element count, relation count.
- Quarantined / withheld / dropped items from the merge report (`merge-report.json`, written
  beside `model.json` - e.g. "2 elements withheld: secret-shaped content"), and any area gaps
  from step 5's failure protocol.
- `source links: none (non-GitHub remote)` when the anchor's remote is not github.com.
- The open_questions rollup across all fragments.
- The embed snippet, with the L1 landing link: link `{slug}.html#/view/index/` as the
  landing URL (the artifact opens at `#/`, an overview grid - `#/view/index/` is the L1
  hero view):

```html
<iframe src="/maps/{slug}.html#/view/index/"
        sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
        style="width:100%;height:80vh;border:0" title="System map"></iframe>
```

  (No `allow-same-origin` - the artifact runs as an opaque origin. `allow-popups` +
  `allow-popups-to-escape-sandbox` are required or the map's GitHub deep links are dead.)
- The toolchain cache path and size (printed by `scripts/likec4.sh` during resolve).
- "Update later with `/orrery update <repo>`." If `--out` was non-default, add that the
  update must be given the same `--out` - the update flow searches only the resolved
  default otherwise.

## Rate-limit discipline

- Area waves are capped at 8 simultaneous scouts (sonnet, lean prompts - light agents).
- On a 429 (`Server is temporarily limiting requests`): stop launching, cool down 30-60s,
  then re-dispatch ONLY the failed packs in waves of at most 4. If it trips again, halve
  the wave size and double the cooldown. Never re-launch the whole burst.

## Update flow - `/orrery update`

`/orrery update [<repo>]` refreshes an existing map incrementally. Everything the hard
rules say about the build path holds here unchanged: every dispatch is an `orrery-scout`,
teardown always runs (including on the "up to date" stop), and an invalid model is never
rendered.

### U1 - anchor and locate the map

Resolve the target repo exactly as step 1, then run step 2 (anchor) as written - the
update flow anchors a worktree too, so **the teardown obligation starts here** and is
discharged on every exit path below. Resolve the out dir exactly as step 2:
`--out` if given, else `$ORRERY_HOME/{slug}`. If `$out/state.json` does not exist,
**STOP** (after step 8): report "no state.json at `$out/state.json` - a map built with a
custom `--out` needs that same `--out` passed to update; run `/orrery` (the build path)
to build here". An explicit update must never full-rebuild at a root it merely guessed -
that is exactly how a second divergent copy gets created (risk adrev2-014). The other
gate conditions (unparseable state, wrong schema_version, likec4_version mismatch -
where the root is right but the state is unusable) DO fall back to a full rebuild; U3
routes them.

### U2 - gate + diff (deterministic)

```
python3 scripts/diff_since.py \
  --repo <repo-path> \
  --state $out/state.json \
  --new-anchor <anchor_sha> \
  --out $out/diff.json
```

`scripts/diff_since.py` owns the whole deterministic decision: the state gate (no
state.json / unparseable / `schema_version` != 1 / `likec4_version` != the installed
toolchain version, which it reads from `scripts/toolchain/package.json` the same way
step 7 does), the history-rewrite check (old anchor resolvable AND an ancestor of the
new one), the unchanged short-circuit, and the rename-aware `git diff -M`
classification. It also updates renamed files' element anchors in place in the baseline
`$out/model.json`, so renames preserve element continuity without re-investigation.
A nonzero exit is an environment or contract bug: report BLOCKED with its stderr and
run step 8.

### U3 - route on diff.json (first match wins)

1. **`state_missing` true**: report the `stop_reason` verbatim (it names the resolved
   path that was searched and the `--out` mismatch cause), run step 8 (teardown), and
   STOP. Never rebuild here - see U1.
2. **`rebuild_required` true**: announce the `rebuild_reason` verbatim (it names which
   gate condition fired, or the clustering-material change), then run the full build -
   steps 3 through 9 exactly as written, reusing the anchor and worktree from U1.
3. **`history_rewritten` true**: announce "history rewritten - old anchor {sha} is
   unresolvable or not an ancestor of {new sha}; full rebuild", then run steps 3-9 the
   same way. Never guess-diff across rewritten history.
4. **`unchanged` true**: report "up to date (anchor {sha})" - zero agent dispatch, **but
   still run step 8 (teardown)**. The short-circuit skips the work, never the cleanup.
5. Otherwise: the patch path (U4).

### U4 - patch path

1. **Refresh the deterministic inputs**: overwrite `$out/anchor.json` with the U1 anchor
   JSON and re-run step 3's enumerate command to refresh `$out/census.json` (announce is
   not repeated; the census here feeds merge meta and the state writer).
2. **Build the re-run pack list from diff.json**: `product-vision` if
   `product_vision_flagged`, `external-systems` if `external_systems_flagged`, and
   `area-{area_id}` for every entry in `affected_areas` - the same load-bearing
   `area-{area_id}` pack naming as step 5. Overwrite `$out/packs.txt` with exactly this
   list; step U4.5 passes exactly it to `--packs`. If `affected_areas` names `misc` and
   state.json's `areas[]` has no misc entry, dispatch `area-misc` with
   `new_paths_routed_to_misc` as its root_paths (`misc` is a reserved, pattern-legal id).

   **Empty pack list = the no-dispatch fast path, not an error.** A patchable diff can
   legitimately affect zero packs - a pure same-area rename (continuity preserved by the
   re-anchor alone) or an anchor advance with an identical tree. Never call
   `merge_fragments.py` with an empty `--packs` (it exits 2 by contract). Instead: skip
   U4.3-U4.5 entirely; if `elements_reanchored` is non-empty, run emit -> validate ->
   render against the already re-anchored baseline `$out/model.json` (step 6 from the
   emit command on - its dispositions apply); if it is empty, keep the existing artifact
   untouched. Either way finish the flow - the atomic state.json advance (U4.6),
   teardown (U4.7) - and report "no packs affected; anchor advanced" with the
   re-anchored element count.
3. **Clear `$out/fragments/`** (delete and recreate - same hygiene as step 5), then
   dispatch ONLY the re-run packs as `orrery-scout`, waves of at most 8, wave-0 packs
   (if flagged) first. Briefs come from `references/packs.md` as in step 5; each area
   pack gets its recorded `root_paths` from state.json's `areas[]`, plus
   `new_paths_routed_to_misc` appended for the misc pack. The published-id set: resolve
   it **per wave-0 pack** - from that pack's re-run reply where it was re-run, else from
   the baseline `$out/model.json` (the `system` id, every `container` and `actor` id,
   and every element whose `source_packs` includes `external-systems`) - so re-running
   only external-systems never drops the baseline container/actor ids. Persist and
   check fragments exactly as step 5.
4. **Failure protocol (update mode)**: one re-dispatch per failed pack, then STOP
   retrying - do NOT split (a split's suffixed area ids would not match the baseline's
   pack namespaces, so its output could never replace the baseline). Keep the failed
   pack listed in `packs.txt`: `merge_fragments.py --patch` retains that pack's baseline
   elements when no valid fragment arrives (reported as
   `reinvestigation_failed_retained`) - the map must never silently shrink because one
   re-investigation failed. Record the retention for the report. This applies to wave-0
   packs too: a failed wave-0 re-run falls back to the baseline, it does not BLOCK.
5. **Patch-merge, emit, validate** - run step 6 with the merge command replaced by patch
   mode; everything else in step 6 (the BLOCKED dispositions for non-element errors, the
   bounded <=3 fix loop, one fixer scout per iteration, the delete-errors.json-first
   hygiene) applies verbatim, re-running THIS merge command each iteration:

```
python3 scripts/merge_fragments.py \
  --fragments-dir $out/fragments \
  --packs <comma-separated list from packs.txt> \
  --census $out/census.json \
  --anchor $out/anchor.json \
  --out $out/model.json \
  --patch --state $out/state.json --diff $out/diff.json
```

   (`--out` is both the baseline in and the patched model out. After 3 failed fix
   iterations: BLOCKED with the errors.json path, step 8, never render.)
6. **Render + state**: run step 7 exactly as written - render, then the atomic
   state.json write. It reads the refreshed anchor.json/census.json and the patched
   model.json, so the new anchor SHA and element index land atomically
   (temp file + rename, never in place).
7. **Teardown**: step 8, unskippable, as always.

### U5 - report the delta

Report the step 9 items (artifact, anchor, visibility warning, counts, embed snippet),
plus the update delta, computed from `$out/diff.json` and the `patch` section of
`merge-report.json`:

- Elements added / updated / removed (`baseline_elements_replaced`, `orphaned_deleted`,
  and the re-run fragments' contents).
- Renames preserved: each `renamed_paths` entry (`from -> to`) and the
  `elements_reanchored` ids whose anchors moved with them.
- Any packs retained from baseline after a failed re-investigation.
- The `open_questions` rollup from the re-run fragments.
