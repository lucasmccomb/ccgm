package tui_test

import (
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/tui"
)

func TestCommandBar_AgentListContext(t *testing.T) {
	m := tui.NewCommandBarModel(tui.DefaultKeyMap)
	m.SetWidth(120)

	view := m.View()

	// All agent-list hints must appear.
	for _, want := range []string{"n", "new", "s", "stop", "r", "restart", "x", "kill", "/", "filter", "tab", "logs", "?", "help", "q", "quit"} {
		if !strings.Contains(view, want) {
			t.Errorf("agent-list view missing %q\nfull view: %q", want, view)
		}
	}
}

func TestCommandBar_LogViewerContext(t *testing.T) {
	m := tui.NewCommandBarModel(tui.DefaultKeyMap)
	m.SetWidth(120)
	m.SetContext(tui.ContextLogViewer)

	view := m.View()

	for _, want := range []string{"j/k", "scroll", "e", "export", "tab", "agents", "?", "help", "q", "quit"} {
		if !strings.Contains(view, want) {
			t.Errorf("log-viewer view missing %q\nfull view: %q", want, view)
		}
	}

	// Agent-list specific hints must NOT appear.
	for _, absent := range []string{"stop", "restart", "kill", "filter"} {
		if strings.Contains(view, absent) {
			t.Errorf("log-viewer view should not contain %q\nfull view: %q", absent, view)
		}
	}
}

func TestCommandBar_ModalContext(t *testing.T) {
	m := tui.NewCommandBarModel(tui.DefaultKeyMap)
	m.SetWidth(120)
	m.SetContext(tui.ContextModal)

	view := m.View()

	for _, want := range []string{"enter", "confirm", "esc", "cancel"} {
		if !strings.Contains(view, want) {
			t.Errorf("modal view missing %q\nfull view: %q", want, view)
		}
	}
}

func TestCommandBar_StatusMessage(t *testing.T) {
	m := tui.NewCommandBarModel(tui.DefaultKeyMap)
	m.SetWidth(120)

	m2, _ := m.Update(tui.StatusMsg{Text: "Agent stopped", IsError: false})

	view := m2.View()
	if !strings.Contains(view, "Agent stopped") {
		t.Errorf("expected status message in view, got: %q", view)
	}
}

func TestCommandBar_StatusMessageError(t *testing.T) {
	m := tui.NewCommandBarModel(tui.DefaultKeyMap)
	m.SetWidth(120)

	m2, _ := m.Update(tui.StatusMsg{Text: "Kill failed", IsError: true})

	view := m2.View()
	if !strings.Contains(view, "Kill failed") {
		t.Errorf("expected error message in view, got: %q", view)
	}
}

func TestCommandBar_StatusMessageAutoClear(t *testing.T) {
	m := tui.NewCommandBarModel(tui.DefaultKeyMap)
	m.SetWidth(120)

	// Show a status message.
	m2, _ := m.Update(tui.StatusMsg{Text: "Done", IsError: false})

	// Simulate the auto-clear tick arriving.
	m3, _ := m2.Update(tui.ClearStatusMsg{})

	// The message should be cleared; keybinding hints should now show.
	view := m3.View()
	if strings.Contains(view, "Done") {
		t.Errorf("status message should have been cleared, got: %q", view)
	}
}

func TestCommandBar_WidthResize(t *testing.T) {
	m := tui.NewCommandBarModel(tui.DefaultKeyMap)

	// Default width is 0 - no panic.
	_ = m.View()

	m2, _ := m.Update(tea.WindowSizeMsg{Width: 200, Height: 40})
	_ = m2.View()
}
