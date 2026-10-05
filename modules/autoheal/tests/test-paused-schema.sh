#!/usr/bin/env bash
# test-paused-schema.sh
#
# lib/repo-config-schema.json lists the boolean `paused` key that
# autoheal-daily.sh honours (#1110), so a per-repo config using it validates.
#
# Run: bash modules/autoheal/tests/test-paused-schema.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA="${SCRIPT_DIR}/../lib/repo-config-schema.json"

OUT="$(python3 - "${SCHEMA}" <<'PY'
import json
import sys

p = json.load(open(sys.argv[1]))["properties"].get("paused")
print("ok" if p and p.get("type") == "boolean" else "missing")
PY
)"
if [ "${OUT}" = "ok" ]; then
    echo "test-paused-schema.sh: 1 passed, 0 failed"
    exit 0
fi
echo "FAIL: schema lacks boolean paused"
exit 1
