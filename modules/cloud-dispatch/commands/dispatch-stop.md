---
description: Stop all dispatched agents and optionally destroy cloud VMs
allowed-tools: Bash
---

# /dispatch-stop - Stop dispatched agents

Stop all running agents and optionally destroy VMs.

## Execution

### Step 1: Stop Agents

```bash
bash modules/cloud-dispatch/lib/agent-stop.sh --all
```

### Step 2: Collect Results

Pull any final results, PRs, or uncommitted work before cleanup:

```bash
bash modules/cloud-dispatch/lib/workspace-collect.sh --all
```

### Step 3: Ask About Cleanup

Ask the user:

"Agents stopped. What do you want to do with the VMs?
1. Keep running (reuse for another dispatch later - saves ~2 min boot time)
2. Destroy VMs (clean shutdown, stops billing)"

If the user chooses destroy:

```bash
# Revoke session SSH keys and clear secrets from tmpfs
bash modules/cloud-dispatch/lib/secrets-cleanup.sh

# Destroy all dispatch VMs
bash modules/cloud-dispatch/lib/vm-destroy.sh --all --force
```

Confirm destruction with a final status:
```bash
bash modules/cloud-dispatch/lib/vm-status.sh
```
