package tui

import (
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// helpers

func makeItem(id, name string, status types.AgentStatus, pid int) AgentListItem {
	return AgentListItem{
		ID:           id,
		Name:         name,
		Status:       status,
		PID:          pid,
		Uptime:       10 * time.Second,
		RestartCount: 0,
	}
}

func pressKey(m AgentListModel, key string) (AgentListModel, tea.Cmd) {
	return m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune(key)})
}

func pressSpecial(m AgentListModel, keyType tea.KeyType) (AgentListModel, tea.Cmd) {
	return m.Update(tea.KeyMsg{Type: keyType})
}

// --- rendering tests ---

func TestView_NoAgents(t *testing.T) {
	m := NewAgentListModel()
	view := m.View()
	if !strings.Contains(view, "(no agents)") {
		t.Errorf("expected '(no agents)' in view, got:\n%s", view)
	}
}

func TestView_ShowsAgentNames(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{
		makeItem("a1", "worker-alpha", types.StatusRunning, 1001),
		makeItem("a2", "worker-beta", types.StatusCrashed, 0),
	})
	view := m.View()
	if !strings.Contains(view, "worker-alpha") {
		t.Errorf("expected 'worker-alpha' in view, got:\n%s", view)
	}
	if !strings.Contains(view, "worker-beta") {
		t.Errorf("expected 'worker-beta' in view, got:\n%s", view)
	}
}

func TestView_AllStatuses(t *testing.T) {
	statuses := []types.AgentStatus{
		types.StatusRunning,
		types.StatusHanging,
		types.StatusCrashed,
		types.StatusStopped,
		types.StatusRestarting,
	}
	for _, status := range statuses {
		m := NewAgentListModel()
		m.SetAgents([]AgentListItem{makeItem("a1", "agent", status, 100)})
		view := m.View()
		// Each status name should appear somewhere in the rendered view.
		if !strings.Contains(view, string(status)) {
			t.Errorf("status %q not found in view:\n%s", status, view)
		}
	}
}

func TestView_ShowsHeader(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{makeItem("a1", "x", types.StatusRunning, 1)})
	view := m.View()
	if !strings.Contains(view, "Name") {
		t.Errorf("expected 'Name' column header in view, got:\n%s", view)
	}
}

func TestView_EmptyFilter(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{makeItem("a1", "alpha", types.StatusRunning, 1)})
	// Activate filter, type something that matches nothing.
	m, _ = pressKey(m, "/")
	// Now we are in filter mode
	for _, ch := range "zzz" {
		m.filter += string(ch)
	}
	view := m.View()
	if !strings.Contains(view, "no agents match filter") {
		t.Errorf("expected 'no agents match filter', got:\n%s", view)
	}
}

// --- navigation tests ---

func TestNavigation_JDown(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{
		makeItem("a1", "alpha", types.StatusRunning, 1),
		makeItem("a2", "beta", types.StatusRunning, 2),
		makeItem("a3", "gamma", types.StatusRunning, 3),
	})
	if m.cursor != 0 {
		t.Fatalf("expected cursor at 0, got %d", m.cursor)
	}
	m, _ = pressKey(m, "j")
	if m.cursor != 1 {
		t.Errorf("expected cursor at 1 after j, got %d", m.cursor)
	}
	m, _ = pressKey(m, "j")
	if m.cursor != 2 {
		t.Errorf("expected cursor at 2 after second j, got %d", m.cursor)
	}
	// Should not go past end
	m, _ = pressKey(m, "j")
	if m.cursor != 2 {
		t.Errorf("expected cursor to stay at 2 (end of list), got %d", m.cursor)
	}
}

func TestNavigation_KUp(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{
		makeItem("a1", "alpha", types.StatusRunning, 1),
		makeItem("a2", "beta", types.StatusRunning, 2),
	})
	m.cursor = 1
	m, _ = pressKey(m, "k")
	if m.cursor != 0 {
		t.Errorf("expected cursor at 0 after k, got %d", m.cursor)
	}
	// Should not go below 0
	m, _ = pressKey(m, "k")
	if m.cursor != 0 {
		t.Errorf("expected cursor to stay at 0, got %d", m.cursor)
	}
}

func TestNavigation_ArrowKeys(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{
		makeItem("a1", "alpha", types.StatusRunning, 1),
		makeItem("a2", "beta", types.StatusRunning, 2),
	})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyDown})
	if m.cursor != 1 {
		t.Errorf("expected cursor 1 after Down, got %d", m.cursor)
	}
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyUp})
	if m.cursor != 0 {
		t.Errorf("expected cursor 0 after Up, got %d", m.cursor)
	}
}

// --- filter tests ---

func TestFilter_EnterAndExit(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{makeItem("a1", "alpha", types.StatusRunning, 1)})

	if m.filtering {
		t.Fatal("should not be filtering initially")
	}

	// Enter filter mode via /
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("/")})
	if !m.filtering {
		t.Fatal("expected filtering=true after /")
	}

	// Type some characters
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("al")})
	if m.filter != "al" {
		t.Errorf("expected filter='al', got %q", m.filter)
	}

	// Escape exits filter mode and clears filter
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEsc})
	if m.filtering {
		t.Error("expected filtering=false after Esc")
	}
	if m.filter != "" {
		t.Errorf("expected filter cleared after Esc, got %q", m.filter)
	}
}

func TestFilter_Narrows(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{
		makeItem("a1", "alpha", types.StatusRunning, 1),
		makeItem("a2", "beta", types.StatusRunning, 2),
		makeItem("a3", "alpine", types.StatusRunning, 3),
	})

	m.filtering = true
	m.filter = "al"

	visible := m.visibleAgents()
	if len(visible) != 2 {
		t.Errorf("expected 2 visible agents with filter 'al', got %d", len(visible))
	}
	names := map[string]bool{}
	for _, a := range visible {
		names[a.Name] = true
	}
	if !names["alpha"] {
		t.Error("expected 'alpha' in filtered results")
	}
	if !names["alpine"] {
		t.Error("expected 'alpine' in filtered results")
	}
	if names["beta"] {
		t.Error("did not expect 'beta' in filtered results")
	}
}

func TestFilter_CaseInsensitive(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{
		makeItem("a1", "Worker-Alpha", types.StatusRunning, 1),
	})
	m.filtering = true
	m.filter = "worker"
	visible := m.visibleAgents()
	if len(visible) != 1 {
		t.Errorf("expected 1 result for case-insensitive filter, got %d", len(visible))
	}
}

func TestFilter_Backspace(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{makeItem("a1", "alpha", types.StatusRunning, 1)})
	m.filtering = true
	m.filter = "alp"

	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyBackspace})
	if m.filter != "al" {
		t.Errorf("expected filter='al' after backspace, got %q", m.filter)
	}
}

// --- SelectedAgent tests ---

func TestSelectedAgent_Empty(t *testing.T) {
	m := NewAgentListModel()
	_, ok := m.SelectedAgent()
	if ok {
		t.Error("expected SelectedAgent to return false for empty list")
	}
}

func TestSelectedAgent_ReturnsCorrect(t *testing.T) {
	m := NewAgentListModel()
	items := []AgentListItem{
		makeItem("a1", "alpha", types.StatusRunning, 1),
		makeItem("a2", "beta", types.StatusStopped, 0),
	}
	m.SetAgents(items)
	m.cursor = 1

	agent, ok := m.SelectedAgent()
	if !ok {
		t.Fatal("expected SelectedAgent to return true")
	}
	if agent.ID != "a2" {
		t.Errorf("expected agent ID 'a2', got %q", agent.ID)
	}
}

func TestSelectedAgent_EnterEmitsMsg(t *testing.T) {
	m := NewAgentListModel()
	m.SetAgents([]AgentListItem{makeItem("a1", "alpha", types.StatusRunning, 1)})

	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyEnter})
	if cmd == nil {
		t.Fatal("expected a command from enter key, got nil")
	}
	msg := cmd()
	sel, ok := msg.(AgentSelectedMsg)
	if !ok {
		t.Fatalf("expected AgentSelectedMsg, got %T", msg)
	}
	if sel.AgentID != "a1" {
		t.Errorf("expected AgentID 'a1', got %q", sel.AgentID)
	}
}

// --- resize tests ---

func TestSetSize(t *testing.T) {
	m := NewAgentListModel()
	m.SetSize(100, 40)
	if m.width != 100 || m.height != 40 {
		t.Errorf("expected width=100 height=40, got %d %d", m.width, m.height)
	}
}

func TestWindowSizeMsg(t *testing.T) {
	m := NewAgentListModel()
	m, _ = m.Update(tea.WindowSizeMsg{Width: 80, Height: 24})
	if m.width != 80 || m.height != 24 {
		t.Errorf("expected width=80 height=24 after WindowSizeMsg, got %d %d", m.width, m.height)
	}
}

func TestAgentListUpdatedMsg(t *testing.T) {
	m := NewAgentListModel()
	msg := AgentListUpdatedMsg{
		Agents: []AgentListItem{makeItem("a1", "alpha", types.StatusRunning, 1)},
	}
	m, _ = m.Update(msg)
	if len(m.agents) != 1 {
		t.Errorf("expected 1 agent after AgentListUpdatedMsg, got %d", len(m.agents))
	}
}

// --- focused border test ---

func TestFocused(t *testing.T) {
	m := NewAgentListModel()
	if m.Focused() {
		t.Error("expected unfocused initially")
	}
	m.SetFocused(true)
	if !m.Focused() {
		t.Error("expected focused after SetFocused(true)")
	}
}

// --- format helpers ---

func TestFormatUptime(t *testing.T) {
	cases := []struct {
		d    time.Duration
		want string
	}{
		{45 * time.Second, "45s"},
		{90 * time.Second, "1m30s"},
		{3700 * time.Second, "1h01m"},
	}
	for _, c := range cases {
		got := formatUptime(c.d)
		if got != c.want {
			t.Errorf("formatUptime(%v) = %q, want %q", c.d, got, c.want)
		}
	}
}

func TestFormatPID(t *testing.T) {
	if formatPID(0) != "-" {
		t.Error("expected '-' for PID 0")
	}
	if formatPID(1234) != "1234" {
		t.Errorf("expected '1234', got %q", formatPID(1234))
	}
}

func TestTruncate(t *testing.T) {
	if truncate("hello", 10) != "hello" {
		t.Error("short string should not be truncated")
	}
	if truncate("hello world", 8) != "hello..." {
		t.Errorf("expected 'hello...', got %q", truncate("hello world", 8))
	}
}
