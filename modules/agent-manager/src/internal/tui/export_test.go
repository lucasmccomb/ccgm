// export_test.go exposes internal AppModel methods for white-box testing.
package tui

import tea "github.com/charmbracelet/bubbletea"

// AgentListFocused reports whether the agent list currently has focus.
func (m AppModel) AgentListFocused() bool {
	return m.agentList.Focused()
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
