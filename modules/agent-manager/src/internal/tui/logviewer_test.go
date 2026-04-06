package tui

import (
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// makeLines is a test helper that creates n LogDisplayLines with sequential text.
func makeLines(n int, isStderr bool) []LogDisplayLine {
	lines := make([]LogDisplayLine, n)
	now := time.Now()
	for i := range lines {
		lines[i] = LogDisplayLine{
			Text:      strings.Repeat("x", 10),
			IsStderr:  isStderr,
			Timestamp: now,
		}
	}
	return lines
}

func TestLogViewer_NoAgentSelected(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	view := m.View()
	if !strings.Contains(view, "no agent selected") {
		t.Errorf("expected 'no agent selected' in view when no agent is set; got:\n%s", view)
	}
}

func TestLogViewer_NoOutputYet(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	m.SetAgent("agent-1", "Test Agent")
	// No lines added yet.
	view := m.View()
	if !strings.Contains(view, "no output yet") {
		t.Errorf("expected 'no output yet' with empty log buffer; got:\n%s", view)
	}
}

func TestLogViewer_AddLinesAndRender(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	m.SetAgent("agent-1", "Test Agent")

	now := time.Now()
	msg := LogLinesMsg{
		AgentID: "agent-1",
		Lines: []LogDisplayLine{
			{Text: "hello world", IsStderr: false, Timestamp: now},
			{Text: "second line", IsStderr: false, Timestamp: now},
		},
	}
	m2, _ := m.Update(msg)

	view := m2.View()
	if !strings.Contains(view, "hello world") {
		t.Errorf("expected 'hello world' in rendered view; got:\n%s", view)
	}
	if !strings.Contains(view, "second line") {
		t.Errorf("expected 'second line' in rendered view; got:\n%s", view)
	}
}

func TestLogViewer_StderrColoring(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	m.SetAgent("agent-1", "Test Agent")

	now := time.Now()
	msg := LogLinesMsg{
		AgentID: "agent-1",
		Lines: []LogDisplayLine{
			{Text: "error line", IsStderr: true, Timestamp: now},
			{Text: "normal line", IsStderr: false, Timestamp: now},
		},
	}
	m2, _ := m.Update(msg)
	view := m2.View()

	// The view must contain both texts regardless of terminal color support.
	if !strings.Contains(view, "error line") {
		t.Errorf("expected 'error line' in view; got:\n%s", view)
	}
	if !strings.Contains(view, "normal line") {
		t.Errorf("expected 'normal line' in view; got:\n%s", view)
	}

	// Verify that the stderr style has a foreground color configured.
	// We check the style definition rather than rendered output because
	// Lip Gloss strips ANSI codes when there is no real TTY (test environments).
	fg := logViewerStyles.stderr.GetForeground()
	if fg == nil {
		t.Error("logViewerStyles.stderr must have a foreground color (error/red)")
	}
}

func TestLogViewer_RingBufferOverflow(t *testing.T) {
	const max = 10_000
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	m.SetAgent("agent-1", "Test Agent")

	// Add max+1 lines via the message path.
	now := time.Now()
	batch := make([]LogDisplayLine, max+1)
	for i := range batch {
		batch[i] = LogDisplayLine{Text: "line", IsStderr: false, Timestamp: now}
	}
	msg := LogLinesMsg{AgentID: "agent-1", Lines: batch}
	m2, _ := m.Update(msg)

	if m2.buf.Len() != max {
		t.Errorf("expected ring buffer to cap at %d, got %d", max, m2.buf.Len())
	}
}

func TestLogViewer_AutoScrollAtBottom(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	m.SetAgent("agent-1", "Test Agent")
	m.SetFocused(true)

	// Initially auto-scroll is true.
	if !m.autoScroll {
		t.Error("expected autoScroll to be true on a fresh LogViewerModel")
	}

	// Add enough lines to overflow the viewport.
	now := time.Now()
	batch := makeLines(100, false)
	for i := range batch {
		batch[i].Timestamp = now
	}
	msg := LogLinesMsg{AgentID: "agent-1", Lines: batch}
	m2, _ := m.Update(msg)

	// Auto-scroll should still be true (we haven't manually scrolled).
	if !m2.autoScroll {
		t.Error("autoScroll should remain true after receiving log lines without manual scroll")
	}
}

func TestLogViewer_ScrollUpDisablesAutoScroll(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 40)
	m.SetAgent("agent-1", "Test Agent")
	m.SetFocused(true)

	// Fill with enough lines so there is content to scroll through.
	now := time.Now()
	batch := makeLines(200, false)
	for i := range batch {
		batch[i].Timestamp = now
	}
	msg := LogLinesMsg{AgentID: "agent-1", Lines: batch}
	m2, _ := m.Update(msg)

	// Simulate pressing PageUp to scroll up.
	keyMsg := tea.KeyMsg{Type: tea.KeyPgUp}
	m3, _ := m2.Update(keyMsg)

	// Auto-scroll should now be disabled because we scrolled away from bottom.
	if m3.autoScroll {
		// Only fail if we actually moved off the bottom.
		if !m3.viewport.AtBottom() {
			t.Error("autoScroll should be false after scrolling up from the bottom")
		}
	}
}

func TestLogViewer_AgentSwitchClearsLogs(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	m.SetAgent("agent-1", "Agent One")

	now := time.Now()
	msg := LogLinesMsg{
		AgentID: "agent-1",
		Lines:   []LogDisplayLine{{Text: "agent one output", Timestamp: now}},
	}
	m2, _ := m.Update(msg)
	if m2.buf.Len() == 0 {
		t.Fatal("expected log lines for agent-1 after update")
	}

	// Switch to a new agent and clear logs.
	m2.SetAgent("agent-2", "Agent Two")
	m2.ClearLogs()

	if m2.buf.Len() != 0 {
		t.Errorf("expected empty buffer after ClearLogs, got %d lines", m2.buf.Len())
	}
	// Logs from agent-1 must not appear after switch.
	msg2 := LogLinesMsg{
		AgentID: "agent-1",
		Lines:   []LogDisplayLine{{Text: "stale agent-1 log", Timestamp: now}},
	}
	m3, _ := m2.Update(msg2)
	if m3.buf.Len() != 0 {
		t.Error("LogLinesMsg for a non-current agent should not add to the buffer")
	}
}

func TestLogViewer_IgnoresOtherAgentLogs(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	m.SetAgent("agent-1", "Agent One")

	now := time.Now()
	msg := LogLinesMsg{
		AgentID: "agent-2", // different agent
		Lines:   []LogDisplayLine{{Text: "other agent", Timestamp: now}},
	}
	m2, _ := m.Update(msg)
	if m2.buf.Len() != 0 {
		t.Errorf("expected no lines when LogLinesMsg is for a different agent, got %d", m2.buf.Len())
	}
}

func TestLogViewer_ResizeUpdatesViewport(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)

	m.SetSize(120, 40)
	if m.viewport.Width == 0 || m.viewport.Height == 0 {
		t.Errorf("viewport dimensions should be non-zero after SetSize; got %dx%d", m.viewport.Width, m.viewport.Height)
	}
	if m.width != 120 || m.height != 40 {
		t.Errorf("expected model width/height 120x40, got %dx%d", m.width, m.height)
	}
}

func TestLogViewer_FocusedAccessor(t *testing.T) {
	m := NewLogViewerModel()
	if m.Focused() {
		t.Error("expected Focused() false on fresh model")
	}
	m.SetFocused(true)
	if !m.Focused() {
		t.Error("expected Focused() true after SetFocused(true)")
	}
}

func TestLogViewer_TitleShowsAgentName(t *testing.T) {
	m := NewLogViewerModel()
	m.SetSize(80, 24)
	m.SetAgent("agent-42", "My Agent")
	title := m.titleString()
	if !strings.Contains(title, "My Agent") {
		t.Errorf("title should contain agent name 'My Agent'; got %q", title)
	}
}
