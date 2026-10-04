#!/usr/bin/env bash
# Runs the ccgm-etp-receipts unit tests.
set -euo pipefail
exec python3 "$(cd "$(dirname "$0")" && pwd)/test_etp_receipts.py"
