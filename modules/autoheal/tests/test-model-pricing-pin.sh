#!/usr/bin/env bash
# Tests that the model autoheal calls has a price everywhere it needs one
# (#1025, #1028).
#
# The analyzer's FALLBACK_PRICING and autoheal-install.sh's seeded
# cost_pricing both feed the daily cost cap. A model swap that forgets to
# bring its price along does not fail loudly on its own: the analyzer
# prices the call at some other model's rate and the cap fires at the
# wrong point. These assertions are that missing failure.
#
# The table below is the published per-MTok list price for each model
# this module names by default, checked against the Anthropic pricing
# page on 2026-09-02. Update it in the same change that swaps a model.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"
INSTALLER="${MODULE_ROOT}/bin/autoheal-install.sh"

PASS=0
FAIL=0

assert_eq() {
    if [ "$1" = "$2" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $3"
        echo "  expected: $2"
        echo "  actual:   $1"
    fi
}

RESULT=$(python3 - "${ANALYZER}" "${INSTALLER}" <<'PY'
import json
import re
import sys

analyzer_src = open(sys.argv[1], encoding="utf-8").read()
installer_src = open(sys.argv[2], encoding="utf-8").read()

# Published per-MTok list prices (input, output), checked 2026-09-02.
# Opus 4.7 and 4.8 share a rate; the $15/$75 that used to sit under the
# 4.7 key was the retired Opus 4.1 rate.
PUBLISHED = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "claude-opus-4-7": (5.0, 25.0),
}

problems = []


def parse_rates(src, block):
    """Pull {model: (input, output)} out of a pricing literal."""
    rates = {}
    for model, inp, out in re.findall(
        r'"(claude-[a-z0-9-]+)":\s*\{\s*"input_per_million":\s*([0-9.]+),\s*'
        r'"output_per_million":\s*([0-9.]+)\s*\}',
        block,
    ):
        rates[model] = (float(inp), float(out))
    if not rates:
        problems.append("no pricing entries found in the block")
    return rates


def block_after(src, marker, closer="}\n"):
    start = src.index(marker)
    end = src.index(closer, start)
    return src[start:end]


# The model the analyzer actually calls.
match = re.search(r'^DEFAULT_MODEL="([^"]+)"', analyzer_src, re.MULTILINE)
default_model = match.group(1) if match else None
if default_model != "claude-sonnet-5":
    problems.append(f"DEFAULT_MODEL is {default_model!r}; structured outputs need a supporting model")

analyzer_rates = parse_rates(analyzer_src, block_after(analyzer_src, "FALLBACK_PRICING = {"))
installer_rates = parse_rates(installer_src, block_after(installer_src, "DEFAULT_PRICING = {"))

for label, rates in (("analyzer FALLBACK_PRICING", analyzer_rates), ("installer DEFAULT_PRICING", installer_rates)):
    if default_model not in rates:
        problems.append(f"{label} has no entry for the model the analyzer calls ({default_model})")
    for model, (inp, out) in rates.items():
        if model not in PUBLISHED:
            continue
        if (inp, out) != PUBLISHED[model]:
            problems.append(
                f"{label}: {model} priced at {inp}/{out}, published rate is "
                f"{PUBLISHED[model][0]}/{PUBLISHED[model][1]}"
            )

# Every model in either table needs a published rate in this test, or a
# swap could carry a stale price forward unnoticed. No exemptions: the
# one entry this used to skip (claude-opus-4-7) turned out to be carrying
# the retired Opus 4.1 rate.
for label, rates in (("analyzer", analyzer_rates), ("installer", installer_rates)):
    unknown = sorted(set(rates) - set(PUBLISHED))
    if unknown:
        problems.append(f"{label}: no published rate recorded in this test for {unknown}")

# The last-resort rate must track the model the analyzer calls.
match = re.search(r'^SONNET_FALLBACK_MODEL = "([^"]+)"', analyzer_src, re.MULTILINE)
fallback_model = match.group(1) if match else None
if fallback_model != default_model:
    problems.append(
        f"SONNET_FALLBACK_MODEL is {fallback_model!r} but the analyzer calls {default_model!r}"
    )

print("OK" if not problems else "; ".join(problems))
PY
)

assert_eq "${RESULT}" "OK" "every default model has its published price in both pricing tables"

# The freshly-written config must name the same model the analyzer calls.
SEEDED_MODEL=$(grep -o '"default_model": "[^"]*"' "${INSTALLER}" | head -n 1 | sed 's/.*: "//; s/"//')
ANALYZER_MODEL=$(grep -o '^DEFAULT_MODEL="[^"]*"' "${ANALYZER}" | sed 's/.*="//; s/"//')
assert_eq "${SEEDED_MODEL}" "${ANALYZER_MODEL}" "autoheal-install.sh seeds the model the analyzer calls"

# ---------------------------------------------------------------------
# Upgrade path: an install still pinned to claude-sonnet-4-6 cannot honor
# structured outputs, so the idempotent merge must migrate it (#1034).
# Fresh-install seeding was already covered above; this is the path that
# actually exists on every machine that ran an earlier version.
# ---------------------------------------------------------------------

UPGRADE_TMP=$(mktemp -d -t autoheal_pricing_upgrade.XXXXXX)
cat > "${UPGRADE_TMP}/config.json" <<'JSON'
{
  "model": "claude-sonnet-4-6",
  "default_model": "claude-sonnet-4-6",
  "daily_cost_cap_usd": 10.00,
  "cost_pricing": {
    "claude-sonnet-4-6": {"input_per_million": 3, "output_per_million": 15}
  }
}
JSON

# Run only the installer's idempotent-merge python block against the
# fixture config, so the test does not install a LaunchAgent.
sed -n '/^DEFAULT_PRICING = {/,/^PY$/p' "${INSTALLER}" | sed '$d' > "${UPGRADE_TMP}/merge.py"
{
    echo "import json, sys"
    echo "path = sys.argv[1]"
    cat "${UPGRADE_TMP}/merge.py"
} > "${UPGRADE_TMP}/merge_runnable.py"

python3 "${UPGRADE_TMP}/merge_runnable.py" "${UPGRADE_TMP}/config.json" >/dev/null 2>&1

UPGRADED_MODEL=$(python3 -c "
import json, sys
cfg = json.load(open(sys.argv[1]))
print(cfg.get('default_model', ''))
" "${UPGRADE_TMP}/config.json")
assert_eq "${UPGRADED_MODEL}" "${ANALYZER_MODEL}" "an existing claude-sonnet-4-6 install is migrated to the analyzer's model"

UPGRADED_PLAIN_MODEL=$(python3 -c "
import json, sys
cfg = json.load(open(sys.argv[1]))
print(cfg.get('model', ''))
" "${UPGRADE_TMP}/config.json")
assert_eq "${UPGRADED_PLAIN_MODEL}" "${ANALYZER_MODEL}" "the legacy 'model' key is migrated too"

UPGRADED_PRICE=$(python3 -c "
import json, sys
cfg = json.load(open(sys.argv[1]))
entry = cfg.get('cost_pricing', {}).get(sys.argv[2], {})
print(f\"{entry.get('input_per_million')}/{entry.get('output_per_million')}\")
" "${UPGRADE_TMP}/config.json" "${ANALYZER_MODEL}")
assert_eq "${UPGRADED_PRICE}" "2/10" "the migrated model gets its price entry"

# A pin the operator chose deliberately is left alone.
cat > "${UPGRADE_TMP}/custom.json" <<'JSON'
{
  "default_model": "claude-opus-4-8",
  "cost_pricing": {"claude-opus-4-8": {"input_per_million": 5, "output_per_million": 25}}
}
JSON
python3 "${UPGRADE_TMP}/merge_runnable.py" "${UPGRADE_TMP}/custom.json" >/dev/null 2>&1
CUSTOM_MODEL=$(python3 -c "
import json, sys
print(json.load(open(sys.argv[1])).get('default_model', ''))
" "${UPGRADE_TMP}/custom.json")
assert_eq "${CUSTOM_MODEL}" "claude-opus-4-8" "a non-4-6 pin is never rewritten"

rm -rf "${UPGRADE_TMP}"

echo ""
echo "test-model-pricing-pin.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
