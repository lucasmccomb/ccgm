#!/usr/bin/env bash
# test-packs-migration.sh — Migration completeness gate for /audit packs.
#
# Verifies that all canonical pack directories have been migrated from the
# Category Prompts in SKILL.md to registry packs.
#
# Canonical pack list (one per original Agent):
#   security, dependencies, code-quality, typescript-react, architecture,
#   performance, testing, documentation, tos-compliance
#
# Modes:
#   (default) STRICT: fail if any canonical pack dir is missing pack.json or checks.md.
#   --allow-partial: skip missing dirs with a SKIP note; validate only present ones.
#                    Used while migration batches 2 and 3 are still in flight.
#
# Checks performed on each PRESENT pack dir:
#   1. pack.json exists
#   2. checks.md exists
#   3. python3 scripts/lint-pack.py passes (schema + required sections + rubric membership)
#   4. checks.md contains a ## Migration Mapping section
#
# Additional checks when tos-compliance is present:
#   5. checks.md covers all 4 compliance surfaces:
#      - license-compliance (surface 1)
#      - third-party API/service ToS (surface 2)
#      - store/platform policy (surface 3)
#      - AI/LLM provider ToS (surface 4)
#
# Exit: 0 if all checks pass (with --allow-partial, missing packs count as skipped not failed)
#       1 if any check fails
#
# Usage:
#   bash test-packs-migration.sh               # strict: all canonical packs required
#   bash test-packs-migration.sh --allow-partial  # partial: validate only present packs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKS_DIR="${AUDIT_DIR}/packs"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"

# ---------------------------------------------------------------------------
# Canonical pack list (all epics combined)
# ---------------------------------------------------------------------------
CANONICAL_PACKS=(
    "security"
    "dependencies"
    "code-quality"
    "typescript-react"
    "architecture"
    "performance"
    "testing"
    "documentation"
    "tos-compliance"
)

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
ALLOW_PARTIAL=false
for arg in "$@"; do
    case "$arg" in
        --allow-partial)
            ALLOW_PARTIAL=true
            ;;
        *)
            printf 'Unknown argument: %s\n' "$arg" >&2
            printf 'Usage: %s [--allow-partial]\n' "$0" >&2
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Counters and helpers
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
SKIP=0

pass() { printf "  PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }
skip() { printf "  SKIP: %s\n" "$1"; SKIP=$((SKIP + 1)); }

# ---------------------------------------------------------------------------
# Run lint-pack.py once for the entire packs directory before the per-pack loop
# ---------------------------------------------------------------------------
LINT_OUTPUT=""
LINT_OVERALL_PASS=true
LINT_OUTPUT=$(python3 "${LINTER}" --packs-dir "${PACKS_DIR}" 2>&1) || LINT_OVERALL_PASS=false

# ---------------------------------------------------------------------------
# Check each canonical pack
# ---------------------------------------------------------------------------
for pack_name in "${CANONICAL_PACKS[@]}"; do
    pack_dir="${PACKS_DIR}/${pack_name}"
    printf "\n--- Checking pack: %s\n" "${pack_name}"

    # ---- Missing directory handling ----
    if [[ ! -d "${pack_dir}" ]]; then
        if [[ "${ALLOW_PARTIAL}" == "true" ]]; then
            skip "${pack_name}: directory not present (--allow-partial mode)"
            continue
        else
            fail "${pack_name}: directory missing (expected ${pack_dir})"
            continue
        fi
    fi

    # ---- 1. pack.json exists ----
    if [[ ! -f "${pack_dir}/pack.json" ]]; then
        if [[ "${ALLOW_PARTIAL}" == "true" ]]; then
            skip "${pack_name}: pack.json missing (--allow-partial mode)"
            continue
        else
            fail "${pack_name}: pack.json missing"
            continue
        fi
    else
        pass "${pack_name}: pack.json present"
    fi

    # ---- 2. checks.md exists ----
    if [[ ! -f "${pack_dir}/checks.md" ]]; then
        if [[ "${ALLOW_PARTIAL}" == "true" ]]; then
            skip "${pack_name}: checks.md missing (--allow-partial mode)"
            continue
        else
            fail "${pack_name}: checks.md missing"
            continue
        fi
    else
        pass "${pack_name}: checks.md present"
    fi

    # ---- 3. lint-pack.py result for this pack (from pre-run output above) ----
    # Filter the single lint run's output to this pack's result line
    if echo "${LINT_OUTPUT}" | grep -q "^PASS: ${pack_name}$"; then
        pass "${pack_name}: lint-pack.py passed"
    elif echo "${LINT_OUTPUT}" | grep -q "^FAIL: ${pack_name}$"; then
        # Extract error lines specific to this pack
        pack_errors=$(echo "${LINT_OUTPUT}" | grep -A 20 "^FAIL: ${pack_name}$" | grep "ERROR:" | head -10 || true)
        fail "${pack_name}: lint-pack.py failed — ${pack_errors}"
    else
        # lint-pack.py ran but result for this pack is unclear — treat as failure
        fail "${pack_name}: lint-pack.py output did not include result for this pack"
    fi

    # ---- 4. checks.md contains ## Migration Mapping section ----
    if grep -qi "^## Migration Mapping" "${pack_dir}/checks.md"; then
        pass "${pack_name}: checks.md contains ## Migration Mapping section"
    else
        fail "${pack_name}: checks.md missing required ## Migration Mapping section"
    fi

    # ---- 5. ToS-specific surface coverage (only for tos-compliance pack) ----
    if [[ "${pack_name}" == "tos-compliance" ]]; then
        checks_md="${pack_dir}/checks.md"

        # Surface 1: license compliance
        if grep -qi "license.compliance\|copyleft\|non.commercial\|attribution\|unlicensed" "${checks_md}"; then
            pass "tos-compliance: checks.md covers Surface 1 (license compliance)"
        else
            fail "tos-compliance: checks.md does not cover Surface 1 (license compliance)"
        fi

        # Surface 2: third-party API/service ToS
        if grep -qi "third.party\|api.*tos\|service.*tos\|scraping\|credential.misuse" "${checks_md}"; then
            pass "tos-compliance: checks.md covers Surface 2 (third-party API/service ToS)"
        else
            fail "tos-compliance: checks.md does not cover Surface 2 (third-party API/service ToS)"
        fi

        # Surface 3: store/platform policy
        if grep -qi "store.*policy\|platform.*policy\|chrome.*web.*store\|app.*store\|google.*play\|extension.*permissions" "${checks_md}"; then
            pass "tos-compliance: checks.md covers Surface 3 (store/platform policy)"
        else
            fail "tos-compliance: checks.md does not cover Surface 3 (store/platform policy)"
        fi

        # Surface 4: AI/LLM provider ToS
        if grep -qi "ai.*tos\|llm.*provider\|ai.*provider\|openai\|anthropic" "${checks_md}"; then
            pass "tos-compliance: checks.md covers Surface 4 (AI/LLM provider ToS)"
        else
            fail "tos-compliance: checks.md does not cover Surface 4 (AI/LLM provider ToS)"
        fi
    fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\n=== Results: %d passed, %d failed, %d skipped ===\n" "${PASS}" "${FAIL}" "${SKIP}"

if [[ "${FAIL}" -gt 0 ]]; then
    printf "MIGRATION GATE: FAIL (%d error(s))\n" "${FAIL}"
    exit 1
fi

if [[ "${SKIP}" -gt 0 ]]; then
    printf "MIGRATION GATE: PASS (with %d skipped — run without --allow-partial to enforce full set)\n" "${SKIP}"
else
    printf "MIGRATION GATE: PASS (all %d canonical packs present and valid)\n" "${#CANONICAL_PACKS[@]}"
fi
exit 0
