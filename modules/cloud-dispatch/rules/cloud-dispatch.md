# Cloud Dispatch Rules

Rules that apply when working with cloud-dispatched agents.

## VM Agent Behavior

When running as an agent on a cloud VM:
- Always create a feature branch before making changes
- Commit frequently (every significant change) for git-based recovery
- Create a PR when work is complete
- Never push directly to main
- Use --max-turns to prevent runaway execution

## Dispatch Workflow

When dispatching work to cloud VMs:
- Verify VMs are healthy before dispatching
- Use jittered starts to avoid rate limit thundering herd
- Monitor agent status periodically
- Collect results and clean up VMs when done
- Track costs and stay within budget

## Security

- Never embed secrets in cloud-init or commit them to git
- Use fine-grained GitHub PATs scoped to the target repo
- Session SSH keys are ephemeral - generated per session, revoked on cleanup
- Agent isolation: each agent runs as a separate Linux user with no sudo access
