// tmux.go provides tmux pane-based process management for Claude Code agents.
// The agent manager runs in a left pane, and each agent gets its own pane
// in the same tmux window. Users navigate with standard tmux keybindings.
package agent

import (
	"fmt"
	"os/exec"
	"strings"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// TmuxSessionName is the tmux session name used by the agent manager.
const TmuxSessionName = "ccgm-am"

// TmuxPaneInfo holds the tmux pane ID for a launched agent.
type TmuxPaneInfo struct {
	PaneID string // e.g., "%5"
}

// TmuxLaunchPane creates a new tmux pane running claude in the given directory.
// The pane is created by splitting the current window horizontally (new pane
// appears to the right). Returns the pane ID.
func TmuxLaunchPane(cfg *types.AgentConfig) (*TmuxPaneInfo, error) {
	// Build the claude command.
	claudeCmd := "claude"
	if cfg.Model != "" {
		claudeCmd = fmt.Sprintf("claude --model %s", cfg.Model)
	}

	// Split the window horizontally, creating a new pane to the right.
	// -d: don't switch focus to the new pane (keep focus on the manager)
	// -c: set the working directory
	// -P -F '#{pane_id}': print the new pane's ID
	cmd := exec.Command("tmux", "split-window", "-h",
		"-d",
		"-c", cfg.WorkingDir,
		"-P", "-F", "#{pane_id}",
		claudeCmd,
	)

	out, err := cmd.Output()
	if err != nil {
		stderr := ""
		if exitErr, ok := err.(*exec.ExitError); ok {
			stderr = string(exitErr.Stderr)
		}
		return nil, fmt.Errorf("tmux split-window: %s: %w", strings.TrimSpace(stderr), err)
	}

	paneID := strings.TrimSpace(string(out))
	if paneID == "" {
		return nil, fmt.Errorf("tmux split-window: empty pane ID")
	}

	// Rebalance panes so they're evenly distributed.
	_ = exec.Command("tmux", "select-layout", "main-vertical").Run()

	return &TmuxPaneInfo{PaneID: paneID}, nil
}

// TmuxPaneIsAlive checks if a tmux pane exists.
func TmuxPaneIsAlive(paneID string) bool {
	cmd := exec.Command("tmux", "list-panes", "-F", "#{pane_id}")
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(out), "\n") {
		if strings.TrimSpace(line) == paneID {
			return true
		}
	}
	return false
}

// TmuxKillPane kills a specific tmux pane.
func TmuxKillPane(paneID string) error {
	cmd := exec.Command("tmux", "kill-pane", "-t", paneID)
	if out, err := cmd.CombinedOutput(); err != nil {
		outStr := strings.TrimSpace(string(out))
		if strings.Contains(outStr, "no server running") || strings.Contains(outStr, "can't find") {
			return nil
		}
		return fmt.Errorf("tmux kill-pane %q: %s: %w", paneID, outStr, err)
	}
	return nil
}

// TmuxCapturePane captures the visible content of a tmux pane.
func TmuxCapturePane(paneID string) (string, error) {
	cmd := exec.Command("tmux", "capture-pane", "-t", paneID, "-p", "-S", "-50")
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("tmux capture-pane %q: %w", paneID, err)
	}
	return string(out), nil
}

// TmuxSelectPane focuses a specific pane.
func TmuxSelectPane(paneID string) error {
	cmd := exec.Command("tmux", "select-pane", "-t", paneID)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("tmux select-pane %q: %s: %w", paneID, strings.TrimSpace(string(out)), err)
	}
	return nil
}

// TmuxIsInsideSession returns true if we're currently running inside tmux.
func TmuxIsInsideSession() bool {
	cmd := exec.Command("tmux", "display-message", "-p", "#{session_name}")
	return cmd.Run() == nil
}

// Legacy session-based functions (kept for backward compatibility with state files).

// TmuxIsAlive checks if a tmux session exists. Used for legacy re-attachment.
func TmuxIsAlive(sessionName string) bool {
	cmd := exec.Command("tmux", "has-session", "-t", sessionName)
	return cmd.Run() == nil
}

// TmuxKill kills a tmux session. Used for legacy cleanup.
func TmuxKill(sessionName string) error {
	cmd := exec.Command("tmux", "kill-session", "-t", sessionName)
	if out, err := cmd.CombinedOutput(); err != nil {
		outStr := strings.TrimSpace(string(out))
		if strings.Contains(outStr, "no server running") || strings.Contains(outStr, "session not found") {
			return nil
		}
		return fmt.Errorf("tmux kill %q: %s: %w", sessionName, outStr, err)
	}
	return nil
}

// TmuxCapture captures content from a tmux session's first pane. Legacy.
func TmuxCapture(sessionName string) (string, error) {
	cmd := exec.Command("tmux", "capture-pane", "-t", sessionName, "-p", "-S", "-50")
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("tmux capture %q: %w", sessionName, err)
	}
	return string(out), nil
}

// TmuxAttachCmd returns the command to attach to a tmux session. Legacy.
func TmuxAttachCmd(sessionName string) *exec.Cmd {
	return exec.Command("tmux", "attach-session", "-t", sessionName)
}
