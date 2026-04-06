---
description: Check the status of dispatched agents across all cloud VMs
allowed-tools: Bash
---

# /dispatch-status - Check agent status

Check the status of dispatched agents across all cloud VMs.

## Execution

### Step 1: Check Agent Status

```bash
bash modules/cloud-dispatch/lib/agent-status.sh --all
```

### Step 2: Collect Results

Pull PR URLs and completed work from all VMs:

```bash
bash modules/cloud-dispatch/lib/workspace-collect.sh --all
```

### Step 3: Present Summary

Format and present the results showing each agent's:
- VM name and agent slot (e.g. ccgm-agent-1 / agent-0)
- Assigned issue number
- Status: running / completed / failed / idle
- PR URL (if a PR was opened)
- Last git commit message (if available)

If all agents have completed, remind the user they can run `/dispatch-stop` to clean up.
