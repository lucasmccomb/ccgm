// discover.go scans the system for running Claude Code processes and registers
// them as discovered agents so the TUI can display and manage them.
package agent

import (
	"fmt"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// DiscoveredProcess holds info about a running Claude Code process found via ps.
type DiscoveredProcess struct {
	PID        int
	WorkingDir string
	Command    string
}

// DiscoverClaudeProcesses finds running Claude Code CLI processes by scanning
// the process table. Returns only main Claude sessions (filters out plugins,
// subprocesses, and the agent-manager itself).
func DiscoverClaudeProcesses() ([]DiscoveredProcess, error) {
	// Find PIDs of processes whose command starts with "claude ".
	pgrepOut, err := exec.Command("pgrep", "-f", "^claude ").Output()
	if err != nil {
		// pgrep returns exit code 1 when no matches found - that's not an error.
		if exitErr, ok := err.(*exec.ExitError); ok && exitErr.ExitCode() == 1 {
			return nil, nil
		}
		return nil, fmt.Errorf("discover: pgrep: %w", err)
	}

	lines := strings.Split(strings.TrimSpace(string(pgrepOut)), "\n")
	if len(lines) == 0 || (len(lines) == 1 && lines[0] == "") {
		return nil, nil
	}

	var discovered []DiscoveredProcess
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		pid, err := strconv.Atoi(line)
		if err != nil {
			continue
		}

		// Get command line for this PID.
		cmdOut, err := exec.Command("ps", "-o", "command=", "-p", strconv.Itoa(pid)).Output()
		if err != nil {
			continue
		}
		cmdLine := strings.TrimSpace(string(cmdOut))

		// Skip non-session processes (plugins, bun subprocesses, etc).
		if !isClaudeSession(cmdLine) {
			continue
		}

		// Get working directory via lsof.
		cwd := getProcessCwd(pid)
		if cwd == "" {
			continue
		}

		discovered = append(discovered, DiscoveredProcess{
			PID:        pid,
			WorkingDir: cwd,
			Command:    cmdLine,
		})
	}

	return discovered, nil
}

// isClaudeSession returns true if the command line looks like a Claude Code
// interactive session (not a plugin, subprocess, or bun runner).
func isClaudeSession(cmdLine string) bool {
	if !strings.HasPrefix(cmdLine, "claude ") && cmdLine != "claude" {
		return false
	}
	// Filter out plugin/bun subprocesses.
	if strings.Contains(cmdLine, "bun") || strings.Contains(cmdLine, "plugin") {
		return false
	}
	return true
}

// getProcessCwd returns the current working directory of a process on macOS
// using lsof. Returns empty string on failure.
func getProcessCwd(pid int) string {
	out, err := exec.Command("lsof", "-a", "-d", "cwd", "-p", strconv.Itoa(pid), "-Fn").Output()
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(out), "\n") {
		if strings.HasPrefix(line, "n/") {
			return strings.TrimPrefix(line, "n")
		}
	}
	return ""
}

// RegisterDiscovered adds discovered system processes to the AgentManager as
// read-only monitored agents. These agents were not spawned by the manager,
// so they have no stdout/stderr pipes - only PID-based health monitoring.
func (m *AgentManager) RegisterDiscovered(procs []DiscoveredProcess) int {
	m.mu.Lock()
	defer m.mu.Unlock()

	count := 0
	for _, proc := range procs {
		// Derive a name from the working directory.
		name := filepath.Base(proc.WorkingDir)
		id := fmt.Sprintf("discovered-%d", proc.PID)

		// Skip if we already track this PID.
		alreadyTracked := false
		for _, existing := range m.agents {
			if existing.State.PID == proc.PID {
				alreadyTracked = true
				break
			}
		}
		if alreadyTracked {
			continue
		}

		// Verify the process is actually alive before registering.
		if err := syscall.Kill(proc.PID, 0); err != nil {
			continue
		}

		cfg := types.AgentConfig{
			ID:         id,
			Name:       name,
			Command:    "claude",
			WorkingDir: proc.WorkingDir,
			RestartPolicy: types.RestartPolicy{
				Type: "never", // don't restart discovered processes
			},
		}

		ma := &ManagedAgent{
			Config:  cfg,
			Process: nil, // no process handle - we didn't spawn it
			State: types.AgentState{
				Config:    cfg,
				PID:       proc.PID,
				Status:    types.StatusRunning,
				StartedAt: time.Now(), // approximate - we don't know actual start time
			},
		}

		m.agents[id] = ma
		count++
	}
	return count
}
