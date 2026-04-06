terraform {
  required_version = ">= 1.5.0"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

# Firewall restricts inbound SSH to the orchestrator IP only.
# VMs provisioned by cloud-dispatch are tagged with this firewall
# so that only the orchestrating machine can reach them.
resource "hcloud_firewall" "agent_firewall" {
  name = "${var.project_name}-firewall"

  # Allow inbound SSH from orchestrator only
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = [var.orchestrator_ip]
    description = "Allow SSH from orchestrator machine only"
  }

  # Allow all outbound traffic (further restricted by iptables on each VM)
  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "icmp"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }
}

# SSH key uploaded to Hetzner so VMs can be provisioned with it.
# This is the orchestrator's public key - private key stays on the MacBook.
resource "hcloud_ssh_key" "dispatch_key" {
  name       = "${var.project_name}-key"
  public_key = var.ssh_public_key
}

# Private network for agent VMs.
# VMs don't require internal communication, but having a private network
# avoids routing through the public internet if VM-to-VM communication
# is ever needed. Each datacenter location gets its own subnet.
resource "hcloud_network" "agent_network" {
  name     = "${var.project_name}-network"
  ip_range = "10.0.0.0/16"
}

resource "hcloud_network_subnet" "fsn1" {
  network_id   = hcloud_network.agent_network.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.0.1.0/24"
}

resource "hcloud_network_subnet" "nbg1" {
  network_id   = hcloud_network.agent_network.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.0.2.0/24"
}

resource "hcloud_network_subnet" "hel1" {
  network_id   = hcloud_network.agent_network.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.0.3.0/24"
}
