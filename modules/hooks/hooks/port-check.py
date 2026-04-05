#!/usr/bin/env python3
"""
PreToolUse:Bash hook that intercepts dev server commands and ensures correct
port allocation based on the port registry and .env.clone identity.

DETECTS: Commands that launch dev servers (vite, wrangler dev, npm run dev,
pnpm dev, next dev, browser-sync, etc.)

CHECKS:
1. Resolves the correct port from port-registry.json + .env.clone
2. Checks if that port is already in use by another process
3. If a collision is found, warns with the PID and suggests action
4. If the command uses a wrong port (hardcoded or default), warns

OUTPUT: Prints a status message to stderr for the agent to see.
Does NOT block - only warns. The agent should act on the warning.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REGISTRY_PATH = Path.home() / ".claude" / "port-registry.json"

# Patterns that indicate a dev server is being launched
DEV_SERVER_PATTERNS = [
    r'\bvite\b',
    r'\bwrangler\s+dev\b',
    r'\bnpm\s+run\s+dev\b',
    r'\bpnpm\s+(run\s+)?dev\b',
    r'\bnext\s+dev\b',
    r'\bbrowser-sync\s+start\b',
    r'\bastro\s+dev\b',
    r'\btsx\s+watch\b',
    r'\bnode\s+.*server',
    r'\bconcurrently\b.*\bdev\b',
]

# Patterns to extract --port from command
PORT_FLAG_PATTERN = re.compile(r'--port[=\s]+(\d+)')
PORT_EXPR_PATTERN = re.compile(r'--port\s+\$\(\(([^)]+)\)\)')


def load_registry():
    """Load port registry."""
    try:
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def get_repo_name():
    """Derive repo name from git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            name = url.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            return name
    except Exception:
        pass
    return None


def get_env_clone():
    """Read .env.clone from current directory."""
    env_clone = {}
    env_path = Path.cwd() / ".env.clone"
    if env_path.exists():
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        env_clone[key.strip()] = val.strip()
        except Exception:
            pass
    return env_clone


def get_port_offset(env_clone):
    """Get port offset from .env.clone."""
    if "PORT_OFFSET" in env_clone:
        try:
            return int(env_clone["PORT_OFFSET"])
        except ValueError:
            pass
    if "CLONE_NUMBER" in env_clone:
        try:
            return int(env_clone["CLONE_NUMBER"])
        except ValueError:
            pass
    # Try deriving from directory name
    dirname = Path.cwd().name
    # Workspace model: extract w and c numbers
    wc_match = re.search(r'w(\d+)-c(\d+)$', dirname)
    if wc_match:
        w, c = int(wc_match.group(1)), int(wc_match.group(2))
        return w * 4 + c  # Assumes 4 clones per workspace
    # Flat clone model: extract trailing number
    num_match = re.search(r'(\d+)$', dirname)
    if num_match:
        return int(num_match.group(1))
    return 0


def check_port_in_use(port):
    """Check if a port is in use. Returns (pid, process_name) or None."""
    try:
        result = subprocess.run(
            ["lsof", "-iTCP:" + str(port), "-sTCP:LISTEN", "-P", "-n", "-t"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip().split("\n")[0]
            # Get process name
            ps_result = subprocess.run(
                ["ps", "-p", pid, "-o", "comm="],
                capture_output=True, text=True, timeout=2,
            )
            proc_name = ps_result.stdout.strip() if ps_result.returncode == 0 else "unknown"
            return (pid, proc_name)
    except Exception:
        pass
    return None


def is_dev_server_command(command):
    """Check if command launches a dev server."""
    for pattern in DEV_SERVER_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def extract_port_from_command(command):
    """Try to extract a hardcoded port from the command."""
    match = PORT_FLAG_PATTERN.search(command)
    if match:
        return int(match.group(1))
    return None


def determine_service_type(command):
    """Determine if this is a frontend or backend service."""
    cmd_lower = command.lower()
    if "wrangler" in cmd_lower:
        return "backend"
    if "tsx" in cmd_lower and ("server" in cmd_lower or "watch" in cmd_lower):
        return "backend"
    if "api" in cmd_lower:
        return "backend"
    # Default to frontend
    return "frontend"


def main():
    try:
        tool_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError, ValueError):
        return  # Silently allow on invalid input

    command = tool_input.get("command", "")

    # Only care about dev server commands
    if not is_dev_server_command(command):
        return

    registry = load_registry()
    if not registry:
        print("WARNING: Port registry (~/.claude/port-registry.json) not found. "
              "Cannot validate port allocation.", file=sys.stderr)
        return

    repo_name = get_repo_name()
    if not repo_name or repo_name not in registry.get("repos", {}):
        # Not a registered repo, skip
        return

    repo_config = registry["repos"][repo_name]
    env_clone = get_env_clone()
    port_offset = get_port_offset(env_clone)
    service_type = determine_service_type(command)
    base_port = repo_config.get(service_type)

    if base_port is None:
        return

    expected_port = base_port + port_offset
    agent_id = env_clone.get("AGENT_ID", f"offset-{port_offset}")

    # Check if the command specifies a different port
    cmd_port = extract_port_from_command(command)

    messages = []

    if cmd_port is not None and cmd_port != expected_port:
        messages.append(
            f"PORT MISMATCH: Command uses port {cmd_port} but registry assigns "
            f"port {expected_port} for {repo_name} {service_type} ({agent_id}). "
            f"Use --port {expected_port} instead."
        )

    # Check if expected port is already in use
    in_use = check_port_in_use(expected_port)
    if in_use:
        pid, proc_name = in_use
        messages.append(
            f"PORT CONFLICT: Port {expected_port} ({repo_name} {service_type}, "
            f"{agent_id}) is already in use by {proc_name} (PID {pid}). "
            f"Kill it with: kill {pid}"
        )

    # Also check if the command port is in use (if different from expected)
    if cmd_port is not None and cmd_port != expected_port:
        in_use_cmd = check_port_in_use(cmd_port)
        if in_use_cmd:
            pid, proc_name = in_use_cmd
            messages.append(
                f"PORT CONFLICT: Command port {cmd_port} is already in use by "
                f"{proc_name} (PID {pid})."
            )

    # If no explicit port in command and not using expected, suggest it
    if cmd_port is None and port_offset > 0:
        messages.append(
            f"PORT INFO: {repo_name} {service_type} ({agent_id}) should use "
            f"port {expected_port} (base {base_port} + offset {port_offset}). "
            f"Ensure --port {expected_port} is passed or .env.clone is read by the dev config."
        )

    if messages:
        # Output as a structured warning
        output = {
            "decision": "warn",
            "reason": " | ".join(messages)
        }
        print(json.dumps(output))
    # If no messages, silently allow


if __name__ == "__main__":
    main()
