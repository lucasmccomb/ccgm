// tmux.go provides tmux-based process management for Claude Code agents.
// Instead of spawning claude as a child process with captured pipes, we launch
// it in a tmux session so it gets a real TTY and the user can attach to interact.
package agent

import (
	"fmt"
	"os/exec"
	"strings"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// TmuxSession represents a Claude Code agent running in a tmux session.
type TmuxSession struct {
	Name       string // tmux session name (same as agent ID)
	WorkingDir string
}

// TmuxLaunch creates a new tmux session running claude in the given directory.
// The session name is derived from the agent config ID.
func TmuxLaunch(cfg *types.AgentConfig) (*TmuxSession, error) {
	sessionName := "ccgm-" + cfg.ID

	// Build the claude command with model flag if specified.
	claudeCmd := "claude"
	if cfg.Model != "" {
		claudeCmd = fmt.Sprintf("claude --model %s", cfg.Model)
	}

	// Create a detached tmux session running claude.
	// tmux new-session -d -s {name} -c {workdir} "{command}"
	cmd := exec.Command("tmux", "new-session", "-d",
		"-s", sessionName,
		"-c", cfg.WorkingDir,
		claudeCmd,
	)

	if out, err := cmd.CombinedOutput(); err != nil {
		return nil, fmt.Errorf("tmux launch %q: %s: %w", sessionName, strings.TrimSpace(string(out)), err)
	}

	return &TmuxSession{
		Name:       sessionName,
		WorkingDir: cfg.WorkingDir,
	}, nil
}

// TmuxIsAlive checks if a tmux session exists and is running.
func TmuxIsAlive(sessionName string) bool {
	cmd := exec.Command("tmux", "has-session", "-t", sessionName)
	return cmd.Run() == nil
}

// TmuxKill kills a tmux session.
func TmuxKill(sessionName string) error {
	cmd := exec.Command("tmux", "kill-session", "-t", sessionName)
	if out, err := cmd.CombinedOutput(); err != nil {
		outStr := strings.TrimSpace(string(out))
		// Session already dead is not an error.
		if strings.Contains(outStr, "no server running") || strings.Contains(outStr, "session not found") {
			return nil
		}
		return fmt.Errorf("tmux kill %q: %s: %w", sessionName, outStr, err)
	}
	return nil
}

// TmuxCapture captures the visible content of a tmux pane.
// Returns the current screen content as a string.
func TmuxCapture(sessionName string) (string, error) {
	cmd := exec.Command("tmux", "capture-pane", "-t", sessionName, "-p", "-S", "-50")
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("tmux capture %q: %w", sessionName, err)
	}
	return string(out), nil
}

// TmuxAttachCmd returns the exec.Cmd to attach to a tmux session.
// The caller should use tea.ExecProcess to hand off the terminal.
func TmuxAttachCmd(sessionName string) *exec.Cmd {
	return exec.Command("tmux", "attach-session", "-t", sessionName)
}

// TmuxSessionName returns the tmux session name for an agent ID.
func TmuxSessionName(agentID string) string {
	return "ccgm-" + agentID
}
