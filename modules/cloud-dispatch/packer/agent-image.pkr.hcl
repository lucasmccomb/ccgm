packer {
  required_version = ">= 1.9.0"

  required_plugins {
    hcloud = {
      version = ">= 1.4.0"
      source  = "github.com/hetznercloud/hcloud"
    }
  }
}

variable "hcloud_token" {
  type        = string
  description = "Hetzner Cloud API token (read from HCLOUD_TOKEN env var)"
  sensitive   = true
  default     = env("HCLOUD_TOKEN")
}

variable "image_version" {
  type        = string
  description = "Snapshot version tag (e.g. 1.0.0)"
  default     = "1.0.0"
}

variable "node_version" {
  type        = string
  description = "Node.js major version to install"
  default     = "22"
}

variable "claude_code_version" {
  type        = string
  description = "Claude Code npm package version to pin"
  default     = "1.2.3"
}

source "hcloud" "agent" {
  token       = var.hcloud_token
  image       = "ubuntu-22.04"
  location    = "fsn1"
  server_type = "cx22"
  ssh_username = "root"

  snapshot_name   = "ccgm-agent-${var.image_version}"
  snapshot_labels = {
    version   = var.image_version
    managed   = "packer"
    purpose   = "ccgm-agent"
    base_os   = "ubuntu-22.04"
    node      = "v${var.node_version}"
  }
}

build {
  name    = "ccgm-agent-image"
  sources = ["source.hcloud.agent"]

  # Wait for cloud-init to finish before provisioning
  provisioner "shell" {
    inline = [
      "cloud-init status --wait || true",
      "apt-get update -y"
    ]
  }

  # 1. Install development toolchain
  provisioner "shell" {
    script = "scripts/install-tools.sh"
    environment_vars = [
      "NODE_VERSION=${var.node_version}",
      "CLAUDE_CODE_VERSION=${var.claude_code_version}"
    ]
    execute_command = "chmod +x '{{ .Path }}' && env {{ .Vars }} bash -eu '{{ .Path }}'"
  }

  # 2. Create agent users and shared directories
  provisioner "shell" {
    script          = "scripts/setup.sh"
    execute_command = "chmod +x '{{ .Path }}' && bash -eu '{{ .Path }}'"
  }

  # 3. Apply security hardening (iptables, sshd config, unattended-upgrades)
  provisioner "shell" {
    script          = "scripts/security-hardening.sh"
    execute_command = "chmod +x '{{ .Path }}' && bash -eu '{{ .Path }}'"
  }

  # 4. Validate the image looks correct before snapshotting
  provisioner "shell" {
    script          = "scripts/validate.sh"
    execute_command = "chmod +x '{{ .Path }}' && bash -eu '{{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "packer-manifest.json"
    strip_path = true
  }
}
