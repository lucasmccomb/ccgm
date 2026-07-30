#!/usr/bin/env bash
set -euo pipefail

# Joined ingestion E2E (plan Epic 4 / adrev2-006, section 8.3).
#
# The only test that executes the deterministic FRONT half (anchor -> census)
# joined to the BACK half (merge -> emit -> validate -> render): without it the
# Epic-2/Epic-3 interface - above all the section-3.5a-sanitized area ids that
# canned fixtures would otherwise hardcode on both sides - is certified only by
# hand-matched fixtures built in parallel by different agents.
#
# Chain: materialize fixture-repo into a temp git repo (INDEX PLUMBING, local
# bare origin) -> anchor_repo.sh -> enumerate_repo.py -> assert census area
# ids against the section-3.5a expectations -> substitute Epic 3's area
# templates (@AREA_ID@ token) with area ids READ FROM census.json, never
# hardcoded -> merge -> emit -> validate -> render -> anchor_repo.sh
# --teardown -> assert `git worktree list` clean.
#
# Portable: macOS bash 3.2 + BSD tools.

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$MODULE_DIR/skills/orrery/scripts"
FRAGMENTS_SRC="$MODULE_DIR/tests/fixtures/fragments"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

for s in anchor_repo.sh enumerate_repo.py merge_fragments.py emit_likec4.py validate_map.py render_map.sh; do
  [ -f "$SCRIPTS/$s" ] || fail "required script missing: scripts/$s"
done
[ -d "$FRAGMENTS_SRC" ] || fail "canned fragment templates missing: tests/fixtures/fragments"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/orrery-ingest.XXXXXX")"
SLUG=""
# anchor_repo.sh creates its output dir under the fixed root below (R4); the
# slug derived from this test's repo dir name exists only here, so removing it
# in cleanup is safe and keeps the real output root clean.
ANCHOR_OUT_ROOT="$HOME/code/orrery"
cleanup() {
  rm -rf "$WORK"
  if [ -n "$SLUG" ] && [ -d "$ANCHOR_OUT_ROOT/$SLUG" ]; then
    rm -rf "$ANCHOR_OUT_ROOT/$SLUG"
  fi
}
trap cleanup EXIT

# --- materialize the fixture repo (index plumbing) + local bare origin -------
# INDEX PLUMBING, never a filesystem copy + `git add`: the fixture repo
# deliberately commits BOTH web/ (storefront) and Web/ (legacy) - two dirs
# that differ only by case. A `cp -R` materializes them as ONE merged physical
# dir on case-insensitive macOS and TWO dirs on case-sensitive Linux, so a
# copy-based temp repo diverges per OS. Building the temp index from the ccgm
# index entry list is case-exact and OS-deterministic (same technique as
# test-pipeline-fixture.sh). core.hooksPath is neutralized because the fixture
# carries secret-SHAPED fake values a machine-level pre-commit hook rejects.
REPO="$WORK/orrery-ingest-fixture"
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
$GITC commit -qm fixture --no-verify
$GITC branch -M main

# Deterministic regression guards for the case-split (read via plumbing, so
# identical on every OS): both case-colliding dirs survived, and every source
# index entry made it into the committed tree.
TREE_LIST="$WORK/tree-paths.txt"
$GITC ls-tree -r --name-only HEAD > "$TREE_LIST"
grep -q '^web/' "$TREE_LIST" \
  || fail "materialized tree lost the lowercase web/ dir (case-folded materialization?)"
grep -q '^Web/' "$TREE_LIST" \
  || fail "materialized tree lost the uppercase Web/ dir (case-folded materialization?)"
TMP_COUNT="$(wc -l < "$TREE_LIST" | tr -d ' ')"
[ "$SRC_COUNT" = "$TMP_COUNT" ] \
  || fail "materialized tree has $TMP_COUNT entries but the ccgm index has $SRC_COUNT"

git init -q --bare "$WORK/origin.git"
$GITC remote add origin "$WORK/origin.git"
$GITC push -q -u origin main
git -C "$WORK/origin.git" symbolic-ref HEAD refs/heads/main
echo "ok: fixture repo materialized case-exactly ($TMP_COUNT entries, web/ + Web/ both present) with local bare origin"

OUT="$WORK/out"
mkdir -p "$OUT/fragments"

# --- stage 1: anchor ---------------------------------------------------------
ANCHOR_STDOUT="$WORK/anchor-stdout.txt"
bash "$SCRIPTS/anchor_repo.sh" "$REPO" >"$ANCHOR_STDOUT" || fail "anchor_repo.sh failed"

PARSED="$(python3 - "$ANCHOR_STDOUT" "$OUT/anchor.json" <<'PYEOF'
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
)" || fail "could not parse anchor_repo.sh JSON output"
SLUG="$(printf '%s\n' "$PARSED" | cut -f1)"
ANCHOR_SHA="$(printf '%s\n' "$PARSED" | cut -f2)"
WORKTREE="$(printf '%s\n' "$PARSED" | cut -f3)"
[ -d "$WORKTREE" ] || fail "anchor worktree does not exist: $WORKTREE"
echo "ok: anchored at $ANCHOR_SHA (slug $SLUG)"

# --- stage 2: enumerate ------------------------------------------------------
python3 "$SCRIPTS/enumerate_repo.py" --worktree "$WORKTREE" --out "$OUT/census.json" \
  || fail "enumerate_repo.py failed"
[ -s "$OUT/census.json" ] || fail "enumerate_repo.py produced no census.json"

# --- stage 3: census area ids vs section-3.5a expectations -------------------
python3 - "$OUT/census.json" <<'PYEOF' || fail "census area ids violate the section-3.5a expectations"
import json
import re
import sys

census = json.load(open(sys.argv[1], encoding="utf-8"))
areas = census.get("areas")
if not isinstance(areas, list) or not areas:
    sys.exit("census has no areas[]")
ids = []
for a in areas:
    aid = a.get("id") if isinstance(a, dict) else a
    if not aid:
        sys.exit("census area without an id: %r" % (a,))
    ids.append(str(aid))

if len(ids) > 24:
    sys.exit("more than 24 areas: %d (the section-3.5a hard ceiling)" % len(ids))
if len(ids) != len(set(ids)):
    sys.exit("duplicate area ids: %s" % sorted(ids))

pat = re.compile(r"^[a-z][a-z0-9_]*$")
bad = [i for i in ids if not pat.match(i)]
if bad:
    sys.exit("area ids not element-id-legal (^[a-z][a-z0-9_]*$): %s" % bad)

# The adversarial fixture dirs must never surface unsanitized.
raw = {"my-app", "Web", "2fa", ".github"} & set(ids)
if raw:
    sys.exit("unsanitized adversarial area ids leaked through: %s" % sorted(raw))

bucketed = [i for i in ids if i.startswith("bucket_")]
if bucketed:
    # Bin-packed shape: only reserved ids may appear (section 3.5a steps 3/5).
    stray = [i for i in ids if not i.startswith("bucket_") and i != "misc"]
    if stray:
        sys.exit("bucketed census carries non-reserved area ids: %s" % stray)
else:
    # Direct-candidate shape - the fixture's natural census: web/ (12-file
    # storefront) survives as `web`, many/ (32 files, under the 60% expansion
    # threshold) survives as `many`, and the <5-file candidates (api/, db/,
    # my-app/, 2fa/, .github/, the 2-file legacy Web/) merge into `misc`.
    expected = {"many", "misc", "web"}
    missing = sorted(expected - set(ids))
    if missing:
        sys.exit("expected census area ids missing: %s (got %s)" % (missing, sorted(ids)))

print("ok: census area ids pass section-3.5a expectations: %s" % sorted(ids))
PYEOF

# --- stage 4: substitute Epic 3's area templates with census-derived ids -----
# The templates (tests/fixtures/fragments/area-*.json.tmpl) carry a literal
# @AREA_ID@ token; each one is materialized with a DISTINCT area id read from
# census.json - never hardcoded - which is exactly the Epic-2/Epic-3 interface
# this chain certifies. Wave-0 fragments are copied as-is. The deliberately
# broken/traversal fixtures are not part of this chain (test-pipeline-fixture.sh
# and the unit suite own the screening layer).
cp "$FRAGMENTS_SRC/product-vision.json" "$FRAGMENTS_SRC/external-systems.json" "$OUT/fragments/"

PACKS="$(python3 - "$FRAGMENTS_SRC" "$OUT/census.json" "$OUT/fragments" <<'PYEOF'
import glob
import json
import os
import sys

fragments_src, census_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
census = json.load(open(census_path, encoding="utf-8"))
ids = []
for a in census.get("areas", []):
    aid = a.get("id") if isinstance(a, dict) else a
    if aid:
        ids.append(str(aid))
# Distinct census-derived ids, non-misc first so real areas are exercised
# before the merged-tinies bucket.
pool = sorted(i for i in set(ids) if i != "misc")
if "misc" in ids:
    pool.append("misc")
if not pool:
    sys.exit("census produced no area ids to substitute")

tmpls = sorted(glob.glob(os.path.join(fragments_src, "area-*.json.tmpl")))
if not tmpls:
    sys.exit("no area-*.json.tmpl templates found in tests/fixtures/fragments")

packs = []
for tmpl, aid in zip(tmpls, pool):
    text = open(tmpl, encoding="utf-8").read().replace("@AREA_ID@", aid)
    frag = json.loads(text)  # a substituted template must still parse
    pack = frag.get("pack")
    if pack != "area-" + aid:
        sys.exit("template %s: pack %r != area-%s after substitution"
                 % (os.path.basename(tmpl), pack, aid))
    with open(os.path.join(out_dir, pack + ".json"), "w", encoding="utf-8") as fh:
        fh.write(text)
    packs.append(pack)

sys.stderr.write("ok: substituted %d template(s) with census-derived ids %s\n"
                 % (len(packs), pool[: len(packs)]))
print(",".join(["product-vision", "external-systems"] + packs))
PYEOF
)" || fail "template substitution failed"
echo "ok: fragments prepared, packs: $PACKS"

# Every fragment path fed to merge must be CASE-EXACT against the committed
# tree: git cat-file -e reads the object store, so this preflight is identical
# on case-sensitive and case-insensitive filesystems (same guard as
# test-pipeline-fixture.sh).
python3 - "$OUT/fragments" "$REPO" "$ANCHOR_SHA" <<'PYEOF' || fail "a fragment cites a path absent at the anchor (case drift?)"
import glob
import json
import os
import subprocess
import sys

frag_dir, repo, sha = sys.argv[1], sys.argv[2], sys.argv[3]
bad = []
for path in sorted(glob.glob(os.path.join(frag_dir, "*.json"))):
    with open(path, encoding="utf-8") as fh:
        frag = json.load(fh)
    for el in frag.get("elements", []):
        if not isinstance(el, dict):
            continue
        for f in el.get("files") or []:
            p = f.get("path")
            rc = subprocess.run(
                ["git", "-C", repo, "cat-file", "-e", "%s:%s" % (sha, p)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode
            if rc != 0:
                bad.append("%s: %s cites %s (absent at anchor)"
                           % (os.path.basename(path), el.get("id"), p))
if bad:
    print("\n".join(bad))
    sys.exit(1)
PYEOF
echo "ok: every fragment path is case-exact at the anchor"

# --- stage 5: merge ----------------------------------------------------------
python3 "$SCRIPTS/merge_fragments.py" \
  --fragments-dir "$OUT/fragments" \
  --packs "$PACKS" \
  --census "$OUT/census.json" \
  --anchor "$OUT/anchor.json" \
  --out "$OUT/model.json" \
  || fail "merge_fragments.py failed"
[ -s "$OUT/model.json" ] || fail "merge produced no model.json"

# The point of the chain: merged elements carry census-derived area-id
# prefixes, proving the front half's ids flowed through the back half.
python3 - "$OUT/model.json" "$OUT/census.json" <<'PYEOF' || fail "no merged element carries a census-derived area-id prefix"
import json
import sys

model = json.load(open(sys.argv[1], encoding="utf-8"))
census = json.load(open(sys.argv[2], encoding="utf-8"))
ids = set()
for a in census.get("areas", []):
    aid = a.get("id") if isinstance(a, dict) else a
    if aid:
        ids.add(str(aid))
hits = [
    e["id"]
    for e in model.get("elements", [])
    if any(str(e.get("id", "")).startswith(a + "__") for a in ids)
]
if not hits:
    sys.exit("model.json has no element namespaced by a census area id")
print("ok: %d merged element(s) carry census-derived prefixes (e.g. %s)" % (len(hits), hits[0]))
PYEOF

# --- stage 6: emit + validate ------------------------------------------------
python3 "$SCRIPTS/emit_likec4.py" --model "$OUT/model.json" --out-dir "$OUT" \
  || fail "emit_likec4.py failed"
[ -f "$OUT/model/likec4.config.json" ] || fail "emit did not place likec4.config.json INSIDE model/ (section 3.7)"

python3 "$SCRIPTS/validate_map.py" \
  --model "$OUT/model.json" \
  --model-dir "$OUT/model" \
  --repo "$REPO" \
  --anchor-sha "$ANCHOR_SHA" \
  || fail "validate_map.py failed (see errors.json in $OUT)"
echo "ok: merge -> emit -> validate green"

# --- stage 7: render ---------------------------------------------------------
bash "$SCRIPTS/render_map.sh" "$OUT" "$SLUG" >/dev/null || fail "render_map.sh failed"
ARTIFACT="$OUT/dist/$SLUG.html"
[ -f "$ARTIFACT" ] || fail "artifact missing: dist/$SLUG.html"
HTML_COUNT="$(find "$OUT/dist" -maxdepth 1 -name '*.html' | wc -l | tr -d ' ')"
[ "$HTML_COUNT" = "1" ] || fail "expected exactly one .html in dist, found $HTML_COUNT"
EXTERNAL_SRC="$({ grep -o '<script src="http' "$ARTIFACT" || true; } | wc -l | tr -d ' ')"
[ "$EXTERNAL_SRC" = "0" ] || fail "artifact references an external script (not self-contained)"
echo "ok: rendered $ARTIFACT"

# --- stage 8: teardown + worktree-clean assertion ----------------------------
bash "$SCRIPTS/anchor_repo.sh" --teardown "$REPO" "$WORKTREE" || fail "anchor_repo.sh --teardown failed"
WT_LIST="$(git -C "$REPO" worktree list)"
WT_COUNT="$(printf '%s\n' "$WT_LIST" | wc -l | tr -d ' ')"
if [ "$WT_COUNT" != "1" ]; then
  echo "$WT_LIST" >&2
  fail "git worktree list not clean after teardown ($WT_COUNT entries)"
fi
if printf '%s\n' "$WT_LIST" | grep -F "$WORKTREE" >/dev/null 2>&1; then
  fail "the anchor worktree is still listed after teardown"
fi
echo "ok: teardown left the target repo clean"

echo "test-ingest-fixture.sh: PASS"
