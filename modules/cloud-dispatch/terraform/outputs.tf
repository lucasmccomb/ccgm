output "firewall_id" {
  description = "ID of the agent firewall resource. Pass this when creating VMs so they inherit the SSH restriction."
  value       = hcloud_firewall.agent_firewall.id
}

output "ssh_key_id" {
  description = "ID of the SSH key resource in Hetzner. Pass this when creating VMs so the orchestrator can connect."
  value       = hcloud_ssh_key.dispatch_key.id
}

output "network_id" {
  description = "ID of the private agent network. Pass this when creating VMs to attach them to the private network."
  value       = hcloud_network.agent_network.id
}

output "next_steps" {
  description = "Guidance for using these resources."
  value       = <<-EOT
    Infrastructure is ready. To provision agent VMs, use the hcloud CLI or cloud-dispatch scripts:

      hcloud server create \
        --name <agent-name> \
        --type cx22 \
        --image <packer-snapshot-id> \
        --ssh-key ${hcloud_ssh_key.dispatch_key.id} \
        --firewall ${hcloud_firewall.agent_firewall.id} \
        --network ${hcloud_network.agent_network.id}

    VMs are ephemeral - destroy them after each session to avoid charges.
  EOT
}
