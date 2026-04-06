// detail.go implements the modal overlay that shows full agent details.
package tui

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/agent"
	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// AgentDetailInfo contains the data shown in the detail modal.
type AgentDetailInfo struct {
	Config       types.AgentConfig
	Status       types.AgentStatus
	PID          int
	Uptime       time.Duration
	RestartCount int
	ExitCode     int
}

// DetailModel is a Bubble Tea component that renders a centered modal with
// complete agent configuration and runtime state.
type DetailModel struct {
	info    *AgentDetailInfo
	visible bool
	width   int
	height  int
}

// NewDetailModel returns a hidden DetailModel.
func NewDetailModel() DetailModel {
	return DetailModel{}
}

// Init satisfies tea.Model.
func (m DetailModel) Init() tea.Cmd {
	return nil
}

// Update handles keyboard events (esc / enter / ? close the modal).
func (m DetailModel) Update(msg tea.Msg) (DetailModel, tea.Cmd) {
	if !m.visible {
		return m, nil
	}
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "esc", "enter", "d", "q":
			m.visible = false
		}
	}
	return m, nil
}

// View renders the detail modal. Returns "" when hidden.
func (m DetailModel) View() string {
	if !m.visible || m.info == nil {
		return ""
	}

	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("12"))
	labelStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("252"))
	valueStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("15"))
	sectionStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("11")).MarginTop(1)
	hintStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("243"))
	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("62")).
		Padding(1, 3).
		Background(lipgloss.Color("235"))

	info := m.info
	var sb strings.Builder

	sb.WriteString(titleStyle.Render(fmt.Sprintf("Agent: %s", info.Config.Name)))
	sb.WriteString("\n")

	sb.WriteString(sectionStyle.Render("Runtime"))
	sb.WriteString("\n")
	sb.WriteString(row(labelStyle, valueStyle, "Status", string(info.Status)))
	sb.WriteString(row(labelStyle, valueStyle, "PID", pidStr(info.PID)))
	sb.WriteString(row(labelStyle, valueStyle, "Uptime", formatUptime(info.Uptime)))
	sb.WriteString(row(labelStyle, valueStyle, "Restarts", fmt.Sprintf("%d", info.RestartCount)))
	sb.WriteString(row(labelStyle, valueStyle, "Exit Code", fmt.Sprintf("%d", info.ExitCode)))

	sb.WriteString(sectionStyle.Render("Configuration"))
	sb.WriteString("\n")
	sb.WriteString(row(labelStyle, valueStyle, "ID", info.Config.ID))
	sb.WriteString(row(labelStyle, valueStyle, "Command", info.Config.Command))
	if len(info.Config.Args) > 0 {
		sb.WriteString(row(labelStyle, valueStyle, "Args", strings.Join(info.Config.Args, " ")))
	}
	sb.WriteString(row(labelStyle, valueStyle, "Working Dir", info.Config.WorkingDir))
	if info.Config.Model != "" {
		sb.WriteString(row(labelStyle, valueStyle, "Model", info.Config.Model))
	}

	sb.WriteString(sectionStyle.Render("Restart Policy"))
	sb.WriteString("\n")
	sb.WriteString(row(labelStyle, valueStyle, "Type", info.Config.RestartPolicy.Type))
	if info.Config.RestartPolicy.MaxRetries > 0 {
		sb.WriteString(row(labelStyle, valueStyle, "Max Retries",
			fmt.Sprintf("%d", info.Config.RestartPolicy.MaxRetries)))
	}
	if info.Config.RestartPolicy.BaseDelay > 0 {
		sb.WriteString(row(labelStyle, valueStyle, "Base Delay",
			info.Config.RestartPolicy.BaseDelay.String()))
	}

	sb.WriteString("\n")
	sb.WriteString(hintStyle.Render("esc / enter  close"))

	return boxStyle.Render(sb.String())
}

// SetAgent populates the modal with data from a ManagedAgent.
func (m *DetailModel) SetAgent(ma *agent.ManagedAgent) {
	now := time.Now()
	uptime := time.Duration(0)
	if ma.State.Status == types.StatusRunning && !ma.State.StartedAt.IsZero() {
		uptime = now.Sub(ma.State.StartedAt)
	}
	m.info = &AgentDetailInfo{
		Config:       ma.Config,
		Status:       ma.State.Status,
		PID:          ma.State.PID,
		Uptime:       uptime,
		RestartCount: ma.State.RestartCount,
		ExitCode:     ma.State.ExitCode,
	}
	m.visible = true
}

// SetVisible shows or hides the modal.
func (m *DetailModel) SetVisible(v bool) {
	m.visible = v
}

// Visible reports whether the modal is currently shown.
func (m DetailModel) Visible() bool {
	return m.visible
}

// SetSize stores terminal dimensions for future use.
func (m *DetailModel) SetSize(w, h int) {
	m.width = w
	m.height = h
}

// row renders one label/value pair.
func row(labelStyle, valueStyle lipgloss.Style, label, value string) string {
	return fmt.Sprintf("  %s  %s\n",
		labelStyle.Render(padRight(label+":", 18)),
		valueStyle.Render(value),
	)
}

// padRight right-pads s to width with spaces.
func padRight(s string, width int) string {
	if len(s) >= width {
		return s
	}
	return s + strings.Repeat(" ", width-len(s))
}

// pidStr formats a PID or returns "-" when zero.
func pidStr(pid int) string {
	if pid == 0 {
		return "-"
	}
	return fmt.Sprintf("%d", pid)
}
