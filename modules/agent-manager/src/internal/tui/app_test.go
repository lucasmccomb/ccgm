package tui_test

import (
	"testing"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/config"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/tui"
)

func newTestApp(t *testing.T) tui.AppModel {
	t.Helper()
	dir := t.TempDir()
	cfg := config.DefaultConfig()
	cfg.DataDir = dir
	mgr := agent.NewAgentManager(dir, cfg)
	return tui.NewApp(mgr, cfg)
}

func TestApp_InitialFocus(t *testing.T) {
	app := newTestApp(t)
	if !app.AgentListFocused() {
		t.Error("expected agent list to be focused on startup")
	}
}

func TestApp_WindowResizeSetsFullWidth(t *testing.T) {
	app := newTestApp(t)
	app = app.Resize(120, 40)

	lw, lh := app.AgentListSize()

	// Agent list should take the full width.
	if lw != 120 {
		t.Errorf("agent list width %d: expected 120 (full width)", lw)
	}

	// Height should be total - 2 (title + command bar).
	if lh != 38 {
		t.Errorf("agent list height %d: expected 38 (40 - 2)", lh)
	}
}
