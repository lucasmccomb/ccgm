package tui_test

import (
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/tui"
)

func TestHelp_InitiallyHidden(t *testing.T) {
	m := tui.NewHelpModel(tui.DefaultKeyMap)
	if m.Visible() {
		t.Error("help overlay should start hidden")
	}
	if m.View() != "" {
		t.Errorf("hidden overlay should render empty string, got %q", m.View())
	}
}

func TestHelp_Toggle(t *testing.T) {
	m := tui.NewHelpModel(tui.DefaultKeyMap)

	m.Toggle()
	if !m.Visible() {
		t.Error("toggle should make overlay visible")
	}

	m.Toggle()
	if m.Visible() {
		t.Error("second toggle should hide overlay")
	}
}

func TestHelp_ViewContainsAllCategories(t *testing.T) {
	m := tui.NewHelpModel(tui.DefaultKeyMap)
	m.SetSize(120, 40)
	m.Toggle()

	view := m.View()

	for _, cat := range []string{"Navigation", "Agent Actions", "Log Actions", "General"} {
		if !strings.Contains(view, cat) {
			t.Errorf("help view missing category %q\nfull view: %q", cat, view)
		}
	}
}

func TestHelp_ViewContainsKeyEntries(t *testing.T) {
	m := tui.NewHelpModel(tui.DefaultKeyMap)
	m.SetSize(120, 40)
	m.Toggle()

	view := m.View()

	for _, entry := range []string{
		"Move down",
		"Move up",
		"Switch panel",
		"Filter agents",
		"New agent",
		"Stop agent",
		"Restart agent",
		"Kill agent",
		"Export logs",
		"Toggle help",
		"Quit",
	} {
		if !strings.Contains(view, entry) {
			t.Errorf("help view missing entry %q\nfull view: %q", entry, view)
		}
	}
}

func TestHelp_DismissWithEscape(t *testing.T) {
	m := tui.NewHelpModel(tui.DefaultKeyMap)
	m.Toggle()
	if !m.Visible() {
		t.Fatal("expected overlay to be visible")
	}

	m2, _ := m.Update(tea.KeyMsg{Type: tea.KeyEsc})
	if m2.Visible() {
		t.Error("escape should dismiss the help overlay")
	}
}

func TestHelp_DismissWithQuestionMark(t *testing.T) {
	m := tui.NewHelpModel(tui.DefaultKeyMap)
	m.Toggle()

	m2, _ := m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'?'}})
	if m2.Visible() {
		t.Error("? should dismiss the help overlay when visible")
	}
}

func TestHelp_UpdateIgnoredWhenHidden(t *testing.T) {
	m := tui.NewHelpModel(tui.DefaultKeyMap)
	// Overlay is hidden; pressing esc should not change visible state.
	m2, _ := m.Update(tea.KeyMsg{Type: tea.KeyEsc})
	if m2.Visible() {
		t.Error("update while hidden should not change visible state")
	}
}

func TestHelp_SetSize(t *testing.T) {
	m := tui.NewHelpModel(tui.DefaultKeyMap)
	m.SetSize(80, 24)
	m.Toggle()
	// Should not panic and should produce a non-empty view.
	view := m.View()
	if view == "" {
		t.Error("expected non-empty view after SetSize and Toggle")
	}
}
