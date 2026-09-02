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

# Published per-MTok list prices (input, output).
#
# Source: the Anthropic Current Models table and its per-model
# descriptions, checked 2026-09-02. Mythos 5 and 5.1 are priced at the
# Fable rate on the published statement that they are the same tier at
# the same per-token price. Opus 4.7 and 4.8 share a rate; the $15/$75
# that used to sit under the 4.7 key was the retired Opus 4.1 rate.
#
# Update this table in the same change that swaps or adds a model.
PUBLISHED = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # Priced but not gated: a config may still hold this pin (the
    # installer migrates it) and older cost.log rows name it.
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (5.0, 25.0),
}

# The two structured-outputs-capable models deliberately left out of the
# gate, with the reason. Recorded here so dropping one silently, or
# adding it back without a rate, fails rather than drifts.
UNPRICED_SO_UNGATED = {
    "claude-opus-4-1": "deprecated, retired 2026-08-05, no published rate",
    "claude-opus-4-5": "active and schema-capable, but no published rate",
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

# The config a FRESH install is handed. This is a third copy of the same
# table -- the one an operator actually runs against -- so it is checked
# like the other two rather than trusted to have been updated alongside.
try:
    seed_start = installer_src.index('{\n  "email_enabled"')
    seed_end = installer_src.index("\n}\nEOF", seed_start) + 2
    seed_cfg = json.loads(installer_src[seed_start:seed_end].replace("${WEBHOOK_TOKEN}", "x"))
    seeded_rates = {
        model: (float(entry["input_per_million"]), float(entry["output_per_million"]))
        for model, entry in (seed_cfg.get("cost_pricing") or {}).items()
    }
except (ValueError, KeyError, TypeError) as exc:
    seeded_rates = {}
    problems.append(f"the config autoheal-install.sh seeds is not readable JSON: {exc}")

if seeded_rates and seeded_rates != installer_rates:
    problems.append(
        "the seeded config cost_pricing and DEFAULT_PRICING disagree: "
        + str(sorted(set(seeded_rates) ^ set(installer_rates)) or "same models, different rates")
    )

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

# The gate and the pricing tables are one contract: a model the gate
# accepts must be priced in BOTH tables, or the run it allows would log
# every call at the fallback rate behind a warning -- the cost-log
# accuracy problem #1025 was filed about. And the gate's remediation
# message prints this same list, so a gate entry with no price would be
# the module recommending a config it cannot account for.
gate_match = re.search(r'^STRUCTURED_OUTPUT_MODELS="([^"]+)"', analyzer_src, re.MULTILINE)
gate = gate_match.group(1).split() if gate_match else []
if not gate:
    problems.append("STRUCTURED_OUTPUT_MODELS not found or empty")

for model in gate:
    if model not in PUBLISHED:
        problems.append(f"gate model {model} has no published rate in this test")
    for label, rates in (("analyzer FALLBACK_PRICING", analyzer_rates),
                         ("installer DEFAULT_PRICING", installer_rates),
                         ("the seeded config", seeded_rates)):
        if rates and model not in rates:
            problems.append(f"gate model {model} has no price entry in {label}")

# A model with no published rate must not be gated, whatever else
# changes. This is the half that keeps a retired or unpriced model from
# being quietly re-admitted.
for model, reason in UNPRICED_SO_UNGATED.items():
    if model in gate:
        problems.append(f"{model} is gated but {reason}")
    if model in PUBLISHED:
        problems.append(f"{model} has a rate in PUBLISHED but is recorded as unpriced")

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
