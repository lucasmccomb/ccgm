---
description: Manage Hetzner Cloud VMs for agent dispatch - create, destroy, status, health checks, and SSH access
allowed-tools: Bash
---

# /vm-manage - Manage cloud VMs

Manage Hetzner Cloud VMs for agent dispatch.

## Usage

The user will specify an action:
- `create [N]` - Create N VMs (default 3)
- `destroy [--all | name]` - Destroy one or all VMs
- `status` - List all VMs and their current state
- `health` - Run health checks on all VMs
- `ssh <name>` - Open an SSH session into a VM

## Execution

Parse the action from the user's message and run the corresponding script:

```bash
# For create:
bash modules/cloud-dispatch/lib/vm-create.sh $N

# For destroy (all):
bash modules/cloud-dispatch/lib/vm-destroy.sh --all

# For destroy (specific VM):
bash modules/cloud-dispatch/lib/vm-destroy.sh $VM_NAME

# For status:
bash modules/cloud-dispatch/lib/vm-status.sh

# For health:
bash modules/cloud-dispatch/lib/vm-health.sh --all

# For ssh:
bash modules/cloud-dispatch/lib/vm-ssh.sh $VM_NAME
```

After running each command, display the output clearly. For `status`, format it as a table showing VM name, IP, state, and uptime.
