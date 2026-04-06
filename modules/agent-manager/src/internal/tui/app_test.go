package tui_test

import (
	"testing"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/tui"
)

// newTestApp builds a minimal AppModel for testing without starting I/O.
func newTestApp(t *testing.T) tui.AppModel {
	t.Helper()
	dir := t.TempDir()
	cfg := config.DefaultConfig()
	cfg.DataDir = dir
	mgr := agent.NewAgentManager(dir, cfg)
	return tui.NewApp(mgr, cfg)
}

// TestApp_InitialFocus verifies the agent list panel has focus on startup.
func TestApp_InitialFocus(t *testing.T) {
	app := newTestApp(t)
	// The agent list should be focused; the log viewer should not.
	if !app.AgentListFocused() {
		t.Error("expected agent list to be focused on startup")
	}
	if app.LogViewerFocused() {
		t.Error("expected log viewer NOT to be focused on startup")
	}
}

// TestApp_TabSwitchesFocus verifies that Tab toggles focus between panels.
func TestApp_TabSwitchesFocus(t *testing.T) {
	app := newTestApp(t)

	// Simulate Tab key.
	app = app.PressTab()
	if app.AgentListFocused() {
		t.Error("after Tab: expected agent list NOT to be focused")
	}
	if !app.LogViewerFocused() {
		t.Error("after Tab: expected log viewer to be focused")
	}

	// Tab again returns focus to agent list.
	app = app.PressTab()
	if !app.AgentListFocused() {
		t.Error("after second Tab: expected agent list to be focused")
	}
	if app.LogViewerFocused() {
		t.Error("after second Tab: expected log viewer NOT to be focused")
	}
}

// TestApp_WindowResizeDistributesSpace verifies that a resize message updates
// panel dimensions correctly.
func TestApp_WindowResizeDistributesSpace(t *testing.T) {
	app := newTestApp(t)

	// Apply a window resize.
	app = app.Resize(120, 40)

	lw, lh := app.AgentListSize()
	rw, rh := app.LogViewerSize()

	// Agent list should be ~40% of 120 = 48.
	if lw < 40 || lw > 60 {
		t.Errorf("agent list width %d: expected ~48 (40%% of 120)", lw)
	}

	// Log viewer should take the rest.
	total := lw + rw
	if total != 120 {
		t.Errorf("panel widths sum to %d, expected 120", total)
	}

	// Both panels should share the available height (total - 2 for title+bar).
	if lh != rh {
		t.Errorf("agent list height %d != log viewer height %d", lh, rh)
	}
	if lh != 38 {
		t.Errorf("panel height %d: expected 38 (40 - 2 title/cmdbar rows)", lh)
	}
}
