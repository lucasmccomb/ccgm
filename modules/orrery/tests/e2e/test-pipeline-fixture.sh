#!/usr/bin/env bash
set -euo pipefail

# Pipeline E2E (plan Epic 3): fixture fragments -> merge (screening report
# asserted) -> emit -> validate against the MATERIALIZED fixture-repo git
# anchor -> render via render_map.sh -> artifact assertions:
#   - contains acme-shop and a blob/{sha} link at the real anchor sha
#   - does NOT contain the fake secret value (quarantined upstream)
#   - does NOT contain live adversarial markup (escaped to entities)
#
# The area fragments are TEMPLATES: their @AREA_ID@ token is substituted
# here (Epic 4 drives the same templates with census-derived ids).
# Portable: macOS bash 3.2 + BSD tools.

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$MODULE_DIR/skills/orrery/scripts"
FRAGSRC="$MODULE_DIR/tests/fixtures/fragments"
REPOSRC="$MODULE_DIR/tests/fixtures/fixture-repo"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/orrery-pipeline.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# --- 1. materialize the fixture repo as a real git anchor --------------------
REPO="$WORK/repo"
mkdir -p "$REPO"
cp -R "$REPOSRC/." "$REPO/"
# Throwaway repo: bypass machine-level hooks (core.hooksPath) because the
# fixture deliberately contains secret-SHAPED fake values that a gitleaks
# pre-commit hook rejects.
GITC="git -C $REPO -c user.name=orrery -c user.email=orrery@example.invalid -c core.hooksPath=/dev/null"
$GITC init -q
$GITC add -A
$GITC commit -qm fixture --no-verify
ANCHOR_SHA="$($GITC rev-parse HEAD)"
echo "ok: fixture repo materialized at anchor $ANCHOR_SHA"

# --- 2. fragments: static fixtures + materialized area templates -------------
FRAG="$WORK/fragments"
mkdir -p "$FRAG"
cp "$FRAGSRC/external-systems.json" "$FRAGSRC/product-vision.json" \
   "$FRAGSRC/broken.json" "$FRAGSRC/traversal.json" "$FRAG/"
sed 's/@AREA_ID@/web/g' "$FRAGSRC/area-alpha.json.tmpl" > "$FRAG/area-web.json"
sed 's/@AREA_ID@/api/g' "$FRAGSRC/area-beta.json.tmpl" > "$FRAG/area-api.json"
sed 's/@AREA_ID@/db/g' "$FRAGSRC/area-gamma.json.tmpl" > "$FRAG/area-db.json"

# --- 3. anchor.json + census.json --------------------------------------------
python3 - "$WORK" "$ANCHOR_SHA" "$REPO" <<'PY'
import json, sys
work, sha, repo = sys.argv[1], sys.argv[2], sys.argv[3]
with open(work + "/anchor.json", "w") as fh:
    json.dump({"repo_path": repo,
               "remote_url": "https://github.com/acme-fixture/acme-shop.git",
               "default_ref": "main", "anchor_sha": sha,
               "worktree": repo, "slug": "acme-shop",
               "behind": False, "dirty": False, "no_remote": False,
               "visibility": "public"}, fh)
with open(work + "/census.json", "w") as fh:
    json.dump({"areas": [{"id": "web", "title": "Web", "root_paths": ["Web"]},
                         {"id": "api", "title": "api", "root_paths": ["api"]},
                         {"id": "db", "title": "db", "root_paths": ["db"]}]}, fh)
PY

# --- 4. merge (screening report asserted) ------------------------------------
# traversal.json is deliberately NOT listed: the whitelist must ignore+report
# it. broken.json IS listed: schema quarantine must fire and the run continue.
MERGE_LOG="$WORK/merge.log"
python3 "$SCRIPTS/merge_fragments.py" \
  --fragments-dir "$FRAG" \
  --packs external-systems,product-vision,area-web,area-api,area-db,broken \
  --census "$WORK/census.json" --anchor "$WORK/anchor.json" \
  --out "$WORK/model.json" | tee "$MERGE_LOG"

grep -q "1 elements withheld: secret-shaped content" "$MERGE_LOG" \
  || fail "secret-quarantine report line missing"
grep -q "traversal.json" "$MERGE_LOG" \
  || fail "whitelist ignored-file report missing"
grep -q "quarantined 1 invalid fragment(s): broken" "$MERGE_LOG" \
  || fail "invalid-fragment quarantine report missing"
grep -q "payments_gateway" "$MERGE_LOG" \
  || fail "cross-pack collision report missing"
grep -q "dropped 1 dangling relation(s)" "$MERGE_LOG" \
  || fail "dangling-relation report missing"
echo "ok: merge screening report asserted"

if grep -q "ghp_0bAdC0ffee" "$WORK/model.json"; then
  fail "fake secret value leaked into model.json"
fi
if grep -q "ghp_0bAdC0ffee" "$WORK/merge-report.json"; then
  fail "fake secret value leaked into merge-report.json"
fi
if grep -q '"payments_gateway"' "$WORK/model.json"; then
  fail "collision element was fused into model.json"
fi
echo "ok: quarantined content absent from model + report"

# --- 5. emit -----------------------------------------------------------------
python3 "$SCRIPTS/emit_likec4.py" --model "$WORK/model.json" --out-dir "$WORK"
[ -f "$WORK/model/likec4.config.json" ] || fail "likec4.config.json not inside model/"

# --- 6. validate against the materialized git anchor -------------------------
python3 "$SCRIPTS/validate_map.py" --model "$WORK/model.json" \
  --model-dir "$WORK/model" --repo "$REPO" --anchor-sha "$ANCHOR_SHA" \
  || fail "validate_map.py rejected the pipeline model"
echo "ok: validate green against anchor $ANCHOR_SHA"

# --- 7. render ---------------------------------------------------------------
bash "$SCRIPTS/render_map.sh" "$WORK" acme-shop >/dev/null
ARTIFACT="$WORK/dist/acme-shop.html"
[ -f "$ARTIFACT" ] || fail "artifact missing"

# --- 8. artifact assertions --------------------------------------------------
grep -q "acme-shop" "$ARTIFACT" || fail "artifact does not contain acme-shop"
grep -q "blob/$ANCHOR_SHA" "$ARTIFACT" || fail "artifact does not contain a blob/{sha} link at the anchor"
if grep -q "ghp_0bAdC0ffee" "$ARTIFACT"; then
  fail "artifact contains the fake secret value"
fi
if grep -qF '<img src=x onerror=' "$ARTIFACT"; then
  fail "artifact contains LIVE adversarial markup"
fi
grep -qF '&lt;img src=x onerror=' "$ARTIFACT" \
  || fail "escaped adversarial payload missing (escaping did not run?)"
grep -qF '[neutralized]' "$ARTIFACT" \
  || fail "neutralization marker missing from artifact"
echo "ok: artifact contains acme-shop + blob/{sha}; secret + live markup absent"

echo "test-pipeline-fixture.sh: PASS"
