#!/usr/bin/env python3
# Epic 10: content TBD — PostToolUse scanner with async:true,
# asyncRewake:true. Reads realtime_alerts_enabled from
# ~/.claude/autoheal/config.json and exits 0 if disabled (default).
# See plan.md §3.6 and §5 Epic 10.
#
# The hook is registered unconditionally in settings.partial.json because
# JSON cannot express config-flag-conditional registration. The runtime
# gate on realtime_alerts_enabled lives here instead.
import sys

sys.exit(0)
