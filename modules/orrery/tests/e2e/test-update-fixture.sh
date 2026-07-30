#!/usr/bin/env bash
set -euo pipefail

# Update E2E (plan Epic 5): fixture-repo v1 -> full deterministic chain
# (anchor -> census -> merge -> emit -> validate -> render -> state.json) ->
# commit v2 changes (modify one api/ file, delete one web/ file, rename one
# db/ file) -> re-anchor -> diff_since -> patch-merge with canned updated
# fragments -> emit -> validate -> render -> assert:
#   - the new element's title is present in the artifact
#   - the deleted element's content is absent from artifact and model
#   - the renamed element is retained with its anchor updated to the new path
#   - state.json's anchor advanced atomically (no temp file left behind)
# Then two more cycles pin the empty-re-run-pack fast path (stage-2 finding 2):
#   v3 - pure same-area rename: zero packs to dispatch, NO merge call, render
#        from the re-anchored baseline, state advances
#   v4 - identical-tree anchor advance (allow-empty commit): zero packs, zero
#        re-anchors, artifact byte-identical, only state.json advances
#
# The whole run exercises the $ORRERY_HOME override (risk adrev2-014): the
# output root is redirected under this test's tempdir, asserted honored, and
# the real ~/code/orrery is never touched.
#
# Fixture materialization uses INDEX PLUMBING, never cp -R + git add: the
# fixture commits BOTH web/ and Web/, which case-insensitive filesystems fold
# into one physical dir, so a copy-based repo diverges per OS (same technique
# as test-ingest-fixture.sh / test-pipeline-fixture.sh). The v2 delta is also
# committed via index plumbing for the same reason.
#
# Injected-failure teardown probe: run with
#   ORRERY_UPDATE_TEST_INJECT_FAIL=post-anchor bash test-update-fixture.sh
# to simulate a mid-run crash right after the v2 anchor; the cleanup trap
# must still tear the anchor worktree down and remove every temp dir.
#
# Portable: macOS bash 3.2 + BSD tools.

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILL_DIR="$MODULE_DIR/skills/orrery"
SCRIPTS="$SKILL_DIR/scripts"
FRAGSRC="$MODULE_DIR/tests/fixtures/fragments"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

for s in anchor_repo.sh enumerate_repo.py diff_since.py merge_fragments.py emit_likec4.py validate_map.py render_map.sh; do
  [ -f "$SCRIPTS/$s" ] || fail "required script missing: scripts/$s"
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/orrery-update.XXXXXX")"
# Redirect the output root under the tempdir (912: the override must be
# honored end-to-end) so the real default root is never written.
export ORRERY_HOME="$WORK/orrery-home"
SLUG="orrery_update_fixture"
OUT="$ORRERY_HOME/$SLUG"
REPO=""
WORKTREE=""
DEFAULT_ROOT_PREEXISTS=0
[ -d "$HOME/code/orrery/$SLUG" ] && DEFAULT_ROOT_PREEXISTS=1

cleanup() {
  # Teardown FIRST (guarded, idempotent, never fatal): the anchor worktree
  # lives under anchor_repo.sh's own mktemp base in TMPDIR - OUTSIDE $WORK -
  # so an intermediate failure would otherwise strand a full checkout there.
  if [ -n "$WORKTREE" ] && [ -n "$REPO" ] && [ -d "$REPO" ]; then
    bash "$SCRIPTS/anchor_repo.sh" --teardown "$REPO" "$WORKTREE" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

# --- materialize the fixture repo (index plumbing) + local bare origin -------
REPO="$WORK/orrery-update-fixture"   # basename must keep matching $SLUG above
mkdir -p "$REPO"
GITC="git -C $REPO -c user.name=orrery -c user.email=orrery@example.invalid -c core.hooksPath=/dev/null"
$GITC init -q
CCGM_ROOT="$(cd "$MODULE_DIR/../.." && pwd)"
FIXPREFIX="modules/orrery/tests/fixtures/fixture-repo"
SRC_COUNT="$(git -C "$CCGM_ROOT" ls-files -- "$FIXPREFIX" | wc -l | tr -d ' ')"
[ "$SRC_COUNT" -gt 0 ] || fail "no fixture-repo entries in the ccgm index (this test must run from a ccgm checkout)"
TAB="$(printf '\t')"
git -C "$CCGM_ROOT" ls-files -s -- "$FIXPREFIX" | while IFS= read -r line; do
  # ls-files -s line shape: <mode> <sha> <stage><TAB><path>
  mode="${line%% *}"
  path="${line#*$TAB}"
  rel="${path#$FIXPREFIX/}"
  sha="$(git -C "$CCGM_ROOT" cat-file blob ":$path" | $GITC hash-object -w --stdin)"
  $GITC update-index --add --cacheinfo "$mode,$sha,$rel"
done
$GITC commit -qm "v1" --no-verify
$GITC branch -M main
git init -q --bare "$WORK/origin.git"
$GITC remote add origin "$WORK/origin.git"
$GITC push -q -u origin main
git -C "$WORK/origin.git" symbolic-ref HEAD refs/heads/main
echo "ok: fixture repo materialized case-exactly with local bare origin"

# --- helper: run anchor_repo.sh and persist the parsed JSON ------------------
# Writes the anchor JSON to $OUT/anchor.json and prints "slug<TAB>sha<TAB>wt".
parse_anchor() {
  python3 - "$1" "$OUT/anchor.json" <<'PYEOF'
import json
import sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
obj = None
for ln in reversed(lines):
    ln = ln.strip()
    if not ln.startswith("{"):
        continue
    try:
        obj = json.loads(ln)
        break
    except ValueError:
        continue
if obj is None:
    sys.exit("no JSON object found in anchor_repo.sh stdout")
for key in ("slug", "anchor_sha", "worktree"):
    if not obj.get(key):
        sys.exit("anchor JSON missing required field: %s" % key)
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(obj, fh)
print("%s\t%s\t%s" % (obj["slug"], obj["anchor_sha"], obj["worktree"]))
PYEOF
}

# --- v1: anchor --------------------------------------------------------------
bash "$SCRIPTS/anchor_repo.sh" "$REPO" >"$WORK/anchor1.txt" || fail "v1 anchor_repo.sh failed"
[ -d "$OUT" ] || fail "anchor did not create the out dir under \$ORRERY_HOME ($OUT)"
if [ "$DEFAULT_ROOT_PREEXISTS" = "0" ] && [ -d "$HOME/code/orrery/$SLUG" ]; then
  fail "anchor created the default root despite the \$ORRERY_HOME override"
fi
PARSED="$(parse_anchor "$WORK/anchor1.txt")" || fail "could not parse v1 anchor JSON"
ANCHOR_SLUG="$(printf '%s\n' "$PARSED" | cut -f1)"
V1_SHA="$(printf '%s\n' "$PARSED" | cut -f2)"
WORKTREE="$(printf '%s\n' "$PARSED" | cut -f3)"
[ "$ANCHOR_SLUG" = "$SLUG" ] || fail "anchor reported slug $ANCHOR_SLUG, expected $SLUG"
echo "ok: v1 anchored at $V1_SHA (out dir under \$ORRERY_HOME honored)"

# --- v1: enumerate + fragments -----------------------------------------------
python3 "$SCRIPTS/enumerate_repo.py" --worktree "$WORKTREE" --out "$OUT/census.json" \
  || fail "v1 enumerate_repo.py failed"
python3 - "$OUT/census.json" <<'PYEOF' || fail "v1 census area ids drifted from the many/misc/web expectation"
import json
import sys

census = json.load(open(sys.argv[1], encoding="utf-8"))
ids = sorted(a["id"] for a in census.get("areas", []))
if ids != ["many", "misc", "web"]:
    sys.exit("expected areas [many, misc, web], got %s" % ids)
PYEOF

mkdir -p "$OUT/fragments"
rm -rf "$OUT/fragments"
mkdir -p "$OUT/fragments"
cp "$FRAGSRC/product-vision.json" "$FRAGSRC/external-systems.json" "$OUT/fragments/"
# Area templates materialized with the census-verified area ids: web keeps the
# storefront paths, misc carries the api/ paths, many carries the db/ paths.
sed 's/@AREA_ID@/web/g'  "$FRAGSRC/area-alpha.json.tmpl" > "$OUT/fragments/area-web.json"
sed 's/@AREA_ID@/misc/g' "$FRAGSRC/area-beta.json.tmpl"  > "$OUT/fragments/area-misc.json"
sed 's/@AREA_ID@/many/g' "$FRAGSRC/area-gamma.json.tmpl" > "$OUT/fragments/area-many.json"
PACKS="product-vision,external-systems,area-web,area-misc,area-many"

# --- v1: merge -> emit -> validate -> render ---------------------------------
python3 "$SCRIPTS/merge_fragments.py" \
  --fragments-dir "$OUT/fragments" \
  --packs "$PACKS" \
  --census "$OUT/census.json" \
  --anchor "$OUT/anchor.json" \
  --out "$OUT/model.json" >/dev/null \
  || fail "v1 merge_fragments.py failed"
python3 "$SCRIPTS/emit_likec4.py" --model "$OUT/model.json" --out-dir "$OUT" \
  || fail "v1 emit_likec4.py failed"
python3 "$SCRIPTS/validate_map.py" \
  --model "$OUT/model.json" --model-dir "$OUT/model" \
  --repo "$REPO" --anchor-sha "$V1_SHA" \
  || fail "v1 validate_map.py failed (see errors.json in $OUT)"
bash "$SCRIPTS/render_map.sh" "$OUT" "$SLUG" >/dev/null || fail "v1 render_map.sh failed"
[ -f "$OUT/dist/$SLUG.html" ] || fail "v1 artifact missing"
echo "ok: v1 chain green (merge -> emit -> validate -> render)"

# --- v1: state.json (the same atomic writer as SKILL.md step 7) --------------
python3 - "$OUT" "$SKILL_DIR" <<'PYEOF' || fail "v1 state.json write failed"
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
PYEOF
V1_STATE_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["anchor_sha"])' "$OUT/state.json")"
[ "$V1_STATE_SHA" = "$V1_SHA" ] || fail "v1 state.json anchor mismatch"
echo "ok: v1 state.json written (anchor $V1_STATE_SHA)"

# --- v1: teardown (the build path's unskippable step 8) ----------------------
bash "$SCRIPTS/anchor_repo.sh" --teardown "$REPO" "$WORKTREE" || fail "v1 teardown failed"
WORKTREE=""

# --- v2: commit the update delta (index plumbing) ----------------------------
# modify one api/ file
NEW_WORKER="$( { $GITC cat-file blob :api/src/worker.js; printf '// v2: refunds endpoint added\n'; } | $GITC hash-object -w --stdin )"
$GITC update-index --add --cacheinfo "100644,$NEW_WORKER,api/src/worker.js"
# delete one web/ file (the sole anchor of the baseline web__cart element)
$GITC update-index --force-remove web/src/components/Cart.tsx
# rename one file, blob unchanged, so `git diff -M` reports R100
OLD_SQL="$($GITC rev-parse :db/migrations/0002_orders.sql)"
$GITC update-index --force-remove db/migrations/0002_orders.sql
$GITC update-index --add --cacheinfo "100644,$OLD_SQL,db/migrations/0002_orders_table.sql"
$GITC commit -qm "v2: modify worker, delete Cart, rename orders migration" --no-verify
$GITC push -q origin main
echo "ok: v2 delta committed and pushed"

# --- v2: re-anchor -----------------------------------------------------------
bash "$SCRIPTS/anchor_repo.sh" "$REPO" >"$WORK/anchor2.txt" || fail "v2 anchor_repo.sh failed"
PARSED="$(parse_anchor "$WORK/anchor2.txt")" || fail "could not parse v2 anchor JSON"
V2_SHA="$(printf '%s\n' "$PARSED" | cut -f2)"
WORKTREE="$(printf '%s\n' "$PARSED" | cut -f3)"
[ "$V2_SHA" != "$V1_SHA" ] || fail "v2 anchor did not advance"

if [ "${ORRERY_UPDATE_TEST_INJECT_FAIL:-}" = "post-anchor" ]; then
  echo "INJECTED FAILURE: simulating a mid-run crash after the v2 anchor (teardown probe)" >&2
  exit 1
fi
echo "ok: v2 anchored at $V2_SHA"

# --- v2: diff_since ----------------------------------------------------------
python3 "$SCRIPTS/diff_since.py" \
  --repo "$REPO" \
  --state "$OUT/state.json" \
  --new-anchor "$V2_SHA" \
  --out "$OUT/diff.json" \
  || fail "diff_since.py failed"

python3 - "$OUT/diff.json" "$OUT/model.json" "$V1_SHA" "$V2_SHA" <<'PYEOF' || fail "diff.json scoping/continuity assertions failed"
import json
import sys

diff = json.load(open(sys.argv[1], encoding="utf-8"))
model = json.load(open(sys.argv[2], encoding="utf-8"))
v1, v2 = sys.argv[3], sys.argv[4]

if diff["unchanged"] or diff["history_rewritten"] or diff["rebuild_required"]:
    sys.exit("expected a patchable diff, got: %s" % {k: diff[k] for k in
             ("unchanged", "history_rewritten", "rebuild_required", "rebuild_reason")})
if diff["old_anchor_sha"] != v1 or diff["new_anchor_sha"] != v2:
    sys.exit("diff anchors wrong: %s..%s" % (diff["old_anchor_sha"], diff["new_anchor_sha"]))
if "api/src/worker.js" not in diff["changed_paths"]:
    sys.exit("modified api/ file missing from changed_paths: %s" % diff["changed_paths"])
if diff["deleted_paths"] != ["web/src/components/Cart.tsx"]:
    sys.exit("deleted_paths wrong: %s" % diff["deleted_paths"])
if diff["renamed_paths"] != [{"from": "db/migrations/0002_orders.sql",
                              "similarity": 100,
                              "to": "db/migrations/0002_orders_table.sql"}]:
    sys.exit("renamed_paths wrong: %s" % diff["renamed_paths"])
# Scoping: exactly the two touched areas - many (the renamed file's element
# owner) is NOT re-investigated; its continuity comes from the re-anchor.
if diff["affected_areas"] != ["misc", "web"]:
    sys.exit("affected_areas wrong (scoping broken): %s" % diff["affected_areas"])
if diff["orphaned_elements"] != ["web__cart"]:
    sys.exit("orphaned_elements wrong: %s" % diff["orphaned_elements"])
# The renamed migration sits under db/migrations/ - a manifest-table dir - so
# the external-systems pack is flagged for re-investigation.
if diff["external_systems_flagged"] is not True:
    sys.exit("external_systems_flagged expected true (migrations path renamed)")
if diff["product_vision_flagged"] is not False:
    sys.exit("product_vision_flagged expected false")
if diff["elements_reanchored"] != ["many__orders_schema"]:
    sys.exit("elements_reanchored wrong: %s" % diff["elements_reanchored"])
# In-place baseline re-anchor: the retained element already cites the new path.
schema = [e for e in model["elements"] if e["id"] == "many__orders_schema"]
if not schema or schema[0]["files"][0]["path"] != "db/migrations/0002_orders_table.sql":
    sys.exit("baseline model was not re-anchored in place for the rename")
print("ok: diff.json scoping, orphan, rename-continuity and pack flags all hold")
PYEOF

# --- v2: refresh deterministic inputs (update-flow U4.1) ---------------------
python3 "$SCRIPTS/enumerate_repo.py" --worktree "$WORKTREE" --out "$OUT/census.json" \
  || fail "v2 enumerate_repo.py failed"

# --- v2: canned updated fragments for exactly the re-run packs ---------------
# external-systems (flagged) re-runs with the canned wave-0 fragment; the two
# affected areas get updated fragments: area-web drops the deleted Cart
# element and adds a NEW one, area-misc updates the worker.
rm -rf "$OUT/fragments"
mkdir -p "$OUT/fragments"
cp "$FRAGSRC/external-systems.json" "$OUT/fragments/"
cat > "$OUT/fragments/area-web.json" <<'JSONEOF'
{
  "pack": "area-web",
  "elements": [
    {
      "id": "web__catalog",
      "kind": "component",
      "title": "Catalog Browser",
      "summary": "Product listing for the storefront grid.",
      "description": "Lists products from the catalog feed because the Shopper needs to find items before checkout.",
      "parent": "web",
      "files": [{ "path": "web/src/components/ProductGrid.tsx", "start_line": 1, "end_line": 7 }]
    },
    {
      "id": "web__wishlist",
      "kind": "component",
      "title": "Wishlist Panel",
      "summary": "Saved-items panel added in v2 of the storefront.",
      "description": "Keeps items the Shopper saved for later because checkout now starts from saved lists too.",
      "parent": "web",
      "files": [{ "path": "web/src/components/Header.tsx" }]
    }
  ],
  "relations": [
    { "from": "web__catalog", "to": "web__wishlist", "kind": "uses", "summary": "saves items" }
  ],
  "open_questions": []
}
JSONEOF
cat > "$OUT/fragments/area-misc.json" <<'JSONEOF'
{
  "pack": "area-misc",
  "elements": [
    {
      "id": "misc__worker",
      "kind": "component",
      "title": "Checkout Worker",
      "summary": "Serverless handler that charges cards, records orders, and queues refunds.",
      "description": "Charges cards through the Stripe API and writes orders because the storefront never touches card data; v2 adds a refunds endpoint.",
      "technology": "Cloudflare Worker",
      "parent": "api",
      "files": [{ "path": "api/src/worker.js", "start_line": 1, "end_line": 17 }]
    }
  ],
  "relations": [
    { "from": "misc__worker", "to": "stripe", "kind": "calls", "summary": "charges cards" }
  ],
  "open_questions": []
}
JSONEOF
RERUN_PACKS="external-systems,area-misc,area-web"

# --- v2: patch-merge -> emit -> validate -> render ---------------------------
python3 "$SCRIPTS/merge_fragments.py" \
  --fragments-dir "$OUT/fragments" \
  --packs "$RERUN_PACKS" \
  --census "$OUT/census.json" \
  --anchor "$OUT/anchor.json" \
  --out "$OUT/model.json" \
  --patch --state "$OUT/state.json" --diff "$OUT/diff.json" >/dev/null \
  || fail "patch-mode merge_fragments.py failed"
python3 "$SCRIPTS/emit_likec4.py" --model "$OUT/model.json" --out-dir "$OUT" \
  || fail "v2 emit_likec4.py failed"
python3 "$SCRIPTS/validate_map.py" \
  --model "$OUT/model.json" --model-dir "$OUT/model" \
  --repo "$REPO" --anchor-sha "$V2_SHA" \
  || fail "v2 validate_map.py failed (see errors.json in $OUT)"
bash "$SCRIPTS/render_map.sh" "$OUT" "$SLUG" >/dev/null || fail "v2 render_map.sh failed"
ARTIFACT="$OUT/dist/$SLUG.html"
[ -f "$ARTIFACT" ] || fail "v2 artifact missing"
echo "ok: v2 patch chain green (patch-merge -> emit -> validate -> render)"

# --- v2: state.json rewrite (atomic advance) ---------------------------------
python3 - "$OUT" "$SKILL_DIR" <<'PYEOF' || fail "v2 state.json write failed"
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
PYEOF

# --- v2: assertions ----------------------------------------------------------
python3 - "$OUT" "$V1_SHA" "$V2_SHA" <<'PYEOF' || fail "v2 model/state assertions failed"
import json, os, sys
out, v1, v2 = sys.argv[1], sys.argv[2], sys.argv[3]
model = json.load(open(os.path.join(out, "model.json"), encoding="utf-8"))
ids = {e["id"] for e in model["elements"]}
if "web__wishlist" not in ids:
    sys.exit("new element web__wishlist missing from the patched model")
if "web__cart" in ids:
    sys.exit("deleted element web__cart survived the patch")
if "many__orders_schema" not in ids:
    sys.exit("renamed element many__orders_schema was not retained")
schema = [e for e in model["elements"] if e["id"] == "many__orders_schema"][0]
if schema["files"][0]["path"] != "db/migrations/0002_orders_table.sql":
    sys.exit("renamed element retained but anchor not updated: %s" % schema["files"])
state = json.load(open(os.path.join(out, "state.json"), encoding="utf-8"))
if state["anchor_sha"] != v2:
    sys.exit("state.json anchor did not advance: %s (expected %s)" % (state["anchor_sha"], v2))
if state["anchor_sha"] == v1:
    sys.exit("state.json anchor still at v1")
if os.path.exists(os.path.join(out, "state.json.tmp")):
    sys.exit("state.json.tmp left behind - the state write was not atomic")
report = json.load(open(os.path.join(out, "merge-report.json"), encoding="utf-8"))
patch = report.get("patch") or {}
if "web__cart" not in patch.get("baseline_elements_replaced", []):
    sys.exit("merge-report patch section did not record the area-web replacement")
if patch.get("reinvestigation_failed_retained"):
    sys.exit("unexpected reinvestigation failures: %s" % patch["reinvestigation_failed_retained"])
print("ok: patched model + advanced state assertions hold")
PYEOF

# (Anchor paths appear in the artifact only as GitHub links, and this fixture's
# remote is a local bare repo - so the rename-continuity assertion lives on the
# patched model above, while titles are asserted in the rendered artifact.)
grep -q "Wishlist Panel" "$ARTIFACT" || fail "new element title missing from the artifact"
if grep -qF "Client-side cart state." "$ARTIFACT"; then
  fail "deleted element's content still present in the artifact"
fi
echo "ok: artifact carries the new title; deleted element's content absent"

# --- v2: teardown ------------------------------------------------------------
bash "$SCRIPTS/anchor_repo.sh" --teardown "$REPO" "$WORKTREE" || fail "v2 teardown failed"
WORKTREE=""

# --- v3: pure same-area rename -> the empty-re-run-pack fast path ------------
# Stage-2 finding 2, shape (a): a same-area rename touching no manifest or
# vision path affects ZERO packs. The flow must NOT call merge (empty --packs
# exits 2); it re-renders from the baseline model diff_since re-anchored in
# place, then advances state.
OLD_GRID="$($GITC rev-parse :web/src/components/ProductGrid.tsx)"
$GITC update-index --force-remove web/src/components/ProductGrid.tsx
$GITC update-index --add --cacheinfo "100644,$OLD_GRID,web/src/components/Grid.tsx"
$GITC commit -qm "v3: rename ProductGrid within the web area" --no-verify
$GITC push -q origin main

bash "$SCRIPTS/anchor_repo.sh" "$REPO" >"$WORK/anchor3.txt" || fail "v3 anchor_repo.sh failed"
PARSED="$(parse_anchor "$WORK/anchor3.txt")" || fail "could not parse v3 anchor JSON"
V3_SHA="$(printf '%s\n' "$PARSED" | cut -f2)"
WORKTREE="$(printf '%s\n' "$PARSED" | cut -f3)"
[ "$V3_SHA" != "$V2_SHA" ] || fail "v3 anchor did not advance"

python3 "$SCRIPTS/diff_since.py" \
  --repo "$REPO" --state "$OUT/state.json" \
  --new-anchor "$V3_SHA" --out "$OUT/diff.json" \
  || fail "v3 diff_since.py failed"
python3 - "$OUT/diff.json" "$OUT/model.json" <<'PYEOF' || fail "v3 empty-pack fast-path diff assertions failed"
import json
import sys

diff = json.load(open(sys.argv[1], encoding="utf-8"))
model = json.load(open(sys.argv[2], encoding="utf-8"))
if diff["unchanged"] or diff["history_rewritten"] or diff["rebuild_required"] or diff["state_missing"]:
    sys.exit("expected a patchable diff, got routing flags set")
# The empty re-run pack list: no areas affected, neither wave-0 pack flagged.
if diff["affected_areas"] != [] or diff["external_systems_flagged"] or diff["product_vision_flagged"]:
    sys.exit("expected ZERO re-run packs, got areas=%s flags=%s/%s" % (
        diff["affected_areas"], diff["external_systems_flagged"], diff["product_vision_flagged"]))
if diff["elements_reanchored"] != ["web__catalog"]:
    sys.exit("elements_reanchored wrong: %s" % diff["elements_reanchored"])
cat = [e for e in model["elements"] if e["id"] == "web__catalog"][0]
if cat["files"][0]["path"] != "web/src/components/Grid.tsx":
    sys.exit("baseline model not re-anchored to the renamed path")
print("ok: v3 diff affects zero packs; baseline re-anchored in place")
PYEOF

# Fast path (SKILL U4.2): refresh inputs, SKIP dispatch + merge entirely,
# re-render from the re-anchored baseline because elements_reanchored != [].
python3 "$SCRIPTS/enumerate_repo.py" --worktree "$WORKTREE" --out "$OUT/census.json" \
  || fail "v3 enumerate_repo.py failed"
python3 "$SCRIPTS/emit_likec4.py" --model "$OUT/model.json" --out-dir "$OUT" \
  || fail "v3 emit_likec4.py failed"
python3 "$SCRIPTS/validate_map.py" \
  --model "$OUT/model.json" --model-dir "$OUT/model" \
  --repo "$REPO" --anchor-sha "$V3_SHA" \
  || fail "v3 validate_map.py failed - the re-anchored baseline must be valid at v3"
bash "$SCRIPTS/render_map.sh" "$OUT" "$SLUG" >/dev/null || fail "v3 render_map.sh failed"
grep -q "Catalog Browser" "$ARTIFACT" || fail "renamed element's title missing after fast-path re-render"

python3 - "$OUT" "$SKILL_DIR" <<'PYEOF' || fail "v3 state.json write failed"
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
PYEOF
V3_STATE_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["anchor_sha"])' "$OUT/state.json")"
[ "$V3_STATE_SHA" = "$V3_SHA" ] || fail "v3 state.json anchor did not advance"
echo "ok: v3 fast path green - zero dispatch, re-anchored render, state advanced"

bash "$SCRIPTS/anchor_repo.sh" --teardown "$REPO" "$WORKTREE" || fail "v3 teardown failed"
WORKTREE=""

# --- v4: identical-tree anchor advance -> fast path with nothing to do -------
# Stage-2 finding 2, shape (b): the anchor advances but the tree is byte-
# identical. Zero packs, zero re-anchors: the artifact stays untouched and
# only state.json advances.
ART_SUM_BEFORE="$(cksum "$ARTIFACT" | cut -d' ' -f1-2)"
$GITC commit -q --allow-empty -m "v4: no tree change" --no-verify
$GITC push -q origin main

bash "$SCRIPTS/anchor_repo.sh" "$REPO" >"$WORK/anchor4.txt" || fail "v4 anchor_repo.sh failed"
PARSED="$(parse_anchor "$WORK/anchor4.txt")" || fail "could not parse v4 anchor JSON"
V4_SHA="$(printf '%s\n' "$PARSED" | cut -f2)"
WORKTREE="$(printf '%s\n' "$PARSED" | cut -f3)"
[ "$V4_SHA" != "$V3_SHA" ] || fail "v4 anchor did not advance"

python3 "$SCRIPTS/diff_since.py" \
  --repo "$REPO" --state "$OUT/state.json" \
  --new-anchor "$V4_SHA" --out "$OUT/diff.json" \
  || fail "v4 diff_since.py failed"
python3 - "$OUT/diff.json" <<'PYEOF' || fail "v4 identical-tree diff assertions failed"
import json
import sys

diff = json.load(open(sys.argv[1], encoding="utf-8"))
if diff["unchanged"] or diff["history_rewritten"] or diff["rebuild_required"] or diff["state_missing"]:
    sys.exit("expected a patchable diff, got routing flags set")
for key in ("affected_areas", "changed_paths", "deleted_paths", "renamed_paths",
            "orphaned_elements", "new_paths_routed_to_misc", "elements_reanchored"):
    if diff[key]:
        sys.exit("%s expected empty, got %s" % (key, diff[key]))
if diff["external_systems_flagged"] or diff["product_vision_flagged"]:
    sys.exit("no pack flags expected on an identical tree")
print("ok: v4 diff is the all-empty patchable shape")
PYEOF

# Fast path with elements_reanchored empty: keep the artifact, advance state.
python3 - "$OUT" "$SKILL_DIR" <<'PYEOF' || fail "v4 state.json write failed"
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
PYEOF
V4_STATE_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["anchor_sha"])' "$OUT/state.json")"
[ "$V4_STATE_SHA" = "$V4_SHA" ] || fail "v4 state.json anchor did not advance"
ART_SUM_AFTER="$(cksum "$ARTIFACT" | cut -d' ' -f1-2)"
[ "$ART_SUM_BEFORE" = "$ART_SUM_AFTER" ] || fail "artifact changed on the nothing-to-do fast path"
echo "ok: v4 fast path green - artifact untouched, state advanced to $V4_SHA"

# --- final teardown + worktree-clean assertion -------------------------------
bash "$SCRIPTS/anchor_repo.sh" --teardown "$REPO" "$WORKTREE" || fail "v4 teardown failed"
WORKTREE=""
WT_LIST="$(git -C "$REPO" worktree list)"
WT_COUNT="$(printf '%s\n' "$WT_LIST" | wc -l | tr -d ' ')"
if [ "$WT_COUNT" != "1" ]; then
  echo "$WT_LIST" >&2
  fail "git worktree list not clean after teardown ($WT_COUNT entries)"
fi
echo "ok: teardown left the target repo clean"

echo "test-update-fixture.sh: PASS"
