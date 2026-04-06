// launch.go implements the modal form for launching a new agent.
package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/lucasmccomb/ccgm/modules/agent-manager/src/internal/types"
)

// LaunchSubmitMsg is emitted when the user confirms the launch form.
type LaunchSubmitMsg struct {
	Config types.AgentConfig
}

// launchField is an index into LaunchModel.inputs.
const (
	fieldName = iota
	fieldCommand
	fieldWorkDir
	fieldModel
	numFields
)

// LaunchModel is a Bubble Tea component that renders a centered modal form
// for creating a new agent configuration.
type LaunchModel struct {
	inputs  [numFields]textinput.Model
	focused int
	visible bool
	width   int
	height  int
	err     string
}

// NewLaunchModel returns a LaunchModel with all inputs initialized.
func NewLaunchModel() LaunchModel {
	m := LaunchModel{}

	placeholders := [numFields]string{
		"e.g. my-agent",
		"claude",
		"/path/to/workdir",
		"opus (optional)",
	}
	labels := [numFields]string{
		"Name (required)",
		"Command (required)",
		"Working Directory (required)",
		"Model (optional)",
	}

	for i := 0; i < numFields; i++ {
		ti := textinput.New()
		ti.Placeholder = placeholders[i]
		ti.CharLimit = 256
		ti.Width = 50
		ti.Prompt = fmt.Sprintf("%-28s ", labels[i])
		m.inputs[i] = ti
	}

	// Defaults.
	m.inputs[fieldCommand].SetValue("claude")
	return m
}

// Init satisfies tea.Model.
func (m LaunchModel) Init() tea.Cmd {
	return nil
}

// Update handles keyboard events within the launch modal.
func (m LaunchModel) Update(msg tea.Msg) (LaunchModel, tea.Cmd) {
	if !m.visible {
		return m, nil
	}

	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "esc":
			m.visible = false
			m.err = ""
			return m, nil

		case "tab", "down":
			m.err = ""
			m.inputs[m.focused].Blur()
			m.focused = (m.focused + 1) % numFields
			m.inputs[m.focused].Focus()
			return m, textinput.Blink

		case "shift+tab", "up":
			m.err = ""
			m.inputs[m.focused].Blur()
			m.focused = (m.focused - 1 + numFields) % numFields
			m.inputs[m.focused].Focus()
			return m, textinput.Blink

		case "enter":
			if m.focused == numFields-1 {
				// Last field: try to submit.
				return m.trySubmit()
			}
			// Advance to next field.
			m.inputs[m.focused].Blur()
			m.focused++
			m.inputs[m.focused].Focus()
			return m, textinput.Blink
		}
	}

	// Forward key strokes to the focused input.
	var cmd tea.Cmd
	m.inputs[m.focused], cmd = m.inputs[m.focused].Update(msg)
	return m, cmd
}

// View renders the modal as a centered dialog string. Returns "" when hidden.
func (m LaunchModel) View() string {
	if !m.visible {
		return ""
	}

	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("12"))
	errorStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("1"))
	hintStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("243"))
	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("62")).
		Padding(1, 3).
		Background(lipgloss.Color("235"))

	var sb strings.Builder
	sb.WriteString(titleStyle.Render("Launch New Agent"))
	sb.WriteString("\n\n")

	for i := 0; i < numFields; i++ {
		sb.WriteString(m.inputs[i].View())
		sb.WriteString("\n")
	}

	if m.err != "" {
		sb.WriteString("\n")
		sb.WriteString(errorStyle.Render(m.err))
		sb.WriteString("\n")
	}

	sb.WriteString("\n")
	sb.WriteString(hintStyle.Render("tab/↓↑ navigate   enter confirm   esc cancel"))

	return boxStyle.Render(sb.String())
}

// SetVisible shows or hides the modal.
func (m *LaunchModel) SetVisible(v bool) {
	m.visible = v
	if v {
		m.inputs[m.focused].Focus()
	} else {
		m.inputs[m.focused].Blur()
	}
}

// Visible reports whether the modal is currently shown.
func (m LaunchModel) Visible() bool {
	return m.visible
}

// SetSize stores terminal dimensions (used by the parent to center the overlay).
func (m *LaunchModel) SetSize(w, h int) {
	m.width = w
	m.height = h
}

// Reset clears all input fields and positions focus on the Name field.
func (m *LaunchModel) Reset() {
	for i := 0; i < numFields; i++ {
		m.inputs[i].SetValue("")
		m.inputs[i].Blur()
	}
	m.inputs[fieldCommand].SetValue("claude")
	m.focused = fieldName
	m.inputs[m.focused].Focus()
	m.err = ""
}

// trySubmit validates inputs and returns LaunchSubmitMsg if valid.
func (m LaunchModel) trySubmit() (LaunchModel, tea.Cmd) {
	name := strings.TrimSpace(m.inputs[fieldName].Value())
	command := strings.TrimSpace(m.inputs[fieldCommand].Value())
	workDir := strings.TrimSpace(m.inputs[fieldWorkDir].Value())
	modelVal := strings.TrimSpace(m.inputs[fieldModel].Value())

	if name == "" {
		m.err = "Name is required"
		m.focused = fieldName
		m.inputs[m.focused].Focus()
		return m, nil
	}
	if command == "" {
		m.err = "Command is required"
		m.focused = fieldCommand
		m.inputs[m.focused].Focus()
		return m, nil
	}
	if workDir == "" {
		m.err = "Working Directory is required"
		m.focused = fieldWorkDir
		m.inputs[m.focused].Focus()
		return m, nil
	}

	// Generate a stable ID from the name.
	id := sanitizeID(name)

	cfg := types.AgentConfig{
		ID:         id,
		Name:       name,
		Command:    command,
		WorkingDir: workDir,
		Model:      modelVal,
		RestartPolicy: types.RestartPolicy{
			Type: "never",
		},
	}

	if err := cfg.Validate(); err != nil {
		m.err = err.Error()
		return m, nil
	}

	m.visible = false
	m.err = ""
	return m, func() tea.Msg {
		return LaunchSubmitMsg{Config: cfg}
	}
}

// sanitizeID converts a display name to a valid agent ID by lowercasing and
// replacing invalid characters with hyphens.
func sanitizeID(name string) string {
	name = strings.ToLower(name)
	var sb strings.Builder
	for _, r := range name {
		switch {
		case r >= 'a' && r <= 'z':
			sb.WriteRune(r)
		case r >= '0' && r <= '9':
			sb.WriteRune(r)
		case r == '-' || r == '_':
			sb.WriteRune(r)
		default:
			sb.WriteRune('-')
		}
	}
	id := strings.Trim(sb.String(), "-")
	if id == "" {
		id = "agent"
	}
	return id
}
