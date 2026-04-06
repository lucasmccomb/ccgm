// agentlist.go implements the scrollable agent list panel for the left pane.
package tui

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// AgentSelectedMsg is emitted when the user presses enter on an agent row.
type AgentSelectedMsg struct {
	AgentID string
}

// AgentListUpdatedMsg carries a fresh snapshot of agent list items to the model.
type AgentListUpdatedMsg struct {
	Agents []AgentListItem
}

// AgentListItem is the display representation of a single managed agent.
type AgentListItem struct {
	ID           string
	Name         string
	Status       types.AgentStatus
	Uptime       time.Duration
	PID          int
	RestartCount int
}

// AgentListModel is the Bubble Tea component for the agent list panel.
type AgentListModel struct {
	agents    []AgentListItem
	cursor    int
	filter    string
	filtering bool
	width     int
	height    int
	focused   bool
}

// NewAgentListModel returns an empty, unfocused agent list model.
func NewAgentListModel() AgentListModel {
	return AgentListModel{}
}

// Init satisfies the tea.Model interface. No I/O needed on startup.
func (m AgentListModel) Init() tea.Cmd {
	return nil
}

// Update handles key input, window resizes, and agent list refreshes.
func (m AgentListModel) Update(msg tea.Msg) (AgentListModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height

	case AgentListUpdatedMsg:
		m.SetAgents(msg.Agents)

	case tea.KeyMsg:
		if m.filtering {
			return m.updateFilter(msg)
		}
		return m.updateNav(msg)
	}
	return m, nil
}

// updateFilter handles key input while the filter input is active.
func (m AgentListModel) updateFilter(msg tea.KeyMsg) (AgentListModel, tea.Cmd) {
	switch msg.String() {
	case "esc":
		m.filtering = false
		m.filter = ""
		m.clampCursor()
	case "backspace":
		if len(m.filter) > 0 {
			m.filter = m.filter[:len(m.filter)-1]
			m.clampCursor()
		}
	default:
		if msg.Type == tea.KeyRunes {
			m.filter += string(msg.Runes)
			m.clampCursor()
		}
	}
	return m, nil
}

// updateNav handles key input during normal (non-filter) navigation.
func (m AgentListModel) updateNav(msg tea.KeyMsg) (AgentListModel, tea.Cmd) {
	visible := m.visibleAgents()

	switch msg.String() {
	case "k", "up":
		if m.cursor > 0 {
			m.cursor--
		}
	case "j", "down":
		if m.cursor < len(visible)-1 {
			m.cursor++
		}
	case "/":
		m.filtering = true
		m.filter = ""
	case "enter":
		if agent, ok := m.SelectedAgent(); ok {
			return m, func() tea.Msg {
				return AgentSelectedMsg{AgentID: agent.ID}
			}
		}
	}
	return m, nil
}

// View renders the agent list panel as a string.
func (m AgentListModel) View() string {
	visible := m.visibleAgents()

	var sb strings.Builder

	// Title bar
	title := "Agents"
	if m.filter != "" {
		title = fmt.Sprintf("Agents [%s]", m.filter)
	}
	sb.WriteString(TitleStyle.Render(title))
	sb.WriteString("\n")

	// Filter mode prompt
	if m.filtering {
		sb.WriteString(fmt.Sprintf("Filter: %s_\n", m.filter))
	}

	// Empty state
	if len(visible) == 0 {
		if m.filter != "" {
			sb.WriteString("(no agents match filter)\n")
		} else {
			sb.WriteString("(no agents)\n")
		}
		return m.wrapBorder(sb.String())
	}

	// Column header
	header := fmt.Sprintf("%-20s  %-13s  %-8s  %-7s  %-8s",
		"Name", "Status", "Uptime", "PID", "Restarts")
	sb.WriteString(HeaderStyle.Render(header))
	sb.WriteString("\n")

	// Agent rows
	for i, agent := range visible {
		row := fmt.Sprintf("%-20s  %-13s  %-8s  %-7s  %-8s",
			truncate(agent.Name, 20),
			m.renderStatus(agent.Status),
			formatUptime(agent.Uptime),
			formatPID(agent.PID),
			fmt.Sprintf("%d", agent.RestartCount),
		)
		if i == m.cursor {
			sb.WriteString(SelectedStyle.Render(row))
		} else {
			sb.WriteString(row)
		}
		sb.WriteString("\n")
	}

	// Filter count hint
	if m.filter != "" {
		sb.WriteString(fmt.Sprintf("\n%d/%d shown", len(visible), len(m.agents)))
	}

	return m.wrapBorder(sb.String())
}

// SetAgents replaces the agent list and clamps the cursor.
func (m *AgentListModel) SetAgents(agents []AgentListItem) {
	m.agents = agents
	m.clampCursor()
}

// SetSize updates the panel dimensions.
func (m *AgentListModel) SetSize(width, height int) {
	m.width = width
	m.height = height
}

// SetFocused marks the panel as focused or unfocused (affects border color).
func (m *AgentListModel) SetFocused(focused bool) {
	m.focused = focused
}

// SelectedAgent returns the agent under the cursor, if any.
func (m AgentListModel) SelectedAgent() (AgentListItem, bool) {
	visible := m.visibleAgents()
	if len(visible) == 0 || m.cursor < 0 || m.cursor >= len(visible) {
		return AgentListItem{}, false
	}
	return visible[m.cursor], true
}

// Focused reports whether this panel has keyboard focus.
func (m AgentListModel) Focused() bool {
	return m.focused
}

// visibleAgents returns the subset of agents that match the current filter.
func (m AgentListModel) visibleAgents() []AgentListItem {
	if m.filter == "" {
		return m.agents
	}
	lower := strings.ToLower(m.filter)
	var out []AgentListItem
	for _, a := range m.agents {
		if strings.Contains(strings.ToLower(a.Name), lower) {
			out = append(out, a)
		}
	}
	return out
}

// clampCursor keeps the cursor within the bounds of the visible agent list.
func (m *AgentListModel) clampCursor() {
	visible := m.visibleAgents()
	if len(visible) == 0 {
		m.cursor = 0
		return
	}
	if m.cursor >= len(visible) {
		m.cursor = len(visible) - 1
	}
	if m.cursor < 0 {
		m.cursor = 0
	}
}

// wrapBorder wraps content in the appropriate border style based on focus.
func (m AgentListModel) wrapBorder(content string) string {
	style := InactiveBorderStyle
	if m.focused {
		style = ActiveBorderStyle
	}
	if m.width > 0 {
		// Subtract 2 for the border characters on each side.
		inner := m.width - 2
		if inner > 0 {
			style = style.Width(inner)
		}
	}
	return style.Render(content)
}

// renderStatus returns a colored status indicator string.
func (m AgentListModel) renderStatus(status types.AgentStatus) string {
	dot := "●"
	switch status {
	case types.StatusRunning:
		return StatusRunning.Render(dot + " running")
	case types.StatusHanging:
		return StatusHanging.Render(dot + " hanging")
	case types.StatusCrashed:
		return StatusCrashed.Render(dot + " crashed")
	case types.StatusStopped:
		return StatusStopped.Render(dot + " stopped")
	case types.StatusRestarting:
		return StatusRestarting.Render(dot + " restarting")
	default:
		return lipgloss.NewStyle().Render(dot + " " + string(status))
	}
}

// formatUptime converts a duration to a human-readable short string.
func formatUptime(d time.Duration) string {
	if d < 0 {
		d = 0
	}
	h := int(d.Hours())
	m := int(d.Minutes()) % 60
	s := int(d.Seconds()) % 60
	if h > 0 {
		return fmt.Sprintf("%dh%02dm", h, m)
	}
	if m > 0 {
		return fmt.Sprintf("%dm%02ds", m, s)
	}
	return fmt.Sprintf("%ds", s)
}

// formatPID returns a dash when the PID is 0 (agent not running).
func formatPID(pid int) string {
	if pid == 0 {
		return "-"
	}
	return fmt.Sprintf("%d", pid)
}

// truncate shortens s to max runes, appending "..." if needed.
func truncate(s string, max int) string {
	runes := []rune(s)
	if len(runes) <= max {
		return s
	}
	if max <= 3 {
		return string(runes[:max])
	}
	return string(runes[:max-3]) + "..."
}
