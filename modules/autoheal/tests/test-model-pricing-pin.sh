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
PUBLISHED = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
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
# swap could carry a stale price forward unnoticed.
for label, rates in (("analyzer", analyzer_rates), ("installer", installer_rates)):
    unknown = sorted(set(rates) - set(PUBLISHED) - {"claude-opus-4-7"})
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

echo ""
echo "test-model-pricing-pin.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
