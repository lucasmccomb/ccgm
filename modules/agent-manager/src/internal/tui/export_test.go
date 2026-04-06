// export_test.go exposes internal AppModel methods for white-box testing.
// This file is compiled only during test runs (the _test.go suffix convention
// does not apply to files without _test in the package declaration, but placing
// helpers here keeps production code clean).
package tui

import tea "github.com/charmbracelet/bubbletea"

// AgentListFocused reports whether the agent list currently has focus.
func (m AppModel) AgentListFocused() bool {
	return m.agentList.Focused()
}

// LogViewerFocused reports whether the log viewer currently has focus.
func (m AppModel) LogViewerFocused() bool {
	return m.logViewer.Focused()
}

// PressTab simulates a Tab key press and returns the updated model.
func (m AppModel) PressTab() AppModel {
	msg := tea.KeyMsg{Type: tea.KeyTab}
	next, _ := m.Update(msg)
	return next.(AppModel)
}

// Resize simulates a window resize and returns the updated model.
func (m AppModel) Resize(width, height int) AppModel {
	msg := tea.WindowSizeMsg{Width: width, Height: height}
	next, _ := m.Update(msg)
	return next.(AppModel)
}

// AgentListSize returns the current (width, height) of the agent list panel.
func (m AppModel) AgentListSize() (int, int) {
	return m.agentList.width, m.agentList.height
}

// LogViewerSize returns the current (width, height) of the log viewer panel.
func (m AppModel) LogViewerSize() (int, int) {
	return m.logViewer.width, m.logViewer.height
}
