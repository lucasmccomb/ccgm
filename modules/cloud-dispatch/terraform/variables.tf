variable "hcloud_token" {
  description = "Hetzner Cloud API token (read/write). Found in Hetzner Cloud Console > Security > API Tokens."
  type        = string
  sensitive   = true
}

variable "orchestrator_ip" {
  description = "IP address of the orchestrating MacBook in CIDR notation (e.g. 203.0.113.10/32). Only this IP is allowed inbound SSH access to agent VMs."
  type        = string

  validation {
    condition     = can(cidrhost(var.orchestrator_ip, 0))
    error_message = "orchestrator_ip must be a valid CIDR block (e.g. 203.0.113.10/32)."
  }
}

variable "ssh_public_key" {
  description = "SSH public key for VM access. The corresponding private key must remain on the orchestrating machine. Paste the full public key string (e.g. 'ssh-ed25519 AAAA...')."
  type        = string
}

variable "project_name" {
  description = "Project name prefix used for naming Hetzner resources."
  type        = string
  default     = "ccgm-dispatch"
}
