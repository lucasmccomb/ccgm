// agentlist.go implements the agent list panel for the dashboard.
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

// Init satisfies the tea.Model interface.
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

// View renders the agent list panel.
func (m AgentListModel) View() string {
	visible := m.visibleAgents()
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("243"))
	filterStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Bold(true)

	var sb strings.Builder

	// Title
	sb.WriteString(TitleStyle.Render("Agents"))
	if len(m.agents) > 0 {
		sb.WriteString(dimStyle.Render(fmt.Sprintf("  %d active", len(m.agents))))
	}
	sb.WriteString("\n\n")

	// Filter
	if m.filtering {
		sb.WriteString(filterStyle.Render("  / " + m.filter + "█"))
		sb.WriteString("\n\n")
	}

	// Empty state
	if len(visible) == 0 {
		if m.filter != "" {
			sb.WriteString(dimStyle.Render("  (no agents match filter)"))
		} else {
			sb.WriteString(dimStyle.Render("  (no agents)"))
			sb.WriteString("\n\n")
			sb.WriteString(dimStyle.Render("  Press n to launch a new agent"))
		}
		sb.WriteString("\n")
		return m.wrapBorder(sb.String())
	}

	// Agent rows - card-style, one agent per block.
	for i, a := range visible {
		if i > 0 {
			sb.WriteString("\n")
		}

		// Status indicator and name
		statusDot, statusColor := statusIndicator(a.Status)
		nameStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("252"))
		if i == m.cursor {
			nameStyle = nameStyle.Foreground(lipgloss.Color("62"))
		}

		cursor := "  "
		if i == m.cursor {
			cursor = "▸ "
		}

		sb.WriteString(cursor)
		sb.WriteString(statusColor.Render(statusDot))
		sb.WriteString(" ")
		sb.WriteString(nameStyle.Render(a.Name))
		sb.WriteString("\n")

		// Details line
		details := dimStyle.Render(fmt.Sprintf("    %s  %s",
			statusLabel(a.Status),
			formatUptime(a.Uptime),
		))
		sb.WriteString(details)
		sb.WriteString("\n")
	}

	// Filter count
	if m.filter != "" {
		sb.WriteString(dimStyle.Render(fmt.Sprintf("\n  %d/%d shown", len(visible), len(m.agents))))
		sb.WriteString("\n")
	}

	return m.wrapBorder(sb.String())
}

// SetAgents replaces the agent list.
func (m *AgentListModel) SetAgents(agents []AgentListItem) {
	m.agents = agents
	m.clampCursor()
}

// SetSize updates the panel dimensions.
func (m *AgentListModel) SetSize(width, height int) {
	m.width = width
	m.height = height
}

// SetFocused marks the panel as focused or unfocused.
func (m *AgentListModel) SetFocused(focused bool) {
	m.focused = focused
}

// SelectedAgent returns the agent under the cursor.
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

func (m AgentListModel) wrapBorder(content string) string {
	style := InactiveBorderStyle
	if m.focused {
		style = ActiveBorderStyle
	}
	if m.width > 0 {
		inner := m.width - 2
		if inner > 0 {
			style = style.Width(inner)
		}
	}
	if m.height > 0 {
		inner := m.height - 2
		if inner > 0 {
			style = style.Height(inner)
		}
	}
	return style.Render(content)
}

// statusIndicator returns a colored dot for the agent's status.
func statusIndicator(status types.AgentStatus) (string, lipgloss.Style) {
	switch status {
	case types.StatusRunning:
		return "●", StatusRunning
	case types.StatusCrashed:
		return "●", StatusCrashed
	case types.StatusStopped:
		return "○", StatusStopped
	case types.StatusRestarting:
		return "◐", StatusRestarting
	default:
		// Treat hanging and any unknown status as running.
		return "●", StatusRunning
	}
}

// statusLabel returns a human-readable label for the status.
func statusLabel(status types.AgentStatus) string {
	switch status {
	case types.StatusRunning, types.StatusHanging:
		return "running"
	case types.StatusCrashed:
		return "crashed"
	case types.StatusStopped:
		return "stopped"
	case types.StatusRestarting:
		return "restarting"
	default:
		return string(status)
	}
}

func formatUptime(d time.Duration) string {
	if d <= 0 {
		return ""
	}
	h := int(d.Hours())
	m := int(d.Minutes()) % 60
	s := int(d.Seconds()) % 60
	if h > 0 {
		return fmt.Sprintf("%dh %02dm", h, m)
	}
	if m > 0 {
		return fmt.Sprintf("%dm %02ds", m, s)
	}
	return fmt.Sprintf("%ds", s)
}

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
