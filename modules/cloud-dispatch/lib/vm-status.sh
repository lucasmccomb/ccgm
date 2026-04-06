#!/usr/bin/env bash
# vm-status.sh - List all running CCGM agent VMs with status details.
#
# Usage:
#   vm-status.sh
#
# Output:
#   Formatted table: NAME | IP | LOCATION | STATUS | UPTIME | TYPE
#
# Environment:
#   HCLOUD_TOKEN  Hetzner Cloud API token (required)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

require_cmd hcloud
require_cmd python3

if [[ -z "${HCLOUD_TOKEN:-}" ]]; then
  log_error "HCLOUD_TOKEN is not set. Export it before running this script."
  exit 1
fi

# ---------------------------------------------------------------------------
# Fetch and format VM list
# ---------------------------------------------------------------------------

log_info "Fetching VM list..."

python3 - <<'PYEOF'
import json
import subprocess
import sys
from datetime import datetime, timezone

result = subprocess.run(
    ["hcloud", "server", "list", "--output", "json"],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    print(f"ERROR: hcloud server list failed: {result.stderr}", file=sys.stderr)
    sys.exit(1)

servers = json.loads(result.stdout)

# Filter to ccgm-agent-* VMs only
servers = [s for s in servers if s.get("name", "").startswith("ccgm-agent-")]

if not servers:
    print("No ccgm-agent-* VMs found.")
    sys.exit(0)

# Sort by name for stable output
servers.sort(key=lambda s: s["name"])

# Column widths
col_name = max(len(s["name"]) for s in servers) + 2
col_ip   = 16
col_loc  = 8
col_stat = 10
col_up   = 16
col_type = 8

header = (
    f"{'NAME':<{col_name}}  {'IP':<{col_ip}}  {'LOC':<{col_loc}}"
    f"  {'STATUS':<{col_stat}}  {'UPTIME':<{col_up}}  {'TYPE':<{col_type}}"
)
sep = "-" * len(header)

print(header)
print(sep)

now = datetime.now(timezone.utc)
for s in servers:
    name   = s.get("name", "")
    ip     = s.get("public_net", {}).get("ipv4", {}).get("ip", "")
    loc    = s.get("datacenter", {}).get("location", {}).get("name", "")
    status = s.get("status", "")
    stype  = s.get("server_type", {}).get("name", "")

    created_str = s.get("created", "")
    if created_str:
        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            delta   = now - created
            total   = int(delta.total_seconds())
            hours, rem = divmod(total, 3600)
            mins        = rem // 60
            uptime  = f"{hours}h {mins}m"
        except ValueError:
            uptime = "unknown"
    else:
        uptime = "unknown"

    print(
        f"{name:<{col_name}}  {ip:<{col_ip}}  {loc:<{col_loc}}"
        f"  {status:<{col_stat}}  {uptime:<{col_up}}  {stype:<{col_type}}"
    )

print()
print(f"Total: {len(servers)} VM(s)")
PYEOF
